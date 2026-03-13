"""Background job: monitor project repos for new master commits.

Flow: git fetch → compare hash → git pull → trigger re-init.
Results logged to monitor_logs table for the Job tab.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from daiflow.database import get_background_db
from daiflow.models import MonitorJobStatus, MonitorLog, Project, ProjectRepo, Setting
from daiflow.services.git_service import clone_or_pull, fetch_remote, get_remote_head
from daiflow.services.project_service import _repo_dir_name
from daiflow.services.skill_service import get_project_dir

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 300  # 5 minutes
_monitor_task: asyncio.Task | None = None


async def _check_and_pull_project(db, project: Project) -> MonitorLog:
    """Check one project's repos, pull if updated, return a MonitorLog."""
    log = MonitorLog(
        project_id=project.id,
        project_name=project.name,
        status=MonitorJobStatus.RUNNING,
    )
    db.add(log)
    await db.flush()

    project_dir = get_project_dir(project.id)
    changed = []

    for repo in project.repos:
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
                # Pull latest code
                await clone_or_pull(repo.git_url, str(clone_dir))
                changed.append({
                    "repo_name": _repo_dir_name(repo.git_url),
                    "old": old_hash[:8],
                    "new": new_hash[:8],
                })

            repo.master_hash = new_hash
        except Exception as e:
            logger.warning("Failed to check %s: %s", repo.git_url, e)

    log.repos_changed = json.dumps(changed)
    log.finished_at = datetime.now(timezone.utc)

    if changed:
        log.status = MonitorJobStatus.UPDATED
        logger.info(
            "Project [%s] has %d repo(s) updated: %s",
            project.name, len(changed),
            ", ".join(r["repo_name"] for r in changed),
        )
    else:
        log.status = MonitorJobStatus.NO_CHANGE

    await db.commit()
    return log


async def check_all_projects() -> list[dict]:
    """Check all projects. Pull if updated. Trigger re-init for changed ones."""
    from daiflow.services.project_service import run_init

    results = []

    async with get_background_db() as db:
        query = select(Project).options(selectinload(Project.repos))
        projects = (await db.execute(query)).scalars().all()

        for project in projects:
            git_repos = [r for r in project.repos if r.git_url]
            if not git_repos:
                continue

            try:
                log = await _check_and_pull_project(db, project)
            except Exception as e:
                logger.error("Monitor failed for project %s: %s", project.id, e)
                # Write a failed log
                err_log = MonitorLog(
                    project_id=project.id,
                    project_name=project.name,
                    status=MonitorJobStatus.FAILED,
                    error=str(e)[:500],
                    finished_at=datetime.now(timezone.utc),
                )
                db.add(err_log)
                await db.commit()
                results.append({
                    "project_id": project.id,
                    "project_name": project.name,
                    "status": "failed",
                    "error": str(e)[:200],
                })
                continue

            status_str = MonitorJobStatus(log.status).name.lower()
            entry = {
                "project_id": project.id,
                "project_name": project.name,
                "status": status_str,
                "repos_changed": json.loads(log.repos_changed),
            }
            results.append(entry)

            # Auto trigger re-init if repos changed
            if log.status == MonitorJobStatus.UPDATED:
                logger.info("Triggering re-init for project %s", project.name)
                asyncio.create_task(run_init(project.id))

    return results


async def _get_interval() -> int:
    """Read monitor interval from settings."""
    try:
        async with get_background_db() as db:
            setting = await db.get(Setting, "repo_monitor_interval")
            if setting and setting.value:
                return max(60, int(setting.value))
    except Exception:
        pass
    return DEFAULT_INTERVAL


async def _monitor_loop():
    """Main loop: check periodically."""
    await asyncio.sleep(30)
    logger.info("Repo monitor started")

    while True:
        try:
            await check_all_projects()
        except Exception as e:
            logger.error("Repo monitor cycle failed: %s", e)

        interval = await _get_interval()
        await asyncio.sleep(interval)


def start_monitor():
    """Start the background monitor. Idempotent."""
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        return
    _monitor_task = asyncio.create_task(_monitor_loop())
    logger.info("Repo monitor scheduled (first check in 30s)")


def stop_monitor():
    """Stop the background monitor."""
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        logger.info("Repo monitor stopped")
    _monitor_task = None
