"""Chat assistant: turn "find funny clips from X, vertical with captions" into a JobSpec.

The local model only has to fill in a JSON object (far more reliable on small models than free-form tool
calling). If the model is offline or replies with junk, a keyword parser covers the common phrasings.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from .llm import LLMError, LocalLLM
from .spec import JobSpec, is_actionable, normalize

SYSTEM = """You are the assistant inside Clip Compiler, an app that finds funny moments from streamers/videos and
edits them into one video. Turn the user's message into a job.

Reply with ONLY a JSON object: {"reply": "<short friendly message>", "spec": <object or null>}

spec fields (include only what the user asked for; the app keeps previous values for the rest):
  "query": streamer name or topic            "urls": [explicit links, if given]
  "platform": "auto" | "youtube" | "twitch"  "period": "week" | "month" | "year" | "all"
  "count": number of clips (1-20)            "style": "countdown" (Top N with #N badges) | "compilation" (plain cuts)
  "aspect": "16:9" | "9:16" (vertical: TikTok/Shorts/Reels) | "1:1"
  "captions": true/false  "overlay": true/false  "intro": true/false
  "max_clip_seconds": 8-60   "title": optional video title

Rules: if you do not know who/what to search for and there are no links, set "spec" to null and ask in "reply".
Otherwise "reply" briefly confirms what you will make; the user presses Start to confirm.
Never claim the video is finished - you only prepare the job."""


def _extract_json(text: str) -> Optional[dict]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    for m in re.finditer(r"\{", text):
        depth = 0
        for j in range(m.start(), len(text)):
            depth += (text[j] == "{") - (text[j] == "}")
            if depth == 0:
                try:
                    d = json.loads(text[m.start(): j + 1])
                    if isinstance(d, dict):
                        return d
                except json.JSONDecodeError:
                    pass
                break
    return None


_URL = re.compile(r"https?://\S+")
_NAME = re.compile(r"(?=\b(?:from|of|by|featuring)\s+@?([A-Za-z0-9_][A-Za-z0-9_ .'-]{1,40}))", re.I)  # lookahead: try every keyword
# the name ends at the first of these words (edit instructions, formats, time phrases)
_CUT = {"and", "then", "in", "into", "as", "on", "with", "for", "using", "make", "compile", "put", "so", "that",
        "top", "vertical", "horizontal", "square", "tiktok", "shorts", "short", "reels", "captions", "caption",
        "subtitles", "no", "without", "this", "last", "past", "all", "twitch", "youtube", "funny", "funniest",
        "clips", "clip", "moments", "compilation", "countdown", "please", "to", "at", "by", "from", "of", "i", "we",
        "need", "want", "like", "video", "videos", "edit", "edits"}
_STOP = {"the", "a", "an", "this", "that", "my", "me", "it", "them", "one", "each", "twitch", "youtube"}


def _name_from(message: str) -> str:
    for m in _NAME.finditer(message):
        toks = []
        for t in m.group(1).split():
            t = t.strip(".,!?;:'\"")
            if not t or t.lower() in _CUT or t.isdigit():
                break
            toks.append(t)
            if len(toks) == 3:
                break
        name = " ".join(toks).strip(" .-")
        if name and name.lower() not in _STOP:
            return name
    return ""


def heuristic_spec(message: str, base: Optional[JobSpec] = None) -> Tuple[dict, bool]:
    """Keyword parse. Returns (changes, understood_anything)."""
    m, low = message, message.lower()
    d: dict = {}
    urls = _URL.findall(m)
    if urls:
        d["urls"] = [u.rstrip(".,)") for u in urls]
    n = re.search(r"\btop\s*(\d{1,2})\b", low) or re.search(r"\b(\d{1,2})\s+(?:of\s+the\s+)?(?:funniest|best|clips|moments)\b", low)
    if n:
        d["count"] = int(n.group(1))
    if re.search(r"\b(vertical|tiktok|tik tok|shorts?|reels?|9:16|portrait)\b", low):
        d["aspect"] = "9:16"
    elif re.search(r"\b(square|1:1|instagram post)\b", low):
        d["aspect"] = "1:1"
    elif re.search(r"\b(16:9|widescreen|landscape|horizontal)\b", low):
        d["aspect"] = "16:9"
    if re.search(r"\b(no|without|remove)\s+(captions?|subtitles?)\b", low):
        d["captions"] = False
    elif re.search(r"\b(captions?|subtitles?)\b", low):
        d["captions"] = True
    if re.search(r"\b(no|without)\s+(countdown|numbers?|ranking)\b|\b(compilation|montage|supercut)\b", low):
        d["style"] = "compilation"
    elif re.search(r"\b(top\s*\d+|countdown|ranked|ranking)\b", low):
        d["style"] = "countdown"
    if re.search(r"\bno\s+intro\b", low):
        d["intro"] = False
    if re.search(r"\b(no|without)\s+(overlays?|text)\b", low):
        d["overlay"] = False
    for pat, val in ((r"\b(this|past|last)\s+week\b", "week"), (r"\b(this|past|last)\s+month\b", "month"),
                     (r"\b(this|past|last)\s+year\b", "year"), (r"\ball[- ]time\b", "all")):
        if re.search(pat, low):
            d["period"] = val
            break
    # platform = where to SEARCH; "for youtube shorts" names the destination, not the source
    if re.search(r"\b(from|on|using|via)\s+twitch\b|\btwitch\s+(clips?|vods?)\b", low):
        d["platform"] = "twitch"
    elif re.search(r"\b(from|on|using|via)\s+youtube\b|\byoutube\s+(search|videos?)\b", low):
        d["platform"] = "youtube"
    sec = re.search(r"\b(\d{1,2})\s*(?:s|sec|secs|seconds)\b", low)
    if sec:
        d["max_clip_seconds"] = int(sec.group(1))
    if not urls:
        name = _name_from(m)
        if name:
            d["query"] = name
    return d, bool(d)


class ChatAgent:
    def __init__(self, llm: Optional[LocalLLM] = None):
        self.llm = llm

    def respond(self, history: List[dict], message: str, current: Optional[JobSpec] = None) -> Tuple[str, Optional[JobSpec]]:
        """Returns (reply, spec). `spec` is the full updated spec, or None if more info is needed."""
        current = current or JobSpec()
        reply, changes, used_llm, failed = "", None, False, False
        if self.llm is not None:
            msgs = [{"role": "system", "content": SYSTEM + f"\n\nCurrent job: {json.dumps(current.to_dict())}"}]
            msgs += [{"role": h["role"], "content": h["content"]} for h in history[-8:]]
            msgs.append({"role": "user", "content": message})
            try:
                data = _extract_json(self.llm.chat(msgs))
                if data is not None:
                    used_llm = True
                    reply = str(data.get("reply", ""))[:600]
                    changes = data.get("spec") if isinstance(data.get("spec"), dict) else None
            except LLMError:
                self.llm, failed = None, True  # stop retrying a dead server on every message; keyword mode from now on
        note = ""
        if not used_llm:
            h, ok = heuristic_spec(message, current)
            changes = h if ok else None
            note = " (I couldn't reach the local model, so I used simple keyword parsing.)" if failed else ""
        spec = normalize(changes, current) if changes is not None else (current if is_actionable(current) else None)
        # a heuristic/LLM spec with nothing to search for is not runnable
        if spec is not None and not is_actionable(spec):
            spec = None
        if spec is None:
            return (reply or "Who should I find clips from? Give me a streamer name or some links, and any edit "
                    "preferences (how many clips, vertical or widescreen, captions...).") + note, None
        if not reply:
            from .spec import summary
            reply = f"Got it: {summary(spec)}. Press Start when you're ready, or tell me what to change."
        return reply + note, spec
