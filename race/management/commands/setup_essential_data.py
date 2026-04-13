from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from race.models import Config, Penalty, MandatoryPenalty


class Command(BaseCommand):
    help = "Creates essential user groups, configs, and penalties for the application"

    def handle(self, *args, **options):
        """Create essential user groups, configs, and penalties."""

        # 1. Create User Groups
        groups = ["Driver Scanner", "Queue Scanner", "Race Director", "Admin"]
        for group_name in groups:
            group, created = Group.objects.get_or_create(name=group_name)
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created group: "{group_name}"'))
            else:
                self.stdout.write(f'Group "{group_name}" already exists')

        # 2. Create Default Configs
        configs = [
            ("page size", "A4"),
            ("card size", "A6"),
            ("display timeout", "5"),
            ("sim driver change delay", "30"),
            ("driver change suspicious buffer", "30"),
            ("sg penalty suspicious buffer", "10"),
            ("sim sg penalty extra delay", "5"),
        ]
        for key, val in configs:
            config, created = Config.objects.get_or_create(
                name=key, defaults={"value": val}
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created config: "{key}" = "{val}"')
                )
            else:
                self.stdout.write(f'Config "{key}" already exists')

        # 3. Create Standard Penalties and MandatoryPenalty links
        # key → (default name, description)
        mandatory_penalties = {
            "required_changes": (
                "required changes",
                "Too few driver changes.",
            ),
            "time_limit": (
                "time limit",
                "Driving more than the maximum drive time.",
            ),
            "time_limit_min": (
                "time limit min",
                "Driving less than the minimum time required.",
            ),
            "grid_order": (
                "grid order",
                "Crossing the start line out of grid position order.",
            ),
            "ignoring_sg": (
                "ignoring s&g",
                "Ignoring a Stop & Go penalty.",
            ),
        }
        for mp_key, (name, description) in mandatory_penalties.items():
            # If already linked, skip penalty creation (name may have been changed)
            existing_mp = MandatoryPenalty.objects.filter(key=mp_key).first()
            if existing_mp:
                self.stdout.write(
                    f'Mandatory key "{mp_key}" already linked → "{existing_mp.penalty.name}"'
                )
                continue

            # Create penalty and link it
            penalty, created = Penalty.objects.get_or_create(
                name=name, defaults={"description": description}
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created penalty: "{name}"'))
            else:
                self.stdout.write(f'Penalty "{name}" already exists')

            MandatoryPenalty.objects.create(key=mp_key, penalty=penalty)
            self.stdout.write(
                self.style.SUCCESS(f'Linked mandatory key "{mp_key}" → "{name}"')
            )

        # 4. Verify all mandatory penalty keys are correctly linked
        self.stdout.write("\nMandatory penalty verification:")
        expected_keys = set(mandatory_penalties.keys())
        existing = {
            mp.key: mp.penalty.name
            for mp in MandatoryPenalty.objects.select_related("penalty").all()
        }
        ok = True
        for key in expected_keys:
            if key in existing:
                self.stdout.write(
                    self.style.SUCCESS(f'  ✓ "{key}" → "{existing[key]}"')
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f'  ✗ "{key}" — MISSING! Link it via /admin/ → Mandatory Penalties'
                    )
                )
                ok = False
        # Warn about unexpected keys
        for key in sorted(set(existing.keys()) - expected_keys):
            self.stdout.write(
                self.style.WARNING(f'  ? "{key}" → "{existing[key]}" (unexpected key)')
            )
        if ok:
            self.stdout.write(
                self.style.SUCCESS("\nEssential data setup completed successfully!")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "\nSetup completed with warnings — fix missing mandatory penalties above"
                )
            )
