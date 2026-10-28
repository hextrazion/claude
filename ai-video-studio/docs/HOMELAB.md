# Homelab migration roadmap

The studio already separates the three roles that might move:

1. **UI**: static files, served by the backend.
2. **Orchestration backend**: FastAPI, SQLite, job queue, FFmpeg assembly. Light on CPU except during assembly.
3. **Generation worker**: ComfyUI on a GPU, reached only through `generation.comfyui_url`.

Nothing assumes they share a machine except the default addresses.

## Stage 1: generation stays on the gaming PC, backend moves (recommended first step)

- Run the backend on the homelab box (Linux): `scripts/start.sh` (Python 3.11+, FFmpeg, Node only for the first UI build). `STUDIO_HOME` can point at your storage pool.
- Keys: the Secret Service keyring is often absent on servers, so set `GROQ_API_KEY` / `FISH_AUDIO_API_KEY` in `config/studio.env` (file readable only by the service user), or let the app use its restricted fallback file.
- On the PC, start ComfyUI listening on the LAN (`--listen 0.0.0.0`) and set the studio's ComfyUI address to `http://<pc-ip>:8188`. Restrict that port to the homelab's IP in Windows Firewall: ComfyUI has no authentication.
- The pause switch and processing hours keep working as before. The "hold while these programs run" and "GPU busy" checks only see the machine the backend runs on, so they stop protecting the PC once the backend moves. A small agent on the PC that reports "gaming now" is the natural next feature (see Stage 3).

## Stage 2: remote access to the UI

Do **not** just set `STUDIO_HOST=0.0.0.0`: there is no login. Instead:

- Put the backend behind a reverse proxy you already trust (Caddy, Nginx Proxy Manager, Traefik) with authentication (forward-auth / Authelia / basic auth) and HTTPS, or reach it only over Tailscale/WireGuard.
- Add the proxy's hostname to `STUDIO_ALLOWED_HOSTS`; both the Host check and the Origin check on state-changing requests use that list.

A built-in auth layer (single user, password + session cookie, required whenever the bind address is not loopback) is planned before any remote-first use.

## Stage 3: dedicated GPU worker

When the homelab gets a GPU (ideally 16–24 GB for LTX-2.x):

- Run ComfyUI there and point the studio at it. Model files never need copying between machines.
- Raise `max_gpu_jobs` only if VRAM allows two workflows at once (rarely worth it).
- Optional next adapter: a thin "worker" service per GPU host that wraps ComfyUI, reports VRAM/temperature and a "busy/gaming" flag back to the backend, enabling multi-worker scheduling. The adapter interface (`submit/wait/status/cancel/health/capabilities`) was designed for this.

## Things to keep in mind

- SQLite is fine for one backend instance. If you ever run several backends, move to Postgres (the data layer is small and SQL-first).
- Store project folders on the same host as the backend; FFmpeg reads clips directly from disk. Clips are downloaded from ComfyUI over HTTP, so the worker never needs shared storage.
- Back up `data/studio.db` and `data/projects/`. Everything else can be rebuilt.
