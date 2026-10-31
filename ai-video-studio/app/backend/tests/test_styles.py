"""Style library: references, analysis (colours, pacing, vision), and applying a style."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient

from studio.integrations.video.base import GenerationRequest
from studio.main import create_app

from .conftest import HEADERS, make_services, needs_ffmpeg, wait_for
from .test_h3_and_voice import h3_object_info

GROQ = "https://api.groq.com/openai/v1"
COMFY = "http://127.0.0.1:8188"


def _png(path: Path, colour=(230, 90, 30)) -> Path:
    from PIL import Image

    Image.new("RGB", (320, 180), colour).save(path)
    return path


def _cutting_video(path: Path) -> Path:
    """4 s video with a hard cut every second (alternating colours)."""
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=1:r=24",
         "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=1:r=24", "-f", "lavfi", "-i", "color=c=green:s=320x180:d=1:r=24",
         "-f", "lavfi", "-i", "color=c=white:s=320x180:d=1:r=24",
         "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True)
    return path


def _client(home, router):
    svc = make_services(home, router)
    return svc, TestClient(create_app(services=svc), base_url="http://127.0.0.1")


def _upload(c, sid, path: Path):
    with path.open("rb") as fh:
        r = c.post(f"/api/styles/{sid}/references", files={"file": (path.name, fh)}, headers=HEADERS)
    assert r.status_code == 200, r.text
    return r.json()


def _groq_models(*ids):
    return httpx.Response(200, json={"data": [{"id": i} for i in ids]})


@needs_ffmpeg
def test_analyse_style_with_vision_model(home, router, tmp_path):
    seen = {}

    def chat(req):
        body = json.loads(req.content)
        seen["body"] = body
        content = {"name": "Neon claymation", "summary": "Soft clay figures under neon light.",
                   "style_prompt": "stop-motion claymation, soft fingerprints in clay, saturated neon rim light, "
                                   "shallow depth of field, handmade miniature sets",
                   "avoid": "photorealism, flat vector art", "camera": "slow push-ins", "motion": "slightly stepped",
                   "mood": "playful, warm", "uses_onscreen_text": False}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 900, "completion_tokens": 120}})

    router.add("GET", f"{GROQ}/models", _groq_models("llama-3.3-70b-versatile", "meta-llama/llama-4-scout-17b-16e-instruct"))
    router.add("POST", f"{GROQ}/chat/completions", chat)
    svc, c = _client(home, router)
    svc.secrets.set("groq", "gsk_test_000000000000")
    with c:
        sid = c.post("/api/styles", json={"name": "New style"}, headers=HEADERS).json()["id"]
        _upload(c, sid, _png(tmp_path / "frame.png"))
        st = _upload(c, sid, _cutting_video(tmp_path / "clip.mp4"))
        assert [r["kind"] for r in st["refs"]] == ["image", "video"] and st["refs"][0]["key"] is True
        c.post(f"/api/styles/{sid}/analyze", headers=HEADERS)
        st = wait_for(lambda: (x := c.get(f"/api/styles/{sid}").json())["status"] in ("ready", "failed") and x,
                      timeout=90, message="style analysis")
        assert st["status"] == "ready", st.get("error")
        p = st["profile"]
        assert st["name"] == "Neon claymation" and "claymation" in p["style_prompt"]
        assert p["vision_model"] == "meta-llama/llama-4-scout-17b-16e-instruct"
        assert p["pacing"]["avg_shot_s"] == pytest.approx(1.0, abs=0.35)  # one cut per second
        assert p["palette"] and all(h.startswith("#") for h in p["palette"])
        assert len(st["refs"][1]["frames"]) == 6
        parts = seen["body"]["messages"][1]["content"]
        images = [x for x in parts if x["type"] == "image_url"]
        assert 1 <= len(images) <= 5 and images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        # Thumbnails are served from the style folder only.
        assert c.get(f"/api/style-files/{sid}/{st['refs'][0]['file']}").status_code == 200
        assert c.get(f"/api/style-files/{sid}/../../studio.db").status_code in (400, 404)
        # Adding a reference keeps the style usable but flags it for re-analysis.
        st = _upload(c, sid, _png(tmp_path / "more.png", (20, 20, 200)))
        assert st["status"] == "ready" and st["profile"]["stale"] is True


@needs_ffmpeg
def test_analyse_without_vision_model_uses_description(home, router, tmp_path):
    router.add("GET", f"{GROQ}/models", _groq_models("llama-3.3-70b-versatile"))
    svc, c = _client(home, router)
    svc.secrets.set("groq", "gsk_test_000000000000")
    with c:
        sid = c.post("/api/styles", json={"name": "Chalk", "notes": "chalkboard drawings, white chalk on dark green"},
                     headers=HEADERS).json()["id"]
        _upload(c, sid, _png(tmp_path / "a.png", (20, 60, 40)))
        c.post(f"/api/styles/{sid}/analyze", headers=HEADERS)
        st = wait_for(lambda: (x := c.get(f"/api/styles/{sid}").json())["status"] in ("ready", "failed") and x,
                      timeout=60, message="fallback analysis")
        assert st["status"] == "ready" and st["profile"]["vision_model"] is None
        assert "chalkboard" in st["profile"]["style_prompt"]


def test_hand_written_style_and_delete(home, router):
    svc, c = _client(home, router)
    with c:
        sid = c.post("/api/styles", json={"name": "Paper cut"}, headers=HEADERS).json()["id"]
        r = c.post(f"/api/styles/{sid}/default", headers=HEADERS)
        assert r.status_code == 400  # not ready yet
        st = c.patch(f"/api/styles/{sid}", json={"style_prompt": "layered paper cut-out dioramas, soft shadows"},
                     headers=HEADERS).json()
        assert st["status"] == "ready"
        assert c.post(f"/api/styles/{sid}/default", headers=HEADERS).json()["is_default"] is True
        assert svc.settings.get().generation.style_id == sid
        bad = c.request("DELETE", f"/api/styles/{sid}", json={"confirm": "nope"}, headers=HEADERS)
        assert bad.status_code == 400
        assert c.request("DELETE", f"/api/styles/{sid}", json={"confirm": "Paper cut"}, headers=HEADERS).status_code == 200
        assert svc.settings.get().generation.style_id == 0


def test_rejects_unsupported_files(home, router, tmp_path):
    svc, c = _client(home, router)
    with c:
        sid = c.post("/api/styles", json={"name": "X"}, headers=HEADERS).json()["id"]
        bad = tmp_path / "notes.exe"
        bad.write_bytes(b"MZ")
        with bad.open("rb") as fh:
            r = c.post(f"/api/styles/{sid}/references", files={"file": (bad.name, fh)}, headers=HEADERS)
        assert r.status_code == 400


def test_style_reaches_planner_and_prompts(home, router):
    from studio.pipeline.stages import _active_style
    from studio.pipeline.prompts import compose_video_prompt

    svc = make_services(home, router)
    st = svc.styles.create("Ink wash")
    svc.styles.update(st["id"], status="ready", profile={
        "style_prompt": "sumi-e ink wash painting, wet brush edges, rice paper texture",
        "summary": "Monochrome ink.", "pacing": {"avg_shot_s": 2.5, "cuts_per_10s": 4}, "avoid": "neon colours"})
    svc.settings.update({"generation": {"style_id": st["id"]}})
    text, guide = _active_style(svc, svc.settings.get().generation)
    assert "sumi-e" in text and "2.5 s" in guide and "neon" in guide
    prompt = compose_video_prompt({"prompt": "a whale"}, "", text)
    assert prompt.startswith("a whale") and "sumi-e" in prompt


def test_reference_images_go_to_h3_reference_mode(services, router, tmp_path):
    info = h3_object_info(unet=("minimax_h3_ref2va_pruned_int8_convrot.safetensors", "minimax_h3_fl2va_int8.safetensors"),
                          loras=("minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",))
    info["MiniMaxH3ReferenceToVideo"] = {"input": {"required": {}}}
    sent, uploads = {}, []
    router.add("GET", f"{COMFY}/object_info", httpx.Response(200, json=info))
    router.add("POST", f"{COMFY}/upload/image",
               lambda r: (uploads.append(1), httpx.Response(200, json={"name": f"ref{len(uploads)}.png", "subfolder": ""}))[1])
    router.add("POST", f"{COMFY}/prompt", lambda r: (sent.update(json.loads(r.content)),
                                                     httpx.Response(200, json={"prompt_id": "r1"}))[1])
    assert anyio.run(services.comfyui().check_workflow, "minimax_h3_r2v_turbo").status == "ok"
    refs = [_png(tmp_path / f"k{i}.png") for i in range(2)]
    req = GenerationRequest(kind="video", workflow="minimax_h3_r2v_turbo", prompt="Visual style reference: <Picture 1> <Picture 2>. a fox",
                            negative_prompt="", width=480, height=864, seed=1, out_dir=tmp_path, filename_prefix="c",
                            num_frames=73, fps=24, ref_images=refs)
    assert anyio.run(services.comfyui().submit, req) == "r1"
    g = sent["prompt"]
    assert g["1"]["inputs"]["unet_name"] == "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
    assert g["4"]["class_type"] == "MiniMaxH3ReferenceToVideo" and g["4"]["inputs"]["prompt"].endswith("a fox")
    assert g["4"]["inputs"]["ref_images.ref_image_0"] == ["ref_load_0", 0]
    assert g["ref_load_1"] == {"class_type": "LoadImage", "inputs": {"image": "ref2.png"}}
    assert g["7"]["inputs"]["steps"] == 4 and len(uploads) == 2


def test_t2v_never_picks_the_reference_model(services):
    from studio.integrations.video.models import resolve_models

    info = h3_object_info(unet=("minimax_h3_ref2va_pruned_int8_convrot.safetensors",))
    _, report = resolve_models(services.workflows.get("minimax_h3_t2v"), info)
    assert report[0]["chosen"] is None  # Ref2VA is not a text-to-video model


def test_colours_become_words_for_the_video_model():
    from studio.styles import colour_words, profile_from_notes

    assert colour_words(["#F0C078", "#181848", "#F00060", "#F2C47A"]) == ["sand", "navy", "crimson"]
    prompt = profile_from_notes("flat shapes", ["#181848"], None)["style_prompt"]
    assert "navy" in prompt and "#" not in prompt
