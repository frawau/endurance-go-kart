"""
SQLite-backed crossing buffer for at-least-once delivery.

Every crossing is written to disk before being sent over WebSocket.
Django sends an ACK (keyed by message_id) after processing; the
station marks the row as acknowledged.  On reconnect, all un-ACK'd
rows are replayed.
"""

import sqlite3
import time
import uuid
import json
import logging
from typing import Optional

_log = logging.getLogger("CrossingBuffer")


class CrossingBuffer:
    """Disk-backed buffer that survives station crashes."""

    def __init__(self, db_path: str = "crossing_buffer.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._open()

    # ── lifecycle ────────────────────────────────────────────────

    def _open(self):
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crossings (
                message_id   TEXT PRIMARY KEY,
                payload      TEXT NOT NULL,
                created_at   REAL NOT NULL,
                acked        INTEGER NOT NULL DEFAULT 0,
                acked_at     REAL
            )
            """
        )
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── write path ───────────────────────────────────────────────

    def store(self, payload: dict) -> str:
        """
        Persist a crossing payload and return the generated message_id.

        The caller should attach this message_id to the WebSocket message
        so Django can ACK by it.
        """
        message_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO crossings (message_id, payload, created_at) VALUES (?, ?, ?)",
            (message_id, json.dumps(payload), time.time()),
        )
        self._conn.commit()
        return message_id

    # ── ack path ─────────────────────────────────────────────────

    def ack(self, message_id: str) -> bool:
        """Mark a crossing as acknowledged.  Returns True if row existed."""
        cur = self._conn.execute(
            "UPDATE crossings SET acked = 1, acked_at = ? WHERE message_id = ? AND acked = 0",
            (time.time(), message_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ── replay path ──────────────────────────────────────────────

    def get_unacked(self) -> list[tuple[str, dict]]:
        """Return all (message_id, payload) pairs not yet ACK'd, oldest first."""
        rows = self._conn.execute(
            "SELECT message_id, payload FROM crossings WHERE acked = 0 ORDER BY created_at"
        ).fetchall()
        return [(mid, json.loads(payload)) for mid, payload in rows]

    # ── cleanup ──────────────────────────────────────────────────

    def cleanup(self, max_acked_age: float = 3600.0) -> int:
        """Delete ACK'd entries older than *max_acked_age* seconds.  Returns count deleted."""
        cutoff = time.time() - max_acked_age
        cur = self._conn.execute(
            "DELETE FROM crossings WHERE acked = 1 AND acked_at < ?", (cutoff,)
        )
        self._conn.commit()
        deleted = cur.rowcount
        if deleted:
            _log.debug("Cleaned up %d old acked crossings", deleted)
        return deleted

    # ── stats ────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return buffer statistics."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS total, SUM(acked) AS acked FROM crossings"
        ).fetchone()
        total, acked = row[0], row[1] or 0
        return {"total": total, "acked": acked, "pending": total - acked}
