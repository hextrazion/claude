"""Choosing a storage folder (e.g. an external SSD) and moving projects to it."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from studio.main import create_app

from .conftest import HEADERS, make_services, wait_for


def _project_with_clip(c, title):
    pid = c.post("/api/projects", json={"title": title, "start": False}, headers=HEADERS).json()["id"]
    p = c.get(f"/api/projects/{pid}").json()
    clip = Path(p["folder"]) / "scenes" / "scene_01" / "clip.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"\x00" * 50_000)
    return pid, Path(p["folder"])


def test_choose_location_and_move_projects(home, router, tmp_path):
    svc = make_services(home, router)
    app = create_app(services=svc, start_worker=False)
    ssd = tmp_path / "external-ssd" / "AI Video Studio"
    with TestClient(app, base_url="http://127.0.0.1") as c:
        pid1, old1 = _project_with_clip(c, "First video")
        pid2, old2 = _project_with_clip(c, "Second video")
        r = c.post("/api/storage/location", json={"path": str(ssd), "move_existing": True}, headers=HEADERS)
        assert r.status_code == 200, r.text
        loc = wait_for(lambda: (x := c.get("/api/storage/location").json())["move"]["status"].startswith("done") and x,
                       message="move")
        assert loc["move"]["status"] == "done" and loc["projects_elsewhere"] == 0
        assert loc["projects_dir"] == str((ssd / "Projects").resolve())
        for pid, old in ((pid1, old1), (pid2, old2)):
            p = c.get(f"/api/projects/{pid}").json()
            new = Path(p["folder"])
            assert new.parent == (ssd / "Projects").resolve() and not old.exists()
            assert (new / "scenes" / "scene_01" / "clip.mp4").stat().st_size == 50_000
            assert c.get(f"/api/files/{pid}/scenes/scene_01/clip.mp4").status_code == 200
        # New projects go straight to the new folder.
        pid3, folder3 = _project_with_clip(c, "Third video")
        assert folder3.parent == (ssd / "Projects").resolve()
    # The choice survives a restart.
    assert make_services(home, router).settings.get().storage.location == str(ssd.resolve())


def test_failed_copy_leaves_project_untouched(home, router, tmp_path, monkeypatch):
    import studio.storage as storage

    svc = make_services(home, router)
    app = create_app(services=svc, start_worker=False)

    def broken_copytree(src, dst, *a, **k):
        Path(dst).mkdir(parents=True)
        (Path(dst) / "partial").write_bytes(b"x")
        raise OSError("drive unplugged during copy")

    with TestClient(app, base_url="http://127.0.0.1") as c:
        pid, old = _project_with_clip(c, "Fragile video")
        monkeypatch.setattr(storage.shutil, "copytree", broken_copytree)
        c.post("/api/storage/location", json={"path": str(tmp_path / "ssd"), "move_existing": True}, headers=HEADERS)
        loc = wait_for(lambda: (x := c.get("/api/storage/location").json())["move"]["status"].startswith("done") and x,
                       message="move")
        assert loc["move"]["status"] == "done_with_errors" and "unplugged" in loc["move"]["errors"][0]
        p = c.get(f"/api/projects/{pid}").json()
        assert Path(p["folder"]) == old and (old / "scenes" / "scene_01" / "clip.mp4").is_file()
        assert not any((tmp_path / "ssd" / "Projects").iterdir())  # no half-copied folder left behind
        assert loc["projects_elsewhere"] == 1  # offered again next time


def test_invalid_locations_are_refused(home, router, tmp_path):
    svc = make_services(home, router)
    app = create_app(services=svc, start_worker=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.post("/api/storage/location", json={"path": "relative/folder", "move_existing": False}, headers=HEADERS)
        assert r.status_code == 400 and "full folder path" in r.json()["error"]["message"]
        blocker = tmp_path / "a-file"
        blocker.write_text("x")
        r = c.post("/api/storage/location", json={"path": str(blocker / "sub"), "move_existing": False}, headers=HEADERS)
        assert r.status_code == 400 and "can't write" in r.json()["error"]["message"]


def test_unplugged_drive_is_reported_not_crashing(home, router, tmp_path):
    svc = make_services(home, router)
    blocker = tmp_path / "gone"
    blocker.write_text("x")  # a file where the folder should be: mkdir fails, like a missing drive
    svc.settings.update({"storage": {"projects_dir": str(blocker / "Projects"), "export_dir": str(blocker / "Library")}})
    app = create_app(services=svc, start_worker=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get("/api/system").status_code == 200
        assert c.get("/api/integrations").status_code == 200
        assert c.get("/api/storage/location").json()["available"] is False
        r = c.post("/api/projects", json={"title": "Will fail", "start": False}, headers=HEADERS)
        assert r.status_code == 400 and "plug it in" in r.json()["error"]["message"]
        allowed, reason = svc.worker.lane_allowed("gpu")
        assert not allowed and "external drive" in reason


def test_delete_project_left_on_old_drive(home, router, tmp_path):
    svc = make_services(home, router)
    app = create_app(services=svc, start_worker=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        pid, old = _project_with_clip(c, "Old place")
        c.post("/api/storage/location", json={"path": str(tmp_path / "ssd"), "move_existing": False}, headers=HEADERS)
        r = c.request("DELETE", f"/api/projects/{pid}", json={"confirm": "Old place", "delete_files": True}, headers=HEADERS)
        assert r.status_code == 200 and not old.exists()


def test_windows_folder_picker_script_parses():
    """On Windows (CI), PowerShell must accept the picker script, including awkward paths."""
    import subprocess
    import sys

    import pytest

    from studio.storage import windows_picker_script

    if sys.platform != "win32":
        pytest.skip("Windows only")
    for start in (None, "E:\\AI Video Studio", "D:\\it's mine"):
        check = (
            "$errs = $null; $null = [System.Management.Automation.Language.Parser]::ParseInput($env:PICKER, [ref]$null, [ref]$errs);"
            "if ($errs.Count) { $errs | ForEach-Object { $_.Message }; exit 1 }"
            "Add-Type -AssemblyName System.Windows.Forms; $null = New-Object System.Windows.Forms.FolderBrowserDialog"
        )
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", check],
                           env={**__import__("os").environ, "PICKER": windows_picker_script(start)},
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
