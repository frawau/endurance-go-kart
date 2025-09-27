from django.core.management.base import BaseCommand
from django.db import transaction
from race.models import (
    Round,
    Session,
    round_pause,
    ChangeLane,
    RoundPenalty,
    PenaltyQueue,
)
import datetime as dt


class Command(BaseCommand):
    help = "Reset the current round by clearing ready/started flags and deleting associated data"

    def get_current_round(self):
        """
        Get the current round using the same logic as TeamMembersView
        """
        now = dt.datetime.now()
        yesterday_start = (now - dt.timedelta(days=1)).replace(
            hour=0, minute=0, second=0
        )

        return (
            Round.objects.filter(start__gte=yesterday_start, ended__isnull=True)
            .order_by("start")
            .first()
        )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be reset without actually doing it",
        )

    def handle(self, *args, **options):
        current_round = self.get_current_round()

        if not current_round:
            self.stdout.write(self.style.ERROR("No current round found."))
            return

        self.stdout.write(f"Current round: {current_round.name}")
        self.stdout.write(f"Championship: {current_round.championship.name}")
        self.stdout.write(f"Start date: {current_round.start}")
        self.stdout.write(f"Ready: {current_round.ready}")
        self.stdout.write(f"Started: {current_round.started}")

        # Count what will be deleted
        sessions_count = Session.objects.filter(
            driver__team__round=current_round
        ).count()
        pauses_count = round_pause.objects.filter(round=current_round).count()
        changelanes_count = ChangeLane.objects.filter(round=current_round).count()
        penalties_count = RoundPenalty.objects.filter(round=current_round).count()
        penalty_queue_count = PenaltyQueue.objects.filter(
            round_penalty__round=current_round
        ).count()

        self.stdout.write(f"Found {sessions_count} sessions to delete")
        self.stdout.write(f"Found {pauses_count} pauses to delete")
        self.stdout.write(f"Found {changelanes_count} pit lanes to delete")
        self.stdout.write(f"Found {penalties_count} penalties to delete")
        self.stdout.write(
            f"Found {penalty_queue_count} penalty queue entries to delete"
        )

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN - This would reset the current round by:\n"
                    "- Setting ready=False and started=None\n"
                    "- Deleting all sessions for this round\n"
                    "- Deleting all pauses for this round\n"
                    "- Deleting all pit lanes (ChangeLane) for this round\n"
                    "- Deleting all penalty queue entries for this round\n"
                    "- Deleting all penalties for this round\n\n"
                    "Run without --dry-run to actually perform the reset."
                )
            )
            return

        # Perform the reset in a transaction
        try:
            with transaction.atomic():
                # Delete all sessions associated with this round
                deleted_sessions = Session.objects.filter(
                    driver__team__round=current_round
                ).delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Deleted {deleted_sessions[0]} sessions")
                )

                # Delete all pauses associated with this round
                deleted_pauses = round_pause.objects.filter(
                    round=current_round
                ).delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Deleted {deleted_pauses[0]} pauses")
                )

                # Delete all pit lanes (ChangeLane) associated with this round
                deleted_changelanes = ChangeLane.objects.filter(
                    round=current_round
                ).delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Deleted {deleted_changelanes[0]} pit lanes")
                )

                # Delete all penalty queue entries associated with this round
                deleted_penalty_queues = PenaltyQueue.objects.filter(
                    round_penalty__round=current_round
                ).delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Deleted {deleted_penalty_queues[0]} penalty queue entries"
                    )
                )

                # Delete all penalties associated with this round
                deleted_penalties = RoundPenalty.objects.filter(
                    round=current_round
                ).delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Deleted {deleted_penalties[0]} penalties")
                )

                # Reset the round flags
                current_round.ready = False
                current_round.started = None
                current_round.save()

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully reset round: {current_round.name}\n"
                        "- Set ready=False\n"
                        "- Set started=None"
                    )
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during reset: {str(e)}"))
            raise
