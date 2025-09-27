import random
import datetime
import requests
from django_countries import countries
from faker import Faker
from race.models import Person
from django.core.files.base import ContentFile
from io import BytesIO
from django.core.management.base import BaseCommand  # Import BaseCommand

fakerth = Faker(["th_TH"])
fakeren = Faker(["en_GB"])
fakerfr = Faker(["fr_FR"])
fakerjp = Faker(["ja_JP"])

fakers = [fakerth, fakeren, fakerfr, fakerjp]


class Command(BaseCommand):  # Inherit from BaseCommand
    help = "Generates and saves random Person objects to the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--number",
            type=int,
            default=150,
            help="Number of teams to generate (default: 15)",
        )

    def handle(self, *args, **options):
        """Generates and saves random Person objects to the database."""

        num_people = options["number"]  # You can adjust this

        genders = ["M", "F"]
        country_codes = [code for code, name in list(countries)]

        for _ in range(num_people):
            fake = random.choice(fakers)
            gender = random.choice(genders)
            surname = fake.last_name()
            if gender == "F":
                firstname = fake.first_name_female()
            else:
                firstname = fake.first_name_male()
            nickname = fake.user_name()
            birthdate = fake.date_between(start_date="-70y", end_date="-18y")
            country = random.choice(country_codes)
            email = fake.email()

            image = requests.get("https://thispersondoesnotexist.com/", stream=True)
            buffer = BytesIO()
            for chunk in image:
                buffer.write(chunk)
            buffer.seek(0)

            person = Person(
                surname=surname,
                firstname=firstname,
                nickname=nickname,
                gender=gender,
                birthdate=birthdate,
                country=country,
                email=email,
            )

            person.mugshot.save(
                f"random_mugshot_{_}.jpg", ContentFile(buffer.read()), save=False
            )

            person.save()
            self.stdout.write(
                self.style.SUCCESS(f"Generated person: {person}")
            )  # use self.stdout.write
