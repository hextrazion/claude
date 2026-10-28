"""Automated technical quality checks for a finished export.

Technical validity is not the same as a good video; the report says so and the
project always waits for a human review afterwards.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..settings import Settings
from .ffmpeg import FFmpeg, media_info

_BLACK = re.compile(r"black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)")
_MAXVOL = re.compile(r"max_volume:\s*(-?[\d.]+|-inf) dB")
_MEANVOL = re.compile(r"mean_volume:\s*(-?[\d.]+|-inf) dB")


def _check(checks: list, cid: str, label: str, status: str, detail: str = "") -> None:
    checks.append({"id": cid, "label": label, "status": status, "detail": detail})


async def run_qc(
    ffmpeg: FFmpeg,
    path: Path,
    s: Settings,
    *,
    expect_audio: bool,
    captions_expected: bool,
    captions_present: bool,
    narration_duration: float | None,
    scene_flags: list[str],
    draft_scenes: int,
    missing_scenes: int,
) -> dict:
    checks: list[dict] = []
    if not path.is_file() or path.stat().st_size == 0:
        _check(checks, "exists", "Output file exists", "fail", "The export file is missing or empty.")
        return _summary(checks)
    _check(checks, "exists", "Output file exists", "pass", f"{path.stat().st_size / 1e6:.1f} MB")

    try:
        info = media_info(await ffmpeg.probe(path))
    except Exception as exc:
        _check(checks, "probe", "File can be opened", "fail", str(exc))
        return _summary(checks)
    _check(checks, "probe", "File can be opened", "pass", f"{info.video_codec}/{info.audio_codec or 'no audio'}")

    v = s.video
    if (info.width, info.height) == (v.width, v.height):
        _check(checks, "resolution", "Resolution", "pass", f"{info.width}×{info.height}")
    else:
        _check(checks, "resolution", "Resolution", "fail", f"Expected {v.width}×{v.height}, got {info.width}×{info.height}")

    if expect_audio:
        _check(checks, "audio", "Narration audio present", "pass" if info.has_audio else "fail")

    if narration_duration:
        diff = info.duration - narration_duration
        status = "pass" if -0.25 <= diff <= v.tail_padding_s + 0.5 else "warn"
        _check(checks, "sync", "Video covers the narration", status,
               f"Video {info.duration:.2f}s, narration {narration_duration:.2f}s")

    if v.min_duration_s <= info.duration <= v.max_duration_s:
        _check(checks, "duration", "Duration within limits", "pass", f"{info.duration:.1f}s")
    else:
        _check(checks, "duration", "Duration within limits", "warn",
               f"{info.duration:.1f}s is outside {v.min_duration_s}–{v.max_duration_s}s")

    if captions_expected:
        _check(checks, "captions", "Captions", "pass" if captions_present else "fail",
               "" if captions_present else "Captions were enabled but no caption file was produced.")

    # One decoding pass: catches corruption, long black sections and audio clipping.
    try:
        stderr = await ffmpeg.run(
            ["-i", str(path), "-vf", "blackdetect=d=0.6:pix_th=0.08", "-af", "volumedetect", "-f", "null", "-"],
            duration_hint=info.duration,
        )
    except Exception as exc:
        _check(checks, "decode", "Decodes without errors", "fail", getattr(exc, "detail", None) or str(exc))
        return _summary(checks)
    decode_errors = [ln for ln in stderr.splitlines() if "error while decoding" in ln.lower() or "corrupt" in ln.lower()]
    _check(checks, "decode", "Decodes without errors", "warn" if decode_errors else "pass",
           "; ".join(decode_errors[:3]))
    blacks = [(float(a), float(b), float(c)) for a, b, c in _BLACK.findall(stderr)]
    if blacks:
        _check(checks, "black", "No long black sections", "warn",
               ", ".join(f"{a:.1f}–{b:.1f}s" for a, b, _ in blacks[:5]))
    else:
        _check(checks, "black", "No long black sections", "pass")
    if info.has_audio:
        mx = _MAXVOL.search(stderr)
        mean = _MEANVOL.search(stderr)
        if mx and mx.group(1) != "-inf" and float(mx.group(1)) >= -0.1:
            _check(checks, "clipping", "Audio not clipping", "warn", f"Peak {mx.group(1)} dB")
        else:
            _check(checks, "clipping", "Audio not clipping", "pass", f"Peak {mx.group(1) if mx else '?'} dB")
        if mean and (mean.group(1) == "-inf" or float(mean.group(1)) < -35):
            _check(checks, "loudness", "Audio loud enough", "warn", f"Mean {mean.group(1)} dB")

    if missing_scenes:
        _check(checks, "scenes", "All scenes have footage", "fail", f"{missing_scenes} scene(s) missing footage")
    else:
        _check(checks, "scenes", "All scenes have footage", "pass")
    if draft_scenes:
        _check(checks, "draft", "Uses AI footage", "warn",
               f"{draft_scenes} scene(s) use draft placeholder cards, not AI-generated video.")
    for f in scene_flags:
        _check(checks, "timing", "Scene timing", "warn", f)
    report = _summary(checks)
    report["media"] = info.to_dict()
    return report


def _summary(checks: list[dict]) -> dict:
    failed = [c for c in checks if c["status"] == "fail"]
    warned = [c for c in checks if c["status"] == "warn"]
    return {
        "checks": checks,
        "technical_ok": not failed,
        "failures": len(failed),
        "warnings": len(warned),
        "note": "Automated checks cover technical validity only. Watch the video to judge quality.",
    }
