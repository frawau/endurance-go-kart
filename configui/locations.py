"""Named Location profiles: snapshot, switch and manage per-site configuration.

A Location snapshots the live ``.env`` **and** the decoder-proxy config
(``proxy/nettag-proxy.toml``) under ``<state>/locations/``, so decoder address
and client list travel with the site. Switching restores both (backing up the
current files), while **preserving this configurator's own settings**
(``CONFIGUI_PASSWORD``/``PORT``/``BIND``) so the operator stays logged in and the
service stays reachable regardless of what the saved Location held.

Applying the switched config to running services (configure-stations + restart)
is done by the caller via the ``apply-location`` command; this module only moves
files.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from envfile import EnvFile

_NAME_RE = re.compile(r"^[A-Za-z0-9 ._-]{1,64}$")

# configui's own settings are preserved across switches (never clobbered by a
# Location), so switching can't lock the operator out or move the port.
PRESERVE_KEYS = ("CONFIGUI_PASSWORD", "CONFIGUI_PORT", "CONFIGUI_BIND")


class LocationError(Exception):
    pass


def _backup(path: Path) -> None:
    if path.exists():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))


class LocationStore:
    def __init__(self, env_path: Path, state_dir: Path, proxy_path: Path | None = None):
        self.env_path = Path(env_path)
        self.proxy_path = Path(proxy_path) if proxy_path else None
        self.dir = Path(state_dir) / "locations"
        self.active_file = Path(state_dir) / "active_location"
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _validate(name: str) -> str:
        name = (name or "").strip()
        if not _NAME_RE.match(name):
            raise LocationError(
                "Name must be 1-64 chars: letters, digits, space, dot, dash, underscore."
            )
        return name

    def _path_for(self, name: str) -> Path:
        return self.dir / f"{name}.env"

    def _proxy_snapshot(self, name: str) -> Path:
        return self.dir / f"{name}.nettag-proxy.toml"

    # -- API --------------------------------------------------------------

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.env"))

    def active(self) -> str | None:
        if self.active_file.exists():
            value = self.active_file.read_text().strip()
            return value or None
        return None

    def save(self, name: str) -> None:
        name = self._validate(name)
        if not self.env_path.exists():
            raise LocationError(".env not found; nothing to save.")
        shutil.copyfile(self.env_path, self._path_for(name))
        if self.proxy_path and self.proxy_path.exists():
            shutil.copyfile(self.proxy_path, self._proxy_snapshot(name))
        self.active_file.write_text(name + "\n")

    def switch(self, name: str) -> None:
        name = self._validate(name)
        src = self._path_for(name)
        if not src.exists():
            raise LocationError(f"Location {name!r} does not exist.")

        # Capture the configurator's own (active) settings to re-apply afterwards.
        preserved: dict[str, str] = {}
        if self.env_path.exists():
            current = EnvFile(self.env_path)
            for key in PRESERVE_KEYS:
                value, active = current.get(key)
                if value and active:
                    preserved[key] = value

        _backup(self.env_path)
        shutil.copyfile(src, self.env_path)

        if preserved:
            new_env = EnvFile(self.env_path)
            for key, value in preserved.items():
                new_env.set(key, value)
            new_env.save()

        # Restore the proxy config if this Location captured one; otherwise leave
        # the current proxy config untouched (older Locations have no snapshot).
        snapshot = self._proxy_snapshot(name)
        if self.proxy_path and snapshot.exists():
            _backup(self.proxy_path)
            shutil.copyfile(snapshot, self.proxy_path)

        self.active_file.write_text(name + "\n")

    def delete(self, name: str) -> None:
        name = self._validate(name)
        path = self._path_for(name)
        if not path.exists():
            raise LocationError(f"Location {name!r} does not exist.")
        path.unlink()
        self._proxy_snapshot(name).unlink(missing_ok=True)
        if self.active() == name:
            self.active_file.write_text("")
