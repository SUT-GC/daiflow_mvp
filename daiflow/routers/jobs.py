"""Job tab API: CRUD jobs, view run history, manual trigger."""

import json

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from daiflow.database import get_db
from daiflow.models import Job, JobRun, JobRunStatus
from daiflow.services.repo_monitor import run_all_jobs, run_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ── Request models ──

class JobCreate(BaseModel):
    project_id: str
    type: str = "repo_monitor"
    enabled: bool = True
    interval: int = 300  # seconds


class JobUpdate(BaseModel):
    enabled: bool | None = None
    interval: int | None = None


# ── Serialization helpers ──

def _serialize_job(job: Job) -> dict:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "type": job.type,
        "enabled": bool(job.enabled),
        "interval": job.interval,
        "config": json.loads(job.config) if job.config else {},
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _serialize_run(run: JobRun) -> dict:
    return {
        "id": run.id,
        "job_id": run.job_id,
        "status": JobRunStatus(run.status).name.lower(),
        "result": json.loads(run.result) if run.result else {},
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


# ── Job CRUD ──

@router.get("")
async def list_jobs(
    project_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List jobs, optionally filtered by project_id."""
    query = select(Job).order_by(Job.created_at.desc())
    if project_id:
        query = query.where(Job.project_id == project_id)
    result = await db.execute(query)
    return [_serialize_job(j) for j in result.scalars().all()]


@router.post("")
async def create_job(data: JobCreate, db: AsyncSession = Depends(get_db)):
    """Create a new job. Rejects duplicates (same project + type)."""
    existing = await db.execute(
        select(Job).where(Job.project_id == data.project_id, Job.type == data.type)
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=409,
            detail=f"A {data.type} job already exists for this project",
        )

    job = Job(
        project_id=data.project_id,
        type=data.type,
        enabled=1 if data.enabled else 0,
        interval=max(60, data.interval),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _serialize_job(job)


@router.put("/{job_id}")
async def update_job(job_id: str, data: JobUpdate, db: AsyncSession = Depends(get_db)):
    """Update job config (enable/disable, interval)."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if data.enabled is not None:
        job.enabled = 1 if data.enabled else 0
    if data.interval is not None:
        job.interval = max(60, data.interval)

    await db.commit()
    return _serialize_job(job)


@router.delete("/{job_id}")
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a job and its run history."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await db.delete(job)
    await db.commit()
    return {"ok": True}


# ── Run history ──

@router.get("/{job_id}/runs")
async def list_runs(job_id: str, limit: int = 50, db: AsyncSession = Depends(get_db)):
    """List recent runs for a job, newest first."""
    result = await db.execute(
        select(JobRun)
        .where(JobRun.job_id == job_id)
        .order_by(JobRun.started_at.desc())
        .limit(limit)
    )
    return [_serialize_run(r) for r in result.scalars().all()]


@router.get("/runs/recent")
async def list_recent_runs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """List recent runs across all jobs, newest first."""
    result = await db.execute(
        select(JobRun)
        .options(selectinload(JobRun.job))
        .order_by(JobRun.started_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()
    out = []
    for r in runs:
        d = _serialize_run(r)
        if r.job:
            d["project_id"] = r.job.project_id
            d["job_type"] = r.job.type
        out.append(d)
    return out


# ── Manual trigger ──

@router.post("/{job_id}/trigger")
async def trigger_job(job_id: str, background_tasks: BackgroundTasks):
    """Manually trigger a single job."""
    background_tasks.add_task(run_job, job_id)
    return {"ok": True, "message": "Job triggered"}


@router.post("/trigger-all")
async def trigger_all(background_tasks: BackgroundTasks):
    """Manually trigger all enabled jobs."""
    background_tasks.add_task(run_all_jobs)
    return {"ok": True, "message": "All jobs triggered"}
