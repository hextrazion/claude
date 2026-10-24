"""Analyze sources -> ranked Plan."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

from . import media, signals
from .llm import LLMError, LocalLLM
from .models import Clip, Plan
from .transcribe import Transcriber


@dataclass
class Settings:
    count: int = 5
    lead_in: float = 3.0      # seconds before the setup starts
    lead_out: float = 2.0     # seconds after the reaction ends
    pre: float = 5.0          # setup seconds before the audio peak
    post: float = 4.0         # reaction seconds after the peak
    per_source_candidates: int = 0   # 0 -> 3 * count
    max_clip: float = 25.0           # longest clip we will cut
    whole_clip_max: float = 90.0     # sources this short are already clips (e.g. Twitch clips): use them whole
    weights: Dict[str, float] = field(default_factory=lambda: {
        "audio": 0.30, "laughter": 0.15, "chat": 0.25, "ai": 0.30, "views": 0.35})


def _combine(sig: Dict[str, float], weights: Dict[str, float]) -> float:
    """Weighted mean over the signals that exist, so missing chat/AI doesn't drag a clip down."""
    used = {k: v for k, v in sig.items() if k in weights}
    total = sum(weights[k] for k in used)
    return sum(weights[k] * v for k, v in used.items()) / total if total else 0.0


def _overlaps(a: Clip, b: Clip) -> bool:
    if a.source != b.source:
        return False
    inter = min(a.end, b.end) - max(a.start, b.start)
    return inter > 0.3 * min(a.duration, b.duration)


def _stamp(t: float) -> str:
    t = int(t)
    return f"{t // 3600:d}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:d}:{t % 60:02d}"


def analyze(sources: List[dict], cfg: Optional[Settings] = None, llm: Optional[LocalLLM] = None,
            transcriber: Optional[Transcriber] = None, log: Callable[[str], None] = print) -> Plan:
    """`sources`: dicts with `path` and optional `url`, `credit`, `chat` (path to a chat log)."""
    cfg = cfg or Settings()
    per_source = cfg.per_source_candidates or cfg.count * 3
    if llm and not transcriber:
        log("note: a local model is set but no transcriber is available, so AI scoring is skipped "
            "(pip install faster-whisper)")
        llm = None

    pool: List[Clip] = []
    source_info: List[dict] = []
    view_counts: Dict[int, int] = {}   # id(clip) -> views, for pre-made clips
    for src in sources:
        path = src["path"]
        duration, has_audio = media.probe(path)
        source_info.append({**{k: v for k, v in src.items() if k != "chat"}, "duration": duration})
        if not has_audio or duration < 5:
            log(f"skip {path}: no usable audio")
            continue
        log(f"analyzing {path} ({_stamp(duration)})")
        audio = media.load_audio(path)
        db = signals.loudness_db(audio, media.SAMPLE_RATE)
        chat_z = None
        if src.get("chat"):
            times = signals.load_chat_times(src["chat"])
            chat_z = signals.chat_z_series(times, duration)
            log(f"  chat: {len(times)} messages")
        cands: List[Clip] = []
        if duration <= cfg.whole_clip_max and len(db) >= 2:
            # already a clip: use it whole (or its loudest stretch); loudness range replaces the z-score
            import numpy as np
            peak = int(np.argmax(db))
            sig = {"audio": signals.unit(float(db[peak] - np.median(db)), 4.0, 20.0),
                   "laughter": signals.sustain_score(db, peak, float(np.median(db)),
                                                     max(float(np.median(np.abs(db - np.median(db))) * 1.4826),
                                                         signals.MIN_SPREAD_DB))}
            if duration <= cfg.max_clip:
                start, end = 0.0, duration
            else:
                start = min(max(0.0, peak * signals.HOP - cfg.max_clip * 0.6), duration - cfg.max_clip)
                end = start + cfg.max_clip
            c = Clip(source=path, start=start, end=end, score=_combine(sig, cfg.weights), signals=sig,
                     title=src.get("title", ""), credit=src.get("credit", ""),
                     permission=src.get("permission", "unknown"))
            cands.append(c)
            views = int(src.get("views") or 0)
            if views:
                view_counts[id(c)] = views
        else:
            moments = signals.audio_moments(db, chat_z)
            log(f"  {len(moments)} loud moments found")
            for m in moments:
                sig = {"audio": m.audio, "laughter": m.laughter}
                if m.chat is not None:
                    sig["chat"] = m.chat
                start = max(0.0, m.t - cfg.pre - cfg.lead_in)
                end = min(duration, m.t + cfg.post + cfg.lead_out, start + cfg.max_clip)
                cands.append(Clip(source=path, start=start, end=end, score=_combine(sig, cfg.weights),
                                  signals=sig, title=src.get("title", ""), credit=src.get("credit", ""),
                                  permission=src.get("permission", "unknown")))
            cands.sort(key=lambda c: -c.score)
            cands = cands[:per_source]

        if llm and transcriber:
            for n, c in enumerate(cands, 1):
                a, b = int(c.start * media.SAMPLE_RATE), int(c.end * media.SAMPLE_RATE)
                c.transcript = transcriber.transcribe(audio[a:b])
                if not c.transcript:
                    continue
                try:
                    j = llm.judge(c.transcript, context=f"clip from {src.get('credit') or 'a stream'}")
                except LLMError as e:
                    log(f"  local model unavailable, continuing without AI scoring: {e}")
                    llm = None
                    break
                c.signals["ai"] = j.score
                c.reason, c.title = j.reason, c.title or j.title
                c.score = _combine(c.signals, cfg.weights)
                log(f"  [{n}/{len(cands)}] {_stamp(c.start)} ai={j.score:.0f} {j.title}")
        pool.extend(cands)

    if len(view_counts) >= 2:   # rank pre-made clips against each other by view count (0-100 percentile)
        ranked = sorted(view_counts.values())
        by_id = {id(c): c for c in pool}
        for cid, v in view_counts.items():
            c = by_id.get(cid)
            if c is not None:
                c.signals["views"] = 100.0 * ranked.index(v) / (len(ranked) - 1)
                c.score = _combine(c.signals, cfg.weights)

    pool.sort(key=lambda c: -c.score)
    picked: List[Clip] = []
    for c in pool:
        if len(picked) >= cfg.count:
            break
        if not any(_overlaps(c, p) for p in picked):
            picked.append(c)
    for c in picked:
        if not c.title:
            c.title = f"Moment at {_stamp(c.start)}"
        if not c.reason:
            c.reason = ", ".join(f"{k} {v:.0f}" for k, v in c.signals.items())
    picked.sort(key=lambda c: c.score)  # countdown: worst first, best last (#1)

    n = len(picked)
    best = picked[-1].title if picked else ""
    return Plan(clips=picked, title=f"Top {n} Funniest Moments",
                video_titles=[f"Top {n} FUNNIEST Moments ({best})" if best else f"Top {n} Funniest Moments",
                              f"Top {n} Moments You Can't Unsee"],
                sources=source_info, settings=asdict(cfg))


def add_captions(plan: Plan, transcriber: Transcriber, log: Callable[[str], None] = print) -> None:
    """Transcribe the chosen clips only and store word-grouped captions (source time) on each clip."""
    from .captions import group_words
    for n, c in enumerate(plan.clips, 1):
        words = transcriber.words(media.load_audio_slice(c.source, c.start, c.end))
        c.captions = [{"start": c.start + w["start"], "end": c.start + w["end"], "text": w["text"]}
                      for w in group_words(words)]
        log(f"  captions {n}/{len(plan.clips)}: {len(c.captions)} lines")
