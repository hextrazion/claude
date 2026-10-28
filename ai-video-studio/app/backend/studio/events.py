"""Live updates (server-sent events) and the persistent activity log."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .db import Database, utcnow

log = logging.getLogger(__name__)


class EventBus:
    """Fan-out of small JSON events to connected browsers.

    Events are hints ("job 12 changed"); the UI refetches the real data, so a
    dropped event only delays a refresh.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, type_: str, **data: Any) -> None:
        event = {"type": type_, **data}
        loop = self._loop
        if loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._deliver(event)
        elif not loop.is_closed():
            loop.call_soon_threadsafe(self._deliver, event)

    def _deliver(self, event: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


class ActivityLog:
    def __init__(self, db: Database, bus: EventBus):
        self.db = db
        self.bus = bus

    def add(
        self,
        message: str,
        *,
        level: str = "info",
        category: str = "system",
        detail: str | None = None,
        project_id: int | None = None,
        job_id: int | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO activity(ts, level, category, message, detail, project_id, job_id) VALUES (?,?,?,?,?,?,?)",
            (utcnow(), level, category, message, detail, project_id, job_id),
        )
        getattr(log, "warning" if level == "warning" else ("error" if level == "error" else "info"))(
            "[%s] %s", category, message
        )
        self.bus.publish("activity", level=level, category=category, message=message, project_id=project_id)

    def recent(self, limit: int = 50, level: str | None = None, project_id: int | None = None) -> list[dict]:
        sql = "SELECT * FROM activity WHERE 1=1"
        params: list = []
        if level:
            sql += " AND level = ?"
            params.append(level)
        if project_id is not None:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return self.db.query(sql, tuple(params))
