"""Ideas, projects, scenes, files and the library."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..db import utcnow
from ..errors import ValidationFailed
from ..media.alignment import tokenize
from ..pipeline.prompts import WORDS_PER_SECOND
from ..pipeline.stages import script_text, store_script
from ..safety import IMAGE_EXTENSIONS, MEDIA_EXTENSIONS, safe_filename, safe_join
from ..services import Services
from .deps import services

router = APIRouter()


# -- ideas -----------------------------------------------------------------------
class GenerateIdeas(BaseModel):
    niche: str = Field("", max_length=300)
    exclusions: str = Field("", max_length=500)
    count: int = Field(8, ge=1, le=20)
    duration_s: int | None = Field(None, ge=5, le=180)
    tone: str = Field("", max_length=200)
    notes: str = Field("", max_length=500)


class IdeaIn(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    niche: str = Field("", max_length=120)
    central_question: str = Field("", max_length=500)
    hook: str = Field("", max_length=500)
    description: str = Field("", max_length=2000)
    appeal: str = Field("", max_length=1000)
    visual_approach: str = Field("", max_length=1000)
    est_duration_s: float | None = Field(None, ge=5, le=300)
    research_needs: str = Field("", max_length=1000)
    accuracy_concerns: str = Field("", max_length=1000)
    notes: str = Field("", max_length=2000)


class IdeaPatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    niche: str | None = Field(None, max_length=120)
    central_question: str | None = Field(None, max_length=500)
    hook: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=2000)
    appeal: str | None = Field(None, max_length=1000)
    visual_approach: str | None = Field(None, max_length=1000)
    est_duration_s: float | None = Field(None, ge=5, le=300)
    research_needs: str | None = Field(None, max_length=1000)
    accuracy_concerns: str | None = Field(None, max_length=1000)
    notes: str | None = Field(None, max_length=2000)
    status: Literal["new", "favorite", "rejected"] | None = None


class ApproveIdea(BaseModel):
    start: bool = True
    overrides: dict = Field(default_factory=dict)


@router.get("/ideas")
def list_ideas(status: str | None = None, q: str | None = None, sort: str = "new", s: Services = Depends(services)):
    return s.projects.list_ideas(status, q, sort)


@router.post("/ideas/generate")
def generate_ideas(body: GenerateIdeas, s: Services = Depends(services)):
    if not s.secrets.get("groq"):
        raise ValidationFailed("Groq is not configured. Add your API key on the Integrations page first.")
    s.usage.check_limit("ideas")
    job_id = s.orchestrator.enqueue(None, "ideas", payload=body.model_dump(), front=True)
    return {"job_id": job_id}


@router.post("/ideas")
def create_idea(body: IdeaIn, s: Services = Depends(services)):
    iid = s.projects.create_idea(body.model_dump(), source="manual")
    return s.projects.get_idea(iid)


@router.patch("/ideas/{idea_id}")
def patch_idea(idea_id: int, body: IdeaPatch, s: Services = Depends(services)):
    if not s.projects.get_idea(idea_id):
        raise ValidationFailed("Idea not found.")
    s.projects.update_idea(idea_id, body.model_dump(exclude_none=True))
    return s.projects.get_idea(idea_id)


@router.delete("/ideas/{idea_id}")
def delete_idea(idea_id: int, s: Services = Depends(services)):
    idea = s.projects.get_idea(idea_id)
    if not idea:
        raise ValidationFailed("Idea not found.")
    if idea["project_id"] and s.projects.get(idea["project_id"]):
        raise ValidationFailed("This idea has a project. Delete the project first.")
    s.db.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
    return {"ok": True}


@router.post("/ideas/{idea_id}/approve")
def approve_idea(idea_id: int, body: ApproveIdea, s: Services = Depends(services)):
    project = s.orchestrator.start_from_idea(idea_id, overrides=_clean_overrides(body.overrides), auto_advance=False)
    if body.start:
        s.orchestrator.advance(project["id"], user=True)
    return s.projects.get(project["id"])


def _clean_overrides(overrides: dict) -> dict:
    """Validate per-project overrides by applying them to the settings model."""
    from pydantic import ValidationError

    from ..settings import Settings, deep_merge

    allowed = {"video", "narration", "captions", "generation", "music", "general"}
    overrides = {k: v for k, v in (overrides or {}).items() if k in allowed and isinstance(v, dict)}
    try:
        Settings.model_validate(deep_merge(Settings().model_dump(), overrides))
    except ValidationError as exc:
        raise ValidationFailed("Invalid project settings.", detail=str(exc)) from exc
    return overrides


# -- projects --------------------------------------------------------------------
class NewProject(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field("", max_length=2000)
    start: bool = True


class ProjectPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    overrides: dict | None = None


class ScriptIn(BaseModel):
    title: str = Field(..., max_length=200)
    segments: list[dict] = Field(..., min_length=1, max_length=40)


class Review(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field("", max_length=1000)


class DeleteProject(BaseModel):
    confirm: str
    delete_files: bool = False


class ActionIn(BaseModel):
    payload: dict = Field(default_factory=dict)


def _full(s: Services, project_id: int) -> dict:
    p = s.projects.require(project_id)
    scenes = s.projects.scenes(project_id)
    p["scenes"] = scenes
    p["jobs"] = s.jobs.list(project_id=project_id, limit=100)
    p["next"] = s.orchestrator.next_step(p, scenes)
    p["gates"] = s.orchestrator.gates()
    p["effective"] = s.projects.effective_settings(p).model_dump(include={"video", "narration", "captions", "generation", "music"})
    p["idea"] = s.projects.get_idea(p["idea_id"]) if p.get("idea_id") else None
    p["folder_exists"] = Path(p["folder"]).is_dir()
    return p


@router.get("/projects")
def list_projects(archived: bool = False, q: str | None = None, s: Services = Depends(services)):
    out = []
    for p in s.projects.list(archived=archived, q=q):
        n = s.db.scalar("SELECT COUNT(*) FROM scenes WHERE project_id = ?", (p["id"],))
        done = s.db.scalar("SELECT COUNT(*) FROM scenes WHERE project_id = ? AND clip_status = 'completed'", (p["id"],))
        out.append({k: p[k] for k in ("id", "title", "stage", "status", "status_message", "created_at", "updated_at",
                                      "export_status", "review_status", "archived", "origin")} |
                   {"scenes": n, "clips_done": done, "export": p.get("export")})
    return out


@router.post("/projects")
def create_project(body: NewProject, s: Services = Depends(services)):
    iid = s.projects.create_idea({"title": body.title, "description": body.description, "central_question": body.title},
                                 source="manual")
    project = s.orchestrator.start_from_idea(iid, auto_advance=False)
    if body.start:
        s.orchestrator.advance(project["id"], user=True)
    return _full(s, project["id"])


@router.get("/projects/{project_id}")
def get_project(project_id: int, s: Services = Depends(services)):
    return _full(s, project_id)


@router.patch("/projects/{project_id}")
def patch_project(project_id: int, body: ProjectPatch, s: Services = Depends(services)):
    p = s.projects.require(project_id)
    fields: dict = {}
    if body.title is not None:
        fields["title"] = body.title.strip()
    if body.overrides is not None:
        keep = {k: v for k, v in (p.get("overrides") or {}).items() if k.startswith("_")}
        fields["overrides"] = {**keep, **_clean_overrides(body.overrides)}
    if fields:
        s.projects.update(project_id, **fields)
        s.projects.snapshot(project_id)
    return _full(s, project_id)


@router.post("/projects/{project_id}/continue")
def continue_project(project_id: int, s: Services = Depends(services)):
    s.projects.require(project_id)
    step = s.orchestrator.advance(project_id, user=True)
    return {"step": step, "project": _full(s, project_id)}


@router.post("/projects/{project_id}/actions/{action}")
def project_action(project_id: int, action: str, body: ActionIn | None = None, s: Services = Depends(services)):
    ids = s.orchestrator.run_action(project_id, action, (body.payload if body else {}) or None)
    return {"job_ids": ids, "project": _full(s, project_id)}


@router.put("/projects/{project_id}/script")
def edit_script(project_id: int, body: ScriptIn, s: Services = Depends(services)):
    p = s.projects.require(project_id)
    old = p.get("script") or {}
    segs = []
    for seg in body.segments:
        text = str(seg.get("text", "")).strip()
        if text:
            segs.append({"text": text[:2000], "purpose": str(seg.get("purpose", ""))[:40],
                         "visual_idea": str(seg.get("visual_idea", ""))[:500]})
    if not segs:
        raise ValidationFailed("The script needs at least one non-empty segment.")
    script = {**old, "title": body.title.strip() or p["title"], "segments": segs, "edited": True, "edited_at": utcnow()}
    script["full_text"] = script_text(script)
    script["word_count"] = len(tokenize(script["full_text"]))
    script["est_duration_s"] = round(script["word_count"] / WORDS_PER_SECOND, 1)
    store_script(s, p, script, status="draft")
    s.orchestrator.refresh(project_id)
    return _full(s, project_id)


@router.post("/projects/{project_id}/approve/{gate}")
def approve(project_id: int, gate: Literal["script", "scene_plan", "assembly"], s: Services = Depends(services)):
    s.orchestrator.approve(project_id, gate)
    return _full(s, project_id)


@router.post("/projects/{project_id}/review")
def review(project_id: int, body: Review, s: Services = Depends(services)):
    s.orchestrator.review(project_id, body.decision, body.note)
    return _full(s, project_id)


@router.post("/projects/{project_id}/cancel")
def cancel_project(project_id: int, s: Services = Depends(services)):
    n = s.orchestrator.cancel_project(project_id)
    return {"cancelled": n}


@router.post("/projects/{project_id}/archive")
def archive(project_id: int, archived: bool = True, s: Services = Depends(services)):
    s.projects.require(project_id)
    if archived:
        s.orchestrator.cancel_project(project_id)
    s.projects.update(project_id, archived=int(archived))
    s.orchestrator.refresh(project_id)
    return {"ok": True}


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, body: DeleteProject, s: Services = Depends(services)):
    p = s.projects.require(project_id)
    if body.confirm.strip() != p["title"].strip():
        raise ValidationFailed("Type the project title exactly to confirm deletion.")
    if s.jobs.active(project_id):
        s.orchestrator.cancel_project(project_id)
        if any(j["status"] == "running" for j in s.jobs.active(project_id)):
            raise ValidationFailed("Jobs are still stopping for this project. Try again in a moment.")
    s.projects.delete(p, delete_files=body.delete_files)
    s.activity.add(f"Deleted project '{p['title']}'" + (" and its files" if body.delete_files else " (files kept)"),
                   level="warning", category="project")
    return {"ok": True, "files_deleted": body.delete_files, "folder": p["folder"]}


def _open_in_file_manager(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # opens Explorer on a folder we own
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


@router.post("/projects/{project_id}/open-folder")
def open_folder(project_id: int, sub: Literal["", "exports", "scenes", "narration"] = "", s: Services = Depends(services)):
    p = s.projects.require(project_id)
    folder = s.projects.folder(p)
    target = safe_join(folder, sub) if sub else folder
    target.mkdir(parents=True, exist_ok=True)
    try:
        _open_in_file_manager(target)
    except OSError as exc:
        raise ValidationFailed("Could not open the folder on this machine.", detail=str(exc)) from exc
    return {"opened": str(target)}


@router.post("/projects/{project_id}/export")
def export_to_library(project_id: int, s: Services = Depends(services)):
    p = s.projects.require(project_id)
    if p["export_status"] != "completed" or not p.get("export"):
        raise ValidationFailed("There is no finished export yet.")
    src = s.projects.abs(p, p["export"]["path"])
    if not src or not src.is_file():
        raise ValidationFailed("The export file is missing on disk.")
    dest = s.projects.export_root / safe_filename(f"{p['title']}.mp4")
    i = 2
    while dest.exists():
        dest = s.projects.export_root / safe_filename(f"{p['title']}-{i}.mp4")
        i += 1
    shutil.copy2(src, dest)
    export = {**p["export"], "library_path": str(dest)}
    s.projects.update(project_id, export=export)
    s.activity.add(f"Exported to library: {dest.name}", category="export", project_id=project_id)
    return {"path": str(dest)}


# -- scenes -------------------------------------------------------------------------
class ScenePatch(BaseModel):
    narration: str | None = Field(None, max_length=2000)
    visual_objective: str | None = Field(None, max_length=500)
    prompt: str | None = Field(None, max_length=2000)
    negative_prompt: str | None = Field(None, max_length=500)
    camera: str | None = Field(None, max_length=200)
    subject_motion: str | None = Field(None, max_length=300)
    environment: str | None = Field(None, max_length=300)
    style: str | None = Field(None, max_length=300)
    duration_s: float | None = Field(None, ge=0.5, le=60)
    needs_image: bool | None = None
    image_prompt: str | None = Field(None, max_length=1500)
    transition: Literal["cut", "fade", "dissolve"] | None = None


class GenerateScene(BaseModel):
    provider: Literal["comfyui", "draft"] | None = None
    seed: int | None = Field(None, ge=0)


def _scene_project(s: Services, scene_id: int) -> tuple[dict, dict]:
    sc = s.projects.scene(scene_id)
    if not sc:
        raise ValidationFailed("Scene not found.")
    return sc, s.projects.require(sc["project_id"])


@router.patch("/scenes/{scene_id}")
def patch_scene(scene_id: int, body: ScenePatch, s: Services = Depends(services)):
    sc, p = _scene_project(s, scene_id)
    fields = body.model_dump(exclude_none=True)
    if "needs_image" in fields:
        fields["needs_image"] = int(fields["needs_image"])
    visual = {"prompt", "negative_prompt", "camera", "subject_motion", "environment", "style"}
    if visual & fields.keys() and sc["clip_status"] == "completed":
        fields["clip_status"] = "stale"
    if "image_prompt" in fields and sc["image_status"] == "completed":
        fields["image_status"] = "none"
    s.projects.update_scene(scene_id, **fields)
    proj_fields = {}
    if "narration" in fields and fields["narration"] != sc["narration"]:
        if p["narration_status"] == "completed":
            proj_fields["narration_status"] = "stale"
        if p["export_status"] == "completed":
            proj_fields["export_status"] = "stale"
    if fields.get("clip_status") == "stale" and p["export_status"] == "completed":
        proj_fields["export_status"] = "stale"
    if proj_fields:
        s.projects.update(p["id"], **proj_fields)
    s.orchestrator.refresh(p["id"])
    return s.projects.scene(scene_id)


@router.post("/scenes/{scene_id}/generate")
def generate_scene(scene_id: int, body: GenerateScene | None = None, s: Services = Depends(services)):
    sc, p = _scene_project(s, scene_id)
    if p["scene_plan_status"] != "approved":
        raise ValidationFailed("Approve the scene plan before generating footage.")
    job = s.orchestrator.enqueue(p["id"], "scene_clip", scene_id=scene_id, payload=(body.model_dump(exclude_none=True) if body else {}))
    s.orchestrator.refresh(p["id"])
    return {"job_id": job}


@router.post("/scenes/{scene_id}/generate-image")
def generate_scene_image(scene_id: int, body: GenerateScene | None = None, s: Services = Depends(services)):
    sc, p = _scene_project(s, scene_id)
    job = s.orchestrator.enqueue(p["id"], "scene_image", scene_id=scene_id, payload=(body.model_dump(exclude_none=True) if body else {}))
    s.orchestrator.refresh(p["id"])
    return {"job_id": job}


@router.post("/scenes/{scene_id}/image")
async def upload_scene_image(scene_id: int, file: UploadFile = File(...), s: Services = Depends(services)):
    sc, p = _scene_project(s, scene_id)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValidationFailed("Upload a PNG, JPG or WebP image.")
    data = await file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise ValidationFailed("Image is larger than 25 MB.")
    dest = s.projects.scene_dir(p, sc) / f"image_upload_{utcnow().replace(':', '').replace('+', '')[:15]}{ext}"
    dest.write_bytes(data)
    s.projects.update_scene(scene_id, image_path=s.projects.rel(p, dest), image_status="completed", needs_image=1,
                            **({"clip_status": "stale"} if sc["clip_status"] == "completed" else {}))
    return s.projects.scene(scene_id)


@router.post("/projects/{project_id}/scenes")
def add_scene(project_id: int, after: int = -1, s: Services = Depends(services)):
    p = s.projects.require(project_id)
    scenes = s.projects.scenes(project_id)
    new = [dict(x) for x in scenes]
    pos = len(new) if after < 0 else min(after + 1, len(new))
    new.insert(pos, {"narration": "", "prompt": "Describe the shot", "duration_s": 3})
    _rewrite_scenes(s, p, new, scenes)
    return _full(s, project_id)


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: int, s: Services = Depends(services)):
    sc, p = _scene_project(s, scene_id)
    scenes = s.projects.scenes(p["id"])
    if s.jobs.active(p["id"], scene_id=scene_id):
        raise ValidationFailed("This scene has queued or running jobs. Cancel them first.")
    _rewrite_scenes(s, p, [x for x in scenes if x["id"] != scene_id], scenes)
    return _full(s, p["id"])


def _rewrite_scenes(s: Services, p: dict, new: list[dict], old: list[dict]) -> None:
    """Insert/delete scenes while keeping existing clips and images attached."""
    keep = {"clip_status", "clip_path", "clip_meta", "image_status", "image_path", "flags"}
    preserved = [{k: x.get(k) for k in keep} if x.get("id") else None for x in new]
    if any(j["status"] == "running" for j in s.jobs.active(p["id"]) if j.get("scene_id")):
        raise ValidationFailed("Wait for running scene jobs to finish before adding or removing scenes.")
    s.projects.replace_scenes(p["id"], new)
    for sc, extra in zip(s.projects.scenes(p["id"]), preserved):
        if extra:
            s.projects.update_scene(sc["id"], **{k: v for k, v in extra.items() if v is not None})
    fields = {"scene_plan_status": "draft"}
    if p["narration_status"] == "completed":
        fields["narration_status"] = "stale"
    if p["export_status"] == "completed":
        fields["export_status"] = "stale"
    s.projects.update(p["id"], **fields)
    s.orchestrator.refresh(p["id"])


# -- files & library ---------------------------------------------------------------
@router.get("/files/{project_id}/{rel_path:path}")
def project_file(project_id: int, rel_path: str, s: Services = Depends(services)):
    p = s.projects.require(project_id)
    path = safe_join(s.projects.folder(p), rel_path)
    if path.suffix.lower() not in MEDIA_EXTENSIONS or not path.is_file():
        raise ValidationFailed("File not found.")
    return FileResponse(path)


@router.get("/library")
def library(q: str | None = None, include_archived: bool = False, s: Services = Depends(services)):
    out = []
    for p in s.projects.list(archived=None if include_archived else False, q=q):
        ex = p.get("export")
        out.append({
            "id": p["id"], "title": p["title"], "created_at": p["created_at"], "updated_at": p["updated_at"],
            "stage": p["stage"], "status": p["status"], "export_status": p["export_status"],
            "review_status": p["review_status"], "archived": bool(p["archived"]), "folder": p["folder"],
            "export": ex, "qc": {k: (p.get("qc") or {}).get(k) for k in ("technical_ok", "failures", "warnings")},
        })
    return out


@router.get("/music")
def list_music(s: Services = Depends(services)):
    from ..safety import AUDIO_EXTENSIONS

    d = s.config.music_dir
    return [{"name": f.name, "bytes": f.stat().st_size} for f in sorted(d.iterdir()) if f.suffix.lower() in AUDIO_EXTENSIONS]


@router.post("/music")
async def upload_music(file: UploadFile = File(...), s: Services = Depends(services)):
    from ..safety import AUDIO_EXTENSIONS

    name = safe_filename(file.filename or "music.mp3")
    if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValidationFailed("Upload an MP3, WAV, M4A, OGG, FLAC or AAC file.")
    data = await file.read(60 * 1024 * 1024 + 1)
    if len(data) > 60 * 1024 * 1024:
        raise ValidationFailed("Music file is larger than 60 MB.")
    (s.config.music_dir / name).write_bytes(data)
    return {"name": name, "note": "Only use music you have the rights to use."}
