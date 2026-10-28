"""Shared fixtures. External APIs are replaced by httpx.MockTransport routes;
FFmpeg is real, so media tests exercise actual encoding."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from studio.config import REPO_ROOT, AppConfig  # noqa: E402
from studio.services import Services  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg not installed")

HEADERS = {"X-Studio-Client": "web"}


class Router:
    """Tiny request router for httpx.MockTransport."""

    def __init__(self):
        self.routes: list[tuple[str, str, object]] = []
        self.calls: list[httpx.Request] = []

    def add(self, method: str, url_prefix: str, handler):
        self.routes.insert(0, (method, url_prefix, handler))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = str(request.url)
        for method, prefix, handler in self.routes:
            if request.method == method and url.startswith(prefix):
                return handler(request) if callable(handler) else handler
        return httpx.Response(599, json={"error": f"no mock for {request.method} {url}"})


@pytest.fixture
def router() -> Router:
    return Router()


@pytest.fixture
def home(tmp_path) -> Path:
    (tmp_path / "config").mkdir()
    shutil.copytree(REPO_ROOT / "config" / "workflows", tmp_path / "config" / "workflows")
    return tmp_path


def make_services(home: Path, router: Router | None = None) -> Services:
    cfg = AppConfig(home=home)
    transport = httpx.MockTransport(router) if router else None
    return Services(cfg, transport=transport, use_keyring=False, configure_logging=False)


@pytest.fixture
def services(home, router) -> Services:
    return make_services(home, router)


def wait_for(predicate, timeout: float = 60.0, interval: float = 0.2, message: str = "condition"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {message}; last value: {last!r}")


# -- media fixtures ---------------------------------------------------------------
@pytest.fixture(scope="session")
def speech_like_mp3(tmp_path_factory) -> Path:
    """~7.5 s of tone bursts separated by short silences, standing in for TTS output."""
    if not HAS_FFMPEG:
        pytest.skip("FFmpeg not installed")
    out = tmp_path_factory.mktemp("media") / "speech.mp3"
    expr = "if(lt(mod(t\\,2.5)\\,2.1)\\,0.4*sin(2*PI*220*t)*sin(2*PI*3*t)\\,0)"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", f"aevalsrc={expr}:s=44100:d=7.5",
         "-c:a", "libmp3lame", "-b:a", "128k", str(out)],
        check=True, capture_output=True,
    )
    return out


# -- fake providers ---------------------------------------------------------------------
SCRIPT_SEGMENTS = [
    "Why is the sky blue but sunsets are orange?",
    "Sunlight looks white, but it is a mix of every colour.",
    "Air molecules scatter short blue waves far more than long red ones.",
    "At sunset light crosses more air, so the blue is scattered away and the reds remain.",
]


def groq_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    text = " ".join(m["content"] for m in body["messages"])
    if "Pitch" in text:
        content = {"ideas": [
            {"title": "Why the sky is blue but sunsets are orange", "niche": "science",
             "central_question": "Why does the sky change colour at sunset?", "hook": "The sky is not actually blue.",
             "description": "Rayleigh scattering explained.", "appeal": "Everyone has seen it", "visual_approach": "3D atmosphere",
             "est_duration_s": 30, "research_needs": "scattering", "accuracy_concerns": "violet vs blue", "score": 8.5},
            {"title": "How octopuses taste with their arms", "niche": "biology", "central_question": "Can arms taste?",
             "hook": "This animal tastes with its hands.", "description": "Chemoreceptors.", "score": 7.9},
        ]}
    elif "Write the narration script" in text:
        content = {"title": "Why sunsets are orange",
                   "segments": [{"text": t, "purpose": "explanation", "visual_idea": "sky"} for t in SCRIPT_SEGMENTS],
                   "sources_used": [], "uncertain_claims": ["blue scatters more than red"]}
    elif "scene-by-scene" in text:
        content = {"style_bible": "soft 3D, warm palette", "scenes": [
            {"narration": SCRIPT_SEGMENTS[0], "prompt": "A blue sky turning orange", "visual_objective": "pose the question"},
            {"narration": SCRIPT_SEGMENTS[1], "prompt": "White light splitting into colours", "visual_objective": "white light is a mix"},
            # Deliberately paraphrased to exercise narration repair:
            {"narration": "Molecules scatter blue more than red.", "prompt": "Tiny molecules bouncing blue waves"},
            {"narration": SCRIPT_SEGMENTS[3], "prompt": "Long path of light through air at sunset"},
        ]}
    elif "fact-checker" in text:
        content = {"claims": [{"claim": "Blue light scatters more than red", "label": "not_checked"}]}
    elif "search queries" in text:
        content = {"queries": ["Rayleigh scattering"]}
    else:
        content = {"facts": [], "cautions": []}
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(content)}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200},
    }, headers={"x-ratelimit-remaining-requests": "999"})


def install_fake_providers(router: Router, speech: Path | None = None) -> None:
    router.add("POST", "https://api.groq.com/openai/v1/chat/completions", groq_handler)
    router.add("GET", "https://api.groq.com/openai/v1/models",
               httpx.Response(200, json={"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "llama-3.1-8b-instant"}]}))
    if speech:
        router.add("POST", "https://api.fish.audio/v1/tts", lambda r: httpx.Response(200, content=speech.read_bytes()))
    router.add("GET", "https://api.fish.audio/wallet/self/api-credit", httpx.Response(200, json={"credit": "12.5"}))
