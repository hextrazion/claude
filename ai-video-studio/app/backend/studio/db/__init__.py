"""SQLite access with a small numbered-migration runner.

Each call to :meth:`Database.connect` opens a short-lived connection. SQLite
connections are cheap, and this keeps the code safe to call from FastAPI's
thread pool and from the asyncio worker alike.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.RLock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialised write transaction (BEGIN IMMEDIATE)."""
        with self._write_lock, self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    # -- convenience helpers -------------------------------------------------
    def query(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def scalar(self, sql: str, params: tuple | dict = ()) -> Any:
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        """Run a write statement; returns lastrowid."""
        with self.transaction() as conn:
            cur = conn.execute(sql, params)
            return cur.lastrowid

    def update(self, table: str, row_id: int, fields: dict[str, Any]) -> None:
        if not fields:
            return
        _check_ident(table)
        for k in fields:
            _check_ident(k)
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", (*fields.values(), row_id))

    # -- migrations ----------------------------------------------------------
    def migrate(self) -> list[str]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        applied: list[str] = []
        with self._write_lock, self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for file in sorted(MIGRATIONS_DIR.iterdir()):
                m = _MIGRATION_RE.match(file.name)
                if not m or m.group(1) in done:
                    continue
                sql = file.read_text(encoding="utf-8")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _split_sql(sql):
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (m.group(1), utcnow()),
                    )
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                conn.execute("COMMIT")
                applied.append(file.name)
        return applied

    def schema_version(self) -> str | None:
        return self.scalar("SELECT MAX(version) FROM schema_migrations")


def _split_sql(sql: str) -> list[str]:
    # Migrations are plain DDL without semicolons inside string literals.
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _check_ident(name: str) -> None:
    if not _IDENT.match(name):
        raise ValueError(f"invalid identifier: {name!r}")
