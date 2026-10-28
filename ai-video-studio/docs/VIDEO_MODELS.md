# Local video models on a 12 GB RTX 4070 Ti

Status: **researched, not yet benchmarked on your PC.** The development environment had no GPU, so every number below comes from the model publishers or community reports (October 2026) and needs confirming with the benchmark procedure at the end. The app does not hardcode any model: it talks to ComfyUI through workflow files, so switching models is a settings change.

## Recommendation

| | Wan 2.2 TI2V‑5B (default) | LTX‑2.3 (GGUF, community) | LTX‑2.5 (22B, Aug 2026) |
|---|---|---|---|
| Fits 12 GB? | Yes: ComfyUI's native offloading runs it in ~8 GB | Reported on 12 GB with Q4_K_M GGUF + offloading | No official 12 GB tier. Official guidance conflicts (16 GB on the model page, 32 GB minimum on the requirements page). Only very low-bit community quants (e.g. Q2_K) target 12 GB, reportedly at low quality |
| Output | ~720p class (704×1280 vertical), 24 fps, up to 121 frames (~5 s) | Up to 1080p+ in theory; on 12 GB expect lower resolution | Highest quality of the three, plus generated audio (not needed here) |
| Text→video / image→video | Both (one model) | Both | Both |
| ComfyUI support | Native nodes, built-in template | Native LTX nodes + GGUF loader custom node | Native (per ComfyUI docs) |
| Licence | Apache 2.0 | LTX-2 community licence | LTX-2.x community licence (open weights, not OSI open source) |

**Default: Wan 2.2 TI2V‑5B.** It is the only option with a documented, supported configuration that fits your card without heroic offloading, it handles stylised 3D and educational motion well, and it does both text-to-video and image-to-video (useful for the optional still-image stage). Its weakness is length: about 5 s per clip, which the scene planner already accounts for (it is told the model's maximum clip length and splits narration accordingly).

**LTX-2.5:** don't reject it, but don't expect it to run well on 12 GB. Also note:
- The **NVFP4** builds target RTX 50-series (Blackwell) FP4 hardware. The 4070 Ti (Ada) has FP8 but not FP4 tensor cores, so prefer **int8/FP8** or **GGUF** variants.
- The text encoder alone is a 12B Gemma model; with 32 GB of system RAM, offloading both the encoder and a quantised transformer is possible but slow.
- Worth re-testing when you have a 16–24 GB GPU or move generation to a homelab box with a bigger card.

**LTX-2.3 GGUF** is the realistic LTX option today on 12 GB: community workflows labelled “12 GB VRAM” use Q4_K_M dev GGUF plus a distilled LoRA. Treat it as an experiment against Wan, not a guaranteed upgrade.

## MiniMax H3 (open weights, Aug 2026)

Usable through ComfyUI's native H3 support. Use the **FL2VA** checkpoint (text-to-video / first-last frame); Ref2VA isn't needed.

- **Licence:** MiniMax H3 Community License. Users in the US, UK, EU and South Korea must apply to MiniMax before use. Check this before publishing anything made with it.
- **12 GB:** community reports say it runs with the pruned INT8 file (~21 GB on disk, offloaded) or GGUF Q3/Q4 (needs the ComfyUI-GGUF nodes), 32 GB system RAM, at about 0.4 MP (≈480×832), roughly 6 min per clip. One RTX 5090 test measured ~32 GB peak VRAM, so 12 GB is unconfirmed. Skip NVFP4 files (no FP4 hardware on the 4070 Ti).
- **Output:** open weights top out at 768p; the studio scales to 1080×1920. H3's own generated audio is discarded (the Fish Audio narration is used).

Setup: run the ComfyUI H3 template once by hand → **Export (API)** → Integrations → **Import from ComfyUI** → select it as the text-to-video workflow → **Check** → generate one scene and compare with Wan. The importer handles models that take clip length in seconds instead of frames, keeps integer inputs as integers, and the scene planner gets H3-specific prompting advice automatically (it recognises H3 from the workflow's node types, whatever you name it).

## Frame settings for any workflow

Each video workflow has **Edit frames** on the Integrations page: width, height, fps, max frames per clip and the frame-count rule (any, 2n+1, 4n+1, 8n+1, 16n+1). The importer guesses the rule (LTX → 8n+1, Wan → 4n+1, otherwise the strictest rule the exported frame count already satisfies). If ComfyUI rejects a frame count, change the rule there. Requested frame counts are rounded **up** to the rule (capped at the maximum), so clips are never shorter than needed because of rounding. Editing a bundled workflow saves a customised copy; the reset button restores the original.

## Installing the default (Wan 2.2 TI2V‑5B)

Into `ComfyUI/models/`:

| File | Folder |
|---|---|
| `wan2.2_ti2v_5B_fp16.safetensors` (~10 GB) | `diffusion_models/` |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` (~6.7 GB) | `text_encoders/` |
| `wan2.2_vae.safetensors` | `vae/` |

Source: [Comfy-Org/Wan_2.2_ComfyUI_Repackaged](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged) (the text encoder is in the Wan 2.1 repackaged repo). ComfyUI's template browser (Workflow → Browse Templates → Video → Wan 2.2 5B) links the same files.

The bundled `config/workflows/wan22_ti2v_5b_t2v.json` mirrors that template (UNETLoader → ModelSamplingSD3 shift 8 → KSampler uni_pc/simple, 30 steps, CFG 5 → VAEDecode → CreateVideo → SaveVideo). Press **Check** on the Integrations page: it compares every node and model file with your ComfyUI's `/object_info`. If anything differs, export the template from ComfyUI in API format and import it; the importer finds the prompt, negative prompt, width/height, frame count, seed, fps, image and filename inputs automatically.

## Tuning for speed vs quality

Edit an imported workflow's defaults (or change the template in ComfyUI and re-import):

- **Frames:** Wan wants 4n+1 frames (the app snaps to that). 81 frames ≈ 3.4 s is noticeably faster than 121.
- **Resolution:** 704×1280 is native. 544×960 cuts time roughly in half; final export is upscaled to 1080×1920 by FFmpeg (soft but acceptable for drafts).
- **Steps:** 30 is the template default; 20 is a reasonable draft setting.
- Keep **one GPU job at a time** (default). Two video models will not fit in 12 GB together.
- Close GPU-heavy apps (games, browsers with hardware acceleration) before long runs, or list them under *Hold GPU jobs while these programs run*.

Out-of-memory errors are detected and reported as such (they are not retried automatically, because retrying with the same settings fails again).

## Benchmark procedure (do this once on your PC)

1. In ComfyUI, run the Wan 2.2 5B template once manually to download/compile anything it needs.
2. In the studio, create a project from a simple topic, approve the script and plan, then generate **one** scene.
3. Record from the scene's clip details and the Queue page: elapsed time, resolution, frames; and from Task Manager or the dashboard: peak VRAM and GPU temperature.
4. Try 81 vs 121 frames and 704×1280 vs 544×960. Keep the setting where a 35 s video (7–10 clips) finishes in an acceptable overnight window.
5. Optional: repeat with an LTX-2.3 GGUF workflow imported from ComfyUI and compare clips side by side.

Write your numbers into this file so future-you (and the homelab plan) have real data.

## Adding another model or engine

- **Another ComfyUI model:** build or load the workflow in ComfyUI → Export (API) → Integrations → Import. Nothing else changes.
- **A different engine** (a Python API, a remote GPU worker): implement the small adapter interface in `app/backend/studio/integrations/video/base.py` (`health`, `capabilities`, `submit`, `wait`, `status`, `cancel`) and register it in `services.py`.
