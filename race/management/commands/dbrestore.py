import json
import os
import subprocess
import tarfile
import tempfile

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# Legacy format (version 1) used a custom binary boundary.
LEGACY_SEPARATOR = b"\n---GOKART_DUMP_BOUNDARY---\n"


class Command(BaseCommand):
    help = (
        "Restore a PostgreSQL database (and media files) from a backup "
        "created by dbbackup.  Checks schema compatibility before restoring."
    )

    def add_arguments(self, parser):
        parser.add_argument("input", help="Path to backup file (.tar.gz or .dump)")
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
        parser.add_argument(
            "--no-media",
            action="store_true",
            help="Skip restoring media files (database only).",
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
        """Parse backup file. Returns (meta_dict, dump_bytes, tar_handle_or_None)."""
        # Try tar.gz first (version 2+)
        if tarfile.is_tarfile(path):
            tar = tarfile.open(path, "r:gz")
            try:
                meta_member = tar.getmember("metadata.json")
            except KeyError:
                tar.close()
                raise CommandError(
                    "Archive missing metadata.json — not a valid gokart backup."
                )
            meta = json.loads(tar.extractfile(meta_member).read().decode("utf-8"))

            try:
                dump_member = tar.getmember("database.dump")
            except KeyError:
                tar.close()
                raise CommandError("Archive missing database.dump.")
            dump_bytes = tar.extractfile(dump_member).read()

            return meta, dump_bytes, tar

        # Fall back to legacy format (version 1)
        with open(path, "rb") as f:
            raw = f.read()

        idx = raw.find(LEGACY_SEPARATOR)
        if idx == -1:
            raise CommandError(
                "Invalid backup file — not a tar.gz archive and missing "
                "legacy metadata boundary. Was this created by dbbackup?"
            )

        meta_bytes = raw[:idx]
        dump_bytes = raw[idx + len(LEGACY_SEPARATOR) :]

        try:
            meta = json.loads(meta_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise CommandError(f"Cannot parse backup metadata: {e}")

        return meta, dump_bytes, None

    def _check_compatibility(self, backup_tables, current_tables):
        """Compare schemas. Returns (ok, messages)."""
        messages = []
        ok = True

        backup_set = set(backup_tables.keys())
        current_set = set(current_tables.keys())

        extra_in_backup = backup_set - current_set
        missing_in_backup = current_set - backup_set
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

            extra_cols = backup_cols - current_cols
            missing_cols = current_cols - backup_cols

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

    def _restore_media(self, tar):
        """Extract media files from tar archive to BASE_DIR."""
        base_dir = settings.BASE_DIR
        count = 0
        for member in tar.getmembers():
            if not member.name.startswith("media/"):
                continue
            # media/static/person/foo → static/person/foo
            rel_path = member.name[len("media/") :]
            dest = os.path.join(base_dir, rel_path)
            dest_dir = os.path.dirname(dest)
            os.makedirs(dest_dir, exist_ok=True)

            src = tar.extractfile(member)
            if src is None:
                continue
            with open(dest, "wb") as f:
                f.write(src.read())
            count += 1
        return count

    def handle(self, *args, **options):
        input_path = options["input"]
        if not os.path.isfile(input_path):
            raise CommandError(f"File not found: {input_path}")

        meta, dump_bytes, tar = self._parse_backup(input_path)

        # Show metadata
        version = meta.get("version", 1)
        self.stdout.write(f"Backup version:   {version}")
        self.stdout.write(f"Backup created:   {meta.get('created', 'unknown')}")
        self.stdout.write(f"Source database:   {meta.get('database', 'unknown')}")
        self.stdout.write(f"Tables in backup:  {len(meta.get('tables', {}))}")

        # Count media files in archive
        media_file_count = 0
        if tar:
            media_file_count = sum(
                1 for m in tar.getmembers() if m.name.startswith("media/")
            )
        self.stdout.write(f"Media files:       {media_file_count}")

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
            if tar:
                tar.close()
            return

        if not ok and not options["force"]:
            if tar:
                tar.close()
            raise CommandError(
                "Schema incompatibility detected. "
                "Use --force to restore anyway, or --info to inspect."
            )

        if not ok:
            self.stdout.write(
                self.style.WARNING("Proceeding despite incompatibilities (--force).")
            )

        # Restore database
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

        self.stdout.write(f"\nRestoring database '{db_name}' …")

        # Write dump to temp file (pg_restore reads from file for -Fc format)
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

        self.stdout.write(self.style.SUCCESS("Database restored."))

        # Restore media files
        if tar and not options["no_media"]:
            count = self._restore_media(tar)
            self.stdout.write(self.style.SUCCESS(f"Restored {count} media files."))
        elif tar and options["no_media"]:
            self.stdout.write("Skipped media restore (--no-media).")

        if tar:
            tar.close()

        self.stdout.write(self.style.SUCCESS("Restore complete."))
