"""Where projects and finished videos are stored, and moving them.

The user picks one "storage folder" (for example on an external SSD). New
projects go to ``<folder>/Projects`` and library copies to ``<folder>/Library``.
Existing projects can be moved there: each project folder is copied, checked,
re-pointed in the database and only then removed from the old drive, so a
failure (or an unplugged drive) never leaves a project without its files.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from .db import utcnow
from .errors import ValidationFailed
from .system_monitor import dir_size_bytes, disk_stats

log = logging.getLogger(__name__)

PROJECTS_SUBDIR = "Projects"
LIBRARY_SUBDIR = "Library"


def validate_location(raw: str) -> Path:
    """An absolute, writable folder. Created if missing (its drive must exist)."""
    raw = (raw or "").strip().strip('"')
    if not raw:
        raise ValidationFailed("Choose a folder.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValidationFailed("Use a full folder path, for example E:\\AI Video Studio.")
    anchor = Path(path.anchor) if path.anchor else None
    if anchor is not None and not anchor.exists():
        raise ValidationFailed(f"The drive {path.anchor} is not available. Is the external drive plugged in?")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{uuid.uuid4().hex[:8]}"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise ValidationFailed(f"The studio can't write to {path}. Pick another folder or check the drive.",
                               detail=str(exc)) from exc
    return path.resolve()


def windows_picker_script(initial: str | None) -> str:
    """PowerShell that shows the standard folder picker on top of other windows and prints the choice."""
    start = (initial or "").replace("'", "''")  # PowerShell single-quote escaping
    return (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false};"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$d.Description = 'Choose where AI Video Studio stores your projects and videos';"
        "$d.ShowNewFolderButton = $true;"
        f"if ('{start}' -ne '' -and (Test-Path -LiteralPath '{start}')) {{ $d.SelectedPath = '{start}' }};"
        "if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $d.SelectedPath }"
    )


async def choose_folder(initial: str | None = None) -> str | None:
    """Open the operating system's folder picker on this PC. Returns None if cancelled."""
    if sys.platform == "win32":
        script = windows_picker_script(initial)
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script]
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW}
    elif sys.platform == "darwin":
        cmd = ["osascript", "-e", 'POSIX path of (choose folder with prompt "Choose where AI Video Studio stores projects")']
        kwargs = {}
    elif shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", "--title=Choose where AI Video Studio stores projects"]
        kwargs = {}
    else:
        raise ValidationFailed("No folder picker is available here; type the folder path instead.")
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                **kwargs)
    out, _ = await proc.communicate()
    chosen = out.decode("utf-8", errors="replace").strip().splitlines()
    return chosen[-1].strip() if chosen else None


class StorageMover:
    def __init__(self, services):
        self.s = services
        self.state: dict = {"status": "idle", "done": 0, "total": 0, "current": "", "errors": [], "bytes": 0,
                            "bytes_total": 0, "finished_at": None}
        self._task: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return bool(self._task and not self._task.done())

    def summary(self) -> dict:
        """Current location, free space, and projects that live somewhere else."""
        st = self.s.settings.get().storage
        root = self.s.projects.projects_root_or_none()
        projects = self.s.projects.list(archived=None)
        elsewhere = [p for p in projects if root is None or Path(p["folder"]).resolve().parent != root]
        return {
            "location": st.location or "",
            "projects_dir": str(root) if root else st.projects_dir,
            "available": root is not None,
            "export_dir": str(self.s.projects.export_root_or_none() or st.export_dir),
            "default_location": str(self.s.config.data_dir),
            "disk": disk_stats(root) if root else None,
            "projects": len(projects),
            "projects_elsewhere": len(elsewhere),
            "move": dict(self.state),
        }

    def set_location(self, raw: str, move_existing: bool) -> dict:
        if self.busy:
            raise ValidationFailed("A move is already running.")
        base = validate_location(raw)
        projects_dir, library_dir = base / PROJECTS_SUBDIR, base / LIBRARY_SUBDIR
        projects_dir.mkdir(exist_ok=True)
        library_dir.mkdir(exist_ok=True)
        self.s.settings.update({"storage": {"location": str(base), "projects_dir": str(projects_dir),
                                            "export_dir": str(library_dir)}})
        self.s.activity.add(f"Storage folder set to {base}", category="storage")
        if move_existing:
            self.start_move()
        return self.summary()

    def start_move(self) -> None:
        if self.busy:
            raise ValidationFailed("A move is already running.")
        active = self.s.jobs.list(status=["running"])
        if active:
            raise ValidationFailed("Wait for running jobs to finish (or pause the queue) before moving projects.")
        self._task = asyncio.get_running_loop().create_task(self._move_all())

    async def _move_all(self) -> None:
        root = self.s.projects.projects_root
        todo = [p for p in self.s.projects.list(archived=None)
                if Path(p["folder"]).exists() and Path(p["folder"]).resolve().parent != root]
        st = self.state
        st.update(status="moving", done=0, total=len(todo), current="", errors=[], bytes=0, finished_at=None,
                  bytes_total=sum(dir_size_bytes(Path(p["folder"])) for p in todo))
        self.s.bus.publish("storage", status="moving")
        free = disk_stats(root)
        if free and free["free_gb"] * 1024**3 < st["bytes_total"] * 1.05:
            st.update(status="error", errors=[f"Not enough free space on the new drive ({free['free_gb']} GB free)."],
                      finished_at=utcnow())
            return
        for p in todo:
            st["current"] = p["title"]
            if self.s.jobs.active(p["id"]):
                st["errors"].append(f"{p['title']}: has queued jobs; moved later (run Move again).")
                st["done"] += 1
                continue
            try:
                await asyncio.to_thread(self._move_one, p, root)
            except Exception as exc:  # keep going; this project stays where it was
                log.exception("moving project %s failed", p["id"])
                st["errors"].append(f"{p['title']}: {exc}")
            st["done"] += 1
            self.s.bus.publish("storage", status="moving", done=st["done"], total=st["total"])
        st.update(status="done" if not st["errors"] else "done_with_errors", current="", finished_at=utcnow())
        moved = st["done"] - len(st["errors"])
        self.s.activity.add(f"Moved {moved} project(s) to {root}" + (f"; {len(st['errors'])} could not be moved" if st["errors"] else ""),
                            level="warning" if st["errors"] else "info", category="storage")
        self.s.bus.publish("storage", status=st["status"])

    def _move_one(self, project: dict, root: Path) -> None:
        src = Path(project["folder"]).resolve()
        dest = root / src.name
        if dest.exists():
            raise RuntimeError(f"a folder named {src.name} already exists in the new location")
        tmp = root / f".moving-{src.name}"
        if tmp.exists():
            shutil.rmtree(tmp)
        try:
            shutil.copytree(src, tmp)
            # Verify before switching: every file present with the same size.
            for f in src.rglob("*"):
                if f.is_file():
                    copy = tmp / f.relative_to(src)
                    if not copy.is_file() or copy.stat().st_size != f.stat().st_size:
                        raise RuntimeError(f"copy check failed for {f.name}")
            os.replace(tmp, dest)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        self.state["bytes"] += dir_size_bytes(dest)
        self.s.projects.update(project["id"], folder=str(dest))
        self.s.projects.snapshot(project["id"])
        shutil.rmtree(src, ignore_errors=True)
