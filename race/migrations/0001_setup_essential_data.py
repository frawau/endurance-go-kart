# Generated data migration for essential application data

from django.db import migrations
from django.contrib.auth.models import Group


def create_essential_data(apps, schema_editor):
    """Create essential user groups, configs, and penalties."""
    # Get models from the migration state
    Config = apps.get_model("race", "Config")
    Penalty = apps.get_model("race", "Penalty")

    # 1. Create User Groups
    groups = ["Driver Scanner", "Queue Scanner", "Race Director", "Admin"]
    for group_name in groups:
        Group.objects.get_or_create(name=group_name)

    # 2. Create Default Configs
    configs = [("page size", "A4"), ("card size", "A6"), ("display timeout", "5")]
    for key, val in configs:
        Config.objects.get_or_create(name=key, defaults={"value": val})

    # 3. Create Standard Penalties
    penalties = [
        ("time limit min", "Driving less than the minimum time required."),
        ("time limit", "Driving more than the maximum drive time."),
        ("required changes", "Too few driver changes."),
    ]
    for name, description in penalties:
        Penalty.objects.get_or_create(name=name, defaults={"description": description})


def remove_essential_data(apps, schema_editor):
    """Remove essential data (for migration rollback)."""
    # Get models from the migration state
    Config = apps.get_model("race", "Config")
    Penalty = apps.get_model("race", "Penalty")

    # Remove configs
    Config.objects.filter(
        name__in=["page size", "card size", "display timeout"]
    ).delete()

    # Remove penalties
    Penalty.objects.filter(
        name__in=["time limit min", "time limit", "required changes"]
    ).delete()

    # Remove groups
    Group.objects.filter(
        name__in=["Driver Scanner", "Queue Scanner", "Race Director", "Admin"]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        # This should depend on the initial migration that creates the models
        # You may need to adjust this based on your actual migration history
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(
            create_essential_data,
            remove_essential_data,
            atomic=True,
        ),
    ]
