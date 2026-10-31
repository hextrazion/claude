# Setup and your first video

Target machine: Windows 10/11, NVIDIA RTX 4070 Ti (12 GB), Ryzen 7 5800X, 32 GB RAM. Everything also runs on Linux.

## 1. Prerequisites

| Software | Version | Why |
|---|---|---|
| Python | 3.11, 3.12 or 3.13 | Backend. Install from python.org and tick **Add python.exe to PATH**. |
| Node.js | 22 LTS (≥ 22.12) | Only when running from source (the installer needs nothing). |
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

## 5. Narration voice (free)

Narration uses **Kokoro**, an open-source (Apache 2.0) voice model that runs on your CPU: no account, no key, no cost, and it never competes with ComfyUI for the GPU.

1. Integrations → **Narration voice** → *Download free voice* (one time, ~140 MB). The app also starts this download by itself on first launch.
2. Pick a voice (★ marks the clearest ones, e.g. *Heart*, *Bella*, *Michael*, *Emma*, *George*) and press **Preview voice**.
3. Optional: change the speed. Each project can override the voice under Project settings.

**Fish Audio (optional, paid).** Fish Audio's API is billed from API credit, which its free plan does not include, so it is off by default. If you buy credit: Integrations → Fish Audio → paste key → *Use Fish Audio*.

## 6. ComfyUI and the video model (MiniMax H3)

Full details and alternatives: [VIDEO_MODELS.md](VIDEO_MODELS.md). Short version:

1. In ComfyUI, make sure the MiniMax H3 example (Workflow → Browse Templates → Video → MiniMax H3) runs once by itself. That confirms your ComfyUI is new enough and the model files are in place.
2. Start ComfyUI and leave it running (default address `http://127.0.0.1:8188`).
3. In the studio: Integrations → ComfyUI → **Auto-detect my model**. It checks which models your ComfyUI has (MiniMax H3, Wan 2.2…), finds your files even if you downloaded a different variant (INT8, FP8, GGUF), and selects the best workflow. The studio also does this automatically when it starts.
4. If it says something is missing, press **Check** on the MiniMax H3 workflow: it lists exactly which file or node it could not find.

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
- **Background voice download:** the voice model comes from the kokoro-onnx project's GitHub releases; ONNX Runtime's telemetry is switched off so narration stays fully local.
- **Development:** `scripts\dev.bat` runs the backend and the Vite dev server with live reload; `scripts\test.bat` runs both test suites.
