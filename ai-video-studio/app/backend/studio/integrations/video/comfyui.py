"""ComfyUI adapter (local or remote ComfyUI server).

Uses ComfyUI's HTTP API: POST /prompt, GET /history/{id}, GET /queue,
POST /interrupt, POST /queue {delete}, GET /view, POST /upload/image,
GET /system_stats, GET /object_info, and the /ws websocket for progress.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

import httpx

from ...errors import Cancelled, ProviderError, ValidationFailed
from ..base import HealthResult, network_error, raise_for_status
from .base import Capabilities, CancelledFn, GenerationRequest, GenerationResult, ProgressFn
from .workflows import WorkflowLibrary, apply_bindings

log = logging.getLogger(__name__)

VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".gif", ".webp"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
DOCS_URL = "https://docs.comfy.org"

_OOM_MARKERS = ("outofmemory", "out of memory", "allocation on device", "cuda error: out of memory")


def _is_oom(text: str) -> bool:
    t = text.lower()
    return any(m in t for m in _OOM_MARKERS)


class ComfyUIAdapter:
    name = "comfyui"
    label = "ComfyUI"
    is_ai = True

    def __init__(self, base_url: str, workflows: WorkflowLibrary, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.workflows = workflows
        self.transport = transport
        self.client_id = uuid.uuid4().hex
        self._progress: dict[str, tuple[float, str]] = {}

    def _client(self, timeout: float = 30) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=timeout, transport=self.transport)

    async def _get(self, path: str, **kw) -> httpx.Response:
        async with self._client() as c:
            try:
                resp = await c.get(path, **kw)
            except httpx.HTTPError as exc:
                raise network_error("ComfyUI", exc) from exc
        raise_for_status(resp, "ComfyUI")
        return resp

    async def _post(self, path: str, **kw) -> httpx.Response:
        async with self._client() as c:
            try:
                resp = await c.post(path, **kw)
            except httpx.HTTPError as exc:
                raise network_error("ComfyUI", exc) from exc
        return resp

    # -- health / validation --------------------------------------------------
    async def system_stats(self) -> dict:
        return (await self._get("/system_stats")).json()

    async def health(self) -> HealthResult:
        try:
            stats = await self.system_stats()
        except ProviderError as exc:
            return HealthResult(
                "unavailable",
                f"ComfyUI is not reachable at {self.base_url}. Start ComfyUI, then test again.",
                detail=exc.detail,
            )
        devices = stats.get("devices") or []
        system = stats.get("system") or {}
        info = {
            "comfyui_version": system.get("comfyui_version"),
            "pytorch_version": system.get("pytorch_version"),
            "devices": [
                {
                    "name": d.get("name"),
                    "vram_total_gb": round((d.get("vram_total") or 0) / 1024**3, 1),
                    "vram_free_gb": round((d.get("vram_free") or 0) / 1024**3, 1),
                }
                for d in devices
            ],
        }
        gpu = info["devices"][0]["name"] if info["devices"] else "no GPU reported"
        return HealthResult("ok", f"Connected to ComfyUI ({gpu}).", info=info)

    async def check_workflow(self, name: str) -> HealthResult:
        """Verify every node type exists and every model file the graph names is installed."""
        try:
            wf = self.workflows.get(name)
        except ValidationFailed as exc:
            return HealthResult("error", exc.message)
        try:
            object_info = (await self._get("/object_info")).json()
        except ProviderError as exc:
            return HealthResult("unavailable", "ComfyUI is not reachable.", detail=exc.detail)
        missing_nodes, missing_files = [], []
        bound = {(str(t["node"]), t["input"]) for ts in (wf.get("bindings") or {}).values() for t in ts}
        for nid, node in wf["workflow"].items():
            ct = node.get("class_type")
            spec = object_info.get(ct)
            if spec is None:
                missing_nodes.append(ct)
                continue
            inputs_spec = {**(spec.get("input", {}).get("required") or {}), **(spec.get("input", {}).get("optional") or {})}
            for inp, value in (node.get("inputs") or {}).items():
                if (nid, inp) in bound or not isinstance(value, str):
                    continue
                s = inputs_spec.get(inp)
                choices = s[0] if isinstance(s, list) and s and isinstance(s[0], list) else None
                if choices is not None and value not in choices and value.endswith((".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin")):
                    missing_files.append(f"{value} (for {ct}.{inp})")
        if missing_nodes or missing_files:
            parts = []
            if missing_nodes:
                parts.append("Missing node types: " + ", ".join(sorted(set(missing_nodes))) +
                             ". Update ComfyUI or install the custom nodes this workflow needs.")
            if missing_files:
                parts.append("Missing model files: " + "; ".join(missing_files) +
                             ". Download them into ComfyUI's models folders (see docs/VIDEO_MODELS.md).")
            return HealthResult("error", "Workflow is not ready.", detail="\n".join(parts),
                                info={"missing_nodes": missing_nodes, "missing_files": missing_files})
        return HealthResult("ok", f"Workflow '{wf.get('label', name)}' is ready: all nodes and model files found.")

    def capabilities(self, workflow: str) -> Capabilities:
        wf = self.workflows.get(workflow)
        d = wf.get("defaults", {})
        return Capabilities(
            kind=wf.get("kind", "video"),
            mode=wf.get("mode", "t2v"),
            width=int(d.get("width", 704)),
            height=int(d.get("height", 1280)),
            fps=int(d.get("fps", 24)),
            max_frames=int(d.get("max_frames", 121)),
            frame_multiple=int(d.get("frame_multiple", 1)),
        )

    # -- jobs -----------------------------------------------------------------
    async def _upload_image(self, path: Path) -> str:
        with path.open("rb") as fh:
            resp = await self._post(
                "/upload/image",
                files={"image": (path.name, fh, "image/png")},
                data={"overwrite": "true", "type": "input"},
            )
        raise_for_status(resp, "ComfyUI")
        data = resp.json()
        sub = data.get("subfolder") or ""
        return f"{sub}/{data['name']}" if sub else data["name"]

    async def submit(self, req: GenerationRequest) -> str:
        wf = self.workflows.get(req.workflow)
        values = {
            "prompt": req.prompt,
            "negative_prompt": req.negative_prompt,
            "width": req.width,
            "height": req.height,
            "frames": req.num_frames,
            "fps": req.fps,
            "seed": req.seed,
            "filename_prefix": f"ai_video_studio/{req.filename_prefix}",
            "seconds": round(req.num_frames / req.fps, 2) if req.num_frames and req.fps else None,
        }
        if wf.get("mode") == "i2v" or (wf.get("bindings") or {}).get("image"):
            if not req.image_path:
                raise ValidationFailed("This workflow needs a source image, but the scene has none.")
            values["image"] = await self._upload_image(req.image_path)
        graph = apply_bindings(wf, values)
        resp = await self._post("/prompt", json={"prompt": graph, "client_id": self.client_id})
        if resp.status_code == 400:
            # ComfyUI explains graph validation problems in the body.
            try:
                body = resp.json()
            except json.JSONDecodeError:
                body = {"error": resp.text[:500]}
            detail = json.dumps(body)[:1500]
            raise ProviderError(
                "ComfyUI rejected the workflow. Run 'Check workflow' on the Integrations page.",
                kind="invalid_request", detail=detail, provider="comfyui",
            )
        raise_for_status(resp, "ComfyUI")
        prompt_id = resp.json().get("prompt_id")
        if not prompt_id:
            raise ProviderError("ComfyUI did not return a prompt id.", kind="transient", provider="comfyui")
        return prompt_id

    async def _history(self, prompt_id: str) -> dict | None:
        data = (await self._get(f"/history/{prompt_id}")).json()
        return data.get(prompt_id)

    async def _queue(self) -> dict:
        return (await self._get("/queue")).json()

    async def status(self, external_id: str) -> str:
        try:
            hist = await self._history(external_id)
            if hist:
                st = (hist.get("status") or {}).get("status_str")
                return "failed" if st == "error" else "completed"
            q = await self._queue()
        except ProviderError:
            return "unknown"
        if any(item[1] == external_id for item in q.get("queue_running", []) if len(item) > 1):
            return "running"
        if any(item[1] == external_id for item in q.get("queue_pending", []) if len(item) > 1):
            return "queued"
        return "unknown"

    async def cancel(self, external_id: str) -> bool:
        try:
            q = await self._queue()
        except ProviderError:
            return False
        if any(item[1] == external_id for item in q.get("queue_pending", []) if len(item) > 1):
            resp = await self._post("/queue", json={"delete": [external_id]})
            return resp.is_success
        if any(item[1] == external_id for item in q.get("queue_running", []) if len(item) > 1):
            # Only interrupt when *our* prompt is the one executing.
            resp = await self._post("/interrupt", json={"prompt_id": external_id})
            return resp.is_success
        return False

    async def _listen_progress(self, prompt_id: str) -> None:
        """Best effort: progress via websocket. Polling decides completion."""
        try:
            import websockets
        except ImportError:  # pragma: no cover
            return
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={self.client_id}"
        try:
            async with websockets.connect(ws_url, max_size=None, open_timeout=10) as ws:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue  # preview images
                    msg = json.loads(raw)
                    data = msg.get("data") or {}
                    if data.get("prompt_id") not in (None, prompt_id):
                        continue
                    if msg.get("type") == "progress" and data.get("max"):
                        self._progress[prompt_id] = (data["value"] / data["max"], f"Sampling step {data['value']}/{data['max']}")
                    elif msg.get("type") == "executing" and data.get("node"):
                        frac = self._progress.get(prompt_id, (None, ""))[0]
                        self._progress[prompt_id] = (frac, f"Running node {data['node']}")
        except Exception as exc:
            log.debug("comfyui websocket closed: %r", exc)

    async def wait(
        self, external_id: str, req: GenerationRequest, on_progress: ProgressFn, is_cancelled: CancelledFn, timeout: float
    ) -> GenerationResult:
        listener = asyncio.create_task(self._listen_progress(external_id))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        unreachable_since: float | None = None
        last_reported = None
        try:
            while True:
                if is_cancelled():
                    await self.cancel(external_id)
                    raise Cancelled()
                if loop.time() > deadline:
                    await self.cancel(external_id)
                    raise ProviderError(
                        f"Generation exceeded the {int(timeout)}s timeout and was cancelled.",
                        kind="timeout", provider="comfyui",
                    )
                try:
                    hist = await self._history(external_id)
                    unreachable_since = None
                except ProviderError:
                    unreachable_since = unreachable_since or loop.time()
                    if loop.time() - unreachable_since > 120:
                        raise ProviderError("Lost connection to ComfyUI during generation.", kind="unavailable",
                                            provider="comfyui")
                    hist = None
                if hist:
                    return await self._collect(external_id, hist, req)
                prog = self._progress.get(external_id)
                if prog and prog != last_reported:
                    last_reported = prog
                    await on_progress(prog[0], prog[1])
                elif last_reported is None:
                    q_status = await self.status(external_id)
                    if q_status == "queued":
                        await on_progress(None, "Waiting in ComfyUI's queue")
                    elif q_status == "unknown":
                        # Not in history or queue: ComfyUI restarted or the prompt was removed.
                        await asyncio.sleep(2)
                        if not await self._history(external_id) and await self.status(external_id) == "unknown":
                            raise ProviderError("ComfyUI no longer knows this job (was it restarted?).",
                                                kind="transient", provider="comfyui")
                await asyncio.sleep(2)
        finally:
            listener.cancel()
            self._progress.pop(external_id, None)

    async def _collect(self, prompt_id: str, hist: dict, req: GenerationRequest) -> GenerationResult:
        status = hist.get("status") or {}
        if status.get("status_str") == "error":
            err_text = ""
            for m in status.get("messages", []):
                if isinstance(m, list) and m and m[0] == "execution_error":
                    d = m[1] if len(m) > 1 else {}
                    err_text = f"{d.get('exception_type', '')}: {d.get('exception_message', '')} (node {d.get('node_type', '?')})"
            if _is_oom(err_text):
                raise ProviderError(
                    "The GPU ran out of memory. Try a lower resolution, fewer frames, a quantised model, "
                    "or close other GPU-heavy apps (games, browsers with hardware acceleration).",
                    kind="oom", detail=err_text, provider="comfyui",
                )
            if "interrupt" in err_text.lower():
                raise Cancelled()
            raise ProviderError("ComfyUI reported an error while generating.", kind="permanent", detail=err_text,
                                provider="comfyui")
        wanted = VIDEO_EXT if req.kind == "video" else IMAGE_EXT
        files: list[dict] = []
        for node_out in (hist.get("outputs") or {}).values():
            for items in node_out.values():
                if isinstance(items, list):
                    files.extend(i for i in items if isinstance(i, dict) and i.get("filename"))
        files = [f for f in files if f.get("type", "output") == "output" and Path(f["filename"]).suffix.lower() in wanted]
        if not files:
            raise ProviderError("ComfyUI finished but produced no output file of the expected type.",
                                kind="permanent", detail=json.dumps(hist.get("outputs"))[:1000], provider="comfyui")
        req.out_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        async with self._client(timeout=300) as c:
            for i, f in enumerate(files[:1] if req.kind == "video" else files):
                ext = Path(f["filename"]).suffix.lower()
                dest = req.out_dir / (f"{req.filename_prefix}{'' if i == 0 else f'_{i}'}{ext}")
                params = {"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": "output"}
                try:
                    async with c.stream("GET", "/view", params=params) as resp:
                        raise_for_status(resp, "ComfyUI")
                        with dest.open("wb") as fh:
                            async for chunk in resp.aiter_bytes():
                                fh.write(chunk)
                except httpx.HTTPError as exc:
                    raise network_error("ComfyUI", exc) from exc
                saved.append(dest)
        return GenerationResult(files=saved, meta={"comfy_prompt_id": prompt_id, "comfy_files": files})
