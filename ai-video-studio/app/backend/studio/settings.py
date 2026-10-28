"""Typed, persisted application settings.

Stored as one JSON document in the ``settings`` table. Updates are deep-merged
onto the current value and re-validated, so a partial PATCH from the UI can
never leave an invalid configuration behind.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .db import Database, dumps, loads, utcnow

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class _Section(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class GeneralSettings(_Section):
    automation_mode: Literal["manual", "supervised", "automated"] = "supervised"
    default_niche: str = Field("science, history, psychology, space and everyday mysteries", max_length=300)
    tone: str = Field("curious, clear and confident; no hype", max_length=200)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class VideoSettings(_Section):
    duration_s: int = Field(35, ge=5, le=180)
    min_duration_s: int = Field(15, ge=3, le=180)
    max_duration_s: int = Field(60, ge=5, le=300)
    aspect_ratio: Literal["9:16", "16:9", "1:1", "4:5"] = "9:16"
    width: int = Field(1080, ge=240, le=3840)
    height: int = Field(1920, ge=240, le=3840)
    fps: int = Field(30, ge=12, le=60)
    fit_mode: Literal["crop", "blur_pad", "black_pad"] = "crop"
    transition: Literal["cut", "fade", "dissolve", "slideup"] = "fade"
    transition_s: float = Field(0.3, ge=0, le=1.5)
    tail_padding_s: float = Field(0.6, ge=0, le=3)
    max_stretch: float = Field(1.35, ge=1.0, le=2.0, description="Max slow-down factor before freezing the last frame")
    crf: int = Field(19, ge=12, le=30)

    @model_validator(mode="after")
    def _check(self):
        if self.min_duration_s > self.max_duration_s:
            raise ValueError("min_duration_s must be <= max_duration_s")
        if self.width % 2 or self.height % 2:
            raise ValueError("width and height must be even numbers (H.264 requirement)")
        return self


class TextSettings(_Section):
    provider: Literal["groq"] = "groq"
    model_quality: str = "llama-3.3-70b-versatile"
    model_fast: str = "llama-3.1-8b-instant"
    temperature: float = Field(0.8, ge=0, le=2)
    research_enabled: bool = True
    research_provider: Literal["none", "wikipedia", "tavily"] = "wikipedia"


class GenerationSettings(_Section):
    video_provider: Literal["comfyui", "draft"] = "comfyui"
    comfyui_url: str = "http://127.0.0.1:8188"
    video_workflow: str = "wan22_ti2v_5b_t2v"
    i2v_workflow: str = "wan22_ti2v_5b_i2v"
    image_workflow: str = ""
    use_image_stage: bool = False
    style_preset: str = Field(
        "polished stylised 3D animation, soft global illumination, clean shapes, vibrant but natural colours, "
        "educational explainer look",
        max_length=500,
    )
    negative_prompt: str = Field(
        "blurry, low quality, distorted, deformed, watermark, text, subtitles, logo, jpeg artifacts, flicker",
        max_length=500,
    )
    seed_mode: Literal["random", "fixed"] = "random"
    fixed_seed: int = Field(42, ge=0)
    job_timeout_s: int = Field(2400, ge=60, le=6 * 3600)
    max_retries: int = Field(2, ge=0, le=10)

    @field_validator("comfyui_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not re.match(r"^https?://[A-Za-z0-9.\-\[\]:]+(:\d+)?$", v):
            raise ValueError("ComfyUI URL must look like http://127.0.0.1:8188")
        return v


class NarrationSettings(_Section):
    provider: Literal["fish_audio"] = "fish_audio"
    voice_id: str = ""
    voice_name: str = ""
    model: str = "s2-pro"
    speed: float = Field(1.0, ge=0.5, le=2.0)
    volume: float = Field(0.0, ge=-20, le=20)
    normalize: bool = True
    format: Literal["mp3", "wav"] = "mp3"
    alignment: Literal["auto", "whisper", "heuristic"] = "auto"
    target_lufs: float = Field(-14.0, ge=-30, le=-6)


class CaptionSettings(_Section):
    enabled: bool = True
    burn_in: bool = True
    save_srt: bool = True
    font: str = Field("Arial Black", max_length=80)
    size_pct: float = Field(6.0, ge=2, le=15, description="Font size as % of video height")
    position_pct: float = Field(30.0, ge=3, le=80, description="Distance from bottom as % of height")
    max_words: int = Field(3, ge=1, le=8)
    max_chars_per_line: int = Field(18, ge=8, le=60)
    uppercase: bool = True
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFD60A"
    outline_color: str = "#000000"
    outline_px: int = Field(6, ge=0, le=20)

    @field_validator("primary_color", "highlight_color", "outline_color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not _HEX.match(v):
            raise ValueError("colours must be #RRGGBB")
        return v.upper()

    @field_validator("font")
    @classmethod
    def _font(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z0-9 \-]+$", v):
            raise ValueError("font name may only contain letters, numbers, spaces and dashes")
        return v


class MusicSettings(_Section):
    enabled: bool = False
    file: str = Field("", description="File name inside data/music")
    volume_db: float = Field(-20.0, ge=-40, le=0)
    ducking: bool = True


class ProcessingWindow(_Section):
    enabled: bool = False
    start: str = "01:00"
    end: str = "08:00"

    @field_validator("start", "end")
    @classmethod
    def _time(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("times must be HH:MM (24h)")
        return v


class QueueSettings(_Section):
    paused: bool = False
    max_gpu_jobs: int = Field(1, ge=1, le=4)
    max_api_jobs: int = Field(2, ge=1, le=8)
    max_cpu_jobs: int = Field(1, ge=1, le=4)
    max_jobs_per_session: int = Field(0, ge=0, description="0 = unlimited")
    processing_window: ProcessingWindow = ProcessingWindow()
    window_applies_to_api: bool = False
    defer_when_gpu_busy: bool = False
    gpu_busy_threshold_pct: int = Field(50, ge=5, le=100)
    pause_when_processes: list[str] = Field(default_factory=list, max_length=50)
    min_free_disk_gb: float = Field(10.0, ge=0)

    @field_validator("pause_when_processes")
    @classmethod
    def _procs(cls, v: list[str]) -> list[str]:
        out = []
        for name in v:
            name = name.strip()
            if not name:
                continue
            if not re.match(r"^[A-Za-z0-9_.\- ]{1,80}$", name):
                raise ValueError(f"invalid process name: {name!r}")
            out.append(name)
        return out


class GateSettings(_Section):
    """Where the pipeline stops for a human. Used in supervised and automated modes."""

    script: bool = True
    scene_plan: bool = True
    assembly: bool = False


class LimitSettings(_Section):
    max_idea_batches_per_day: int = Field(20, ge=0)
    max_scripts_per_day: int = Field(25, ge=0)
    max_tts_chars_per_day: int = Field(30000, ge=0)
    max_auto_projects_per_day: int = Field(3, ge=0)


class AutomationSettings(_Section):
    auto_generate_ideas: bool = False
    idea_pool_min: int = Field(5, ge=0, le=100)
    auto_select_ideas: bool = False
    min_idea_score: float = Field(7.5, ge=0, le=10)
    max_active_projects: int = Field(2, ge=1, le=20)


class StorageSettings(_Section):
    projects_dir: str = Field("", description="Empty = data/projects")
    export_dir: str = Field("", description="Empty = data/library")
    low_disk_warning_gb: float = Field(30.0, ge=0)
    keep_work_files_days: int = Field(14, ge=0)


class PricingSettings(_Section):
    """Used only for cost estimates. Verify against the providers' pricing pages."""

    groq_usd_per_m_tokens: dict[str, list[float]] = Field(
        default_factory=lambda: {
            "llama-3.3-70b-versatile": [0.59, 0.79],
            "llama-3.1-8b-instant": [0.05, 0.08],
            "openai/gpt-oss-120b": [0.15, 0.75],
            "openai/gpt-oss-20b": [0.10, 0.50],
        }
    )
    groq_free_tier: bool = True
    fish_usd_per_m_chars: float = Field(15.0, ge=0)


class Settings(_Section):
    general: GeneralSettings = GeneralSettings()
    video: VideoSettings = VideoSettings()
    text: TextSettings = TextSettings()
    generation: GenerationSettings = GenerationSettings()
    narration: NarrationSettings = NarrationSettings()
    captions: CaptionSettings = CaptionSettings()
    music: MusicSettings = MusicSettings()
    queue: QueueSettings = QueueSettings()
    gates: GateSettings = GateSettings()
    limits: LimitSettings = LimitSettings()
    automation: AutomationSettings = AutomationSettings()
    storage: StorageSettings = StorageSettings()
    pricing: PricingSettings = PricingSettings()


def deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class SettingsService:
    KEY = "app"

    def __init__(self, db: Database):
        self.db = db
        self._cache: Settings | None = None

    def get(self) -> Settings:
        if self._cache is None:
            row = self.db.query_one("SELECT value FROM settings WHERE key = ?", (self.KEY,))
            stored = loads(row["value"], {}) if row else {}
            # Unknown/old keys are dropped; invalid stored values fall back to defaults per section.
            try:
                self._cache = Settings.model_validate(stored)
            except Exception:
                self._cache = _salvage(stored)
        return self._cache

    def update(self, patch: dict) -> Settings:
        merged = deep_merge(self.get().model_dump(), patch)
        new = Settings.model_validate(merged)  # raises pydantic.ValidationError
        self._save(new)
        return new

    def replace(self, settings: Settings) -> Settings:
        self._save(settings)
        return settings

    def _save(self, settings: Settings) -> None:
        self.db.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (self.KEY, dumps(settings.model_dump()), utcnow()),
        )
        self._cache = settings

    # small key/value store for internal state (e.g. cached health results)
    def get_value(self, key: str, default=None):
        row = self.db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return loads(row["value"], default) if row else default

    def set_value(self, key: str, value) -> None:
        self.db.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, dumps(value), utcnow()),
        )


def _salvage(stored: dict) -> Settings:
    base = Settings()
    data = base.model_dump()
    for name in data:
        section = stored.get(name)
        if not isinstance(section, dict):
            continue
        try:
            setattr(base, name, type(getattr(base, name)).model_validate(section))
        except Exception:
            pass
    return base
