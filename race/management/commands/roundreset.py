from django.core.management.base import BaseCommand
from django.db import transaction
from race.models import (
    Round,
    Race,
    Session,
    round_pause,
    ChangeLane,
    RoundPenalty,
    RoundStanding,
    PenaltyQueue,
    LapCrossing,
    RaceTransponderAssignment,
    GridPosition,
)
import datetime as dt


class Command(BaseCommand):
    help = "Reset the current round by clearing all runtime state and race data"

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
            "--dry-run",
            action="store_true",
            help="Show what would be reset without actually doing it",
        )
        parser.add_argument(
            "--round-id",
            type=int,
            default=None,
            help="Reset a specific round by ID (default: current round)",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all rounds with their IDs and exit",
        )

    def handle(self, *args, **options):
        if options["list"]:
            rounds = Round.objects.select_related("championship").order_by("-start")
            if not rounds:
                self.stdout.write("No rounds found.")
                return
            self.stdout.write(
                f"{'ID':>4}  {'Started':<8} {'Ended':<8}  {'Round':<20}  Championship"
            )
            self.stdout.write("-" * 80)
            for r in rounds:
                started = "yes" if r.started else "no"
                ended = "yes" if r.ended else "no"
                self.stdout.write(
                    f"{r.id:>4}  {started:<8} {ended:<8}  {r.name:<20}  {r.championship.name}"
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
        self.stdout.write(f"Ready:        {cround.ready}")
        self.stdout.write(f"Started:      {cround.started}")
        self.stdout.write(f"Ended:        {cround.ended}")

        races = Race.objects.filter(round=cround)

        sessions_count = Session.objects.filter(driver__team__round=cround).count()
        pauses_count = round_pause.objects.filter(round=cround).count()
        changelanes_count = ChangeLane.objects.filter(round=cround).count()
        penalty_queue_count = PenaltyQueue.objects.filter(
            round_penalty__round=cround
        ).count()
        penalties_count = RoundPenalty.objects.filter(round=cround).count()
        standings_count = RoundStanding.objects.filter(round=cround).count()
        crossings_count = LapCrossing.objects.filter(race__in=races).count()
        assignments_count = RaceTransponderAssignment.objects.filter(
            race__in=races
        ).count()
        grid_count = GridPosition.objects.filter(race__in=races).count()
        races_count = races.count()

        self.stdout.write(f"\nFound {sessions_count} sessions to delete")
        self.stdout.write(f"Found {pauses_count} pauses to delete")
        self.stdout.write(f"Found {changelanes_count} pit lanes to delete")
        self.stdout.write(
            f"Found {penalty_queue_count} penalty queue entries to delete"
        )
        self.stdout.write(f"Found {penalties_count} penalties to delete")
        self.stdout.write(f"Found {standings_count} championship standings to delete")
        self.stdout.write(f"Found {crossings_count} lap crossings to delete")
        self.stdout.write(
            f"Found {assignments_count} transponder assignments to delete"
        )
        self.stdout.write(f"Found {grid_count} grid positions to delete")
        self.stdout.write(f"Found {races_count} races to reset")

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nDRY RUN — would reset the current round by:\n"
                    "- Deleting all sessions, pauses, pit lanes\n"
                    "- Deleting all penalty queue entries and penalties\n"
                    "- Deleting all championship standings for this round\n"
                    "- Deleting all lap crossings and transponder assignments\n"
                    "- Deleting all grid positions\n"
                    "- Resetting all race flags (started/ended/ready/grid_locked)\n"
                    "- Resetting round flags (ready/started/ended/post_race_check_completed)\n\n"
                    "Run without --dry-run to actually perform the reset."
                )
            )
            return

        try:
            with transaction.atomic():
                n, _ = Session.objects.filter(driver__team__round=cround).delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {n} sessions"))

                n, _ = round_pause.objects.filter(round=cround).delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {n} pauses"))

                n, _ = ChangeLane.objects.filter(round=cround).delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {n} pit lanes"))

                n, _ = PenaltyQueue.objects.filter(round_penalty__round=cround).delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Deleted {n} penalty queue entries")
                )

                n, _ = RoundPenalty.objects.filter(round=cround).delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {n} penalties"))

                n, _ = RoundStanding.objects.filter(round=cround).delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Deleted {n} championship standings")
                )

                n, _ = LapCrossing.objects.filter(race__in=races).delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {n} lap crossings"))

                n, _ = RaceTransponderAssignment.objects.filter(race__in=races).delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Deleted {n} transponder assignments")
                )

                n, _ = GridPosition.objects.filter(race__in=races).delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {n} grid positions"))

                races.update(started=None, ended=None, ready=False, grid_locked=False)
                self.stdout.write(
                    self.style.SUCCESS(f"Reset {races_count} races to initial state")
                )

                cround.ready = False
                cround.started = None
                cround.ended = None
                cround.post_race_check_completed = False
                cround.results_confirmed = False
                cround.save()

                self.stdout.write(
                    self.style.SUCCESS(f"Round '{cround.name}' fully reset.")
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during reset: {str(e)}"))
            raise
