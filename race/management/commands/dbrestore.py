import json
import os
import subprocess
import tempfile

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

SEPARATOR = b"\n---GOKART_DUMP_BOUNDARY---\n"


class Command(BaseCommand):
    help = (
        "Restore a PostgreSQL database from a backup created by dbbackup. "
        "Checks schema compatibility before restoring."
    )

    def add_arguments(self, parser):
        parser.add_argument("input", help="Path to backup file (.dump)")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Restore even if schema compatibility check fails.",
        )
        parser.add_argument(
            "--info",
            action="store_true",
            help="Show backup metadata and compatibility check, then exit.",
        )

    def _get_current_schema(self):
        """Return a dict mapping table names to sorted column lists."""
        schema = {}
        with connection.cursor() as cursor:
            for model in apps.get_app_config("race").get_models():
                table = model._meta.db_table
                try:
                    cols = connection.introspection.get_table_description(cursor, table)
                    schema[table] = sorted(c.name for c in cols)
                except Exception:
                    pass
        return schema

    def _parse_backup(self, path):
        """Split backup into metadata dict and pg_dump bytes."""
        with open(path, "rb") as f:
            raw = f.read()

        idx = raw.find(SEPARATOR)
        if idx == -1:
            raise CommandError(
                "Invalid backup file — missing metadata boundary. "
                "Was this created by dbbackup?"
            )

        meta_bytes = raw[:idx]
        dump_bytes = raw[idx + len(SEPARATOR) :]

        try:
            meta = json.loads(meta_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise CommandError(f"Cannot parse backup metadata: {e}")

        return meta, dump_bytes

    def _check_compatibility(self, backup_tables, current_tables):
        """Compare schemas. Returns (ok, messages)."""
        messages = []
        ok = True

        backup_set = set(backup_tables.keys())
        current_set = set(current_tables.keys())

        missing_in_backup = current_set - backup_set
        extra_in_backup = backup_set - current_set
        common = backup_set & current_set

        if extra_in_backup:
            messages.append(
                f"Tables in backup but not in current schema: "
                f"{', '.join(sorted(extra_in_backup))}"
            )
            ok = False

        if missing_in_backup:
            messages.append(
                f"Tables in current schema but not in backup: "
                f"{', '.join(sorted(missing_in_backup))}"
            )
            # New tables are fine — they'll be empty after restore

        for table in sorted(common):
            backup_cols = set(backup_tables[table])
            current_cols = set(current_tables[table])

            missing_cols = current_cols - backup_cols
            extra_cols = backup_cols - current_cols

            if extra_cols:
                messages.append(
                    f"  {table}: columns in backup but not in schema: "
                    f"{', '.join(sorted(extra_cols))}"
                )
                ok = False

            if missing_cols:
                messages.append(
                    f"  {table}: columns in schema but not in backup: "
                    f"{', '.join(sorted(missing_cols))}"
                )

        return ok, messages

    def handle(self, *args, **options):
        input_path = options["input"]
        if not os.path.isfile(input_path):
            raise CommandError(f"File not found: {input_path}")

        meta, dump_bytes = self._parse_backup(input_path)

        # Show metadata
        self.stdout.write(f"Backup created:  {meta.get('created', 'unknown')}")
        self.stdout.write(f"Source database:  {meta.get('database', 'unknown')}")
        self.stdout.write(f"Tables in backup: {len(meta.get('tables', {}))}")
        self.stdout.write(f"Metadata version: {meta.get('version', 'unknown')}")

        # Compatibility check
        backup_tables = meta.get("tables", {})
        current_tables = self._get_current_schema()

        ok, messages = self._check_compatibility(backup_tables, current_tables)

        if messages:
            self.stdout.write("\nCompatibility check:")
            for msg in messages:
                style = self.style.WARNING if ok else self.style.ERROR
                self.stdout.write(style(f"  {msg}"))
        else:
            self.stdout.write(self.style.SUCCESS("\nSchema fully compatible."))

        if options["info"]:
            return

        if not ok and not options["force"]:
            raise CommandError(
                "Schema incompatibility detected. "
                "Use --force to restore anyway, or --info to inspect."
            )

        if not ok:
            self.stdout.write(
                self.style.WARNING("Proceeding despite incompatibilities (--force).")
            )

        # Perform restore
        db = settings.DATABASES["default"]
        db_name = db["NAME"]
        db_user = db["USER"]
        db_host = db["HOST"]
        db_port = db["PORT"]
        db_password = db["PASSWORD"]

        env = os.environ.copy()
        if db_password:
            env["PGPASSWORD"] = db_password

        pg_args = ["pg_restore", "--clean", "--if-exists", "-d", db_name]
        if db_user:
            pg_args += ["-U", db_user]
        if db_host:
            pg_args += ["-h", db_host]
        if db_port:
            pg_args += ["-p", str(db_port)]

        self.stdout.write(f"\nRestoring to database '{db_name}' …")

        # Write dump to temp file (pg_restore reads from file, not stdin for -Fc)
        with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as tmp:
            tmp.write(dump_bytes)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                pg_args + [tmp_path],
                stderr=subprocess.PIPE,
                env=env,
            )
            # pg_restore returns non-zero for warnings (e.g. "table does not exist"
            # during --clean). Only report actual errors.
            if result.returncode != 0:
                stderr = result.stderr.decode().strip()
                # Filter out harmless "does not exist" warnings from --clean
                error_lines = [
                    line
                    for line in stderr.splitlines()
                    if "ERROR" in line and "does not exist" not in line
                ]
                if error_lines:
                    self.stdout.write(
                        self.style.WARNING(
                            f"pg_restore completed with warnings:\n{stderr}"
                        )
                    )
                else:
                    self.stdout.write("pg_restore completed (clean warnings only).")
        except FileNotFoundError:
            raise CommandError("pg_restore not found — is PostgreSQL client installed?")
        finally:
            os.unlink(tmp_path)

        self.stdout.write(self.style.SUCCESS("Database restored successfully."))
