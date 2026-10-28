"""Project, scene and idea persistence plus the on-disk project folder."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..db import Database, dumps, loads, utcnow
from ..errors import ValidationFailed
from ..safety import ensure_within, slugify
from ..settings import SettingsService

_JSON_FIELDS = {
    "overrides_json": "overrides",
    "research_json": "research",
    "script_json": "script",
    "factcheck_json": "factcheck",
    "narration_json": "narration",
    "export_json": "export",
    "qc_json": "qc",
}
_SCENE_JSON = {"settings_json": "settings", "clip_meta_json": "clip_meta", "flags_json": "flags"}

PROJECT_MARKER = "project.json"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _decode(row: dict | None, mapping: dict[str, str]) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for col, key in mapping.items():
        if col in out:
            out[key] = loads(out.pop(col), None)
    return out


_STOP = set(
    "a an the of in on at to for and or but is are was were be why how what when who does do did can your you it its "
    "this that these those with from into about than then there their they we our us vs really actually".split()
)


def fingerprint(*texts: str) -> str:
    words = re.findall(r"[a-z0-9]+", " ".join(texts).lower())
    return " ".join(sorted({w for w in words if w not in _STOP and len(w) > 2}))


def similarity(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class ProjectStore:
    def __init__(self, db: Database, config: AppConfig, settings: SettingsService):
        self.db = db
        self.config = config
        self.settings = settings

    # -- directories ------------------------------------------------------------
    @property
    def projects_root(self) -> Path:
        custom = self.settings.get().storage.projects_dir.strip()
        root = Path(custom).expanduser() if custom else self.config.default_projects_dir
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()

    @property
    def export_root(self) -> Path:
        custom = self.settings.get().storage.export_dir.strip()
        root = Path(custom).expanduser() if custom else self.config.library_dir
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()

    def folder(self, project: dict) -> Path:
        return Path(project["folder"])

    def rel(self, project: dict, path: Path) -> str:
        return ensure_within(self.folder(project), path).relative_to(self.folder(project).resolve()).as_posix()

    def abs(self, project: dict, rel_path: str | None) -> Path | None:
        if not rel_path:
            return None
        return ensure_within(self.folder(project), self.folder(project) / rel_path)

    # -- ideas ------------------------------------------------------------------
    def create_idea(self, data: dict, *, source: str = "groq", model: str | None = None, batch_id: str | None = None) -> int:
        now = utcnow()
        fp = fingerprint(data.get("title", ""), data.get("central_question", ""))
        dup_id, dup_score = self.find_duplicate(fp, title=str(data.get("title", "")))
        return self.db.execute(
            "INSERT INTO ideas(title, niche, central_question, hook, description, appeal, visual_approach, est_duration_s,"
            " research_needs, accuracy_concerns, score, status, fingerprint, duplicate_of, duplicate_score, source, model,"
            " batch_id, notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(data.get("title", "")).strip()[:200] or "Untitled idea",
                str(data.get("niche", ""))[:120],
                str(data.get("central_question", ""))[:500],
                str(data.get("hook", ""))[:500],
                str(data.get("description", ""))[:2000],
                str(data.get("appeal", ""))[:1000],
                str(data.get("visual_approach", ""))[:1000],
                _num(data.get("est_duration_s")),
                _text(data.get("research_needs"))[:1000],
                _text(data.get("accuracy_concerns"))[:1000],
                _num(data.get("score")),
                "new",
                fp,
                dup_id,
                dup_score,
                source,
                model,
                batch_id,
                str(data.get("notes", ""))[:2000],
                now,
                now,
            ),
        )

    def find_duplicate(self, fp: str, exclude_id: int | None = None, title: str = "",
                       threshold: float = 0.5) -> tuple[int | None, float | None]:
        """Most similar existing idea, judged on title+question and on title alone."""
        title_fp = fingerprint(title)
        best, best_score = None, 0.0
        for row in self.db.query("SELECT id, title, fingerprint FROM ideas ORDER BY id DESC LIMIT 3000"):
            if row["id"] == exclude_id:
                continue
            sc = max(similarity(fp, row["fingerprint"]),
                     similarity(title_fp, fingerprint(row["title"])) * 0.85 if title_fp else 0.0)
            if sc > best_score:
                best, best_score = row["id"], sc
        if best_score >= threshold:
            return best, round(best_score, 2)
        return None, None

    def get_idea(self, idea_id: int) -> dict | None:
        return self.db.query_one("SELECT * FROM ideas WHERE id = ?", (idea_id,))

    def list_ideas(self, status: str | None = None, q: str | None = None, sort: str = "new") -> list[dict]:
        sql, params = "SELECT * FROM ideas WHERE 1=1", []
        if status == "active":
            sql += " AND status IN ('new','favorite')"
        elif status:
            sql += " AND status = ?"
            params.append(status)
        if q:
            sql += " AND (title LIKE ? OR description LIKE ? OR niche LIKE ?)"
            params += [f"%{q}%"] * 3
        order = {"new": "id DESC", "score": "COALESCE(score, 0) DESC, id DESC", "title": "title COLLATE NOCASE"}.get(sort, "id DESC")
        return self.db.query(f"{sql} ORDER BY {order} LIMIT 500", tuple(params))

    def update_idea(self, idea_id: int, fields: dict) -> None:
        allowed = {"title", "niche", "central_question", "hook", "description", "appeal", "visual_approach",
                   "est_duration_s", "research_needs", "accuracy_concerns", "status", "notes", "score", "project_id"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if "status" in fields and fields["status"] not in ("new", "favorite", "rejected", "approved", "produced"):
            raise ValidationFailed("Invalid idea status.")
        if {"title", "central_question"} & fields.keys():
            cur = self.get_idea(idea_id) or {}
            fp = fingerprint(fields.get("title", cur.get("title", "")), fields.get("central_question", cur.get("central_question", "")))
            dup, score = self.find_duplicate(fp, exclude_id=idea_id, title=fields.get("title", cur.get("title", "")))
            fields.update(fingerprint=fp, duplicate_of=dup, duplicate_score=score)
        fields["updated_at"] = utcnow()
        self.db.update("ideas", idea_id, fields)

    def avoid_titles(self, limit: int = 80) -> list[str]:
        rows = self.db.query(
            "SELECT title FROM ideas WHERE status IN ('approved','produced','rejected','new','favorite') ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [r["title"] for r in rows]

    # -- projects -------------------------------------------------------------
    def create_project(self, idea: dict, *, overrides: dict | None = None, origin: str = "manual") -> dict:
        now = utcnow()
        slug = slugify(idea["title"])
        pid = self.db.execute(
            "INSERT INTO projects(idea_id, title, slug, folder, niche, overrides_json, origin, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (idea["id"], idea["title"], slug, "", idea.get("niche", ""), dumps(overrides or {}), origin, now, now),
        )
        folder = self.projects_root / f"{pid:04d}-{slug}"
        folder.mkdir(parents=True, exist_ok=True)
        self.db.update("projects", pid, {"folder": str(folder)})
        self.update_idea(idea["id"], {"status": "approved", "project_id": pid})
        project = self.get(pid)
        self.write_json(project, "idea.json", self.get_idea(idea["id"]))
        self.snapshot(project)
        return project

    def get(self, project_id: int) -> dict | None:
        return _decode(self.db.query_one("SELECT * FROM projects WHERE id = ?", (project_id,)), _JSON_FIELDS)

    def require(self, project_id: int) -> dict:
        p = self.get(project_id)
        if not p:
            raise ValidationFailed("Project not found.")
        return p

    def list(self, archived: bool | None = False, q: str | None = None) -> list[dict]:
        sql, params = "SELECT * FROM projects WHERE 1=1", []
        if archived is not None:
            sql += " AND archived = ?"
            params.append(int(archived))
        if q:
            sql += " AND title LIKE ?"
            params.append(f"%{q}%")
        rows = self.db.query(sql + " ORDER BY updated_at DESC LIMIT 500", tuple(params))
        return [_decode(r, _JSON_FIELDS) for r in rows]

    def update(self, project_id: int, **fields: Any) -> None:
        out = {}
        reverse = {v: k for k, v in _JSON_FIELDS.items()}
        for k, v in fields.items():
            if k in reverse:
                out[reverse[k]] = None if v is None else dumps(v)
            else:
                out[k] = v
        out["updated_at"] = utcnow()
        self.db.update("projects", project_id, out)

    def effective_settings(self, project: dict):
        """Global settings with this project's overrides applied."""
        from ..settings import Settings, deep_merge

        base = self.settings.get().model_dump()
        return Settings.model_validate(deep_merge(base, project.get("overrides") or {}))

    def write_json(self, project: dict, rel_path: str, data: Any) -> Path:
        path = ensure_within(self.folder(project), self.folder(project) / rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return path

    def snapshot(self, project: dict | int) -> None:
        """Write project.json: a human-readable copy of the project record."""
        p = self.get(project if isinstance(project, int) else project["id"])
        if not p:
            return
        scenes = self.scenes(p["id"])
        self.write_json(p, PROJECT_MARKER, {"project": p, "scenes": scenes, "written_at": utcnow()})

    def delete(self, project: dict, delete_files: bool) -> None:
        folder = self.folder(project)
        if delete_files and folder.exists():
            # Only ever remove a folder that is inside the projects root and is marked as ours.
            root = self.projects_root
            resolved = ensure_within(root, folder)
            marker = resolved / PROJECT_MARKER
            if resolved == root or not marker.is_file():
                raise ValidationFailed("Refusing to delete: folder is not a recognised project folder.", detail=str(folder))
            try:
                data = json.loads(marker.read_text(encoding="utf-8"))
                if data.get("project", {}).get("id") != project["id"]:
                    raise ValidationFailed("Refusing to delete: project folder belongs to a different project.")
            except json.JSONDecodeError as exc:
                raise ValidationFailed("Refusing to delete: project marker is unreadable.") from exc
            shutil.rmtree(resolved)
        if project.get("idea_id"):
            self.db.execute("UPDATE ideas SET project_id = NULL, status = 'rejected', updated_at = ? WHERE id = ?",
                            (utcnow(), project["idea_id"]))
        self.db.execute("DELETE FROM projects WHERE id = ?", (project["id"],))

    # -- scenes -----------------------------------------------------------------
    def scenes(self, project_id: int) -> list[dict]:
        rows = self.db.query("SELECT * FROM scenes WHERE project_id = ? ORDER BY idx", (project_id,))
        return [_decode(r, _SCENE_JSON) for r in rows]

    def scene(self, scene_id: int) -> dict | None:
        return _decode(self.db.query_one("SELECT * FROM scenes WHERE id = ?", (scene_id,)), _SCENE_JSON)

    def replace_scenes(self, project_id: int, scenes: list[dict]) -> None:
        now = utcnow()
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM jobs WHERE project_id = ? AND scene_id IS NOT NULL AND status IN ('pending','paused')",
                         (project_id,))
            conn.execute("DELETE FROM scenes WHERE project_id = ?", (project_id,))
            for i, s in enumerate(scenes):
                conn.execute(
                    "INSERT INTO scenes(project_id, idx, narration, visual_objective, prompt, negative_prompt, camera,"
                    " subject_motion, environment, style, duration_s, needs_image, image_prompt, transition, settings_json,"
                    " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        project_id, i, s.get("narration", ""), s.get("visual_objective", ""), s.get("prompt", ""),
                        s.get("negative_prompt", ""), s.get("camera", ""), s.get("subject_motion", ""),
                        s.get("environment", ""), s.get("style", ""), float(s.get("duration_s") or 4),
                        int(bool(s.get("needs_image"))), s.get("image_prompt", ""), s.get("transition", "cut"),
                        dumps(s.get("settings") or {}), now,
                    ),
                )

    def update_scene(self, scene_id: int, **fields: Any) -> None:
        out = {}
        reverse = {v: k for k, v in _SCENE_JSON.items()}
        for k, v in fields.items():
            out[reverse[k] if k in reverse else k] = dumps(v) if k in reverse else v
        out["updated_at"] = utcnow()
        self.db.update("scenes", scene_id, out)

    def scene_dir(self, project: dict, scene: dict) -> Path:
        d = self.folder(project) / "scenes" / f"scene_{scene['idx'] + 1:02d}"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _num(v) -> float | None:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _text(v) -> str:
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return str(v or "")
