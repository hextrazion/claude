"""Research providers: fetch source text the scriptwriter can cite.

* ``wikipedia`` - MediaWiki API, free, no key. Good for well-established facts.
* ``tavily``    - web search API, needs a key (free tier available).

Providers only *retrieve*. Claims are classified later against what was
actually retrieved; nothing is labelled verified without sources.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import quote, urlparse

import httpx

from .. import __version__
from ..errors import NotConfigured, ProviderError
from ..secrets_store import SecretStore
from ..usage import UsageTracker
from .base import HealthResult, Timer, network_error, raise_for_status

USER_AGENT = f"AIVideoStudio/{__version__} (personal research tool; local app)"


@dataclass
class Source:
    id: str
    title: str
    url: str
    snippet: str
    provider: str

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.lower().removeprefix("www.")

    def to_dict(self) -> dict:
        return {**asdict(self), "domain": self.domain}


class WikipediaResearch:
    name = "wikipedia"
    API = "https://en.wikipedia.org/w/api.php"

    def __init__(self, usage: UsageTracker, transport: httpx.AsyncBaseTransport | None = None):
        self.usage = usage
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=20, transport=self.transport)

    async def search(self, query: str, limit: int = 3) -> list[Source]:
        async with self._client() as client:
            with Timer() as t:
                try:
                    resp = await client.get(
                        self.API,
                        params={"action": "query", "list": "search", "srsearch": query[:200], "srlimit": limit,
                                "format": "json", "formatversion": 2},
                    )
                    raise_for_status(resp, "Wikipedia")
                    titles = [r["title"] for r in resp.json().get("query", {}).get("search", [])]
                    if not titles:
                        return []
                    resp = await client.get(
                        self.API,
                        params={"action": "query", "prop": "extracts", "explaintext": 1, "exchars": 3500,
                                "titles": "|".join(titles), "format": "json", "formatversion": 2, "redirects": 1},
                    )
                    raise_for_status(resp, "Wikipedia")
                except httpx.HTTPError as exc:
                    self.usage.record("wikipedia", "search", ok=False, error=repr(exc))
                    raise network_error("Wikipedia", exc) from exc
        self.usage.record("wikipedia", "search", ok=True, duration_ms=t.ms)
        pages = resp.json().get("query", {}).get("pages", [])
        out = []
        for p in pages:
            extract = (p.get("extract") or "").strip()
            if not extract:
                continue
            title = p.get("title", "")
            out.append(Source(
                id="", title=title, url=f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                snippet=extract, provider="wikipedia",
            ))
        return out

    async def test(self) -> HealthResult:
        try:
            results = await self.search("Rayleigh scattering", limit=1)
        except ProviderError as exc:
            return HealthResult("error", exc.message, detail=exc.detail)
        return HealthResult("ok" if results else "warning", "Wikipedia API reachable." if results else "No results returned.")


class TavilyResearch:
    name = "tavily"
    URL = "https://api.tavily.com/search"

    def __init__(self, secrets: SecretStore, usage: UsageTracker, transport: httpx.AsyncBaseTransport | None = None):
        self.secrets = secrets
        self.usage = usage
        self.transport = transport

    async def search(self, query: str, limit: int = 4) -> list[Source]:
        key = self.secrets.get("tavily")
        if not key:
            raise NotConfigured("tavily", "Tavily API key is not configured.")
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            with Timer() as t:
                try:
                    resp = await client.post(
                        self.URL,
                        headers={"Authorization": f"Bearer {key}"},
                        json={"query": query[:300], "max_results": limit, "search_depth": "basic", "include_answer": False},
                    )
                except httpx.HTTPError as exc:
                    self.usage.record("tavily", "search", ok=False, error=repr(exc))
                    raise network_error("Tavily", exc) from exc
        self.usage.record("tavily", "search", ok=resp.is_success, status_code=resp.status_code, duration_ms=t.ms)
        raise_for_status(resp, "Tavily")
        return [
            Source(id="", title=r.get("title", ""), url=r.get("url", ""), snippet=(r.get("content") or "")[:3000],
                   provider="tavily")
            for r in resp.json().get("results", [])
            if r.get("url")
        ]

    async def test(self) -> HealthResult:
        if not self.secrets.get("tavily"):
            return HealthResult("not_configured", "Optional. Add a Tavily key for web search research.")
        try:
            await self.search("speed of light", limit=1)
        except ProviderError as exc:
            return HealthResult("error", exc.message, detail=exc.detail)
        return HealthResult("ok", "Connected.")
