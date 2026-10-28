"""Full idea → finished MP4 run through the HTTP API.

Groq and Fish Audio are mocked (no credentials in CI); footage comes from the
draft-card provider; FFmpeg assembly, captions and QC are real.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from studio.main import create_app

from .conftest import HEADERS, install_fake_providers, make_services, needs_ffmpeg, wait_for

FAST_SETTINGS = {
    "general": {"automation_mode": "supervised"},
    "text": {"research_enabled": False},
    "video": {"duration_s": 8, "min_duration_s": 3, "max_duration_s": 30, "width": 360, "height": 640, "fps": 24,
              "transition": "fade", "transition_s": 0.25},
    "generation": {"video_provider": "draft"},
    "narration": {"voice_id": "voice-123", "voice_name": "Test voice", "alignment": "heuristic"},
    "captions": {"font": "DejaVu Sans"},
    "gates": {"script": True, "scene_plan": True, "assembly": False},
    "queue": {"min_free_disk_gb": 0},
}


def _project(c, pid):
    r = c.get(f"/api/projects/{pid}")
    assert r.status_code == 200, r.text
    return r.json()


@needs_ffmpeg
def test_idea_to_finished_video(home, router, speech_like_mp3):
    install_fake_providers(router, speech_like_mp3)
    svc = make_services(home, router)
    svc.secrets.set("groq", "gsk_testkey_1234567890")
    svc.secrets.set("fish_audio", "fish_testkey_123456")
    app = create_app(services=svc)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.patch("/api/settings", json=FAST_SETTINGS, headers=HEADERS).status_code == 200

        # Stage 1: ideas
        r = c.post("/api/ideas/generate", json={"count": 2}, headers=HEADERS)
        assert r.status_code == 200, r.text
        ideas = wait_for(lambda: c.get("/api/ideas").json() or None, message="ideas")
        idea = next(i for i in ideas if "sky" in i["title"])

        # Approve → project; supervised mode writes the script and waits for approval
        r = c.post(f"/api/ideas/{idea['id']}/approve", json={"start": True}, headers=HEADERS)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        p = wait_for(lambda: (x := _project(c, pid))["script_status"] == "draft" and x["status"] == "waiting_approval" and x,
                     message="script draft")
        assert p["next"]["action"] == "approve_script"
        assert len(p["script"]["segments"]) == 4
        # Claim check runs after the script; without sources nothing may be labelled verified.
        p = wait_for(lambda: (x := _project(c, pid)).get("factcheck") and x, message="factcheck")
        assert all(cl["status"] != "verified" for cl in p["factcheck"]["claims"])

        # Edit + approve the script
        segs = p["script"]["segments"]
        r = c.put(f"/api/projects/{pid}/script", json={"title": "Why sunsets are orange", "segments": segs}, headers=HEADERS)
        assert r.status_code == 200
        assert c.post(f"/api/projects/{pid}/approve/script", headers=HEADERS).status_code == 200

        # Scene plan (narration of a paraphrased scene must be repaired to the exact script)
        p = wait_for(lambda: (x := _project(c, pid))["scene_plan_status"] == "draft" and x, message="scene plan")
        assert len(p["scenes"]) == 4
        joined = " ".join(s["narration"] for s in p["scenes"])
        assert joined.split() == p["script"]["full_text"].split()

        # Supervised mode never generates footage before the plan is approved
        assert not [j for j in c.get(f"/api/jobs?project_id={pid}").json() if j["kind"] == "scene_clip"]
        assert c.post(f"/api/projects/{pid}/approve/scene_plan", headers=HEADERS).status_code == 200

        # Clips + narration, then automatic assembly (assembly gate is off)
        p = wait_for(lambda: (x := _project(c, pid))["export_status"] == "completed" and x, timeout=180, message="export")
        assert p["stage"] == "review" and p["status"] == "waiting_approval"
        assert all(s["clip_status"] == "completed" for s in p["scenes"])
        assert p["narration"]["alignment_method"] == "heuristic"

        folder = Path(p["folder"])
        final = folder / p["export"]["path"]
        assert final.is_file() and final.stat().st_size > 10_000
        assert (folder / "captions" / "captions.srt").is_file()
        assert (folder / "script" / "script.json").is_file()
        assert (folder / "scenes" / "scene_plan.json").is_file()
        assert (folder / "exports" / "qc.json").is_file()
        assert (folder / "project.json").is_file()
        meta_files = list((folder / "scenes").glob("scene_*/clip_*.json"))
        assert len(meta_files) == 4

        qc = p["qc"]
        assert qc["technical_ok"], qc
        checks = {ch["id"]: ch["status"] for ch in qc["checks"]}
        assert checks["resolution"] == "pass" and checks["audio"] == "pass" and checks["captions"] == "pass"
        assert checks["draft"] == "warn"  # draft cards are never reported as AI footage

        # The file is served to the UI from inside the project folder only
        r = c.get(f"/api/files/{pid}/{p['export']['path']}")
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
        assert c.get(f"/api/files/{pid}/../../studio.db").status_code in (400, 404)

        # Review → complete
        r = c.post(f"/api/projects/{pid}/review", json={"decision": "approved"}, headers=HEADERS)
        assert r.json()["status"] == "completed"
        lib = c.get("/api/library").json()
        assert lib[0]["export"]["path"].endswith(".mp4")

        # Regenerating one scene does not touch the others
        before = {s["id"]: s["clip_path"] for s in p["scenes"]}
        target = p["scenes"][1]["id"]
        assert c.post(f"/api/scenes/{target}/generate", headers=HEADERS).status_code == 200
        p = wait_for(lambda: (x := _project(c, pid)) and next(s for s in x["scenes"] if s["id"] == target)["clip_path"] != before[target] and x,
                     timeout=60, message="regenerated scene")
        for s in p["scenes"]:
            if s["id"] != target:
                assert s["clip_path"] == before[s["id"]]
        # The edit invalidated the export; with the assembly gate off it is rebuilt and needs a fresh review.
        p = wait_for(lambda: (x := _project(c, pid))["export_status"] == "completed" and x["review_status"] == "none" and x,
                     timeout=120, message="re-assembly")
        assert p["status"] == "waiting_approval"

    # Usage was recorded for both providers
    providers = {r["provider"] for r in svc.usage.summary()}
    assert {"groq", "fish_audio"} <= providers


@needs_ffmpeg
def test_narration_failure_preserves_footage(home, router, speech_like_mp3):
    import httpx

    install_fake_providers(router, speech_like_mp3)
    router.add("POST", "https://api.fish.audio/v1/tts", httpx.Response(402, json={"message": "Insufficient balance"}))
    svc = make_services(home, router)
    svc.secrets.set("groq", "gsk_testkey_1234567890")
    svc.secrets.set("fish_audio", "fish_testkey_123456")
    app = create_app(services=svc)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.patch("/api/settings", json={**FAST_SETTINGS, "gates": {"script": False, "scene_plan": False, "assembly": False},
                                       "general": {"automation_mode": "automated"}}, headers=HEADERS)
        r = c.post("/api/projects", json={"title": "Why sunsets are orange", "start": True}, headers=HEADERS)
        pid = r.json()["id"]
        p = wait_for(lambda: (x := _project(c, pid))["status"] == "failed" and
                     all(s["clip_status"] == "completed" for s in x["scenes"]) and x["scenes"] and x,
                     timeout=120, message="narration failure")
        assert p["narration_status"] == "failed"
        nar = next(j for j in p["jobs"] if j["kind"] == "narration")
        assert nar["status"] == "failed" and nar["error_kind"] == "quota" and nar["attempts"] == 1  # no pointless retries
        assert "credit" in nar["error_message"].lower()
        assert p["script_status"] == "approved"  # nothing upstream was discarded
