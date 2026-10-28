"""Path and name validation. Every filesystem path derived from user input or
model output must pass through here."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .errors import ValidationFailed

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def slugify(text: str, max_len: int = 48) -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = _SLUG_STRIP.sub("-", norm.lower()).strip("-")[:max_len].strip("-")
    if not slug or slug in _WINDOWS_RESERVED:
        slug = f"project-{slug}" if slug else "project"
    return slug


def safe_filename(name: str, max_len: int = 80) -> str:
    """A filename safe on Windows and POSIX. Keeps the extension."""
    name = name.replace("\\", "/").split("/")[-1]
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = slugify(stem, max_len) if stem else "file"
    ext = re.sub(r"[^a-z0-9]", "", ext.lower())[:8]
    return f"{stem}.{ext}" if ext else stem


def ensure_within(base: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and require it to sit inside ``base``."""
    base_r = base.resolve()
    cand_r = candidate.resolve()
    if cand_r != base_r and base_r not in cand_r.parents:
        raise ValidationFailed("Path is outside the allowed directory.", detail=str(candidate))
    return cand_r


def safe_join(base: Path, relative: str) -> Path:
    """Join a user-supplied relative path onto ``base`` without escaping it."""
    if not relative or "\x00" in relative:
        raise ValidationFailed("Invalid path.")
    rel = Path(relative.replace("\\", "/"))
    # ':' catches Windows drive letters and NTFS alternate data streams on any OS.
    if rel.is_absolute() or rel.drive or any(part == ".." or ":" in part for part in rel.parts):
        raise ValidationFailed("Invalid path.", detail=relative)
    return ensure_within(base, base / rel)


MEDIA_EXTENSIONS = {
    ".mp4", ".webm", ".mov", ".mkv",
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac",
    ".png", ".jpg", ".jpeg", ".webp",
    ".srt", ".ass", ".json", ".txt", ".md",
}

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
