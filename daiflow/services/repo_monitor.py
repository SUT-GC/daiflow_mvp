"""Background job: monitor project repos for new master commits.

Flow: git fetch → compare hash → git pull → trigger re-init.
Results logged to job_runs table for the Job tab.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from daiflow.database import get_background_db
from daiflow.models import Job, JobRun, JobRunStatus, ProjectRepo
from daiflow.services.git_service import clone_or_pull, fetch_remote, get_remote_head
from daiflow.services.project_service import _repo_dir_name
from daiflow.services.skill_service import get_project_dir

logger = logging.getLogger(__name__)

JOB_TYPE = "repo_monitor"
_monitor_task: asyncio.Task | None = None


async def _check_and_pull(db, job: Job) -> JobRun:
    """Check one job's project repos, pull if updated, return a JobRun."""
    run = JobRun(job_id=job.id, status=JobRunStatus.RUNNING)
    db.add(run)
    await db.flush()

    # Load repos for this project
    result = await db.execute(
        select(ProjectRepo).where(ProjectRepo.project_id == job.project_id)
    )
    repos = result.scalars().all()
    project_dir = get_project_dir(job.project_id)
    changed = []

    for repo in repos:
        if not repo.git_url:
            continue

        clone_dir = project_dir / "code" / _repo_dir_name(repo.git_url)
        if not (clone_dir / ".git").exists():
            continue

        try:
            await fetch_remote(str(clone_dir))
            new_hash = await get_remote_head(str(clone_dir))
            if not new_hash:
                continue

            old_hash = repo.master_hash or ""
            if old_hash and new_hash != old_hash:
                await clone_or_pull(repo.git_url, str(clone_dir))
                changed.append({
                    "repo_name": _repo_dir_name(repo.git_url),
                    "old": old_hash[:8],
                    "new": new_hash[:8],
                })

            repo.master_hash = new_hash
        except Exception as e:
            logger.warning("Failed to check %s: %s", repo.git_url, e)

    run.result = json.dumps({"repos_changed": changed})
    run.finished_at = datetime.now(timezone.utc)
    run.status = JobRunStatus.SUCCESS
    await db.commit()

    # Auto trigger re-init if repos changed
    if changed:
        from daiflow.services.project_service import run_init
        logger.info(
            "Job [%s] detected %d repo change(s), triggering re-init for project %s",
            job.id, len(changed), job.project_id,
        )
        asyncio.create_task(run_init(job.project_id))

    return run


async def run_job(job_id: str) -> dict:
    """Execute a single job by ID. Returns run summary."""
    async with get_background_db() as db:
        job = await db.get(Job, job_id)
        if not job:
            return {"error": "job not found"}

        try:
            run = await _check_and_pull(db, job)
            result_data = json.loads(run.result)
            return {
                "run_id": run.id,
                "status": JobRunStatus(run.status).name.lower(),
                "repos_changed": result_data.get("repos_changed", []),
            }
        except Exception as e:
            # Write failed run
            failed_run = JobRun(
                job_id=job.id,
                status=JobRunStatus.FAILED,
                error=str(e)[:500],
                finished_at=datetime.now(timezone.utc),
            )
            db.add(failed_run)
            await db.commit()
            logger.error("Job %s failed: %s", job_id, e)
            return {"run_id": failed_run.id, "status": "failed", "error": str(e)[:200]}


async def run_all_jobs() -> list[dict]:
    """Execute all enabled repo_monitor jobs."""
    results = []
    async with get_background_db() as db:
        query = select(Job).where(Job.type == JOB_TYPE, Job.enabled == 1)
        jobs = (await db.execute(query)).scalars().all()

    # Run each job (use separate DB sessions per job)
    for job in jobs:
        r = await run_job(job.id)
        r["job_id"] = job.id
        r["project_id"] = job.project_id
        results.append(r)

    return results


async def _monitor_loop():
    """Main loop: run enabled jobs at their configured intervals."""
    await asyncio.sleep(30)
    logger.info("Job scheduler started")

    while True:
        try:
            await run_all_jobs()
        except Exception as e:
            logger.error("Job scheduler cycle failed: %s", e)

        # Use the smallest interval among enabled jobs, default 5 min
        try:
            async with get_background_db() as db:
                query = select(Job.interval).where(Job.type == JOB_TYPE, Job.enabled == 1)
                rows = (await db.execute(query)).scalars().all()
                interval = min(rows) if rows else 300
                interval = max(60, interval)
        except Exception:
            interval = 300

        await asyncio.sleep(interval)


def start_monitor():
    """Start the background job scheduler. Idempotent."""
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        return
    _monitor_task = asyncio.create_task(_monitor_loop())
    logger.info("Job scheduler scheduled (first run in 30s)")


def stop_monitor():
    """Stop the background job scheduler."""
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        logger.info("Job scheduler stopped")
    _monitor_task = None
