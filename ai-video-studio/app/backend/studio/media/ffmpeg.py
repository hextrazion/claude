"""FFmpeg/ffprobe wrapper.

Only structured argument lists are executed (never a shell string), the
executable is always one of the two resolved binaries, and file arguments are
paths the pipeline built itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from ..errors import Cancelled, StudioError
from ..integrations.base import HealthResult

log = logging.getLogger(__name__)

_TIME_RE = re.compile(r"out_time_us=(\d+)")
# Keep FFmpeg from flashing console windows when the studio runs without one.
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


@dataclass
class FFmpegPaths:
    ffmpeg: str
    ffprobe: str


def locate(ffmpeg_hint: str | None = None) -> FFmpegPaths | None:
    """Find ffmpeg/ffprobe: env FFMPEG_PATH, then tools/ffmpeg/bin, then PATH."""
    exe = ".exe" if sys.platform == "win32" else ""
    candidates: list[Path] = []
    hint = ffmpeg_hint or os.environ.get("FFMPEG_PATH")
    if hint:
        p = Path(hint)
        candidates.append(p if p.is_dir() else p.parent)
    from ..config import REPO_ROOT

    candidates.append(REPO_ROOT / "tools" / "ffmpeg" / "bin")
    for d in candidates:
        f, p = d / f"ffmpeg{exe}", d / f"ffprobe{exe}"
        if f.is_file() and p.is_file():
            return FFmpegPaths(str(f), str(p))
    f, p = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if f and p:
        return FFmpegPaths(f, p)
    return None


class FFmpeg:
    def __init__(self, paths: FFmpegPaths | None = None):
        self.paths = paths or locate()

    @property
    def available(self) -> bool:
        return self.paths is not None

    def _require(self) -> FFmpegPaths:
        if not self.paths:
            raise StudioError(
                "FFmpeg was not found. Install it (see docs/SETUP.md) or set FFMPEG_PATH.",
                kind="not_configured",
            )
        return self.paths

    def version(self) -> str | None:
        if not self.paths:
            return None
        try:
            out = subprocess.run([self.paths.ffmpeg, "-hide_banner", "-version"], capture_output=True, text=True,
                                 timeout=15, **_NO_WINDOW)
            return out.stdout.splitlines()[0] if out.stdout else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def has_filter(self, name: str) -> bool:
        if not self.paths:
            return False
        try:
            out = subprocess.run([self.paths.ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True,
                                 timeout=15, **_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return any(line.split()[1:2] == [name] for line in out.stdout.splitlines() if line.strip())

    def health(self) -> HealthResult:
        if not self.paths:
            return HealthResult("not_configured", "FFmpeg not found. It is required for assembly.")
        version = self.version()
        if not version:
            return HealthResult("error", "FFmpeg was found but did not run.", detail=self.paths.ffmpeg)
        missing = [f for f in ("subtitles", "xfade", "loudnorm") if not self.has_filter(f)]
        if missing:
            return HealthResult(
                "warning",
                f"{version.split(' Copyright')[0]} — missing filters: {', '.join(missing)}",
                detail="Install a full FFmpeg build (e.g. gyan.dev 'full' build on Windows).",
                info={"path": self.paths.ffmpeg},
            )
        return HealthResult("ok", version.split(" Copyright")[0], info={"path": self.paths.ffmpeg})

    async def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        duration_hint: float | None = None,
        on_progress: Callable[[float], Awaitable[None] | None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        timeout: float = 1800,
    ) -> str:
        """Run ffmpeg with the given arguments; returns stderr tail on success."""
        paths = self._require()
        cmd = [paths.ffmpeg, "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
        log.debug("ffmpeg %s", " ".join(cmd[1:]))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd) if cwd else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **_NO_WINDOW,
            )
        except NotImplementedError as exc:  # pragma: no cover - Windows selector event loop
            raise StudioError(
                "This Python event loop cannot start FFmpeg. Launch the studio with scripts\\start.bat.",
                kind="permanent",
            ) from exc
        stderr_chunks: list[bytes] = []

        async def read_stderr():
            assert proc.stderr
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break
                stderr_chunks.append(chunk)
                if len(stderr_chunks) > 400:
                    del stderr_chunks[:200]

        async def read_progress():
            assert proc.stdout
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                m = _TIME_RE.search(line.decode(errors="ignore"))
                if m and duration_hint and on_progress:
                    frac = min(1.0, int(m.group(1)) / 1e6 / duration_hint)
                    r = on_progress(frac)
                    if asyncio.iscoroutine(r):
                        await r

        async def watch_cancel():
            while proc.returncode is None:
                if is_cancelled and is_cancelled():
                    proc.kill()
                    return True
                await asyncio.sleep(0.5)
            return False

        tasks = [asyncio.create_task(read_stderr()), asyncio.create_task(read_progress())]
        cancel_task = asyncio.create_task(watch_cancel())
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise StudioError("FFmpeg timed out.", kind="timeout")
        finally:
            await asyncio.gather(*tasks, return_exceptions=True)
            cancel_task.cancel()
        if cancel_task.done() and not cancel_task.cancelled() and cancel_task.result():
            raise Cancelled()
        stderr = b"".join(stderr_chunks).decode(errors="replace")
        if proc.returncode != 0:
            if is_cancelled and is_cancelled():
                raise Cancelled()
            tail = "\n".join(stderr.strip().splitlines()[-15:])
            raise StudioError("FFmpeg failed while processing media.", kind="permanent", detail=tail)
        return stderr[-20000:]

    async def probe(self, path: Path) -> dict:
        paths = self._require()
        proc = await asyncio.create_subprocess_exec(
            paths.ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **_NO_WINDOW,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            raise StudioError(f"Could not read media file {path.name}.", kind="permanent", detail=err.decode(errors="replace")[-500:])
        return json.loads(out or b"{}")


@dataclass
class MediaInfo:
    duration: float
    width: int | None
    height: int | None
    fps: float | None
    has_video: bool
    has_audio: bool
    video_codec: str | None
    audio_codec: str | None
    size_bytes: int

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def media_info(probe: dict) -> MediaInfo:
    streams = probe.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = probe.get("format", {})
    duration = float(fmt.get("duration") or (v or {}).get("duration") or (a or {}).get("duration") or 0)
    fps = None
    if v and v.get("avg_frame_rate") and v["avg_frame_rate"] != "0/0":
        num, _, den = v["avg_frame_rate"].partition("/")
        try:
            fps = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            fps = None
    return MediaInfo(
        duration=duration,
        width=int(v["width"]) if v and v.get("width") else None,
        height=int(v["height"]) if v and v.get("height") else None,
        fps=fps,
        has_video=v is not None,
        has_audio=a is not None,
        video_codec=v.get("codec_name") if v else None,
        audio_codec=a.get("codec_name") if a else None,
        size_bytes=int(fmt.get("size") or 0),
    )


def find_font_file() -> str | None:
    """A TrueType font for drawtext (used only by draft visuals)."""
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    return next((c for c in candidates if Path(c).is_file()), None)


def escape_filter_value(value: str) -> str:
    """Escape a value for use inside an FFmpeg filter argument."""
    return value.replace("\\", "/").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")
