import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import asyncio

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import SESSIONS_DIR, safe_filename
from daiflow.database import get_db
from daiflow.models import Session
from daiflow.schemas import SessionStatusResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/{session_id:path}/status")
async def get_session_status(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionStatusResponse.model_validate(session).model_dump()


def _read_logs_sync(log_path, limit: int, offset: int) -> list:
    """Read JSONL logs from disk (sync, runs in thread pool)."""
    logs = []
    line_num = 0
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line_num < offset:
                line_num += 1
                continue
            if len(logs) >= limit:
                break
            try:
                logs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
            line_num += 1
    return logs


@router.get("/{session_id:path}/logs")
async def get_session_logs(session_id: str, limit: int = 5000, offset: int = 0):
    log_path = SESSIONS_DIR / f"{safe_filename(session_id)}.jsonl"
    if not log_path.exists():
        return []
    return await asyncio.to_thread(_read_logs_sync, log_path, limit, offset)
