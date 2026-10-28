"""Database, settings persistence, secrets and security safeguards."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from studio.errors import ValidationFailed
from studio.logging_setup import RedactingFilter
from studio.main import create_app
from studio.safety import safe_filename, safe_join, slugify
from studio.secrets_store import mask

from .conftest import HEADERS, make_services


def test_migrations_are_idempotent(services):
    assert services.db.schema_version() == "0001"
    assert services.db.migrate() == []
    tables = {r["name"] for r in services.db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"projects", "scenes", "jobs", "ideas", "settings", "api_usage", "activity"} <= tables


def test_settings_persist_across_restart(home, router):
    s1 = make_services(home, router)
    s1.settings.update({"video": {"duration_s": 42}, "narration": {"voice_id": "abc"}})
    s2 = make_services(home, router)
    st = s2.settings.get()
    assert st.video.duration_s == 42 and st.narration.voice_id == "abc"
    assert st.video.fps == 30  # untouched defaults survive a partial update


def test_invalid_settings_rejected_and_not_saved(services):
    with pytest.raises(ValidationError):
        services.settings.update({"video": {"width": 1081}})
    with pytest.raises(ValidationError):
        services.settings.update({"queue": {"processing_window": {"start": "25:00"}}})
    with pytest.raises(ValidationError):
        services.settings.update({"captions": {"font": "Arial'; rm -rf"}})
    assert services.settings.get().video.width == 1080


def test_corrupt_settings_section_falls_back_to_defaults(home, router):
    s1 = make_services(home, router)
    s1.settings.update({"video": {"duration_s": 50}})
    s1.db.execute("UPDATE settings SET value = ? WHERE key = 'app'",
                  (json.dumps({"video": {"duration_s": 50}, "captions": {"size_pct": "huge"}}),))
    st = make_services(home, router).settings.get()
    assert st.video.duration_s == 50 and st.captions.size_pct == 6.0


def test_secrets_are_masked_and_env_overrides(services, monkeypatch):
    services.secrets.set("groq", "gsk_abcdefghijklmnop1234")
    assert services.secrets.masked("groq") == "gsk_••••1234"
    assert services.secrets.get("groq") == "gsk_abcdefghijklmnop1234"
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fromenvironment9999")
    assert services.secrets.get("groq") == "gsk_fromenvironment9999"
    assert "environment" in services.secrets.source("groq")
    services.secrets.delete("groq")
    monkeypatch.delenv("GROQ_API_KEY")
    assert services.secrets.get("groq") is None
    assert mask(None) is None


def test_api_never_returns_full_key(services):
    app = create_app(services=services, start_worker=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        key = "gsk_supersecretvalue_987654321"
        r = c.put("/api/integrations/groq/key", json={"api_key": key}, headers=HEADERS)
        assert r.status_code == 200
        everything = c.get("/api/integrations").text + r.text + c.get("/api/settings").text + c.get("/api/dashboard").text
        assert key not in everything
        assert "gsk_••••4321" in everything


def test_log_redaction():
    f = RedactingFilter(lambda: ["my-secret-value-123"])
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "auth Bearer abcdefghijklmnop and my-secret-value-123 gsk_ABCDEFGHIJKLMNOP", None, None)
    f.filter(rec)
    msg = rec.getMessage()
    assert "my-secret-value-123" not in msg and "abcdefghijklmnop" not in msg and "gsk_ABCDEFGHIJKLMNOP" not in msg


def test_path_validation(tmp_path):
    base = tmp_path / "project"
    base.mkdir()
    assert safe_join(base, "exports/final.mp4") == (base / "exports" / "final.mp4").resolve()
    for bad in ("../secrets.json", "/etc/passwd", "C:/Windows/win.ini", "a/../../b", "..\\..\\x", "", "a\x00b"):
        with pytest.raises(ValidationFailed):
            safe_join(base, bad)
    assert slugify("Con") == "project-con"
    assert slugify("Why is the sky blue?!") == "why-is-the-sky-blue"
    assert safe_filename("../../evil name.MP4") == "evil-name.mp4"


def test_request_guards(services):
    app = create_app(services=services, start_worker=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        # Mutations need the client header (CSRF guard)
        assert c.patch("/api/settings", json={"video": {"fps": 24}}).status_code == 403
        # Cross-origin mutation refused even with the header
        r = c.patch("/api/settings", json={"video": {"fps": 24}}, headers={**HEADERS, "Origin": "https://evil.example"})
        assert r.status_code == 403
        assert c.patch("/api/settings", json={"video": {"fps": 24}}, headers=HEADERS).status_code == 200
        # DNS-rebinding style Host header refused
        assert c.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
        assert "Content-Security-Policy" not in c.get("/api/health").headers
        assert c.get("/api/health").headers["X-Frame-Options"] == "DENY"


def test_delete_project_requires_confirmation_and_marker(services):
    app = create_app(services=services, start_worker=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        pid = c.post("/api/projects", json={"title": "Test project", "start": False}, headers=HEADERS).json()["id"]
        folder = services.projects.folder(services.projects.get(pid))
        outside = folder.parent.parent / "unrelated.txt"
        outside.write_text("keep me")
        r = c.request("DELETE", f"/api/projects/{pid}", json={"confirm": "wrong", "delete_files": True}, headers=HEADERS)
        assert r.status_code == 400 and folder.exists()
        # A folder without our marker file is never removed
        (folder / "project.json").unlink()
        r = c.request("DELETE", f"/api/projects/{pid}", json={"confirm": "Test project", "delete_files": True}, headers=HEADERS)
        assert r.status_code == 400 and folder.exists()
        services.projects.snapshot(pid)
        r = c.request("DELETE", f"/api/projects/{pid}", json={"confirm": "Test project", "delete_files": True}, headers=HEADERS)
        assert r.status_code == 200 and not folder.exists()
        assert outside.read_text() == "keep me"
        assert c.get(f"/api/projects/{pid}").status_code == 400


def test_delete_project_keep_files(services):
    app = create_app(services=services, start_worker=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        pid = c.post("/api/projects", json={"title": "Keep files", "start": False}, headers=HEADERS).json()["id"]
        folder = services.projects.folder(services.projects.get(pid))
        r = c.request("DELETE", f"/api/projects/{pid}", json={"confirm": "Keep files"}, headers=HEADERS)
        assert r.status_code == 200 and folder.exists()


def test_duplicate_idea_detection(services):
    a = services.projects.create_idea({"title": "Why the sky is blue", "central_question": "Why is the sky blue during the day?"})
    b = services.projects.create_idea({"title": "Why is the sky blue?", "central_question": "Why the daytime sky is blue"})
    c = services.projects.create_idea({"title": "How octopuses taste with their arms"})
    assert services.projects.get_idea(b)["duplicate_of"] == a
    assert services.projects.get_idea(c)["duplicate_of"] is None
