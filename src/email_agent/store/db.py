"""SQLite persistence. One file, WAL mode, short-lived connections.

Replaces the previous JSON-file queue (rewritten in full on every push/pop)
and the per-email directory queue. Everything the app remembers is here:
emails + their processing state, analysis results, alerts, sender rules,
and runtime settings.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Alert, Analysis, EmailRow, EmailStatus, SenderRule

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    message_id  TEXT NOT NULL UNIQUE,
    received_at TEXT NOT NULL,
    from_addr   TEXT NOT NULL DEFAULT '',
    subject     TEXT NOT NULL DEFAULT '',
    raw         BLOB NOT NULL,
    body_text   TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'queued',
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_emails_status ON emails(status, id);
CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received_at DESC);

CREATE TABLE IF NOT EXISTS analyses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id   INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    result     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_email ON analyses(email_id);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id   INTEGER REFERENCES emails(id) ON DELETE SET NULL,
    type       TEXT NOT NULL,
    level      TEXT NOT NULL,
    message    TEXT NOT NULL,
    details    TEXT NOT NULL DEFAULT '{}',
    read       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);

CREATE TABLE IF NOT EXISTS sender_rules (
    pattern      TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    notes        TEXT,
    added_at     TEXT NOT NULL,
    last_matched TEXT,
    match_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    """One connection per thread, reused. WAL is set once (it persists in the file)."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._write_lock = threading.Lock()
        self._local = threading.local()
        with self._conn() as c:
            c.execute("PRAGMA journal_mode = WAL")
            c.execute("PRAGMA auto_vacuum = INCREMENTAL")
            c.executescript(_SCHEMA)
            c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.path, timeout=10, isolation_level=None, check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA synchronous = NORMAL")
            self._local.conn = conn
        return conn

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        yield self._connect()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            c.execute("COMMIT")

    # ---- emails ---------------------------------------------------------

    def add_email(
        self,
        *,
        source: str,
        message_id: str,
        received_at: str,
        from_addr: str,
        subject: str,
        raw: bytes,
        body_text: str,
    ) -> int | None:
        """Insert an email. Returns the new id, or None if message_id already exists."""
        now = utcnow()
        with self._tx() as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO emails
                   (source, message_id, received_at, from_addr, subject, raw, body_text,
                    status, attempts, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,0,?,?)""",
                (
                    source,
                    message_id,
                    received_at,
                    from_addr,
                    subject,
                    raw,
                    body_text,
                    EmailStatus.QUEUED.value,
                    now,
                    now,
                ),
            )
            return cur.lastrowid if cur.rowcount else None

    def has_message(self, message_id: str) -> bool:
        with self._conn() as c:
            return (
                c.execute("SELECT 1 FROM emails WHERE message_id=?", (message_id,)).fetchone()
                is not None
            )

    def claim_queued(self, limit: int, *, exclude: set[int] | None = None) -> list[EmailRow]:
        """Atomically move up to `limit` queued emails to processing and return them.

        `exclude` lets the worker skip emails it already retried this tick so a
        failing email waits for the next poll instead of burning all attempts
        at once."""
        exclude = exclude or set()
        with self._tx() as c:
            sql = "SELECT id FROM emails WHERE status=?"
            params: list = [EmailStatus.QUEUED.value]
            if exclude:
                sql += " AND id NOT IN (" + ",".join("?" * len(exclude)) + ")"
                params += list(exclude)
            sql += " ORDER BY id LIMIT ?"
            params.append(limit)
            rows = c.execute(sql, params).fetchall()
            ids = [r["id"] for r in rows]
            if not ids:
                return []
            marks = ",".join("?" * len(ids))
            c.execute(
                f"UPDATE emails SET status=?, attempts=attempts+1, updated_at=? WHERE id IN ({marks})",
                (EmailStatus.PROCESSING.value, utcnow(), *ids),
            )
            out = c.execute(
                f"SELECT * FROM emails WHERE id IN ({marks}) ORDER BY id", ids
            ).fetchall()
            return [self._email(r) for r in out]

    def requeue_stale_processing(self) -> int:
        """On startup: anything left in 'processing' was interrupted. Put it back."""
        with self._tx() as c:
            cur = c.execute(
                "UPDATE emails SET status=?, updated_at=? WHERE status=?",
                (EmailStatus.QUEUED.value, utcnow(), EmailStatus.PROCESSING.value),
            )
            return cur.rowcount

    def set_status(self, email_id: int, status: EmailStatus, error: str | None = None) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE emails SET status=?, error=?, updated_at=? WHERE id=?",
                (status.value, error, utcnow(), email_id),
            )

    def retry_email(self, email_id: int) -> bool:
        with self._tx() as c:
            cur = c.execute(
                "UPDATE emails SET status=?, attempts=0, error=NULL, updated_at=? WHERE id=? AND status=?",
                (EmailStatus.QUEUED.value, utcnow(), email_id, EmailStatus.FAILED.value),
            )
            return cur.rowcount == 1

    def get_email(self, email_id: int) -> EmailRow | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM emails WHERE id=?", (email_id,)).fetchone()
            return self._email(r) if r else None

    def get_raw(self, email_id: int) -> bytes | None:
        with self._conn() as c:
            r = c.execute("SELECT raw FROM emails WHERE id=?", (email_id,)).fetchone()
            return bytes(r["raw"]) if r else None

    def list_emails(
        self,
        *,
        status: EmailStatus | None = None,
        limit: int = 50,
        offset: int = 0,
        q: str | None = None,
    ) -> list[EmailRow]:
        where, params = [], []
        if status:
            where.append("status=?")
            params.append(status.value)
        if q:
            where.append("(subject LIKE ? OR from_addr LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        sql = "SELECT * FROM emails"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY received_at DESC, id DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        with self._conn() as c:
            return [self._email(r) for r in c.execute(sql, params).fetchall()]

    def queue_stats(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT status, COUNT(*) AS n FROM emails GROUP BY status").fetchall()
        stats = {s.value: 0 for s in EmailStatus}
        for r in rows:
            stats[r["status"]] = r["n"]
        stats["total"] = sum(stats.values())
        return stats

    def prune(self, *, older_than_days: int) -> dict[str, int]:
        """Delete emails finished more than N days ago (analyses cascade, alerts keep history).

        Keyed on updated_at, not received_at: a backlog of old mail must not be
        deleted the moment it is processed."""
        if older_than_days <= 0:
            return {"emails": 0}
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat(timespec="seconds")
        with self._tx() as c:
            n = c.execute(
                "DELETE FROM emails WHERE status IN (?, ?) AND updated_at < ?",
                (EmailStatus.DONE.value, EmailStatus.FAILED.value, cutoff),
            ).rowcount
        if n:
            with self._conn() as c:
                c.execute("PRAGMA incremental_vacuum")
        return {"emails": n}

    @staticmethod
    def _email(r: sqlite3.Row) -> EmailRow:
        return EmailRow(
            id=r["id"],
            source=r["source"],
            message_id=r["message_id"],
            received_at=r["received_at"],
            from_addr=r["from_addr"],
            subject=r["subject"],
            body_text=r["body_text"],
            status=EmailStatus(r["status"]),
            attempts=r["attempts"],
            error=r["error"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

    # ---- analyses -------------------------------------------------------

    def add_analysis(self, email_id: int, kind: str, result: dict[str, Any]) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO analyses (email_id, kind, result, created_at) VALUES (?,?,?,?)",
                (email_id, kind, json.dumps(result, default=str), utcnow()),
            )
            return int(cur.lastrowid)

    def analyses_for(self, email_id: int) -> list[Analysis]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM analyses WHERE email_id=? ORDER BY id", (email_id,)
            ).fetchall()
        return [
            Analysis(
                id=r["id"],
                email_id=r["email_id"],
                kind=r["kind"],
                result=json.loads(r["result"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def latest_analyses(self, email_ids: list[int]) -> dict[int, dict[str, dict[str, Any]]]:
        """{email_id: {kind: result}} using the newest analysis per kind."""
        if not email_ids:
            return {}
        marks = ",".join("?" * len(email_ids))
        with self._conn() as c:
            rows = c.execute(
                f"SELECT email_id, kind, result FROM analyses WHERE email_id IN ({marks}) ORDER BY id",
                email_ids,
            ).fetchall()
        out: dict[int, dict[str, dict[str, Any]]] = {}
        for r in rows:
            out.setdefault(r["email_id"], {})[r["kind"]] = json.loads(r["result"])
        return out

    # ---- alerts ---------------------------------------------------------

    def add_alert(
        self, *, email_id: int | None, type: str, level: str, message: str, details: dict[str, Any]
    ) -> Alert:
        now = utcnow()
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO alerts (email_id, type, level, message, details, read, created_at) "
                "VALUES (?,?,?,?,?,0,?)",
                (email_id, type, level, message, json.dumps(details, default=str), now),
            )
            aid = int(cur.lastrowid)
        return Alert(
            id=aid,
            email_id=email_id,
            type=type,
            level=level,
            message=message,
            details=details,
            read=False,
            created_at=now,
        )

    def list_alerts(self, *, limit: int = 50, unread_only: bool = False) -> list[Alert]:
        sql = "SELECT * FROM alerts"
        if unread_only:
            sql += " WHERE read=0"
        sql += " ORDER BY id DESC LIMIT ?"
        with self._conn() as c:
            rows = c.execute(sql, (limit,)).fetchall()
        return [
            Alert(
                id=r["id"],
                email_id=r["email_id"],
                type=r["type"],
                level=r["level"],
                message=r["message"],
                details=json.loads(r["details"]),
                read=bool(r["read"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def mark_alert_read(self, alert_id: int, read: bool = True) -> bool:
        with self._tx() as c:
            return (
                c.execute("UPDATE alerts SET read=? WHERE id=?", (int(read), alert_id)).rowcount
                == 1
            )

    def mark_all_alerts_read(self) -> int:
        with self._tx() as c:
            return c.execute("UPDATE alerts SET read=1 WHERE read=0").rowcount

    def unread_alert_count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM alerts WHERE read=0").fetchone()[0])

    # ---- sender rules ---------------------------------------------------

    def list_rules(self) -> list[SenderRule]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM sender_rules ORDER BY added_at").fetchall()
        return [SenderRule(**dict(r)) for r in rows]

    def upsert_rule(self, pattern: str, category: str, notes: str | None = None) -> SenderRule:
        pattern = pattern.strip().lower()
        with self._tx() as c:
            c.execute(
                """INSERT INTO sender_rules (pattern, category, notes, added_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(pattern) DO UPDATE SET category=excluded.category, notes=excluded.notes""",
                (pattern, category, notes, utcnow()),
            )
            r = c.execute("SELECT * FROM sender_rules WHERE pattern=?", (pattern,)).fetchone()
        return SenderRule(**dict(r))

    def delete_rule(self, pattern: str) -> bool:
        with self._tx() as c:
            return (
                c.execute(
                    "DELETE FROM sender_rules WHERE pattern=?", (pattern.strip().lower(),)
                ).rowcount
                == 1
            )

    def touch_rule(self, pattern: str) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE sender_rules SET last_matched=?, match_count=match_count+1 WHERE pattern=?",
                (utcnow(), pattern),
            )

    # ---- settings -------------------------------------------------------

    def get_setting(self, key: str) -> Any | None:
        with self._conn() as c:
            r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else None

    def set_setting(self, key: str, value: Any) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, default=str)),
            )
