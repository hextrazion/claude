"""Run a JobSpec end to end: find sources -> download -> analyze -> (captions) -> render."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import discover, ingest, pipeline, render
from .llm import LocalLLM
from .media import MediaError
from .models import Plan
from .spec import JobSpec, summary
from .transcribe import Transcriber


@dataclass
class Context:
    workdir: str = "."
    llm: Optional[LocalLLM] = None
    whisper: str = "small"
    env: Mapping = field(default_factory=lambda: os.environ)
    # swappable for tests / alternative backends
    find: Callable = discover.find_sources
    fetch: Callable = ingest.fetch
    make_transcriber: Callable = Transcriber
    transcriber_available: Callable = Transcriber.available


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "video"


def run_job(spec: JobSpec, ctx: Context, plan_path: str, log: Callable[[str], None]) -> dict:
    """Returns {"plan": path, "output": mp4 path}. Raises MediaError with a readable message on failure."""
    work = Path(ctx.workdir)
    (work / "downloads").mkdir(parents=True, exist_ok=True)
    log(f"Job: {summary(spec)}")

    cands, notes = ctx.find(spec, env=ctx.env)
    for n in notes:
        log(n)
    if not cands:
        raise MediaError("I couldn't find any source videos for that. Try a different name, a longer time period, "
                         "or paste links.")
    log(f"Found {len(cands)} source{'s' if len(cands) != 1 else ''}.")

    sources = []
    for i, c in enumerate(cands, 1):
        label = c.title or c.url
        try:
            if ingest.is_url(c.url):
                log(f"Downloading {i}/{len(cands)}: {label[:70]}")
                path, info = ctx.fetch(c.url, str(work / "downloads"))
                credit = c.credit or info.get("credit", "")
            elif Path(c.url).exists():
                path, credit = c.url, c.credit
            else:
                log(f"Skipping {c.url}: not a link or an existing file")
                continue
        except MediaError as e:
            log(f"Skipping {label[:50]}: {e}")
            continue
        sources.append({"path": path, "url": c.url if ingest.is_url(c.url) else "", "credit": credit,
                        "title": c.title if c.platform == "twitch" else "", "views": c.views, "permission": "unknown"})
    if not sources:
        raise MediaError("None of the sources could be downloaded (see the messages above).")

    have_whisper = ctx.transcriber_available()
    llm = ctx.llm if have_whisper else None
    transcriber = ctx.make_transcriber(ctx.whisper) if (have_whisper and (llm or spec.captions)) else None
    if ctx.llm and not have_whisper:
        log("Whisper isn't installed, so the local model can't hear the clips (pip install faster-whisper). "
            "Ranking by audio and view counts only.")
    cfg = pipeline.Settings(count=spec.count, max_clip=float(spec.max_clip_seconds))
    plan = pipeline.analyze(sources, cfg, llm, transcriber if llm else None, log=log)
    if not plan.clips:
        raise MediaError("I analysed the sources but didn't find any standout moments in them.")

    if spec.captions:
        if transcriber:
            log("Writing captions...")
            pipeline.add_captions(plan, transcriber, log)
        else:
            log("Captions need faster-whisper (pip install faster-whisper); skipping captions.")

    n, who = len(plan.clips), spec.query
    base = spec.title or (f"Top {n} Funniest {who} Moments" if spec.style == "countdown" and who else
                          f"Funniest {who} Moments" if who else plan.title)
    plan.title = base
    plan.video_titles = [base, f"{base} (you won't believe #1)" if spec.style == "countdown" else f"{base} - Compilation"]
    plan.settings.update(aspect=spec.aspect, style=spec.style, captions=spec.captions and bool(
        any(c.captions for c in plan.clips)), overlay=spec.overlay, intro=spec.intro, query=spec.query)
    plan.save(plan_path)
    log(f"Picked {n} clip{'s' if n != 1 else ''}. Rendering {spec.aspect} video...")

    out = str(work / f"{_slug(spec.query or 'video')}_{'top' + str(n) if spec.style == 'countdown' else 'compilation'}.mp4")
    render.render(plan, out, on_progress=lambda i, t, m: log(f"Rendering {i}/{t}: {m}"))
    render.thumbnail(plan, str(Path(out).with_suffix(".jpg")))
    log("Done.")
    return {"plan": plan_path, "output": out}
