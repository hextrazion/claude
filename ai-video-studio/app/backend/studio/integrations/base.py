"""Shared pieces for HTTP integrations."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from ..db import utcnow
from ..errors import ProviderError, http_error_kind


@dataclass
class HealthResult:
    status: str  # ok | warning | error | not_configured | unavailable
    message: str
    detail: str | None = None
    info: dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return asdict(self)


def parse_retry_after(headers: httpx.Headers) -> float | None:
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def error_message_from(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        return resp.text[:300]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        if isinstance(err, str):
            return err[:300]
        for key in ("message", "detail"):
            if body.get(key):
                return str(body[key])[:300]
    return str(body)[:300]


def raise_for_status(resp: httpx.Response, provider: str, friendly: dict[int, str] | None = None) -> None:
    if resp.is_success:
        return
    kind = http_error_kind(resp.status_code)
    detail = f"HTTP {resp.status_code}: {error_message_from(resp)}"
    message = (friendly or {}).get(resp.status_code) or {
        "auth": f"{provider} rejected the API key. Check it on the Integrations page.",
        "quota": f"{provider} reports insufficient credit or quota.",
        "rate_limit": f"{provider} rate limit reached; the job will retry automatically.",
        "timeout": f"{provider} timed out.",
        "transient": f"{provider} had a temporary server error.",
        "invalid_request": f"{provider} rejected the request.",
    }[kind]
    raise ProviderError(message, kind=kind, detail=detail, retry_after=parse_retry_after(resp.headers), provider=provider)


def network_error(provider: str, exc: Exception) -> ProviderError:
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(f"{provider} did not respond in time.", kind="timeout", detail=repr(exc), provider=provider)
    return ProviderError(
        f"Could not reach {provider}. Check your internet connection or the service address.",
        kind="unavailable",
        detail=repr(exc),
        provider=provider,
    )


class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self.start) * 1000)
        return False
