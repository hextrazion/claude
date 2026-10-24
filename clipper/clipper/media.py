from __future__ import annotations

import json
import subprocess
from typing import Tuple

import numpy as np

SAMPLE_RATE = 16000


class MediaError(RuntimeError):
    pass


def _run(cmd, **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, check=True, **kw)
    except FileNotFoundError as e:
        raise MediaError(f"{cmd[0]} not found - install ffmpeg and make sure it is on PATH") from e
    except subprocess.CalledProcessError as e:
        tail = e.stderr.decode("utf-8", "replace")[-800:] if e.stderr else ""
        raise MediaError(f"{cmd[0]} failed: {tail}") from e


def probe(path: str) -> Tuple[float, bool]:
    """Return (duration_seconds, has_audio)."""
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                "-of", "json", path]).stdout
    info = json.loads(out)
    duration = float(info.get("format", {}).get("duration") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    return duration, has_audio


def load_audio(path: str) -> np.ndarray:
    """Decode to mono float32 at 16 kHz."""
    raw = _run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
                "-f", "s16le", "-"]).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def probe_size(path: str) -> Tuple[int, int]:
    """Return (width, height) of the first video stream."""
    out = _run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                "-of", "json", path]).stdout
    st = (json.loads(out).get("streams") or [{}])[0]
    return int(st.get("width") or 0), int(st.get("height") or 0)


def load_audio_slice(path: str, start: float, end: float) -> np.ndarray:
    raw = _run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{max(0.0, end - start):.3f}", "-i", path,
                "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
