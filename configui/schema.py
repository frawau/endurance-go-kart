"""Curated description of the ``.env`` keys the GUI knows how to edit.

Derived from ``.env.example``. Each field carries enough metadata for the
frontend to render a typed, grouped form (text / password / number / select /
bool) with helpful descriptions and dropdown choices.

Keys that are *not* listed here are still preserved in the file (envfile.py
round-trips everything) — they simply do not get a dedicated input.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Field:
    key: str
    label: str
    type: str = "text"  # text | password | number | select | bool
    help: str = ""
    choices: list[str] = field(default_factory=list)
    placeholder: str = ""
    secret: bool = False  # rendered masked; has a "generate" affordance
    # Show this field only when another key currently equals a given value, e.g.
    # ("TIMING_PLUGIN_TYPE", "nettag"). Hidden fields are still submitted, so
    # switching plugin type never wipes the other plugins' settings.
    show_if: tuple[str, str] | None = None


@dataclass
class Group:
    title: str
    fields: list[Field]


LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]

SCHEMA: list[Group] = [
    Group(
        "Database",
        [
            Field("POSTGRES_USER", "Postgres user"),
            Field("POSTGRES_PASSWORD", "Postgres password", type="password"),
            Field("POSTGRES_DB", "Postgres database"),
        ],
    ),
    Group(
        "Django Admin",
        [
            Field("DJANGO_SUPERUSER_USERNAME", "Admin username"),
            Field("DJANGO_SUPERUSER_PASSWORD", "Admin password", type="password"),
        ],
    ),
    Group(
        "Security Secrets",
        [
            Field(
                "SECRET_KEY",
                "Django secret key",
                type="password",
                secret=True,
                help="Run generate-secret to (re)create all three secrets.",
            ),
            Field(
                "STOPANDGO_HMAC_SECRET",
                "Stop & Go HMAC secret",
                type="password",
                secret=True,
            ),
            Field(
                "TIMING_HMAC_SECRET", "Timing HMAC secret", type="password", secret=True
            ),
        ],
    ),
    Group(
        "Domain & Port",
        [
            Field("APP_HOSTNAME", "Public hostname", placeholder="gokart.example.com"),
            Field(
                "APP_PORT",
                "HTTP port",
                type="number",
                help="nginx listens here in HTTP-only mode.",
            ),
            Field(
                "EXTRA_ALLOWED_HOST",
                "Extra allowed host",
                help="Additional IP/hostname for Django ALLOWED_HOSTS.",
            ),
        ],
    ),
    Group(
        "SSL",
        [
            Field(
                "SSL_MODE",
                "SSL mode",
                type="select",
                choices=["none", "letsencrypt", "acme", "manual"],
            ),
            Field("SSL_EMAIL", "SSL contact email", placeholder="admin@example.com"),
            Field(
                "SSL_CERT_PATH", "Certificate path", placeholder="./ssl/fullchain.pem"
            ),
            Field("SSL_KEY_PATH", "Private key path", placeholder="./ssl/privkey.pem"),
            Field("ACME_CHALLENGE", "ACME challenge", type="select", choices=["http"]),
        ],
    ),
    Group(
        "Stop & Go Station",
        [
            Field("STOPANDGO_PORT", "Port (override)", type="number"),
            Field(
                "STOPANDGO_SECURE",
                "Secure (override)",
                type="select",
                choices=["", "true", "false"],
            ),
            Field(
                "STOPANDGO_LOG_LEVEL",
                "Log level",
                type="select",
                choices=[""] + LOG_LEVELS,
            ),
        ],
    ),
    Group(
        "Timing Station",
        [
            Field(
                "TIMING_STATION_ENABLED",
                "Enabled",
                type="select",
                choices=["", "true", "false"],
            ),
            Field(
                "TIMING_PLUGIN_TYPE",
                "Plugin",
                type="select",
                choices=["simulator", "tag", "nettag"],
            ),
            Field(
                "TIMING_MODE",
                "Timing mode",
                type="select",
                choices=["interval", "duration", "time_of_day", "own_time"],
            ),
            Field("TIMING_ROLLOVER_SECONDS", "Rollover seconds", type="number"),
            # --- Simulator plugin only ---
            Field(
                "TIMING_SIM_TRANSPONDERS",
                "Sim transponders",
                type="number",
                show_if=("TIMING_PLUGIN_TYPE", "simulator"),
            ),
            Field(
                "TIMING_SIM_LAP_MIN",
                "Sim lap min (s)",
                type="number",
                show_if=("TIMING_PLUGIN_TYPE", "simulator"),
            ),
            Field(
                "TIMING_SIM_LAP_MAX",
                "Sim lap max (s)",
                type="number",
                show_if=("TIMING_PLUGIN_TYPE", "simulator"),
            ),
            # --- TAG (serial) plugin only ---
            Field(
                "TIMING_TAG_DEVICE",
                "TAG device",
                placeholder="/dev/ttyUSB0",
                show_if=("TIMING_PLUGIN_TYPE", "tag"),
            ),
            Field(
                "TIMING_TAG_BAUD",
                "TAG baud",
                type="number",
                show_if=("TIMING_PLUGIN_TYPE", "tag"),
            ),
            Field(
                "TIMING_TAG_ENDIAN",
                "TAG endian",
                type="select",
                choices=["normal", "reversed"],
                show_if=("TIMING_PLUGIN_TYPE", "tag"),
            ),
            # --- NetTag (network decoder) plugin only ---
            Field(
                "TIMING_NETTAG_HOST",
                "NetTag host",
                placeholder="192.168.0.11",
                show_if=("TIMING_PLUGIN_TYPE", "nettag"),
            ),
            Field(
                "TIMING_NETTAG_PORT",
                "NetTag port",
                type="number",
                show_if=("TIMING_PLUGIN_TYPE", "nettag"),
            ),
            Field(
                "TIMING_NETTAG_PROTOCOL",
                "NetTag protocol",
                type="select",
                choices=["udp", "tcp"],
                show_if=("TIMING_PLUGIN_TYPE", "nettag"),
            ),
        ],
    ),
    Group(
        "Config UI",
        [
            Field(
                "CONFIGUI_PORT",
                "Config UI port",
                type="number",
                help="HTTPS port this service listens on.",
            ),
            Field("CONFIGUI_BIND", "Bind address", placeholder="0.0.0.0"),
            Field(
                "CONFIGUI_PASSWORD",
                "Config UI password",
                type="password",
                secret=True,
                help="Login password for this page. Changing it logs everyone out.",
            ),
        ],
    ),
    Group(
        "Timezone",
        [
            Field("TZ", "Timezone", placeholder="UTC"),
        ],
    ),
]


def all_fields() -> list[Field]:
    return [f for g in SCHEMA for f in g.fields]
