"""Prompts for the text model. Each returns chat messages asking for JSON."""

from __future__ import annotations

import json

WORDS_PER_SECOND = 2.6  # brisk short-form narration (~155 wpm)

_BANNED = (
    "\"In this video\", \"Have you ever wondered\", \"Let's dive in\", \"buckle up\", \"mind-blowing\", "
    "\"you won't believe\", \"fascinating\", \"delve\", \"in today's world\", \"stay tuned\", \"smash that like\""
)


def ideas_messages(*, niche: str, exclusions: str, count: int, duration_s: int, tone: str, avoid: list[str], notes: str) -> list[dict]:
    avoid_block = "\n".join(f"- {t}" for t in avoid[:80]) or "- (none yet)"
    system = (
        "You are a senior content strategist for short-form educational explainer videos (TikTok, YouTube Shorts, "
        "Reels). You pitch specific, surprising, *verifiable* concepts that can be explained visually in under a "
        "minute. You never pitch listicles ('5 facts about...'), vague topics, conspiracy theories, medical or "
        "financial advice, or claims that rest on a single disputed study."
    )
    user = f"""Pitch {count} video concepts.

Niche / themes: {niche}
Tone: {tone}
Target length: about {duration_s} seconds each.
Exclude these topics: {exclusions or 'nothing specific'}
Extra direction: {notes or 'none'}

Do NOT repeat or closely resemble any of these existing titles:
{avoid_block}

Each concept must centre on ONE concrete question or surprising mechanism (e.g. "Why do onions make you cry,
but only when cut?"), have a hook a viewer understands in the first two seconds, and be explainable with clear
visuals (animation, 3D, diagrams in motion). Prefer well-established science/history over fringe claims.

Return JSON:
{{"ideas": [{{
  "title": "working title, max 70 chars",
  "niche": "short category",
  "central_question": "the single question or surprising idea",
  "hook": "the spoken opening line (max 14 words)",
  "description": "2-3 sentence outline of the explanation",
  "appeal": "why viewers will watch to the end",
  "visual_approach": "how it can be shown visually",
  "est_duration_s": {duration_s},
  "research_needs": "facts that must be checked before publishing",
  "accuracy_concerns": "common misconceptions or claims that are often exaggerated",
  "score": 0-10 honest rating of hook strength x clarity x visual potential
}}]}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def research_queries_messages(idea: dict) -> list[dict]:
    return [
        {"role": "system", "content": "You write precise encyclopedia/web search queries. Reply with JSON only."},
        {"role": "user", "content": (
            f"Topic: {idea['title']}\nQuestion: {idea.get('central_question', '')}\n"
            f"Facts to check: {idea.get('research_needs', '')}\n\n"
            'Write 3 short search queries (2-6 words each) that would find authoritative background. '
            'Return {"queries": ["...", "...", "..."]}'
        )},
    ]


def fact_sheet_messages(idea: dict, sources: list[dict]) -> list[dict]:
    src = "\n\n".join(f"[{s['id']}] {s['title']} ({s['url']})\n{s['snippet'][:2200]}" for s in sources)
    return [
        {"role": "system", "content": (
            "You extract facts from provided sources only. Never add knowledge that is not in the sources. "
            "Every fact must cite the source ids it comes from. Reply with JSON only."
        )},
        {"role": "user", "content": (
            f"Video topic: {idea['title']} — {idea.get('central_question', '')}\n\nSOURCES:\n{src}\n\n"
            "List up to 12 facts from these sources that are useful for a short explainer on this topic, plus "
            "cautions (common misconceptions, nuances, things the sources do NOT support).\n"
            'Return {"facts": [{"fact": "...", "source_ids": ["S1"]}], "cautions": ["..."]}'
        )},
    ]


def script_messages(idea: dict, *, duration_s: int, tone: str, research: dict | None, feedback: str | None = None) -> list[dict]:
    target_words = round(duration_s * WORDS_PER_SECOND)
    if research and research.get("facts"):
        facts = "\n".join(f"- {f['fact']} [{', '.join(f.get('source_ids', []))}]" for f in research["facts"])
        cautions = "\n".join(f"- {c}" for c in research.get("cautions", []))
        fact_rule = (
            f"Use ONLY these researched facts for factual claims (cite ids in sources_used):\n{facts}\n"
            f"Cautions:\n{cautions or '- none'}\n"
            "If a point you want to make is not supported above, leave it out or phrase it as clearly hedged."
        )
    else:
        fact_rule = (
            "No research sources are available. Use only widely established, textbook-level facts. Do NOT invent "
            "statistics, dates, names or numbers. List every specific factual claim you make in uncertain_claims "
            "so a human can verify it."
        )
    system = (
        "You are an expert scriptwriter for short-form educational explainers. You write for the ear: short "
        "sentences, concrete images, one idea per sentence, natural rhythm. Every line earns its place."
    )
    user = f"""Write the narration script.

Concept: {idea['title']}
Central question: {idea.get('central_question', '')}
Suggested hook: {idea.get('hook', '')}
Outline: {idea.get('description', '')}
Tone: {tone}
Length: {duration_s} seconds ≈ {target_words} spoken words (stay within ±10%).

{fact_rule}

Rules:
- First sentence is the hook: a surprising statement or question, max 14 words.
- Then a clear, logical explanation that builds step by step; each step should be easy to show visually.
- End with a satisfying payoff line that resolves the opening question. Optional short call to action (max 8 words) only if natural.
- No filler, no repetition, no hype, no exaggeration. Avoid these phrases: {_BANNED}.
- Write numbers as they should be spoken. No emojis, hashtags, stage directions or markdown in the narration.
- Split into 4-9 segments; each segment is 1-3 sentences that belong together visually.

Return JSON:
{{"title": "final title",
  "segments": [{{"text": "narration", "purpose": "hook|setup|explanation|payoff|cta", "visual_idea": "what the viewer should see"}}],
  "sources_used": ["S1"],
  "uncertain_claims": ["specific claims a human should double-check"]}}"""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if feedback:
        msgs.append({"role": "user", "content": feedback})
    return msgs


def factcheck_messages(script_text: str, sources: list[dict]) -> list[dict]:
    if sources:
        src = "\n\n".join(f"[{s['id']}] {s['title']} ({s['domain']})\n{s['snippet'][:1800]}" for s in sources)
        task = (
            "For each claim decide, using ONLY the sources: supported, partially_supported, not_found, contradicted, "
            "or creative (opinion, framing, rhetorical question, not a factual claim). Quote a short evidence "
            "snippet for supported/contradicted claims."
        )
    else:
        src = "(no sources available)"
        task = "No sources are available: label every factual claim not_checked and every non-factual line creative."
    return [
        {"role": "system", "content": "You are a meticulous fact-checker. You never assume facts that are not in the provided sources. Reply with JSON only."},
        {"role": "user", "content": (
            f"SCRIPT:\n{script_text}\n\nSOURCES:\n{src}\n\n"
            f"Extract up to 12 distinct factual claims from the script. {task}\n"
            'Return {"claims": [{"claim": "...", "label": "...", "source_ids": ["S1"], "evidence": "...", "note": "..."}]}'
        )},
    ]


def scene_plan_messages(
    script: dict,
    *,
    duration_s: int,
    max_clip_s: float,
    model_notes: str,
    style: str,
    aspect: str,
    use_images: bool,
    feedback: str | None = None,
) -> list[dict]:
    segments = "\n".join(f"{i + 1}. {s['text']}  (visual idea: {s.get('visual_idea', '')})" for i, s in enumerate(script["segments"]))
    min_scenes = max(3, round(duration_s / max(1.0, max_clip_s)))
    system = (
        "You are a director and storyboard artist for animated educational explainers. You translate narration "
        "into shots that make the explanation easier to understand, and you write prompts for AI video models."
    )
    user = f"""Create the scene-by-scene production plan.

SCRIPT SEGMENTS:
{segments}

Video: about {duration_s}s, aspect {aspect}.
Video model: {model_notes}
Each generated clip can be at most {max_clip_s:.1f}s long, so a scene's narration should take no more than about
{max_clip_s:.1f}s to speak (~{int(max_clip_s * 2.6)} words). Split long segments into several scenes. Expect roughly
{min_scenes}-{min_scenes + 4} scenes; choose what the pacing needs.
Global visual style (apply to every scene): {style}

Rules:
- The scenes' "narration" fields, concatenated in order, must reproduce the full script text EXACTLY, word for word.
- Each scene shows what the viewer needs to SEE to understand that narration (mechanism, comparison, cause and effect), not generic pretty footage.
- Video prompts: one clear subject and one clear action, concrete nouns, materials, lighting, colours and camera; 40-90 words; describe motion explicitly. Never ask for readable text, labels, numbers or UI in the image.
- Keep characters, objects, palette and environment consistent between related scenes: define them once in style_bible and repeat key descriptors in each prompt.
- {"For scenes that need tight composition or consistent recurring objects, set needs_image=true and write image_prompt for a still frame." if use_images else "Set needs_image=false for every scene."}

Return JSON:
{{"style_bible": "consistent look, palette, recurring elements",
  "scenes": [{{
    "narration": "exact script text for this scene",
    "visual_objective": "what the viewer must understand from the visuals",
    "prompt": "detailed video generation prompt",
    "negative_prompt": "things to avoid (optional)",
    "camera": "camera movement",
    "subject_motion": "what moves and how",
    "environment": "setting and lighting",
    "style": "style notes specific to this scene",
    "duration_s": estimated seconds,
    "needs_image": false,
    "image_prompt": "",
    "transition": "cut|fade|dissolve"
  }}]}}"""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if feedback:
        msgs.append({"role": "user", "content": feedback})
    return msgs


def compose_video_prompt(scene: dict, style_bible: str, global_style: str) -> str:
    parts = [scene.get("prompt", "").strip()]
    if scene.get("subject_motion"):
        parts.append(f"Motion: {scene['subject_motion']}")
    if scene.get("camera"):
        parts.append(f"Camera: {scene['camera']}")
    if scene.get("environment"):
        parts.append(f"Setting: {scene['environment']}")
    style = " ".join(x for x in (scene.get("style", ""), style_bible, global_style) if x)
    if style:
        parts.append(f"Style: {style}")
    return ". ".join(p.rstrip(". ") for p in parts if p) + "."


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
