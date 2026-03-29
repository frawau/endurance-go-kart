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
        "Assign available transponders to teams that have none for the current race. "
        "Skips teams already assigned. Assigns in team-number order using "
        "transponders sorted by ID."
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
            help="Show what would be assigned without creating anything",
        )
        parser.add_argument(
            "--race",
            type=str,
            metavar="RACE_TYPE",
            help="Race type to assign for (e.g. Q1, MAIN). Defaults to active race.",
        )

    def handle(self, *args, **options):
        cround = self.get_current_round()
        if not cround:
            self.stdout.write(self.style.ERROR("No current round found."))
            return

        # Determine target race
        race_type = options.get("race")
        if race_type:
            target_race = cround.races.filter(race_type=race_type.upper()).first()
            if not target_race:
                self.stdout.write(
                    self.style.ERROR(
                        f"Race '{race_type.upper()}' not found in round '{cround.name}'."
                    )
                )
                return
        else:
            target_race = cround.active_race
            if target_race is None:
                target_race = cround.races.order_by("sequence_number").first()

        if target_race is None:
            self.stdout.write(self.style.ERROR("No race found for current round."))
            return

        self.stdout.write(f"Round: {cround.name}")
        self.stdout.write(f"Race:  {target_race.get_race_type_display()}")

        # All teams in the round, sorted by team number
        all_teams = list(
            round_team.objects.filter(round=cround)
            .select_related("team", "team__team")
            .order_by("team__number")
        )

        # Teams already assigned for this race
        assigned_team_ids = set(
            RaceTransponderAssignment.objects.filter(race=target_race).values_list(
                "team_id", flat=True
            )
        )

        unassigned_teams = [t for t in all_teams if t.id not in assigned_team_ids]

        if not unassigned_teams:
            self.stdout.write(
                self.style.SUCCESS("All teams already have transponder assignments.")
            )
            return

        self.stdout.write(
            f"Teams needing assignment: {len(unassigned_teams)} of {len(all_teams)}"
        )

        # Transponders already used in this race
        used_transponder_ids = set(
            RaceTransponderAssignment.objects.filter(race=target_race).values_list(
                "transponder_id", flat=True
            )
        )

        # Available active transponders not yet used in this race
        available = list(
            Transponder.objects.filter(active=True)
            .exclude(id__in=used_transponder_ids)
            .order_by("transponder_id")
        )

        if not available:
            self.stdout.write(
                self.style.ERROR(
                    "No active transponders available. Add transponders in the admin first."
                )
            )
            return

        if len(available) < len(unassigned_teams):
            self.stdout.write(
                self.style.WARNING(
                    f"Only {len(available)} transponders available for "
                    f"{len(unassigned_teams)} teams — will assign as many as possible."
                )
            )

        to_create = []
        for team, transponder in zip(unassigned_teams, available):
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
