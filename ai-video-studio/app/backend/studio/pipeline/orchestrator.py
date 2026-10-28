"""Decides what happens next for each project.

``next_step`` is a pure function of a project's recorded state; ``advance``
acts on it according to the automation mode and approval gates. Failed work
is never re-queued automatically by ``advance`` (that is the job queue's
retry policy's job); a person has to retry it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..errors import ValidationFailed

log = logging.getLogger(__name__)

STAGE_FOR_ACTION = {
    "research": "research",
    "script": "script",
    "approve_script": "script",
    "scene_plan": "scene_plan",
    "approve_scene_plan": "scene_plan",
    "production": "production",
    "approve_assembly": "assembly",
    "assemble": "assembly",
    "review": "review",
    "done": "complete",
}

USER_ACTIONS = {"research", "script", "factcheck", "scene_plan", "clips", "images", "narration", "assemble"}


class Orchestrator:
    def __init__(self, services):
        self.s = services

    # -- configuration ------------------------------------------------------------
    def gates(self) -> dict:
        st = self.s.settings.get()
        mode = st.general.automation_mode
        if mode == "manual":
            return {"mode": mode, "auto": False, "script": True, "scene_plan": True, "assembly": True}
        if mode == "supervised":
            # Supervised always stops before spending GPU time on footage.
            return {"mode": mode, "auto": True, "script": st.gates.script, "scene_plan": True, "assembly": st.gates.assembly}
        return {"mode": mode, "auto": True, "script": st.gates.script, "scene_plan": st.gates.scene_plan,
                "assembly": st.gates.assembly}

    def _research_on(self) -> bool:
        return self.s.research_provider() is not None

    # -- queueing -------------------------------------------------------------------
    def enqueue(self, project_id: int | None, kind: str, *, scene_id: int | None = None, payload: dict | None = None,
                front: bool = False) -> int:
        if project_id is not None:
            existing = self.s.jobs.active(project_id, kind, scene_id)
            if existing:
                return existing[0]["id"]
        st = self.s.settings.get()
        max_attempts = st.generation.max_retries + 1 if kind in ("scene_clip", "scene_image") else 4
        provider = None
        if kind in ("scene_clip", "scene_image"):
            provider = (payload or {}).get("provider") or st.generation.video_provider
        job_id = self.s.jobs.create(kind, project_id=project_id, scene_id=scene_id, payload=payload,
                                    max_attempts=max_attempts, provider=provider, front=front)
        if kind == "scene_clip" and scene_id:
            self.s.projects.update_scene(scene_id, clip_status="queued")
        elif kind == "scene_image" and scene_id:
            self.s.projects.update_scene(scene_id, image_status="queued")
        elif kind == "narration" and project_id:
            self.s.projects.update(project_id, narration_status="queued")
        elif kind == "research" and project_id:
            self.s.projects.update(project_id, research_status="running")
        self.s.bus.publish("job", id=job_id, project_id=project_id)
        if self.s.worker:
            self.s.worker.wake()
        return job_id

    def _latest_failed(self, project_id: int, kind: str, scene_id: int | None = None) -> bool:
        job = self.s.jobs.latest(project_id, kind, scene_id)
        return bool(job and job["status"] == "failed")

    # -- state machine -----------------------------------------------------------
    def next_step(self, p: dict, scenes: list[dict]) -> dict:
        def step(action, message, gate=None, **extra):
            return {"action": action, "message": message, "gate": gate, **extra}

        if p["archived"]:
            return step("archived", "Archived")
        if p["review_status"] == "approved" and p["export_status"] == "completed":
            return step("done", "Finished and approved")
        if p["research_status"] == "failed" and p["script_status"] == "none":
            return step("fix_failed", "Research failed. Retry it, or write the script without research.")
        if self._research_on() and p["research_status"] == "none" and p["script_status"] == "none":
            return step("research", "Research the topic")
        if p["research_status"] == "running":
            return step("wait", "Researching")
        if p["script_status"] == "none":
            return step("script", "Write the script")
        if p["script_status"] == "draft":
            return step("approve_script", "Review and approve the script", gate="script")
        if p["scene_plan_status"] in ("none", "stale"):
            msg = "Create the scene plan" if p["scene_plan_status"] == "none" else "The script changed: re-plan the scenes"
            return step("scene_plan", msg)
        if p["scene_plan_status"] == "draft":
            return step("approve_scene_plan", "Review and approve the scene plan", gate="scene_plan")

        st = self.s.projects.effective_settings(p)
        use_images = st.generation.use_image_stage and bool(st.generation.image_workflow)
        need_images = [sc for sc in scenes if use_images and sc["needs_image"] and sc["image_status"] in ("none",)]
        need_clips = [
            sc for sc in scenes
            if sc["clip_status"] in ("none", "stale")
            and not (use_images and sc["needs_image"] and sc["image_status"] != "completed")
        ]
        failed = [sc["idx"] + 1 for sc in scenes if sc["clip_status"] == "failed" or sc["image_status"] == "failed"]
        busy = [sc for sc in scenes if sc["clip_status"] in ("queued", "running") or sc["image_status"] in ("queued", "running")]
        narration_needed = p["narration_status"] in ("none", "stale")
        if need_images or need_clips or narration_needed:
            parts = []
            if need_images:
                parts.append(f"{len(need_images)} still(s)")
            if need_clips:
                parts.append(f"{len(need_clips)} clip(s)")
            if narration_needed:
                parts.append("narration")
            return step("production", "Generate " + ", ".join(parts), images=[x["id"] for x in need_images],
                        clips=[x["id"] for x in need_clips], narration=narration_needed)
        if failed or p["narration_status"] == "failed":
            what = (f"scene(s) {failed}" if failed else "") + (" and " if failed and p["narration_status"] == "failed" else "")
            what += "narration" if p["narration_status"] == "failed" else ""
            return step("fix_failed", f"Generation failed for {what}. Retry from the Production page.")
        if busy or p["narration_status"] in ("queued", "running"):
            return step("wait_production", "Generating footage and narration")
        if p["export_status"] in ("none", "stale"):
            if not p["assembly_approved"]:
                return step("approve_assembly", "All footage ready: approve assembly", gate="assembly")
            return step("assemble", "Assemble the final video")
        if p["export_status"] == "failed":
            return step("fix_failed", "Assembly failed. See the error, then retry.")
        if p["export_status"] in ("running",):
            return step("wait_assembly", "Assembling")
        if p["review_status"] == "rejected":
            return step("review", "Marked as needing changes. Regenerate scenes or narration, then re-assemble.", gate="review")
        return step("review", "Review the finished video", gate="review")

    def advance(self, project_id: int, *, user: bool = False) -> dict:
        """Move the project forward as far as the mode and gates allow."""
        gates = self.gates()
        step: dict = {}
        for _ in range(8):
            p = self.s.projects.get(project_id)
            if not p:
                return {"action": "missing", "message": "Project not found"}
            scenes = self.s.projects.scenes(project_id)
            step = self.next_step(p, scenes)
            action = step["action"]
            if not (gates["auto"] or user):
                break
            if action in ("approve_script", "approve_scene_plan", "approve_assembly"):
                gate_name = step["gate"]
                if gates.get(gate_name, True):
                    break
                self._auto_approve(p, gate_name)
                continue
            if action == "research" and (user or not self._latest_failed(project_id, "research")):
                self.enqueue(project_id, "research")
            elif action == "script" and (user or not self._latest_failed(project_id, "script")):
                self.enqueue(project_id, "script")
            elif action == "scene_plan" and (user or not self._latest_failed(project_id, "scene_plan")):
                self.enqueue(project_id, "scene_plan")
            elif action == "production":
                for sid in step["images"]:
                    if user or not self._latest_failed(project_id, "scene_image", sid):
                        self.enqueue(project_id, "scene_image", scene_id=sid)
                for sid in step["clips"]:
                    if user or not self._latest_failed(project_id, "scene_clip", sid):
                        self.enqueue(project_id, "scene_clip", scene_id=sid)
                if step["narration"] and (user or not self._latest_failed(project_id, "narration")):
                    self.enqueue(project_id, "narration")
            elif action == "assemble" and (user or not self._latest_failed(project_id, "assemble")):
                self.enqueue(project_id, "assemble")
            break
        self.refresh(project_id)
        return step

    def _auto_approve(self, p: dict, gate: str) -> None:
        if gate == "script":
            self.s.projects.update(p["id"], script_status="approved")
        elif gate == "scene_plan":
            self.s.projects.update(p["id"], scene_plan_status="approved")
        elif gate == "assembly":
            self.s.projects.update(p["id"], assembly_approved=1)
        self.s.activity.add(f"Auto-approved {gate.replace('_', ' ')} (gate disabled in {self.gates()['mode']} mode)",
                            category="automation", project_id=p["id"])

    def refresh(self, project_id: int) -> None:
        p = self.s.projects.get(project_id)
        if not p:
            return
        scenes = self.s.projects.scenes(project_id)
        step = self.next_step(p, scenes)
        active = self.s.jobs.active(project_id)
        running = [j for j in active if j["status"] == "running"]
        stage = STAGE_FOR_ACTION.get(step["action"], p["stage"])
        if step["action"] in ("wait_production",):
            stage = "production"
        elif step["action"] == "wait_assembly":
            stage = "assembly"
        elif step["action"] == "wait":
            stage = "research"
        if running:
            j = running[0]
            status = "running"
            msg = f"{j['label']}: {j.get('progress_message') or 'working'}"
            if len(active) > 1:
                msg += f" (+{len(active) - 1} more queued)"
        elif any(j["status"] == "pending" for j in active):
            status, msg = "queued", f"{len(active)} job(s) waiting in the queue"
        elif active:
            status, msg = "idle", "Jobs are paused in the queue"
        elif step["action"] == "done":
            status, msg = "completed", step["message"]
        elif step["action"] == "fix_failed":
            status, msg = "failed", step["message"]
        elif step.get("gate"):
            status, msg = "waiting_approval", step["message"]
        elif step["action"] == "archived":
            status, msg = p["status"], "Archived"
        else:
            status, msg = "idle", f"Next: {step['message']}"
        if (p["stage"], p["status"], p["status_message"]) != (stage, status, msg):
            self.s.projects.update(project_id, stage=stage, status=status, status_message=msg)
            self.s.bus.publish("project", id=project_id, stage=stage, status=status)

    # -- lifecycle hooks --------------------------------------------------------------
    def on_job_finished(self, job: dict, outcome: str, error: str | None = None) -> None:
        pid, sid = job.get("project_id"), job.get("scene_id")
        kind = job["kind"]
        if pid is None:
            return
        p = self.s.projects.get(pid)
        if not p:
            return
        if outcome != "completed":
            if sid and kind in ("scene_clip", "scene_image"):
                sc = self.s.projects.scene(sid)
                if sc:
                    field, path_field = ("clip_status", "clip_path") if kind == "scene_clip" else ("image_status", "image_path")
                    if outcome == "failed":
                        self.s.projects.update_scene(sid, **{field: "failed"})
                    else:
                        self.s.projects.update_scene(sid, **{field: "completed" if sc.get(path_field) else "none"})
            elif kind == "narration" and p["narration_status"] in ("queued", "running"):
                self.s.projects.update(pid, narration_status="failed" if outcome == "failed" else
                                       ("stale" if p.get("narration") else "none"))
            elif kind == "research" and p["research_status"] == "running":
                self.s.projects.update(pid, research_status="failed" if outcome == "failed" else "none")
            elif kind == "assemble" and p["export_status"] == "running":
                self.s.projects.update(pid, export_status="failed" if outcome == "failed" else
                                       ("stale" if p.get("export") else "none"))
            if outcome == "failed":
                self.s.activity.add(f"{job['label']} failed: {error or 'unknown error'}", level="error",
                                    category=kind, project_id=pid, job_id=job["id"])
        if outcome == "completed":
            self.advance(pid)
        else:
            self.refresh(pid)
        self.s.projects.snapshot(pid)

    # -- user actions -------------------------------------------------------------------
    def start_from_idea(self, idea_id: int, *, overrides: dict | None = None, origin: str = "manual",
                        auto_advance: bool = True) -> dict:
        idea = self.s.projects.get_idea(idea_id)
        if not idea:
            raise ValidationFailed("Idea not found.")
        if idea.get("project_id") and self.s.projects.get(idea["project_id"]):
            raise ValidationFailed("This idea already has a project.")
        project = self.s.projects.create_project(idea, overrides=overrides, origin=origin)
        self.s.activity.add(f"Project created: {project['title']}", category="project", project_id=project["id"])
        if auto_advance:
            self.advance(project["id"])
        else:
            self.refresh(project["id"])
        return self.s.projects.get(project["id"])

    def approve(self, project_id: int, gate: str) -> dict:
        p = self.s.projects.require(project_id)
        if gate == "script":
            if not p.get("script"):
                raise ValidationFailed("There is no script to approve.")
            self.s.projects.update(project_id, script_status="approved")
        elif gate == "scene_plan":
            if not self.s.projects.scenes(project_id):
                raise ValidationFailed("There is no scene plan to approve.")
            if p["script_status"] != "approved":
                raise ValidationFailed("Approve the script first.")
            self.s.projects.update(project_id, scene_plan_status="approved")
        elif gate == "assembly":
            self.s.projects.update(project_id, assembly_approved=1)
        else:
            raise ValidationFailed("Unknown approval.")
        self.s.activity.add(f"Approved {gate.replace('_', ' ')}", category="approval", project_id=project_id)
        # Approving is an explicit user action: continue even in manual mode.
        return self.advance(project_id, user=True)

    def review(self, project_id: int, decision: str, note: str = "") -> None:
        p = self.s.projects.require(project_id)
        if p["export_status"] != "completed":
            raise ValidationFailed("There is no finished export to review.")
        if decision not in ("approved", "rejected"):
            raise ValidationFailed("Decision must be approved or rejected.")
        self.s.projects.update(project_id, review_status=decision, review_note=note[:1000])
        if decision == "approved" and p.get("idea_id"):
            self.s.projects.update_idea(p["idea_id"], {"status": "produced"})
        self.s.activity.add(f"Review: {decision}" + (f" — {note}" if note else ""), category="review", project_id=project_id)
        self.refresh(project_id)

    def run_action(self, project_id: int, action: str, payload: dict | None = None) -> list[int]:
        if action not in USER_ACTIONS:
            raise ValidationFailed("Unknown action.")
        p = self.s.projects.require(project_id)
        scenes = self.s.projects.scenes(project_id)
        ids: list[int] = []
        if action in ("research", "script", "factcheck", "narration", "assemble"):
            if action == "script" and p["research_status"] == "failed":
                self.s.projects.update(project_id, research_status="skipped")
            if action == "assemble":
                self.s.projects.update(project_id, assembly_approved=1)
            ids.append(self.enqueue(project_id, action, payload=payload))
        elif action == "scene_plan":
            if p["script_status"] != "approved":
                raise ValidationFailed("Approve the script before planning scenes.")
            ids.append(self.enqueue(project_id, "scene_plan"))
        elif action in ("clips", "images"):
            if p["scene_plan_status"] != "approved":
                raise ValidationFailed("Approve the scene plan before generating footage.")
            kind = "scene_clip" if action == "clips" else "scene_image"
            field = "clip_status" if action == "clips" else "image_status"
            only = set((payload or {}).get("scene_ids") or [])
            for sc in scenes:
                if only and sc["id"] not in only:
                    continue
                if action == "images" and not sc["needs_image"]:
                    continue
                if only or sc[field] in ("none", "stale", "failed"):
                    ids.append(self.enqueue(project_id, kind, scene_id=sc["id"], payload=payload))
        self.refresh(project_id)
        return ids

    def cancel_project(self, project_id: int) -> int:
        n = 0
        for job in self.s.jobs.active(project_id):
            if self.s.worker:
                self.s.worker.cancel(job["id"])
            n += 1
        self.refresh(project_id)
        return n

    # -- automation ---------------------------------------------------------------------
    def automation_tick(self) -> None:
        st = self.s.settings.get()
        if st.general.automation_mode != "automated" or st.queue.paused:
            return
        a = st.automation
        if a.auto_generate_ideas and self.s.secrets.get("groq"):
            pool = self.s.db.scalar(
                "SELECT COUNT(*) FROM ideas WHERE status IN ('new','favorite') AND duplicate_of IS NULL AND COALESCE(score,0) >= ?",
                (a.min_idea_score,),
            )
            active = self.s.jobs.list(status=["pending", "running"])
            if pool < a.idea_pool_min and not any(j["kind"] == "ideas" for j in active):
                limit = st.limits.max_idea_batches_per_day
                if not limit or self.s.usage.count_today("groq", "ideas") < limit:
                    self.enqueue(None, "ideas", payload={"count": 8})
                    self.s.activity.add("Automation: generating a new batch of ideas", category="automation")
        if a.auto_select_ideas:
            active_projects = self.s.db.scalar(
                "SELECT COUNT(*) FROM projects WHERE archived = 0 AND stage NOT IN ('review','complete') AND status != 'failed'"
            )
            day_start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
            today = self.s.db.scalar(
                "SELECT COUNT(*) FROM projects WHERE origin = 'automation' AND created_at >= ?",
                (day_start.astimezone(timezone.utc).isoformat(timespec="seconds"),),
            )
            if active_projects < a.max_active_projects and (
                not st.limits.max_auto_projects_per_day or today < st.limits.max_auto_projects_per_day
            ):
                idea = self.s.db.query_one(
                    "SELECT id FROM ideas WHERE status IN ('new','favorite') AND duplicate_of IS NULL AND project_id IS NULL"
                    " AND COALESCE(score,0) >= ? ORDER BY (status = 'favorite') DESC, score DESC, id LIMIT 1",
                    (a.min_idea_score,),
                )
                if idea:
                    p = self.start_from_idea(idea["id"], origin="automation")
                    self.s.activity.add(f"Automation started a project: {p['title']}", category="automation",
                                        project_id=p["id"])

