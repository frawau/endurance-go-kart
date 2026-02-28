"""
Management command: populate_round

Adds N teams (each with M drivers) to an existing round.
Each Person is used at most once in the round — no driver appears in two teams.

Usage:
    python manage.py populate_round              # uses current (first not-ended) round
    python manage.py populate_round --list       # list all rounds with IDs and exit
    python manage.py populate_round --round-id 1
    python manage.py populate_round --round-id 1 --teams 10 --min-drivers 4 --max-drivers 6
"""

import random
from django.core.management.base import BaseCommand, CommandError
from faker import Faker
from race.models import (
    Round,
    Team,
    Person,
    championship_team,
    round_team,
    team_member,
)

fake = Faker()


def _current_round():
    """Return the first not-ended round (running first, then upcoming), or None."""
    return Round.objects.filter(ended__isnull=True).order_by("start").first()


class Command(BaseCommand):
    help = "Populate a round with teams and drivers (no driver in two teams)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--round-id",
            type=int,
            default=None,
            help="ID of the Round to populate (default: current round).",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all rounds with their IDs and exit.",
        )
        parser.add_argument(
            "--teams",
            type=int,
            default=10,
            help="Number of teams to add (default: 10).",
        )
        parser.add_argument(
            "--min-drivers",
            type=int,
            default=4,
            help="Minimum drivers per team (default: 4).",
        )
        parser.add_argument(
            "--max-drivers",
            type=int,
            default=6,
            help="Maximum drivers per team (default: 6).",
        )

    def handle(self, *args, **options):
        if options["list"]:
            self._list_rounds()
            return

        round_id = options["round_id"]
        num_teams = options["teams"]
        min_drivers = options["min_drivers"]
        max_drivers = options["max_drivers"]

        if round_id is None:
            cround = _current_round()
            if cround is None:
                raise CommandError(
                    "No active or upcoming round found. "
                    "Use --round-id or --list to pick one."
                )
            self.stdout.write(f"Using current round: {cround.name} (id={cround.pk})")
            cround = Round.objects.select_related("championship").get(pk=cround.pk)
        else:
            try:
                cround = Round.objects.select_related("championship").get(pk=round_id)
            except Round.DoesNotExist:
                raise CommandError(f"Round {round_id} does not exist.")

        championship = cround.championship
        self.stdout.write(
            f'Populating round "{cround.name}" (championship: {championship.name})'
        )

        # ── People pool: exclude anyone already in this round ─────────────────
        already_in_round = set(
            team_member.objects.filter(team__round=cround).values_list(
                "member_id", flat=True
            )
        )
        available_people = list(Person.objects.exclude(pk__in=already_in_round))
        random.shuffle(available_people)

        needed = num_teams * min_drivers  # lower bound on people needed
        if len(available_people) < needed:
            raise CommandError(
                f"Not enough People in the database: need at least {needed}, "
                f"found {len(available_people)} not already in round {cround.pk}. "
                f"Run: python manage.py generate_people --number {needed - len(available_people)}"
            )

        # ── Team number pool: avoid collisions with existing numbers ──────────
        used_numbers = set(
            championship_team.objects.filter(championship=championship).values_list(
                "number", flat=True
            )
        )
        free_numbers = [n for n in range(1, 100) if n not in used_numbers]
        if len(free_numbers) < num_teams:
            raise CommandError(
                f"Not enough free team numbers (1-99) in championship. "
                f"Only {len(free_numbers)} slots left, need {num_teams}."
            )
        random.shuffle(free_numbers)

        # ── Existing Team objects we can reuse (not yet in championship) ──────
        teams_in_championship = set(
            championship_team.objects.filter(championship=championship).values_list(
                "team_id", flat=True
            )
        )
        reusable_teams = list(Team.objects.exclude(pk__in=teams_in_championship))
        random.shuffle(reusable_teams)

        # ── Create teams ──────────────────────────────────────────────────────
        people_cursor = 0

        for i in range(num_teams):
            # Get or create a Team object
            if reusable_teams:
                team_obj = reusable_teams.pop()
            else:
                team_obj = Team.objects.create(name=fake.company() + " Racing")
                self.stdout.write(f'  Created team "{team_obj.name}"')

            # Register team in championship
            number = free_numbers[i]
            ct = championship_team.objects.create(
                championship=championship,
                team=team_obj,
                number=number,
            )

            # Register team in round
            rt = round_team.objects.create(round=cround, team=ct)

            # Pick drivers
            n_drivers = random.randint(min_drivers, max_drivers)
            if people_cursor + n_drivers > len(available_people):
                n_drivers = len(available_people) - people_cursor
                if n_drivers <= 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Ran out of people after {i} teams — stopping."
                        )
                    )
                    break

            drivers = available_people[people_cursor : people_cursor + n_drivers]
            people_cursor += n_drivers

            # First driver is manager
            manager = drivers[0]
            team_member.objects.create(
                team=rt,
                member=manager,
                driver=True,
                manager=True,
                weight=round(random.uniform(50, 100), 1),
            )
            for person in drivers[1:]:
                team_member.objects.create(
                    team=rt,
                    member=person,
                    driver=True,
                    manager=False,
                    weight=round(random.uniform(50, 100), 1),
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"  #{number:02d} {team_obj.name}: {n_drivers} drivers"
                )
            )

        self.stdout.write(self.style.SUCCESS("Done."))

    def _list_rounds(self):
        rounds = Round.objects.select_related("championship").order_by("start")
        if not rounds.exists():
            self.stdout.write("No rounds found.")
            return
        current = _current_round()
        self.stdout.write(
            f"{'ID':>4}  {'Championship':<30}  {'Round':<20}  {'Start':<20}  {'Teams':>5}  Status"
        )
        self.stdout.write("-" * 100)
        for r in rounds:
            n_teams = round_team.objects.filter(round=r).count()
            if r.ended:
                status = "ended"
            elif r.started:
                status = "running"
            else:
                status = "upcoming"
            marker = " <-- current" if current and r.pk == current.pk else ""
            self.stdout.write(
                f"{r.pk:>4}  {r.championship.name:<30}  {r.name:<20}  "
                f"{str(r.start)[:19]:<20}  {n_teams:>5}  {status}{marker}"
            )
