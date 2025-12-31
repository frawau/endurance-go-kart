"""
Management command to convert an existing championship to lap-based timing.

Usage:
    python manage.py convert_to_lap_based <championship_id> [--ending-mode MODE] [--dry-run]

Example:
    python manage.py convert_to_lap_based 5 --ending-mode CROSS_AFTER_TIME
    python manage.py convert_to_lap_based 5 --dry-run  # Preview changes without applying
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from race.models import Championship, Round, Race


class Command(BaseCommand):
    help = "Convert an existing championship to use lap-based timing system"

    def add_arguments(self, parser):
        parser.add_argument(
            "championship_id",
            type=int,
            help="ID of the championship to convert",
        )
        parser.add_argument(
            "--ending-mode",
            type=str,
            default="TIME_ONLY",
            choices=[
                "CROSS_AFTER_TIME",
                "CROSS_AFTER_LAPS",
                "QUALIFYING",
                "QUALIFYING_PLUS",
                "FULL_LAPS",
                "TIME_ONLY",
                "AUTO_TRANSFORM",
            ],
            help="Default ending mode for races (default: TIME_ONLY for backward compatibility)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without applying them",
        )

    def handle(self, *args, **options):
        championship_id = options["championship_id"]
        ending_mode = options["ending_mode"]
        dry_run = options["dry_run"]

        # Get championship
        try:
            championship = Championship.objects.get(id=championship_id)
        except Championship.DoesNotExist:
            raise CommandError(f"Championship with ID {championship_id} does not exist")

        self.stdout.write(
            self.style.WARNING(f"\nConverting Championship: {championship.name}")
        )
        self.stdout.write(f"Ending Mode: {ending_mode}")
        self.stdout.write(f"Dry Run: {dry_run}\n")

        # Check for started rounds
        started_rounds = championship.round_set.filter(started__isnull=False)
        if started_rounds.exists():
            self.stdout.write(
                self.style.ERROR(
                    f"\n❌ ERROR: Championship has {started_rounds.count()} round(s) that have already started!"
                )
            )
            self.stdout.write("Cannot convert championship with started rounds.")
            self.stdout.write(
                "Please create a new championship for lap-based timing.\n"
            )
            return

        # Get all rounds
        rounds = championship.round_set.all()
        self.stdout.write(f"Found {rounds.count()} round(s) to convert:\n")

        for round_obj in rounds:
            self.stdout.write(f"  - {round_obj.name}")
            if round_obj.ready:
                self.stdout.write(
                    self.style.WARNING("    (marked as ready but not started)")
                )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\n[DRY RUN] Would perform the following changes:\n")
            )
            self.stdout.write(
                f"1. Set championship.default_ending_mode = '{ending_mode}'"
            )
            self.stdout.write(
                "2. Set championship.default_lap_count = 100  (example, adjust as needed)"
            )
            self.stdout.write(
                "3. Set championship.default_time_limit = 4 hours  (example, adjust as needed)"
            )

            for round_obj in rounds:
                self.stdout.write(f"\n4. For round '{round_obj.name}':")
                self.stdout.write("   - Set uses_legacy_session_model = False")
                self.stdout.write("   - Create Race object (type=MAIN, sequence=1)")
                self.stdout.write(f"   - Set race.ending_mode = '{ending_mode}'")

            self.stdout.write(
                self.style.SUCCESS(
                    "\n✅ Dry run complete. Use without --dry-run to apply changes.\n"
                )
            )
            return

        # Confirm before proceeding
        if not dry_run:
            confirm = input(
                "\n⚠️  This will modify the championship and all rounds. Continue? (yes/no): "
            )
            if confirm.lower() != "yes":
                self.stdout.write(self.style.ERROR("\n❌ Conversion cancelled.\n"))
                return

        # Perform conversion
        try:
            with transaction.atomic():
                # Update championship
                championship.default_ending_mode = ending_mode
                championship.default_lap_count = 100  # Default, can be adjusted
                championship.default_time_limit = round_obj.duration if rounds else None
                championship.save()

                self.stdout.write(
                    self.style.SUCCESS(f"\n✅ Updated championship default settings")
                )

                # Convert each round
                for round_obj in rounds:
                    # Set flag to use new model
                    round_obj.uses_legacy_session_model = False
                    round_obj.save()

                    # Create single main race
                    race = Race.objects.create(
                        round=round_obj,
                        race_type="MAIN",
                        sequence_number=1,
                        ending_mode=ending_mode,
                        time_limit_override=round_obj.duration,
                    )

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✅ Converted round '{round_obj.name}' (created Race ID: {race.id})"
                        )
                    )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n🎉 Successfully converted championship '{championship.name}' to lap-based timing!"
                    )
                )
                self.stdout.write("\nNext steps:")
                self.stdout.write("1. Review championship and round settings in admin")
                self.stdout.write("2. Adjust lap counts and time limits as needed")
                self.stdout.write(
                    "3. Set up transponder assignments before starting races"
                )
                self.stdout.write(
                    "4. Use grid management interface to configure starting positions\n"
                )

        except Exception as e:
            raise CommandError(f"Conversion failed: {str(e)}")
