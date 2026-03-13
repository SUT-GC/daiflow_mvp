"""Background job that monitors project repos for new commits on master/main.

Periodically fetches remote and compares HEAD hash with stored master_hash.
When changes are detected, notifies via WebSocket and optionally triggers
knowledge re-generation (project re-init).
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from daiflow.database import get_background_db
from daiflow.models import Project, ProjectRepo
from daiflow.services.git_service import fetch_remote, get_remote_head
from daiflow.services.skill_service import get_project_dir
from daiflow.services.project_service import _repo_dir_name
from daiflow.ws_manager import ws_manager

logger = logging.getLogger(__name__)

# Default check interval in seconds (5 minutes)
DEFAULT_INTERVAL = 300

# Global handle for the monitor task so it can be cancelled on shutdown
_monitor_task: asyncio.Task | None = None


async def _check_project_repos(project: Project, repos: list[ProjectRepo]) -> list[dict]:
    """Check all git repos in a project for new remote commits.

    Returns a list of dicts describing repos that have new commits:
    [{"repo_id": ..., "repo_name": ..., "old_hash": ..., "new_hash": ...}, ...]
    """
    project_dir = get_project_dir(project.id)
    changed = []

    for repo in repos:
        if not repo.git_url:
            continue

        clone_dir = project_dir / "code" / _repo_dir_name(repo.git_url)
        if not (clone_dir / ".git").exists():
            # Repo not cloned yet (init not run), skip
            continue

        try:
            await fetch_remote(str(clone_dir))
            new_hash = await get_remote_head(str(clone_dir))
            if not new_hash:
                continue

            old_hash = repo.master_hash or ""
            if old_hash and new_hash != old_hash:
                changed.append({
                    "repo_id": repo.id,
                    "repo_name": _repo_dir_name(repo.git_url),
                    "git_url": repo.git_url,
                    "old_hash": old_hash[:8],
                    "new_hash": new_hash[:8],
                })

            # Always update the stored hash (initial seed or change)
            repo.master_hash = new_hash

        except Exception as e:
            logger.warning(
                "Failed to check repo %s for project %s: %s",
                repo.git_url, project.id, e,
            )

    return changed


async def check_all_projects() -> list[dict]:
    """Check all projects for repo changes. Returns list of change events."""
    all_changes = []

    async with get_background_db() as db:
        result = await db.execute(
            select(Project).options(selectinload(Project.repos))
        )
        projects = result.scalars().all()

        for project in projects:
            git_repos = [r for r in project.repos if r.git_url]
            if not git_repos:
                continue

            changed = await _check_project_repos(project, git_repos)

            if changed:
                event = {
                    "type": "repo_changed",
                    "project_id": project.id,
                    "project_name": project.name,
                    "repos": changed,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                }
                all_changes.append(event)

                # Notify via WebSocket on a project-scoped channel
                await ws_manager.publish(
                    f"project:monitor:{project.id}", event,
                )
                # Also publish to a global monitor channel
                await ws_manager.publish("monitor:repo_changes", event)

                logger.info(
                    "Detected %d repo change(s) in project %s: %s",
                    len(changed), project.name,
                    ", ".join(r["repo_name"] for r in changed),
                )

        await db.commit()

    return all_changes


async def _get_interval() -> int:
    """Read the monitor interval from settings. Falls back to DEFAULT_INTERVAL."""
    try:
        async with get_background_db() as db:
            from daiflow.models import Setting
            setting = await db.get(Setting, "repo_monitor_interval")
            if setting and setting.value:
                return max(60, int(setting.value))  # minimum 60s
    except Exception:
        pass
    return DEFAULT_INTERVAL


async def _monitor_loop():
    """Main loop: periodically checks repos and sleeps."""
    # Wait a bit after startup before first check
    await asyncio.sleep(30)
    logger.info("Repo monitor started")

    while True:
        try:
            await check_all_projects()
        except Exception as e:
            logger.error("Repo monitor check failed: %s", e)

        interval = await _get_interval()
        await asyncio.sleep(interval)


def start_monitor():
    """Start the repo monitor background task. Idempotent."""
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        return
    _monitor_task = asyncio.create_task(_monitor_loop())
    logger.info("Repo monitor task created (first check in 30s)")


def stop_monitor():
    """Stop the repo monitor background task."""
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        logger.info("Repo monitor task cancelled")
    _monitor_task = None
