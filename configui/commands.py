"""Allow-listed ``race-manager`` command runner with live output streaming.

Commands run as ``sudo -n <repo>/race-manager <subcommand>`` so that
race-manager's own internal ``sudo`` calls already execute as root. The
``/etc/sudoers.d/configui`` rule installed by ``deploy-configui`` grants the
service user passwordless access to the race-manager script only.

Set ``CONFIGUI_SUDO=0`` to drop the sudo prefix (used for local development).
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import AsyncIterator

# race-manager emits ANSI colour codes; strip them so the web log stays clean.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# name -> (race-manager argv, human label, destructive?)
COMMANDS: dict[str, tuple[list[str], str, bool]] = {
    "status": (["status"], "Show status", False),
    "start": (["start"], "Start services", False),
    "stop": (["stop"], "Stop services", True),
    "restart": (["restart"], "Restart services", True),
    "rebuild": (["rebuild"], "Rebuild & restart", True),
    "generate-secret": (["generate-secret"], "Generate secrets", True),
    "configure-stations": (["configure-stations"], "Configure stations", False),
    "enable-letsencrypt": (["enable-letsencrypt"], "Enable Let's Encrypt", True),
    "enable-manual": (["enable-manual"], "Enable manual SSL", True),
    "disable-ssl": (["disable-ssl"], "Disable SSL", True),
    "generate-cert": (["generate-cert"], "Generate certificate", True),
    "install-cert": (["install-cert"], "Install manual cert", True),
    "deploy-timing": (["deploy-timing"], "Deploy timing station", True),
    "deploy-proxy": (["deploy-proxy"], "Deploy nettag proxy", True),
    "deploy-configui": (["deploy-configui"], "Re-deploy config UI", True),
    "timing-status": (["timing-status"], "Timing status", False),
    "proxy-status": (["proxy-status"], "Proxy status", False),
}


# Display grouping for the dashboard (title -> command names, in order).
SECTIONS: list[tuple[str, list[str]]] = [
    ("Services", ["status", "start", "stop", "restart", "rebuild"]),
    ("Secrets & Stations", ["generate-secret", "configure-stations"]),
    (
        "SSL",
        [
            "enable-letsencrypt",
            "enable-manual",
            "disable-ssl",
            "generate-cert",
            "install-cert",
        ],
    ),
    (
        "Deploy",
        [
            "deploy-timing",
            "timing-status",
            "deploy-proxy",
            "proxy-status",
            "deploy-configui",
        ],
    ),
]


# Composite commands run several race-manager steps in sequence, stopping at the
# first failure. "apply-location" is what a Location switch triggers: regenerate
# station configs from the new .env (restarting timing/proxy if deployed), then
# restart the Docker app so it picks up the new .env.
COMPOSITES: dict[str, tuple[list[list[str]], str]] = {
    "apply-location": (
        [["configure-stations"], ["restart"]],
        "Apply switched location",
    ),
}


# Commands safe to run while a round is locked (they don't change config or
# touch running services).
READ_ONLY = {"status", "timing-status", "proxy-status"}


def is_allowed(name: str) -> bool:
    return name in COMMANDS or name in COMPOSITES


def is_read_only(name: str) -> bool:
    return name in READ_ONLY


def _use_sudo() -> bool:
    return os.environ.get("CONFIGUI_SUDO", "1").lower() not in ("0", "false", "no")


def _argv(repo_root: Path, sub: list[str]) -> list[str]:
    argv = [str(repo_root / "race-manager"), *sub]
    if _use_sudo():
        argv = ["sudo", "-n", *argv]
    return argv


def build_argv(repo_root: Path, name: str) -> list[str]:
    sub, _, _ = COMMANDS[name]
    return _argv(repo_root, sub)


async def _run_one(
    repo_root: Path, sub: list[str]
) -> AsyncIterator[tuple[str, int | None]]:
    """Run a single race-manager subcommand, yielding (text, returncode).

    ``returncode`` is ``None`` for streamed output lines and the integer exit
    code on the final yield.
    """
    argv = _argv(repo_root, sub)
    yield f"$ {' '.join(argv)}\n", None
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        yield _ANSI_RE.sub("", raw.decode(errors="replace")), None
    yield "", await proc.wait()


async def run(repo_root: Path, name: str) -> AsyncIterator[str]:
    """Run an allow-listed command (single or composite), yielding output lines.

    The final yielded line is a sentinel ``__EXIT__ <returncode>``. A composite
    stops at the first failing step and reports that step's code.
    """
    if name in COMPOSITES:
        steps = COMPOSITES[name][0]
    elif name in COMMANDS:
        steps = [COMMANDS[name][0]]
    else:
        yield f"refused: unknown command {name!r}\n__EXIT__ 1\n"
        return

    for sub in steps:
        async for text, rc in _run_one(repo_root, sub):
            if text:
                yield text
            if rc is not None and rc != 0:
                yield f"__EXIT__ {rc}\n"
                return
    yield "__EXIT__ 0\n"
