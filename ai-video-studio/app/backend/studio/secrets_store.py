"""API key storage.

Order of precedence when reading a secret:

1. Environment variable (e.g. ``GROQ_API_KEY``) - handy for servers/CI.
2. The OS credential store via ``keyring`` (Windows Credential Manager on
   Windows, Keychain on macOS, Secret Service on Linux desktops).
3. Fallback file ``data/secrets.json`` with owner-only permissions, used only
   when no OS credential store is available (e.g. a headless Linux homelab).

Secrets never leave the backend. The API only ever returns masked values.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)

SERVICE = "ai-video-studio"

SECRET_ENV = {
    "groq": "GROQ_API_KEY",
    "fish_audio": "FISH_AUDIO_API_KEY",
    "tavily": "TAVILY_API_KEY",
}


def mask(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}••••{value[-4:]}"


class SecretStore:
    def __init__(self, fallback_file: Path, use_keyring: bool = True):
        self.fallback_file = fallback_file
        self._lock = threading.Lock()
        self._keyring = None
        if use_keyring:
            try:
                import keyring
                from keyring.backends import fail

                backend = keyring.get_keyring()
                if not isinstance(backend, fail.Keyring) and "fail" not in type(backend).__module__:
                    self._keyring = keyring
            except Exception:  # pragma: no cover - depends on platform
                self._keyring = None
        self.backend_name = (
            type(self._keyring.get_keyring()).__name__ if self._keyring else "file (restricted permissions)"
        )
        self._listeners: list = []

    def on_change(self, fn) -> None:
        self._listeners.append(fn)

    # -- public API ------------------------------------------------------------
    def get(self, name: str) -> str | None:
        env = SECRET_ENV.get(name)
        if env and os.environ.get(env):
            return os.environ[env].strip()
        if self._keyring:
            try:
                value = self._keyring.get_password(SERVICE, name)
                if value:
                    return value
            except Exception as exc:  # pragma: no cover
                log.warning("credential store read failed for %s: %s", name, type(exc).__name__)
        return self._file_read().get(name)

    def source(self, name: str) -> str | None:
        env = SECRET_ENV.get(name)
        if env and os.environ.get(env):
            return f"environment variable {env}"
        if self._keyring:
            try:
                if self._keyring.get_password(SERVICE, name):
                    return "OS credential store"
            except Exception:  # pragma: no cover
                pass
        if name in self._file_read():
            return "local secrets file"
        return None

    def set(self, name: str, value: str) -> None:
        value = value.strip()
        if not value:
            raise ValueError("empty secret")
        if self._keyring:
            try:
                self._keyring.set_password(SERVICE, name, value)
                self._file_delete(name)
                self._notify(name)
                return
            except Exception as exc:  # pragma: no cover
                log.warning("credential store write failed (%s); using file fallback", type(exc).__name__)
        data = self._file_read()
        data[name] = value
        self._file_write(data)
        self._notify(name)

    def delete(self, name: str) -> None:
        if self._keyring:
            try:
                self._keyring.delete_password(SERVICE, name)
            except Exception:
                pass
        self._file_delete(name)
        self._notify(name)

    def masked(self, name: str) -> str | None:
        return mask(self.get(name))

    def all_values(self) -> list[str]:
        """Every stored secret, for log redaction."""
        return [v for v in (self.get(n) for n in SECRET_ENV) if v]

    # -- file fallback -------------------------------------------------------
    def _notify(self, name: str) -> None:
        for fn in self._listeners:
            try:
                fn(name)
            except Exception:  # pragma: no cover
                pass

    def _file_read(self) -> dict:
        with self._lock:
            if not self.fallback_file.is_file():
                return {}
            try:
                return json.loads(self.fallback_file.read_text(encoding="utf-8"))
            except Exception:
                return {}

    def _file_write(self, data: dict) -> None:
        with self._lock:
            self.fallback_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.fallback_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:  # pragma: no cover - Windows ignores POSIX modes
                pass
            os.replace(tmp, self.fallback_file)

    def _file_delete(self, name: str) -> None:
        data = self._file_read()
        if name in data:
            del data[name]
            self._file_write(data)
