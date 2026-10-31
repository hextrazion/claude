"""Job handlers: one coroutine per job kind. Each reads its inputs from the
database, writes its outputs to the project folder and database, and returns
a small JSON-able result. Handlers never touch other stages' outputs except
to mark them stale."""

from __future__ import annotations

import logging
import random
import re
import uuid
from pathlib import Path

from ..db import utcnow
from ..errors import ProviderError, ValidationFailed
from ..integrations.video.base import GenerationRequest
from ..jobs.context import JobContext
from ..media import alignment, assembly, captions, qc
from ..media.ffmpeg import media_info
from ..safety import AUDIO_EXTENSIONS, ensure_within
from . import prompts
from .projects import stamp

log = logging.getLogger(__name__)

# Model-specific advice for the scene planner. Keyed by substrings of the workflow name.
MODEL_NOTES = {
    "minimax": "MiniMax H3 (open-weights video model; its generated audio is discarded and replaced by the narration). Follows detailed, chronological shot descriptions with explicit camera direction; open weights output up to 768p, so favour bold, simple compositions over fine detail; avoid readable text.",
    "wan": "Wan 2.2 (open-source diffusion video model). Strong at stylised 3D, natural motion and camera moves; weak at readable text and precise diagrams; one subject and one action per clip works best.",
    "ltx": "LTX-2 family (open-weights video model). Good cinematic motion and coherent short shots; keep prompts descriptive and chronological; avoid readable text.",
    "draft": "Draft placeholder cards (no AI video): prompts are shown as text labels only.",
}


def model_notes_for(workflow: str, provider: str, wf: dict | None = None) -> str:
    """Planner advice for the model behind a workflow, matched on its name, label and node types."""
    if provider == "draft":
        return MODEL_NOTES["draft"]
    haystack = " ".join([workflow, (wf or {}).get("label", ""),
                         *(str(n.get("class_type", "")) for n in ((wf or {}).get("workflow") or {}).values())]).lower()
    for key, note in MODEL_NOTES.items():
        if key in haystack:
            return note
    return "Open-source text-to-video diffusion model; one clear subject and action per clip; avoid readable text."


def script_text(script: dict) -> str:
    return " ".join(s["text"].strip() for s in script.get("segments", []) if s.get("text", "").strip())


def _tokens(text: str) -> list[str]:
    return [alignment.norm_token(t) for t in alignment.tokenize(text) if alignment.norm_token(t)]


def repair_scene_narration(full_text: str, scenes: list[dict]) -> tuple[list[dict], bool]:
    """Make the scenes' narration cover the script exactly, in order.

    If the model paraphrased or skipped words, the script's own words are
    re-split across the scenes in proportion to what the model assigned,
    breaking at sentence or clause boundaries where possible.
    """
    if _tokens(" ".join(s.get("narration", "") for s in scenes)) == _tokens(full_text):
        return scenes, False
    words = alignment.tokenize(full_text)
    weights = [max(1, len(alignment.tokenize(s.get("narration", "")))) for s in scenes]
    total_w = sum(weights)
    n = len(words)
    cuts, acc = [], 0
    for w in weights[:-1]:
        acc += w
        target = round(n * acc / total_w)
        best = target
        for delta in range(0, 6):
            for cand in (target + delta, target - delta):
                if 0 < cand < n and words[cand - 1][-1:] in ".!?,;:":
                    best = cand
                    break
            else:
                continue
            break
        cuts.append(best)
    bounds = [0] + sorted(set(min(max(c, 1), n - 1) for c in cuts)) + [n]
    fixed = []
    for i, s in enumerate(scenes[: len(bounds) - 1]):
        fixed.append({**s, "narration": " ".join(words[bounds[i]: bounds[i + 1]])})
    return fixed, True


# ---------------------------------------------------------------------------
async def run_ideas(ctx: JobContext) -> dict:
    s = ctx.s
    st = s.settings.get()
    s.usage.check_limit("ideas")
    p = ctx.payload
    count = max(1, min(int(p.get("count") or 8), 20))
    await ctx.progress(0.1, "Asking the text model for ideas")
    data = await s.groq.chat_json(
        prompts.ideas_messages(
            niche=p.get("niche") or st.general.default_niche,
            exclusions=p.get("exclusions", ""),
            count=count,
            duration_s=int(p.get("duration_s") or st.video.duration_s),
            tone=p.get("tone") or st.general.tone,
            avoid=s.projects.avoid_titles(),
            notes=p.get("notes", ""),
        ),
        model=st.text.model_quality,
        operation="ideas",
        temperature=min(1.2, st.text.temperature + 0.2),
        max_tokens=6000,
    )
    ideas = data.get("ideas")
    if not isinstance(ideas, list) or not ideas:
        raise ProviderError("The text model returned no ideas.", kind="transient", provider="groq")
    batch = uuid.uuid4().hex[:8]
    ids, dups = [], 0
    for idea in ideas[:count]:
        if not isinstance(idea, dict) or not idea.get("title"):
            continue
        iid = s.projects.create_idea(idea, source="groq", model=st.text.model_quality, batch_id=batch)
        ids.append(iid)
        if s.projects.get_idea(iid)["duplicate_of"]:
            dups += 1
    ctx.log(f"Generated {len(ids)} ideas" + (f" ({dups} look like duplicates)" if dups else ""))
    s.bus.publish("ideas", batch=batch)
    return {"created": len(ids), "ids": ids, "duplicates": dups}


async def run_research(ctx: JobContext) -> dict:
    s = ctx.s
    project = s.projects.require(ctx.project_id)
    idea = s.projects.get_idea(project["idea_id"]) or {"title": project["title"]}
    provider = s.research_provider()
    if provider is None:
        s.projects.update(project["id"], research_status="skipped",
                          research={"provider": None, "note": "No research provider configured; claims are not independently verified.",
                                    "sources": [], "facts": [], "cautions": []})
        return {"skipped": True}
    s.projects.update(project["id"], research_status="running")
    st = s.settings.get()
    await ctx.progress(0.1, "Planning searches")
    q = await s.groq.chat_json(prompts.research_queries_messages(idea), model=st.text.model_fast,
                               operation="research", temperature=0.2, max_tokens=300, project_id=project["id"])
    queries = [str(x)[:120] for x in (q.get("queries") or [])][:4] or [idea["title"]]
    sources, seen = [], set()
    for i, query in enumerate(queries):
        await ctx.progress(0.2 + 0.4 * i / len(queries), f"Searching {provider.name}: {query}")
        try:
            results = await provider.search(query)
        except ProviderError as exc:
            if exc.kind in ("auth", "not_configured", "quota"):
                raise
            ctx.log(f"Search failed for '{query}': {exc.message}", "warning")
            continue
        for r in results:
            if r.url in seen:
                continue
            seen.add(r.url)
            r.id = f"S{len(sources) + 1}"
            sources.append(r.to_dict())
    facts, cautions = [], []
    if sources:
        await ctx.progress(0.7, "Extracting facts from sources")
        sheet = await s.groq.chat_json(prompts.fact_sheet_messages(idea, sources[:8]), model=st.text.model_quality,
                                       operation="research", temperature=0.1, max_tokens=2500, project_id=project["id"])
        valid = {src["id"] for src in sources}
        for f in sheet.get("facts") or []:
            ids = [i for i in (f.get("source_ids") or []) if i in valid]
            if f.get("fact") and ids:  # facts without a real source are dropped
                facts.append({"fact": str(f["fact"])[:500], "source_ids": ids})
        cautions = [str(c)[:300] for c in (sheet.get("cautions") or [])][:8]
    research = {
        "provider": provider.name, "queries": queries, "sources": sources, "facts": facts, "cautions": cautions,
        "generated_at": utcnow(),
        "note": None if sources else "Searches returned no usable sources; the script will rely on general knowledge.",
    }
    s.projects.update(project["id"], research=research, research_status="completed")
    s.projects.write_json(project, "research/research.json", research)
    ctx.log(f"Research found {len(sources)} sources and {len(facts)} sourced facts")
    return {"sources": len(sources), "facts": len(facts)}


async def run_script(ctx: JobContext) -> dict:
    s = ctx.s
    project = s.projects.require(ctx.project_id)
    eff = s.projects.effective_settings(project)
    s.usage.check_limit("script")
    idea = s.projects.get_idea(project["idea_id"]) if project.get("idea_id") else None
    idea = idea or {"title": project["title"], "central_question": "", "hook": "", "description": ""}
    duration = int(ctx.payload.get("duration_s") or eff.video.duration_s)
    target = duration * prompts.WORDS_PER_SECOND
    research = project.get("research") if project.get("research_status") == "completed" else None
    feedback = ctx.payload.get("feedback")
    data, words = None, 0
    for attempt in range(2):
        await ctx.progress(0.2 + 0.4 * attempt, "Writing script" if attempt == 0 else "Adjusting script length")
        data = await s.groq.chat_json(
            prompts.script_messages(idea, duration_s=duration, tone=eff.general.tone, research=research, feedback=feedback),
            model=eff.text.model_quality, operation="script", temperature=eff.text.temperature, max_tokens=3000,
            project_id=project["id"],
        )
        segs = [x for x in (data.get("segments") or []) if isinstance(x, dict) and str(x.get("text", "")).strip()]
        if not segs:
            raise ProviderError("The text model returned an empty script.", kind="transient", provider="groq")
        data["segments"] = [{"text": str(x["text"]).strip(), "purpose": str(x.get("purpose", "")),
                             "visual_idea": str(x.get("visual_idea", ""))} for x in segs]
        words = len(alignment.tokenize(script_text(data)))
        if 0.75 * target <= words <= 1.3 * target:
            break
        feedback = (f"Your script has {words} words but must be about {round(target)} words "
                    f"({duration}s). Rewrite it to that length, same JSON format.")
    script = {
        "title": str(data.get("title") or project["title"])[:200],
        "segments": data["segments"],
        "sources_used": [str(x) for x in (data.get("sources_used") or [])][:20],
        "uncertain_claims": [str(x) for x in (data.get("uncertain_claims") or [])][:20],
        "word_count": words,
        "est_duration_s": round(words / prompts.WORDS_PER_SECOND, 1),
        "target_duration_s": duration,
        "model": eff.text.model_quality,
        "generated_at": utcnow(),
        "edited": False,
    }
    script["full_text"] = script_text(script)
    store_script(s, project, script, status="draft")
    if not (0.75 * target <= words <= 1.3 * target):
        ctx.log(f"Script is {words} words for a {duration}s target; review its length.", "warning")
    else:
        ctx.log(f"Script written ({words} words, ~{script['est_duration_s']}s)")
    # Claim check runs automatically after every new script.
    s.orchestrator.enqueue(project["id"], "factcheck")
    return {"words": words}


def store_script(s, project: dict, script: dict, status: str) -> None:
    fields = {"script": script, "script_status": status}
    if project.get("scene_plan_status") in ("draft", "approved"):
        fields["scene_plan_status"] = "stale"
    if project.get("narration_status") == "completed":
        fields["narration_status"] = "stale"
    s.projects.update(project["id"], **fields)
    s.projects.write_json(project, "script/script.json", script)
    md = f"# {script['title']}\n\n" + "\n\n".join(seg["text"] for seg in script["segments"]) + "\n"
    (s.projects.folder(project) / "script" / "script.md").write_text(md, encoding="utf-8")


async def run_factcheck(ctx: JobContext) -> dict:
    s = ctx.s
    project = s.projects.require(ctx.project_id)
    script = project.get("script")
    if not script:
        raise ValidationFailed("There is no script to check yet.")
    research = project.get("research") or {}
    sources = research.get("sources") or []
    st = s.settings.get()
    await ctx.progress(0.2, "Checking claims against sources" if sources else "Listing claims for manual review")
    data = await s.groq.chat_json(prompts.factcheck_messages(script["full_text"], sources[:8]),
                                  model=st.text.model_quality if sources else st.text.model_fast,
                                  operation="factcheck", temperature=0.1, max_tokens=2500, project_id=project["id"])
    by_id = {src["id"]: src for src in sources}
    claims = []
    for c in data.get("claims") or []:
        if not isinstance(c, dict) or not c.get("claim"):
            continue
        ids = [i for i in (c.get("source_ids") or []) if i in by_id]
        label = str(c.get("label", "")).lower()
        domains = {by_id[i]["domain"] for i in ids}
        if not sources:
            status = "speculative" if label == "creative" else "not_checked"
        elif label == "supported" and len(domains) >= 2:
            status = "verified"
        elif label in ("supported", "partially_supported") and ids:
            status = "needs_review"
        elif label == "contradicted":
            status = "contradicted"
        elif label == "creative":
            status = "speculative"
        else:
            status = "unverified"
        claims.append({
            "claim": str(c["claim"])[:400], "status": status, "model_label": label, "source_ids": ids,
            "sources": [{"title": by_id[i]["title"], "url": by_id[i]["url"]} for i in ids],
            "evidence": str(c.get("evidence") or "")[:400], "note": str(c.get("note") or "")[:300],
        })
    factcheck = {
        "claims": claims,
        "research_provider": research.get("provider"),
        "disclaimer": (
            "No research provider was used, so nothing here is independently verified." if not sources else
            "Automatic labels compare claims with retrieved text only. 'Verified' requires agreement from two "
            "different sites; everything else needs a human check."
        ),
        "generated_at": utcnow(),
    }
    s.projects.update(project["id"], factcheck=factcheck)
    s.projects.write_json(project, "research/factcheck.json", factcheck)
    flagged = sum(1 for c in claims if c["status"] in ("contradicted", "unverified", "not_checked"))
    ctx.log(f"Claim check: {len(claims)} claims, {flagged} need attention", "warning" if any(c["status"] == "contradicted" for c in claims) else "info")
    return {"claims": len(claims), "flagged": flagged}


async def run_scene_plan(ctx: JobContext) -> dict:
    s = ctx.s
    project = s.projects.require(ctx.project_id)
    script = project.get("script")
    if not script or project["script_status"] != "approved":
        raise ValidationFailed("Approve the script before planning scenes.")
    eff = s.projects.effective_settings(project)
    g = eff.generation
    adapter = s.video_adapter(g.video_provider)
    caps = adapter.capabilities(g.video_workflow)
    use_images = g.use_image_stage and bool(g.image_workflow) and g.video_provider != "draft"
    feedback = None
    scenes: list[dict] = []
    for attempt in range(2):
        await ctx.progress(0.2 + 0.4 * attempt, "Planning scenes")
        data = await s.groq.chat_json(
            prompts.scene_plan_messages(
                script, duration_s=round(script.get("est_duration_s") or eff.video.duration_s),
                max_clip_s=caps.max_clip_s,
                model_notes=model_notes_for(g.video_workflow, g.video_provider, _workflow_or_none(s, g)),
                style=g.style_preset, aspect=eff.video.aspect_ratio, use_images=use_images, feedback=feedback,
            ),
            model=eff.text.model_quality, operation="scene_plan", temperature=0.6, max_tokens=7000,
            project_id=project["id"],
        )
        scenes = [x for x in (data.get("scenes") or []) if isinstance(x, dict) and x.get("prompt")]
        if scenes:
            break
        feedback = "The plan had no usable scenes. Return the JSON with a non-empty scenes array."
    if not scenes:
        raise ProviderError("The text model returned no scenes.", kind="transient", provider="groq")
    scenes, repaired = repair_scene_narration(script["full_text"], scenes)
    cleaned = []
    for sc in scenes[:30]:
        words = len(alignment.tokenize(sc.get("narration", "")))
        cleaned.append({
            "narration": sc.get("narration", "").strip(),
            "visual_objective": str(sc.get("visual_objective", ""))[:500],
            "prompt": str(sc.get("prompt", ""))[:2000],
            "negative_prompt": str(sc.get("negative_prompt", ""))[:500],
            "camera": str(sc.get("camera", ""))[:200],
            "subject_motion": str(sc.get("subject_motion", ""))[:300],
            "environment": str(sc.get("environment", ""))[:300],
            "style": str(sc.get("style", ""))[:300],
            "duration_s": round(max(1.0, words / prompts.WORDS_PER_SECOND), 2),
            "needs_image": bool(sc.get("needs_image")) and use_images,
            "image_prompt": str(sc.get("image_prompt", ""))[:1500],
            "transition": sc.get("transition") if sc.get("transition") in ("cut", "fade", "dissolve") else "cut",
        })
    s.projects.replace_scenes(project["id"], cleaned)
    style_bible = str(data.get("style_bible", ""))[:1000]
    overrides = dict(project.get("overrides") or {})
    s.projects.update(project["id"], scene_plan_status="draft",
                      **({"narration_status": "stale"} if project["narration_status"] == "completed" else {}),
                      **({"export_status": "stale"} if project["export_status"] == "completed" else {}))
    plan = {"style_bible": style_bible, "scenes": cleaned, "model": eff.text.model_quality, "video_workflow": g.video_workflow,
            "max_clip_s": caps.max_clip_s, "narration_repaired": repaired, "generated_at": utcnow()}
    s.projects.update(project["id"], overrides={**overrides, "_style_bible": style_bible})
    s.projects.write_json(project, "scenes/scene_plan.json", plan)
    long = [i + 1 for i, c in enumerate(cleaned) if c["duration_s"] > caps.max_clip_s * 1.3]
    msg = f"Scene plan created with {len(cleaned)} scenes"
    if repaired:
        msg += " (narration re-aligned to the exact script)"
    if long:
        msg += f"; scenes {long} are longer than one clip and will be slowed or held"
    ctx.log(msg, "warning" if long else "info")
    return {"scenes": len(cleaned), "repaired": repaired}


def _workflow_or_none(s, g) -> dict | None:
    if g.video_provider == "draft":
        return None
    try:
        return s.workflows.get(g.video_workflow)
    except ValidationFailed:
        return None


def _style_bible(project: dict) -> str:
    return (project.get("overrides") or {}).get("_style_bible", "")


def _seed(eff, scene: dict) -> int:
    if eff.generation.seed_mode == "fixed":
        return eff.generation.fixed_seed + scene["idx"]
    return random.randint(1, 2**31 - 1)


def _scene_target_seconds(project: dict, scene: dict, scenes: list[dict], transition_s: float) -> float:
    narr = project.get("narration")
    if narr and project.get("narration_status") == "completed" and narr.get("words"):
        words = [alignment.Word(**w) for w in narr["words"]]
        spans = alignment.scene_spans([x["narration"] for x in scenes], words, narr["duration"], 0.6)
        if scene["idx"] < len(spans):
            a, b = spans[scene["idx"]]
            return (b - a) + transition_s
    return float(scene["duration_s"]) + transition_s


async def _generate(ctx: JobContext, kind: str) -> dict:
    s = ctx.s
    scene = s.projects.scene(ctx.job["scene_id"])
    if not scene:
        raise ValidationFailed("Scene no longer exists.")
    project = s.projects.require(scene["project_id"])
    eff = s.projects.effective_settings(project)
    g = eff.generation
    provider = ctx.payload.get("provider") or g.video_provider
    adapter = s.video_adapter(provider)
    status_field = "clip_status" if kind == "video" else "image_status"
    s.projects.update_scene(scene["id"], **{status_field: "running"})
    s.bus.publish("scene", id=scene["id"], project_id=project["id"])

    image_path = None
    if kind == "video":
        use_i2v = bool(scene.get("image_path")) and g.use_image_stage and provider != "draft"
        workflow = g.i2v_workflow if use_i2v else g.video_workflow
        if use_i2v:
            image_path = s.projects.abs(project, scene["image_path"])
        prompt = prompts.compose_video_prompt(scene, _style_bible(project), g.style_preset)
    else:
        workflow = g.image_workflow
        if not workflow and provider != "draft":
            raise ValidationFailed("No image workflow configured (Settings → Generation).")
        prompt = (scene.get("image_prompt") or scene.get("prompt", "")) + f". Style: {g.style_preset}"
    caps = adapter.capabilities(workflow)
    scenes = s.projects.scenes(project["id"])
    seconds = _scene_target_seconds(project, scene, scenes, eff.video.transition_s)
    frames = caps.frames_for(seconds) if kind == "video" else 1
    seed = int(ctx.payload.get("seed") or _seed(eff, scene))
    negative = ", ".join(x for x in (scene.get("negative_prompt"), g.negative_prompt) if x)
    name = f"{'clip' if kind == 'video' else 'image'}_{stamp()}"
    req = GenerationRequest(
        kind=kind, workflow=workflow, prompt=prompt, negative_prompt=negative,
        width=caps.width, height=caps.height, seed=seed, out_dir=s.projects.scene_dir(project, scene),
        filename_prefix=name, num_frames=frames, fps=caps.fps, image_path=image_path,
        extra={"label": scene.get("visual_objective") or scene.get("narration", "")},
    )
    external = ctx.payload.get("resume_external_id")
    if external:
        await ctx.progress(None, "Re-attached to a generation that was already running")
    else:
        await ctx.progress(0.0, f"Submitting to {adapter.label}")
        external = await adapter.submit(req)
    ctx.set_external(external, adapter.name)
    started = utcnow()

    async def on_progress(frac, msg):
        await ctx.progress(frac, msg)

    result = await adapter.wait(external, req, on_progress, ctx.is_cancelled, g.job_timeout_s)
    out = result.files[0]
    info = media_info(await s.ffmpeg.probe(out)) if s.ffmpeg.available else None
    meta = {
        "provider": adapter.name, "provider_label": adapter.label, "is_ai": adapter.is_ai, "workflow": workflow,
        "prompt": prompt, "negative_prompt": negative, "seed": seed, "width": caps.width, "height": caps.height,
        "frames": frames, "fps": caps.fps, "requested_seconds": round(seconds, 2),
        "duration": info.duration if info else None, "source_image": scene.get("image_path") if image_path else None,
        "started_at": started, "finished_at": utcnow(), "external_id": external, **result.meta,
    }
    ensure_within(s.projects.folder(project), out)
    (out.with_suffix(".json")).write_text(prompts.dump(meta), encoding="utf-8")
    rel = s.projects.rel(project, out)
    if kind == "video":
        flags = []
        if info and info.duration and info.duration + 0.05 < seconds / eff.video.max_stretch:
            flags.append(f"Clip ({info.duration:.1f}s) is shorter than its narration ({seconds:.1f}s).")
        s.projects.update_scene(scene["id"], clip_status="completed", clip_path=rel, clip_meta=meta, flags=flags)
        if project["export_status"] == "completed":
            s.projects.update(project["id"], export_status="stale")
    else:
        s.projects.update_scene(scene["id"], image_status="completed", image_path=rel)
        if scene["clip_status"] == "completed":
            s.projects.update_scene(scene["id"], clip_status="stale")
    s.projects.snapshot(project["id"])
    return {"path": rel, "seconds": info.duration if info else None}


async def run_scene_clip(ctx: JobContext) -> dict:
    return await _generate(ctx, "video")


async def run_scene_image(ctx: JobContext) -> dict:
    return await _generate(ctx, "image")


async def _detect_silences(s, audio: Path, duration: float) -> list[tuple[float, float]]:
    stderr = await s.ffmpeg.run(["-i", str(audio), "-af", "silencedetect=noise=-38dB:d=0.15", "-f", "null", "-"],
                                duration_hint=duration)
    return alignment.parse_silences(stderr)


async def compute_word_timings(s, audio: Path, text: str, duration: float, method: str) -> tuple[list[alignment.Word], str]:
    tokens = alignment.tokenize(text)
    if method in ("auto", "whisper"):
        import asyncio

        asr = await asyncio.to_thread(alignment.whisper_words, str(audio))
        if asr:
            return alignment.align_to_transcript(tokens, asr, duration), "whisper"
        if method == "whisper":
            log.warning("faster-whisper not available; using heuristic alignment")
    silences = await _detect_silences(s, audio, duration)
    return alignment.heuristic_timings(tokens, duration, silences), "heuristic"


async def run_narration(ctx: JobContext) -> dict:
    s = ctx.s
    project = s.projects.require(ctx.project_id)
    eff = s.projects.effective_settings(project)
    n = eff.narration
    scenes = s.projects.scenes(project["id"])
    if scenes:
        text = " ".join(sc["narration"].strip() for sc in scenes if sc["narration"].strip())
    elif project.get("script"):
        text = project["script"]["full_text"]
    else:
        raise ValidationFailed("There is no script to narrate yet.")
    text = re.sub(r"\s+", " ", text).strip()
    local = n.provider == "kokoro"
    if not local:
        s.usage.check_limit("tts", len(text))  # daily cap protects paid credit only
    s.projects.update(project["id"], narration_status="running")
    ext = "wav" if local else n.format
    out = s.projects.folder(project) / "narration" / f"narration_{stamp()}.{ext}"
    try:
        if local:
            from ..integrations.kokoro_tts import describe_voice

            if not s.kokoro.installed():
                await ctx.progress(0.02, "Downloading the free voice model (one time, ~140 MB)")

                async def dl_progress(frac):
                    await ctx.progress(0.02 + 0.3 * frac, f"Downloading the free voice model… {int(frac * 100)}%")
            else:
                dl_progress = None
            await ctx.progress(0.35, "Generating narration on this PC (free voice)")
            tts = await s.kokoro.synthesize(text, out, voice=n.kokoro_voice, speed=n.speed, project_id=project["id"],
                                            on_progress=dl_progress)
            voice_id, voice_name, model = n.kokoro_voice, describe_voice(n.kokoro_voice)["label"], tts["model"]
        else:
            await ctx.progress(0.1, "Generating narration with Fish Audio")
            tts = await s.fish.synthesize(text, out, voice_id=n.voice_id, model=n.model, fmt=n.format, speed=n.speed,
                                          volume=n.volume, normalize=n.normalize, project_id=project["id"])
            voice_id, voice_name, model = n.voice_id, n.voice_name, n.model
    except BaseException:
        s.projects.update(project["id"], narration_status="failed")
        raise
    await ctx.progress(0.7, "Measuring and aligning narration")
    info = media_info(await s.ffmpeg.probe(out))
    words, method = await compute_word_timings(s, out, text, info.duration, n.alignment)
    narration = {
        "path": s.projects.rel(project, out), "duration": round(info.duration, 3), "voice_id": voice_id,
        "voice_name": voice_name, "provider": n.provider, "model": model, "speed": n.speed,
        "characters": tts["characters"],
        "cost_usd": tts.get("cost_usd"), "text": text, "words": [w.to_dict() for w in words],
        "alignment_method": method, "generated_at": utcnow(),
    }
    fields = {"narration": narration, "narration_status": "completed"}
    if project["export_status"] == "completed":
        fields["export_status"] = "stale"
    s.projects.update(project["id"], **fields)
    s.projects.write_json(project, "narration/narration.json", narration)
    ctx.log(f"Narration ready ({info.duration:.1f}s, {method} timing)")
    return {"duration": info.duration, "alignment": method}


def _music_path(s, eff) -> Path | None:
    m = eff.music
    if not m.enabled or not m.file:
        return None
    path = ensure_within(s.config.music_dir, s.config.music_dir / m.file)
    if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValidationFailed(f"Background music file '{m.file}' was not found in data/music.")
    return path


async def run_assemble(ctx: JobContext) -> dict:
    s = ctx.s
    project = s.projects.require(ctx.project_id)
    eff = s.projects.effective_settings(project)
    scenes = s.projects.scenes(project["id"])
    narr = project.get("narration")
    if not scenes:
        raise ValidationFailed("The project has no scenes.")
    if not narr or project["narration_status"] != "completed":
        raise ValidationFailed("Narration is missing or out of date. Generate narration first.")
    current_text = re.sub(r"\s+", " ", " ".join(sc["narration"].strip() for sc in scenes if sc["narration"].strip())).strip()
    if alignment.tokenize(current_text) != alignment.tokenize(narr["text"]):
        raise ValidationFailed("Scene narration changed after the audio was generated. Regenerate narration first.")
    missing = [sc["idx"] + 1 for sc in scenes if sc["clip_status"] != "completed" or not sc.get("clip_path")]
    if missing:
        raise ValidationFailed(f"Scenes {missing} have no finished clip yet.")
    s.projects.update(project["id"], export_status="running")
    folder = s.projects.folder(project)
    try:
        clips = []
        for sc in scenes:
            path = s.projects.abs(project, sc["clip_path"])
            if not path or not path.is_file():
                raise ValidationFailed(f"Clip file for scene {sc['idx'] + 1} is missing on disk; regenerate it.")
            info = media_info(await s.ffmpeg.probe(path))
            clips.append((path, info.duration))
        words = [alignment.Word(**w) for w in narr["words"]]
        tail = eff.video.tail_padding_s
        spans = alignment.scene_spans([sc["narration"] for sc in scenes], words, narr["duration"], tail)
        plans = assembly.plan_segments(clips, spans, max_stretch=eff.video.max_stretch, transition_s=eff.video.transition_s
                                       if eff.video.transition != "cut" else 0.0)
        total = round(narr["duration"] + tail, 3)
        cap = eff.captions
        ass_path = srt_path = None
        if cap.enabled:
            line_chars = captions.fit_chars(cap, eff.video.width, eff.video.height)
            cues = captions.build_cues(words, cap.max_words, line_chars)
            cap_dir = folder / "captions"
            cap_dir.mkdir(parents=True, exist_ok=True)
            if cap.save_srt:
                srt_path = cap_dir / "captions.srt"
                captions.write_srt(cues, srt_path, line_chars)
            if cap.burn_in:
                ass_path = cap_dir / "captions.ass"
                captions.write_ass(cues, ass_path, cap, eff.video.width, eff.video.height)
        out = folder / "exports" / f"{project['slug']}_{stamp()}.mp4"
        await assembly.assemble(
            s.ffmpeg, folder / "work", plans, s.projects.abs(project, narr["path"]), out, eff,
            ass_file=ass_path, music=_music_path(s, eff), total=total,
            on_progress=ctx.progress, is_cancelled=ctx.is_cancelled,
        )
        await ctx.progress(0.97, "Running quality checks")
        flags = [f"Scene {p.index + 1}: {f}" for p in plans for f in p.flags]
        report = await qc.run_qc(
            s.ffmpeg, out, eff, expect_audio=True, captions_expected=cap.enabled,
            captions_present=bool(ass_path or srt_path), narration_duration=narr["duration"], scene_flags=flags,
            draft_scenes=sum(1 for sc in scenes if (sc.get("clip_meta") or {}).get("is_ai") is False),
            missing_scenes=0,
        )
    except BaseException:
        s.projects.update(project["id"], export_status="failed")
        raise
    export = {
        "path": s.projects.rel(project, out), "srt_path": s.projects.rel(project, srt_path) if srt_path else None,
        "duration": report.get("media", {}).get("duration"), "width": eff.video.width, "height": eff.video.height,
        "fps": eff.video.fps, "created_at": utcnow(),
        "timeline": [{"scene": p.index + 1, "target": p.target, "speed": p.speed, "freeze": p.freeze} for p in plans],
    }
    s.projects.update(project["id"], export=export, export_status="completed", qc=report, stage="review",
                      review_status="none", assembly_approved=0)
    s.projects.write_json(project, "exports/export_settings.json", {"export": export, "settings": eff.model_dump()})
    s.projects.write_json(project, "exports/qc.json", report)
    s.projects.snapshot(project["id"])
    level = "info" if report["technical_ok"] and not report["warnings"] else "warning"
    ctx.log(f"Video exported ({export['duration'] or 0:.1f}s): {report['failures']} failed checks, {report['warnings']} warnings", level)
    return {"path": export["path"], "qc_ok": report["technical_ok"]}


HANDLERS = {
    "ideas": run_ideas,
    "research": run_research,
    "script": run_script,
    "factcheck": run_factcheck,
    "scene_plan": run_scene_plan,
    "scene_clip": run_scene_clip,
    "scene_image": run_scene_image,
    "narration": run_narration,
    "assemble": run_assemble,
}
