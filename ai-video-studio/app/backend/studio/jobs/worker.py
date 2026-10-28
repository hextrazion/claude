"""The job runner.

Three lanes run independently: ``gpu`` (video/image generation, one at a time
by default), ``api`` (Groq, Fish Audio, research) and ``cpu`` (FFmpeg).
Before launching a job the lane checks the pause switch, processing window,
session limit, disk space and, optionally, GPU load / blocklisted programs
(games). Running jobs are never killed by those checks; pausing only stops
*new* jobs from starting.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, time as dtime

from ..errors import Cancelled, StudioError
from ..system_monitor import disk_stats, gpu_stats, running_blocklisted
from .context import JobContext

log = logging.getLogger(__name__)

LANES = ("gpu", "api", "cpu")


def in_window(start: str, end: str, now: datetime | None = None) -> bool:
    now_t = (now or datetime.now()).time()
    s = dtime.fromisoformat(start)
    e = dtime.fromisoformat(end)
    if s == e:
        return True
    if s < e:
        return s <= now_t < e
    return now_t >= s or now_t < e  # window crosses midnight


def backoff_seconds(attempt: int, retry_after: float | None) -> float:
    if retry_after:
        return min(3600.0, max(5.0, retry_after))
    return float(min(900, 20 * 2 ** max(0, attempt - 1)))


class Worker:
    def __init__(self, services, handlers: dict):
        self.s = services
        self.handlers = handlers
        self._wake = asyncio.Event()
        self._tasks: dict[int, asyncio.Task] = {}
        self.cancel_flags: set[int] = set()
        self._loop_task: asyncio.Task | None = None
        self._stopping = False
        self.session_gpu_jobs = 0
        self.lane_state: dict[str, dict] = {lane: {"allowed": True, "reason": ""} for lane in LANES}
        self._last_automation = 0.0
        self._last_maintenance = 0.0

    # -- lifecycle ----------------------------------------------------------------
    async def start(self) -> None:
        await self.recover()
        self._loop_task = asyncio.create_task(self._run(), name="studio-worker")

    async def stop(self) -> None:
        """App shutdown: stop launching; leave running remote generations alone.

        Jobs still marked running are reconciled with the generation service on
        the next start (see ``recover``)."""
        self._stopping = True
        self._wake.set()
        if self._loop_task:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    def wake(self) -> None:
        self._wake.set()

    # -- gating -------------------------------------------------------------------------
    def lane_allowed(self, lane: str) -> tuple[bool, str]:
        st = self.s.settings.get()
        q = st.queue
        if q.paused:
            return False, "Queue is paused"
        if q.processing_window.enabled and (lane != "api" or q.window_applies_to_api):
            if not in_window(q.processing_window.start, q.processing_window.end):
                return False, f"Outside processing hours ({q.processing_window.start}–{q.processing_window.end})"
        if lane in ("gpu", "cpu"):
            disk = disk_stats(self.s.projects.projects_root)
            if disk and q.min_free_disk_gb and disk["free_gb"] < q.min_free_disk_gb:
                return False, f"Low disk space ({disk['free_gb']} GB free, minimum {q.min_free_disk_gb} GB)"
        if lane == "gpu":
            if q.max_jobs_per_session and self.session_gpu_jobs >= q.max_jobs_per_session:
                return False, f"Session limit reached ({q.max_jobs_per_session} generation jobs). Restart the queue to continue."
            blockers = running_blocklisted(q.pause_when_processes)
            if blockers:
                return False, f"Paused while {', '.join(blockers)} is running"
            if q.defer_when_gpu_busy and self.s.jobs.running_count("gpu") == 0:
                gpus = gpu_stats()
                if gpus and gpus[0].get("utilization_pct") is not None and gpus[0]["utilization_pct"] >= q.gpu_busy_threshold_pct:
                    return False, f"GPU busy ({gpus[0]['utilization_pct']:.0f}% used by another app)"
        return True, ""

    def lane_limit(self, lane: str) -> int:
        q = self.s.settings.get().queue
        return {"gpu": q.max_gpu_jobs, "api": q.max_api_jobs, "cpu": q.max_cpu_jobs}[lane]

    def state(self) -> dict:
        q = self.s.settings.get().queue
        return {
            "paused": q.paused,
            "lanes": {
                lane: {**self.lane_state[lane], "running": self.s.jobs.running_count(lane), "limit": self.lane_limit(lane)}
                for lane in LANES
            },
            "session_gpu_jobs": self.session_gpu_jobs,
            "counts": self.s.jobs.counts(),
        }

    def reset_session(self) -> None:
        self.session_gpu_jobs = 0
        self.wake()

    # -- main loop -------------------------------------------------------------------
    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stopping:
            try:
                self._tick()
                if loop.time() - self._last_automation > 60:
                    self._last_automation = loop.time()
                    self.s.orchestrator.automation_tick()
                if loop.time() - self._last_maintenance > 3600:
                    self._last_maintenance = loop.time()
                    await asyncio.to_thread(self.cleanup_work_files)
            except Exception:
                log.exception("worker tick failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    def _tick(self) -> None:
        for lane in LANES:
            allowed, reason = self.lane_allowed(lane)
            if self.lane_state[lane] != {"allowed": allowed, "reason": reason}:
                self.lane_state[lane] = {"allowed": allowed, "reason": reason}
                self.s.bus.publish("queue", lane=lane, allowed=allowed, reason=reason)
            if not allowed:
                continue
            while self.s.jobs.running_count(lane) < self.lane_limit(lane):
                job = self.s.jobs.claim_next(lane)
                if not job:
                    break
                if lane == "gpu":
                    self.session_gpu_jobs += 1
                self._tasks[job["id"]] = asyncio.create_task(self._execute(job), name=f"job-{job['id']}")
                self.s.bus.publish("job", id=job["id"], project_id=job.get("project_id"), status="running")
                if job.get("project_id"):
                    self.s.orchestrator.refresh(job["project_id"])
                if lane == "gpu":
                    # Re-check gates (e.g. session limit) before launching another GPU job.
                    allowed, _ = self.lane_allowed(lane)
                    if not allowed:
                        break

    async def _execute(self, job: dict) -> None:
        jid = job["id"]
        handler = self.handlers.get(job["kind"])
        ctx = JobContext(job, self.s, self.cancel_flags)
        outcome, err_msg = "completed", None
        try:
            if handler is None:
                raise StudioError(f"No handler for job kind {job['kind']}")
            result = await handler(ctx)
            self.s.jobs.complete(jid, result)
        except (Cancelled, asyncio.CancelledError) as exc:
            if self._stopping and isinstance(exc, asyncio.CancelledError) and jid not in self.cancel_flags:
                return  # app shutting down; recover() reconciles on next start
            outcome = "cancelled"
            self.s.jobs.cancelled(jid)
        except StudioError as exc:
            current = self.s.jobs.get(jid) or job
            if exc.retryable and current["attempts"] < current["max_attempts"]:
                delay = backoff_seconds(current["attempts"], exc.retry_after)
                self.s.jobs.retry_later(jid, delay, exc.message, kind=exc.kind, detail=exc.detail)
                self.s.activity.add(
                    f"{job['label']} hit a temporary problem ({exc.message}); retry {current['attempts']}/"
                    f"{current['max_attempts'] - 1} in {int(delay)}s",
                    level="warning", category=job["kind"], project_id=job.get("project_id"), job_id=jid,
                )
                outcome = "retrying"
            else:
                outcome, err_msg = "failed", exc.message
                self.s.jobs.fail(jid, exc.message, kind=exc.kind, detail=exc.detail)
        except Exception as exc:  # bug or unexpected library error: keep the trace for diagnostics
            log.exception("job %s crashed", jid)
            outcome, err_msg = "failed", f"Unexpected error: {exc}"
            self.s.jobs.fail(jid, err_msg, kind="internal", detail=traceback.format_exc()[-6000:])
        finally:
            self._tasks.pop(jid, None)
            self.cancel_flags.discard(jid)
        if outcome != "retrying":
            try:
                self.s.orchestrator.on_job_finished(self.s.jobs.get(jid) or job, outcome, err_msg)
            except Exception:
                log.exception("post-job hook failed for job %s", jid)
        elif job.get("project_id"):
            self.s.orchestrator.refresh(job["project_id"])
        self.s.bus.publish("job", id=jid, project_id=job.get("project_id"), status=outcome)
        self.wake()

    # -- controls ----------------------------------------------------------------------
    def cancel(self, job_id: int) -> str:
        job = self.s.jobs.require(job_id)
        if job["status"] in ("pending", "paused"):
            self.s.jobs.cancelled(job_id)
            self.s.orchestrator.on_job_finished(job, "cancelled")
            self.s.bus.publish("job", id=job_id, project_id=job.get("project_id"), status="cancelled")
            return "cancelled"
        if job["status"] == "running":
            self.s.jobs.request_cancel(job_id)
            self.cancel_flags.add(job_id)
            task = self._tasks.get(job_id)
            if task and job["lane"] == "api":
                task.cancel()  # in-flight HTTP request; nothing external to clean up
            # GPU/CPU jobs notice the flag and stop their ComfyUI prompt / FFmpeg process cleanly.
            return "cancelling"
        return job["status"]

    def cleanup_work_files(self) -> int:
        """Delete intermediate render files (project/work) older than the retention period.

        Only the ``work`` folder of projects with no active jobs is touched;
        clips, narration, captions and exports are never removed automatically."""
        days = self.s.settings.get().storage.keep_work_files_days
        if not days:
            return 0
        import shutil
        import time

        cutoff = time.time() - days * 86400
        removed = 0
        for p in self.s.projects.list(archived=None):
            work = self.s.projects.folder(p) / "work"
            if not work.is_dir() or self.s.jobs.active(p["id"]):
                continue
            try:
                if work.stat().st_mtime < cutoff:
                    shutil.rmtree(work)
                    removed += 1
            except OSError:
                log.warning("could not clean %s", work)
        if removed:
            self.s.activity.add(f"Removed intermediate render files from {removed} project(s)", category="storage")
        return removed

    # -- crash recovery -----------------------------------------------------------------
    async def recover(self) -> None:
        """Reconcile jobs recorded as running with reality after a restart."""
        stale = self.s.jobs.list(status="running")
        for job in stale:
            note = "Interrupted by an app restart; requeued"
            payload = dict(job["payload"])
            payload.pop("resume_external_id", None)
            keep_attempt = True
            if job["kind"] in ("scene_clip", "scene_image") and job.get("external_id"):
                adapter = self.s.video_adapter(job.get("provider"))
                try:
                    remote = await adapter.status(job["external_id"])
                except Exception:
                    remote = "unknown"
                if remote in ("queued", "running", "completed"):
                    payload["resume_external_id"] = job["external_id"]
                    note = f"Re-attaching to generation still {remote} in {adapter.label}"
                elif remote == "failed":
                    keep_attempt = False
                    note = "The generation failed while the app was closed; retrying"
                else:
                    note = f"{adapter.label} no longer has this generation; it will be resubmitted"
            self.s.jobs.requeue(job["id"], keep_attempt=keep_attempt, note=note, payload=payload)
            self.s.activity.add(f"{job['label']} (job {job['id']}): {note}", level="warning", category="recovery",
                                project_id=job.get("project_id"), job_id=job["id"])
        # Entities left in transient states without a live job go back to a retryable state.
        for p in self.s.projects.list(archived=None):
            for sc in self.s.projects.scenes(p["id"]):
                for field, kind in (("clip_status", "scene_clip"), ("image_status", "scene_image")):
                    if sc[field] in ("queued", "running") and not self.s.jobs.active(p["id"], kind, sc["id"]):
                        self.s.projects.update_scene(sc["id"], **{field: "failed"})
            fixes = {}
            if p["narration_status"] in ("queued", "running") and not self.s.jobs.active(p["id"], "narration"):
                fixes["narration_status"] = "failed"
            if p["export_status"] == "running" and not self.s.jobs.active(p["id"], "assemble"):
                fixes["export_status"] = "failed"
            if p["research_status"] == "running" and not self.s.jobs.active(p["id"], "research"):
                fixes["research_status"] = "failed"
            if fixes:
                self.s.projects.update(p["id"], **fixes)
            self.s.orchestrator.refresh(p["id"])
