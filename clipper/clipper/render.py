"""Assemble a Plan into a finished MP4 with ffmpeg."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import media
from .captions import to_ass
from .models import Clip, Plan

FPS = 30
ASPECT_SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
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


def _base_graph(W: int, H: int, src_wh: Tuple[int, int]) -> str:
    """Fit the source into WxH. Same shape: plain scale. Different shape: sharp video over a blurred copy."""
    sw, sh = src_wh
    if sw and sh and abs(sw / sh - W / H) < 0.02:
        return f"[0:v]scale={W}:{H},setsar=1,fps={FPS}"
    return (f"[0:v]split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=30:3[bg];[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}")


def clip_command(clip: Clip, rank: int, out: str, tmp: str, overlay: bool = True, has_audio: bool = True,
                 aspect: str = "16:9", style: str = "countdown", src_wh: Tuple[int, int] = (0, 0),
                 captions: bool = False) -> List[str]:
    W, H = ASPECT_SIZES[aspect]
    k = min(W, H) / 1080
    off = int(380 * k) if aspect == "9:16" else 0     # keep text clear of TikTok/Shorts UI
    dur = clip.duration
    vf = [_base_graph(W, H, src_wh)]
    if overlay:
        font = find_font()
        if style == "countdown":
            vf.append(_drawtext(_text(tmp, f"rank{rank}.txt", f"#{rank}"), int(110 * k), str(int(56 * k)),
                                str(int(48 * k)), "0x7C5CFFD9", font))
        if clip.title:
            vf.append(_drawtext(_text(tmp, f"title{rank}.txt", clip.title), int(44 * k), str(int(56 * k)),
                                f"h-th-{int(96 * k) + off}", "0x000000B3", font, "lt(t,4.5)"))
        if clip.credit:
            vf.append(_drawtext(_text(tmp, f"credit{rank}.txt", f"Source: {clip.credit}"), int(26 * k),
                                str(int(56 * k)), f"h-th-{int(40 * k) + off}", "0x00000099", font))
    if captions and clip.captions:
        rel = [{"start": c["start"] - clip.start, "end": c["end"] - clip.start, "text": c["text"]}
               for c in clip.captions if c["end"] > clip.start and c["start"] < clip.end]
        ass = Path(tmp) / f"cap{rank}.ass"
        ass.write_text(to_ass(rel, W, H, int(64 * k) if aspect == "9:16" else int(56 * k),
                              int(560 * k) if aspect == "9:16" else int(190 * k)), encoding="utf-8")
        vf.append(f"ass='{_fp(str(ass))}'")
    vf += ["fade=t=in:st=0:d=0.25", f"fade=t=out:st={max(0.0, dur - 0.25):.2f}:d=0.25", "format=yuv420p[v]"]
    graph = ",".join(vf)
    af = (f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,afade=t=in:d=0.2,"
          f"afade=t=out:st={max(0.0, dur - 0.2):.2f}:d=0.2")

    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{clip.start:.3f}", "-i", clip.source, "-t", f"{dur:.3f}"]
    if has_audio:
        cmd += ["-filter_complex", graph, "-af", af, "-map", "[v]", "-map", "0:a:0"]
    else:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                "-filter_complex", graph, "-map", "[v]", "-map", "1:a:0"]
    return cmd + ENC_V + ENC_A + [out]


def intro_command(title: str, out: str, tmp: str, aspect: str = "16:9", seconds: float = 2.5) -> List[str]:
    W, H = ASPECT_SIZES[aspect]
    k = min(W, H) / 1080
    # long titles wrap onto two lines so they stay on screen in narrow formats
    words, lines, cur = title.split(), [], ""
    for w in words:
        if cur and len(cur) + len(w) + 1 > (16 if aspect == "9:16" else 28):
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    dt = _drawtext(_text(tmp, "intro.txt", "\n".join(lines)), int(84 * k), "(w-tw)/2", "(h-th)/2", "0x7C5CFF00", find_font())
    return (["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x0F1115:s={W}x{H}:r={FPS}:d={seconds}",
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(seconds),
             "-vf", f"{dt},fade=t=in:d=0.4,format=yuv420p"] + ENC_V + ENC_A + [out])


def render(plan: Plan, out: str, overlay: Optional[bool] = None, intro: Optional[bool] = None,
           aspect: Optional[str] = None, style: Optional[str] = None, captions: Optional[bool] = None,
           on_progress: Optional[Callable[[int, int, str], None]] = None) -> str:
    """Render `plan.clips` (already in video order, best last) to `out`. Unset options come from plan.settings."""
    if not plan.clips:
        raise media.MediaError("the plan has no clips")
    st = plan.settings

    def pick(v, key, default):
        return v if v is not None else st.get(key, default)

    overlay, intro = pick(overlay, "overlay", True), pick(intro, "intro", True)
    aspect, style = pick(aspect, "aspect", "16:9"), pick(style, "style", "countdown")
    captions = pick(captions, "captions", False)
    if aspect not in ASPECT_SIZES:
        raise media.MediaError(f"unknown aspect {aspect!r}")

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
            media._run(intro_command(plan.title, p, tmp, aspect))
            parts.append(p)
            tick("intro")
        for i, clip in enumerate(plan.clips):
            rank = total - i
            p = str(Path(tmp) / f"clip{rank}.mp4")
            _, has_audio = media.probe(clip.source)
            media._run(clip_command(clip, rank, p, tmp, overlay, has_audio, aspect, style,
                                    media.probe_size(clip.source), captions))
            parts.append(p)
            tick(f"clip #{rank}: {clip.title}" if style == "countdown" else f"clip {i + 1}/{total}: {clip.title}")
        lst = Path(tmp) / "list.txt"
        lst.write_text("".join(f"file '{p.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for p in parts),
                       encoding="utf-8")
        media._run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", out])
        tick("joined")
    return out


def thumbnail(plan: Plan, out: str, aspect: Optional[str] = None) -> str:
    """Grab a frame from the best clip (last in the plan) with the video title on it."""
    aspect = aspect or plan.settings.get("aspect", "16:9")
    W, H = ASPECT_SIZES.get(aspect, ASPECT_SIZES["16:9"])
    k = min(W, H) / 1080
    best = plan.clips[-1]
    mid = best.start + best.duration * 0.6
    with tempfile.TemporaryDirectory(prefix="clipper_") as tmp:
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        vf += "," + _drawtext(_text(tmp, "t.txt", plan.title.upper()), int(96 * k), "(w-tw)/2", f"h-th-{int(80 * k)}",
                              "0x000000B3", find_font())
        media._run(["ffmpeg", "-v", "error", "-y", "-ss", f"{mid:.3f}", "-i", best.source,
                    "-frames:v", "1", "-vf", vf, "-q:v", "2", out])
    return out
