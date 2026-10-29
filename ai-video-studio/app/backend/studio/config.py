"""Process-level configuration: where things live and how the server binds.

Everything user-tunable at runtime lives in the settings service instead.
These values come from environment variables (optionally loaded from
``config/studio.env``) because they must be known before the database opens.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    # Installed desktop build (PyInstaller): bundled files sit next to the code
    # in the read-only install folder; user data goes to %LOCALAPPDATA%.
    REPO_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    # ai-video-studio/app/backend/studio/config.py -> ai-video-studio/
    REPO_ROOT = Path(__file__).resolve().parents[3]


def default_home() -> Path:
    if FROZEN:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        return Path(base) / "AI Video Studio"
    return REPO_ROOT


def _load_env_file(path: Path) -> None:
    """Minimal KEY=VALUE loader. Existing environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class AppConfig:
    home: Path
    host: str = "127.0.0.1"
    port: int = 8765
    dev: bool = False
    extra_allowed_hosts: list[str] = field(default_factory=list)

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "studio.db"

    @property
    def default_projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def library_dir(self) -> Path:
        return self.data_dir / "library"

    @property
    def music_dir(self) -> Path:
        return self.data_dir / "music"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def user_workflows_dir(self) -> Path:
        return self.data_dir / "workflows"

    # Code-relative paths: these ship with the app, independent of STUDIO_HOME.
    @property
    def bundled_workflows_dir(self) -> Path:
        return REPO_ROOT / "config" / "workflows"

    @property
    def frontend_dist(self) -> Path:
        return REPO_ROOT / "app" / "frontend" / "dist"

    def ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.logs_dir,
            self.default_projects_dir,
            self.library_dir,
            self.music_dir,
            self.cache_dir,
            self.user_workflows_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


def load_config(home: Path | None = None) -> AppConfig:
    home = Path(home or os.environ.get("STUDIO_HOME") or default_home()).resolve()
    _load_env_file(home / "config" / "studio.env")
    if home != REPO_ROOT:
        _load_env_file(REPO_ROOT / "config" / "studio.env")
    host = os.environ.get("STUDIO_HOST", "127.0.0.1")
    port = int(os.environ.get("STUDIO_PORT", "8765"))
    extra = [h.strip() for h in os.environ.get("STUDIO_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return AppConfig(
        home=home,
        host=host,
        port=port,
        dev=os.environ.get("STUDIO_DEV") == "1",
        extra_allowed_hosts=extra,
    )
