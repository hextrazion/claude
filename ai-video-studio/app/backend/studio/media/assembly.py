"""Final video assembly with FFmpeg.

Narration sets the pacing: each scene occupies the span of its narration on
the timeline, and footage is trimmed, gently slowed, or (as a last resort)
held on its last frame to fit. Problems are reported as flags, never hidden.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from ..settings import Settings
from .ffmpeg import FFmpeg

XFADE = {"fade": "fade", "dissolve": "dissolve", "slideup": "slideup"}


@dataclass
class SegmentPlan:
    index: int
    clip: Path
    clip_duration: float
    target: float  # length on the timeline (without transition overlap)
    render_length: float  # target + overlap for the next transition
    speed: float  # >1 means slowed down
    freeze: float
    flags: list[str] = field(default_factory=list)


def plan_segments(
    clips: list[tuple[Path, float]],
    spans: list[tuple[float, float]],
    *,
    max_stretch: float,
    transition_s: float,
) -> list[SegmentPlan]:
    plans = []
    n = len(clips)
    for i, ((clip, clip_dur), (start, end)) in enumerate(zip(clips, spans)):
        target = max(0.2, end - start)
        overlap = transition_s if i < n - 1 else 0.0
        need = target + overlap
        flags: list[str] = []
        speed, freeze = 1.0, 0.0
        if clip_dur <= 0:
            freeze = need
            flags.append("Clip has no readable duration; showing a still frame.")
        elif clip_dur >= need:
            if clip_dur > need * 2.5 and clip_dur - need > 3:
                flags.append(f"Clip is {clip_dur:.1f}s but the narration only needs {need:.1f}s; it was trimmed.")
        else:
            speed = min(max_stretch, need / clip_dur)
            freeze = max(0.0, need - clip_dur * speed)
            if freeze > 0.4 * need:
                flags.append(
                    f"Clip is too short ({clip_dur:.1f}s for {need:.1f}s of narration); the last frame is held for "
                    f"{freeze:.1f}s. Consider regenerating with more frames or splitting the scene."
                )
        plans.append(SegmentPlan(i, clip, clip_dur, target, need, round(speed, 4), round(freeze, 3), flags))
    return plans


def fit_filter(mode: str, w: int, h: int) -> str:
    """Filter graph (input [0:v], output [fit]) that fits footage to the frame."""
    if mode == "black_pad":
        return (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black[fit]")
    if mode == "blur_pad":
        return (f"[0:v]split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                f"boxblur=24:2[bg];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[fit]")
    return f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[fit]"


def segment_args(plan: SegmentPlan, out: Path, s: Settings) -> list[str]:
    v = s.video
    chain = [fit_filter(v.fit_mode, v.width, v.height)]
    post = []
    if plan.speed != 1.0:
        post.append(f"setpts={plan.speed}*PTS")
    post.append(f"fps={v.fps}")
    if plan.freeze > 0:
        post.append(f"tpad=stop_mode=clone:stop_duration={plan.freeze + 0.5:.3f}")
    post += ["setsar=1", "format=yuv420p"]
    graph = ";".join(chain) + f";[fit]{','.join(post)}[out]"
    args = []
    if plan.clip_duration <= 0:
        args += ["-loop", "1"]
    args += [
        "-i", str(plan.clip), "-filter_complex", graph, "-map", "[out]", "-an",
        "-t", f"{plan.render_length:.3f}", "-r", str(v.fps),
        "-c:v", "libx264", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p", str(out),
    ]
    return args


def final_args(
    segments: list[Path],
    plans: list[SegmentPlan],
    narration: Path,
    out: Path,
    s: Settings,
    *,
    subtitles_file: str | None,
    music: Path | None,
    total: float,
) -> list[str]:
    v, n = s.video, len(segments)
    args: list[str] = []
    for seg in segments:
        args += ["-i", str(seg)]
    args += ["-i", str(narration)]
    narr_idx = n
    music_idx = None
    if music:
        args += ["-stream_loop", "-1", "-i", str(music)]
        music_idx = n + 1

    parts: list[str] = []
    transition = XFADE.get(v.transition)
    if n == 1:
        parts.append("[0:v]null[vcat]")
    elif not transition or v.transition_s <= 0:
        parts.append("".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")
    else:
        prev, offset = "[0:v]", 0.0
        for k in range(1, n):
            offset += plans[k - 1].target
            label = "[vcat]" if k == n - 1 else f"[x{k}]"
            parts.append(f"{prev}[{k}:v]xfade=transition={transition}:duration={v.transition_s}:offset={offset:.3f}{label}")
            prev = label
    if subtitles_file:
        parts.append(f"[vcat]subtitles={subtitles_file}[vout]")
    else:
        parts.append("[vcat]null[vout]")

    lufs = s.narration.target_lufs
    narr = f"[{narr_idx}:a]aresample=48000,loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000,apad"
    if music_idx is not None:
        m = s.music
        parts.append(f"{narr},asplit=2[narr][sc]")
        fade_start = max(0.0, total - 1.5)
        music_chain = f"[{music_idx}:a]aresample=48000,volume={m.volume_db}dB,afade=t=out:st={fade_start:.2f}:d=1.5[mus]"
        parts.append(music_chain)
        if m.ducking:
            parts.append("[mus][sc]sidechaincompress=threshold=0.04:ratio=6:attack=30:release=500[duck]")
            parts.append("[narr][duck]amix=inputs=2:duration=first:normalize=0[aout]")
        else:
            parts.append("[sc]anullsink")
            parts.append("[narr][mus]amix=inputs=2:duration=first:normalize=0[aout]")
    else:
        parts.append(f"{narr}[aout]")

    args += [
        "-filter_complex", ";".join(parts),
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{total:.3f}", "-r", str(v.fps),
        "-c:v", "libx264", "-preset", "medium", "-crf", str(v.crf), "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(out),
    ]
    return args


async def assemble(
    ffmpeg: FFmpeg,
    work_dir: Path,
    plans: list[SegmentPlan],
    narration: Path,
    out: Path,
    s: Settings,
    *,
    ass_file: Path | None,
    music: Path | None,
    total: float,
    on_progress: Callable[[float, str], Awaitable[None]],
    is_cancelled: Callable[[], bool],
) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    segments = []
    for i, plan in enumerate(plans):
        seg = work_dir / f"seg_{i:02}.mp4"
        await on_progress(0.05 + 0.5 * i / max(1, len(plans)), f"Preparing scene {i + 1}/{len(plans)}")
        await ffmpeg.run(segment_args(plan, seg, s), duration_hint=plan.render_length, is_cancelled=is_cancelled)
        segments.append(seg)
    subs_name = None
    if ass_file:
        # Copy next to the work files and refer to it relatively: avoids
        # Windows drive-letter escaping issues in the subtitles filter.
        shutil.copyfile(ass_file, work_dir / "captions.ass")
        subs_name = "captions.ass"
    tmp_out = work_dir / "final_render.mp4"
    args = final_args(
        [p.relative_to(work_dir) if p.is_relative_to(work_dir) else p for p in segments],
        plans,
        narration.resolve(),
        tmp_out.relative_to(work_dir),
        s,
        subtitles_file=subs_name,
        music=music.resolve() if music else None,
        total=total,
    )

    async def prog(frac: float):
        await on_progress(0.55 + 0.45 * frac, "Rendering final video")

    await ffmpeg.run(args, cwd=work_dir, duration_hint=total, on_progress=prog, is_cancelled=is_cancelled)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp_out), str(out))
