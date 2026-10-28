# Architecture

```
 Browser (React UI)  ──HTTP + SSE──►  FastAPI backend (127.0.0.1:8765)
                                        │  api/        typed endpoints, security middleware
                                        │  pipeline/   orchestrator (state machine), stage handlers, prompts
                                        │  jobs/       persistent queue + worker (gpu / api / cpu lanes), recovery
                                        │  media/      FFmpeg wrapper, assembly, captions, alignment, QC
                                        │  integrations/ groq, fish_audio, research, video/{comfyui,draft,workflows}
                                        │  db/         SQLite + numbered SQL migrations
                                        ▼
            SQLite (data/studio.db)   project folders (data/projects/NNNN-slug/)
                                        │
                     ┌──────────────────┼────────────────────┐
                 Groq API         Fish Audio API       ComfyUI (local or remote GPU)
```

The UI never talks to providers or holds secrets; the backend is the only component that does. ComfyUI is reached over HTTP at a configurable address, so the generation engine can live on another machine without code changes.

## Pipeline and state

Each project records a status per stage: `research_status`, `script_status` (none/draft/approved), `scene_plan_status`, per-scene `clip_status`/`image_status`, `narration_status`, `export_status`, `review_status`. `Orchestrator.next_step()` is a pure function of that state returning the next action (`research`, `script`, `approve_script`, `scene_plan`, `approve_scene_plan`, `production`, `approve_assembly`, `assemble`, `review`, `done`, `fix_failed`, `wait…`). `advance()` acts on it:

- **Manual:** never acts on its own; buttons call it with `user=True`.
- **Supervised:** acts automatically, stops at the script gate (configurable) and always at the scene-plan gate, so no GPU time is spent without approval.
- **Automated:** gates come from Settings; an automation tick (once a minute) keeps an idea pool topped up and starts projects from the best ideas, inside daily limits.

Failed work is never re-queued by `advance()`; only the queue's retry policy or a person retries it. Edits mark downstream outputs **stale** instead of deleting them (editing a scene prompt marks its clip and the export stale; editing narration text marks narration and export stale).

Narration drives pacing. Scene narrations concatenated must equal the script word for word (the planner output is repaired if the model paraphrased). Word timings come from faster-whisper when installed, otherwise from a length-weighted estimate snapped to silences detected by FFmpeg. Scene boundaries are placed in the pauses between scenes; clips are trimmed, slowed by up to `max_stretch`, then held on their last frame, with a flag when a clip is too short.

## Job queue

`jobs` table rows: kind, lane, status (`pending`, `running`, `paused`, `completed`, `failed`, `cancelled`), position, attempts/max_attempts, payload, result, error message/kind/detail, provider, external id (ComfyUI prompt id), progress, timestamps. Projects waiting on a person are shown as *waiting for approval* at project level.

- Lanes run independently with their own concurrency limits (GPU 1, API 2, FFmpeg 1 by default).
- Before starting a job, a lane checks: global pause, processing window, free disk, per-session GPU limit, blocklisted processes, optional GPU-busy threshold.
- Errors carry a kind. `transient`, `rate_limit`, `unavailable`, `timeout` retry with exponential backoff (or the server's `Retry-After`); `auth`, `quota`, `invalid_request`, `oom`, `not_configured` fail immediately with a plain-language message and technical detail.
- **Recovery:** on start-up, jobs recorded as running are reconciled. A clip job with a ComfyUI prompt id asks ComfyUI: still queued/running/finished → re-attach and collect; failed → retry; unknown → resubmit. Other jobs are requeued. Scenes or narration left “running” without a job are marked failed so they can be retried. Successful outputs of other stages are never touched.
- Cancelling a running GPU job interrupts only that ComfyUI prompt (`/interrupt` with its prompt id, or removal from ComfyUI's pending queue). FFmpeg jobs kill only their own FFmpeg process. Nothing else is ever terminated.

## Security

- Binds to `127.0.0.1`; `TrustedHostMiddleware` rejects other Host headers (DNS rebinding).
- State-changing requests require an `X-Studio-Client` header and a same-host `Origin` when present; no CORS is enabled, so other websites cannot make the browser call the API.
- Keys live in the OS credential store via `keyring` (Windows Credential Manager), or environment variables; a permission-restricted file is used only if no credential store exists (headless Linux). The API returns masked values only. Log handlers redact stored keys and key-shaped strings.
- Every user- or model-derived path goes through `safety.safe_join/ensure_within` (no absolute paths, `..`, drive letters or NTFS streams). Files are served only from inside a project folder and only with media/text extensions.
- Subprocesses are FFmpeg/ffprobe/nvidia-smi with argument lists (no shell). Model output never becomes a command or a path; prompt text goes to providers only. Caption text is escaped for ASS, and file-based `textfile=`/relative subtitle paths avoid filter-string injection.
- Deleting a project with files requires typing its title, and the folder must be inside the projects root and contain its own `project.json` marker with the matching id.

## Data on disk

```
data/studio.db           settings, ideas, projects, scenes, jobs, activity, api_usage, cache
data/projects/0007-why-onions-make-you-cry/
  project.json idea.json
  research/research.json research/factcheck.json
  script/script.json script/script.md
  scenes/scene_plan.json scenes/scene_01/clip_20261028-201512.mp4 (+ .json metadata) image_*.png
  narration/narration_*.mp3 narration/narration.json   (includes word timings)
  captions/captions.srt captions/captions.ass
  exports/<slug>_<timestamp>.mp4 exports/qc.json exports/export_settings.json
  work/                    intermediate segments (cleaned after keep_work_files_days)
data/library/            copies made with "Copy to library folder"
data/music/              your licensed music tracks
data/workflows/          imported ComfyUI workflows (override bundled ones by name)
```

## Extending

- **New video/image engine:** implement `GenerationAdapter` (`integrations/video/base.py`) and return it from `Services.video_adapter`.
- **New research source:** a class with `search(query) -> list[Source]` and `test()`; add it to `Services.research_provider` and the settings literal.
- **Schema change:** add `app/backend/studio/db/migrations/0002_<name>.sql`; it runs once at start-up.
