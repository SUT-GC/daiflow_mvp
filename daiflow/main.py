import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from daiflow.config import init_daiflow_dir
from daiflow.database import init_db
from daiflow.routers import projects, sessions, settings, tasks, todos, ws

logger = logging.getLogger(__name__)


async def _recover_interrupted_inits():
    """Reset interrupted init sessions (RUNNING → FAILED) and auto-retry affected projects."""
    from sqlalchemy import select, update
    from daiflow.database import get_background_db
    from daiflow.models import Session, SessionStatus
    from daiflow.services.project_service import run_init_retry

    async with get_background_db() as db:
        # Find all RUNNING init sessions (interrupted by shutdown)
        result = await db.execute(
            select(Session).where(
                Session.type == "init",
                Session.status == SessionStatus.RUNNING,
            )
        )
        interrupted = result.scalars().all()
        if not interrupted:
            return

        # Group by project and find earliest interrupted layer per project
        projects_to_retry: dict[str, dict] = {}  # ref_id -> {from_layer, failed_ids}
        for s in interrupted:
            s.status = SessionStatus.FAILED
            s.error = "Interrupted by server shutdown"
            pid = s.ref_id
            if pid not in projects_to_retry:
                projects_to_retry[pid] = {"from_layer": s.layer or 1, "failed_ids": []}
            info = projects_to_retry[pid]
            if s.layer and s.layer < info["from_layer"]:
                info["from_layer"] = s.layer
            if s.layer == info["from_layer"]:
                info["failed_ids"].append(s.session_id)
        await db.commit()

        logger.info(
            "Recovered %d interrupted init sessions across %d projects",
            len(interrupted), len(projects_to_retry),
        )

        # Auto-retry each affected project
        for pid, info in projects_to_retry.items():
            logger.info("Auto-retrying init for project %s from layer %d", pid, info["from_layer"])
            asyncio.create_task(run_init_retry(pid, info["failed_ids"], info["from_layer"]))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_daiflow_dir()
    await init_db()
    await _recover_interrupted_inits()
    yield


app = FastAPI(title="DaiFlow", version="0.1.0", lifespan=lifespan)

# CORS — restrict to local dev origins
_allowed_origins = os.environ.get(
    "DAIFLOW_CORS_ORIGINS",
    "http://localhost:3000,http://localhost:8000,http://127.0.0.1:3000,http://127.0.0.1:8000",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(settings.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(todos.router)
app.include_router(sessions.router)
app.include_router(ws.router)

# Serve React build as static files (production mode)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    # Mount static assets (js, css, images, etc.)
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

    # SPA fallback: serve index.html for all non-API routes
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        # Try to serve the exact file first (e.g. favicon, manifest)
        file_path = static_dir / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        # Otherwise return index.html for client-side routing
        return FileResponse(static_dir / "index.html")
