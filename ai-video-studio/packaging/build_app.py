"""Builds the desktop app folder with PyInstaller (dist/AI Video Studio/).

Run from anywhere after the web UI has been built (app/frontend/dist) and,
on Windows, after FFmpeg has been placed in tools/ffmpeg/bin.
"""

import os
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
SEP = os.pathsep  # PyInstaller --add-data separator
exe = ".exe" if sys.platform == "win32" else ""

if not (ROOT / "app" / "frontend" / "dist" / "index.html").is_file():
    sys.exit("Build the web UI first: cd app/frontend && npm ci && npm run build")

args = [
    str(ROOT / "packaging" / "entry.py"),
    "--name", "AI Video Studio",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build" / "pyinstaller"),
    "--specpath", str(ROOT / "build"),
    "--paths", str(ROOT / "app" / "backend"),
    "--collect-submodules", "studio",
    "--collect-submodules", "uvicorn",
    "--hidden-import", "keyring.backends.Windows",
    "--add-data", f"{ROOT / 'app' / 'frontend' / 'dist'}{SEP}app/frontend/dist",
    "--add-data", f"{ROOT / 'config' / 'workflows'}{SEP}config/workflows",
    "--add-data", f"{ROOT / 'app' / 'backend' / 'studio' / 'db' / 'migrations'}{SEP}studio/db/migrations",
]
icon = ROOT / "packaging" / "icon.ico"
if icon.is_file():
    args += ["--icon", str(icon)]
ffmpeg_dir = ROOT / "tools" / "ffmpeg" / "bin"
for tool in ("ffmpeg", "ffprobe"):
    f = ffmpeg_dir / f"{tool}{exe}"
    if f.is_file():
        args += ["--add-binary", f"{f}{SEP}tools/ffmpeg/bin"]
    else:
        print(f"warning: {f} not found; the app will look for FFmpeg on PATH")

PyInstaller.__main__.run(args)
