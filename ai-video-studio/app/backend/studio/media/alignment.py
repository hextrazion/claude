"""Word timing for narration.

Two strategies:

* ``whisper``: if the optional ``faster-whisper`` package is installed, the
  narration is transcribed with word timestamps and matched back to the script.
* ``heuristic``: words get time proportional to their length plus punctuation
  pauses, then sentence boundaries are snapped to real silences found by
  FFmpeg's ``silencedetect``. Accurate to a few hundred ms for clean TTS audio.
"""

from __future__ import annotations

import bisect
import difflib
import logging
import re
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\S+")
_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*([\d.]+)")


@dataclass
class Word:
    text: str
    start: float
    end: float

    def to_dict(self) -> dict:
        return asdict(self)


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def norm_token(token: str) -> str:
    return re.sub(r"[^a-z0-9']", "", token.lower())


def parse_silences(stderr: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    start = None
    for line in stderr.splitlines():
        m = _SIL_START.search(line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = _SIL_END.search(line)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    return out


def _weight(token: str) -> float:
    letters = len(re.sub(r"[^A-Za-z0-9]", "", token))
    w = 0.6 + 0.12 * letters
    if any(ch.isdigit() for ch in token):
        w += 0.25 * sum(ch.isdigit() for ch in token)  # numbers are spoken long
    return w


def _pause_after(token: str) -> float:
    if token.endswith(("...", "…")):
        return 1.6
    if token[-1:] in ".!?":
        return 1.4
    if token[-1:] in ",;:—–-":
        return 0.7
    return 0.0


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0] + (x - xs[0])
    if x >= xs[-1]:
        return ys[-1] + (x - xs[-1])
    i = bisect.bisect_right(xs, x) - 1
    x0, x1, y0, y1 = xs[i], xs[i + 1], ys[i], ys[i + 1]
    if x1 == x0:
        return y0
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


def heuristic_timings(tokens: list[str], duration: float, silences: list[tuple[float, float]]) -> list[Word]:
    if not tokens:
        return []
    speech_start, speech_end = 0.0, duration
    inner = []
    for s, e in silences:
        if s <= 0.05:
            speech_start = max(speech_start, e)
        elif e >= duration - 0.05:
            speech_end = min(speech_end, s)
        else:
            inner.append((s, e))
    if speech_end - speech_start < 0.5:
        speech_start, speech_end = 0.0, duration

    weights = [_weight(t) for t in tokens]
    pauses = [_pause_after(t) for t in tokens]
    pauses[-1] = 0.0
    total = sum(weights) + sum(pauses)
    scale = (speech_end - speech_start) / total
    est: list[tuple[float, float]] = []
    t = speech_start
    for w, p in zip(weights, pauses):
        est.append((t, t + w * scale))
        t += (w + p) * scale

    # Anchor punctuation pauses to detected silences (monotonic matching).
    xs, ys = [speech_start], [speech_start]
    used = -1
    for i, p in enumerate(pauses):
        if p <= 0:
            continue
        gap_start, gap_end = est[i][1], est[i + 1][0]
        mid = (gap_start + gap_end) / 2
        best, best_d = None, 1.2
        for j in range(used + 1, len(inner)):
            s, e = inner[j]
            d = abs((s + e) / 2 - mid)
            if d < best_d:
                best, best_d = j, d
            if (s + e) / 2 > mid + 1.2:
                break
        if best is not None:
            s, e = inner[best]
            if s > ys[-1] and gap_start > xs[-1]:
                xs += [gap_start, gap_end]
                ys += [s, e]
                used = best
    xs.append(speech_end)
    ys.append(speech_end)
    words = []
    for tok, (s, e) in zip(tokens, est):
        ms, me = _interp(s, xs, ys), _interp(e, xs, ys)
        words.append(Word(tok, round(max(0.0, ms), 3), round(min(duration, max(me, ms + 0.05)), 3)))
    return words


def align_to_transcript(tokens: list[str], asr: list[tuple[str, float, float]], duration: float) -> list[Word]:
    """Map script tokens onto ASR words; unmatched tokens are interpolated."""
    script_n = [norm_token(t) for t in tokens]
    asr_n = [norm_token(w) for w, _, _ in asr]
    times: list[tuple[float, float] | None] = [None] * len(tokens)
    sm = difflib.SequenceMatcher(a=script_n, b=asr_n, autojunk=False)
    for block in sm.get_matching_blocks():
        for k in range(block.size):
            _, s, e = asr[block.b + k]
            times[block.a + k] = (s, e)
    # Fill gaps by distributing time between known neighbours.
    i = 0
    n = len(tokens)
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else 0.0
        right = times[j][0] if j < n else duration
        span = max(0.05 * (j - i), right - left)
        step = span / (j - i)
        for k in range(i, j):
            times[k] = (left + (k - i) * step, left + (k - i + 1) * step)
        i = j
    return [Word(t, round(s, 3), round(e, 3)) for t, (s, e) in zip(tokens, times)]  # type: ignore[misc]


def whisper_words(audio_path: str) -> list[tuple[str, float, float]] | None:
    """Transcribe with faster-whisper if installed. Returns None if unavailable."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return None
    try:
        model = WhisperModel("base.en", device="auto", compute_type="int8")
        segments, _ = model.transcribe(audio_path, word_timestamps=True, vad_filter=False)
        out = []
        for seg in segments:
            for w in seg.words or []:
                out.append((w.word.strip(), float(w.start), float(w.end)))
        return out
    except Exception as exc:  # GPU busy, model download blocked, etc.
        log.warning("faster-whisper alignment failed, falling back to heuristic: %r", exc)
        return None


def scene_spans(scene_texts: list[str], words: list[Word], audio_duration: float, tail: float) -> list[tuple[float, float]]:
    """Timeline span for each scene, cutting in the pause between scenes."""
    counts = [len(tokenize(t)) for t in scene_texts]
    if sum(counts) != len(words):
        # Narration text diverged from scene texts; distribute proportionally.
        total = max(1, sum(counts))
        acc, spans = 0.0, []
        end_total = audio_duration + tail
        for c in counts:
            s = acc
            acc += end_total * c / total
            spans.append((round(s, 3), round(acc, 3)))
        return spans
    spans = []
    idx = 0
    boundaries = [0.0]
    for c in counts[:-1]:
        idx += c
        if idx <= 0 or idx >= len(words):
            boundaries.append(boundaries[-1])
            continue
        prev_end, next_start = words[idx - 1].end, words[idx].start
        boundaries.append(round((prev_end + next_start) / 2, 3))
    boundaries.append(round(audio_duration + tail, 3))
    for i in range(len(counts)):
        spans.append((boundaries[i], max(boundaries[i] + 0.2, boundaries[i + 1])))
    return spans
