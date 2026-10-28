"""Fish Audio text-to-speech.

Docs: https://docs.fish.audio  (TTS: POST /v1/tts, voices: GET /model,
credit: GET /wallet/self/api-credit). The TTS model is selected with the
``model`` request header (e.g. ``s2-pro`` or ``s1``); which models and voices
an account can use depends on its plan, so the app discovers voices at
runtime instead of hardcoding them.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from ..errors import NotConfigured, ProviderError
from ..secrets_store import SecretStore
from ..usage import UsageTracker
from .base import HealthResult, Timer, network_error, raise_for_status

log = logging.getLogger(__name__)

BASE_URL = "https://api.fish.audio"
DOCS_URL = "https://docs.fish.audio"
KEYS_URL = "https://fish.audio/app/api-keys/"
KNOWN_MODELS = ["s2-pro", "s1"]

_FRIENDLY = {
    401: "Fish Audio rejected the API key. Check it on the Integrations page.",
    402: "Fish Audio reports insufficient API credit. Top up your account to continue narration.",
}


class FishAudioClient:
    name = "fish_audio"

    def __init__(self, secrets: SecretStore, usage: UsageTracker, transport: httpx.AsyncBaseTransport | None = None):
        self.secrets = secrets
        self.usage = usage
        self.transport = transport

    def _client(self, timeout: float = 60, extra_headers: dict | None = None) -> httpx.AsyncClient:
        key = self.secrets.get("fish_audio")
        if not key:
            raise NotConfigured("fish_audio", "Fish Audio API key is not configured. Add it on the Integrations page.")
        return httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {key}", **(extra_headers or {})},
            timeout=timeout,
            transport=self.transport,
        )

    async def credit(self) -> dict:
        async with self._client(timeout=20) as client:
            try:
                resp = await client.get("/wallet/self/api-credit")
            except httpx.HTTPError as exc:
                raise network_error("Fish Audio", exc) from exc
        raise_for_status(resp, "Fish Audio", _FRIENDLY)
        return resp.json()

    async def list_voices(self, *, mine: bool = False, query: str = "", page_size: int = 20, page: int = 1) -> dict:
        params: dict = {"page_size": max(1, min(page_size, 50)), "page_number": max(1, page)}
        if mine:
            params["self"] = "true"
        if query:
            params["title"] = query[:80]
        async with self._client(timeout=20) as client:
            try:
                resp = await client.get("/model", params=params)
            except httpx.HTTPError as exc:
                raise network_error("Fish Audio", exc) from exc
        raise_for_status(resp, "Fish Audio", _FRIENDLY)
        data = resp.json()
        items = data.get("items", []) if isinstance(data, dict) else []
        return {
            "total": data.get("total", len(items)) if isinstance(data, dict) else len(items),
            "items": [
                {
                    "id": v.get("_id") or v.get("id"),
                    "title": v.get("title", ""),
                    "description": (v.get("description") or "")[:200],
                    "languages": v.get("languages", []),
                    "tags": v.get("tags", [])[:6],
                    "cover_image": v.get("cover_image"),
                    "visibility": v.get("visibility"),
                    "samples": [s.get("audio") for s in v.get("samples", []) if isinstance(s, dict) and s.get("audio")][:1],
                }
                for v in items
                if isinstance(v, dict)
            ],
        }

    async def test(self) -> HealthResult:
        if not self.secrets.get("fish_audio"):
            return HealthResult("not_configured", "Add a Fish Audio API key to enable narration.")
        try:
            credit = await self.credit()
        except ProviderError as exc:
            return HealthResult("error", exc.message, detail=exc.detail)
        balance = credit.get("credit")
        msg = "Connected."
        status = "ok"
        if balance is not None:
            msg = f"Connected. API credit: {balance}"
            try:
                if float(balance) <= 0:
                    status, msg = "warning", "Connected, but the API credit balance is 0."
            except (TypeError, ValueError):
                pass
        return HealthResult(status, msg, info={"credit": balance})

    async def synthesize(
        self,
        text: str,
        out_path: Path,
        *,
        voice_id: str,
        model: str,
        fmt: str = "mp3",
        speed: float = 1.0,
        volume: float = 0.0,
        normalize: bool = True,
        project_id: int | None = None,
    ) -> dict:
        if not voice_id:
            raise ProviderError(
                "No narration voice selected. Pick one in Settings → Narration or on the project.",
                kind="invalid_request", provider="fish_audio",
            )
        body = {
            "text": text,
            "reference_id": voice_id,
            "format": fmt,
            "normalize": normalize,
            "latency": "normal",
            "prosody": {"speed": speed, "volume": volume},
        }
        if fmt == "mp3":
            body["mp3_bitrate"] = 192
        chars = len(text)
        tmp = out_path.with_suffix(out_path.suffix + ".part")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._client(timeout=300, extra_headers={"model": model}) as client:
            with Timer() as t:
                try:
                    async with client.stream("POST", "/v1/tts", json=body) as resp:
                        if not resp.is_success:
                            await resp.aread()
                            self.usage.record(
                                "fish_audio", "tts", ok=False, model=model, status_code=resp.status_code,
                                error=resp.text[:300], project_id=project_id,
                            )
                            raise_for_status(resp, "Fish Audio", _FRIENDLY)
                        size = 0
                        with tmp.open("wb") as fh:
                            async for chunk in resp.aiter_bytes():
                                fh.write(chunk)
                                size += len(chunk)
                except httpx.HTTPError as exc:
                    tmp.unlink(missing_ok=True)
                    err = network_error("Fish Audio", exc)
                    self.usage.record("fish_audio", "tts", ok=False, model=model, error=err.message, project_id=project_id)
                    raise err from exc
        if size < 1024:
            tmp.unlink(missing_ok=True)
            raise ProviderError("Fish Audio returned an empty audio file.", kind="transient", provider="fish_audio")
        tmp.replace(out_path)
        cost = self.usage.record(
            "fish_audio", "tts", ok=True, model=model, status_code=200, characters=chars,
            duration_ms=t.ms, project_id=project_id,
        )
        return {"path": str(out_path), "bytes": size, "characters": chars, "model": model, "cost_usd": cost}
