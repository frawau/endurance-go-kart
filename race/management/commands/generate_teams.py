# race/management/commands/generate_teams.py
from django.core.management.base import BaseCommand
from faker import Faker
from race.models import Team
from django.core.files.base import ContentFile
from io import BytesIO
from PIL import Image
import random

fake = Faker()


class Command(BaseCommand):
    help = "Generates and saves random Team objects to the database. You can specify the number of teams."

    def add_arguments(self, parser):
        parser.add_argument(
            "--number",
            type=int,
            default=30,
            help="Number of teams to generate (default: 15)",
        )

    def handle(self, *args, **options):
        """Generates and saves random Team objects to the database."""

        num_teams = options["number"]

        for _ in range(num_teams):
            team_name = fake.company() + " Racing"
            image = Image.new(
                "RGB",
                (100, 100),
                color=(
                    random.randint(0, 255),
                    random.randint(0, 255),
                    random.randint(0, 255),
                ),
            )
            buffer = BytesIO()
            image.save(buffer, "PNG")
            buffer.seek(0)

            team = Team(name=team_name)
            team.logo.save(
                f"random_logo_{_}.png", ContentFile(buffer.read()), save=False
            )
            team.save()

            self.stdout.write(self.style.SUCCESS(f"Generated team: {team}"))
