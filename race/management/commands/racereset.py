from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from race.models import (
    Round,
    Race,
    Session,
    round_pause,
    ChangeLane,
    RoundPenalty,
    PenaltyQueue,
    LapCrossing,
    RaceTransponderAssignment,
)
import datetime as dt


class Command(BaseCommand):
    help = (
        "Reset the last started race in the current round. "
        "Clears lap crossings, sessions, penalties, pauses, and pit lanes for that race, "
        "and unconfirms transponder assignments so they can be re-locked. "
        "Transponder assignments and grid positions are kept."
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
            "--dry-run",
            action="store_true",
            help="Show what would be reset without actually doing it",
        )

    def handle(self, *args, **options):
        cround = self.get_current_round()

        if not cround:
            self.stdout.write(self.style.ERROR("No current round found."))
            return

        # Find the last started race (highest sequence_number with started set)
        race = (
            Race.objects.filter(round=cround, started__isnull=False)
            .order_by("-sequence_number")
            .first()
        )
        if not race:
            # No race has been started — try the first ready race
            race = (
                Race.objects.filter(round=cround, ready=True)
                .order_by("sequence_number")
                .first()
            )
        if not race:
            self.stdout.write(
                self.style.ERROR(
                    "No started or ready race found for the current round."
                )
            )
            return

        race_started = race.started
        race_ended = race.ended
        now = timezone.now()

        crossings_count = LapCrossing.objects.filter(race=race).count()
        sessions_count = Session.objects.filter(round=cround, race=race).count()

        # Penalties imposed while this race was running
        penalties_qs = RoundPenalty.objects.filter(round=cround)
        if race_started:
            penalties_qs = penalties_qs.filter(
                imposed__gte=race_started,
                imposed__lte=race_ended or now,
            )
        penalties_count = penalties_qs.count()
        penalty_queue_count = PenaltyQueue.objects.filter(
            round_penalty__in=penalties_qs
        ).count()

        # Pauses that started during this race
        pauses_qs = round_pause.objects.filter(round=cround)
        if race_started:
            pauses_qs = pauses_qs.filter(start__gte=race_started)
        pauses_count = pauses_qs.count()

        # Pit lane (ChangeLane) records are round-level, delete all for the round
        changelanes_count = ChangeLane.objects.filter(round=cround).count()

        confirmed_assignments = RaceTransponderAssignment.objects.filter(
            race=race, confirmed=True
        ).count()

        self.stdout.write(f"Round:      {cround.name}")
        self.stdout.write(
            f"Race:       {race.get_race_type_display()} "
            f"(seq {race.sequence_number})"
        )
        self.stdout.write(f"Started:    {race_started}")
        self.stdout.write(f"Ended:      {race_ended}")
        self.stdout.write(f"\nFound {crossings_count} lap crossings to delete")
        self.stdout.write(f"Found {sessions_count} sessions to delete")
        self.stdout.write(f"Found {pauses_count} pauses to delete")
        self.stdout.write(f"Found {changelanes_count} pit lanes to delete")
        self.stdout.write(
            f"Found {penalty_queue_count} penalty queue entries to delete"
        )
        self.stdout.write(f"Found {penalties_count} race penalties to delete")
        self.stdout.write(
            f"Found {confirmed_assignments} transponder assignments to unconfirm "
            f"(assignments kept, lock removed)"
        )

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nDRY RUN — would reset the race by:\n"
                    "- Deleting all lap crossings for this race\n"
                    "- Deleting sessions linked to this race\n"
                    "- Deleting pauses that started during this race\n"
                    "- Deleting all pit lane (ChangeLane) records for the round\n"
                    "- Deleting penalty queue entries and penalties imposed during this race\n"
                    "- Unconfirming transponder assignments (assignments kept)\n"
                    "- Resetting race: started=None, ended=None, ready=False\n"
                    "- Resetting Round.ended/started if appropriate\n\n"
                    "Grid positions are preserved.\n"
                    "Run without --dry-run to actually perform the reset."
                )
            )
            return

        try:
            with transaction.atomic():
                n, _ = LapCrossing.objects.filter(race=race).delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {n} lap crossings"))

                n, _ = Session.objects.filter(round=cround, race=race).delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {n} sessions"))

                n, _ = pauses_qs.delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {n} pauses"))

                n, _ = ChangeLane.objects.filter(round=cround).delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {n} pit lanes"))

                n, _ = PenaltyQueue.objects.filter(
                    round_penalty__in=penalties_qs
                ).delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Deleted {n} penalty queue entries")
                )

                n, _ = penalties_qs.delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {n} race penalties"))

                n = RaceTransponderAssignment.objects.filter(
                    race=race, confirmed=True
                ).update(confirmed=False)
                self.stdout.write(
                    self.style.SUCCESS(f"Unconfirmed {n} transponder assignments")
                )

                race.started = None
                race.ended = None
                race.ready = False
                race.grid_locked = False
                race.save()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Reset race '{race.get_race_type_display()}' "
                        f"(started=None, ended=None, ready=False)"
                    )
                )

                # Reset Round.ended if it was set by this race ending
                if cround.ended is not None:
                    cround.ended = None
                    cround.post_race_check_completed = False
                    cround.save()
                    self.stdout.write(
                        self.style.SUCCESS(
                            "Reset round ended/post_race_check_completed"
                        )
                    )

                # Reset Round.started if this was the only started race
                other_started = cround.races.filter(started__isnull=False).exists()
                if not other_started and cround.started is not None:
                    cround.started = None
                    cround.ready = False
                    cround.save()
                    self.stdout.write(
                        self.style.SUCCESS("Reset round started (was the first race)")
                    )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"\nRace reset complete. "
                        f"Transponder assignments are kept but unlocked — "
                        f"re-lock when ready to start again."
                    )
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during reset: {str(e)}"))
            raise
