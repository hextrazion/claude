# Testing, results and current limitations

## Running the tests

```bat
scripts\test.bat
```

or manually: `python -m pytest` from `ai-video-studio/` (after `pip install -r requirements-dev.txt`), and `npm test` in `app/frontend`.

## Results (development environment, 28 Oct 2026)

Environment: Linux container, Python 3.13, Node 22, FFmpeg 6.1, **no GPU, no Windows, no provider credentials, outbound access limited to package registries.**

| Suite | Result |
|---|---|
| Backend (`pytest`, 72 tests) | **72 passed** (one runs the real Kokoro voice model) |
| Frontend (`vitest`, 9 tests) | **9 passed** |
| TypeScript typecheck + production build | Passed |
| App start-up (fresh venv from `requirements.txt`, `python -m studio`) | Starts, serves UI and API; start-up health checks report each service honestly (not configured / unreachable / OK) |
| UI smoke test (Playwright, all pages and project tabs) | All pages render, no console errors |

What the backend tests cover:

- **Persistence:** migrations are idempotent; settings survive a restart; invalid settings are rejected and not saved; a corrupt settings section falls back to defaults.
- **Security:** keys are masked in every API response; environment overrides; log redaction; path traversal (`..`, absolute paths, drive letters, NTFS streams); CSRF header and cross-origin refusal; Host-header (DNS rebinding) refusal; project deletion requires the exact title and refuses folders without the matching `project.json` marker; files outside the project folder are untouched.
- **Providers (mocked HTTP):** missing/invalid Groq key, 429 with `Retry-After`, retired model, JSON-mode retry; Fish Audio 402 insufficient credit (no partial files left), missing voice, request shape (model header, reference_id, prosody), voice listing; ComfyUI submit → poll → download with binding substitution, out-of-memory detection (not retried), cancel interrupts only the job's own prompt, unreachable server, workflow check reporting missing nodes and model files, automatic binding detection, refusal of UI-format exports, frame-rule inference, seconds-based length inputs with integer coercion, model detection for planner notes, editing/resetting workflow frame settings.
- **Queue:** transient failure retried then succeeds; permanent failure not retried; backoff; processing windows (including across midnight); pause blocks new jobs; session limits; blocklisted programs; one GPU job at a time; reorder/pause/remove; **queue persists across restart**; **crash recovery re-attaches to a ComfyUI prompt that is still running** and resubmits one ComfyUI forgot; queue API controls; daily limits; work-file retention touches only `work/`.
- **Media (real FFmpeg):** silence-snapped alignment, transcript alignment, scene spans, narration repair, caption chunking/SRT/ASS, segment planning; **assembly of clips with different sizes, frame rates and lengths into a 9:16 MP4 with burned captions and fades**; music looping and ducking; QC detects wrong size, missing audio, missing captions, empty files.
- **End-to-end (HTTP API, worker running, mocked Groq/Fish, draft-card footage, real FFmpeg):** idea generation → approve → script (supervised gate) → claim check (never "verified" without sources) → edit + approve → scene plan with narration repair → no footage before plan approval → clips + narration → automatic assembly → QC → files on disk → review → single-scene regeneration leaves other clips untouched and invalidates the export. A second test confirms a Fish Audio credit failure is not retried and preserves the approved script and all clips.

Added since the first release: MiniMax H3 workflows (model-file matching for INT8/FP8/GGUF variants, the 17n+5 frame grid, turbo LoRA wiring, auto-detection order H3 turbo → H3 → Wan, settings untouched when ComfyUI is off), migration of old settings to the free voice, the Kokoro voice (WAV output, voice list, preview endpoint, truncated-download handling, a full idea→MP4 run with it), and a check that the packaged app makes no telemetry calls.

## Not tested (needs your PC or accounts)

| Item | Why not | How to verify |
|---|---|---|
| Real Groq calls | No key/network in the build environment | Integrations → Groq → Save key → Test; generate one idea batch |
| Real Fish Audio narration (optional) | No key/credit | Only if you switch to Fish Audio |
| MiniMax H3 generating on your RTX 4070 Ti | No GPU here | Auto-detect, then generate one scene |
| ComfyUI + Wan 2.2 5B on the RTX 4070 Ti (speed, VRAM, quality) | No GPU | Follow the benchmark in VIDEO_MODELS.md |
| Bundled Wan workflow node names vs your ComfyUI version | No ComfyUI | Integrations → workflow **Check**; re-import from ComfyUI if it reports mismatches |
| Windows-specific behaviour (start.bat, Credential Manager, `os.startfile`, fonts, gyan.dev FFmpeg) | Linux container | Run `scripts\start.bat`; on the Integrations page the key source should read "OS credential store" |
| Wikipedia/Tavily research | Network blocked in the build environment | Integrations → Research → Test |
| faster-whisper alignment | Optional dependency not installed | Install `requirements-optional.txt`, regenerate narration; the Narration tab shows "Speech recognition" |
| `nvidia-smi` GPU metrics | No GPU | Dashboard → System |

## Known limitations

- **Visual quality is not judged automatically.** QC checks technical validity only; every video waits for your review.
- **Clip length:** Wan 2.2 5B produces ~5 s clips. Longer narration segments are split by the planner; when a clip is still short it is slowed (up to 1.35×) and then held on its last frame, with a warning.
- **Consistency across scenes** relies on a shared style bible, a global style preset and optional image-to-video from stills. There is no character LoRA or IP-Adapter workflow bundled yet.
- **Caption timing** without faster-whisper is estimated and snapped to pauses; it is usually within a few hundred milliseconds of clean TTS but can drift on long sentences.
- **Fish Audio model names and voice availability** depend on your plan; the app discovers voices at runtime and shows the provider's error if a model is rejected.
- **Cost figures** are estimates from configurable rates (Groq shows $0 while "free tier" is enabled). Fish Audio's credit balance is shown from their API.
- **No authentication**: the app is for loopback use only. See HOMELAB.md before exposing it.
- **One ComfyUI instance** at a time (no multi-worker scheduling yet).
- Transitions are applied globally (cut/fade/dissolve/slide-up); the per-scene transition field is stored and shown but not yet used by assembly.
