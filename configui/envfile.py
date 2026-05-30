"""Round-trip reader/writer for the project ``.env`` file.

The whole point of this module is to *preserve* the existing file: comments,
blank lines, ordering and commented-out keys all survive a load/save cycle.
Only the values the user actually changes are touched, mirroring the behaviour
of the ``sed`` edits performed by ``race-manager``.
"""

from __future__ import annotations

import re
from pathlib import Path

# A value made only of these characters is safe to write unquoted: it survives
# both `source .env` (bash) and docker compose's interpolation. Anything else
# (notably spaces and shell metacharacters like ! $ " etc.) is single-quoted so
# a password such as "G0 F4Ster!" doesn't break `source .env`.
_SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:@%+,=-]*$")


def shell_quote(value: str) -> str:
    """Quote *value* for a ``.env`` line if it isn't already shell-safe."""
    if _SAFE_VALUE_RE.match(value):
        return value
    # Single-quote, escaping embedded single quotes the POSIX way ('\'').
    return "'" + value.replace("'", "'\\''") + "'"


def shell_unquote(raw: str) -> str:
    """Inverse of :func:`shell_quote` for reading a ``.env`` value."""
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        inner = s[1:-1]
        if s[0] == "'":
            inner = inner.replace("'\\''", "'")
        return inner
    return raw.rstrip()


class EnvFile:
    """A line-oriented, comment-preserving view of a ``.env`` file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        text = self.path.read_text() if self.path.exists() else ""
        # splitlines() drops the trailing newline; we re-add it on save.
        self.lines: list[str] = text.splitlines()

    # -- internal helpers -------------------------------------------------

    def _active_re(self, key: str) -> re.Pattern:
        return re.compile(rf"^\s*{re.escape(key)}=(.*)$")

    def _commented_re(self, key: str) -> re.Pattern:
        return re.compile(rf"^\s*#\s*{re.escape(key)}=(.*)$")

    def _find(self, key: str) -> tuple[int | None, int | None]:
        """Return ``(active_index, commented_index)`` for *key*."""
        active_re = self._active_re(key)
        commented_re = self._commented_re(key)
        active_idx = commented_idx = None
        for i, line in enumerate(self.lines):
            if active_idx is None and active_re.match(line):
                active_idx = i
            elif commented_idx is None and commented_re.match(line):
                commented_idx = i
        return active_idx, commented_idx

    @staticmethod
    def _strip_inline_comment(value: str) -> str:
        """Drop a trailing ``   # explanation`` from a commented example value.

        Only whitespace-preceded ``#`` is treated as a comment so that values
        containing ``#`` (rare, but possible) are left intact.
        """
        return re.sub(r"\s+#.*$", "", value).strip()

    # -- public API -------------------------------------------------------

    def get(self, key: str) -> tuple[str | None, bool]:
        """Return ``(value, is_active)``.

        ``value`` is ``None`` when the key is absent entirely. ``is_active`` is
        ``True`` when the key is uncommented, ``False`` when it only exists as a
        commented default.
        """
        active_idx, commented_idx = self._find(key)
        if active_idx is not None:
            return shell_unquote(self.lines[active_idx].split("=", 1)[1]), True
        if commented_idx is not None:
            raw = self.lines[commented_idx].split("=", 1)[1]
            return shell_unquote(self._strip_inline_comment(raw)), False
        return None, False

    def set(self, key: str, value: str) -> None:
        """Set *key* to *value* as an active assignment.

        Updates the existing active line, uncomments a commented default, or
        appends a new line — in that order of preference.
        """
        active_idx, commented_idx = self._find(key)
        new_line = f"{key}={shell_quote(value)}"
        if active_idx is not None:
            self.lines[active_idx] = new_line
        elif commented_idx is not None:
            self.lines[commented_idx] = new_line
        else:
            self.lines.append(new_line)

    def save(self) -> None:
        self.path.write_text("\n".join(self.lines) + "\n")

    def as_text(self) -> str:
        return "\n".join(self.lines) + "\n"
