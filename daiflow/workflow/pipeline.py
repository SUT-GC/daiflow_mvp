"""Pipeline executor for Project Init and similar layer-based workflows.

Provides:
- run_simple_task(): Wrapper for non-AI tasks with unified Session state management
- INIT_PIPELINE: Declarative pipeline configuration for project knowledge generation
- run_pipeline(): Generic executor that runs layers serially with concurrent tasks within each layer
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.database import get_background_db
from daiflow.models import ProjectRepo, Session, SessionStatus
from daiflow.services.settings_service import get_language_setting
from daiflow.services.skill_service import get_project_dir
from daiflow.config import utc_iso
from daiflow.session_runner import append_log
from daiflow.ws_manager import WSManager, ws_manager as _default_ws_manager

logger = logging.getLogger(__name__)


async def run_simple_task(
    session_id: str,
    project_bus: str,
    fn: Callable[[AsyncSession, str], Awaitable[None]],
    ws_manager: WSManager | None = None,
):
    """Execute a non-AI task with unified Session state management.

    Handles: status transitions, timestamps, log writing, WebSocket publishing.
    The caller only needs to provide the pure business logic function `fn`.
    """
    ws_manager = ws_manager or _default_ws_manager
    async with get_background_db() as db:
        session = await db.get(Session, session_id)
        if not session:
            logger.error("Session %s not found for run_simple_task", session_id)
            return

        started = datetime.now(timezone.utc)
        session.status = SessionStatus.RUNNING
        session.started_at = started
        await db.commit()
        await ws_manager.publish(project_bus, {
            "type": "session_status",
            "session_id": session_id,
            "status": SessionStatus.RUNNING,
            "layer": session.layer,
            "started_at": utc_iso(started),
        })

        try:
            await fn(db, session_id)

            finished = datetime.now(timezone.utc)
            await append_log(session_id, {"type": "done", "ts": utc_iso(finished)})
            session.status = SessionStatus.DONE
            session.finished_at = finished
            await db.commit()
            await ws_manager.publish(project_bus, {
                "type": "session_status",
                "session_id": session_id,
                "status": SessionStatus.DONE,
                "layer": session.layer,
                "finished_at": utc_iso(finished),
            })

        except Exception as e:
            failed_at = datetime.now(timezone.utc)
            logger.error("Simple task %s failed: %s", session_id, e)
            await append_log(session_id, {
                "type": "text_delta", "ts": utc_iso(failed_at),
                "content": f"✗ Failed: {e}\n",
            })
            await append_log(session_id, {"type": "done", "ts": utc_iso(failed_at)})
            session.status = SessionStatus.FAILED
            session.error = str(e)[:500]
            session.finished_at = failed_at
            await db.commit()
            await ws_manager.publish(project_bus, {
                "type": "session_status",
                "session_id": session_id,
                "status": SessionStatus.FAILED,
                "error": str(e)[:500],
                "layer": session.layer,
                "finished_at": utc_iso(failed_at),
            })
            raise
