from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from race.models import Config, Penalty


class Command(BaseCommand):
    help = "Creates essential system data required for the application to function"

    def handle(self, *args, **options):
        # 1. Create User Groups
        groups = ["Driver Scanner", "Queue Scanner", "Race Director", "Admin"]
        for group_name in groups:
            group, created = Group.objects.get_or_create(name=group_name)
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Group "{group_name}" created.')
                )
            else:
                self.stdout.write(f'Group "{group_name}" already exists.')

        # 2. Create Default Configs
        configs = [
            ("page size", "A4"),
            ("card size", "A6"),
            ("display timeout", "5")
        ]
        for key, val in configs:
            config, created = Config.objects.get_or_create(
                name=key, defaults={"value": val}
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Config "{key}" = "{val}" created.')
                )
            else:
                self.stdout.write(f'Config "{key}" already exists.')

        # 3. Create Standard Penalties
        penalties = [
            ("time limit min", "Driving less than the minimum time required."),
            ("time limit", "Driving more than the maximum drive time."),
            ("required changes", "Too few driver changes."),
        ]
        for name, description in penalties:
            penalty, created = Penalty.objects.get_or_create(
                name=name, defaults={"description": description}
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Penalty "{name}" created.')
                )
            else:
                self.stdout.write(f'Penalty "{name}" already exists.')

        self.stdout.write(
            self.style.SUCCESS("Essential database setup completed successfully.")
        )