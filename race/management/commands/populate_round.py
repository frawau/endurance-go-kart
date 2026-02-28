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
    Race,
    Team,
    Person,
    Transponder,
    RaceTransponderAssignment,
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
        parser.add_argument(
            "--transponders-only",
            action="store_true",
            help="Skip team/driver creation; only assign transponders to existing teams.",
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

        if options["transponders_only"]:
            self._assign_transponders(cround)
            return

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

        # ── Transponders + race assignments ───────────────────────────────────
        self._assign_transponders(cround)

        self.stdout.write(self.style.SUCCESS("Done."))

    def _assign_transponders(self, cround):
        """Assign transponders from the global 25-transponder pool to teams in the round.

        Creates a RaceTransponderAssignment (confirmed=True) for the first unstarted
        race only. The end-of-race signal clones assignments to subsequent races
        automatically when each race ends.

        Idempotent — skips teams that already have an assignment in the first race.
        """
        # ── Global pool of 25 transponders ───────────────────────────────────
        POOL_SIZE = 25
        pool = []
        for i in range(1, POOL_SIZE + 1):
            t, _ = Transponder.objects.get_or_create(transponder_id=f"{100000 + i:06d}")
            pool.append(t)

        # ── Find the first unstarted race ─────────────────────────────────────
        first_race = (
            Race.objects.filter(round=cround, started__isnull=True, ended__isnull=True)
            .order_by("sequence_number")
            .first()
        )
        if not first_race:
            self.stdout.write("  No unstarted races — skipping transponder assignment.")
            return

        all_round_teams = list(round_team.objects.filter(round=cround))
        if len(all_round_teams) > POOL_SIZE:
            self.stdout.write(
                self.style.WARNING(
                    f"  {len(all_round_teams)} teams but only {POOL_SIZE} transponders — "
                    f"first {POOL_SIZE} teams will be assigned."
                )
            )
            all_round_teams = all_round_teams[:POOL_SIZE]

        # Build map of already-assigned transponders in this race so we can
        # reuse them (idempotent) and avoid double-assigning pool slots.
        already = {
            a.team_id: a.transponder
            for a in RaceTransponderAssignment.objects.filter(
                race=first_race, team__in=all_round_teams
            ).select_related("transponder")
        }
        used_transponders = set(t.pk for t in already.values())
        free_pool = [t for t in pool if t.pk not in used_transponders]
        random.shuffle(free_pool)

        n_created = 0
        for rt in all_round_teams:
            if rt.pk in already:
                continue  # already has an assignment, leave it alone
            if not free_pool:
                self.stdout.write(
                    self.style.WARNING("  Pool exhausted — remaining teams skipped.")
                )
                break
            transponder = free_pool.pop()
            RaceTransponderAssignment.objects.create(
                race=first_race,
                transponder=transponder,
                team=rt,
                kart_number=rt.number,
                confirmed=True,
            )
            n_created += 1

        # Lock the grid on the first race to match what the UI "Lock" button does.
        if n_created and not first_race.grid_locked:
            first_race.grid_locked = True
            first_race.save(update_fields=["grid_locked"])

        self.stdout.write(
            self.style.SUCCESS(
                f"  Transponder assignments: {n_created} created for "
                f'race "{first_race.get_race_type_display()}" (id={first_race.pk}); '
                f"subsequent races get assignments via end-of-race signal."
            )
        )

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
