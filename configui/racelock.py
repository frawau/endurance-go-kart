"""Race-state lock client.

The configurator must not change anything while a round is operationally live —
from the moment the first race's pre-race check passes until the round ends. The
Django app exposes that state at ``/api/config_lock/``; this module queries it.

Fail-open by design: if the app is unreachable we assume nothing is running (a
down app means no live round) and allow configuration — you likely need the
configurator precisely to fix a down system.
"""

from __future__ import annotations

import aiohttp

UNLOCKED_UNREACHABLE = {
    "locked": False,
    "round": None,
    "reachable": False,
    "reason": "",
}


async def lock_state(app_url: str) -> dict:
    """Return ``{locked, round, reachable, reason}`` for the running app."""
    url = app_url.rstrip("/") + "/api/config_lock/"
    try:
        timeout = aiohttp.ClientTimeout(total=1.5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return {**UNLOCKED_UNREACHABLE, "reason": f"app HTTP {resp.status}"}
                data = await resp.json()
                return {
                    "locked": bool(data.get("locked")),
                    "round": data.get("round"),
                    "reachable": True,
                    "reason": data.get("reason", ""),
                }
    except Exception as exc:  # network error, timeout, bad JSON → fail open
        return {**UNLOCKED_UNREACHABLE, "reason": str(exc)}
