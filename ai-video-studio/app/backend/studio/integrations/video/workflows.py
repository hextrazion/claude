"""ComfyUI workflow templates and parameter bindings.

A workflow file is the API-format graph exported from ComfyUI ("Export (API)")
plus a ``bindings`` map telling the app which node inputs receive the prompt,
size, frame count, seed, etc. Templates live in ``config/workflows`` (bundled)
and ``data/workflows`` (imported by the user; these override bundled ones).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from ...errors import ValidationFailed
from ...safety import slugify

BINDABLE = ("prompt", "negative_prompt", "width", "height", "frames", "fps", "seed", "image", "filename_prefix")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")


def _validate_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise ValidationFailed("Workflow names may only contain lowercase letters, numbers, '-' and '_'.")
    return name


class WorkflowLibrary:
    def __init__(self, bundled_dir: Path, user_dir: Path):
        self.bundled_dir = bundled_dir
        self.user_dir = user_dir

    def _files(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for d in (self.bundled_dir, self.user_dir):
            if d.is_dir():
                for f in sorted(d.glob("*.json")):
                    found[f.stem] = f
        return found

    def list(self) -> list[dict]:
        out = []
        for name, path in self._files().items():
            try:
                wf = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                out.append({"name": name, "label": name, "error": f"unreadable: {exc}"})
                continue
            out.append({
                "name": name,
                "label": wf.get("label", name),
                "kind": wf.get("kind", "video"),
                "mode": wf.get("mode", "t2v"),
                "description": wf.get("description", ""),
                "defaults": wf.get("defaults", {}),
                "requirements": wf.get("requirements", {}),
                "bindings": wf.get("bindings", {}),
                "user": path.parent == self.user_dir,
            })
        return out

    def get(self, name: str) -> dict:
        _validate_name(name)
        path = self._files().get(name)
        if not path:
            raise ValidationFailed(f"Workflow '{name}' not found. Import it on the Integrations page.")
        wf = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(wf.get("workflow"), dict) or not wf["workflow"]:
            raise ValidationFailed(f"Workflow '{name}' has no graph.")
        return wf

    def save_user(self, name: str, data: dict) -> Path:
        name = _validate_name(slugify(name).replace("-", "_"))
        self.user_dir.mkdir(parents=True, exist_ok=True)
        path = self.user_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def delete_user(self, name: str) -> bool:
        _validate_name(name)
        path = self.user_dir / f"{name}.json"
        if path.is_file():
            path.unlink()
            return True
        return False


def apply_bindings(wf: dict, values: dict[str, Any]) -> dict:
    """Return a copy of the graph with bound inputs replaced by ``values``."""
    graph = copy.deepcopy(wf["workflow"])
    for key, targets in (wf.get("bindings") or {}).items():
        if key not in values or values[key] is None:
            continue
        for t in targets:
            node = graph.get(str(t["node"]))
            if node is None:
                raise ValidationFailed(f"Workflow binding '{key}' points to missing node {t['node']}.")
            node.setdefault("inputs", {})[t["input"]] = values[key]
    return graph


# -- import helpers ----------------------------------------------------------

def _links_to(graph: dict, node_id: str) -> list[tuple[str, str]]:
    """(consumer_node_id, input_name) pairs consuming any output of node_id."""
    out = []
    for nid, node in graph.items():
        for name, val in (node.get("inputs") or {}).items():
            if isinstance(val, list) and len(val) == 2 and str(val[0]) == str(node_id):
                out.append((nid, name))
    return out


def detect_bindings(graph: dict) -> tuple[dict, list[str]]:
    """Best-effort guess of bindings for an API-format graph exported from ComfyUI."""
    if not isinstance(graph, dict) or not graph:
        raise ValidationFailed("That file is not a ComfyUI API-format workflow (use 'Export (API)').")
    for nid, node in graph.items():
        if not isinstance(node, dict) or "class_type" not in node:
            raise ValidationFailed(
                "That looks like a UI-format workflow. In ComfyUI use Workflow → Export (API) and import that file."
            )
    b: dict[str, list[dict]] = {}
    warnings: list[str] = []

    text_nodes = [nid for nid, n in graph.items() if "text" in (n.get("inputs") or {})
                  and isinstance(n["inputs"]["text"], str) and "encode" in n["class_type"].lower()]
    pos, neg = [], []
    for nid in text_nodes:
        consumers = {name for _, name in _links_to(graph, nid)}
        title = (graph[nid].get("_meta") or {}).get("title", "").lower()
        if "negative" in consumers or "negative" in title:
            neg.append(nid)
        elif "positive" in consumers or "positive" in title or consumers:
            pos.append(nid)
    if not pos and text_nodes:
        pos = text_nodes[:1]
        neg = text_nodes[1:2]
    if pos:
        b["prompt"] = [{"node": n, "input": "text"} for n in pos]
    else:
        warnings.append("No prompt text node found.")
    if neg:
        b["negative_prompt"] = [{"node": n, "input": "text"} for n in neg]

    def bind_inputs(key: str, names: tuple[str, ...], need_int: bool = True):
        for nid, n in graph.items():
            for name in names:
                v = (n.get("inputs") or {}).get(name)
                if v is not None and not isinstance(v, list) and (not need_int or isinstance(v, (int, float))):
                    b.setdefault(key, []).append({"node": nid, "input": name})

    bind_inputs("width", ("width",))
    bind_inputs("height", ("height",))
    bind_inputs("frames", ("length", "num_frames", "frames", "frame_count"))
    bind_inputs("seed", ("seed", "noise_seed"))
    bind_inputs("fps", ("fps", "frame_rate"))
    for nid, n in graph.items():
        ct = n["class_type"]
        if ct in ("LoadImage",) and isinstance(n.get("inputs", {}).get("image"), str):
            b.setdefault("image", []).append({"node": nid, "input": "image"})
        if "filename_prefix" in (n.get("inputs") or {}):
            b.setdefault("filename_prefix", []).append({"node": nid, "input": "filename_prefix"})
    for key in ("width", "height", "frames", "seed"):
        if key not in b:
            warnings.append(f"No '{key}' input detected; the workflow's own value will be used.")
    if "filename_prefix" not in b:
        warnings.append("No save node with filename_prefix found; outputs may be hard to locate.")
    return b, warnings


def build_imported(name: str, label: str, kind: str, mode: str, graph: dict, defaults: dict | None = None) -> dict:
    bindings, warnings = detect_bindings(graph)
    d = {"width": 704, "height": 1280, "fps": 24, "max_frames": 121, "frame_multiple": 4}
    for key, targets in bindings.items():
        if key in ("width", "height", "fps") and targets:
            t = targets[0]
            d[key] = graph[t["node"]]["inputs"][t["input"]]
        if key == "frames" and targets:
            t = targets[0]
            d["max_frames"] = graph[t["node"]]["inputs"][t["input"]]
    d.update(defaults or {})
    return {
        "name": name,
        "label": label or name,
        "kind": kind,
        "mode": mode,
        "description": "Imported from ComfyUI.",
        "defaults": d,
        "bindings": bindings,
        "workflow": graph,
        "import_warnings": warnings,
    }
