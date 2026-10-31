"""Groq text generation (OpenAI-compatible chat completions API).

Docs: https://console.groq.com/docs/api-reference
Groq has no live web access through this API; research is a separate stage.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from ..errors import NotConfigured, ProviderError
from ..secrets_store import SecretStore
from ..usage import UsageTracker
from .base import HealthResult, Timer, network_error, raise_for_status

log = logging.getLogger(__name__)

BASE_URL = "https://api.groq.com/openai/v1"
DOCS_URL = "https://console.groq.com/docs/quickstart"
KEYS_URL = "https://console.groq.com/keys"


class GroqClient:
    name = "groq"

    def __init__(self, secrets: SecretStore, usage: UsageTracker, transport: httpx.AsyncBaseTransport | None = None):
        self.secrets = secrets
        self.usage = usage
        self.transport = transport

    def _client(self, timeout: float = 90) -> httpx.AsyncClient:
        key = self.secrets.get("groq")
        if not key:
            raise NotConfigured("groq", "Groq API key is not configured. Add it on the Integrations page.")
        return httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
            transport=self.transport,
        )

    def _capture_rate_limits(self, headers: httpx.Headers) -> None:
        info = {k: v for k, v in headers.items() if k.lower().startswith("x-ratelimit")}
        if info:
            self.usage.rate_limits["groq"] = info

    async def list_models(self) -> list[dict]:
        async with self._client(timeout=20) as client:
            try:
                resp = await client.get("/models")
            except httpx.HTTPError as exc:
                raise network_error("Groq", exc) from exc
        raise_for_status(resp, "Groq")
        self._capture_rate_limits(resp.headers)
        models = resp.json().get("data", [])
        return sorted(
            (
                {
                    "id": m.get("id"),
                    "owned_by": m.get("owned_by"),
                    "context_window": m.get("context_window"),
                    "active": m.get("active", True),
                }
                for m in models
                if m.get("id")
            ),
            key=lambda m: m["id"],
        )

    async def pick_vision_model(self, preferred: str) -> str | None:
        """An available model that accepts images: the preferred one, else any vision-capable id."""
        try:
            ids = [m["id"] for m in await self.list_models() if m.get("active", True)]
        except ProviderError:
            return preferred or None
        if preferred in ids:
            return preferred
        from ..styles import VISION_PATTERNS

        for pattern in VISION_PATTERNS:
            for mid in ids:
                if pattern in mid.lower():
                    return mid
        return None

    async def test(self) -> HealthResult:
        if not self.secrets.get("groq"):
            return HealthResult("not_configured", "Add a Groq API key to enable ideas and scripts.")
        try:
            models = await self.list_models()
        except ProviderError as exc:
            return HealthResult("error", exc.message, detail=exc.detail)
        ids = [m["id"] for m in models]
        return HealthResult(
            "ok",
            f"Connected. {len(ids)} models available.",
            info={"models": ids, "rate_limits": self.usage.rate_limits.get("groq", {})},
        )

    async def chat_json(
        self,
        messages: list[dict],
        *,
        model: str,
        operation: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Chat completion that must return a JSON object.

        Uses Groq's JSON mode, and retries once with a corrective message if
        the model still produces something unparsable.
        """
        attempt_messages = list(messages)
        last_error: Exception | None = None
        for attempt in range(2):
            content = await self._complete(
                attempt_messages,
                model=model,
                operation=operation,
                temperature=temperature if attempt == 0 else max(0.2, temperature - 0.4),
                max_tokens=max_tokens,
                project_id=project_id,
                json_mode=True,
            )
            try:
                return parse_json_object(content)
            except ValueError as exc:
                last_error = exc
                attempt_messages = messages + [
                    {"role": "assistant", "content": content[:4000]},
                    {"role": "user", "content": "That was not valid JSON. Reply again with only the JSON object."},
                ]
        raise ProviderError(
            "The text model returned malformed output twice.", kind="transient", detail=str(last_error), provider="groq"
        )

    async def _complete(
        self, messages, *, model, operation, temperature, max_tokens, project_id, json_mode
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        async with self._client() as client:
            with Timer() as t:
                try:
                    resp = await client.post("/chat/completions", json=body)
                except httpx.HTTPError as exc:
                    err = network_error("Groq", exc)
                    self.usage.record("groq", operation, ok=False, model=model, error=err.message, project_id=project_id)
                    raise err from exc
        self._capture_rate_limits(resp.headers)
        if not resp.is_success:
            # Groq returns 400 json_validate_failed when the model breaks JSON mode: worth one retry.
            text = resp.text
            self.usage.record(
                "groq", operation, ok=False, model=model, status_code=resp.status_code,
                duration_ms=t.ms, error=text[:300], project_id=project_id,
            )
            if resp.status_code == 400 and "json_validate_failed" in text:
                raise ProviderError("The text model produced invalid JSON.", kind="transient", detail=text[:300], provider="groq")
            if resp.status_code == 404 or "model_not_found" in text or "decommissioned" in text:
                raise ProviderError(
                    f"Groq model '{model}' is not available. Choose another model in Settings → Text.",
                    kind="invalid_request", detail=text[:300], provider="groq",
                )
            raise_for_status(resp, "Groq")
        data = resp.json()
        usage = data.get("usage") or {}
        self.usage.record(
            "groq", operation, ok=True, model=model, status_code=resp.status_code,
            input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
            duration_ms=t.ms, project_id=project_id,
        )
        try:
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
        except (KeyError, IndexError) as exc:
            raise ProviderError("Unexpected response from Groq.", kind="transient", detail=str(data)[:300]) from exc
        if choice.get("finish_reason") == "length":
            log.warning("groq %s output truncated at max tokens", operation)
        return content


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_object(text: str) -> dict:
    text = text.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        stripped = _FENCE.sub("", text).strip()
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object found")
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value
