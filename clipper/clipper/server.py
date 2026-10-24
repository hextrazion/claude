"""Local review UI: edit the plan, preview clips, render. Binds to 127.0.0.1 only."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from . import media, render
from .models import Plan

WEB = Path(__file__).parent / "web"


class State:
    def __init__(self, plan_path: str):
        self.plan_path = plan_path
        self.lock = threading.Lock()
        self.cache = tempfile.mkdtemp(prefix="clipper_preview_")
        self.render = {"status": "idle", "step": 0, "total": 0, "message": "", "output": "", "error": ""}
        self.preview_lock = threading.Lock()

    def plan(self) -> Plan:
        return Plan.load(self.plan_path)


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

        def do_GET(self):
            u = urlparse(self.path)
            try:
                if u.path == "/":
                    return self._file(str(WEB / "index.html"), "text/html; charset=utf-8")
                if u.path == "/api/plan":
                    return self._json(asdict(state.plan()))
                if u.path == "/api/state":
                    return self._json(state.render)
                if u.path.startswith("/preview/"):
                    p = _preview(state, state.plan(), int(u.path.rsplit("/", 1)[1].split(".")[0]))
                    return self._file(p, "video/mp4") if p else self._json({"error": "no such clip"}, 404)
                if u.path == "/video" and state.render["output"] and os.path.exists(state.render["output"]):
                    return self._file(state.render["output"], "video/mp4")
                if u.path == "/thumbnail":
                    t = str(Path(state.render["output"] or "top5.mp4").with_suffix(".jpg"))
                    return self._file(t, "image/jpeg") if os.path.exists(t) else self._json({"error": "none"}, 404)
            except (media.MediaError, ValueError, OSError) as e:
                return self._json({"error": str(e)}, 500)
            self._json({"error": "not found"}, 404)

        def do_PUT(self):
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

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                opts = self._body()
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            if path == "/api/render":
                with state.lock:
                    if state.render["status"] == "running":
                        return self._json({"error": "a render is already running"}, 409)
                    state.render = {"status": "running", "step": 0, "total": 0, "message": "starting",
                                    "output": "", "error": ""}
                out = str(Path(opts.get("output") or "top5.mp4").resolve())
                threading.Thread(target=_run_render, args=(state, out, bool(opts.get("overlay", True)),
                                                           bool(opts.get("intro", True))), daemon=True).start()
                return self._json({"ok": True, "output": out})
            self._json({"error": "not found"}, 404)

    return H


def _run_render(state: State, out: str, overlay: bool, intro: bool) -> None:
    def prog(i, n, msg):
        state.render.update(step=i, total=n, message=msg)
    try:
        plan = state.plan()
        render.render(plan, out, overlay=overlay, intro=intro, on_progress=prog)
        render.thumbnail(plan, str(Path(out).with_suffix(".jpg")))
        state.render.update(status="done", output=out, message="done")
    except Exception as e:  # surface any failure in the UI instead of dying silently
        state.render.update(status="error", error=str(e))


def make_server(plan_path: str, port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), _handler(State(plan_path)))


def serve(plan_path: str, port: int = 8765, open_browser: bool = True) -> None:
    srv = make_server(plan_path, port)
    url = f"http://127.0.0.1:{srv.server_port}/"
    print(f"review UI: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
