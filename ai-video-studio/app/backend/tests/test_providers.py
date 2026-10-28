"""Provider adapters against mocked HTTP: error mapping, parsing, ComfyUI flow."""

from __future__ import annotations

import json

import anyio
import httpx
import pytest

from studio.errors import Cancelled, ProviderError
from studio.integrations.groq import parse_json_object
from studio.integrations.video.base import GenerationRequest
from studio.integrations.video.workflows import apply_bindings, build_imported, detect_bindings

GROQ = "https://api.groq.com/openai/v1"
COMFY = "http://127.0.0.1:8188"


def run(coro_fn, *args, **kw):
    return anyio.run(lambda: coro_fn(*args, **kw))


def test_groq_missing_key_is_not_configured(services):
    with pytest.raises(ProviderError) as e:
        run(services.groq.chat_json, [{"role": "user", "content": "x"}], model="m", operation="test")
    assert e.value.kind == "not_configured"
    assert run(services.groq.test).status == "not_configured"


def test_groq_invalid_key(services, router):
    services.secrets.set("groq", "gsk_invalid_000000000")
    router.add("GET", f"{GROQ}/models", httpx.Response(401, json={"error": {"message": "Invalid API Key"}}))
    router.add("POST", f"{GROQ}/chat/completions", httpx.Response(401, json={"error": {"message": "Invalid API Key"}}))
    health = run(services.groq.test)
    assert health.status == "error" and "rejected the API key" in health.message
    with pytest.raises(ProviderError) as e:
        run(services.groq.chat_json, [{"role": "user", "content": "json"}], model="m", operation="script")
    assert e.value.kind == "auth" and not e.value.retryable
    row = services.db.query_one("SELECT * FROM api_usage ORDER BY id DESC")
    assert row["ok"] == 0 and row["status_code"] == 401


def test_groq_rate_limit_is_retryable_with_retry_after(services, router):
    services.secrets.set("groq", "gsk_valid_00000000000")
    router.add("POST", f"{GROQ}/chat/completions",
               httpx.Response(429, json={"error": {"message": "Rate limit"}}, headers={"retry-after": "17"}))
    with pytest.raises(ProviderError) as e:
        run(services.groq.chat_json, [{"role": "user", "content": "json"}], model="m", operation="ideas")
    assert e.value.kind == "rate_limit" and e.value.retryable and e.value.retry_after == 17


def test_groq_decommissioned_model(services, router):
    services.secrets.set("groq", "gsk_valid_00000000000")
    router.add("POST", f"{GROQ}/chat/completions",
               httpx.Response(400, json={"error": {"message": "The model `x` has been decommissioned", "code": "model_decommissioned"}}))
    with pytest.raises(ProviderError) as e:
        run(services.groq.chat_json, [{"role": "user", "content": "json"}], model="x", operation="ideas")
    assert e.value.kind == "invalid_request" and "Settings" in e.value.message


def test_groq_json_retry_then_success(services, router):
    services.secrets.set("groq", "gsk_valid_00000000000")
    replies = iter(["not json at all", '```json\n{"ok": true}\n```'])

    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 5}})

    router.add("POST", f"{GROQ}/chat/completions", handler)
    assert run(services.groq.chat_json, [{"role": "user", "content": "json"}], model="m", operation="t") == {"ok": True}
    body = json.loads(router.calls[-1].content)
    assert body["response_format"] == {"type": "json_object"}


def test_parse_json_object():
    assert parse_json_object('prefix {"a": 1} suffix') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json_object("[1, 2]")


def test_fish_insufficient_credit(services, router, tmp_path):
    services.secrets.set("fish_audio", "fish_key_0000000000")
    router.add("POST", "https://api.fish.audio/v1/tts", httpx.Response(402, json={"message": "Insufficient balance"}))
    with pytest.raises(ProviderError) as e:
        run(services.fish.synthesize, "Hello", tmp_path / "a.mp3", voice_id="v", model="s2-pro")
    assert e.value.kind == "quota" and "credit" in e.value.message.lower()
    assert not (tmp_path / "a.mp3").exists() and not (tmp_path / "a.mp3.part").exists()


def test_fish_requires_voice(services, tmp_path):
    services.secrets.set("fish_audio", "fish_key_0000000000")
    with pytest.raises(ProviderError) as e:
        run(services.fish.synthesize, "Hello", tmp_path / "a.mp3", voice_id="", model="s2-pro")
    assert e.value.kind == "invalid_request"


def test_fish_request_shape_and_voices(services, router, tmp_path):
    services.secrets.set("fish_audio", "fish_key_0000000000")
    router.add("POST", "https://api.fish.audio/v1/tts", httpx.Response(200, content=b"ID3" + b"\x00" * 5000))
    router.add("GET", "https://api.fish.audio/model", httpx.Response(200, json={
        "total": 1, "items": [{"_id": "abc", "title": "Narrator", "languages": ["en"], "tags": ["calm"]}]}))
    res = run(services.fish.synthesize, "Hello world", tmp_path / "a.mp3", voice_id="abc", model="s2-pro", speed=1.1)
    req = router.calls[-1]
    body = json.loads(req.content)
    assert req.headers["model"] == "s2-pro" and req.headers["authorization"] == "Bearer fish_key_0000000000"
    assert body["reference_id"] == "abc" and body["prosody"]["speed"] == 1.1 and body["format"] == "mp3"
    assert res["characters"] == 11 and (tmp_path / "a.mp3").stat().st_size > 1000
    voices = run(services.fish.list_voices, mine=True)
    assert voices["items"][0]["id"] == "abc"
    assert "self=true" in str(router.calls[-1].url)


# -- ComfyUI ------------------------------------------------------------------------
def _comfy_req(tmp_path, workflow="wan22_ti2v_5b_t2v"):
    return GenerationRequest(kind="video", workflow=workflow, prompt="a red ball", negative_prompt="blur", width=704,
                             height=1280, seed=7, out_dir=tmp_path, filename_prefix="clip_x", num_frames=81, fps=24)


def test_comfyui_submit_wait_collect(services, router, tmp_path):
    submitted = {}

    def prompt(req):
        submitted.update(json.loads(req.content))
        return httpx.Response(200, json={"prompt_id": "pid-1", "number": 1})

    history = {"pid-1": {"status": {"status_str": "success", "completed": True},
                         "outputs": {"58": {"images": [{"filename": "clip_00001_.mp4", "subfolder": "ai_video_studio", "type": "output"}]}}}}
    router.add("POST", f"{COMFY}/prompt", prompt)
    router.add("GET", f"{COMFY}/history/pid-1", httpx.Response(200, json=history))
    router.add("GET", f"{COMFY}/view", httpx.Response(200, content=b"\x00" * 2048))
    adapter = services.comfyui()

    async def go():
        pid = await adapter.submit(_comfy_req(tmp_path))
        async def prog(f, m):
            pass
        return await adapter.wait(pid, _comfy_req(tmp_path), prog, lambda: False, 30)

    adapter._listen_progress = lambda pid: anyio.sleep(0)  # no websocket in tests
    result = anyio.run(go)
    graph = submitted["prompt"]
    assert graph["6"]["inputs"]["text"] == "a red ball"
    assert graph["7"]["inputs"]["text"] == "blur"
    assert graph["55"]["inputs"]["length"] == 81 and graph["55"]["inputs"]["width"] == 704
    assert graph["3"]["inputs"]["seed"] == 7
    assert graph["58"]["inputs"]["filename_prefix"] == "ai_video_studio/clip_x"
    assert result.files[0].name == "clip_x.mp4" and result.files[0].stat().st_size == 2048


def test_comfyui_out_of_memory_is_reported(services, router, tmp_path):
    hist = {"p": {"status": {"status_str": "error", "messages": [["execution_error", {
        "exception_type": "torch.OutOfMemoryError", "exception_message": "CUDA out of memory. Tried to allocate 2 GiB",
        "node_type": "KSampler"}]]}, "outputs": {}}}
    router.add("GET", f"{COMFY}/history/p", httpx.Response(200, json=hist))
    adapter = services.comfyui()
    adapter._listen_progress = lambda pid: anyio.sleep(0)

    async def go():
        async def prog(f, m):
            pass
        await adapter.wait("p", _comfy_req(tmp_path), prog, lambda: False, 30)

    with pytest.raises(ProviderError) as e:
        anyio.run(go)
    assert e.value.kind == "oom" and not e.value.retryable and "lower resolution" in e.value.message


def test_comfyui_cancel_interrupts_only_our_prompt(services, router, tmp_path):
    router.add("GET", f"{COMFY}/history/mine", httpx.Response(200, json={}))
    router.add("GET", f"{COMFY}/queue", httpx.Response(200, json={"queue_running": [[0, "mine", {}, {}, []]], "queue_pending": []}))
    router.add("POST", f"{COMFY}/interrupt", httpx.Response(200, json={}))
    adapter = services.comfyui()
    adapter._listen_progress = lambda pid: anyio.sleep(0)

    async def go():
        async def prog(f, m):
            pass
        await adapter.wait("mine", _comfy_req(tmp_path), prog, lambda: True, 30)

    with pytest.raises(Cancelled):
        anyio.run(go)
    interrupt = [c for c in router.calls if c.url.path == "/interrupt"]
    assert interrupt and json.loads(interrupt[0].content) == {"prompt_id": "mine"}


def test_comfyui_unreachable(services):
    health = run(services.comfyui().health)
    assert health.status == "unavailable" and "Start ComfyUI" in health.message


def test_check_workflow_reports_missing_nodes_and_models(services, router):
    object_info = {
        "UNETLoader": {"input": {"required": {"unet_name": [["other_model.safetensors"]], "weight_dtype": [["default"]]}}},
        "CLIPLoader": {"input": {"required": {"clip_name": [["umt5_xxl_fp8_e4m3fn_scaled.safetensors"]]}}},
        "VAELoader": {"input": {"required": {"vae_name": [["wan2.2_vae.safetensors"]]}}},
        "ModelSamplingSD3": {"input": {}}, "CLIPTextEncode": {"input": {}}, "KSampler": {"input": {}},
        "VAEDecode": {"input": {}}, "CreateVideo": {"input": {}}, "SaveVideo": {"input": {}},
    }
    router.add("GET", f"{COMFY}/object_info", httpx.Response(200, json=object_info))
    res = run(services.comfyui().check_workflow, "wan22_ti2v_5b_t2v")
    assert res.status == "error"
    assert "Wan22ImageToVideoLatent" in res.info["missing_nodes"]
    assert any("wan2.2_ti2v_5B_fp16" in f for f in res.info["missing_files"])


def test_detect_bindings_from_exported_graph(services):
    wf = services.workflows.get("wan22_ti2v_5b_i2v")
    bindings, warnings = detect_bindings(wf["workflow"])
    assert bindings["prompt"] == [{"node": "6", "input": "text"}]
    assert bindings["negative_prompt"] == [{"node": "7", "input": "text"}]
    assert {"node": "55", "input": "length"} in bindings["frames"]
    assert bindings["image"] == [{"node": "56", "input": "image"}]
    imported = build_imported("my_wf", "Mine", "video", "i2v", wf["workflow"])
    assert imported["defaults"]["max_frames"] == 121
    graph = apply_bindings(imported, {"prompt": "hello", "seed": 3})
    assert graph["6"]["inputs"]["text"] == "hello" and wf["workflow"]["6"]["inputs"]["text"] == ""


def test_detect_bindings_rejects_ui_format():
    from studio.errors import ValidationFailed

    with pytest.raises(ValidationFailed):
        detect_bindings({"nodes": [], "links": []})
