"""Judge clip transcripts with any local OpenAI-compatible server (Ollama, LM Studio, llama.cpp, Jan)."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import List, Optional

SYSTEM = (
    "You judge short clips from livestreams and videos for a 'Top 5 funniest moments' compilation. "
    "You get a transcript of the clip (it may be empty or noisy). Rate how funny/entertaining the moment is. "
    "Reply with ONLY a JSON object: "
    '{"score": <0-100 integer>, "reason": "<max 20 words>", "title": "<max 8 words, catchy>"}'
)


@dataclass
class Judgement:
    score: float
    reason: str
    title: str


class LLMError(RuntimeError):
    pass


class LocalLLM:
    def __init__(self, base_url: str = "http://localhost:11434/v1", model: str = "", api_key: str = "",
                 timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, path: str, payload: Optional[dict] = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base_url + path, data=data,
                                     headers={"Content-Type": "application/json"})
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            raise LLMError(f"cannot reach local model at {self.base_url}: {e}") from e

    def models(self) -> List[str]:
        return [m.get("id", "") for m in self._request("/models").get("data", [])]

    def resolve_model(self) -> str:
        """Use the configured model, or the first one the server lists."""
        if not self.model:
            names = self.models()
            if not names:
                raise LLMError("the local server reports no models")
            self.model = names[0]
        return self.model

    def judge(self, transcript: str, context: str = "") -> Judgement:
        model = self.resolve_model()
        user = f"Clip transcript:\n\"\"\"\n{transcript.strip()[:2500] or '(no speech detected)'}\n\"\"\""
        if context:
            user += f"\nContext: {context}"
        resp = self._request("/chat/completions", {
            "model": model, "temperature": 0.2, "stream": False,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        })
        try:
            text = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"unexpected response shape: {str(resp)[:200]}") from e
        return parse_judgement(text)


def parse_judgement(text: str) -> Judgement:
    """Models wrap JSON in prose or code fences; pull out the first object."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)  # reasoning models
    m = re.search(r"\{.*?\}", text, flags=re.S)
    if not m:
        raise LLMError(f"no JSON in model reply: {text[:200]!r}")
    try:
        d = json.loads(m.group(0))
        score = float(d.get("score", 0))
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise LLMError(f"bad JSON from model: {m.group(0)[:200]!r}") from e
    return Judgement(score=max(0.0, min(100.0, score)), reason=str(d.get("reason", ""))[:200],
                     title=str(d.get("title", ""))[:80])
