"""Wires every service together. One instance per running app."""

from __future__ import annotations

import logging

import httpx

from .config import AppConfig
from .db import Database
from .events import ActivityLog, EventBus
from .integrations.base import HealthResult
from .integrations.fish_audio import FishAudioClient
from .integrations.groq import GroqClient
from .integrations.kokoro_tts import KokoroTTS
from .integrations.research import TavilyResearch, WikipediaResearch
from .integrations.video.comfyui import ComfyUIAdapter
from .integrations.video.draft import DraftAdapter
from .integrations.video.workflows import WorkflowLibrary
from .jobs.repo import JobRepo
from .logging_setup import setup_logging
from .media.ffmpeg import FFmpeg
from .pipeline.projects import ProjectStore
from .secrets_store import SecretStore
from .settings import SettingsService

log = logging.getLogger(__name__)


class Services:
    def __init__(
        self,
        config: AppConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        use_keyring: bool = True,
        ffmpeg: FFmpeg | None = None,
        configure_logging: bool = True,
    ):
        self.config = config
        config.ensure_dirs()
        self.db = Database(config.db_path)
        self.db.migrate()
        self.settings = SettingsService(self.db)
        self.secrets = SecretStore(config.data_dir / "secrets.json", use_keyring=use_keyring)
        if configure_logging:
            self.redactor = setup_logging(config.logs_dir, self.settings.get().general.log_level, self.secrets.all_values)
        self.bus = EventBus()
        self.activity = ActivityLog(self.db, self.bus)
        from .usage import UsageTracker

        self.usage = UsageTracker(self.db, self.settings)
        self.transport = transport
        self.groq = GroqClient(self.secrets, self.usage, transport)
        self.fish = FishAudioClient(self.secrets, self.usage, transport)
        self.kokoro = KokoroTTS(config.data_dir / "models" / "kokoro", self.usage, transport)
        self.wikipedia = WikipediaResearch(self.usage, transport)
        self.tavily = TavilyResearch(self.secrets, self.usage, transport)
        self.ffmpeg = ffmpeg or FFmpeg()
        self.workflows = WorkflowLibrary(config.bundled_workflows_dir, config.user_workflows_dir)
        self.projects = ProjectStore(self.db, config, self.settings)
        self.jobs = JobRepo(self.db)
        self.draft = DraftAdapter(self.ffmpeg)
        from .storage import StorageMover

        self.storage = StorageMover(self)
        self._comfy: ComfyUIAdapter | None = None
        self.worker = None  # set by the app (jobs.worker.Worker)
        self.orchestrator = None  # set by the app (pipeline.orchestrator.Orchestrator)

    # -- providers chosen by settings ------------------------------------------
    def comfyui(self) -> ComfyUIAdapter:
        url = self.settings.get().generation.comfyui_url
        if self._comfy is None or self._comfy.base_url != url:
            self._comfy = ComfyUIAdapter(url, self.workflows, self.transport)
        return self._comfy

    def video_adapter(self, provider: str | None = None):
        provider = provider or self.settings.get().generation.video_provider
        return self.draft if provider == "draft" else self.comfyui()

    def research_provider(self):
        t = self.settings.get().text
        if not t.research_enabled or t.research_provider == "none":
            return None
        return self.tavily if t.research_provider == "tavily" else self.wikipedia

    # -- integration health (cached in the settings table) ---------------------
    def save_health(self, name: str, result: HealthResult) -> dict:
        data = result.to_dict()
        cache = self.settings.get_value("health", {}) or {}
        cache[name] = data
        self.settings.set_value("health", cache)
        self.bus.publish("integration", name=name, status=result.status)
        return data

    def cached_health(self) -> dict:
        return self.settings.get_value("health", {}) or {}
