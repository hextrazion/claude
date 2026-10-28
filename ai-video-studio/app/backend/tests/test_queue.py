"""Persistent queue: retries, permanent failures, pause, ordering, restart recovery."""

from __future__ import annotations

from datetime import datetime

import anyio
import httpx
from fastapi.testclient import TestClient

from studio.errors import ProviderError
from studio.jobs.worker import Worker, backoff_seconds, in_window
from studio.main import create_app
from studio.pipeline.orchestrator import Orchestrator

from .conftest import HEADERS, make_services, wait_for


def _wired(home, router, handlers):
    svc = make_services(home, router)
    svc.orchestrator = Orchestrator(svc)
    svc.worker = Worker(svc, handlers)
    return svc


async def _drive(worker, until, timeout=10):
    with anyio.fail_after(timeout):
        while not until():
            worker._tick()
            await anyio.sleep(0.05)


def test_transient_failure_retries_then_succeeds(home, router):
    calls = {"n": 0}

    async def flaky(ctx):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("temporary", kind="transient")
        return {"ok": True}

    svc = _wired(home, router, {"ideas": flaky})
    jid = svc.jobs.create("ideas", max_attempts=4)

    async def go():
        import asyncio
        svc.bus.bind_loop(asyncio.get_running_loop())
        for attempt in (1, 2, 3):
            await _drive(svc.worker, lambda: svc.jobs.get(jid)["attempts"] == attempt and svc.jobs.get(jid)["status"] != "running"
                         and not svc.worker._tasks)
            # skip the backoff wait
            svc.db.execute("UPDATE jobs SET next_attempt_at = NULL WHERE id = ?", (jid,))
            if svc.jobs.get(jid)["status"] == "completed":
                break

    anyio.run(go)
    job = svc.jobs.get(jid)
    assert job["status"] == "completed" and job["attempts"] == 3 and calls["n"] == 3


def test_permanent_failure_is_not_retried(home, router):
    calls = {"n": 0}

    async def bad_key(ctx):
        calls["n"] += 1
        raise ProviderError("Groq rejected the API key.", kind="auth", detail="HTTP 401")

    svc = _wired(home, router, {"ideas": bad_key})
    jid = svc.jobs.create("ideas", max_attempts=5)

    async def go():
        import asyncio
        svc.bus.bind_loop(asyncio.get_running_loop())
        await _drive(svc.worker, lambda: svc.jobs.get(jid)["status"] == "failed")

    anyio.run(go)
    job = svc.jobs.get(jid)
    assert calls["n"] == 1 and job["error_kind"] == "auth" and job["error_detail"] == "HTTP 401"


def test_backoff_and_window():
    assert backoff_seconds(1, None) == 20 and backoff_seconds(10, None) == 900
    assert backoff_seconds(1, 120) == 120
    assert in_window("01:00", "08:00", datetime(2026, 1, 1, 3, 0))
    assert not in_window("01:00", "08:00", datetime(2026, 1, 1, 9, 0))
    assert in_window("22:00", "06:00", datetime(2026, 1, 1, 23, 30))
    assert in_window("22:00", "06:00", datetime(2026, 1, 1, 5, 0))
    assert not in_window("22:00", "06:00", datetime(2026, 1, 1, 12, 0))


def test_pause_blocks_new_jobs_and_window(home, router):
    svc = _wired(home, router, {})
    svc.settings.update({"queue": {"paused": True}})
    jid = svc.jobs.create("scene_clip")
    svc.worker._tick()
    assert svc.jobs.get(jid)["status"] == "pending"
    allowed, reason = svc.worker.lane_allowed("gpu")
    assert not allowed and "paused" in reason.lower()
    svc.settings.update({"queue": {"paused": False, "processing_window": {"enabled": True, "start": "00:00", "end": "00:01"}}})
    allowed, reason = svc.worker.lane_allowed("gpu")
    if not in_window("00:00", "00:01"):
        assert not allowed and "processing hours" in reason
    # API work is not held by the GPU processing window unless configured
    assert svc.worker.lane_allowed("api")[0]


def test_session_limit_and_blocklisted_process(home, router, monkeypatch):
    svc = _wired(home, router, {})
    svc.settings.update({"queue": {"max_jobs_per_session": 2}})
    svc.worker.session_gpu_jobs = 2
    assert not svc.worker.lane_allowed("gpu")[0]
    svc.worker.reset_session()
    assert svc.worker.lane_allowed("gpu")[0]
    monkeypatch.setattr("studio.jobs.worker.running_blocklisted", lambda names: ["cyberpunk2077"])
    svc.settings.update({"queue": {"pause_when_processes": ["Cyberpunk2077.exe"]}})
    allowed, reason = svc.worker.lane_allowed("gpu")
    assert not allowed and "cyberpunk2077" in reason


def test_one_gpu_job_at_a_time(home, router):
    import asyncio

    started = []
    release = asyncio.Event()

    async def slow(ctx):
        started.append(ctx.job["id"])
        await release.wait()
        return {}

    svc = _wired(home, router, {"scene_clip": slow})
    ids = [svc.jobs.create("scene_clip") for _ in range(3)]

    async def go():
        svc.bus.bind_loop(asyncio.get_running_loop())
        nonlocal release
        release = asyncio.Event()
        svc.worker._tick()
        await asyncio.sleep(0.1)
        svc.worker._tick()
        assert started == [ids[0]]
        assert svc.jobs.running_count("gpu") == 1
        release.set()
        await _drive(svc.worker, lambda: all(svc.jobs.get(i)["status"] == "completed" for i in ids))

    anyio.run(go)
    assert started == ids


def test_reorder_pause_remove(home, router):
    svc = _wired(home, router, {})
    a, b, c = (svc.jobs.create("scene_clip") for _ in range(3))
    assert svc.jobs.move(c, "top")
    assert svc.jobs.claim_next("gpu")["id"] == c
    assert svc.jobs.move(b, "up")
    assert svc.jobs.set_status(b, "paused", ("pending",))
    assert svc.jobs.claim_next("gpu")["id"] == a
    assert svc.jobs.claim_next("gpu") is None  # b is paused
    assert not svc.jobs.remove(a)  # running jobs cannot be removed
    assert svc.jobs.remove(b)


def test_queue_persists_and_recovers_after_restart(home, router):
    svc = _wired(home, router, {})
    p = svc.projects.create_project({"id": svc.projects.create_idea({"title": "Restart test"}), "title": "Restart test"})
    svc.projects.replace_scenes(p["id"], [{"narration": "hi", "prompt": "x"}])
    scene = svc.projects.scenes(p["id"])[0]
    pending = svc.jobs.create("narration", project_id=p["id"])
    running = svc.jobs.create("scene_clip", project_id=p["id"], scene_id=scene["id"], provider="comfyui")
    svc.jobs.claim_next("gpu")
    svc.jobs.set_external(running, "prompt-42", "comfyui")
    svc.projects.update_scene(scene["id"], clip_status="running")

    # "Crash": new process, same data directory. ComfyUI still has the prompt running.
    router.add("GET", "http://127.0.0.1:8188/history/prompt-42", httpx.Response(200, json={}))
    router.add("GET", "http://127.0.0.1:8188/queue",
               httpx.Response(200, json={"queue_running": [[0, "prompt-42", {}, {}, []]], "queue_pending": []}))
    svc2 = _wired(home, router, {})
    assert svc2.jobs.get(pending)["status"] == "pending"
    anyio.run(svc2.worker.recover)
    job = svc2.jobs.get(running)
    assert job["status"] == "pending"
    assert job["payload"]["resume_external_id"] == "prompt-42"  # re-attach instead of resubmitting
    assert job["attempts"] == 0
    assert "Re-attaching" in job["progress_message"]


def test_recovery_when_engine_forgot_the_job(home, router):
    svc = _wired(home, router, {})
    p = svc.projects.create_project({"id": svc.projects.create_idea({"title": "Forgot"}), "title": "Forgot"})
    svc.projects.replace_scenes(p["id"], [{"narration": "hi", "prompt": "x"}])
    scene = svc.projects.scenes(p["id"])[0]
    jid = svc.jobs.create("scene_clip", project_id=p["id"], scene_id=scene["id"], provider="comfyui")
    svc.jobs.claim_next("gpu")
    svc.jobs.set_external(jid, "gone", "comfyui")
    router.add("GET", "http://127.0.0.1:8188/history/gone", httpx.Response(200, json={}))
    router.add("GET", "http://127.0.0.1:8188/queue", httpx.Response(200, json={"queue_running": [], "queue_pending": []}))
    svc2 = _wired(home, router, {})
    anyio.run(svc2.worker.recover)
    job = svc2.jobs.get(jid)
    assert job["status"] == "pending" and "resume_external_id" not in job["payload"]


def test_queue_api_controls(home, router):
    svc = make_services(home, router)
    app = create_app(services=svc, start_worker=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.post("/api/queue/pause", headers=HEADERS).json()["paused"] is True
        jid = svc.jobs.create("ideas")
        assert c.post(f"/api/jobs/{jid}/pause", headers=HEADERS).json()["status"] == "paused"
        assert c.post(f"/api/jobs/{jid}/resume", headers=HEADERS).json()["status"] == "pending"
        assert c.post(f"/api/jobs/{jid}/cancel", headers=HEADERS).json()["status"] == "cancelled"
        assert c.post(f"/api/jobs/{jid}/retry", headers=HEADERS).json()["status"] == "pending"
        r = c.post(f"/api/jobs/{jid}/retry", headers=HEADERS)
        assert r.status_code == 400 and "failed or cancelled" in r.json()["error"]["message"]
        assert c.post("/api/queue/resume", headers=HEADERS).json()["paused"] is False
        state = c.get("/api/queue").json()
        assert set(state["lanes"]) == {"gpu", "api", "cpu"}


def test_daily_limit_blocks_idea_generation(home, router):
    svc = make_services(home, router)
    svc.secrets.set("groq", "gsk_k_000000000000")
    svc.settings.update({"limits": {"max_idea_batches_per_day": 1}})
    svc.usage.record("groq", "ideas", ok=True, model="m", input_tokens=1, output_tokens=1)
    app = create_app(services=svc, start_worker=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.post("/api/ideas/generate", json={"count": 3}, headers=HEADERS)
        assert r.status_code == 429 and "limit" in r.json()["error"]["message"].lower()


def test_wait_for_helper():
    assert wait_for(lambda: 5, timeout=1) == 5


def test_work_file_retention_only_touches_work_folder(home, router):
    import os
    import time

    svc = _wired(home, router, {})
    p = svc.projects.create_project({"id": svc.projects.create_idea({"title": "Old project"}), "title": "Old project"})
    folder = svc.projects.folder(p)
    work = folder / "work"
    work.mkdir()
    (work / "seg_00.mp4").write_bytes(b"x")
    keep = folder / "exports" / "final.mp4"
    keep.parent.mkdir()
    keep.write_bytes(b"x")
    old = time.time() - 30 * 86400
    os.utime(work, (old, old))
    svc.settings.update({"storage": {"keep_work_files_days": 14}})
    assert svc.worker.cleanup_work_files() == 1
    assert not work.exists() and keep.exists()
