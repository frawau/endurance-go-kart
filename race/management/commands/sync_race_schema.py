from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder


class Command(BaseCommand):
    help = (
        "Sync race app database schema — adds missing tables and columns "
        "without data loss. Used on rebuild when no migration files are committed."
    )

    def handle(self, *args, **options):
        race_app = apps.get_app_config("race")
        created_tables = []
        added_columns = []

        with connection.schema_editor() as editor:
            existing_tables = set(connection.introspection.table_names())

            for model in race_app.get_models():
                table_name = model._meta.db_table

                if table_name not in existing_tables:
                    editor.create_model(model)
                    created_tables.append(table_name)
                    self.stdout.write(
                        self.style.SUCCESS(f"Created table: {table_name}")
                    )
                else:
                    with connection.cursor() as cursor:
                        existing_columns = {
                            col.name
                            for col in connection.introspection.get_table_description(
                                cursor, table_name
                            )
                        }

                    for field in model._meta.local_fields:
                        if field.column not in existing_columns:
                            editor.add_field(model, field)
                            added_columns.append(f"{table_name}.{field.column}")
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Added column: {table_name}.{field.column}"
                                )
                            )

                    # Check many-to-many join tables
                    for m2m in model._meta.local_many_to_many:
                        m2m_table = m2m.remote_field.through._meta.db_table
                        if m2m_table not in existing_tables:
                            editor.create_model(m2m.remote_field.through)
                            created_tables.append(m2m_table)
                            self.stdout.write(
                                self.style.SUCCESS(f"Created M2M table: {m2m_table}")
                            )

        # Ensure 0001_initial is recorded so migrate doesn't try to re-run it
        recorder = MigrationRecorder(connection)
        if not recorder.migration_qs.filter(app="race", name="0001_initial").exists():
            recorder.record_applied("race", "0001_initial")
            self.stdout.write(
                "Marked race 0001_initial as applied in django_migrations"
            )

        if created_tables or added_columns:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Schema sync complete: {len(created_tables)} tables created, "
                    f"{len(added_columns)} columns added."
                )
            )
        else:
            self.stdout.write("Schema sync complete: nothing to do.")
