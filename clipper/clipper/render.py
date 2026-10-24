"""Assemble a Plan into a finished MP4 with ffmpeg."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from . import media
from .models import Clip, Plan

W, H, FPS = 1920, 1080, 30
ENC_V = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]
ENC_A = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]

_FONTS = [
    os.environ.get("CLIPPER_FONT", ""),
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def find_font() -> Optional[str]:
    return next((f for f in _FONTS if f and Path(f).exists()), None)


def _fp(path: str) -> str:
    """Escape a path for use inside an ffmpeg filter argument."""
    return path.replace("\\", "/").replace(":", "\\:")


def _text(tmp: str, name: str, value: str) -> str:
    p = Path(tmp) / name
    p.write_text(value, encoding="utf-8")
    return _fp(str(p))


def _drawtext(textfile: str, size: int, x: str, y: str, box: str, font: Optional[str], enable: str = "") -> str:
    s = (f"drawtext=textfile='{textfile}':fontsize={size}:fontcolor=white:box=1:boxcolor={box}:"
         f"boxborderw={max(8, size // 4)}:x={x}:y={y}")
    if font:
        s += f":fontfile='{_fp(font)}'"
    if enable:
        s += f":enable='{enable}'"
    return s


def clip_command(clip: Clip, rank: int, out: str, tmp: str, overlay: bool, has_audio: bool) -> List[str]:
    dur = clip.duration
    vf = [f"scale={W}:{H}:force_original_aspect_ratio=decrease", f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black",
          "setsar=1", f"fps={FPS}"]
    if overlay:
        font = find_font()
        vf.append(_drawtext(_text(tmp, f"rank{rank}.txt", f"#{rank}"), 110, "56", "48", "0x7C5CFFD9", font))
        vf.append(_drawtext(_text(tmp, f"title{rank}.txt", clip.title), 44, "56", "h-th-96",
                            "0x000000B3", font, "lt(t,4.5)"))
        if clip.credit:
            vf.append(_drawtext(_text(tmp, f"credit{rank}.txt", f"Source: {clip.credit}"), 26, "56", "h-th-40",
                                "0x00000099", font))
    vf += [f"fade=t=in:st=0:d=0.25", f"fade=t=out:st={max(0.0, dur - 0.25):.2f}:d=0.25", "format=yuv420p"]
    af = f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,afade=t=in:d=0.2,afade=t=out:st={max(0.0, dur - 0.2):.2f}:d=0.2"

    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{clip.start:.3f}", "-i", clip.source, "-t", f"{dur:.3f}"]
    if has_audio:
        cmd += ["-vf", ",".join(vf), "-af", af, "-map", "0:v:0", "-map", "0:a:0"]
    else:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                "-vf", ",".join(vf), "-map", "0:v:0", "-map", "1:a:0"]
    return cmd + ENC_V + ENC_A + [out]


def intro_command(title: str, out: str, tmp: str, seconds: float = 2.5) -> List[str]:
    font = find_font()
    tf = _text(tmp, "intro.txt", title)
    dt = _drawtext(tf, 84, "(w-tw)/2", "(h-th)/2", "0x7C5CFF00", font)
    return (["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x0F1115:s={W}x{H}:r={FPS}:d={seconds}",
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(seconds),
             "-vf", f"{dt},fade=t=in:d=0.4,format=yuv420p"] + ENC_V + ENC_A + [out])


def render(plan: Plan, out: str, overlay: bool = True, intro: bool = True,
           on_progress: Optional[Callable[[int, int, str], None]] = None) -> str:
    """Render `plan.clips` (already in video order, best last) to `out`. Returns the output path."""
    if not plan.clips:
        raise media.MediaError("the plan has no clips")
    total = len(plan.clips)
    steps = total + (1 if intro else 0) + 1
    done = 0

    def tick(msg: str) -> None:
        nonlocal done
        done += 1
        if on_progress:
            on_progress(done, steps, msg)

    Path(out).resolve().parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clipper_") as tmp:
        parts: List[str] = []
        if intro:
            p = str(Path(tmp) / "intro.mp4")
            media._run(intro_command(plan.title, p, tmp))
            parts.append(p)
            tick("intro")
        for i, clip in enumerate(plan.clips):
            rank = total - i
            p = str(Path(tmp) / f"clip{rank}.mp4")
            _, has_audio = media.probe(clip.source)
            media._run(clip_command(clip, rank, p, tmp, overlay, has_audio))
            parts.append(p)
            tick(f"clip #{rank}: {clip.title}")
        lst = Path(tmp) / "list.txt"
        lst.write_text("".join(f"file '{p.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for p in parts),
                       encoding="utf-8")
        media._run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", out])
        tick("joined")
    return out


def thumbnail(plan: Plan, out: str) -> str:
    """Grab a frame from the #1 clip (last in the plan) with the video title on it."""
    best = plan.clips[-1]
    mid = best.start + best.duration * 0.6
    with tempfile.TemporaryDirectory(prefix="clipper_") as tmp:
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        font = find_font()
        vf += "," + _drawtext(_text(tmp, "t.txt", plan.title.upper()), 96, "(w-tw)/2", "h-th-80", "0x000000B3", font)
        media._run(["ffmpeg", "-v", "error", "-y", "-ss", f"{mid:.3f}", "-i", best.source,
                    "-frames:v", "1", "-vf", vf, "-q:v", "2", out])
    return out
