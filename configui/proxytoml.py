"""Read/write the decoder-proxy config (``proxy/nettag-proxy.toml``).

The proxy fans a single decoder connection out to multiple downstream clients,
so its config is an array of ``[[client]]`` tables — a poor fit for flat ``.env``
keys. This module therefore edits the TOML directly: it reads with stdlib
``tomllib`` and writes a canonical, commented file from structured data.

The co-located timing station is, by convention, the client on ``127.0.0.1``;
``race-manager deploy-proxy`` reads that client's port to repoint the timing
station at the proxy.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

LOCAL_HOSTS = ("127.0.0.1", "localhost")

DEFAULTS = {
    "upstream": {"decoder_host": "", "decoder_port": 2009},
    "downstream": {"listen_port": 2010, "resend_interval": 1.0},
    "clients": [{"host": "127.0.0.1", "port": 2011}],
    "buffer": {"db": "/var/lib/nettag-proxy/nettag_buffer.db", "cleanup_interval": 60},
    "logging": {"level": "INFO"},
}


def _fresh_defaults() -> dict:
    return {
        "upstream": dict(DEFAULTS["upstream"]),
        "downstream": dict(DEFAULTS["downstream"]),
        "clients": [dict(c) for c in DEFAULTS["clients"]],
        "buffer": dict(DEFAULTS["buffer"]),
        "logging": dict(DEFAULTS["logging"]),
    }


def load(path: str | Path) -> dict:
    data = _fresh_defaults()
    path = Path(path)
    if not path.exists():
        return data
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return data

    up = raw.get("upstream", {})
    data["upstream"]["decoder_host"] = up.get(
        "decoder_host", data["upstream"]["decoder_host"]
    )
    data["upstream"]["decoder_port"] = up.get(
        "decoder_port", data["upstream"]["decoder_port"]
    )

    dn = raw.get("downstream", {})
    data["downstream"]["listen_port"] = dn.get(
        "listen_port", data["downstream"]["listen_port"]
    )
    data["downstream"]["resend_interval"] = dn.get(
        "resend_interval", data["downstream"]["resend_interval"]
    )

    clients = raw.get("client", [])
    if clients:
        data["clients"] = [
            {"host": c.get("host", ""), "port": c.get("port", "")} for c in clients
        ]

    buf = raw.get("buffer", {})
    data["buffer"]["db"] = buf.get("db", data["buffer"]["db"])
    data["buffer"]["cleanup_interval"] = buf.get(
        "cleanup_interval", data["buffer"]["cleanup_interval"]
    )
    data["logging"]["level"] = raw.get("logging", {}).get(
        "level", data["logging"]["level"]
    )
    return data


def split_clients(data: dict) -> tuple[str | int, list[dict]]:
    """Split the client list into ``(local_port, extra_clients)``.

    The first client on a loopback host is the co-located timing station.
    """
    local_port: str | int = ""
    extras: list[dict] = []
    seen_local = False
    for c in data["clients"]:
        if not seen_local and c["host"] in LOCAL_HOSTS:
            local_port = c["port"]
            seen_local = True
        else:
            extras.append(c)
    return local_port, extras


def dump(path: str | Path, data: dict) -> None:
    lines: list[str] = [
        "# NetTag UDP Proxy Configuration",
        "# Fans out a single decoder connection to multiple downstream clients.",
        "# Managed by the Config UI — manual comments here may be overwritten on save.",
        "",
        "[upstream]",
        "# Decoder/Lantronix address",
        f'decoder_host = "{data["upstream"]["decoder_host"]}"',
        f'decoder_port = {int(data["upstream"]["decoder_port"])}',
        "",
        "[downstream]",
        "# Port to listen on for client ACKs and to send frames to clients",
        f'listen_port = {int(data["downstream"]["listen_port"])}',
        "# Seconds before resending an unACK'd frame to a client",
        f'resend_interval = {float(data["downstream"]["resend_interval"])}',
        "",
    ]
    for c in data["clients"]:
        if c["host"] in LOCAL_HOSTS:
            lines.append(
                "# Co-located timing station (kept in sync with TIMING_NETTAG_PORT)"
            )
        lines.append("[[client]]")
        lines.append(f'host = "{c["host"]}"')
        lines.append(f"port = {int(c['port'])}")
        lines.append("")
    lines += [
        "[buffer]",
        f'db = "{data["buffer"]["db"]}"',
        f'cleanup_interval = {int(data["buffer"]["cleanup_interval"])}',
        "",
        "[logging]",
        f'level = "{data["logging"]["level"]}"',
        "",
    ]
    Path(path).write_text("\n".join(lines))
