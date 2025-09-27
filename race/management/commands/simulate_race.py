import datetime as dt
import time
import random
import threading
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.db import models
from race.models import (
    Session,
    Round,
    team_member,
    ChampionshipPenalty,
    RoundPenalty,
)


class Command(BaseCommand):
    help = "Simulate a realistic race with driver changes and penalties."

    def add_arguments(self, parser):
        parser.add_argument(
            "--average-lap-time",
            type=float,
            default=90.0,
            help="Average lap time in seconds (default: 90)",
        )
        parser.add_argument(
            "--real-time-speed",
            type=float,
            default=1.0,
            help="Simulation speed multiplier - how many seconds of race time per real second (default: 1.0 for real-time)",
        )
        parser.add_argument(
            "--penalty-probability",
            type=float,
            default=0.15,
            help="Probability of penalty per team per hour (default: 0.15)",
        )
        parser.add_argument(
            "--verbose", action="store_true", help="Enable verbose logging"
        )

    def handle(self, *args, **options):
        self.verbose = options["verbose"]
        self.average_lap_time = options["average_lap_time"]
        self.real_time_speed = options["real_time_speed"]
        self.penalty_probability = options["penalty_probability"]

        # Find current round
        start_date = dt.date.today() - dt.timedelta(days=1)
        end_date = start_date + dt.timedelta(days=60)
        cround = Round.objects.filter(
            Q(start__date__range=[start_date, end_date]) & Q(ended__isnull=True)
        ).first()

        if not cround:
            raise CommandError("Could not find an active round to simulate")

        self.round = cround
        self.log(f"Starting simulation for round: {cround.name}")
        self.log(f"Race duration: {cround.duration}")
        self.log(f"Average lap time: {self.average_lap_time}s")
        self.log(f"Real-time speed: {self.real_time_speed}x")

        try:
            self.simulate_full_race()
        except KeyboardInterrupt:
            self.log("Simulation interrupted by user")
        except Exception as e:
            self.log(f"Simulation error: {e}")
            raise

    def log(self, message):
        """Log with timestamp"""
        timestamp = dt.datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
        if self.verbose:
            self.stdout.write(f"[{timestamp}] {message}")

    def simulate_full_race(self):
        """Run complete race simulation"""

        # Phase 1: Register first drivers (like firstregister command)
        self.log("Phase 1: Registering first drivers...")
        self.register_first_drivers()

        # Phase 2: Pre-race check
        self.log("Phase 2: Running pre-race check...")
        errors = self.round.pre_race_check()
        if errors:
            raise CommandError(f"Pre-race check failed: {errors}")
        self.log("Pre-race check passed ✓")

        # Phase 3: Start race
        self.log("Phase 3: Starting race...")
        self.round.start_race()
        self.log("Race started ✓")

        # Phase 4: Simulate race duration with pit stops and penalties
        self.log("Phase 4: Simulating race...")
        self.simulate_race_events()

        # Phase 5: End race (if not already ended)
        if not self.round.ended:
            self.log("Phase 5: Ending race...")
            penalty_count = self.round.end_race()
            self.log(f"Race ended ✓ ({penalty_count} post-race penalties applied)")
        else:
            self.log("Phase 5: Race already ended")

    def register_first_drivers(self):
        """Register one driver per team (like firstregister command)"""
        teams = self.round.round_team_set.all().order_by("team__number")
        now = dt.datetime.now()

        for team in teams:
            driver = team.team_member_set.filter(driver=True).order_by("?").first()
            if driver:
                session = Session.objects.create(
                    round=self.round, driver=driver, register=now
                )
                self.log(
                    f"  Registered {driver.member.nickname} for team {team.number}"
                )

    def simulate_race_events(self):
        """Simulate the race duration with realistic timing"""
        race_duration_seconds = self.round.duration.total_seconds()
        pitlane_open_after_seconds = self.round.pitlane_open_after.total_seconds()
        pitlane_close_before_seconds = self.round.pitlane_close_before.total_seconds()

        # Calculate when pit lane opens and closes
        pitlane_open_at = pitlane_open_after_seconds
        pitlane_close_at = race_duration_seconds - pitlane_close_before_seconds

        self.log(f"Race will run for {race_duration_seconds/60:.1f} minutes")
        self.log(f"Pit lane opens at {pitlane_open_at/60:.1f} minutes")
        self.log(f"Pit lane closes at {pitlane_close_at/60:.1f} minutes")

        # Get all teams and their driver change requirements
        teams = list(self.round.round_team_set.all())
        team_stats = self.initialize_team_stats(teams)

        # Time tracking
        elapsed_time = 0
        last_penalty_check = 0

        # Stop & Go penalty tracking
        active_stop_go_penalty = None
        penalty_serve_time = 0
        penalty_timeout_time = 0

        # Event loop - use real wall clock time multiplied by speed factor
        simulation_start_time = time.time()
        race_start_time = simulation_start_time

        while elapsed_time < race_duration_seconds:
            # Sleep for a short interval to avoid busy waiting
            time.sleep(0.1)

            # Calculate elapsed time based on real wall clock time and speed multiplier
            wall_clock_elapsed = time.time() - race_start_time
            elapsed_time = wall_clock_elapsed * self.real_time_speed

            # Check if race has ended (manual end or duration reached)
            self.round.refresh_from_db()
            if self.round.ended:
                self.log(f"Race ended manually at {elapsed_time/60:.1f} minutes")
                break

            # Check if pit lane is open
            pit_lane_open = pitlane_open_at <= elapsed_time <= pitlane_close_at

            if pit_lane_open:
                # Simulate driver changes
                self.simulate_driver_changes(
                    elapsed_time, team_stats, pitlane_close_at, pit_lane_open
                )

                # Check for penalties every 5 minutes of race time (only if no active Stop & Go)
                if (
                    elapsed_time - last_penalty_check >= 300
                    and active_stop_go_penalty is None  # 5 minutes
                ):
                    penalty = self.simulate_penalties(elapsed_time)
                    if penalty and penalty.penalty.sanction in [
                        "S",
                        "D",
                    ]:  # Stop & Go penalties
                        active_stop_go_penalty = penalty
                        # Calculate realistic serve time with randomness
                        serve_delay = self.calculate_penalty_serve_time()
                        penalty_serve_time = elapsed_time + serve_delay + penalty.value
                        penalty_timeout_time = elapsed_time + (
                            3.5 * self.average_lap_time
                        )  # Auto-ignore after ~3.5 laps

                        laps_to_serve = serve_delay / self.average_lap_time
                        self.log(
                            f"🚨 Active Stop & Go penalty - team will serve after ~{laps_to_serve:.1f} laps ({serve_delay:.0f}s)"
                        )
                    last_penalty_check = elapsed_time

                # Check if it's time to serve the active Stop & Go penalty OR if it timed out
                if active_stop_go_penalty:
                    if elapsed_time >= penalty_serve_time:
                        # Team served the penalty in time
                        success = self.serve_stop_go_penalty(active_stop_go_penalty)
                        if success:
                            self.log(
                                f"✅ Stop & Go penalty served for team {active_stop_go_penalty.offender.number}"
                            )
                            active_stop_go_penalty = None
                            penalty_serve_time = 0
                            penalty_timeout_time = 0
                    elif elapsed_time >= penalty_timeout_time:
                        # Team ignored penalty - issue "ignoring stop & go" penalty but keep original active
                        ignore_penalty = self.issue_ignoring_penalty(
                            active_stop_go_penalty.offender
                        )
                        if ignore_penalty:
                            self.log(
                                f"⚠️ Team {active_stop_go_penalty.offender.number} ignored Stop & Go - issued '{ignore_penalty.penalty.penalty.name}' penalty"
                            )
                            self.log(
                                f"⚠️ Original Stop & Go penalty still active and must be served"
                            )
                        else:
                            self.log(
                                f"⚠️ Team {active_stop_go_penalty.offender.number} ignored Stop & Go - no 'ignoring s&g' penalty configured"
                            )

                        # Reset timeout to allow more time for serving the original penalty
                        penalty_timeout_time = elapsed_time + (
                            2 * self.average_lap_time
                        )  # Give 2 more laps
                        self.log(
                            f"⚠️ Team {active_stop_go_penalty.offender.number} has {2 * self.average_lap_time:.0f}s more to serve original Stop & Go"
                        )

            # Log progress every 10 minutes of race time
            if (
                int(elapsed_time) % 600 == 0 and int(elapsed_time) != 0
            ):  # Every 10 minutes
                actual_wall_clock_elapsed = time.time() - race_start_time
                self.log(
                    f"Race progress: {elapsed_time/60:.1f}/{race_duration_seconds/60:.1f} minutes (wall clock: {actual_wall_clock_elapsed/60:.1f} min, speed: {self.real_time_speed}x)"
                )

        # End the race if it hasn't been ended already
        if not self.round.ended:
            self.log(
                f"Race duration reached, ending race at {elapsed_time/60:.1f} minutes"
            )
            try:
                self.round.end_race()
                self.log("Race officially ended")
            except Exception as e:
                self.log(f"Failed to end race: {e}")

        self.log_final_stats(team_stats)

    def initialize_team_stats(self, teams):
        """Initialize tracking stats for each team"""
        team_stats = {}

        for team in teams:
            drivers = list(team.team_member_set.filter(driver=True))

            # Calculate realistic driver change pattern
            required_changes = self.round.required_changes

            # Add variation with higher targets to account for simulation constraints
            # Many teams fail to achieve their target due to pit lane timing, etc.
            # So we need higher targets to ensure most teams meet the minimum requirement
            variation = random.random()
            if variation < 0.6:
                target_changes = (
                    required_changes + 1
                )  # Aim higher to reliably meet requirement
            elif variation < 0.8:
                target_changes = required_changes + random.randint(
                    2, 4
                )  # Do significantly more
            else:
                target_changes = required_changes  # Some teams aim for exact minimum (might fall short)

            # Calculate time limits for this team
            limit_type, limit_value = self.round.driver_time_limit(team)

            # Determine if this team will violate time limits (5% chance)
            will_violate_limits = random.random() < 0.05

            team_stats[team.id] = {
                "team": team,
                "drivers": drivers,
                "target_changes": target_changes,
                "completed_changes": 0,
                "next_queue_time": 0,  # Will be calculated after team_stats is complete
                "has_queued_driver": False,
                "change_ready_time": 0,
                "top_queue_reached_time": 0,  # When team reached top queue positions
                "limit_type": limit_type,
                "limit_value": limit_value,
                "will_violate_limits": will_violate_limits,
                "driver_times": {
                    driver.id: 0 for driver in drivers
                },  # Track each driver's time
            }

            # Log team setup
            limit_info = "No time limit"
            if limit_type and limit_value:
                # limit_value is now always a timedelta
                limit_minutes = limit_value.total_seconds() / 60
                limit_info = f"{limit_type} limit: {limit_minutes:.1f} min per driver"

            violation_note = " (may violate limits)" if will_violate_limits else ""

            # Now calculate initial queue time with complete team stats
            team_stats[team.id]["next_queue_time"] = self.calculate_next_queue_time(
                0, team_stats[team.id]
            )

            self.log(
                f"Team {team.number} ({team.team.team.name}): targeting {target_changes} changes, {limit_info}{violation_note}"
            )

        return team_stats

    def calculate_next_queue_time(self, current_time, team_stats=None):
        """Calculate realistic next driver queue time based on race duration and required changes"""
        if team_stats and team_stats.get("target_changes", 0) > 0:
            # Calculate optimal stint duration based on race duration and required changes
            race_duration_seconds = (
                self.round.duration.total_seconds()
                if hasattr(self.round.duration, "total_seconds")
                else self.round.duration * 60
            )
            remaining_changes = (
                team_stats["target_changes"] - team_stats["completed_changes"]
            )

            if remaining_changes <= 0:
                return float("inf")  # No more changes needed

            # Calculate remaining race time (leave 10 minutes buffer for pit closure)
            remaining_time = race_duration_seconds - current_time - (10 * 60)

            if remaining_time <= 0:
                return float("inf")  # Too late for more changes

            # Distribute remaining time across remaining changes
            optimal_stint_duration = remaining_time / remaining_changes

            # Add some realistic variation (±15%) but stay close to optimal
            variation_factor = random.uniform(0.85, 1.15)
            stint_duration = optimal_stint_duration * variation_factor

            # Ensure minimum stint of 5 minutes and don't exceed remaining time
            stint_duration = max(300, min(stint_duration, remaining_time - 300))

            return current_time + stint_duration
        else:
            # Fallback to old logic if no target changes
            base_stint = random.uniform(15 * 60, 45 * 60)
            lap_variation = random.uniform(0.8, 1.2) * self.average_lap_time
            return current_time + base_stint + lap_variation

    def calculate_penalty_serve_time(self):
        """Calculate realistic time for team to serve Stop & Go penalty"""
        # Realistic distribution of penalty serving behavior:
        # 30% serve after 1 lap
        # 40% serve after 2 laps
        # 20% serve after 3 laps
        # 8% serve after 3+ laps (will trigger ignoring penalty)
        # 2% serve after 4+ laps (will trigger ignoring penalty)

        rand = random.random()
        if rand < 0.30:  # 30% - serve after ~1 lap
            return random.uniform(0.8, 1.2) * self.average_lap_time
        elif rand < 0.70:  # 40% - serve after ~2 laps
            return random.uniform(1.8, 2.2) * self.average_lap_time
        elif rand < 0.90:  # 20% - serve after ~3 laps
            return random.uniform(2.8, 3.2) * self.average_lap_time
        elif rand < 0.98:  # 8% - serve after 3.5+ laps (too late)
            return random.uniform(3.5, 4.0) * self.average_lap_time
        else:  # 2% - serve after 4+ laps (way too late)
            return random.uniform(4.0, 5.0) * self.average_lap_time

    def simulate_driver_changes(
        self, elapsed_time, team_stats, pitlane_close_at, pit_lane_open
    ):
        """Simulate realistic driver changes using proper driver_queue -> driver_change flow"""

        # Phase 1: Handle driver_queue registrations (drivers coming to pit lane)
        for team_id, stats in team_stats.items():
            team = stats["team"]

            # Check if it's time for this team to queue a driver
            if (
                elapsed_time >= stats["next_queue_time"]
                and stats["completed_changes"] < stats["target_changes"]
                and not stats.get("has_queued_driver", False)
                and pit_lane_open  # Don't queue drivers when pit lanes are closed
            ):
                # Check if current driver needs to be changed due to time limits
                should_change = self.should_change_driver_for_time_limit(
                    team, stats, elapsed_time
                )

                success = self.perform_driver_queue(team, elapsed_time)
                if success:
                    stats["has_queued_driver"] = True
                    # Set time for actual driver change (about 2 laps later)
                    stats["change_ready_time"] = elapsed_time + (
                        2 * self.average_lap_time
                    )

                    # Schedule next queue time based on adaptive algorithm
                    stats["next_queue_time"] = self.calculate_next_queue_time(
                        stats["change_ready_time"], stats
                    )
                    change_reason = "time limit" if should_change else "normal stint"
                    self.log(
                        f"Team {team.number}: driver queued ({change_reason}), change ready in {2 * self.average_lap_time:.0f}s"
                    )

        # Phase 2: Check for teams in top queue positions and track timing
        for team_id, stats in team_stats.items():
            team = stats["team"]

            if stats.get("has_queued_driver", False):
                # Check if team just reached top queue positions
                if stats[
                    "top_queue_reached_time"
                ] == 0 and self.team_in_top_queue_positions(team):
                    # Check if pit lanes are still open when reaching top positions
                    if elapsed_time <= pitlane_close_at:
                        stats["top_queue_reached_time"] = elapsed_time
                        self.log(
                            f"Team {team.number}: reached top {self.round.change_lanes} queue positions"
                        )
                    else:
                        # Too late - pit lanes are closed or about to close
                        stats["has_queued_driver"] = False
                        self.log(
                            f"Team {team.number}: reached top queue too late - pit lanes closed/closing"
                        )

                # Check if driver change is ready and team is in position
                if elapsed_time >= stats.get(
                    "change_ready_time", 0
                ) and self.team_ready_for_change(team):

                    # Double-check pit lanes are still open
                    if elapsed_time <= pitlane_close_at:
                        success = self.perform_driver_change(team, elapsed_time)
                    else:
                        # Pit lanes closed before change could complete
                        stats["has_queued_driver"] = False
                        stats["top_queue_reached_time"] = 0
                        self.log(
                            f"Team {team.number}: driver change cancelled - pit lanes closed"
                        )
                        success = False
                    if success:
                        # Calculate how long they took from reaching top positions
                        if stats["top_queue_reached_time"] > 0:
                            queue_delay = elapsed_time - stats["top_queue_reached_time"]
                            max_allowed_delay = 3 * self.average_lap_time

                            if queue_delay > max_allowed_delay:
                                # Issue "driver change too long" penalty
                                slow_change_penalty = (
                                    self.issue_driver_change_too_long_penalty(
                                        team, queue_delay
                                    )
                                )
                                if slow_change_penalty:
                                    self.log(
                                        f"⏰ Team {team.number} took {queue_delay:.0f}s for driver change - issued '{slow_change_penalty.penalty.penalty.name}' penalty"
                                    )

                        stats["completed_changes"] += 1
                        stats["has_queued_driver"] = False
                        stats["top_queue_reached_time"] = 0

                        # Schedule next queue time with adaptive algorithm
                        if stats["completed_changes"] < stats["target_changes"]:
                            stats["next_queue_time"] = self.calculate_next_queue_time(
                                elapsed_time, stats
                            )

                        self.log(
                            f"Team {team.number}: driver change completed #{stats['completed_changes']}"
                        )

    def perform_driver_queue(self, team, elapsed_time):
        """Register a driver for the queue (driver_queue equivalent)"""
        try:
            # Find drivers who are NOT currently on track (all sessions complete)
            available_drivers = []
            for driver in team.team_member_set.filter(driver=True):
                # Check if driver has any active session (registered, started, not ended)
                active_session = Session.objects.filter(
                    round=self.round,
                    driver=driver,
                    register__isnull=False,
                    start__isnull=False,
                    end__isnull=True,
                ).exists()

                if not active_session:
                    available_drivers.append(driver)

            if not available_drivers:
                return False

            # Prioritize drivers who haven't driven yet, then those with least drive time
            drivers_with_sessions = []
            drivers_without_sessions = []

            for driver in available_drivers:
                # Check if driver has any completed sessions
                has_sessions = Session.objects.filter(
                    round=self.round, driver=driver, end__isnull=False
                ).exists()

                if has_sessions:
                    # Calculate total drive time for drivers who have driven
                    total_time = Session.objects.filter(
                        round=self.round, driver=driver, end__isnull=False
                    ).aggregate(
                        total_seconds=models.Sum(
                            models.F("end") - models.F("start"),
                            output_field=models.DurationField(),
                        )
                    )[
                        "total_seconds"
                    ]

                    if total_time:
                        total_seconds = total_time.total_seconds()
                        drivers_with_sessions.append((driver, total_seconds))
                else:
                    drivers_without_sessions.append(driver)

            # Pick driver: prioritize those who haven't driven, then least experienced
            if drivers_without_sessions:
                next_driver = random.choice(drivers_without_sessions)
                self.log(
                    f"  Selected {next_driver.member.nickname} (first time driving)"
                )
            else:
                # Sort by drive time and pick one with least time (with some randomness)
                drivers_with_sessions.sort(key=lambda x: x[1])
                # Pick from bottom 50% to add some randomness but still favor less experienced
                bottom_half = drivers_with_sessions[
                    : max(1, len(drivers_with_sessions) // 2)
                ]
                next_driver, drive_time = random.choice(bottom_half)
                self.log(
                    f"  Selected {next_driver.member.nickname} (has driven {drive_time/60:.1f} minutes)"
                )

            # Register them for the queue (equivalent to scanning driver_queue)
            result = self.round.driver_register(next_driver)

            if result["status"] == "ok":
                self.log(f"  {next_driver.member.nickname} added to queue")
                return True
            else:
                self.log(
                    f"  Failed to queue {next_driver.member.nickname}: {result['message']}"
                )

        except Exception as e:
            self.log(f"Driver queue failed: {e}")

        return False

    def team_in_top_queue_positions(self, team):
        """Check if team has someone in the top queue positions"""
        pending_sessions = Session.objects.filter(
            round=self.round,
            register__isnull=False,
            start__isnull=True,
            end__isnull=True,
        ).order_by("register")[
            : self.round.change_lanes
        ]  # Top N positions based on pit lanes

        return any(session.driver.team == team for session in pending_sessions)

    def team_ready_for_change(self, team):
        """Check if team is ready for driver change"""
        # Team must have someone in top queue positions
        if not self.team_in_top_queue_positions(team):
            return False

        # Team must have exactly one driver currently on track
        current_drivers = Session.objects.filter(
            round=self.round,
            driver__team=team,
            register__isnull=False,
            start__isnull=False,
            end__isnull=True,
        )

        return current_drivers.count() == 1

    def perform_driver_change(self, team, elapsed_time):
        """Perform actual driver change (driver_change equivalent)"""
        try:
            # Find the current driver on track for this team
            current_session = Session.objects.filter(
                round=self.round,
                driver__team=team,
                register__isnull=False,
                start__isnull=False,
                end__isnull=True,
            ).first()

            if not current_session:
                return False

            # Simulate pit lane delay (30-60 seconds in race time)
            pit_delay_race_time = random.uniform(30, 60)
            # Convert to wall clock time based on speed multiplier
            pit_delay_wall_time = pit_delay_race_time / self.real_time_speed
            time.sleep(pit_delay_wall_time)

            # End current driver's session (this should start the queued driver)
            result = self.round.driver_endsession(current_session.driver)

            if result["status"] == "ok":
                return True
            else:
                self.log(f"  Driver change failed: {result['message']}")

        except Exception as e:
            self.log(f"Driver change failed: {e}")

        return False

    def should_change_driver_for_time_limit(self, team, stats, elapsed_time):
        """Check if current driver should be changed due to time limits"""
        if not stats["limit_type"] or not stats["limit_value"]:
            return False  # No time limits configured

        # Get current active driver
        current_session = Session.objects.filter(
            round=self.round,
            driver__team=team,
            register__isnull=False,
            start__isnull=False,
            end__isnull=True,
        ).first()

        if not current_session:
            return False

        # Calculate current session time
        session_start_time = current_session.start.timestamp()
        race_start_time = (
            self.round.started.timestamp() if self.round.started else session_start_time
        )
        current_time = race_start_time + elapsed_time
        session_duration = current_time - session_start_time

        # Get time limit for this team (now always a timedelta)
        limit_value = stats["limit_value"]
        max_duration = limit_value

        # For teams that will violate limits, allow them to go over occasionally
        if stats["will_violate_limits"]:
            # Allow them to exceed by 10-30% sometimes
            violation_factor = random.uniform(1.1, 1.3)
            max_duration = dt.timedelta(
                seconds=max_duration.total_seconds() * violation_factor
            )
        else:
            # Normal teams stay within 95% of limit to be safe
            max_duration = dt.timedelta(seconds=max_duration.total_seconds() * 0.95)

        return dt.timedelta(seconds=session_duration) >= max_duration

    def is_normal_stint_change_time(self, team, stats, elapsed_time):
        """Check if it's time for a normal stint change (not time-limit related)"""
        # This is the original logic - just check if it's time for next queue
        return elapsed_time >= stats["next_queue_time"]

    def simulate_penalties(self, elapsed_time):
        """Randomly issue penalties (only championship-registered ones, excluding Post Race Laps)"""
        # Get penalties that can be issued during race (exclude Post Race Laps)
        all_penalties = ChampionshipPenalty.objects.filter(
            championship=self.round.championship
        ).exclude(
            sanction="P"
        )  # Post Race Laps are handled automatically at race end

        if not all_penalties:
            return None

        teams = list(self.round.round_team_set.all())

        # Check each team for potential penalty
        for team in teams:
            # Random penalty chance based on probability per hour
            hours_elapsed = elapsed_time / 3600
            penalty_chance = self.penalty_probability * (hours_elapsed / len(teams))

            if random.random() < penalty_chance:
                # Issue a random penalty from available ones
                penalty = random.choice(all_penalties)

                # Find potential victim (different team, for regular Stop & Go)
                victim = None
                if penalty.sanction == "S":  # Regular Stop & Go needs victim
                    other_teams = [t for t in teams if t != team]
                    if other_teams:
                        victim = random.choice(other_teams)

                # Create penalty with appropriate served timestamp
                served_time = None
                if (
                    penalty.sanction == "L"
                ):  # Laps are auto-served (Post Race excluded from race)
                    served_time = dt.datetime.now()

                round_penalty = RoundPenalty.objects.create(
                    round=self.round,
                    offender=team,
                    victim=victim,
                    penalty=penalty,
                    value=penalty.value,
                    imposed=dt.datetime.now(),
                    served=served_time,
                )

                # Log penalty type appropriately
                if penalty.sanction == "S":
                    penalty_type = "Stop & Go"
                elif penalty.sanction == "D":
                    penalty_type = "Self Stop & Go"
                elif penalty.sanction == "L":
                    penalty_type = "Laps"
                else:
                    penalty_type = penalty.penalty.name

                victim_str = f" (victim: team {victim.number})" if victim else ""

                if penalty.sanction in ["S", "D"]:
                    self.log(
                        f"🚨 {penalty_type} penalty issued to team {team.number}{victim_str} - needs serving"
                    )
                    return round_penalty  # Only return Stop & Go penalties for tracking
                else:
                    self.log(
                        f"📋 {penalty_type} penalty issued to team {team.number}{victim_str} - auto-handled"
                    )
                    return None  # Other penalties don't need tracking

        return None

    def serve_stop_go_penalty(self, round_penalty):
        """Simulate serving a Stop & Go penalty (equivalent to clicking 'Served' button)"""
        try:
            # Update penalty served timestamp (equivalent to /api/update-penalty-served/)
            round_penalty.served = dt.datetime.now()
            round_penalty.save()

            penalty_type = (
                "Self Stop & Go"
                if round_penalty.penalty.sanction == "D"
                else "Stop & Go"
            )
            self.log(
                f"  {penalty_type} penalty served: {round_penalty.value}s for team {round_penalty.offender.number}"
            )
            return True

        except Exception as e:
            self.log(f"Failed to serve Stop & Go penalty: {e}")
            return False

    def issue_ignoring_penalty(self, offender_team):
        """Issue 'ignoring stop & go' penalty for teams that don't serve in time"""
        try:
            # Look for "ignoring s&g" or similar penalty in championship
            ignore_penalties = ChampionshipPenalty.objects.filter(
                championship=self.round.championship,
                penalty__name__icontains="ignoring",
            ).filter(penalty__name__icontains="stop")

            if not ignore_penalties:
                # Try looking for "ignoring" and "go" separately
                ignore_penalties = ChampionshipPenalty.objects.filter(
                    championship=self.round.championship,
                    penalty__name__icontains="ignoring",
                ).filter(penalty__name__icontains="go")

            if not ignore_penalties:
                # Try just "ignoring" penalties (broader search)
                ignore_penalties = ChampionshipPenalty.objects.filter(
                    championship=self.round.championship,
                    penalty__name__icontains="ignoring",
                )

            if not ignore_penalties:
                # Finally, try any lap penalty that might be for ignoring
                ignore_penalties = ChampionshipPenalty.objects.filter(
                    championship=self.round.championship,
                    sanction="L",  # Look for Lap penalties
                    penalty__name__icontains="ignore",
                )

            if not ignore_penalties:
                return None

            # Use the first matching penalty
            ignore_penalty = ignore_penalties.first()

            # Create the ignoring penalty
            round_penalty = RoundPenalty.objects.create(
                round=self.round,
                offender=offender_team,
                victim=None,  # Ignoring penalties don't have victims
                penalty=ignore_penalty,
                value=ignore_penalty.value,
                imposed=dt.datetime.now(),
                served=dt.datetime.now()
                if ignore_penalty.sanction == "L"
                else None,  # Lap penalties are served immediately
            )

            return round_penalty

        except Exception as e:
            self.log(f"Failed to issue ignoring penalty: {e}")
            return None

    def issue_driver_change_too_long_penalty(self, offender_team, delay_seconds):
        """Issue 'driver change too long' penalty for slow pit stops"""
        try:
            # Look for "driver change too long" or similar penalty in championship
            slow_change_penalties = ChampionshipPenalty.objects.filter(
                championship=self.round.championship,
                penalty__name__icontains="driver change",
            ).filter(penalty__name__icontains="long")

            if not slow_change_penalties:
                # Also try looking for "too long" penalties
                slow_change_penalties = ChampionshipPenalty.objects.filter(
                    championship=self.round.championship,
                    penalty__name__icontains="too long",
                )

            if not slow_change_penalties:
                return None

            # Use the first matching penalty
            slow_penalty = slow_change_penalties.first()

            # Create the slow driver change penalty
            round_penalty = RoundPenalty.objects.create(
                round=self.round,
                offender=offender_team,
                victim=None,  # Driver change penalties don't have victims
                penalty=slow_penalty,
                value=slow_penalty.value,
                imposed=dt.datetime.now(),
                served=dt.datetime.now()
                if slow_penalty.sanction == "L"
                else None,  # Auto-serve if it's laps
            )

            return round_penalty

        except Exception as e:
            self.log(f"Failed to issue driver change too long penalty: {e}")
            return None

    def log_final_stats(self, team_stats):
        """Log final simulation statistics"""
        self.log("\n=== SIMULATION COMPLETE ===")
        self.log("Final team statistics:")

        for team_id, stats in team_stats.items():
            team = stats["team"]
            actual_sessions = Session.objects.filter(
                round=self.round, driver__team=team, end__isnull=False
            ).count()

            # Check for time limit violations
            violations = self.check_team_time_violations(team, stats)
            violation_str = (
                f" (⚠️ {violations} time violations)" if violations > 0 else ""
            )

            self.log(f"Team {team.number} ({team.team.team.name}):{violation_str}")
            self.log(f"  Target changes: {stats['target_changes']}")
            self.log(f"  Completed sessions: {actual_sessions}")
            self.log(f"  Required changes: {self.round.required_changes}")

            if stats["limit_type"] and stats["limit_value"]:
                # limit_value is now always a timedelta
                limit_str = f"{stats['limit_value'].total_seconds()/60:.1f} min"
                self.log(
                    f"  Time limit: {stats['limit_type']} - {limit_str} per driver"
                )

        # Log penalties
        penalties = RoundPenalty.objects.filter(round=self.round)
        served_penalties = penalties.filter(served__isnull=False)
        self.log(f"\nPenalties issued during race: {penalties.count()}")
        self.log(f"Stop & Go penalties served: {served_penalties.count()}")

        for penalty in penalties:
            served_status = "✅ SERVED" if penalty.served else "⏳ PENDING"
            penalty_type = penalty.penalty.penalty.name
            victim_info = (
                f" (victim: team {penalty.victim.number})" if penalty.victim else ""
            )
            self.log(
                f"  {penalty_type} - Team {penalty.offender.number}{victim_info} - {served_status}"
            )

        # Log driver participation statistics
        self.log(f"\n=== DRIVER PARTICIPATION ===")
        total_drivers = 0
        drivers_who_drove = 0

        for team_id, stats in team_stats.items():
            team = stats["team"]
            team_drivers = team.team_member_set.filter(driver=True)
            team_drivers_count = team_drivers.count()

            # Count how many drivers from this team actually drove
            team_drivers_who_drove = (
                Session.objects.filter(
                    round=self.round, driver__in=team_drivers, end__isnull=False
                )
                .values("driver")
                .distinct()
                .count()
            )

            total_drivers += team_drivers_count
            drivers_who_drove += team_drivers_who_drove

            self.log(
                f"Team {team.number}: {team_drivers_who_drove}/{team_drivers_count} drivers drove"
            )

            # List drivers who didn't get to drive
            drivers_who_didnt_drive = team_drivers.exclude(
                id__in=Session.objects.filter(
                    round=self.round, end__isnull=False
                ).values("driver")
            )

            if drivers_who_didnt_drive.exists():
                missing_drivers = ", ".join(
                    [d.member.nickname for d in drivers_who_didnt_drive]
                )
                self.log(f"  Drivers who didn't drive: {missing_drivers}")

        participation_rate = (
            (drivers_who_drove / total_drivers) * 100 if total_drivers > 0 else 0
        )
        self.log(
            f"\nOverall participation: {drivers_who_drove}/{total_drivers} drivers ({participation_rate:.1f}%)"
        )

    def check_team_time_violations(self, team, stats):
        """Check how many drivers in a team exceeded their time limits"""
        violations = 0

        # Get the time limit for this team
        limit_type, limit_value = self.round.driver_time_limit(team)
        if not limit_type or not limit_value:
            return 0  # No time limit set

        # Get all completed sessions for this team
        sessions = Session.objects.filter(
            round=self.round, driver__team=team, end__isnull=False
        ).select_related("driver__member")

        # Group sessions by driver and check their total time
        driver_times = {}
        for session in sessions:
            driver_id = session.driver.id
            if driver_id not in driver_times:
                driver_times[driver_id] = {
                    "total_time": dt.timedelta(0),
                    "driver_name": session.driver.member.nickname,
                }

            session_duration = session.end - session.start
            driver_times[driver_id]["total_time"] += session_duration

        # Check each driver against the time limit
        for driver_id, driver_data in driver_times.items():
            total_time = driver_data["total_time"]

            # Now limit_value is always a timedelta, so we can compare directly
            if total_time > limit_value:
                violations += 1
                self.log(
                    f"    ⚠️ Driver {driver_data['driver_name']} exceeded limit: "
                    f"{total_time.total_seconds()/60:.1f}min > {limit_value.total_seconds()/60:.1f}min"
                )

        return violations
