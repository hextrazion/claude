"""Style library endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..errors import ValidationFailed
from ..safety import MEDIA_EXTENSIONS, safe_join
from ..services import Services
from ..styles import StyleStore
from .deps import services

router = APIRouter()

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 500 * 1024 * 1024


class StyleIn(BaseModel):
    name: str = Field("New style", min_length=1, max_length=80)
    notes: str = Field("", max_length=2000)


class StylePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    notes: str | None = Field(None, max_length=2000)
    style_prompt: str | None = Field(None, max_length=900)
    avoid: str | None = Field(None, max_length=400)


class KeyIn(BaseModel):
    file: str = Field(..., max_length=200)
    key: bool


class DeleteIn(BaseModel):
    confirm: str


def _view(s: Services, style: dict) -> dict:
    defaults = s.settings.get().generation
    style["is_default"] = defaults.style_id == style["id"]
    jobs = [j for j in s.jobs.list(status=["pending", "running"]) if j["kind"] == "style_analysis"
            and (j.get("payload") or {}).get("style_id") == style["id"]]
    style["job"] = jobs[0] if jobs else None
    return style


@router.get("/styles")
def list_styles(s: Services = Depends(services)):
    return [_view(s, st) for st in s.styles.list()]


@router.post("/styles")
def create_style(body: StyleIn, s: Services = Depends(services)):
    return _view(s, s.styles.create(body.name, body.notes))


@router.get("/styles/{style_id}")
def get_style(style_id: int, s: Services = Depends(services)):
    return _view(s, s.styles.require(style_id))


@router.patch("/styles/{style_id}")
def patch_style(style_id: int, body: StylePatch, s: Services = Depends(services)):
    st = s.styles.require(style_id)
    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.notes is not None:
        fields["notes"] = body.notes
    if body.style_prompt is not None or body.avoid is not None:
        profile = dict(st.get("profile") or {})
        if body.style_prompt is not None:
            profile["style_prompt"] = body.style_prompt.strip()
        if body.avoid is not None:
            profile["avoid"] = body.avoid.strip()
        profile["edited"] = True
        fields["profile"] = profile
        if profile.get("style_prompt") and st["status"] in ("new", "failed"):
            fields["status"] = "ready"  # a hand-written style is usable without analysis
    s.styles.update(style_id, **fields)
    return _view(s, s.styles.require(style_id))


@router.delete("/styles/{style_id}")
def delete_style(style_id: int, body: DeleteIn, s: Services = Depends(services)):
    st = s.styles.require(style_id)
    if body.confirm.strip() != st["name"].strip():
        raise ValidationFailed("Type the style name exactly to delete it.")
    if s.settings.get().generation.style_id == style_id:
        s.settings.update({"generation": {"style_id": 0}})
    s.styles.delete(style_id)
    return {"ok": True}


@router.post("/styles/{style_id}/references")
async def upload_reference(style_id: int, file: UploadFile = File(...), s: Services = Depends(services)):
    s.styles.require(style_id)
    kind = StyleStore.kind_for(file.filename or "")
    limit = MAX_VIDEO_BYTES if kind == "video" else MAX_IMAGE_BYTES
    tmp = s.styles.folder(style_id) / f".upload-{uuid.uuid4().hex}"
    size = 0
    try:
        with tmp.open("wb") as fh:
            while chunk := await file.read(1 << 20):  # stream to disk: videos can be large
                size += len(chunk)
                if size > limit:
                    raise ValidationFailed(f"That file is larger than {limit // (1024 * 1024)} MB.")
                fh.write(chunk)
        if size == 0:
            raise ValidationFailed("The file is empty.")
        return _view(s, s.styles.add_reference(style_id, file.filename or "reference", tmp))
    finally:
        tmp.unlink(missing_ok=True)


@router.delete("/styles/{style_id}/references")
def delete_reference(style_id: int, file: str, s: Services = Depends(services)):
    return _view(s, s.styles.remove_reference(style_id, file))


@router.post("/styles/{style_id}/key")
def set_key(style_id: int, body: KeyIn, s: Services = Depends(services)):
    return _view(s, s.styles.set_key(style_id, body.file, body.key))


@router.post("/styles/{style_id}/analyze")
def analyze(style_id: int, s: Services = Depends(services)):
    st = s.styles.require(style_id)
    if not st["refs"]:
        raise ValidationFailed("Add at least one reference image or video first.")
    job_id = s.orchestrator.enqueue(None, "style_analysis", payload={"style_id": style_id}, front=True)
    s.styles.update(style_id, status="analyzing", error=None)
    return {"job_id": job_id, "style": _view(s, s.styles.require(style_id))}


@router.post("/styles/{style_id}/default")
def make_default(style_id: int, on: bool = True, s: Services = Depends(services)):
    if on:
        st = s.styles.require(style_id)
        if st["status"] != "ready":
            raise ValidationFailed("Analyse the style (or write its description) before using it.")
    s.settings.update({"generation": {"style_id": style_id if on else 0}})
    return _view(s, s.styles.require(style_id))


@router.get("/style-files/{style_id}/{rel_path:path}")
def style_file(style_id: int, rel_path: str, s: Services = Depends(services)):
    s.styles.require(style_id)
    path = safe_join(s.styles.folder(style_id), rel_path)
    if path.suffix.lower() not in MEDIA_EXTENSIONS or not path.is_file():
        raise ValidationFailed("File not found.")
    return FileResponse(path)
