from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Generates complete test data: teams, people, championship, rounds, and memberships."

    def add_arguments(self, parser):
        parser.add_argument(
            "--teams",
            type=int,
            default=30,
            help="Number of teams to generate (default: 30)",
        )
        parser.add_argument(
            "--people",
            type=int,
            default=150,
            help="Number of people/drivers to generate (default: 150)",
        )

    def handle(self, *args, **options):
        num_teams = options["teams"]
        num_people = options["people"]

        self.stdout.write(
            self.style.WARNING(
                "Generating complete test data for championship..."
            )
        )
        self.stdout.write("")

        # Step 1: Generate teams
        self.stdout.write(
            self.style.SUCCESS(f"Step 1/3: Generating {num_teams} teams...")
        )
        call_command("generate_teams", number=num_teams)
        self.stdout.write("")

        # Step 2: Generate people/drivers
        self.stdout.write(
            self.style.SUCCESS(f"Step 2/3: Generating {num_people} people/drivers...")
        )
        call_command("generate_people", number=num_people)
        self.stdout.write("")

        # Step 3: Create championship, rounds, and assign teams/members
        self.stdout.write(
            self.style.SUCCESS(
                "Step 3/3: Creating championship, rounds, and team assignments..."
            )
        )
        call_command("initialisedb")
        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                "✓ Test data generation complete! You can now access the championship."
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"  - {num_teams} teams created"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"  - {num_people} drivers created"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "  - 1 championship with 4 rounds created"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "  - Teams assigned to rounds with drivers"
            )
        )
