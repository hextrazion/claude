"""A JobSpec is what the chat assistant produces and the job runner executes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List

PLATFORMS = ("auto", "youtube", "twitch")
STYLES = ("countdown", "compilation")
ASPECTS = ("16:9", "9:16", "1:1")
PERIODS = ("week", "month", "year", "all")


@dataclass
class JobSpec:
    query: str = ""                  # streamer / topic, e.g. "xQc"
    urls: List[str] = field(default_factory=list)   # explicit sources (links or files) instead of searching
    platform: str = "auto"           # auto = Twitch if API keys exist, else YouTube
    period: str = "month"            # how far back to look (Twitch clips)
    count: int = 5
    style: str = "countdown"         # countdown (#5..#1 badges) | compilation (plain cuts)
    aspect: str = "16:9"             # 16:9 YouTube | 9:16 Shorts/TikTok/Reels | 1:1
    captions: bool = False
    overlay: bool = True             # title + credit lines (+ countdown badge)
    intro: bool = True
    max_clip_seconds: int = 25
    title: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _pick(v, allowed, default):
    v = str(v).strip().lower() if v is not None else ""
    return v if v in allowed else default


def _bool(v, default):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "on")
    return default if v is None else bool(v)


def _int(v, default, lo, hi):
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError):
        return default


def normalize(d: dict, base: "JobSpec | None" = None) -> JobSpec:
    """Coerce a loosely-typed dict (from an LLM or a form) into a valid JobSpec. Unknown keys are ignored."""
    b = base or JobSpec()
    urls = d.get("urls", b.urls)
    if isinstance(urls, str):
        urls = [urls]
    return JobSpec(
        query=str(d.get("query", b.query) or "").strip()[:80],
        urls=[str(u).strip() for u in (urls or []) if str(u).strip()][:20],
        platform=_pick(d.get("platform", b.platform), PLATFORMS, b.platform),
        period=_pick(d.get("period", b.period), PERIODS, b.period),
        count=_int(d.get("count", b.count), b.count, 1, 20),
        style=_pick(d.get("style", b.style), STYLES, b.style),
        aspect=_pick(str(d.get("aspect", b.aspect)).replace("x", ":"), ASPECTS, b.aspect),
        captions=_bool(d.get("captions"), b.captions),
        overlay=_bool(d.get("overlay"), b.overlay),
        intro=_bool(d.get("intro"), b.intro),
        max_clip_seconds=_int(d.get("max_clip_seconds", b.max_clip_seconds), b.max_clip_seconds, 8, 60),
        title=str(d.get("title", b.title) or "").strip()[:100],
    )


def is_actionable(s: JobSpec) -> bool:
    return bool(s.query or s.urls)


def summary(s: JobSpec) -> str:
    src = ", ".join(s.urls[:3]) + (" ..." if len(s.urls) > 3 else "") if s.urls else f'"{s.query}" ({s.platform}, {s.period})'
    kind = f"Top {s.count} countdown" if s.style == "countdown" else f"{s.count}-clip compilation"
    fmt = {"16:9": "16:9 widescreen", "9:16": "9:16 vertical", "1:1": "1:1 square"}[s.aspect]
    extras = [x for x, on in (("captions", s.captions), ("overlays", s.overlay), ("intro card", s.intro)) if on]
    return f"{kind} from {src} - {fmt}, up to {s.max_clip_seconds}s per clip" + (f", with {', '.join(extras)}" if extras else "")
