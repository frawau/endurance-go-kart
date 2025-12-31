# Generated migration for lap-based timing system
# Run this migration on your Django server with: python manage.py migrate

from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("race", "0001_initial"),
    ]

    operations = [
        # Add new fields to Championship
        migrations.AddField(
            model_name="championship",
            name="default_ending_mode",
            field=models.CharField(
                max_length=32,
                default="TIME_ONLY",
                choices=[
                    ("CROSS_AFTER_TIME", "Cross After Time"),
                    ("CROSS_AFTER_LAPS", "Cross After Laps"),
                    ("QUALIFYING", "Qualifying"),
                    ("QUALIFYING_PLUS", "Qualifying Plus (F1 Style)"),
                    ("FULL_LAPS", "Full Laps"),
                    ("TIME_ONLY", "Time Only"),
                    ("AUTO_TRANSFORM", "Auto Transform"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="championship",
            name="default_lap_count",
            field=models.IntegerField(
                null=True,
                blank=True,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AddField(
            model_name="championship",
            name="default_time_limit",
            field=models.DurationField(null=True, blank=True),
        ),
        # Add new fields to Round
        migrations.AddField(
            model_name="round",
            name="uses_legacy_session_model",
            field=models.BooleanField(
                default=True,
                help_text="True = uses old Session-only model, False = uses new Race model with lap tracking",
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="lap_count_adjustment",
            field=models.IntegerField(
                null=True,
                blank=True,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="time_limit_adjustment",
            field=models.DurationField(null=True, blank=True),
        ),
        # Create Transponder model
        migrations.CreateModel(
            name="Transponder",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("transponder_id", models.CharField(max_length=32, unique=True)),
                ("description", models.CharField(max_length=128, blank=True)),
                ("active", models.BooleanField(default=True)),
                ("last_seen", models.DateTimeField(null=True, blank=True)),
            ],
            options={
                "verbose_name": "Transponder",
                "verbose_name_plural": "Transponders",
                "ordering": ["transponder_id"],
            },
        ),
        # Create Race model
        migrations.CreateModel(
            name="Race",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "race_type",
                    models.CharField(
                        max_length=16,
                        choices=[
                            ("Q1", "Qualifying 1"),
                            ("Q2", "Qualifying 2"),
                            ("Q3", "Qualifying 3"),
                            ("MAIN", "Main Race"),
                            ("PRACTICE", "Practice"),
                        ],
                    ),
                ),
                (
                    "sequence_number",
                    models.IntegerField(
                        help_text="Order within round (1=first, 2=second, etc.)",
                    ),
                ),
                (
                    "ending_mode",
                    models.CharField(
                        max_length=32,
                        choices=[
                            ("CROSS_AFTER_TIME", "Cross After Time"),
                            ("CROSS_AFTER_LAPS", "Cross After Laps"),
                            ("QUALIFYING", "Qualifying"),
                            ("QUALIFYING_PLUS", "Qualifying Plus (F1 Style)"),
                            ("FULL_LAPS", "Full Laps"),
                            ("TIME_ONLY", "Time Only"),
                            ("AUTO_TRANSFORM", "Auto Transform"),
                        ],
                    ),
                ),
                ("lap_count_override", models.IntegerField(null=True, blank=True)),
                ("time_limit_override", models.DurationField(null=True, blank=True)),
                (
                    "count_crossings_during_suspension",
                    models.BooleanField(default=False),
                ),
                ("started", models.DateTimeField(null=True, blank=True)),
                ("ended", models.DateTimeField(null=True, blank=True)),
                ("ready", models.BooleanField(default=False)),
                ("grid_locked", models.BooleanField(default=False)),
                (
                    "round",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="races",
                        to="race.Round",
                    ),
                ),
                (
                    "depends_on_race",
                    models.ForeignKey(
                        null=True,
                        blank=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="dependent_races",
                        to="race.Race",
                    ),
                ),
            ],
            options={
                "verbose_name": "Race",
                "verbose_name_plural": "Races",
                "ordering": ["round", "sequence_number"],
            },
        ),
        migrations.AlterUniqueTogether(
            name="race",
            unique_together={("round", "sequence_number")},
        ),
        # Add race field to Session (for backward compatibility)
        migrations.AddField(
            model_name="session",
            name="race",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="race.Race",
            ),
        ),
        # Create LapCrossing model
        migrations.CreateModel(
            name="LapCrossing",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("lap_number", models.IntegerField()),
                ("crossing_time", models.DateTimeField()),
                ("lap_time", models.DurationField(null=True, blank=True)),
                ("is_valid", models.BooleanField(default=True)),
                ("is_suspicious", models.BooleanField(default=False)),
                ("was_split", models.BooleanField(default=False)),
                ("counted_during_suspension", models.BooleanField(default=False)),
                (
                    "race",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lap_crossings",
                        to="race.Race",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="race.round_team",
                    ),
                ),
                (
                    "transponder",
                    models.ForeignKey(
                        null=True,
                        blank=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="race.Transponder",
                    ),
                ),
                (
                    "split_from",
                    models.ForeignKey(
                        null=True,
                        blank=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="race.LapCrossing",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        null=True,
                        blank=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="race.Session",
                    ),
                ),
            ],
            options={
                "verbose_name": "Lap Crossing",
                "verbose_name_plural": "Lap Crossings",
                "ordering": ["race", "team", "lap_number"],
            },
        ),
        migrations.AddIndex(
            model_name="lapcrossing",
            index=models.Index(
                fields=["race", "team", "lap_number"], name="race_lapcro_race_id_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="lapcrossing",
            index=models.Index(
                fields=["race", "crossing_time"], name="race_lapcro_race_cr_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="lapcrossing",
            index=models.Index(
                fields=["is_suspicious"], name="race_lapcro_is_susp_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="lapcrossing",
            index=models.Index(
                fields=["transponder", "crossing_time"], name="race_lapcro_transp_idx"
            ),
        ),
        # Create GridPosition model
        migrations.CreateModel(
            name="GridPosition",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("position", models.IntegerField()),
                (
                    "source",
                    models.CharField(
                        max_length=32,
                        choices=[
                            ("QUALIFYING", "From Qualifying"),
                            ("COMBINED_Q", "From Combined Qualifying"),
                            ("KNOCKOUT", "From Knockout Qualifying"),
                            ("CHAMPIONSHIP", "From Championship Standings"),
                            ("MANUAL", "Manual Override"),
                        ],
                    ),
                ),
                ("manually_overridden", models.BooleanField(default=False)),
                ("override_reason", models.TextField(blank=True)),
                (
                    "race",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="race.Race",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="race.round_team",
                    ),
                ),
                (
                    "source_race",
                    models.ForeignKey(
                        null=True,
                        blank=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="race.Race",
                        related_name="derived_grids",
                    ),
                ),
            ],
            options={
                "verbose_name": "Grid Position",
                "verbose_name_plural": "Grid Positions",
                "ordering": ["race", "position"],
            },
        ),
        migrations.AlterUniqueTogether(
            name="gridposition",
            unique_together={("race", "team"), ("race", "position")},
        ),
        # Create RaceTransponderAssignment model
        migrations.CreateModel(
            name="RaceTransponderAssignment",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("kart_number", models.IntegerField()),
                ("confirmed", models.BooleanField(default=False)),
                (
                    "race",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="race.Race",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="race.round_team",
                    ),
                ),
                (
                    "transponder",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="race.Transponder",
                    ),
                ),
            ],
            options={
                "verbose_name": "Race Transponder Assignment",
                "verbose_name_plural": "Race Transponder Assignments",
            },
        ),
        migrations.AlterUniqueTogether(
            name="racetransponderassignment",
            unique_together={
                ("race", "transponder"),
                ("race", "team"),
                ("race", "kart_number"),
            },
        ),
        # Create QualifyingKnockoutRule model
        migrations.CreateModel(
            name="QualifyingKnockoutRule",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "eliminates_to_position_range_start",
                    models.IntegerField(
                        help_text="Starting position for elimination (e.g., -5 for bottom 5)",
                    ),
                ),
                (
                    "eliminates_to_position_range_end",
                    models.IntegerField(
                        help_text="Ending position for elimination (e.g., -1 for last)",
                    ),
                ),
                (
                    "grid_position_offset",
                    models.IntegerField(
                        default=0,
                        help_text="Offset for grid positions in target race",
                    ),
                ),
                (
                    "qualifying_race",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="race.Race",
                        related_name="qualifyingknockoutrule_set",
                    ),
                ),
                (
                    "sets_grid_positions_for",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="race.Race",
                        related_name="knockout_sources",
                    ),
                ),
            ],
            options={
                "verbose_name": "Qualifying Knockout Rule",
                "verbose_name_plural": "Qualifying Knockout Rules",
            },
        ),
    ]
