"""API usage accounting, cost estimates and daily limits."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import Database, utcnow
from .errors import ProviderError
from .settings import SettingsService


def _day_start_utc() -> str:
    # Limits reset at local midnight.
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).isoformat(timespec="seconds")


class UsageTracker:
    def __init__(self, db: Database, settings: SettingsService):
        self.db = db
        self.settings = settings
        # Latest rate-limit headers per provider (in memory; informational).
        self.rate_limits: dict[str, dict] = {}

    def record(
        self,
        provider: str,
        operation: str,
        *,
        ok: bool,
        model: str | None = None,
        status_code: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        characters: int | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
        project_id: int | None = None,
    ) -> float | None:
        cost = self.estimate_cost(provider, model, input_tokens, output_tokens, characters) if ok else None
        self.db.execute(
            "INSERT INTO api_usage(ts, provider, model, operation, ok, status_code, input_tokens, output_tokens,"
            " characters, cost_usd, duration_ms, error, project_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                utcnow(), provider, model, operation, int(ok), status_code, input_tokens, output_tokens,
                characters, cost, duration_ms, (error or "")[:500] or None, project_id,
            ),
        )
        return cost

    def estimate_cost(self, provider, model, input_tokens, output_tokens, characters) -> float | None:
        pricing = self.settings.get().pricing
        if provider == "groq":
            if pricing.groq_free_tier:
                return 0.0
            rates = pricing.groq_usd_per_m_tokens.get(model or "")
            if not rates or input_tokens is None:
                return None
            return round((input_tokens * rates[0] + (output_tokens or 0) * rates[1]) / 1_000_000, 6)
        if provider == "kokoro":
            return 0.0  # runs locally
        if provider == "fish_audio" and characters:
            return round(characters * pricing.fish_usd_per_m_chars / 1_000_000, 6)
        return None

    def count_today(self, provider: str, operation: str | None = None, ok_only: bool = True) -> int:
        sql = "SELECT COUNT(*) FROM api_usage WHERE provider = ? AND ts >= ?"
        params: list = [provider, _day_start_utc()]
        if operation:
            sql += " AND operation = ?"
            params.append(operation)
        if ok_only:
            sql += " AND ok = 1"
        return int(self.db.scalar(sql, tuple(params)) or 0)

    def chars_today(self, provider: str) -> int:
        return int(
            self.db.scalar(
                "SELECT COALESCE(SUM(characters), 0) FROM api_usage WHERE provider = ? AND ok = 1 AND ts >= ?",
                (provider, _day_start_utc()),
            )
            or 0
        )

    def check_limit(self, kind: str, extra_chars: int = 0) -> None:
        """Raise a quota error when a configured daily limit would be exceeded."""
        limits = self.settings.get().limits
        if kind == "ideas":
            if limits.max_idea_batches_per_day and self.count_today("groq", "ideas") >= limits.max_idea_batches_per_day:
                raise ProviderError(
                    f"Daily idea-generation limit reached ({limits.max_idea_batches_per_day} batches). "
                    "Raise it in Settings → Limits or wait until tomorrow.",
                    kind="quota", provider="groq",
                )
        elif kind == "script":
            if limits.max_scripts_per_day and self.count_today("groq", "script") >= limits.max_scripts_per_day:
                raise ProviderError(
                    f"Daily script limit reached ({limits.max_scripts_per_day}).", kind="quota", provider="groq"
                )
        elif kind == "tts":
            if limits.max_tts_chars_per_day and self.chars_today("fish_audio") + extra_chars > limits.max_tts_chars_per_day:
                raise ProviderError(
                    f"Daily narration limit would be exceeded ({limits.max_tts_chars_per_day} characters).",
                    kind="quota", provider="fish_audio",
                )

    def summary(self, days: int = 30) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        return self.db.query(
            "SELECT provider, COUNT(*) AS requests, SUM(ok) AS ok, SUM(COALESCE(input_tokens,0)) AS input_tokens,"
            " SUM(COALESCE(output_tokens,0)) AS output_tokens, SUM(COALESCE(characters,0)) AS characters,"
            " SUM(COALESCE(cost_usd,0)) AS cost_usd, MAX(ts) AS last_used"
            " FROM api_usage WHERE ts >= ? GROUP BY provider",
            (since,),
        )

    def today(self) -> list[dict]:
        return self.db.query(
            "SELECT provider, COUNT(*) AS requests, SUM(ok) AS ok, SUM(COALESCE(characters,0)) AS characters,"
            " SUM(COALESCE(input_tokens,0) + COALESCE(output_tokens,0)) AS tokens, SUM(COALESCE(cost_usd,0)) AS cost_usd"
            " FROM api_usage WHERE ts >= ? GROUP BY provider",
            (_day_start_utc(),),
        )
