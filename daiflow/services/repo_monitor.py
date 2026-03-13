"""Background job: monitor project repos for new master commits.

Flow per repo: git fetch → compare hash → git merge --ff-only → trigger re-init.
Results logged to job_runs table for the Job tab.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from daiflow.database import get_background_db
from daiflow.models import Job, JobRun, JobRunStatus, ProjectRepo
from daiflow.services.git_service import fetch_remote, get_remote_head, merge_ff_only
from daiflow.services.project_service import repo_dir_name
from daiflow.services.skill_service import get_project_dir

logger = logging.getLogger(__name__)

JOB_TYPE = "repo_monitor"
_monitor_task: asyncio.Task | None = None
# Simple lock to prevent concurrent runs of the same job
_running_jobs: set[str] = set()


async def _check_and_pull(db, job: Job) -> JobRun:
    """Check one job's project repos, pull if updated, return a JobRun."""
    result = await db.execute(
        select(ProjectRepo).where(ProjectRepo.project_id == job.project_id)
    )
    repos = result.scalars().all()
    project_dir = get_project_dir(job.project_id)
    changed = []
    error_msgs = []

    for repo in repos:
        if not repo.git_url:
            continue

        clone_dir = project_dir / "code" / repo_dir_name(repo.git_url)
        if not (clone_dir / ".git").exists():
            continue

        try:
            await fetch_remote(str(clone_dir))
            new_hash, branch_name = await get_remote_head(str(clone_dir))
            if not new_hash or not branch_name:
                continue

            old_hash = repo.master_hash or ""
            if old_hash and new_hash != old_hash:
                # Fast-forward merge (no redundant fetch)
                await merge_ff_only(str(clone_dir), branch_name)
                changed.append({
                    "repo_name": repo_dir_name(repo.git_url),
                    "old": old_hash[:8],
                    "new": new_hash[:8],
                })

            # Update master_hash via SQL (not ORM attribute) to avoid session issues
            await db.execute(
                update(ProjectRepo).where(ProjectRepo.id == repo.id).values(master_hash=new_hash)
            )
        except Exception as e:
            error_msgs.append(f"{repo.git_url}: {e}")
            logger.warning("Failed to check %s: %s", repo.git_url, e)

    # Create run record at the end (not before) to avoid orphan RUNNING records
    run = JobRun(
        job_id=job.id,
        status=JobRunStatus.SUCCESS,
        result=json.dumps({"repos_changed": changed}),
        error="; ".join(error_msgs) if error_msgs else None,
        finished_at=datetime.now(timezone.utc),
    )
    db.add(run)
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
    if job_id in _running_jobs:
        return {"status": "skipped", "reason": "already running"}
    _running_jobs.add(job_id)

    try:
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
    finally:
        _running_jobs.discard(job_id)


async def run_all_jobs() -> list[dict]:
    """Execute all enabled repo_monitor jobs."""
    results = []
    async with get_background_db() as db:
        query = select(Job).where(Job.type == JOB_TYPE, Job.enabled == 1)
        jobs = (await db.execute(query)).scalars().all()

    for job in jobs:
        r = await run_job(job.id)
        r["job_id"] = job.id
        r["project_id"] = job.project_id
        results.append(r)

    return results


async def _monitor_loop():
    """Main loop: run enabled jobs respecting each job's interval."""
    await asyncio.sleep(30)
    logger.info("Job scheduler started")

    # Track last run time per job to respect individual intervals
    last_run: dict[str, float] = {}

    while True:
        try:
            async with get_background_db() as db:
                query = select(Job).where(Job.type == JOB_TYPE, Job.enabled == 1)
                jobs = (await db.execute(query)).scalars().all()
                job_list = [(j.id, j.project_id, j.interval) for j in jobs]
        except Exception:
            job_list = []

        now = asyncio.get_event_loop().time()
        for job_id, project_id, interval in job_list:
            elapsed = now - last_run.get(job_id, 0)
            if elapsed >= interval:
                await run_job(job_id)
                last_run[job_id] = asyncio.get_event_loop().time()

        # Clean up stale entries
        active_ids = {j[0] for j in job_list}
        for stale_id in list(last_run.keys()):
            if stale_id not in active_ids:
                del last_run[stale_id]

        # Sleep a short tick, individual intervals handled above
        await asyncio.sleep(30)


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
