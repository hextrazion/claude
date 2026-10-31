"""Match a workflow's model files to the files actually installed in ComfyUI.

Bundled workflows name the files ComfyUI's official template uses, but people
download other variants (INT8, FP8, BF16, or GGUF quants for the ComfyUI-GGUF
loaders). A workflow lists ``model_slots`` describing each model it needs;
this module picks the best installed file for each slot from ComfyUI's
``/object_info`` and, for GGUF files, swaps in the GGUF loader node.
"""

from __future__ import annotations

import copy
import re


def _compact(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _choices(object_info: dict, class_type: str, input_name: str) -> list[str] | None:
    spec = object_info.get(class_type)
    if not spec:
        return None
    inputs = {**(spec.get("input", {}).get("required") or {}), **(spec.get("input", {}).get("optional") or {})}
    s = inputs.get(input_name)
    if isinstance(s, list) and s and isinstance(s[0], list):
        return [str(c) for c in s[0]]
    # Newer ComfyUI: ["COMBO", {"options": [...]}]
    if isinstance(s, list) and len(s) > 1 and isinstance(s[1], dict) and isinstance(s[1].get("options"), list):
        return [str(c) for c in s[1]["options"]]
    return None


def _score(candidate: str, expected: str, slot: dict) -> float | None:
    c = _compact(candidate.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
    if any(_compact(t) not in c for t in slot.get("require", [])):
        return None
    any_of = slot.get("any_of") or []
    if any_of and not any(_compact(t) in c for t in any_of):
        return None
    if any(_compact(t) in c for t in slot.get("avoid", [])):
        return None
    score = 0.0
    for i, t in enumerate(slot.get("prefer", [])):
        if _compact(t) in c:
            score += 2.0 - i * 0.1  # earlier preferences weigh a little more
    exp_tokens = set(re.findall(r"[a-z0-9]+", expected.lower()))
    cand_tokens = set(re.findall(r"[a-z0-9]+", candidate.lower()))
    score += len(exp_tokens & cand_tokens) * 0.5
    return score


def _best(choices: list[str], expected: str, slot: dict) -> str | None:
    scored = [(s, c) for c in choices if (s := _score(c, expected, slot)) is not None]
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][1]


def resolve_models(wf: dict, object_info: dict) -> tuple[dict, list[dict]]:
    """Return a copy of ``wf`` with each model slot pointed at an installed file.

    The report has one entry per slot: label, expected file, chosen file (or
    None), and whether the GGUF loader was used.
    """
    wf = copy.deepcopy(wf)
    graph = wf["workflow"]
    report: list[dict] = []
    for slot in wf.get("model_slots") or []:
        node = graph.get(str(slot["node"]))
        if node is None:
            continue
        inp = slot["input"]
        expected = str((node.get("inputs") or {}).get(inp, ""))
        entry = {"label": slot.get("label", f"{node['class_type']}.{inp}"), "expected": expected, "chosen": None,
                 "gguf": False}
        choices = _choices(object_info, node["class_type"], inp)
        if choices is not None:
            if expected in choices:
                entry["chosen"] = expected
            else:
                entry["chosen"] = _best(choices, expected, slot)
        gguf_class = slot.get("gguf_class")
        if entry["chosen"] is None and gguf_class:
            gguf_choices = _choices(object_info, gguf_class, inp)
            if gguf_choices:
                pick = _best(gguf_choices, expected, slot)
                if pick:
                    old_inputs = node.get("inputs") or {}
                    allowed = set((object_info[gguf_class].get("input", {}).get("required") or {}).keys()) | set(
                        (object_info[gguf_class].get("input", {}).get("optional") or {}).keys())
                    node["class_type"] = gguf_class
                    node["inputs"] = {k: v for k, v in old_inputs.items() if k in allowed or isinstance(v, list)}
                    entry["chosen"], entry["gguf"] = pick, True
        if entry["chosen"] is not None:
            node.setdefault("inputs", {})[inp] = entry["chosen"]
        entry["gguf_loader_available"] = bool(gguf_class and gguf_class in object_info)
        report.append(entry)
    return wf, report
