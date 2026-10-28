"""Dashboard, system status, settings, activity, events and usage."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from .. import __version__
from ..errors import ValidationFailed
from ..services import Services
from ..settings import Settings
from ..system_monitor import dir_size_bytes, system_snapshot
from .deps import services

router = APIRouter()


@router.get("/health")
def health(s: Services = Depends(services)):
    return {"ok": True, "version": __version__, "schema": s.db.schema_version()}


@router.get("/system")
def system(s: Services = Depends(services)):
    snap = system_snapshot(s.projects.projects_root)
    st = s.settings.get().storage
    disk = snap.get("disk")
    snap["low_disk"] = bool(disk and st.low_disk_warning_gb and disk["free_gb"] < st.low_disk_warning_gb)
    return snap


@router.get("/storage")
def storage(s: Services = Depends(services)):
    root = s.projects.projects_root
    projects = []
    for p in s.projects.list(archived=None):
        folder = s.projects.folder(p)
        projects.append({"id": p["id"], "title": p["title"], "bytes": dir_size_bytes(folder)})
    return {
        "projects_root": str(root),
        "export_root": str(s.projects.export_root),
        "projects_bytes": sum(x["bytes"] for x in projects),
        "library_bytes": dir_size_bytes(s.projects.export_root),
        "cache_bytes": dir_size_bytes(s.config.cache_dir),
        "projects": sorted(projects, key=lambda x: -x["bytes"])[:50],
    }


@router.get("/dashboard")
def dashboard(s: Services = Depends(services)):
    db = s.db
    counts = {
        "projects": db.scalar("SELECT COUNT(*) FROM projects WHERE archived = 0"),
        "ideas_awaiting": db.scalar("SELECT COUNT(*) FROM ideas WHERE status IN ('new','favorite')"),
        "processing": db.scalar("SELECT COUNT(*) FROM projects WHERE archived = 0 AND status IN ('running','queued')"),
        "awaiting_review": db.scalar(
            "SELECT COUNT(*) FROM projects WHERE archived = 0 AND export_status = 'completed' AND review_status != 'approved'"
        ),
        "waiting_approval": db.scalar("SELECT COUNT(*) FROM projects WHERE archived = 0 AND status = 'waiting_approval'"),
        "failed_jobs": db.scalar("SELECT COUNT(*) FROM jobs WHERE status = 'failed'"),
        "completed_videos": db.scalar("SELECT COUNT(*) FROM projects WHERE review_status = 'approved'"),
    }
    attention = db.query(
        "SELECT id, title, stage, status, status_message, updated_at FROM projects WHERE archived = 0 AND status IN"
        " ('waiting_approval','failed') ORDER BY updated_at DESC LIMIT 8"
    )
    return {
        "counts": counts,
        "attention": attention,
        "activity": s.activity.recent(20),
        "errors": s.activity.recent(8, level="error"),
        "integrations": s.cached_health(),
        "queue": s.worker.state() if s.worker else None,
        "usage_today": s.usage.today(),
        "mode": s.settings.get().general.automation_mode,
    }


@router.get("/activity")
def activity(level: str | None = None, project_id: int | None = None, limit: int = 100, s: Services = Depends(services)):
    return s.activity.recent(min(limit, 500), level=level, project_id=project_id)


@router.get("/usage")
def usage(days: int = 30, s: Services = Depends(services)):
    return {
        "summary": s.usage.summary(days),
        "today": s.usage.today(),
        "rate_limits": s.usage.rate_limits,
        "recent": s.db.query("SELECT * FROM api_usage ORDER BY id DESC LIMIT 50"),
        "free_tier_note": "Groq costs show $0 while 'Groq free tier' is enabled in Settings → Pricing.",
    }


@router.get("/settings")
def get_settings(s: Services = Depends(services)):
    return s.settings.get().model_dump()


@router.get("/settings/defaults")
def default_settings():
    return Settings().model_dump()


@router.patch("/settings")
def patch_settings(patch: dict, s: Services = Depends(services)):
    try:
        new = s.settings.update(patch)
    except ValidationError as exc:
        msgs = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ValidationFailed("Some settings are invalid.", detail=msgs) from exc
    if "general" in patch and "log_level" in patch["general"]:
        import logging

        logging.getLogger().setLevel(new.general.log_level)
    if s.worker:
        s.worker.wake()
    s.bus.publish("settings")
    return new.model_dump()


@router.get("/events")
async def events(request: Request, s: Services = Depends(services)):
    q = s.bus.subscribe()

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            s.bus.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
