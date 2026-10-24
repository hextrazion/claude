"""Local app server: chat assistant, job runner, review UI. Binds to 127.0.0.1 only."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from . import jobs, media, render
from .chat import ChatAgent
from .llm import LLMError, LocalLLM
from .models import Plan
from .spec import JobSpec, is_actionable, normalize

WEB = Path(__file__).parent / "web"
CSRF_HEADER = "X-Clipper"   # custom header on every write: browsers can't send it cross-site without a preflight


@dataclass
class ServerConfig:
    workdir: str = "."
    llm_url: str = "http://localhost:11434/v1"
    llm_model: str = ""
    use_llm: bool = True
    whisper: str = "small"


class State:
    def __init__(self, plan_path: str, config: Optional[ServerConfig] = None, ctx: Optional[jobs.Context] = None):
        self.plan_path = plan_path
        self.config = config or ServerConfig()
        self.lock = threading.Lock()
        self.cache = tempfile.mkdtemp(prefix="clipper_preview_")
        self.preview_lock = threading.Lock()
        self.render = {"status": "idle", "step": 0, "total": 0, "message": "", "output": "", "error": ""}
        llm = LocalLLM(self.config.llm_url, self.config.llm_model) if self.config.use_llm else None
        self.agent = ChatAgent(llm)
        self.ctx = ctx or jobs.Context(workdir=self.config.workdir, llm=llm, whisper=self.config.whisper)
        self.history: List[dict] = []
        self.spec: Optional[JobSpec] = None
        self.job = {"status": "idle", "log": [], "output": "", "error": ""}

    def plan(self) -> Plan:
        return Plan.load(self.plan_path) if Path(self.plan_path).exists() else Plan(clips=[])

    def busy(self) -> bool:
        return self.render["status"] == "running" or self.job["status"] == "running"


def _preview(state: State, plan: Plan, i: int) -> Optional[str]:
    if not 0 <= i < len(plan.clips):
        return None
    c = plan.clips[i]
    key = hashlib.sha1(f"{c.source}|{c.start:.2f}|{c.end:.2f}".encode()).hexdigest()[:16]
    out = os.path.join(state.cache, key + ".mp4")
    with state.preview_lock:
        if not os.path.exists(out):
            _, has_audio = media.probe(c.source)
            cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{c.start:.3f}", "-i", c.source, "-t", f"{c.duration:.3f}",
                   "-vf", "scale=640:-2", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p"]
            cmd += ["-c:a", "aac", "-b:a", "96k"] if has_audio else ["-an"]
            media._run(cmd + [out])
    return out


def _out_path(state: State, name: str, default: str) -> str:
    """Output always lands in the work folder, whatever name the browser sends."""
    base = Path(str(name or default)).name or default
    if not base.lower().endswith(".mp4"):
        base += ".mp4"
    return str((Path(state.config.workdir) / base).resolve())


def _handler(state: State):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _guard(self, write: bool) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):            # DNS-rebinding defence
                self._json({"error": "forbidden host"}, 403)
                return False
            if write and self.headers.get(CSRF_HEADER) != "1":
                self._json({"error": "missing " + CSRF_HEADER + " header"}, 403)
                return False
            return True

        def _file(self, path: str, ctype: str):
            size = os.path.getsize(path)
            start, end, code = 0, size - 1, 200
            rng = self.headers.get("Range", "")
            if rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                try:
                    if a:
                        start, end = int(a), (int(b) if b else size - 1)
                    else:
                        start = max(0, size - int(b))
                except ValueError:
                    return self._json({"error": "bad range"}, 416)
                end = min(end, size - 1)
                if start > end:
                    return self._json({"error": "bad range"}, 416)
                code = 206
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                raise ValueError("body too large")
            return json.loads(self.rfile.read(n) or b"{}")

        # ---- GET -------------------------------------------------------------------------------------------
        def do_GET(self):
            if not self._guard(False):
                return
            u = urlparse(self.path)
            try:
                if u.path == "/":
                    return self._file(str(WEB / "index.html"), "text/html; charset=utf-8")
                if u.path == "/api/plan":
                    return self._json(asdict(state.plan()))
                if u.path == "/api/state":
                    return self._json(state.render)
                if u.path == "/api/chat":
                    return self._json({"history": state.history, "spec": state.spec.to_dict() if state.spec else None,
                                       "model": state.agent.llm.model if state.agent.llm else None,
                                       "llm": state.agent.llm is not None})
                if u.path == "/api/job":
                    since = int((parse_qs(u.query).get("since") or ["0"])[0])
                    j = state.job
                    return self._json({"status": j["status"], "log": j["log"][since:], "n": len(j["log"]),
                                       "output": j["output"], "error": j["error"]})
                if u.path.startswith("/preview/"):
                    p = _preview(state, state.plan(), int(u.path.rsplit("/", 1)[1].split(".")[0]))
                    return self._file(p, "video/mp4") if p else self._json({"error": "no such clip"}, 404)
                if u.path == "/video" and state.render["output"] and os.path.exists(state.render["output"]):
                    return self._file(state.render["output"], "video/mp4")
                if u.path == "/thumbnail":
                    t = str(Path(state.render["output"] or "x.mp4").with_suffix(".jpg"))
                    return self._file(t, "image/jpeg") if os.path.exists(t) else self._json({"error": "none"}, 404)
            except (media.MediaError, ValueError, OSError) as e:
                return self._json({"error": str(e)}, 500)
            self._json({"error": "not found"}, 404)

        # ---- PUT -------------------------------------------------------------------------------------------
        def do_PUT(self):
            if not self._guard(True):
                return
            if urlparse(self.path).path != "/api/plan":
                return self._json({"error": "not found"}, 404)
            try:
                d = self._body()
                tmp = Path(state.plan_path).with_suffix(".tmp")
                tmp.write_text(json.dumps(d), encoding="utf-8")
                Plan.load(tmp)                       # validates shape
                tmp.replace(state.plan_path)
                self._json({"ok": True})
            except (ValueError, TypeError, KeyError) as e:
                self._json({"error": f"invalid plan: {e}"}, 400)

        # ---- POST ------------------------------------------------------------------------------------------
        def do_POST(self):
            if not self._guard(True):
                return
            path = urlparse(self.path).path
            try:
                opts = self._body()
            except ValueError as e:
                return self._json({"error": str(e)}, 400)

            if path == "/api/chat":
                msg = str(opts.get("message", "")).strip()[:2000]
                if not msg:
                    return self._json({"error": "empty message"}, 400)
                reply, spec = state.agent.respond(state.history, msg, state.spec)
                state.history += [{"role": "user", "content": msg}, {"role": "assistant", "content": reply}]
                state.spec = spec
                return self._json({"reply": reply, "spec": spec.to_dict() if spec else None})

            if path == "/api/job":
                spec = normalize(opts["spec"], state.spec) if isinstance(opts.get("spec"), dict) else state.spec
                if spec is None or not is_actionable(spec):
                    return self._json({"error": "nothing to do yet - tell me who to find clips from"}, 400)
                with state.lock:
                    if state.busy():
                        return self._json({"error": "something is already running"}, 409)
                    state.job = {"status": "running", "log": [], "output": "", "error": ""}
                state.spec = spec
                threading.Thread(target=_run_job, args=(state, spec), daemon=True).start()
                return self._json({"ok": True})

            if path == "/api/render":
                with state.lock:
                    if state.busy():
                        return self._json({"error": "something is already running"}, 409)
                    state.render = {"status": "running", "step": 0, "total": 0, "message": "starting",
                                    "output": "", "error": ""}
                out = _out_path(state, opts.get("output"), "top5.mp4")
                over = {k: opts[k] for k in ("overlay", "intro", "captions") if isinstance(opts.get(k), bool)}
                for k in ("aspect", "style"):
                    if isinstance(opts.get(k), str):
                        over[k] = opts[k]
                threading.Thread(target=_run_render, args=(state, out, over), daemon=True).start()
                return self._json({"ok": True, "output": out})
            self._json({"error": "not found"}, 404)

    return H


def _run_render(state: State, out: str, opts: dict) -> None:
    def prog(i, n, msg):
        state.render.update(step=i, total=n, message=msg)
    try:
        plan = state.plan()
        render.render(plan, out, on_progress=prog, **opts)
        render.thumbnail(plan, str(Path(out).with_suffix(".jpg")), aspect=opts.get("aspect"))
        state.render.update(status="done", output=out, message="done")
    except Exception as e:  # surface any failure in the UI instead of dying silently
        state.render.update(status="error", error=str(e))


def _run_job(state: State, spec: JobSpec) -> None:
    log = state.job["log"]
    try:
        res = jobs.run_job(spec, state.ctx, state.plan_path, log.append)
        state.render = {"status": "done", "step": 1, "total": 1, "message": "done", "output": res["output"], "error": ""}
        state.job.update(status="done", output=res["output"])
    except (media.MediaError, LLMError) as e:
        log.append(f"Stopped: {e}")
        state.job.update(status="error", error=str(e))
    except Exception as e:  # unexpected: still show it instead of hanging the chat
        log.append(f"Unexpected error: {e}")
        state.job.update(status="error", error=f"unexpected error: {e}")


def make_server(plan_path: str, port: int = 8765, config: Optional[ServerConfig] = None,
                ctx: Optional[jobs.Context] = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), _handler(State(plan_path, config, ctx)))


def serve(plan_path: str, port: int = 8765, open_browser: bool = True, config: Optional[ServerConfig] = None) -> None:
    config = config or ServerConfig()
    Path(config.workdir).mkdir(parents=True, exist_ok=True)
    srv = make_server(plan_path, port, config)
    url = f"http://127.0.0.1:{srv.server_port}/"
    print(f"Clip Compiler: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
