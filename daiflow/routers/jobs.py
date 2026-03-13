"""Job tab API: monitor log history + manual trigger + config."""

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.database import get_db
from daiflow.models import MonitorJobStatus, MonitorLog, Setting
from daiflow.services.repo_monitor import check_all_projects

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """List recent monitor job logs, newest first."""
    result = await db.execute(
        select(MonitorLog).order_by(MonitorLog.created_at.desc()).limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "project_id": log.project_id,
            "project_name": log.project_name,
            "status": MonitorJobStatus(log.status).name.lower(),
            "repos_changed": json.loads(log.repos_changed) if log.repos_changed else [],
            "error": log.error,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "finished_at": log.finished_at.isoformat() if log.finished_at else None,
        }
        for log in logs
    ]


@router.post("/check")
async def trigger_check():
    """Manually trigger a repo check across all projects."""
    results = await check_all_projects()
    return {"results": results}


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    """Get monitor config."""
    setting = await db.get(Setting, "repo_monitor_interval")
    return {
        "interval": int(setting.value) if setting and setting.value else 300,
    }


@router.put("/config")
async def update_config(data: dict, db: AsyncSession = Depends(get_db)):
    """Update monitor config. Body: {"interval": 300}."""
    interval = data.get("interval", 300)
    interval = max(60, int(interval))

    setting = await db.get(Setting, "repo_monitor_interval")
    if setting:
        setting.value = str(interval)
    else:
        db.add(Setting(key="repo_monitor_interval", value=str(interval)))
    await db.commit()

    return {"interval": interval}
