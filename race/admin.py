# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.contrib import admin

from django.apps import apps
from django.contrib import admin
from .models import (
    Logo,
    Race,
    Transponder,
    LapCrossing,
    GridPosition,
    RaceTransponderAssignment,
    QualifyingKnockoutRule,
)

# Register your models here.


@admin.register(Logo)
class LogoAdmin(admin.ModelAdmin):
    list_display = ("name", "championship", "image")
    list_filter = ("championship",)
    search_fields = ("name",)


@admin.register(Race)
class RaceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "round",
        "race_type",
        "sequence_number",
        "ending_mode",
        "ready",
        "started",
        "ended",
        "grid_locked",
    )
    list_filter = (
        "race_type",
        "ending_mode",
        "ready",
        "grid_locked",
        "round__championship",
    )
    search_fields = ("round__name", "round__championship__name")
    readonly_fields = ("started", "ended")
    fieldsets = (
        (
            "Basic Information",
            {"fields": ("round", "race_type", "sequence_number", "depends_on_race")},
        ),
        (
            "Race Configuration",
            {
                "fields": (
                    "ending_mode",
                    "lap_count_override",
                    "time_limit_override",
                    "count_crossings_during_suspension",
                )
            },
        ),
        ("State", {"fields": ("ready", "grid_locked", "started", "ended")}),
    )


@admin.register(Transponder)
class TransponderAdmin(admin.ModelAdmin):
    list_display = ("transponder_id", "description", "active", "last_seen")
    list_filter = ("active",)
    search_fields = ("transponder_id", "description")
    ordering = ("transponder_id",)


@admin.register(LapCrossing)
class LapCrossingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "race",
        "team",
        "lap_number",
        "crossing_time",
        "lap_time",
        "is_valid",
        "is_suspicious",
        "was_split",
    )
    list_filter = (
        "is_valid",
        "is_suspicious",
        "was_split",
        "counted_during_suspension",
        "race__round__championship",
    )
    search_fields = ("team__team__name", "transponder__transponder_id")
    readonly_fields = ("crossing_time", "lap_time", "split_from")
    ordering = ("race", "team", "lap_number")
    fieldsets = (
        (
            "Crossing Information",
            {
                "fields": (
                    "race",
                    "team",
                    "transponder",
                    "lap_number",
                    "crossing_time",
                    "lap_time",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "is_valid",
                    "is_suspicious",
                    "was_split",
                    "split_from",
                    "counted_during_suspension",
                )
            },
        ),
        (
            "Session Link",
            {
                "fields": ("session",),
                "description": "Legacy session link for backward compatibility",
            },
        ),
    )


@admin.register(GridPosition)
class GridPositionAdmin(admin.ModelAdmin):
    list_display = (
        "race",
        "position",
        "team",
        "source",
        "source_race",
        "manually_overridden",
    )
    list_filter = ("source", "manually_overridden", "race__round__championship")
    search_fields = ("team__team__name", "race__round__name")
    ordering = ("race", "position")
    fieldsets = (
        ("Position", {"fields": ("race", "team", "position")}),
        ("Source", {"fields": ("source", "source_race")}),
        ("Manual Override", {"fields": ("manually_overridden", "override_reason")}),
    )


@admin.register(RaceTransponderAssignment)
class RaceTransponderAssignmentAdmin(admin.ModelAdmin):
    list_display = ("race", "team", "transponder", "kart_number", "confirmed")
    list_filter = ("confirmed", "race__round__championship")
    search_fields = ("team__team__name", "transponder__transponder_id")
    ordering = ("race", "kart_number")


@admin.register(QualifyingKnockoutRule)
class QualifyingKnockoutRuleAdmin(admin.ModelAdmin):
    list_display = (
        "qualifying_race",
        "eliminates_to_position_range_start",
        "eliminates_to_position_range_end",
        "sets_grid_positions_for",
        "grid_position_offset",
    )
    list_filter = ("qualifying_race__round__championship",)
    search_fields = (
        "qualifying_race__round__name",
        "sets_grid_positions_for__round__name",
    )
    fieldsets = (
        ("Qualifying Race", {"fields": ("qualifying_race",)}),
        (
            "Elimination Range",
            {
                "fields": (
                    "eliminates_to_position_range_start",
                    "eliminates_to_position_range_end",
                ),
                "description": "Use negative numbers to count from bottom (e.g., -5 to -1 for bottom 5)",
            },
        ),
        (
            "Target Race",
            {"fields": ("sets_grid_positions_for", "grid_position_offset")},
        ),
    )


app_models = apps.get_app_config("race").get_models()
# Models with custom admin classes that should be excluded from auto-registration
custom_admin_models = {
    "Logo",
    "Race",
    "Transponder",
    "LapCrossing",
    "GridPosition",
    "RaceTransponderAssignment",
    "QualifyingKnockoutRule",
}

for model in app_models:
    try:

        # Special processing for UserProfile
        if "UserProfile" == model.__name__:

            # The model is registered only if has specific data
            # 1 -> ID
            # 2 -> User (one-to-one) relation
            if len(model._meta.fields) > 2:
                admin.site.register(model)

        # Register to Admin (skip models with custom admin classes)
        elif model.__name__ not in custom_admin_models:
            admin.site.register(model)

    except Exception:
        pass
