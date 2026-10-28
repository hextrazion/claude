"""Integrations: credentials, connection tests, models, voices, workflows."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..errors import ProviderError, ValidationFailed
from ..integrations import fish_audio, groq
from ..integrations.base import HealthResult
from ..integrations.video.workflows import BINDABLE, build_imported
from ..media.ffmpeg import FFmpeg
from ..secrets_store import SECRET_ENV
from ..services import Services
from ..system_monitor import disk_stats
from .deps import services

router = APIRouter()

INTEGRATIONS = {
    "groq": {"label": "Groq", "kind": "api", "purpose": "Ideas, research planning, scripts, scene plans",
             "docs": groq.DOCS_URL, "keys_url": groq.KEYS_URL, "secret": "groq"},
    "fish_audio": {"label": "Fish Audio", "kind": "api", "purpose": "Narration (text-to-speech)",
                   "docs": fish_audio.DOCS_URL, "keys_url": fish_audio.KEYS_URL, "secret": "fish_audio"},
    "comfyui": {"label": "ComfyUI (local video engine)", "kind": "local", "purpose": "Video and image generation on your GPU",
                "docs": "https://docs.comfy.org", "secret": None},
    "research": {"label": "Research provider", "kind": "api", "purpose": "Sources for fact-checking (optional)",
                 "docs": "https://docs.tavily.com", "keys_url": "https://app.tavily.com", "secret": "tavily"},
    "ffmpeg": {"label": "FFmpeg", "kind": "local", "purpose": "Assembly, captions, audio mixing, quality checks",
               "docs": "https://ffmpeg.org/download.html", "secret": None},
    "storage": {"label": "Storage", "kind": "local", "purpose": "Project folders and exports", "secret": None},
}


class KeyIn(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=400)


class ImportWorkflow(BaseModel):
    name: str = Field(..., min_length=2, max_length=64)
    label: str = Field("", max_length=120)
    kind: Literal["video", "image"] = "video"
    mode: Literal["t2v", "i2v", "t2i"] = "t2v"
    graph: dict
    defaults: dict = Field(default_factory=dict)


class WorkflowPatch(BaseModel):
    label: str | None = Field(None, max_length=120)
    defaults: dict | None = None
    bindings: dict | None = None


def _describe(s: Services, name: str) -> dict:
    meta = INTEGRATIONS[name]
    cached = s.cached_health().get(name)
    out = {"name": name, **meta, "health": cached}
    if meta.get("secret"):
        sec = meta["secret"]
        out["key"] = {"masked": s.secrets.masked(sec), "source": s.secrets.source(sec), "env_var": SECRET_ENV.get(sec),
                      "backend": s.secrets.backend_name}
    st = s.settings.get()
    if name == "groq":
        out["config"] = {"model_quality": st.text.model_quality, "model_fast": st.text.model_fast}
        out["rate_limits"] = s.usage.rate_limits.get("groq")
    elif name == "fish_audio":
        out["config"] = {"voice_id": st.narration.voice_id, "voice_name": st.narration.voice_name, "model": st.narration.model,
                         "known_models": fish_audio.KNOWN_MODELS}
    elif name == "comfyui":
        out["config"] = {"url": st.generation.comfyui_url, "video_provider": st.generation.video_provider,
                         "video_workflow": st.generation.video_workflow, "i2v_workflow": st.generation.i2v_workflow,
                         "image_workflow": st.generation.image_workflow}
    elif name == "research":
        out["config"] = {"enabled": st.text.research_enabled, "provider": st.text.research_provider}
    elif name == "ffmpeg":
        out["config"] = {"path": s.ffmpeg.paths.ffmpeg if s.ffmpeg.paths else None}
    elif name == "storage":
        out["config"] = {"projects_dir": str(s.projects.projects_root), "export_dir": str(s.projects.export_root)}
    return out


@router.get("/integrations")
def list_integrations(s: Services = Depends(services)):
    return [_describe(s, n) for n in INTEGRATIONS]


async def run_test(s: Services, name: str) -> dict:
    if name not in INTEGRATIONS:
        raise ValidationFailed("Unknown integration.")
    if name == "groq":
        result = await s.groq.test()
        if result.status == "ok":
            models = set(result.info.get("models", []))
            st = s.settings.get().text
            missing = [m for m in (st.model_quality, st.model_fast) if m not in models]
            if missing:
                result = HealthResult("warning", f"Connected, but configured model(s) not available: {', '.join(missing)}. "
                                      "Pick available models below.", info=result.info)
    elif name == "fish_audio":
        result = await s.fish.test()
        if result.status == "ok" and not s.settings.get().narration.voice_id:
            result = HealthResult("warning", result.message + " — choose a narration voice.", info=result.info)
    elif name == "comfyui":
        st = s.settings.get().generation
        if st.video_provider == "draft":
            result = HealthResult("warning", "Video provider is set to draft cards (no AI). Switch to ComfyUI for real footage.")
            comfy = await s.comfyui().health()
            result.info = {"comfyui": comfy.to_dict()}
        else:
            result = await s.comfyui().health()
            if result.status == "ok":
                wf = await s.comfyui().check_workflow(st.video_workflow)
                result.info["workflow_check"] = wf.to_dict()
                if wf.status != "ok":
                    result = HealthResult("warning", f"ComfyUI is running, but the video workflow is not ready: {wf.message}",
                                          detail=wf.detail, info=result.info)
    elif name == "research":
        provider = s.research_provider()
        if provider is None:
            result = HealthResult("warning", "Research is off. Scripts will not be checked against sources.")
        else:
            result = await provider.test()
    elif name == "ffmpeg":
        s.ffmpeg = FFmpeg()  # re-detect in case it was just installed
        s.draft.ffmpeg = s.ffmpeg
        result = s.ffmpeg.health()
    else:
        disk = disk_stats(s.projects.projects_root)
        st = s.settings.get().storage
        if not disk:
            result = HealthResult("error", "Project folder is not accessible.")
        elif disk["free_gb"] < st.low_disk_warning_gb:
            result = HealthResult("warning", f"Low disk space: {disk['free_gb']} GB free.", info=disk)
        else:
            result = HealthResult("ok", f"{disk['free_gb']} GB free on the project drive.", info=disk)
    return s.save_health(name, result)


@router.post("/integrations/{name}/test")
async def test_integration(name: str, s: Services = Depends(services)):
    await run_test(s, name)
    return _describe(s, name)


@router.post("/integrations/test-all")
async def test_all(s: Services = Depends(services)):
    for n in INTEGRATIONS:
        try:
            await run_test(s, n)
        except Exception as exc:  # one failing check must not hide the others
            s.save_health(n, HealthResult("error", "Check failed unexpectedly.", detail=repr(exc)))
    return [_describe(s, n) for n in INTEGRATIONS]


@router.put("/integrations/{name}/key")
async def set_key(name: str, body: KeyIn, s: Services = Depends(services)):
    sec = (INTEGRATIONS.get(name) or {}).get("secret")
    if not sec:
        raise ValidationFailed("This integration does not use an API key.")
    s.secrets.set(sec, body.api_key)
    s.activity.add(f"{INTEGRATIONS[name]['label']} API key updated", category="integrations")
    await run_test(s, name)
    return _describe(s, name)


@router.delete("/integrations/{name}/key")
def delete_key(name: str, s: Services = Depends(services)):
    sec = (INTEGRATIONS.get(name) or {}).get("secret")
    if not sec:
        raise ValidationFailed("This integration does not use an API key.")
    s.secrets.delete(sec)
    s.save_health(name, HealthResult("not_configured", "API key removed."))
    return _describe(s, name)


@router.get("/integrations/groq/models")
async def groq_models(s: Services = Depends(services)):
    return await s.groq.list_models()


@router.get("/integrations/fish_audio/voices")
async def fish_voices(mine: bool = False, q: str = "", page: int = 1, s: Services = Depends(services)):
    return await s.fish.list_voices(mine=mine, query=q, page=page)


@router.get("/integrations/comfyui/stats")
async def comfy_stats(s: Services = Depends(services)):
    return (await s.comfyui().health()).to_dict()


@router.get("/workflows")
def list_workflows(s: Services = Depends(services)):
    return {"workflows": s.workflows.list(), "bindable": BINDABLE}


@router.post("/workflows/import")
def import_workflow(body: ImportWorkflow, s: Services = Depends(services)):
    data = build_imported(body.name, body.label, body.kind, body.mode, body.graph, body.defaults)
    path = s.workflows.save_user(body.name, data)
    return {"name": path.stem, "warnings": data["import_warnings"], "bindings": data["bindings"], "defaults": data["defaults"]}


@router.patch("/workflows/{name}")
def patch_workflow(name: str, body: WorkflowPatch, s: Services = Depends(services)):
    wf = s.workflows.get(name)
    if body.label is not None:
        wf["label"] = body.label
    if body.defaults is not None:
        allowed = {"width", "height", "fps", "max_frames", "frame_multiple"}
        for k, v in body.defaults.items():
            if k not in allowed or not isinstance(v, int) or v <= 0 or v > 8192:
                raise ValidationFailed(f"Invalid default '{k}'.")
        wf["defaults"] = {**wf.get("defaults", {}), **body.defaults}
    if body.bindings is not None:
        graph = wf["workflow"]
        for key, targets in body.bindings.items():
            if key not in BINDABLE or not isinstance(targets, list):
                raise ValidationFailed(f"Invalid binding '{key}'.")
            for t in targets:
                if not isinstance(t, dict) or str(t.get("node")) not in graph or not isinstance(t.get("input"), str):
                    raise ValidationFailed(f"Binding '{key}' points to a node that is not in the workflow.")
        wf["bindings"] = body.bindings
    s.workflows.save_user(name, wf)
    return {"ok": True}


@router.delete("/workflows/{name}")
def delete_workflow(name: str, s: Services = Depends(services)):
    if not s.workflows.delete_user(name):
        raise ValidationFailed("Only imported workflows can be deleted.")
    return {"ok": True}


@router.post("/workflows/{name}/check")
async def check_workflow(name: str, s: Services = Depends(services)):
    try:
        return (await s.comfyui().check_workflow(name)).to_dict()
    except ProviderError as exc:
        return HealthResult("unavailable", exc.message, detail=exc.detail).to_dict()
