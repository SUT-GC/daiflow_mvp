import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import SESSIONS_DIR, safe_filename
from daiflow.database import get_db
from daiflow.models import Session, SessionStatus
from daiflow.schemas import SessionStatusResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/running")
async def get_running_sessions(db: AsyncSession = Depends(get_db)):
    """Return count of currently running sessions (for desktop close protection)."""
    result = await db.execute(
        select(Session).where(Session.status == SessionStatus.RUNNING)
    )
    sessions = result.scalars().all()
    return {"count": len(sessions)}


@router.get("")
async def list_sessions(
    ref_id: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List sessions with optional filters. For the debug/troubleshoot page."""
    query = select(Session).order_by(Session.created_at.desc())
    if ref_id:
        query = query.where(Session.ref_id == ref_id)
    if type:
        query = query.where(Session.type == type)
    result = await db.execute(query.limit(200))
    sessions = result.scalars().all()
    return [
        SessionStatusResponse.model_validate(s).model_dump()
        for s in sessions
    ]


@router.get("/{session_id:path}/status")
async def get_session_status(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionStatusResponse.model_validate(session).model_dump()


def _read_logs_sync(log_path, limit: int, offset: int, all_attempts: bool) -> list:
    """Read JSONL logs from disk (sync, runs in thread pool).

    By default, returns only logs from the latest run attempt
    (everything after the last run_boundary marker). Set all_attempts=True
    to return the full log history across all attempts.
    """
    all_logs: list[tuple[int, dict]] = []  # (index, parsed_event)
    last_boundary = -1
    idx = 0
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            all_logs.append((idx, event))
            if event.get("type") == "run_boundary":
                last_boundary = idx
            idx += 1

    # Filter to latest attempt unless all_attempts requested
    if not all_attempts and last_boundary >= 0:
        logs = [ev for (i, ev) in all_logs if i > last_boundary]
    else:
        logs = [ev for (_, ev) in all_logs]

    # Apply offset + limit
    return logs[offset : offset + limit]


@router.get("/{session_id:path}/logs")
async def get_session_logs(
    session_id: str,
    limit: int = 5000,
    offset: int = 0,
    all_attempts: bool = False,
):
    log_path = SESSIONS_DIR / f"{safe_filename(session_id)}.jsonl"
    if not log_path.exists():
        return []
    return await asyncio.to_thread(_read_logs_sync, log_path, limit, offset, all_attempts)
