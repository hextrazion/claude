# Troubleshooting

Every failed job shows a plain-language message; click it on the Queue page or a project's Jobs tab for the technical detail. The full log is `logs/studio.log` (API keys are redacted).

## Start-up

| Symptom | Fix |
|---|---|
| `Python 3.11 or newer was not found` | Install Python from python.org with "Add to PATH", reopen the window. |
| `Node.js was not found` on first run | Install Node 22 LTS. Only needed to build the UI once (and after UI updates: `scripts\build-ui.bat`). |
| Browser shows "Backend running. Frontend not built" | Run `scripts\build-ui.bat`, then reload. |
| Port 8765 already in use | Another copy is running, or set `STUDIO_PORT=8766` in `config\studio.env`. |
| Page says "Live updates disconnected" | The backend stopped or restarted. The UI reconnects automatically. |

## Groq

| Message | Meaning |
|---|---|
| "Groq rejected the API key" | Key wrong or revoked: paste a new one on Integrations. Not retried. |
| "rate limit reached; the job will retry automatically" | Free-tier per-minute/day limit. The job waits (using Groq's `Retry-After`) and retries. Lower idea batch sizes or daily limits if this is frequent. |
| "model … is not available" | The model was retired or isn't on your account. Integrations → Groq → Load available models → pick another. |
| "returned malformed output twice" | The model broke JSON mode. Retries automatically; if persistent, choose a larger writing model. |
| Script length warnings | The writer missed the length target twice; edit the script or regenerate with feedback like "make it 90 words". |

## Fish Audio

| Message | Meaning |
|---|---|
| "insufficient API credit" (HTTP 402) | Top up API credit. Your script and footage are kept; retry narration afterwards. |
| "No narration voice selected" | Integrations → Fish Audio → Choose. |
| Model rejected | Your plan may not include that model: try `s1` or `s2-pro` under TTS model. |
| Captions drift from speech | Install `requirements-optional.txt` (faster-whisper) for recognition-based timing, then regenerate narration. |

## ComfyUI / video generation

| Symptom | Fix |
|---|---|
| "ComfyUI is not reachable at http://127.0.0.1:8188" | Start ComfyUI. If you changed its port, update the address on Integrations. |
| Check: "Missing node types" | Update ComfyUI (Manager → Update ComfyUI) or install the custom nodes the workflow needs. For bundled templates, re-export the built-in template in API format and import it. |
| Check: "Missing model files" | Download the listed files into the listed `ComfyUI/models/...` folders, then restart ComfyUI or refresh its model list. |
| "ComfyUI rejected the workflow" | A value isn't valid for your ComfyUI version; the detail shows ComfyUI's validation error. Re-import the template from your ComfyUI. |
| "The GPU ran out of memory" | Fewer frames (81), lower resolution (544×960), close games/browsers, keep one GPU job. Not retried automatically. |
| Very slow generations | Normal for video diffusion on 12 GB. See speed settings in VIDEO_MODELS.md. Use processing hours to run overnight. |
| "ComfyUI no longer knows this job" | ComfyUI was restarted mid-generation; the job is resubmitted automatically. |
| Clip is too short for its narration (warning) | Regenerate with the scene split in two, or accept the slowed/held frame. |

## FFmpeg / assembly

| Symptom | Fix |
|---|---|
| "FFmpeg was not found" | See SETUP.md §3. Test on Integrations afterwards. |
| Missing `subtitles`, `xfade` or `loudnorm` filter | Use a "full" FFmpeg build. |
| Captions use a different font | The font must be installed on Windows; set its exact family name in Settings → Captions. |
| "Scene narration changed after the audio was generated" | Regenerate narration (Narration tab), then assemble. |
| Quality check warnings | Warnings never block you: they flag black sections, clipping, short clips or draft footage. Failures (wrong size, no audio, unreadable file) mean the export should not be used. |

## Storage

| Symptom | Fix |
|---|---|
| "The projects folder … is not available" | The external drive is unplugged or has a new drive letter. Plug it in, or choose the folder again in Settings → Where your videos are saved. |
| Some projects could not be moved | They stay in their old place and keep working. Close anything using their files and press *Try moving the remaining projects again*. |

## Queue

| Symptom | Fix |
|---|---|
| Jobs stay pending | Check the lane cards on the Queue page; they state the reason (paused, outside processing hours, low disk, session limit, a blocklisted program running, GPU busy). |
| After a crash/restart | Running jobs are reconciled automatically; see the "recovery" entries in recent activity. |
| Too many failed jobs | Fix the cause, then Queue → Failed → Retry all. |
