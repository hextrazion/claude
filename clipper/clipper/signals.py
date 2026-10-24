"""Cheap signals that point at funny moments: loudness spikes, sustained noise (laughter), chat bursts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

HOP = 0.5  # seconds per loudness frame
MIN_SPREAD_DB = 1.5  # loudness varying less than this is noise, not a signal


def loudness_db(samples: np.ndarray, sr: int, hop: float = HOP) -> np.ndarray:
    """RMS loudness in dB for each `hop`-second frame."""
    n = max(1, int(sr * hop))
    frames = len(samples) // n
    if frames == 0:
        return np.zeros(0, dtype=np.float32)
    x = samples[: frames * n].reshape(frames, n)
    rms = np.sqrt(np.mean(x * x, axis=1) + 1e-12)
    return (20 * np.log10(rms)).astype(np.float32)


def robust_z(x: np.ndarray, floor: float = 1e-3) -> np.ndarray:
    """Median/MAD z-score. `floor` stops near-constant series (e.g. quiet chat) from exploding."""
    if len(x) == 0:
        return x
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826
    return (x - med) / max(mad, floor)


def smooth(x: np.ndarray, width: int) -> np.ndarray:
    if width <= 1 or len(x) == 0:
        return x
    k = np.ones(width) / width
    pad = width // 2
    padded = np.pad(x, (pad, width - 1 - pad), mode="edge")   # zero padding would fake peaks at the edges
    return np.convolve(padded, k, mode="valid")


def find_peaks(z: np.ndarray, min_z: float, min_gap: int) -> List[int]:
    """Greedy peak picking: highest first, suppress neighbours within min_gap frames."""
    order = np.argsort(-z)
    taken: List[int] = []
    for i in order:
        if z[i] < min_z:
            break
        if all(abs(int(i) - t) >= min_gap for t in taken):
            taken.append(int(i))
    return sorted(taken)


def unit(z: float, lo: float, hi: float) -> float:
    """Map z from [lo, hi] onto 0..100."""
    return float(np.clip((z - lo) / (hi - lo), 0, 1) * 100)


@dataclass
class Moment:
    t: float             # peak time in seconds
    audio: float         # 0-100 loudness-spike strength
    laughter: float      # 0-100 sustained loudness after the peak
    chat: Optional[float]  # 0-100 chat burst strength, None if no chat data


def sustain_score(db: np.ndarray, idx: int, baseline: float, spread: float, seconds: float = 6.0) -> float:
    """Laughter/commotion proxy: how long loudness stays elevated after the peak."""
    n = int(seconds / HOP)
    seg = db[idx + 1: idx + 1 + n]
    if len(seg) == 0:
        return 0.0
    frac = float(np.mean(seg > baseline + 0.75 * spread))
    return frac * 100


def audio_moments(db: np.ndarray, chat_z: Optional[np.ndarray] = None, max_moments: int = 60,
                  min_gap_s: float = 15.0, min_z: float = 1.5) -> List[Moment]:
    if len(db) < 4:
        return []
    z = robust_z(smooth(db, 3), floor=MIN_SPREAD_DB)
    baseline = float(np.median(db))
    spread = max(float(np.median(np.abs(db - baseline)) * 1.4826), MIN_SPREAD_DB)
    peaks = find_peaks(z, min_z, max(1, int(min_gap_s / HOP)))
    peaks.sort(key=lambda i: -z[i])
    out: List[Moment] = []
    for i in peaks[:max_moments]:
        chat = None
        if chat_z is not None and len(chat_z):
            lo, hi = max(0, i - 4), min(len(chat_z), i + 12)   # reaction lags the event
            chat = unit(float(np.max(chat_z[lo:hi])), 1.0, 6.0)
        out.append(Moment(t=i * HOP, audio=unit(float(z[i]), 1.5, 7.0),
                          laughter=sustain_score(db, i, baseline, spread), chat=chat))
    return out


def load_chat_times(path: str) -> List[float]:
    """Accept: JSON list of numbers/objects, {"comments": [...]} (Twitch downloaders), or one number per line."""
    text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [float(s) for s in text.split() if _isnum(s)]
    if isinstance(data, dict):
        data = data.get("comments") or data.get("messages") or []
    times: List[float] = []
    for item in data:
        if isinstance(item, (int, float)):
            times.append(float(item))
        elif isinstance(item, dict):
            for k in ("t", "time", "time_in_seconds", "content_offset_seconds", "offset"):
                if k in item:
                    times.append(float(item[k]))
                    break
    return times


def _isnum(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def chat_z_series(times: List[float], duration: float) -> np.ndarray:
    """Messages per 5 s, on the same HOP grid as loudness, as a robust z-score."""
    frames = max(1, int(duration / HOP))
    counts = np.zeros(frames, dtype=np.float32)
    for t in times:
        i = int(t / HOP)
        if 0 <= i < frames:
            counts[i] += 1
    rate = smooth(counts, int(5 / HOP)) * (5 / HOP)
    return robust_z(rate, floor=2.0)
