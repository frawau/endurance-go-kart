import datetime as dt
import json
import os
import subprocess
import tempfile

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = (
        "Back up the PostgreSQL database to a compressed archive. "
        "Embeds schema metadata for compatibility checks on restore."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "-o",
            "--output",
            help=(
                "Output file path. Defaults to "
                "gokart_backup_YYYYMMDD_HHMMSS.dump in the current directory."
            ),
        )

    def _get_schema_fingerprint(self):
        """Return a dict mapping table names to sorted column lists."""
        fingerprint = {}
        with connection.cursor() as cursor:
            for model in apps.get_app_config("race").get_models():
                table = model._meta.db_table
                try:
                    cols = connection.introspection.get_table_description(cursor, table)
                    fingerprint[table] = sorted(c.name for c in cols)
                except Exception:
                    pass
        return fingerprint

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        db_name = db["NAME"]
        db_user = db["USER"]
        db_host = db["HOST"]
        db_port = db["PORT"]
        db_password = db["PASSWORD"]

        if not db_name:
            raise CommandError("POSTGRES_DB not set — cannot back up.")

        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        output = options["output"] or f"gokart_backup_{timestamp}.dump"

        # Build schema fingerprint
        fingerprint = self._get_schema_fingerprint()
        meta = {
            "version": 1,
            "created": dt.datetime.now().isoformat(),
            "database": db_name,
            "tables": fingerprint,
        }

        env = os.environ.copy()
        if db_password:
            env["PGPASSWORD"] = db_password

        pg_args = ["pg_dump", "-Fc", "-d", db_name]
        if db_user:
            pg_args += ["-U", db_user]
        if db_host:
            pg_args += ["-h", db_host]
        if db_port:
            pg_args += ["-p", str(db_port)]

        self.stdout.write(f"Backing up database '{db_name}' …")

        try:
            result = subprocess.run(
                pg_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=True,
            )
        except FileNotFoundError:
            raise CommandError("pg_dump not found — is PostgreSQL client installed?")
        except subprocess.CalledProcessError as e:
            raise CommandError(f"pg_dump failed: {e.stderr.decode().strip()}")

        dump_data = result.data if hasattr(result, "data") else result.stdout

        # Write combined archive: JSON metadata line + newline + pg_dump binary
        meta_bytes = json.dumps(meta).encode("utf-8")
        separator = b"\n---GOKART_DUMP_BOUNDARY---\n"

        with open(output, "wb") as f:
            f.write(meta_bytes)
            f.write(separator)
            f.write(dump_data)

        size_mb = os.path.getsize(output) / (1024 * 1024)
        self.stdout.write(
            self.style.SUCCESS(
                f"Backup saved to {output} ({size_mb:.1f} MB, "
                f"{len(fingerprint)} tables)"
            )
        )
