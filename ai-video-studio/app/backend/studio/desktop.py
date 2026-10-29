"""Desktop launcher used by the installed Windows app.

Starts the backend in a background thread, opens the studio in its own
window (Edge/Chrome "app" mode, falling back to the default browser) and
keeps a system-tray icon with Open / Open data folder / Quit. Closing the
window leaves the studio running in the tray, so queued generations carry on;
Quit stops it. Starting it a second time just opens the window again.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = "AI Video Studio"
log = logging.getLogger(__name__)


def _ensure_streams(logs_dir: Path) -> None:
    """Windowed executables have no console; give stdout/stderr somewhere to go."""
    if sys.stdout is None or sys.stderr is None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        stream = open(logs_dir / "desktop.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream


def make_icon_image(size: int = 256):
    """The app icon (purple rounded square with a play triangle), drawn with Pillow."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 4, fill=(109, 94, 252, 255))
    s = size
    d.polygon([(s * 0.38, s * 0.28), (s * 0.38, s * 0.72), (s * 0.74, s * 0.50)], fill=(255, 255, 255, 255))
    return img


def _studio_running(url: str) -> bool:
    import httpx

    try:
        r = httpx.get(f"{url}/api/health", timeout=1.5)
        return r.status_code == 200 and r.json().get("ok") is True
    except Exception:
        return False


def _app_browser() -> list[str] | None:
    candidates = []
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates += [
                Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe",
            ]
    for c in candidates:
        if c.is_file():
            return [str(c)]
    for name in ("msedge", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return [found]
    return None


def open_window(url: str) -> None:
    browser = _app_browser()
    if browser:
        try:
            subprocess.Popen([*browser, f"--app={url}", "--window-size=1440,920"])
            return
        except OSError:
            pass
    webbrowser.open(url)


def _message(text: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10)
    else:
        print(text, file=sys.stderr)


def _open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def main() -> int:
    from .config import load_config

    config = load_config()
    _ensure_streams(config.logs_dir)
    url = f"http://127.0.0.1:{config.port}"

    if _studio_running(url):  # already running (e.g. in the tray): just show it
        open_window(url)
        return 0

    import uvicorn

    from .main import create_app

    try:
        app = create_app(config)
    except Exception as exc:  # pragma: no cover - shown to the user
        logging.getLogger(__name__).exception("start-up failed")
        _message(f"{APP_NAME} could not start:\n\n{exc}\n\nDetails: {config.logs_dir / 'studio.log'}")
        return 1
    server = uvicorn.Server(uvicorn.Config(app, host=config.host, port=config.port, log_config=None, log_level="warning"))
    thread = threading.Thread(target=server.run, name="studio-server", daemon=True)
    thread.start()

    deadline = time.time() + 60
    while not server.started:
        if not thread.is_alive() or time.time() > deadline:
            _message(
                f"{APP_NAME} could not start its local server on port {config.port}.\n"
                f"Another program may be using it. Details: {config.logs_dir / 'studio.log'}"
            )
            return 1
        time.sleep(0.2)

    if not os.environ.get("STUDIO_NO_WINDOW"):
        open_window(url)

    def quit_app(icon=None) -> None:
        server.should_exit = True
        if icon is not None:
            icon.stop()

    try:
        if os.environ.get("STUDIO_NO_TRAY"):
            raise RuntimeError("tray disabled")
        import pystray

        icon = pystray.Icon(
            "ai-video-studio",
            make_icon_image(64),
            APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("Open AI Video Studio", lambda: open_window(url), default=True),
                pystray.MenuItem("Open data folder", lambda: _open_folder(config.home)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit (stops queued work)", lambda icon_, item: quit_app(icon_)),
            ),
        )
        icon.run()  # blocks until Quit
    except Exception as exc:
        log.info("no tray icon (%s); running until the server stops", exc)
        try:
            while thread.is_alive():
                thread.join(0.5)
        except KeyboardInterrupt:
            quit_app()
    server.should_exit = True
    thread.join(timeout=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
