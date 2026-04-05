from django.core.management.base import BaseCommand
from race.models import (
    Round,
    RaceTransponderAssignment,
    Transponder,
    round_team,
)
import datetime as dt


class Command(BaseCommand):
    help = (
        "Assign available transponders to teams for the first race in the current round. "
        "Only runs when no assignments exist yet. The system carries assignments forward "
        "to subsequent races automatically."
    )

    def get_current_round(self):
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
            help="Show what would be assigned without creating anything",
        )

    def handle(self, *args, **options):
        cround = self.get_current_round()
        if not cround:
            self.stdout.write(self.style.ERROR("No current round found."))
            return

        # Always target the first race in the round
        target_race = cround.races.order_by("sequence_number").first()
        if target_race is None:
            self.stdout.write(self.style.ERROR("No races found for current round."))
            return

        self.stdout.write(f"Round: {cround.name}")
        self.stdout.write(f"Race:  {target_race.get_race_type_display()}")

        # Refuse to run if any assignments already exist for this race
        if RaceTransponderAssignment.objects.filter(race=target_race).exists():
            self.stdout.write(
                self.style.ERROR(
                    f"Assignments already exist for {target_race.get_race_type_display()}. "
                    "Use the admin to manage them."
                )
            )
            return

        # All teams in the round, sorted by team number
        all_teams = list(
            round_team.objects.filter(round=cround)
            .select_related("team", "team__team")
            .order_by("team__number")
        )

        if not all_teams:
            self.stdout.write(self.style.ERROR("No teams found in current round."))
            return

        self.stdout.write(f"Teams to assign: {len(all_teams)}")

        # Available active transponders, sorted by ID
        available = list(
            Transponder.objects.filter(active=True).order_by("transponder_id")
        )

        if not available:
            self.stdout.write(
                self.style.ERROR(
                    "No active transponders available. Add transponders in the admin first."
                )
            )
            return

        if len(available) < len(all_teams):
            self.stdout.write(
                self.style.WARNING(
                    f"Only {len(available)} transponders available for "
                    f"{len(all_teams)} teams — will assign as many as possible."
                )
            )

        to_create = []
        for team, transponder in zip(all_teams, available):
            self.stdout.write(
                f"  Team #{team.team.number:>3}  {team.team.team.name:<30} "
                f"→  {transponder.transponder_id}"
            )
            to_create.append(
                RaceTransponderAssignment(
                    race=target_race,
                    transponder=transponder,
                    team=team,
                    confirmed=False,
                )
            )

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY RUN — would create {len(to_create)} assignments. "
                    "Re-run without --dry-run to apply."
                )
            )
            return

        RaceTransponderAssignment.objects.bulk_create(to_create, ignore_conflicts=True)
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {len(to_create)} transponder assignments for "
                f"{target_race.get_race_type_display()}."
            )
        )
