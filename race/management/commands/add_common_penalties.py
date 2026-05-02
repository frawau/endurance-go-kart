import os
from pathlib import Path
from django.core.management.base import BaseCommand
from django.core.files import File
from race.models import Penalty

# Penalties already created by setup_essential_data — do not recreate.
ESSENTIAL_PENALTY_NAMES = {
    "time limit min",
    "time limit",
    "required changes",
    "grid order",
}

ILLUSTRATIONS_DIR = Path(__file__).parent.parent / "illustrations"

# Common penalties observed across deployments.
# Tuple: (name, description, illustration_filename_or_None)
COMMON_PENALTIES = [
    ("A-Bumping", "Bumping into another go-kart", "penalty_Bumping"),
    ("aggressive", "Aggressive driving", "penalty_aggressive"),
    ("arguing", "Arguing with the Race Director over penalties", None),
    ("B-Squeezing", "Squeezing another go-kart", "penalty_squeezing"),
    ("crashing", "Crashing out another go-kart", "penalty_crashing"),
    (
        "driver change too long",
        "Driver change lasted longer than allowed number of laps",
        None,
    ),
    ("ignoring s&g", "Ignoring Stop and Go penalty", None),
    ("interference", "Unfairly interfering with another go-kart", None),
    (
        "leaning",
        "Leaning to force another go-kart out of its racing line.",
        "penalty_leaning",
    ),
    (
        "stealing",
        "Stealing the racing line by ignoring the ½ kart length rule.",
        "penalty_stealing",
    ),
]


class Command(BaseCommand):
    help = "Creates common racing penalties (excluding those already created by setup_essential_data)"

    def handle(self, *args, **options):
        for name, description, illustration_file in COMMON_PENALTIES:
            if name in ESSENTIAL_PENALTY_NAMES:
                self.stdout.write(
                    f'Skipping "{name}" — handled by setup_essential_data'
                )
                continue

            penalty, created = Penalty.objects.get_or_create(
                name=name, defaults={"description": description}
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f'Created penalty: "{name}"'))
            else:
                self.stdout.write(f'Penalty "{name}" already exists')
                continue

            # Attach illustration if available and not already set
            if illustration_file and not penalty.illustration:
                illustration_path = ILLUSTRATIONS_DIR / illustration_file
                if illustration_path.exists():
                    with open(illustration_path, "rb") as f:
                        penalty.illustration.save(illustration_file, File(f), save=True)
                    self.stdout.write(
                        self.style.SUCCESS(f'  Attached illustration for "{name}"')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Illustration file not found: {illustration_path}"
                        )
                    )

        self.stdout.write(self.style.SUCCESS("Common penalties setup completed."))
