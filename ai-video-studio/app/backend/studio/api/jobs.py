"""Queue manager endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..errors import ValidationFailed
from ..services import Services
from .deps import services

router = APIRouter()


class Move(BaseModel):
    direction: Literal["up", "down", "top", "bottom"]


def _with_names(s: Services, jobs: list[dict]) -> list[dict]:
    titles = {r["id"]: r["title"] for r in s.db.query("SELECT id, title FROM projects")}
    scene_idx = {r["id"]: r["idx"] for r in s.db.query("SELECT id, idx FROM scenes")}
    for j in jobs:
        j["project_title"] = titles.get(j["project_id"])
        j["scene_number"] = scene_idx[j["scene_id"]] + 1 if j.get("scene_id") in scene_idx else None
    return jobs


@router.get("/jobs")
def list_jobs(status: str | None = None, project_id: int | None = None, limit: int = 200, s: Services = Depends(services)):
    statuses = status.split(",") if status else None
    return _with_names(s, s.jobs.list(status=statuses, project_id=project_id, limit=min(limit, 1000)))


@router.get("/queue")
def queue_state(s: Services = Depends(services)):
    waiting = s.db.query(
        "SELECT id, title, status_message, stage, updated_at FROM projects WHERE archived = 0 AND status = 'waiting_approval'"
        " ORDER BY updated_at"
    )
    return {**s.worker.state(), "awaiting_approval": waiting}


@router.post("/queue/pause")
def pause_queue(s: Services = Depends(services)):
    s.settings.update({"queue": {"paused": True}})
    s.activity.add("Queue paused: no new jobs will start. Running jobs finish normally.", category="queue")
    s.worker.wake()
    return s.worker.state()


@router.post("/queue/resume")
def resume_queue(reset_session: bool = False, s: Services = Depends(services)):
    s.settings.update({"queue": {"paused": False}})
    if reset_session:
        s.worker.reset_session()
    s.activity.add("Queue resumed", category="queue")
    s.worker.wake()
    return s.worker.state()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, s: Services = Depends(services)):
    return {"status": s.worker.cancel(job_id)}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, s: Services = Depends(services)):
    job = s.jobs.require(job_id)
    if job.get("project_id") and job["kind"] in ("scene_clip", "scene_image") and not job.get("scene_id"):
        raise ValidationFailed("The scene for this job was removed; generate the new scene instead.")
    extra = s.settings.get().generation.max_retries + 1
    if not s.jobs.manual_retry(job_id, extra):
        raise ValidationFailed("Only failed or cancelled jobs can be retried.")
    if job["kind"] == "scene_clip" and job.get("scene_id"):
        s.projects.update_scene(job["scene_id"], clip_status="queued")
    elif job["kind"] == "scene_image" and job.get("scene_id"):
        s.projects.update_scene(job["scene_id"], image_status="queued")
    elif job["kind"] == "narration" and job.get("project_id"):
        s.projects.update(job["project_id"], narration_status="queued")
    elif job["kind"] == "research" and job.get("project_id"):
        s.projects.update(job["project_id"], research_status="running")
    if job.get("project_id"):
        s.orchestrator.refresh(job["project_id"])
    s.worker.wake()
    return s.jobs.get(job_id)


@router.post("/jobs/{job_id}/pause")
def pause_job(job_id: int, s: Services = Depends(services)):
    if not s.jobs.set_status(job_id, "paused", ("pending",)):
        raise ValidationFailed("Only pending jobs can be paused. Cancel a running job instead.")
    return s.jobs.get(job_id)


@router.post("/jobs/{job_id}/resume")
def resume_job(job_id: int, s: Services = Depends(services)):
    if not s.jobs.set_status(job_id, "pending", ("paused",)):
        raise ValidationFailed("Job is not paused.")
    s.worker.wake()
    return s.jobs.get(job_id)


@router.post("/jobs/{job_id}/move")
def move_job(job_id: int, body: Move, s: Services = Depends(services)):
    if not s.jobs.move(job_id, body.direction):
        raise ValidationFailed("Only pending or paused jobs can be reordered.")
    return {"ok": True}


@router.delete("/jobs/{job_id}")
def remove_job(job_id: int, s: Services = Depends(services)):
    job = s.jobs.require(job_id)
    if job["status"] == "running":
        raise ValidationFailed("Cancel the running job before removing it.")
    if job["status"] in ("pending", "paused"):
        s.worker.cancel(job_id)
    s.jobs.remove(job_id)
    return {"ok": True}


@router.post("/jobs/clear-finished")
def clear_finished(s: Services = Depends(services)):
    n = s.db.scalar("SELECT COUNT(*) FROM jobs WHERE status IN ('completed','cancelled')")
    s.db.execute("DELETE FROM jobs WHERE status IN ('completed','cancelled')")
    return {"removed": n}
