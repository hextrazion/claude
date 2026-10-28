"""Error taxonomy shared by providers, the pipeline and the job queue.

``kind`` decides retry behaviour:

* transient / rate_limit / unavailable -> retried with backoff
* everything else -> fails the job immediately (no point retrying a bad key)
"""

from __future__ import annotations

RETRYABLE = {"transient", "rate_limit", "unavailable", "timeout"}


class StudioError(Exception):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "permanent",
        detail: str | None = None,
        retry_after: float | None = None,
        provider: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.detail = detail
        self.retry_after = retry_after
        self.provider = provider

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE

    def to_dict(self) -> dict:
        return {"message": self.message, "kind": self.kind, "detail": self.detail, "provider": self.provider}


class ProviderError(StudioError):
    """Raised by an integration. Kinds: auth, quota, rate_limit, transient,
    unavailable, timeout, invalid_request, not_configured, oom, permanent."""


class NotConfigured(ProviderError):
    def __init__(self, provider: str, message: str):
        super().__init__(message, kind="not_configured", provider=provider)


class ValidationFailed(StudioError):
    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message, kind="invalid_request", detail=detail)


class Cancelled(Exception):
    """Raised inside a job when the user cancelled it."""


def http_error_kind(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 402:
        return "quota"
    if status == 429:
        return "rate_limit"
    if status in (408, 504):
        return "timeout"
    if status >= 500:
        return "transient"
    return "invalid_request"
