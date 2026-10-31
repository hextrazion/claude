"""Kokoro text-to-speech: free, open-source (Apache 2.0) narration that runs on this PC.

Uses the ``kokoro-onnx`` runtime with the int8 Kokoro v1.0 model (~110 MB) and
its voice pack (~28 MB). The files are downloaded once into data/models/kokoro;
after that narration works offline with no account, key or per-use cost.
Synthesis runs on the CPU, so it never competes with ComfyUI for VRAM.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import wave
from pathlib import Path

import httpx

from ..errors import ProviderError
from ..usage import UsageTracker
from .base import HealthResult, Timer

log = logging.getLogger(__name__)

# ONNX Runtime (1.31+) sends usage telemetry to Microsoft about 20 s after a model
# loads, and disable_telemetry_events() does not stop it; this variable does.
# Must be set before the runtime library initialises, i.e. at import time here.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
FILES = {
    # name: minimum plausible size in bytes (guards against truncated or error-page downloads)
    "kokoro-v1.0.int8.onnx": 80_000_000,
    "voices-v1.0.bin": 20_000_000,
}
DOWNLOAD_MB = 140
SAMPLE_RATE = 24000

_ACCENT = {"a": "American", "b": "British"}
_GENDER = {"f": "female", "m": "male"}
# Voices Kokoro's authors grade highest for English; shown first.
RECOMMENDED = ["af_heart", "af_bella", "am_michael", "am_fenrir", "bf_emma", "bm_george", "am_puck", "af_nicole"]


def describe_voice(voice_id: str) -> dict:
    prefix, _, name = voice_id.partition("_")
    accent = _ACCENT.get(prefix[:1], prefix[:1].upper())
    gender = _GENDER.get(prefix[1:2], "")
    return {
        "id": voice_id,
        "name": name.capitalize(),
        "accent": accent,
        "gender": gender,
        "label": f"{name.capitalize()} ({accent} {gender})".strip(),
        "recommended": voice_id in RECOMMENDED,
    }


def _log_download_result(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:  # the state dict already carries a user-facing message
        log.warning("voice model download failed: %s", getattr(exc, "message", exc))


class KokoroTTS:
    name = "kokoro"

    def __init__(self, models_dir: Path, usage: UsageTracker, transport: httpx.AsyncBaseTransport | None = None):
        self.dir = models_dir
        self.usage = usage
        self.transport = transport
        self._engine = None
        self._engine_lock = threading.Lock()
        self.download_state: dict = {"status": "idle", "received": 0, "total": 0, "error": None}
        self._download_task: asyncio.Task | None = None

    # -- model files ------------------------------------------------------------
    def installed(self) -> bool:
        return all((self.dir / f).is_file() and (self.dir / f).stat().st_size >= size for f, size in FILES.items())

    def status(self) -> dict:
        return {"installed": self.installed(), "download": dict(self.download_state), "download_mb": DOWNLOAD_MB,
                "folder": str(self.dir)}

    def start_download(self) -> dict:
        if self.installed():
            return self.status()
        if not (self._download_task and not self._download_task.done()):
            self._download_task = asyncio.get_running_loop().create_task(self.download())
            self._download_task.add_done_callback(_log_download_result)
        return self.status()

    async def download(self, on_progress=None) -> None:
        """Download the model files (resumable per file: finished files are kept)."""
        if self.installed():
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        st = self.download_state
        st.update(status="downloading", received=0, total=0, error=None)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=120), follow_redirects=True,
                                         transport=self.transport) as client:
                for fname, min_size in FILES.items():
                    dest = self.dir / fname
                    if dest.is_file() and dest.stat().st_size >= min_size:
                        continue
                    part = dest.with_suffix(dest.suffix + ".part")
                    async with client.stream("GET", f"{RELEASE}/{fname}") as resp:
                        if not resp.is_success:
                            raise ProviderError(f"Could not download the voice model ({fname}): HTTP {resp.status_code}.",
                                                kind="transient", provider="kokoro")
                        st["total"] += int(resp.headers.get("content-length") or min_size)
                        with part.open("wb") as fh:
                            async for chunk in resp.aiter_bytes(1 << 20):
                                fh.write(chunk)
                                st["received"] += len(chunk)
                                if on_progress and st["total"]:
                                    await on_progress(st["received"] / st["total"])
                    if part.stat().st_size < min_size:
                        part.unlink(missing_ok=True)
                        raise ProviderError("The voice model download was incomplete. Try again.", kind="transient",
                                            provider="kokoro")
                    part.replace(dest)
        except httpx.HTTPError as exc:
            st.update(status="error", error="Download failed. Check your internet connection and try again.")
            raise ProviderError("Could not download the voice model. Check your internet connection.",
                                kind="unavailable", detail=repr(exc), provider="kokoro") from exc
        except ProviderError as exc:
            st.update(status="error", error=exc.message)
            raise
        st.update(status="done")

    # -- synthesis ------------------------------------------------------------------
    def _load(self):
        with self._engine_lock:
            if self._engine is None:
                try:
                    import onnxruntime

                    onnxruntime.disable_telemetry_events()  # belt and braces with ORT_DISABLE_TELEMETRY
                    from kokoro_onnx import Kokoro
                except ImportError as exc:
                    raise ProviderError("The local voice engine is not installed (pip install kokoro-onnx).",
                                        kind="not_configured", provider="kokoro") from exc
                self._engine = Kokoro(str(self.dir / "kokoro-v1.0.int8.onnx"), str(self.dir / "voices-v1.0.bin"))
            return self._engine

    def voices(self) -> list[dict]:
        if not self.installed():
            ids = RECOMMENDED
        else:
            ids = [v for v in self._load().get_voices() if v[:1] in _ACCENT]
        out = [describe_voice(v) for v in ids]
        return sorted(out, key=lambda v: (not v["recommended"], v["accent"], v["gender"], v["name"]))

    def _synth_sync(self, text: str, out_path: Path, voice: str, speed: float) -> float:
        engine = self._load()
        if voice not in engine.get_voices():
            raise ProviderError(f"Voice '{voice}' is not in the Kokoro voice pack. Pick another voice.",
                                kind="invalid_request", provider="kokoro")
        samples, sr = engine.create(text, voice=voice, speed=speed, lang="en-gb" if voice.startswith("b") else "en-us")
        import numpy as np

        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(out_path.suffix + ".part")
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm)
        tmp.replace(out_path)
        return len(samples) / sr

    async def synthesize(self, text: str, out_path: Path, *, voice: str, speed: float = 1.0,
                         project_id: int | None = None, on_progress=None) -> dict:
        if not self.installed():
            await self.download(on_progress=on_progress)
        with Timer() as t:
            try:
                seconds = await asyncio.to_thread(self._synth_sync, text, out_path, voice, speed)
            except ProviderError:
                raise
            except Exception as exc:
                self.usage.record("kokoro", "tts", ok=False, error=repr(exc)[:300], project_id=project_id)
                raise ProviderError("The local voice engine failed while generating narration.", kind="permanent",
                                    detail=repr(exc), provider="kokoro") from exc
        self.usage.record("kokoro", "tts", ok=True, model="kokoro-v1.0-int8", characters=len(text),
                          duration_ms=t.ms, project_id=project_id)
        return {"path": str(out_path), "characters": len(text), "seconds": seconds, "model": "kokoro-v1.0",
                "cost_usd": 0.0}

    async def test(self) -> HealthResult:
        if not self.installed():
            state = self.download_state
            if state["status"] == "downloading":
                return HealthResult("warning", "Downloading the voice model…")
            return HealthResult("not_configured", f"Free local voice ready to install: one-time {DOWNLOAD_MB} MB download.")
        try:
            await asyncio.to_thread(self._load)
        except Exception as exc:
            return HealthResult("error", "The voice model is downloaded but could not be loaded.", detail=repr(exc))
        return HealthResult("ok", "Free local voice ready. Runs on your CPU, no account needed.")
