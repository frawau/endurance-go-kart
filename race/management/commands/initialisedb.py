import datetime as dt
import random
from django.core.management.base import BaseCommand
from django.utils import timezone
from race.models import (
    Person,
    Team,
    Championship,
    Round,
    championship_team,
    round_team,
    team_member,
)


class Command(BaseCommand):
    help = "Creates a championship, rounds, teams, and team members."

    def handle(self, *args, **options):
        # 1. Create Championship
        current_year = timezone.now().year
        championship_name = f"Easykart Endurance Championship {current_year}"
        championship = Championship.objects.create(
            name=championship_name,
            start=dt.date(current_year, 1, 1),
            end=dt.date(current_year, 12, 31),
        )
        self.stdout.write(
            self.style.SUCCESS(f'Championship "{championship_name}" created.')
        )

        # 2. Create Rounds
        rounds = []
        start_date = dt.date.today()
        for i in range(1, 5):
            duration = dt.timedelta(hours=random.randint(4, 12))
            round_obj = Round.objects.create(
                name=f"Round {i}",
                championship=championship,
                start=start_date,
                duration=duration,
                ready=False,
                change_lanes=random.randint(1, 4),
                pitlane_open_after=dt.timedelta(minutes=random.randint(5, 15)),
                pitlane_close_before=dt.timedelta(minutes=random.randint(5, 15)),
            )

            rounds.append(round_obj)
            start_date += dt.timedelta(days=random.randint(7, 42))  # Space rounds out
            self.stdout.write(self.style.SUCCESS(f'Round "{round_obj.name}" created.'))

        # 3. Add Teams to Championship
        teams = list(Team.objects.all())
        if teams:
            used_numbers = set()
            for team in teams:
                number = random.randint(1, 99)
                while number in used_numbers:
                    number = random.randint(1, 99)
                used_numbers.add(number)
                championship_team.objects.create(
                    championship=championship, team=team, number=number
                )
                self.stdout.write(
                    self.style.SUCCESS(f'Team "{team.name}" added to championship.')
                )

            # 4. Add Round Teams
            championship_teams = list(championship_team.objects.all())
            for round_obj in rounds:
                num_round_teams = random.randint(15, 22)
                selected_championship_teams = random.sample(
                    championship_teams, min(num_round_teams, len(championship_teams))
                )
                for championship_team_obj in selected_championship_teams:
                    round_team.objects.create(
                        round=round_obj, team=championship_team_obj
                    )
                self.stdout.write(
                    self.style.SUCCESS(
                        f'{num_round_teams} round teams added to "{round_obj.name}".'
                    )
                )

            # 5. Add Team Members (with corrected logic)
            people = list(Person.objects.all())
            for round_obj in rounds:
                round_teams = round_team.objects.filter(round=round_obj)
                available_people = people[
                    :
                ]  # Make a copy to avoid modifying the original list
                for round_team_obj in round_teams:
                    num_team_members = random.randint(3, 7)
                    selected_people = []

                    for _ in range(num_team_members):
                        if (
                            not available_people
                        ):  # Check if there are still available people
                            break
                        person = random.choice(available_people)
                        selected_people.append(person)
                        available_people.remove(
                            person
                        )  # Ensure each person is unique within the round

                    if not selected_people:  # prevent error if no person is selected.
                        continue

                    manager = random.choice(selected_people)
                    selected_people.remove(manager)  # Manager is unique

                    team_member.objects.create(
                        team=round_team_obj,
                        member=manager,
                        driver=random.choice([True, False, True, True, True, True]),
                        manager=True,
                        weight=random.uniform(50, 100),
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Manager added to round team "{round_team_obj.id}".'
                        )
                    )

                    for person in selected_people:
                        team_member.objects.create(
                            team=round_team_obj,
                            member=person,
                            driver=True,
                            manager=False,
                            weight=round(random.uniform(50, 100), 1),
                        )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'{len(selected_people)} Drivers added to round team "{round_team_obj.id}".'
                        )
                    )

        # Note: User Groups, Configs, and Standard Penalties are now created
        # automatically via data migration 0001_setup_essential_data.py

        self.stdout.write(self.style.SUCCESS("All tasks completed successfully."))
