# AI Video Studio

A local, self-hosted production studio for short-form animated explainer videos. One app takes a video from **idea → research → script → scene plan → AI footage → narration → captions → finished vertical MP4**, with a review step wherever you want one.

- **Text:** [Groq](https://console.groq.com) (ideas, scripts, scene plans, claim checks)
- **Video:** an open model running on your own GPU through [ComfyUI](https://github.com/comfyanonymous/ComfyUI): **MiniMax H3** built in (also Wan 2.2 5B); the app detects which one you have and finds its files
- **Voice:** free [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) narration that runs on your PC (no account, no key); [Fish Audio](https://fish.audio) optional
- **Assembly:** FFmpeg (timeline, transitions, word-highlighted captions, music ducking, loudness, quality checks)
- **Research (optional):** Wikipedia (no key) or Tavily web search

Everything is controlled from a dark-themed web UI served by a local Python backend on `127.0.0.1`. Claude is not used anywhere in the pipeline.

## Install (Windows)

1. Download **[AI-Video-Studio-Setup.exe](https://github.com/hextrazion/claude/releases/download/ai-video-studio-latest/AI-Video-Studio-Setup.exe)** (you must be signed in to GitHub if the repository is private).
2. Double-click it. If Windows says it protected your PC (the installer isn't code-signed), click **More info → Run anyway**.
3. Click **Install**. No admin rights, Python, Node or FFmpeg needed: everything is included.
4. AI Video Studio opens in its own window and adds a Start-menu and desktop icon. A small tray icon near the clock keeps it running while videos render; right-click it → **Quit** to stop.
5. Open **Integrations**: paste your free Groq key, pick and preview a narration voice (it downloads once, ~140 MB), start ComfyUI and press **Auto-detect my model**. Then follow [Your first video](docs/SETUP.md#7-your-first-video).

Your projects live in `%LOCALAPPDATA%\AI Video Studio` and are kept if you uninstall or update. Each push to the app rebuilds the installer at the same link.

### Running from source (developers)

Install Python 3.11–3.13, Node.js 22 and FFmpeg, then run `scripts\start.bat` ([docs/SETUP.md](docs/SETUP.md)).

No GPU model yet? Set **Video provider → Draft cards** to run the whole pipeline with FFmpeg-rendered placeholder cards. They are clearly labelled and flagged in quality checks, so they are never mistaken for AI footage.

## What it does

| Page | Purpose |
|---|---|
| **Dashboard** | Real counts, things waiting for you, service health, GPU/VRAM/temperature, disk, API usage, recent errors |
| **Idea Studio** | Generate batches of specific concepts, duplicate warnings, favourite/edit/reject, approve into production |
| **Production** | Per-project workspace: script editor, scene-by-scene prompts with per-scene generate/regenerate, narration, research & claim status, final review with QC results |
| **Styles** | Reference images/clips → measured colours and pacing + an AI-written style applied to every scene; starred images feed H3's reference mode |
| **Queue** | Persistent job queue in three lanes (GPU / API / FFmpeg), pause/resume, cancel, retry, reorder, limits, processing hours |
| **Library** | All projects and finished videos: preview, rename, archive, export, safe delete |
| **Integrations** | Keys (masked, stored in Windows Credential Manager), connection tests, Groq model list, free voice picker with preview, ComfyUI model auto-detect and workflows |
| **Settings** | Everything else, persisted in SQLite |

Automation modes: **Manual** (you start every stage), **Supervised** (default: writes ideas/scripts, stops before footage), **Automated** (works through its own idea pool inside your daily limits, gates and processing hours). Nothing is ever published to social platforms.

## Gaming-friendly GPU use

- **Pause new jobs** (sidebar or Queue page) stops new generations immediately; the current one finishes, or cancel it safely (the app interrupts only its own ComfyUI prompt).
- **Hold while these programs run:** list game executables and GPU jobs wait until they close.
- **Wait while the GPU is busy**, **processing hours** (e.g. 01:00–08:00), **one GPU job at a time** by default, per-session limits and a minimum free disk space.
- The app never kills processes it did not start.

## Repository layout

```
ai-video-studio/
  app/backend/studio/   FastAPI app (api/, integrations/, pipeline/, jobs/, media/, db/)
  app/backend/tests/    pytest suite (unit, integration with mocked providers, real-FFmpeg end-to-end)
  app/frontend/         React + TypeScript + Vite UI
  config/workflows/     Bundled ComfyUI workflow templates (Wan 2.2 5B T2V/I2V, SDXL stills)
  config/studio.env.example
  scripts/              start.bat, dev.bat, build-ui.bat, test.bat, start.sh (running from source)
  packaging/            desktop launcher entry, PyInstaller build, Inno Setup installer script
  docs/                 Setup, models, architecture, homelab, troubleshooting, testing
  data/                 Created at runtime: studio.db, projects/, library/, music/, workflows/ (git-ignored)
  logs/                 studio.log (API keys redacted)
```

## Documentation

- [Setup & first video](docs/SETUP.md): installing, Groq, narration voice, ComfyUI, first video
- [Video models on a 12 GB GPU](docs/VIDEO_MODELS.md): why Wan 2.2 5B is the default, LTX-2.x options, how to benchmark
- [Architecture](docs/ARCHITECTURE.md): components, data model, job lifecycle, security
- [Homelab roadmap](docs/HOMELAB.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Testing & current limitations](docs/TESTING.md)
