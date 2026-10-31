"""MiniMax H3 workflows (model matching, frame rule, auto-detect), settings
migration and the free local Kokoro voice."""

from __future__ import annotations

import json
import math
import os
import wave
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient

from studio.integrations.kokoro_tts import KokoroTTS, describe_voice
from studio.integrations.video.base import Capabilities
from studio.integrations.video.models import resolve_models
from studio.main import create_app

from .conftest import HEADERS, make_services

COMFY = "http://127.0.0.1:8188"


def combo(*files):
    return [list(files)]


def h3_object_info(unet=("minimax_h3_fl2va_pruned_int8_convrot.safetensors",), loras=(), gguf_unets=None,
                   clip=("qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",),
                   vae=("minimax_h3_video_vae_int8_convrot.safetensors", "minimax_h3_audio_vae_fp32.safetensors")):
    info = {
        "UNETLoader": {"input": {"required": {"unet_name": combo(*unet), "weight_dtype": combo("default")}}},
        "CLIPLoader": {"input": {"required": {"clip_name": combo(*clip), "type": combo("wan", "minimax")},
                                 "optional": {"device": combo("default", "cpu")}}},
        "VAELoader": {"input": {"required": {"vae_name": combo(*vae)}}},
        "LoraLoaderModelOnly": {"input": {"required": {"lora_name": combo(*loras), "strength_model": ["FLOAT", {}]}}},
        "LoadImage": {"input": {"required": {"image": combo("example.png")}}},
    }
    for n in ("MiniMaxH3ImageToVideo", "RandomNoise", "KSamplerSelect", "BasicScheduler", "BasicGuider",
              "SamplerCustomAdvanced", "VAEDecode", "CreateVideo", "SaveVideo"):
        info[n] = {"input": {"required": {}}}
    if gguf_unets is not None:
        info["UnetLoaderGGUF"] = {"input": {"required": {"unet_name": combo(*gguf_unets)}}}
    return info


# -- model matching -----------------------------------------------------------------
def test_exact_files_are_kept(services):
    wf, report = resolve_models(services.workflows.get("minimax_h3_t2v"), h3_object_info())
    assert all(r["chosen"] == r["expected"] for r in report)
    assert wf["workflow"]["1"]["class_type"] == "UNETLoader"


def test_other_variants_are_matched(services):
    info = h3_object_info(unet=("wan2.2_ti2v_5B_fp16.safetensors", "minimax_h3_r2va_fp8.safetensors",
                                "MiniMax-H3-FL2VA-fp8_e4m3fn.safetensors"),
                          clip=("umt5_xxl_fp8_e4m3fn_scaled.safetensors", "qwen3vl_32b_minimax_h3_fp8.safetensors"),
                          vae=("minimax_h3_audio_vae_fp32.safetensors", "minimax_h3_video_vae_bf16.safetensors"))
    wf, report = resolve_models(services.workflows.get("minimax_h3_t2v"), info)
    chosen = {r["label"]: r["chosen"] for r in report}
    assert chosen["H3 video model"] == "MiniMax-H3-FL2VA-fp8_e4m3fn.safetensors"  # not the R2VA or Wan file
    assert chosen["H3 text encoder"] == "qwen3vl_32b_minimax_h3_fp8.safetensors"
    assert chosen["H3 video VAE"] == "minimax_h3_video_vae_bf16.safetensors"  # never the audio VAE
    assert wf["workflow"]["1"]["inputs"]["unet_name"] == chosen["H3 video model"]


def test_gguf_model_swaps_loader(services):
    info = h3_object_info(unet=("wan2.2_ti2v_5B_fp16.safetensors",), gguf_unets=("minimax-h3-fl2va-Q4_K_M.gguf",))
    wf, report = resolve_models(services.workflows.get("minimax_h3_t2v"), info)
    node = wf["workflow"]["1"]
    assert node["class_type"] == "UnetLoaderGGUF" and node["inputs"] == {"unet_name": "minimax-h3-fl2va-Q4_K_M.gguf"}
    assert report[0]["gguf"] is True


def test_missing_model_reported_with_gguf_hint(services, router):
    router.add("GET", f"{COMFY}/object_info", httpx.Response(200, json=h3_object_info(unet=("other.safetensors",))))
    res = anyio.run(services.comfyui().check_workflow, "minimax_h3_t2v")
    assert res.status == "error"
    assert "H3 video model" in res.detail and "ComfyUI-GGUF" in res.detail


def test_h3_frame_rule_and_bindings(services):
    caps = services.comfyui().capabilities("minimax_h3_t2v")
    assert (caps.width, caps.height, caps.fps, caps.frame_multiple, caps.frame_offset) == (480, 864, 24, 17, 5)
    assert caps.frames_for(2) == 56  # 48 frames -> next 17n+5, same as ComfyUI's template formula
    assert caps.frames_for(5) == 124 and caps.frames_for(30) == 124  # capped at max frames
    assert Capabilities("video", "t2v", 1, 1, 24, 121, frame_multiple=4).frames_for(2) == 49


def test_h3_submit_uses_installed_files(services, router, tmp_path):
    from studio.integrations.video.base import GenerationRequest

    sent = {}
    router.add("GET", f"{COMFY}/object_info", httpx.Response(200, json=h3_object_info(
        loras=("minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",),
        unet=("minimax_h3_fl2va_fp8.safetensors",))))
    router.add("POST", f"{COMFY}/prompt", lambda r: (sent.update(json.loads(r.content)),
                                                     httpx.Response(200, json={"prompt_id": "p1"}))[1])
    req = GenerationRequest(kind="video", workflow="minimax_h3_t2v_turbo", prompt="a red ball", negative_prompt="",
                            width=480, height=864, seed=3, out_dir=tmp_path, filename_prefix="clip", num_frames=56, fps=24)
    assert anyio.run(services.comfyui().submit, req) == "p1"
    g = sent["prompt"]
    assert g["1"]["inputs"]["unet_name"] == "minimax_h3_fl2va_fp8.safetensors"
    assert g["4"]["inputs"]["prompt"] == "a red ball" and g["4"]["inputs"]["length"] == 56
    assert g["7"]["inputs"]["steps"] == 8 and g["7"]["inputs"]["model"] == ["13", 0]  # turbo LoRA in the chain
    assert g["5"]["inputs"]["noise_seed"] == 3
    assert g["12"]["inputs"]["format"] == "auto" and g["12"]["inputs"]["format.codec"] == "auto"


def test_autodetect_prefers_h3_turbo_then_h3_then_wan(services, router):
    from studio.api.integrations import autodetect_workflows

    services.settings.update({"generation": {"video_workflow": "wan22_ti2v_5b_t2v"}})
    info = h3_object_info()  # H3 installed, but no turbo LoRA
    router.add("GET", f"{COMFY}/object_info", httpx.Response(200, json=info))
    result = anyio.run(lambda: autodetect_workflows(services, force=True))
    assert result["video_workflow"] == "minimax_h3_t2v"
    assert services.settings.get().generation.i2v_workflow == "minimax_h3_i2v"
    info2 = h3_object_info(loras=("minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",))
    services.comfyui()._object_info = None
    router.add("GET", f"{COMFY}/object_info", httpx.Response(200, json=info2))
    result = anyio.run(lambda: autodetect_workflows(services, force=True))
    assert result["video_workflow"] == "minimax_h3_t2v_turbo"


def test_autodetect_leaves_settings_alone_when_comfyui_is_off(services):
    from studio.api.integrations import autodetect_workflows

    before = services.settings.get().generation.video_workflow
    result = anyio.run(lambda: autodetect_workflows(services, force=True))
    assert result["changed"] is False and services.settings.get().generation.video_workflow == before


# -- settings migration ------------------------------------------------------------------
def test_old_settings_move_to_free_voice_and_h3(home, router):
    s1 = make_services(home, router)
    s1.db.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES ('app', ?, 'x')",
        (json.dumps({"narration": {"provider": "fish_audio", "voice_id": "abc"},
                     "generation": {"video_workflow": "wan22_ti2v_5b_t2v"}, "video": {"duration_s": 40}}),),
    )
    st = make_services(home, router).settings.get()
    assert st.narration.provider == "kokoro" and st.narration.voice_id == "abc"
    assert st.generation.video_workflow == "minimax_h3_t2v_turbo" and st.video.duration_s == 40
    assert st.settings_version == 2
    # Choosing Fish Audio again afterwards sticks.
    s3 = make_services(home, router)
    s3.settings.update({"narration": {"provider": "fish_audio"}})
    assert make_services(home, router).settings.get().narration.provider == "fish_audio"


# -- Kokoro -----------------------------------------------------------------------------------
class FakeKokoro:
    def get_voices(self):
        return ["af_heart", "am_michael", "bf_emma", "zf_xiaobei"]

    def create(self, text, voice, speed=1.0, lang="en-us"):
        import numpy as np

        n = int(24000 * min(6.0, 0.06 * len(text)))
        t = np.arange(n) / 24000
        return (0.3 * np.sin(2 * math.pi * 220 * t)).astype("float32"), 24000


def test_kokoro_synthesize_writes_wav_and_costs_nothing(services, tmp_path, monkeypatch):
    k = services.kokoro
    monkeypatch.setattr(k, "installed", lambda: True)
    monkeypatch.setattr(k, "_load", lambda: FakeKokoro())
    out = tmp_path / "n.wav"
    res = anyio.run(lambda: k.synthesize("Hello there, this is a test.", out, voice="am_michael"))
    with wave.open(str(out)) as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1 and w.getnframes() > 1000
    assert res["cost_usd"] == 0.0
    row = services.db.query_one("SELECT * FROM api_usage WHERE provider = 'kokoro'")
    assert row["ok"] == 1 and row["cost_usd"] == 0.0
    voices = k.voices()
    assert [v["id"] for v in voices][:1] == ["af_heart"] and all(v["id"][0] in "ab" for v in voices)
    with pytest.raises(Exception) as e:
        anyio.run(lambda: k.synthesize("Hi", out, voice="am_nobody"))
    assert "not in the Kokoro voice pack" in str(e.value)


def test_kokoro_download_rejects_truncated_files(tmp_path, monkeypatch, services):
    import studio.integrations.kokoro_tts as kt

    monkeypatch.setattr(kt, "FILES", {"kokoro-v1.0.int8.onnx": 1000, "voices-v1.0.bin": 500})
    calls = []

    def handler(req):
        calls.append(req.url.path)
        size = 2000 if req.url.path.endswith(".onnx") else 100  # voices file truncated
        return httpx.Response(200, content=b"x" * size)

    k = KokoroTTS(tmp_path / "kokoro", services.usage, httpx.MockTransport(handler))
    with pytest.raises(Exception):
        anyio.run(k.download)
    assert (tmp_path / "kokoro" / "kokoro-v1.0.int8.onnx").is_file()  # finished file kept
    assert not (tmp_path / "kokoro" / "voices-v1.0.bin").exists()
    assert k.download_state["status"] == "error"


def test_describe_voice():
    assert describe_voice("bm_george")["label"] == "George (British male)"


@pytest.mark.skipif(not os.environ.get("KOKORO_MODEL_DIR"), reason="set KOKORO_MODEL_DIR to run real Kokoro")
def test_real_kokoro_voice(tmp_path, services):
    k = KokoroTTS(Path(os.environ["KOKORO_MODEL_DIR"]), services.usage)
    out = tmp_path / "real.wav"
    res = anyio.run(lambda: k.synthesize("Why is the sky blue?", out, voice="af_heart"))
    assert res["seconds"] > 0.5 and out.stat().st_size > 20000


def test_voice_api_endpoints(services, monkeypatch):
    monkeypatch.setattr(services.kokoro, "installed", lambda: True)
    monkeypatch.setattr(services.kokoro, "_load", lambda: FakeKokoro())
    app = create_app(services=services, start_worker=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        v = c.get("/api/integrations/kokoro/voices").json()
        assert v["installed"] and v["voices"][0]["id"] == "af_heart"
        r = c.post("/api/integrations/kokoro/preview", json={"voice": "bf_emma"}, headers=HEADERS)
        assert r.status_code == 200
        audio = c.get(r.json()["url"])
        assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
        assert c.get("/api/voice-preview/../studio.db").status_code in (400, 404)
        bad = c.post("/api/integrations/kokoro/preview", json={"voice": "../../x"}, headers=HEADERS)
        assert bad.status_code == 422


def test_full_video_with_free_voice(home, router, monkeypatch):
    """Idea → finished MP4 using the local voice (fake engine) instead of Fish Audio."""
    from .conftest import install_fake_providers, needs_ffmpeg, wait_for  # noqa: F401
    from .test_pipeline_e2e import FAST_SETTINGS

    install_fake_providers(router)  # Groq only; no Fish Audio mock: it must not be called
    svc = make_services(home, router)
    svc.secrets.set("groq", "gsk_testkey_1234567890")
    monkeypatch.setattr(svc.kokoro, "installed", lambda: True)
    monkeypatch.setattr(svc.kokoro, "_load", lambda: FakeKokoro())
    app = create_app(services=svc)
    settings = {**FAST_SETTINGS, "general": {"automation_mode": "automated"},
                "gates": {"script": False, "scene_plan": False, "assembly": False},
                "narration": {"provider": "kokoro", "kokoro_voice": "bf_emma", "alignment": "heuristic"}}
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.patch("/api/settings", json=settings, headers=HEADERS).status_code == 200
        pid = c.post("/api/projects", json={"title": "Why sunsets are orange", "start": True}, headers=HEADERS).json()["id"]
        p = wait_for(lambda: (x := c.get(f"/api/projects/{pid}").json())["export_status"] in ("completed", "failed") and x,
                     timeout=180, message="export with free voice")
        assert p["export_status"] == "completed", [j["error_message"] for j in p["jobs"] if j["status"] == "failed"]
        assert p["narration"]["provider"] == "kokoro" and p["narration"]["path"].endswith(".wav")
        assert p["narration"]["voice_name"] == "Emma (British female)" and p["narration"]["cost_usd"] == 0.0
        assert p["qc"]["technical_ok"]
    assert not any("fish.audio" in str(r.url) for r in router.calls)
