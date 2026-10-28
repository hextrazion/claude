"""Draft visuals: animated gradient cards rendered by FFmpeg. NOT AI footage.

Useful for checking script pacing, narration and captions end-to-end before
spending GPU time, and for automated tests. Projects made with it are flagged
in quality control so they are never mistaken for finished videos.
"""

from __future__ import annotations

import textwrap
import uuid
from pathlib import Path

from ...media.ffmpeg import FFmpeg, find_font_file
from ..base import HealthResult
from .base import Capabilities, CancelledFn, GenerationRequest, GenerationResult, ProgressFn

_PALETTES = [
    ("0x1e3a8a", "0x7c3aed"), ("0x0f766e", "0x22d3ee"), ("0x9a3412", "0xf59e0b"),
    ("0x831843", "0xf472b6"), ("0x14532d", "0x84cc16"), ("0x312e81", "0x38bdf8"),
]


class DraftAdapter:
    name = "draft"
    label = "Draft cards (FFmpeg, no AI)"
    is_ai = False

    def __init__(self, ffmpeg: FFmpeg):
        self.ffmpeg = ffmpeg
        self._pending: dict[str, GenerationRequest] = {}

    async def health(self) -> HealthResult:
        if not self.ffmpeg.available:
            return HealthResult("not_configured", "Needs FFmpeg.")
        return HealthResult("ok", "Ready. Produces placeholder cards, not AI video.")

    def capabilities(self, workflow: str) -> Capabilities:
        return Capabilities(kind="video", mode="t2v", width=720, height=1280, fps=24, max_frames=24 * 10, is_ai=False)

    async def submit(self, req: GenerationRequest) -> str:
        job_id = uuid.uuid4().hex
        self._pending[job_id] = req
        return job_id

    async def status(self, external_id: str) -> str:
        return "queued" if external_id in self._pending else "unknown"

    async def cancel(self, external_id: str) -> bool:
        return self._pending.pop(external_id, None) is not None

    async def wait(
        self, external_id: str, req: GenerationRequest, on_progress: ProgressFn, is_cancelled: CancelledFn, timeout: float
    ) -> GenerationResult:
        self._pending.pop(external_id, None)
        req.out_dir.mkdir(parents=True, exist_ok=True)
        out = req.out_dir / f"{req.filename_prefix}.mp4"
        fps = req.fps or 24
        seconds = max(1.0, (req.num_frames or fps * 4) / fps)
        if req.kind == "image":
            out = req.out_dir / f"{req.filename_prefix}.png"
        c0, c1 = _PALETTES[req.seed % len(_PALETTES)]
        size = f"{req.width}x{req.height}"
        vf = []
        font = find_font_file()
        text_file = None
        if font:
            text_file = req.out_dir / f"{req.filename_prefix}_label.txt"
            label = req.extra.get("label") or req.prompt
            wrapped = "\n".join(textwrap.wrap(label, 22)[:6])
            text_file.write_text(f"DRAFT\n\n{wrapped}", encoding="utf-8")
            fs = max(18, req.width // 18)
            # Relative paths + cwd avoid Windows drive-letter escaping problems.
            vf.append(
                f"drawtext=fontfile='{Path(font).as_posix().replace(':', chr(92) + ':')}':textfile={text_file.name}:"
                f"fontcolor=white:fontsize={fs}:line_spacing={fs // 3}:x=(w-text_w)/2:y=(h-text_h)/2:"
                f"box=1:boxcolor=black@0.35:boxborderw={fs // 2}"
            )
        vf.append("format=yuv420p")
        src = f"gradients=s={size}:c0={c0}:c1={c1}:x0=0:y0=0:x1={req.width}:y1={req.height}:speed=0.02:d={seconds}:r={fps}:seed={req.seed % 100000}"
        args = ["-f", "lavfi", "-i", src, "-vf", ",".join(vf)]
        if req.kind == "image":
            args += ["-frames:v", "1", out.name]
        else:
            args += ["-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", out.name]
        await on_progress(0.1, "Rendering draft card")
        await self.ffmpeg.run(args, cwd=req.out_dir, duration_hint=seconds, is_cancelled=is_cancelled, timeout=timeout)
        if text_file:
            text_file.unlink(missing_ok=True)
        return GenerationResult(files=[out], meta={"draft": True})
