from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from race.models import Config, Penalty


class Command(BaseCommand):
    help = "Creates essential user groups, configs, and penalties for the application"

    def handle(self, *args, **options):
        """Create essential user groups, configs, and penalties."""

        # 1. Create User Groups
        groups = ["Driver Scanner", "Queue Scanner", "Race Director", "Admin"]
        for group_name in groups:
            group, created = Group.objects.get_or_create(name=group_name)
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created group: "{group_name}"')
                )
            else:
                self.stdout.write(f'Group "{group_name}" already exists')

        # 2. Create Default Configs
        configs = [
            ("page size", "A4"),
            ("card size", "A6"),
            ("display timeout", "5")
        ]
        for key, val in configs:
            config, created = Config.objects.get_or_create(
                name=key,
                defaults={"value": val}
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created config: "{key}" = "{val}"')
                )
            else:
                self.stdout.write(f'Config "{key}" already exists')

        # 3. Create Standard Penalties
        penalties = [
            ("time limit min", "Driving less than the minimum time required."),
            ("time limit", "Driving more than the maximum drive time."),
            ("required changes", "Too few driver changes."),
        ]
        for name, description in penalties:
            penalty, created = Penalty.objects.get_or_create(
                name=name,
                defaults={"description": description}
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created penalty: "{name}"')
                )
            else:
                self.stdout.write(f'Penalty "{name}" already exists')

        self.stdout.write(
            self.style.SUCCESS('Essential data setup completed successfully!')
        )