# Setup and your first video

Target machine: Windows 10/11, NVIDIA RTX 4070 Ti (12 GB), Ryzen 7 5800X, 32 GB RAM. Everything also runs on Linux.

## 1. Prerequisites

| Software | Version | Why |
|---|---|---|
| Python | 3.11, 3.12 or 3.13 | Backend. Install from python.org and tick **Add python.exe to PATH**. |
| Node.js | 22 LTS (≥ 22.12) | Builds the web UI on first launch (not needed afterwards). |
| FFmpeg | 6.x or 7.x **full** build | Assembly, captions, audio, quality checks. |
| NVIDIA driver | Recent Game Ready/Studio driver | ComfyUI and `nvidia-smi` GPU monitoring. |
| ComfyUI | Current release (desktop app or portable) | Local video generation. |

Disk: plan for **30–60 GB** for ComfyUI models plus a few hundred MB per finished project (clips are kept so you can re-assemble without regenerating).

## 2. Launch the studio

Double-click `scripts\start.bat`. It:

1. finds Python (`py -3.13`, `-3.12`, `-3.11`, then `python`),
2. creates `.venv` and installs `requirements.txt` (again only when that file changes),
3. builds `app\frontend\dist` with npm on the first run,
4. starts the server on `http://127.0.0.1:8765` and opens your browser.

Close the console window (or press Ctrl+C) to stop. Running ComfyUI generations are left alone; the queue re-attaches to them on the next start.

Optional settings live in `config\studio.env` (copy `config\studio.env.example`), e.g. `STUDIO_HOME=D:\AI-Video-Studio` to keep data on a bigger drive.

## 3. FFmpeg

Easiest: download the **release full** build from <https://www.gyan.dev/ffmpeg/builds/>, extract it, and copy its `bin` folder so that this file exists:

```
ai-video-studio\tools\ffmpeg\bin\ffmpeg.exe
```

The studio looks there first, then `FFMPEG_PATH`, then your PATH. On the Integrations page, **FFmpeg → Test** must report the `subtitles`, `xfade` and `loudnorm` filters as present (“essentials” builds may lack some).

## 4. Groq (ideas, scripts, scene plans)

1. Create a key at <https://console.groq.com/keys>.
2. Integrations → Groq → paste → **Save** (it is tested immediately).
3. **Load available models** and pick:
   - *Writing model*: `llama-3.3-70b-versatile` (default) or another large model your account lists, e.g. `openai/gpt-oss-120b`.
   - *Fast model*: `llama-3.1-8b-instant` (search queries, claim listing).

Notes: Groq's API has no web access, so research is a separate optional stage. Free-tier limits are per model and change over time; the app records rate-limit headers, waits and retries on HTTP 429, and stops immediately on invalid keys. Set daily caps under Settings → Daily limits. If a model is retired, scripts fail with “model not available” and you choose another one; nothing is lost.

## 5. Fish Audio (narration)

1. Create an API key at <https://fish.audio/app/api-keys/> and make sure the account has API credit (API calls draw on API credit, which may be separate from a website subscription).
2. Integrations → Fish Audio → paste → **Save**. The test shows your API credit balance.
3. **Choose** a voice: search public voices, switch to *My voices* for voices you cloned on fish.audio, or paste a voice ID.
4. *TTS model* is sent as Fish's `model` header. `s2-pro` is the default; `s1` also works on most accounts. If your plan rejects a model you will see the error on the narration job.

Each narration is one request for the whole script (better prosody than per-scene clips). Characters and estimated cost are recorded; Settings → Pricing holds the per-million-character rate used for estimates.

## 6. ComfyUI and the video model

Full details and alternatives: [VIDEO_MODELS.md](VIDEO_MODELS.md). Short version for the default model:

1. Install ComfyUI and start it (default address `http://127.0.0.1:8188`).
2. Download into ComfyUI's `models` folder:
   - `diffusion_models/wan2.2_ti2v_5B_fp16.safetensors`
   - `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors`
   - `vae/wan2.2_vae.safetensors`
   (ComfyUI's built-in “Wan 2.2 5B video generation” template links to all three.)
3. Integrations → ComfyUI: video provider **ComfyUI**, workflow **Wan 2.2 TI2V 5B — text to video**, press **Check**. It confirms every node type and model file exists in *your* ComfyUI.
4. If Check reports a node mismatch (ComfyUI renames nodes occasionally): open the built-in template in ComfyUI, **Workflow → Export (API)**, then **Import from ComfyUI** in the studio and select the imported workflow.

## 7. Your first video

1. **Settings → Automation mode:** keep **Supervised**. Video defaults: 35 s, 1080×1920, 30 fps.
2. **Idea Studio → Generate ideas.** Review the cards; open one to edit it. Rejected ideas are remembered so they are not suggested again.
3. **Approve & start.** The project researches (if enabled) and writes a script, then waits.
4. **Script tab:** edit freely, **Save edits**, then **Approve script**. Check *Research & claims* for anything marked *Not found* or *Contradicted*.
5. **Scenes tab:** the plan appears. Each scene has its narration, what the viewer must understand, and a video prompt. Edit prompts, then **Approve scene plan**. Clip jobs and narration are queued.
6. Watch progress on the **Queue** page. Each clip is generated individually; a failed scene can be retried alone.
7. When all clips and narration exist, assembly runs (or waits for you if *Approve before assembly* is on).
8. **Video & review tab:** watch the result, read the automated checks, then **Approve as finished** or **Needs changes**. Use **Copy to library folder** or **Open exports**.

Everything for the project is in its folder: `idea.json`, `research/`, `script/`, `scenes/scene_NN/clip_*.mp4` with a `.json` recording model/workflow/seed/prompt, `narration/`, `captions/` (`.srt` and `.ass`), `exports/` (MP4, `qc.json`, `export_settings.json`) and `project.json`.

## 8. Optional extras

- **Research:** Settings → Text & research. Wikipedia needs nothing; for Tavily add a key on Integrations.
- **Better caption timing:** `.venv\Scripts\python.exe -m pip install -r requirements-optional.txt` installs faster-whisper; caption timing then comes from speech recognition instead of estimation.
- **Background music:** Settings → Background music → *Add track* (only tracks you have rights to), enable, and set volume/ducking.
- **Still images first:** pick the SDXL (or your own) image workflow on Integrations, enable *Generate stills first* in Settings → Video generation. Scenes the planner marks as needing a still are generated as an image and animated with the image-to-video workflow. You can also upload your own source image per scene.
- **Development:** `scripts\dev.bat` runs the backend and the Vite dev server with live reload; `scripts\test.bat` runs both test suites.
