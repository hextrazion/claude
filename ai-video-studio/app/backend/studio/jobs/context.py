"""What a running job handler gets to work with."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..services import Services


class JobContext:
    def __init__(self, job: dict, services: "Services", cancel_flags: set[int]):
        self.job = job
        self.s = services
        self._cancel_flags = cancel_flags
        self._last_progress = 0.0

    @property
    def project_id(self) -> int | None:
        return self.job.get("project_id")

    @property
    def payload(self) -> dict:
        return self.job.get("payload") or {}

    def is_cancelled(self) -> bool:
        return self.job["id"] in self._cancel_flags

    async def progress(self, fraction: float | None, message: str) -> None:
        now = time.monotonic()
        if now - self._last_progress < 0.5 and fraction not in (None, 1.0):
            return
        self._last_progress = now
        self.s.jobs.set_progress(self.job["id"], fraction, message)
        self.s.bus.publish("job", id=self.job["id"], project_id=self.project_id, progress=fraction, message=message)

    def set_external(self, external_id: str | None, provider: str | None = None) -> None:
        self.job["external_id"] = external_id
        self.s.jobs.set_external(self.job["id"], external_id, provider)

    def log(self, message: str, level: str = "info") -> None:
        self.s.activity.add(message, level=level, category=self.job["kind"], project_id=self.project_id, job_id=self.job["id"])
