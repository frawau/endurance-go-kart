import datetime as dt
import io
import json
import os
import subprocess
import tarfile

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# Directories under BASE_DIR that hold uploaded media (ImageField paths).
MEDIA_DIRS = ["static/person", "static/logos", "static/illustration"]


class Command(BaseCommand):
    help = (
        "Back up the PostgreSQL database and uploaded media files to a "
        "compressed tar archive.  Embeds schema metadata for compatibility "
        "checks on restore."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "-o",
            "--output",
            help=(
                "Output file path. Defaults to "
                "gokart_backup_YYYYMMDD_HHMMSS.tar.gz in the current directory."
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
        output = options["output"] or f"gokart_backup_{timestamp}.tar.gz"

        # Build schema fingerprint
        fingerprint = self._get_schema_fingerprint()
        meta = {
            "version": 2,
            "created": dt.datetime.now().isoformat(),
            "database": db_name,
            "tables": fingerprint,
            "media_dirs": MEDIA_DIRS,
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

        dump_data = result.stdout

        # Build tar.gz archive
        base_dir = settings.BASE_DIR
        media_count = 0

        with tarfile.open(output, "w:gz") as tar:
            # 1. metadata.json
            meta_bytes = json.dumps(meta, indent=2).encode("utf-8")
            info = tarfile.TarInfo(name="metadata.json")
            info.size = len(meta_bytes)
            tar.addfile(info, io.BytesIO(meta_bytes))

            # 2. database.dump (pg_dump custom format)
            info = tarfile.TarInfo(name="database.dump")
            info.size = len(dump_data)
            tar.addfile(info, io.BytesIO(dump_data))

            # 3. media files
            for media_dir in MEDIA_DIRS:
                full_path = os.path.join(base_dir, media_dir)
                if not os.path.isdir(full_path):
                    continue
                for root, dirs, files in os.walk(full_path):
                    for fname in files:
                        file_path = os.path.join(root, fname)
                        arcname = os.path.join(
                            "media", media_dir, os.path.relpath(file_path, full_path)
                        )
                        tar.add(file_path, arcname=arcname)
                        media_count += 1

        size_mb = os.path.getsize(output) / (1024 * 1024)
        self.stdout.write(
            self.style.SUCCESS(
                f"Backup saved to {output} ({size_mb:.1f} MB, "
                f"{len(fingerprint)} tables, {media_count} media files)"
            )
        )
