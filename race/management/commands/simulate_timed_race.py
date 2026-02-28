"""
Timed race simulator — exercises the full stack via actual endpoints.

Three asyncio agents share a Coordinator:

  director   — race lifecycle (pre-race check, start, end, penalties) via ORM
  decoder    — transponder crossings via WebSocket /ws/timing/ (HMAC signed)
  pit_lane   — driver changes via DRF token HTTP endpoints

Constraints:
  • Requires a running round with confirmed RaceTransponderAssignments.
  • Does NOT modify models.py or any core system file.
  • Decoder talks to the live TimingConsumer through channels.testing —
    no external server needed, full consumer code path exercised.
  • Pit-lane scanner users (sim_queue_scanner / sim_driver_scanner) are
    created automatically if absent and removed on exit.
"""

import asyncio
import datetime as dt
import hashlib
import hmac as hmac_module
import json
import random
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from race.models import (
    ChampionshipPenalty,
    Race,
    RaceTransponderAssignment,
    Round,
    RoundPenalty,
    Session,
    team_member,
)
from race.utils import dataencode


# ── Coordinator ──────────────────────────────────────────────────────────────


@dataclass
class Coordinator:
    """Shared state between the three agents."""

    speed: float  # race seconds per wall second

    # transponder_id (str) → round_team.id (int)
    transponder_map: Dict[str, int] = field(default_factory=dict)
    # round_team.id → transponder_id
    team_transponder: Dict[int, str] = field(default_factory=dict)

    # team_id → loop.time() when suppression ends
    change_windows: Dict[int, float] = field(default_factory=dict)
    stopped_teams: Dict[int, float] = field(default_factory=dict)

    # asyncio events for inter-agent sync
    race_ready: asyncio.Event = field(default_factory=asyncio.Event)
    race_started: asyncio.Event = field(default_factory=asyncio.Event)
    all_done: asyncio.Event = field(default_factory=asyncio.Event)

    def is_suppressed(self, team_id: int) -> bool:
        """Return True if this team's crossing should be held right now."""
        now = asyncio.get_event_loop().time()
        for bucket in (self.change_windows, self.stopped_teams):
            if team_id in bucket:
                if now < bucket[team_id]:
                    return True
                del bucket[team_id]
        return False


# ── HMAC helper ──────────────────────────────────────────────────────────────


def _sign(msg: dict, secret: str) -> dict:
    """Return a copy of msg with hmac_signature appended (timing-station style)."""
    body = json.dumps(msg, sort_keys=False, separators=(",", ":"))
    sig = hmac_module.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return {**msg, "hmac_signature": sig}


# ── Management command ───────────────────────────────────────────────────────


class Command(BaseCommand):
    help = (
        "Simulate a timed race end-to-end. "
        "Uses actual /ws/timing/ WebSocket and scanning HTTP endpoints."
    )

    # ── CLI args ──────────────────────────────────────────────────────────────

    def add_arguments(self, parser):
        parser.add_argument(
            "--speed",
            type=float,
            default=10.0,
            help="Simulation speed multiplier — race-seconds per wall-second (default: 10)",
        )
        parser.add_argument(
            "--avg-lap",
            type=float,
            default=90.0,
            help="Average lap time in race-seconds (default: 90)",
        )
        parser.add_argument(
            "--lap-variance",
            type=float,
            default=5.0,
            help="Lap time variance in race-seconds (default: 5)",
        )
        parser.add_argument(
            "--penalty-prob",
            type=float,
            default=0.1,
            help="Probability of a penalty per team per race-hour (default: 0.1)",
        )
        parser.add_argument(
            "--timing-mode",
            default="duration",
            choices=["interval", "duration", "time_of_day", "own_time"],
            help="Raw timing value mode sent to the consumer (default: duration)",
        )
        parser.add_argument(
            "--race-id",
            type=int,
            default=None,
            help="Specific Race.id to simulate (default: first unstarted race in active round)",
        )
        parser.add_argument("--verbose", action="store_true")

    # ── Entry point ───────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        self.verbose = options["verbose"]
        self.speed = options["speed"]

        cround = self._find_round()
        self.log(f"Round: {cround.name}")

        active_race = self._find_race(cround, options.get("race_id"))
        self.log(
            f"Race: {active_race.get_race_type_display()} "
            f"(id={active_race.id}, start_mode={active_race.start_mode})"
        )
        if active_race.start_mode == "FIRST_CROSSING":
            raise CommandError(
                "FIRST_CROSSING start mode is not yet supported by this simulator. "
                "Switch the race to IMMEDIATE mode."
            )

        transponder_map, team_transponder = self._build_transponder_map(active_race)
        if not transponder_map:
            raise CommandError(
                "No transponder assignments found for this race. "
                "Complete transponder matching first."
            )
        self.log(f"Transponder assignments: {len(transponder_map)} teams")
        self._ensure_assignments_confirmed(active_race)

        queue_client, change_client = self._setup_scanner_clients()
        self._register_first_drivers(cround, active_race)

        coord = Coordinator(
            speed=self.speed,
            transponder_map=transponder_map,
            team_transponder=team_transponder,
        )

        try:
            asyncio.run(
                self._run(
                    coord, cround, active_race, queue_client, change_client, options
                )
            )
        except KeyboardInterrupt:
            self.log("Simulation interrupted by user.")

    # ── Async entry ───────────────────────────────────────────────────────────

    async def _run(
        self, coord, cround, active_race, queue_client, change_client, options
    ):
        from core.asgi import application  # imported here to avoid Django setup races

        await asyncio.gather(
            self._director_agent(coord, cround, active_race, options),
            self._decoder_agent(coord, active_race, options, application),
            self._pit_lane_agent(
                coord, cround, active_race, queue_client, change_client, options
            ),
        )

    # ── Director agent ────────────────────────────────────────────────────────

    async def _director_agent(self, coord, cround, active_race, options):
        """Manage race lifecycle through direct model calls."""
        loop = asyncio.get_event_loop()
        speed = coord.speed
        penalty_prob = options["penalty_prob"]

        # ── Pre-race check ──
        self.log("[Director] Pre-race check…")
        errors = await sync_to_async(cround.pre_race_check)()
        if errors:
            self.log(f"[Director] Pre-race check failed: {errors}")
            coord.all_done.set()
            return
        await sync_to_async(cround.activate_race_ready)()
        await sync_to_async(self._set_race_ready)(active_race)
        coord.race_ready.set()
        self.log("[Director] Race ready ✓")

        await asyncio.sleep(0.5)  # brief pause before start

        # ── Start race ──
        self.log("[Director] Starting race…")
        now = dt.datetime.now()
        await sync_to_async(self._do_race_start)(cround, active_race, now)
        coord.race_started.set()
        self.log("[Director] Race started ✓")

        race_start_wall = loop.time()
        race_duration_s = await sync_to_async(
            lambda: active_race.duration.total_seconds()
        )()
        race_wall_s = race_duration_s / speed

        penalty_wall_interval = 300.0 / speed  # check every 5 race-minutes
        last_penalty_wall = 0.0

        # ── Wait for race duration ──
        while True:
            await asyncio.sleep(0.3)
            elapsed_wall = loop.time() - race_start_wall
            elapsed_race = elapsed_wall * speed

            # Check if race was ended externally
            ended = await sync_to_async(
                lambda: Race.objects.filter(
                    pk=active_race.pk, ended__isnull=False
                ).exists()
            )()
            if ended:
                self.log("[Director] Race ended externally.")
                coord.all_done.set()
                return

            # Issue penalties periodically
            if elapsed_wall - last_penalty_wall >= penalty_wall_interval:
                await sync_to_async(self._maybe_issue_penalty)(
                    coord, cround, penalty_prob, loop, speed
                )
                last_penalty_wall = elapsed_wall

            if elapsed_race >= race_duration_s:
                break

        # ── End race ──
        self.log("[Director] Ending race…")
        now = dt.datetime.now()
        await sync_to_async(self._do_race_end)(cround, active_race, now)
        self.log("[Director] Race ended ✓")
        coord.all_done.set()

    def _set_race_ready(self, race):
        if not race.ready:
            race.ready = True
            race.save()

    def _do_race_start(self, cround, active_race, now):
        """Replicate race_start view logic for IMMEDIATE mode."""
        active_race.started = now
        active_race.save()
        if cround.started is None:
            cround.started = now
            cround.save()
        sessions = cround.session_set.filter(
            register__isnull=False, start__isnull=True, end__isnull=True
        )
        for s in sessions:
            s.start = now
            s.race = active_race
            s.save()

    def _do_race_end(self, cround, active_race, now):
        """Replicate endofrace view logic."""
        active_race.ended = now
        active_race.save()
        sessions = cround.session_set.filter(
            register__isnull=False, start__isnull=False, end__isnull=True
        )
        for s in sessions:
            s.end = now
            s.save()
        cround.session_set.filter(
            register__isnull=False, start__isnull=True, end__isnull=True
        ).delete()
        from race.models import ChangeLane

        ChangeLane.objects.all().delete()
        # Close round if this is the last race
        next_race = (
            cround.races.filter(ended__isnull=True).order_by("sequence_number").first()
        )
        if next_race is None:
            cround.ended = now
            cround.save()
            cround.post_race_check()

    def _maybe_issue_penalty(self, coord, cround, penalty_prob, loop, speed):
        """Randomly issue a Stop & Go or other penalty."""
        penalties = list(
            ChampionshipPenalty.objects.filter(
                championship=cround.championship
            ).exclude(sanction="P")
        )
        if not penalties:
            return
        teams = list(cround.round_team_set.filter(retired=False))
        if not teams:
            return

        # probability per team per 5-minute check
        chance = penalty_prob * (300.0 / 3600.0) / len(teams)
        for team in teams:
            if random.random() >= chance:
                continue
            penalty = random.choice(penalties)
            victim = None
            if penalty.sanction == "S":
                others = [t for t in teams if t != team]
                if others:
                    victim = random.choice(others)
            rp = RoundPenalty.objects.create(
                round=cround,
                offender=team,
                victim=victim,
                penalty=penalty,
                value=penalty.value,
                imposed=dt.datetime.now(),
            )
            self.log(
                f"[Director] Penalty: {penalty.penalty.name} → team {team.number}"
                + (f" (victim: {victim.number})" if victim else "")
            )
            # For S&G/self-S&G: suppress crossings then auto-serve
            if penalty.sanction in ("S", "D"):
                stop_wall = float(penalty.value) / speed
                coord.stopped_teams[team.id] = loop.time() + stop_wall
                # Schedule auto-serve
                asyncio.get_event_loop().create_task(
                    self._serve_penalty_after(rp.id, stop_wall)
                )

    async def _serve_penalty_after(self, penalty_id, delay_wall):
        await asyncio.sleep(delay_wall)
        await sync_to_async(self._mark_served)(penalty_id)
        self.log(f"[Director] S&G penalty {penalty_id} served")

    def _mark_served(self, penalty_id):
        try:
            rp = RoundPenalty.objects.get(pk=penalty_id, served__isnull=True)
            rp.served = dt.datetime.now()
            rp.save()
        except RoundPenalty.DoesNotExist:
            pass

    # ── Decoder agent ─────────────────────────────────────────────────────────

    async def _decoder_agent(self, coord, active_race, options, application):
        """Send HMAC-signed crossings to /ws/timing/ via WebsocketCommunicator."""
        hmac_secret = settings.TIMING_HMAC_SECRET
        timing_mode = options["timing_mode"]
        avg_lap = options["avg_lap"]
        lap_variance = options["lap_variance"]
        speed = coord.speed
        loop = asyncio.get_event_loop()

        communicator = WebsocketCommunicator(application, "/ws/timing/")
        connected, _ = await communicator.connect()
        if not connected:
            self.log("[Decoder] ERROR: Could not connect to /ws/timing/")
            return

        # Announce ourselves to TimingConsumer
        await communicator.send_json_to(
            _sign(
                {
                    "type": "connected",
                    "plugin_type": "simulator",
                    "timing_mode": timing_mode,
                    "rollover_seconds": 360000.0,
                    "timestamp": dt.datetime.now().isoformat(),
                },
                hmac_secret,
            )
        )

        await coord.race_started.wait()
        self.log("[Decoder] Race started — emitting crossings")

        race_start_wall = loop.time()
        tod_offset = (
            dt.datetime.now().hour * 3600
            + dt.datetime.now().minute * 60
            + dt.datetime.now().second
        )

        def compute_raw(cumulative, lap_time):
            if timing_mode == "interval":
                return lap_time
            elif timing_mode == "duration":
                return cumulative
            elif timing_mode == "time_of_day":
                return (tod_offset + cumulative) % 86400.0
            else:  # own_time
                return cumulative % 360000.0

        # Per-team crossing state: cumulative race-time, base lap time, next scheduled crossing
        team_states = {}
        for team_id in coord.team_transponder:
            offset = random.uniform(0, min(8.0, avg_lap * 0.08))
            base = avg_lap + random.uniform(-lap_variance * 2, lap_variance * 2)
            base = max(avg_lap * 0.6, base)
            variance = random.uniform(-lap_variance, lap_variance)
            team_states[team_id] = {
                "cumulative": offset,
                "base_lap": base,
                "next_race_time": offset + base + variance,
            }

        async def drain_acks():
            """Non-blocking drain of ACK messages from consumer."""
            while True:
                try:
                    await asyncio.wait_for(
                        communicator.receive_json_from(), timeout=0.0
                    )
                except (asyncio.TimeoutError, Exception):
                    break

        while not coord.all_done.is_set():
            # Find the team with the earliest next crossing
            if not team_states:
                break
            next_team_id = min(
                team_states, key=lambda t: team_states[t]["next_race_time"]
            )
            state = team_states[next_team_id]
            next_race_t = state["next_race_time"]

            # How long to wait in wall time
            now_race = (loop.time() - race_start_wall) * speed
            wait_wall = (next_race_t - now_race) / speed

            if wait_wall > 0:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(coord.all_done.wait()),
                        timeout=wait_wall,
                    )
                    break  # all_done fired while waiting
                except asyncio.TimeoutError:
                    pass

            await drain_acks()

            lap_time = next_race_t - state["cumulative"]
            raw = compute_raw(next_race_t, lap_time)
            transponder = coord.team_transponder[next_team_id]

            if not coord.is_suppressed(next_team_id):
                msg = {
                    "type": "lap_crossing",
                    "transponder_id": transponder,
                    "timestamp": dt.datetime.now().isoformat(),
                    "raw_time": raw,
                    "signal_strength": random.randint(80, 100),
                    "message_id": str(uuid.uuid4()),
                }
                await communicator.send_json_to(_sign(msg, hmac_secret))
                if self.verbose:
                    self.log(
                        f"[Decoder] team={next_team_id} transponder={transponder} raw={raw:.3f}"
                    )
            else:
                if self.verbose:
                    self.log(f"[Decoder] Suppressed team={next_team_id}")

            # Schedule next crossing for this team
            variance = random.uniform(-lap_variance, lap_variance)
            # Slight random drift so laps don't become perfectly regular
            drift = random.uniform(-0.3, 0.3)
            new_base = max(avg_lap * 0.6, state["base_lap"] + drift)
            state["cumulative"] = next_race_t
            state["base_lap"] = new_base
            state["next_race_time"] = next_race_t + new_base + variance

        await communicator.disconnect()
        self.log("[Decoder] Done")

    # ── Pit-lane agent ────────────────────────────────────────────────────────

    async def _pit_lane_agent(
        self, coord, cround, active_race, queue_client, change_client, options
    ):
        """Manage driver changes via the HTTP scanning endpoints."""
        speed = coord.speed
        avg_lap = options["avg_lap"]
        loop = asyncio.get_event_loop()

        await coord.race_started.wait()
        race_start_wall = loop.time()

        race_duration_s = await sync_to_async(
            lambda: active_race.duration.total_seconds()
        )()
        # Use cround.duration (the configured endurance length) for the pit window,
        # matching the real pit_lane_open property which also uses cround.duration.
        round_duration_s = await sync_to_async(
            lambda: cround.duration.total_seconds()
        )()
        pit_open_after = await sync_to_async(
            lambda: cround.pitlane_open_after.total_seconds()
        )()
        pit_close_before = await sync_to_async(
            lambda: cround.pitlane_close_before.total_seconds()
        )()
        required_changes = await sync_to_async(lambda: cround.required_changes)()
        race_type = await sync_to_async(lambda: active_race.race_type)()
        change_lanes = await sync_to_async(lambda: cround.change_lanes)()

        is_qualifying = race_type in ("Q1", "Q2", "Q3", "PRACTICE")
        if is_qualifying:
            # Real pit_lane_open always returns True for non-MAIN races.
            pit_open_at = 0.0
            pit_close_at = float("inf")
        else:
            pit_open_at = pit_open_after
            pit_close_at = round_duration_s - pit_close_before

        team_stats = await sync_to_async(self._init_team_stats)(
            cround, required_changes, race_type, avg_lap, pit_open_at, pit_close_at
        )
        if is_qualifying:
            self.log(
                f"[PitLane] {len(team_stats)} teams — pit always open (qualifying)"
            )
        else:
            self.log(
                f"[PitLane] {len(team_stats)} teams — "
                f"pit open {pit_open_at/60:.0f}–{pit_close_at/60:.0f} race-min"
            )

        while not coord.all_done.is_set():
            await asyncio.sleep(0.25)
            elapsed_race = (loop.time() - race_start_wall) * speed
            pit_open = pit_open_at <= elapsed_race <= pit_close_at
            if not pit_open:
                continue

            for team_id, stats in team_stats.items():
                team = stats["team"]

                # ── Queue next driver ──
                if (
                    not stats["has_queued"]
                    and stats["completed_changes"] < stats["target_changes"]
                    and elapsed_race >= stats["next_queue_race_time"]
                ):
                    driver = await sync_to_async(self._pick_next_driver)(cround, team)
                    if driver:
                        encoded = await sync_to_async(dataencode)(cround, driver.id)
                        resp = await sync_to_async(queue_client.post)(
                            "/driver_queue/", {"data": encoded}, format="json"
                        )
                        if resp.status_code == 200 and resp.data.get("status") == "ok":
                            stats["has_queued"] = True
                            stats["in_lane"] = False
                            stats["change_race_time"] = float("inf")
                            self.log(
                                f"[PitLane] Team {team.number}: queued {driver.member.nickname}"
                            )
                        else:
                            if self.verbose:
                                self.log(
                                    f"[PitLane] Team {team.number}: queue failed — {resp.data}"
                                )

                # ── Check lane promotion ──
                # A driver physically enters the pit lane only when their session
                # reaches a top change_lanes slot (first-registered pending sessions).
                if stats["has_queued"] and not stats["in_lane"]:
                    in_lane = await sync_to_async(self._check_in_lane)(
                        cround, team, change_lanes
                    )
                    if in_lane:
                        stats["in_lane"] = True
                        laps_wait = random.choices(
                            [1, 2, 3, 4, 5, 6], weights=[15, 30, 50, 3, 1, 1]
                        )[0]
                        stats["change_race_time"] = elapsed_race + avg_lap * laps_wait
                        self.log(
                            f"[PitLane] Team {team.number}: reached lane "
                            f"— change in {laps_wait} lap(s)"
                        )

                # ── Perform driver change ──
                if (
                    stats["has_queued"]
                    and stats["in_lane"]
                    and elapsed_race >= stats["change_race_time"]
                ):
                    current = await sync_to_async(self._get_current_driver)(
                        cround, team
                    )
                    if current:
                        # Suppress decoder during physical stop
                        change_race_s = random.uniform(25, 55)
                        change_wall_s = change_race_s / speed
                        coord.change_windows[team_id] = loop.time() + change_wall_s
                        await asyncio.sleep(change_wall_s)

                        encoded = await sync_to_async(dataencode)(cround, current.id)
                        resp = await sync_to_async(change_client.post)(
                            "/driver_change/", {"data": encoded}, format="json"
                        )
                        if resp.status_code == 200 and resp.data.get("status") == "ok":
                            stats["completed_changes"] += 1
                            stats["has_queued"] = False
                            stats["in_lane"] = False
                            stats["next_queue_race_time"] = self._next_queue_time(
                                elapsed_race, stats, pit_close_at, avg_lap
                            )
                            self.log(
                                f"[PitLane] Team {team.number}: "
                                f"change #{stats['completed_changes']} done"
                            )
                        else:
                            stats["has_queued"] = False
                            stats["in_lane"] = False
                            if self.verbose:
                                self.log(
                                    f"[PitLane] Team {team.number}: change failed — {resp.data}"
                                )
                    else:
                        # No current driver yet — retry next cycle
                        stats["change_race_time"] = elapsed_race + avg_lap * 0.5

        self.log("[PitLane] Done")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_round(self):
        start = dt.date.today() - dt.timedelta(days=1)
        end = start + dt.timedelta(days=60)
        r = Round.objects.filter(
            Q(start__date__range=[start, end]) & Q(ended__isnull=True)
        ).first()
        if not r:
            raise CommandError(
                "No active round found (started within last day, not yet ended)."
            )
        return r

    def _find_race(self, cround, race_id=None):
        if race_id:
            try:
                return Race.objects.get(pk=race_id, round=cround)
            except Race.DoesNotExist:
                raise CommandError(f"Race {race_id} not found in round {cround.id}.")
        race = (
            cround.races.filter(started__isnull=True, ended__isnull=True)
            .order_by("sequence_number")
            .first()
        )
        if not race:
            raise CommandError("No unstarted race found in this round.")
        return race

    def _ensure_assignments_confirmed(self, race):
        """Confirm any unconfirmed transponder assignments and lock the grid.

        If assignments were already confirmed manually, this is a no-op.
        If the signal carried them over with confirmed=False (next race in chain),
        we confirm them automatically so the rest of the system is in a consistent state.
        """
        qs = RaceTransponderAssignment.objects.filter(race=race)
        unconfirmed = qs.filter(confirmed=False).count()
        if unconfirmed == 0:
            self.log("Transponder assignments already confirmed ✓")
            return
        qs.filter(confirmed=False).update(confirmed=True)
        if not race.grid_locked:
            race.grid_locked = True
            race.save(update_fields=["grid_locked"])
        self.log(f"Auto-confirmed {unconfirmed} transponder assignment(s) ✓")

    def _build_transponder_map(self, active_race):
        t_map = {}
        team_map = {}
        for a in RaceTransponderAssignment.objects.filter(
            race=active_race
        ).select_related("transponder", "team"):
            code = a.transponder.transponder_id
            t_map[code] = a.team.id
            team_map[a.team.id] = code
        return t_map, team_map

    def _setup_scanner_clients(self):
        queue_group, _ = Group.objects.get_or_create(name="Queue Scanner")
        change_group, _ = Group.objects.get_or_create(name="Driver Scanner")
        queue_user = self._ensure_scanner_user("sim_queue_scanner", queue_group)
        change_user = self._ensure_scanner_user("sim_driver_scanner", change_group)
        qt, _ = Token.objects.get_or_create(user=queue_user)
        ct, _ = Token.objects.get_or_create(user=change_user)
        qc = APIClient(SERVER_NAME="localhost")
        qc.credentials(HTTP_AUTHORIZATION=f"Token {qt.key}")
        cc = APIClient(SERVER_NAME="localhost")
        cc.credentials(HTTP_AUTHORIZATION=f"Token {ct.key}")
        return qc, cc

    def _ensure_scanner_user(self, username, group):
        user, created = User.objects.get_or_create(
            username=username, defaults={"is_active": True}
        )
        if created:
            user.set_password("sim_scanner_internal_only")
            user.save()
            self.log(f"Created scanner user: {username}")
        if not user.groups.filter(pk=group.pk).exists():
            user.groups.add(group)
        return user

    def _register_first_drivers(self, cround, active_race):
        now = dt.datetime.now()
        for team in cround.round_team_set.filter(retired=False):
            # A pending session is registered but not yet started and not ended.
            # Previous races leave behind ended sessions — those don't count.
            already = Session.objects.filter(
                round=cround,
                driver__team=team,
                register__isnull=False,
                start__isnull=True,
                end__isnull=True,
            ).exists()
            if already:
                continue
            driver = team.team_member_set.filter(driver=True).order_by("?").first()
            if driver:
                Session.objects.create(round=cround, driver=driver, register=now)
                self.log(
                    f"  Registered {driver.member.nickname} for team {team.number}"
                )

    def _init_team_stats(
        self, cround, required_changes, race_type, avg_lap, pit_open_at, pit_close_at
    ):
        is_qualifying = race_type in ("Q1", "Q2", "Q3", "PRACTICE")
        stats = {}
        for team in cround.round_team_set.select_related("team", "team__team").filter(
            retired=False
        ):
            if is_qualifying:
                # Qualifying: pit always open but changes are rare — mostly nobody changes.
                target = 1 if random.random() < 0.15 else 0
            else:
                v = random.random()
                target = required_changes + (
                    1 if v < 0.6 else random.randint(2, 4) if v < 0.8 else 0
                )
            window = max(pit_close_at - pit_open_at, avg_lap)
            initial_queue = pit_open_at + random.uniform(
                0, min(avg_lap * 2, window * 0.2)
            )
            stats[team.id] = {
                "team": team,
                "target_changes": target,
                "completed_changes": 0,
                "has_queued": False,
                "in_lane": False,
                "next_queue_race_time": initial_queue,
                "change_race_time": float("inf"),
            }
        return stats

    def _check_in_lane(self, cround, team, change_lanes):
        """Return True if this team has a pending session in the top change_lanes slots."""
        top_team_ids = list(
            Session.objects.filter(
                round=cround,
                register__isnull=False,
                start__isnull=True,
                end__isnull=True,
            )
            .order_by("register")
            .values_list("driver__team_id", flat=True)[:change_lanes]
        )
        return team.pk in top_team_ids

    def _next_queue_time(self, current_race, stats, pit_close_at, avg_lap):
        """Schedule the next queue attempt, spread evenly within the remaining pit window."""
        remaining = stats["target_changes"] - stats["completed_changes"]
        if remaining <= 0:
            return float("inf")
        remaining_window = pit_close_at - current_race
        if remaining_window <= avg_lap:  # not enough time for another change
            return float("inf")
        optimal = remaining_window / remaining
        return current_race + optimal * random.uniform(0.85, 1.15)

    def _pick_next_driver(self, cround, team):
        active_ids = Session.objects.filter(
            round=cround,
            driver__team=team,
            register__isnull=False,
            start__isnull=False,
            end__isnull=True,
        ).values_list("driver_id", flat=True)
        queued_ids = Session.objects.filter(
            round=cround,
            driver__team=team,
            register__isnull=False,
            start__isnull=True,
            end__isnull=True,
        ).values_list("driver_id", flat=True)
        available = (
            team.team_member_set.select_related("member")
            .filter(driver=True)
            .exclude(id__in=list(active_ids) + list(queued_ids))
        )
        if not available.exists():
            return None
        undriven = available.exclude(
            id__in=Session.objects.filter(round=cround, end__isnull=False).values(
                "driver"
            )
        )
        return (undriven if undriven.exists() else available).order_by("?").first()

    def _get_current_driver(self, cround, team):
        s = (
            Session.objects.select_related("driver__member")
            .filter(
                round=cround,
                driver__team=team,
                register__isnull=False,
                start__isnull=False,
                end__isnull=True,
            )
            .first()
        )
        return s.driver if s else None

    def log(self, message):
        ts = dt.datetime.now().strftime("%H:%M:%S")
        self.stdout.write(f"[{ts}] {message}")
        if self.verbose:
            print(f"[{ts}] {message}")
