"""Fetch videos from Twitch/YouTube/etc. with yt-dlp. Local files pass straight through."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Tuple

from .media import MediaError


def is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def fetch(url: str, dest_dir: str) -> Tuple[str, dict]:
    """Download `url` into dest_dir; returns (file_path, info) where info has credit/url/title."""
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    exe = shutil.which("yt-dlp")
    cmd = [exe] if exe else [sys.executable, "-m", "yt_dlp"]
    cmd += ["-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
            "-o", str(Path(dest_dir) / "%(id)s.%(ext)s"), "--no-playlist", "--print-json", "--no-simulate", url]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except FileNotFoundError as e:
        raise MediaError("yt-dlp is not installed: pip install yt-dlp") from e
    except subprocess.CalledProcessError as e:
        raise MediaError(f"yt-dlp failed: {(e.stderr or '')[-600:]}") from e
    info = json.loads(out.strip().splitlines()[-1])
    path = (info.get("requested_downloads") or [{}])[0].get("filepath") or info.get("_filename")
    if not path or not Path(path).exists():
        raise MediaError("yt-dlp finished but the output file was not found")
    site = (info.get("extractor_key") or "web")
    who = info.get("uploader") or info.get("channel") or ""
    return path, {"url": info.get("webpage_url", url), "title": info.get("title", ""),
                  "credit": f"{site}: {who}".strip(": ")}
