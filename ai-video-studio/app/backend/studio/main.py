"""FastAPI application: security middleware, API routers, static frontend."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .api import integrations, jobs, projects, styles, system
from .config import AppConfig, load_config
from .errors import ProviderError, StudioError, ValidationFailed
from .jobs.worker import Worker
from .pipeline.orchestrator import Orchestrator
from .pipeline.stages import HANDLERS
from .services import Services

log = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CLIENT_HEADER = "x-studio-client"


def create_app(config: AppConfig | None = None, services: Services | None = None, start_worker: bool = True) -> FastAPI:
    config = config or (services.config if services else load_config())
    svc = services or Services(config)
    svc.orchestrator = Orchestrator(svc)
    svc.worker = Worker(svc, HANDLERS)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc.bus.bind_loop(asyncio.get_running_loop())
        svc.activity.add(f"AI Video Studio {__version__} started", category="system")
        if start_worker:
            await svc.worker.start()
            # Fill in service status for the dashboard without blocking startup.
            startup_checks = asyncio.create_task(_startup_checks(svc))
        else:
            await svc.worker.recover()
            startup_checks = None
        yield
        if startup_checks:
            startup_checks.cancel()
        await svc.worker.stop()

    app = FastAPI(title="AI Video Studio", version=__version__, lifespan=lifespan, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None)
    app.state.services = svc

    allowed_hosts = ["127.0.0.1", "localhost", "[::1]", *config.extra_allowed_hosts]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def security(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and request.method not in SAFE_METHODS:
            # Browsers cannot attach custom headers cross-origin without a CORS
            # preflight, which this server never approves: blocks CSRF from other sites.
            if request.headers.get(CLIENT_HEADER) != "web":
                return JSONResponse({"error": {"message": "Missing client header.", "kind": "forbidden"}}, status_code=403)
            origin = request.headers.get("origin")
            if origin:
                host = origin.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0]
                if host not in ("127.0.0.1", "localhost", "[::1]", *config.extra_allowed_hosts):
                    return JSONResponse({"error": {"message": "Cross-origin request refused.", "kind": "forbidden"}},
                                        status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not path.startswith("/api/"):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: https:; media-src 'self' https:; style-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; frame-ancestors 'none'",
            )
        return response

    @app.exception_handler(StudioError)
    async def studio_error(request: Request, exc: StudioError):
        if isinstance(exc, ValidationFailed):
            status = 400
        elif isinstance(exc, ProviderError):
            status = {"auth": 401, "not_configured": 409, "quota": 429, "rate_limit": 429}.get(exc.kind, 502)
        else:
            status = 500
        return JSONResponse({"error": exc.to_dict()}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, exc: RequestValidationError):
        msgs = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
        return JSONResponse({"error": {"message": "Invalid request.", "kind": "invalid_request", "detail": msgs}},
                            status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse({"error": {"message": "Something went wrong on the server. Details are in logs/studio.log.",
                                       "kind": "internal", "detail": repr(exc)[:500]}}, status_code=500)

    for module in (system, projects, jobs, integrations, styles):
        app.include_router(module.router, prefix="/api")

    dist = config.frontend_dist
    if dist.is_dir() and (dist / "index.html").is_file():
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse({"error": {"message": "Not found", "kind": "not_found"}}, status_code=404)
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def no_frontend():
            return JSONResponse({"message": "Backend running. Frontend not built: run scripts/build-frontend or start.bat."})

    return app


async def _startup_checks(svc: Services) -> None:
    from .api.integrations import INTEGRATIONS, autodetect_workflows, run_test
    from .integrations.base import HealthResult

    # Fetch the free narration voice in the background so it is ready before the first video.
    if svc.settings.get().narration.provider == "kokoro" and not svc.kokoro.installed():
        try:
            svc.kokoro.start_download()
        except Exception:
            log.warning("could not start the voice model download", exc_info=True)
    try:
        # Switch to whichever video model the user's ComfyUI actually has (e.g. MiniMax H3).
        await autodetect_workflows(svc, force=False)
    except Exception:
        log.warning("video workflow auto-detection failed", exc_info=True)
    for name in INTEGRATIONS:
        try:
            await run_test(svc, name)
        except Exception as exc:  # a failing check must never stop the app
            svc.save_health(name, HealthResult("error", "Check failed unexpectedly.", detail=repr(exc)))


def run() -> None:
    import uvicorn
    import webbrowser

    config = load_config()
    if config.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Binding to %s exposes the studio to your network. There is no login; see docs/HOMELAB.md.", config.host)
    app = create_app(config)
    url = f"http://127.0.0.1:{config.port}"
    if not config.dev and Path(config.frontend_dist / "index.html").is_file():
        import threading

        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"\n  AI Video Studio is running at {url}\n  Press Ctrl+C to stop.\n")
    uvicorn.run(app, host=config.host, port=config.port, log_level="warning")
