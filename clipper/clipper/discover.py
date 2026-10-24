"""Find source videos for a streamer/topic: Twitch top clips (official API) or YouTube search (yt-dlp)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

from .media import MediaError
from .spec import JobSpec

PERIOD_DAYS = {"week": 7, "month": 30, "year": 365}


@dataclass
class Candidate:
    url: str
    title: str = ""
    credit: str = ""
    duration: float = 0.0
    views: int = 0
    platform: str = ""


def _default_runner(cmd: List[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except FileNotFoundError as e:
        raise MediaError("yt-dlp is not installed: pip install yt-dlp") from e
    except subprocess.CalledProcessError as e:
        raise MediaError(f"yt-dlp search failed: {(e.stderr or '')[-400:]}") from e


def search_youtube(query: str, limit: int = 4, runner: Optional[Callable[[List[str]], str]] = None) -> List[Candidate]:
    """Search "<query> funny moments"; keep videos long enough to contain several moments."""
    exe = shutil.which("yt-dlp")
    base = [exe] if exe else [sys.executable, "-m", "yt_dlp"]
    out = (runner or _default_runner)(base + ["--flat-playlist", "--dump-json", f"ytsearch{limit * 4}:{query} funny moments"])
    found: List[Candidate] = []
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        dur = float(e.get("duration") or 0)
        if not (120 <= dur <= 5400):
            continue
        url = e.get("webpage_url") or e.get("url") or ""
        if not url.startswith("http") and e.get("id"):
            url = f"https://www.youtube.com/watch?v={e['id']}"
        found.append(Candidate(url=url, title=e.get("title", ""), duration=dur, views=int(e.get("view_count") or 0),
                               credit=f"YouTube: {e.get('channel') or e.get('uploader') or 'unknown'}", platform="youtube"))
    return found[:limit]


def _http(method: str, url: str, headers: Optional[dict] = None, data: Optional[dict] = None) -> dict:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # network, HTTP error or bad JSON: all mean "Twitch lookup failed"
        raise MediaError(f"Twitch API request failed: {e}") from e


def twitch_clips(login: str, period: str, limit: int, client_id: str, secret: str,
                 http: Callable[..., dict] = _http, now: Optional[datetime] = None) -> List[Candidate]:
    """Top clips (by views) for a channel. Viewers clipping a moment is a strong 'this was funny' signal."""
    tok = http("POST", "https://id.twitch.tv/oauth2/token",
               data={"client_id": client_id, "client_secret": secret, "grant_type": "client_credentials"})
    h = {"Authorization": f"Bearer {tok['access_token']}", "Client-Id": client_id}
    q = urllib.parse.quote(login.strip().replace(" ", ""))
    users = http("GET", f"https://api.twitch.tv/helix/users?login={q}", headers=h).get("data", [])
    if not users:
        raise MediaError(f'no Twitch channel named "{login}"')
    params = {"broadcaster_id": users[0]["id"], "first": "100"}
    if period in PERIOD_DAYS:
        now = now or datetime.now(timezone.utc)
        params["started_at"] = (now - timedelta(days=PERIOD_DAYS[period])).strftime("%Y-%m-%dT%H:%M:%SZ")
        params["ended_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")   # the API defaults this to started_at + 1 week
    clips = http("GET", "https://api.twitch.tv/helix/clips?" + urllib.parse.urlencode(params), headers=h).get("data", [])
    clips.sort(key=lambda c: -int(c.get("view_count") or 0))
    return [Candidate(url=c["url"], title=c.get("title", ""), duration=float(c.get("duration") or 0),
                      views=int(c.get("view_count") or 0), platform="twitch",
                      credit=f"Twitch: {c.get('broadcaster_name', login)}" +
                             (f" (clip by {c['creator_name']})" if c.get("creator_name") else ""))
            for c in clips[:limit]]


def find_sources(spec: JobSpec, env=None, runner=None, http=None) -> Tuple[List[Candidate], List[str]]:
    """Returns (candidates, notes). Explicit URLs win; otherwise search by spec.platform."""
    env = os.environ if env is None else env
    notes: List[str] = []
    if spec.urls:
        return [Candidate(url=u, platform="url") for u in spec.urls], notes
    cid, sec = env.get("TWITCH_CLIENT_ID", ""), env.get("TWITCH_CLIENT_SECRET", "")
    platform = spec.platform
    if platform == "auto":
        platform = "twitch" if (cid and sec) else "youtube"
        if platform == "youtube":
            notes.append("No Twitch API keys set (TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET), so I searched YouTube.")
    if platform == "twitch":
        if not (cid and sec):
            raise MediaError("Twitch search needs a free API key: set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET "
                             "(create an app at dev.twitch.tv/console), or ask for YouTube instead.")
        try:
            kw = {"http": http} if http else {}
            cands = twitch_clips(spec.query, spec.period, min(spec.count * 3, 15), cid, sec, **kw)
        except MediaError as e:
            raise MediaError(str(e)) from e
        if not cands:
            notes.append(f'No Twitch clips for "{spec.query}" in the last {spec.period}; try a longer period.')
        return cands, notes
    return search_youtube(spec.query, min(max(2, spec.count // 2 + 1), 5), runner), notes
