"""Persistent job records (the queue lives in SQLite, not in memory)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import Database, dumps, loads, utcnow
from ..errors import ValidationFailed

LANES = {
    "ideas": "api",
    "research": "api",
    "script": "api",
    "factcheck": "api",
    "scene_plan": "api",
    "narration": "api",
    "scene_image": "gpu",
    "scene_clip": "gpu",
    "assemble": "cpu",
    "style_analysis": "api",
}

KIND_LABELS = {
    "ideas": "Generate ideas",
    "research": "Research",
    "script": "Write script",
    "factcheck": "Check claims",
    "scene_plan": "Plan scenes",
    "narration": "Narration",
    "scene_image": "Scene still",
    "scene_clip": "Scene clip",
    "assemble": "Assemble video",
    "style_analysis": "Analyse style",
}

ACTIVE = ("pending", "running", "paused")


def _decode(row: dict | None) -> dict | None:
    if row is None:
        return None
    row = dict(row)
    row["payload"] = loads(row.pop("payload_json"), {})
    row["result"] = loads(row.pop("result_json"), None)
    row["label"] = KIND_LABELS.get(row["kind"], row["kind"])
    return row


class JobRepo:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        kind: str,
        *,
        project_id: int | None = None,
        scene_id: int | None = None,
        payload: dict | None = None,
        max_attempts: int = 3,
        provider: str | None = None,
        front: bool = False,
    ) -> int:
        if kind not in LANES:
            raise ValidationFailed(f"Unknown job kind {kind}")
        now = utcnow()
        with self.db.transaction() as conn:
            if front:
                pos = (conn.execute("SELECT MIN(position) FROM jobs WHERE status IN ('pending','paused')").fetchone()[0] or 1) - 1
            else:
                pos = (conn.execute("SELECT MAX(position) FROM jobs").fetchone()[0] or 0) + 1
            cur = conn.execute(
                "INSERT INTO jobs(project_id, scene_id, kind, lane, status, position, max_attempts, payload_json,"
                " provider, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (project_id, scene_id, kind, LANES[kind], "pending", pos, max_attempts, dumps(payload or {}),
                 provider, now, now),
            )
            return cur.lastrowid

    def get(self, job_id: int) -> dict | None:
        return _decode(self.db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,)))

    def require(self, job_id: int) -> dict:
        job = self.get(job_id)
        if not job:
            raise ValidationFailed("Job not found.")
        return job

    def list(self, *, status: str | list[str] | None = None, project_id: int | None = None, limit: int = 300) -> list[dict]:
        sql, params = "SELECT * FROM jobs WHERE 1=1", []
        if isinstance(status, str):
            status = [status]
        if status:
            sql += f" AND status IN ({','.join('?' * len(status))})"
            params += status
        if project_id is not None:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += " ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END,"
        sql += " CASE WHEN status IN ('pending','paused','running') THEN position END, id DESC LIMIT ?"
        params.append(limit)
        return [_decode(r) for r in self.db.query(sql, tuple(params))]

    def active(self, project_id: int, kind: str | None = None, scene_id: int | None = None) -> list[dict]:
        sql = "SELECT * FROM jobs WHERE project_id = ? AND status IN ('pending','running','paused')"
        params: list[Any] = [project_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if scene_id is not None:
            sql += " AND scene_id = ?"
            params.append(scene_id)
        return [_decode(r) for r in self.db.query(sql, tuple(params))]

    def latest(self, project_id: int, kind: str, scene_id: int | None = None) -> dict | None:
        sql = "SELECT * FROM jobs WHERE project_id = ? AND kind = ?"
        params: list[Any] = [project_id, kind]
        if scene_id is not None:
            sql += " AND scene_id = ?"
            params.append(scene_id)
        return _decode(self.db.query_one(sql + " ORDER BY id DESC LIMIT 1", tuple(params)))

    def running_count(self, lane: str) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM jobs WHERE status = 'running' AND lane = ?", (lane,)) or 0)

    def claim_next(self, lane: str) -> dict | None:
        now = utcnow()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM jobs WHERE status = 'pending' AND lane = ? AND (next_attempt_at IS NULL OR next_attempt_at <= ?)"
                " ORDER BY position, id LIMIT 1",
                (lane, now),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1, started_at = ?, finished_at = NULL,"
                " progress = NULL, progress_message = 'Starting', error_message = NULL, error_detail = NULL,"
                " error_kind = NULL, updated_at = ? WHERE id = ?",
                (now, now, row[0]),
            )
        return self.get(row[0])

    def set_progress(self, job_id: int, progress: float | None, message: str) -> None:
        self.db.execute(
            "UPDATE jobs SET progress = ?, progress_message = ?, updated_at = ? WHERE id = ?",
            (None if progress is None else round(max(0.0, min(1.0, progress)), 4), message[:200], utcnow(), job_id),
        )

    def set_external(self, job_id: int, external_id: str | None, provider: str | None = None) -> None:
        self.db.execute("UPDATE jobs SET external_id = ?, provider = COALESCE(?, provider), updated_at = ? WHERE id = ?",
                        (external_id, provider, utcnow(), job_id))

    def complete(self, job_id: int, result: Any) -> None:
        now = utcnow()
        self.db.execute(
            "UPDATE jobs SET status = 'completed', result_json = ?, progress = 1, progress_message = 'Done',"
            " finished_at = ?, updated_at = ?, cancel_requested = 0 WHERE id = ?",
            (dumps(result), now, now, job_id),
        )

    def fail(self, job_id: int, message: str, *, kind: str, detail: str | None) -> None:
        now = utcnow()
        self.db.execute(
            "UPDATE jobs SET status = 'failed', error_message = ?, error_kind = ?, error_detail = ?, finished_at = ?,"
            " updated_at = ?, progress_message = NULL WHERE id = ?",
            (message[:500], kind, (detail or "")[:8000] or None, now, now, job_id),
        )

    def retry_later(self, job_id: int, delay_s: float, message: str, *, kind: str, detail: str | None) -> None:
        now = datetime.now(timezone.utc)
        at = (now + timedelta(seconds=delay_s)).isoformat(timespec="seconds")
        self.db.execute(
            "UPDATE jobs SET status = 'pending', next_attempt_at = ?, error_message = ?, error_kind = ?, error_detail = ?,"
            " progress = NULL, progress_message = ?, external_id = NULL, updated_at = ? WHERE id = ?",
            (at, message[:500], kind, (detail or "")[:8000] or None, f"Retrying in {int(delay_s)}s", utcnow(), job_id),
        )

    def cancelled(self, job_id: int, message: str = "Cancelled") -> None:
        now = utcnow()
        self.db.execute(
            "UPDATE jobs SET status = 'cancelled', progress_message = ?, finished_at = ?, updated_at = ? WHERE id = ?",
            (message, now, now, job_id),
        )

    def requeue(self, job_id: int, *, keep_attempt: bool, note: str, payload: dict | None = None) -> None:
        sets = "status = 'pending', progress = NULL, progress_message = ?, updated_at = ?"
        params: list[Any] = [note, utcnow()]
        if keep_attempt:
            sets += ", attempts = MAX(0, attempts - 1)"
        if payload is not None:
            sets += ", payload_json = ?"
            params.append(dumps(payload))
        params.append(job_id)
        self.db.execute(f"UPDATE jobs SET {sets} WHERE id = ?", tuple(params))

    def request_cancel(self, job_id: int) -> None:
        self.db.execute("UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE id = ?", (utcnow(), job_id))

    def set_status(self, job_id: int, status: str, expect: tuple[str, ...]) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or row[0] not in expect:
                return False
            conn.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", (status, utcnow(), job_id))
            return True

    def manual_retry(self, job_id: int, extra_attempts: int) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT status, attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or row[0] not in ("failed", "cancelled"):
                return False
            conn.execute(
                "UPDATE jobs SET status = 'pending', next_attempt_at = NULL, cancel_requested = 0, max_attempts = ?,"
                " progress = NULL, progress_message = 'Queued for retry', external_id = NULL, updated_at = ? WHERE id = ?",
                (row[1] + extra_attempts, utcnow(), job_id),
            )
            return True

    def move(self, job_id: int, direction: str) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT position, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or row[1] not in ("pending", "paused"):
                return False
            pos = row[0]
            if direction == "top":
                new = (conn.execute("SELECT MIN(position) FROM jobs WHERE status IN ('pending','paused')").fetchone()[0] or pos) - 1
                conn.execute("UPDATE jobs SET position = ? WHERE id = ?", (new, job_id))
                return True
            if direction == "bottom":
                new = (conn.execute("SELECT MAX(position) FROM jobs").fetchone()[0] or pos) + 1
                conn.execute("UPDATE jobs SET position = ? WHERE id = ?", (new, job_id))
                return True
            op, order = ("<", "DESC") if direction == "up" else (">", "ASC")
            other = conn.execute(
                f"SELECT id, position FROM jobs WHERE status IN ('pending','paused') AND position {op} ? ORDER BY position {order} LIMIT 1",
                (pos,),
            ).fetchone()
            if not other:
                return False
            conn.execute("UPDATE jobs SET position = ? WHERE id = ?", (other[1], job_id))
            conn.execute("UPDATE jobs SET position = ? WHERE id = ?", (pos, other[0]))
            return True

    def remove(self, job_id: int) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or row[0] == "running":
                return False
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            return True

    def counts(self) -> dict[str, int]:
        rows = self.db.query("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
        return {r["status"]: r["n"] for r in rows}
