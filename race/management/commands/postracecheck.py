from django.core.management.base import BaseCommand
from race.models import (
    Round,
    ChampionshipPenalty,
    MandatoryPenalty,
    RoundPenalty,
    team_member,
)
import datetime as dt


class Command(BaseCommand):
    help = (
        "Simulate the post-race check for a round: show the penalties it "
        "would create and why. Pass --apply to actually create them when "
        "the round has not yet had its post-race check run."
    )

    def get_current_round(self):
        now = dt.datetime.now()
        yesterday_start = (now - dt.timedelta(days=1)).replace(
            hour=0, minute=0, second=0
        )
        return (
            Round.objects.filter(start__gte=yesterday_start).order_by("start").first()
        )

    def add_arguments(self, parser):
        parser.add_argument(
            "--round-id",
            type=int,
            default=None,
            help="Check a specific round by ID (default: current round)",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all rounds with their IDs and exit",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help=(
                "After showing the simulation, run the real post-race check "
                "if the round has not already had one. Refuses to run if "
                "post_race_check_completed is already True."
            ),
        )

    def _fmt_td(self, td):
        if td is None:
            return "—"
        total = int(td.total_seconds())
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h:d}:{m:02d}:{s:02d}"
        return f"{m:d}:{s:02d}"

    def handle(self, *args, **options):
        if options["list"]:
            rounds = Round.objects.select_related("championship").order_by("-start")
            if not rounds:
                self.stdout.write("No rounds found.")
                return
            self.stdout.write(
                f"{'ID':>4}  {'Started':<8} {'Ended':<8} {'PRChk':<6}  {'Round':<20}  Championship"
            )
            self.stdout.write("-" * 90)
            for r in rounds:
                started = "yes" if r.started else "no"
                ended = "yes" if r.ended else "no"
                prc = "yes" if r.post_race_check_completed else "no"
                self.stdout.write(
                    f"{r.id:>4}  {started:<8} {ended:<8} {prc:<6}  {r.name:<20}  {r.championship.name}"
                )
            return

        if options["round_id"]:
            try:
                cround = Round.objects.get(pk=options["round_id"])
            except Round.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"Round {options['round_id']} not found.")
                )
                return
        else:
            cround = self.get_current_round()

        if not cround:
            self.stdout.write(self.style.ERROR("No current round found."))
            self.stdout.write("Use --list to see available rounds, or --round-id N.")
            return

        self.stdout.write(f"Round:        {cround.name}")
        self.stdout.write(f"Championship: {cround.championship.name}")
        self.stdout.write(f"Start date:   {cround.start}")
        self.stdout.write(f"Duration:     {self._fmt_td(cround.duration)}")
        self.stdout.write(f"Started:      {cround.started}")
        self.stdout.write(f"Ended:        {cround.ended}")
        self.stdout.write(
            f"Post-race check already completed: {cround.post_race_check_completed}"
        )

        if cround.post_race_check_completed:
            existing = RoundPenalty.objects.filter(round=cround).count()
            self.stdout.write(
                self.style.WARNING(
                    f"NOTE: post_race_check has already run; "
                    f"{existing} RoundPenalty record(s) currently exist for this round. "
                    "The simulation below shows what a fresh run would produce from the "
                    "CURRENT state (penalty creation is bypassed)."
                )
            )

        championship = cround.championship
        penalties = {}
        for mp_key in ("required_changes", "time_limit", "time_limit_min"):
            try:
                mp = MandatoryPenalty.objects.get(key=mp_key)
                penalties[mp_key] = ChampionshipPenalty.objects.get(
                    championship=championship,
                    penalty=mp.penalty,
                    sanction="P",
                )
            except (MandatoryPenalty.DoesNotExist, ChampionshipPenalty.DoesNotExist):
                penalties[mp_key] = None

        self.stdout.write("\nConfigured Post-Race-Laps penalties:")
        for key, cp in penalties.items():
            if cp:
                self.stdout.write(f"  - {key}: value={cp.value} option={cp.option}")
            else:
                self.stdout.write(f"  - {key}: not configured")

        if not any(penalties.values()):
            self.stdout.write(
                self.style.WARNING(
                    "\nNo post-race penalties configured — nothing would be created."
                )
            )
            return

        duration_hours = cround.duration.total_seconds() // 3600
        self.stdout.write(
            f"\nRace duration for per-hour calc: {int(duration_hours)} hour(s)"
        )

        total_would_create = 0
        total_laps = 0

        for team in cround.round_team_set.all().order_by("team__number"):
            self.stdout.write("")
            self.stdout.write(
                self.style.HTTP_INFO(f"Team {team.number} — {team.team.team.name}")
            )

            if penalties["required_changes"]:
                tg = team.required_changes_transgression
                req = cround.required_changes
                self.stdout.write(f"  required_changes: required={req}  shortfall={tg}")
                if tg > 0:
                    laps = penalties["required_changes"].value * tg
                    if penalties["required_changes"].option == "per_hour":
                        laps = laps * duration_hours
                    self.stdout.write(
                        self.style.WARNING(
                            f"    -> WOULD CREATE team penalty: +{int(laps)} post-race laps "
                            f"(shortfall of {tg} change(s))"
                        )
                    )
                    total_would_create += 1
                    total_laps += int(laps)
                else:
                    self.stdout.write("    OK — no required-changes shortfall")

            for driver in team.team_member_set.filter(driver=True):
                nick = driver.member.nickname
                time_spent = driver.time_spent

                if penalties["time_limit"]:
                    ltype, lval = cround.driver_time_limit(team)
                    tg = driver.limit_time_transgression
                    if ltype is not None:
                        self.stdout.write(
                            f"  driver {nick}: time_spent={self._fmt_td(time_spent)} "
                            f"limit={self._fmt_td(lval)} ({ltype}) transgressions={tg}"
                        )
                    else:
                        self.stdout.write(
                            f"  driver {nick}: time_spent={self._fmt_td(time_spent)} "
                            f"(no time limit set)"
                        )
                    if tg > 0:
                        laps = penalties["time_limit"].value * tg
                        if penalties["time_limit"].option == "per_hour":
                            laps = laps * duration_hours
                        reason = (
                            f"{tg} session(s) exceeded {self._fmt_td(lval)}"
                            if ltype == "session"
                            else f"total driving time exceeds {self._fmt_td(lval)}"
                        )
                        self.stdout.write(
                            self.style.WARNING(
                                f"    -> WOULD CREATE time-limit penalty on team {team.number}: "
                                f"+{int(laps)} post-race laps ({reason})"
                            )
                        )
                        total_would_create += 1
                        total_laps += int(laps)

                if penalties["time_limit_min"]:
                    min_limit = cround.limit_time_min
                    tg = driver.limit_time_min_transgression
                    self.stdout.write(
                        f"  driver {nick}: time_spent={self._fmt_td(time_spent)} "
                        f"min_required={self._fmt_td(min_limit)} transgressions={tg}"
                    )
                    if tg > 0:
                        laps = penalties["time_limit_min"].value * tg
                        if penalties["time_limit_min"].option == "per_hour":
                            laps = laps * duration_hours
                        self.stdout.write(
                            self.style.WARNING(
                                f"    -> WOULD CREATE min-time penalty on team {team.number}: "
                                f"+{int(laps)} post-race laps "
                                f"(drove {self._fmt_td(time_spent)} < required {self._fmt_td(min_limit)})"
                            )
                        )
                        total_would_create += 1
                        total_laps += int(laps)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Simulation complete: {total_would_create} penalty record(s) "
                f"would be created, totalling {total_laps} post-race lap(s)."
            )
        )

        if not options["apply"]:
            self.stdout.write("No changes were made to the database.")
            return

        if cround.post_race_check_completed:
            self.stdout.write(
                self.style.ERROR(
                    "\n--apply refused: post_race_check_completed is already True "
                    "for this round. Nothing applied."
                )
            )
            return

        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING("--apply set: running real post-race check...")
        )
        created = cround.post_race_check()
        self.stdout.write(
            self.style.SUCCESS(
                f"Post-race check applied: {created} penalty record(s) created."
            )
        )
