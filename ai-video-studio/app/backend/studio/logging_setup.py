"""Logging with secret redaction.

Every handler gets a filter that replaces known secret values and anything
shaped like a bearer token or API key with ``[redacted]``.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{10,}"),  # Groq
    re.compile(r"tvly-[A-Za-z0-9\-]{10,}"),  # Tavily
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._\-]{8,}"),
]


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: Callable[[], list[str]]):
        super().__init__()
        self._secrets = secrets

    def redact(self, text: str) -> str:
        for value in self._secrets():
            if value and len(value) >= 6:
                text = text.replace(value, "[redacted]")
        for pat in _PATTERNS:
            text = pat.sub(lambda m: (m.group(1) if m.groups() else "") + "[redacted]", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        red = self.redact(msg)
        if red != msg:
            record.msg, record.args = red, None
        if record.exc_info and record.exc_info[1] is not None:
            # Render the traceback now so it can be redacted too.
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = self.redact(formatted)
            record.exc_info = None
        return True


def setup_logging(logs_dir: Path, level: str, secrets: Callable[[], list[str]]) -> RedactingFilter:
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        if getattr(h, "_studio", False):
            root.removeHandler(h)
    redactor = RedactingFilter(secrets)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(logs_dir / "studio.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    console = logging.StreamHandler()
    for h in (file_handler, console):
        h.setFormatter(fmt)
        h.addFilter(redactor)
        h._studio = True  # type: ignore[attr-defined]
        root.addHandler(h)
    # httpx logs full request URLs at INFO; keep it quieter.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return redactor
