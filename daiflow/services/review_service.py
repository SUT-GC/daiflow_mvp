"""Review stage service: diff aggregation, commit message generation, MR submission."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.models import Task
from daiflow.prompts import COMMIT_MESSAGE_PROMPT_TEMPLATE
from daiflow.services.cody_service import build_cody_client
from daiflow.services.git_service import commit, get_diff, push
from daiflow.services.skill_service import get_task_dir
from daiflow.services.task_service import fetch_project_repos, resolve_repo_path

logger = logging.getLogger(__name__)


async def get_task_diffs(db: AsyncSession, task: Task) -> list[dict]:
    """Collect git diffs across all repos for a task."""
    repos = await fetch_project_repos(db, task.project_id)
    diffs = []
    for repo in repos:
        repo_path = resolve_repo_path(repo, task.id)
        if not repo_path:
            continue
        repo_label = repo.git_url or repo.local_path
        try:
            diff = await get_diff(repo_path, task.branch)
            if diff:
                diffs.append({"repo": repo_label, "repo_type": repo.repo_type, "diff": diff})
        except Exception as e:
            diffs.append({"repo": repo_label, "repo_type": repo.repo_type, "diff": "", "error": str(e)})
    return diffs


async def generate_commit_message(db: AsyncSession, task: Task) -> str:
    """Generate a commit message from the task's diff using AI.

    Falls back to a simple message if AI generation fails or there are no diffs.
    """
    fallback = f"feat: {task.name}"

    repos = await fetch_project_repos(db, task.project_id)
    allowed_roots = [p for r in repos if (p := resolve_repo_path(r, task.id))]

    # Collect diffs
    diff_texts = []
    for root in allowed_roots:
        try:
            d = await get_diff(root, task.branch)
            if d:
                diff_texts.append(d)
        except Exception:
            pass

    if not diff_texts:
        return fallback

    # Truncate diff if too large (keep first 8000 chars)
    combined_diff = "\n".join(diff_texts)
    if len(combined_diff) > 8000:
        combined_diff = combined_diff[:8000] + "\n... (truncated)"

    prompt = COMMIT_MESSAGE_PROMPT_TEMPLATE.format(
        task_name=task.name,
        task_description=task.description or "N/A",
        diff=combined_diff,
    )

    try:
        workdir = allowed_roots[0] if allowed_roots else str(get_task_dir(task.id))
        client = await build_cody_client(db, workdir, allowed_roots or [workdir])
        result_text = ""
        async with client:
            async for chunk in client.stream(prompt):
                if chunk.type == "text_delta":
                    result_text += chunk.content
                elif chunk.type == "done":
                    break
        return result_text.strip() or fallback
    except Exception:
        logger.warning("AI commit message generation failed for task %s", task.id, exc_info=True)
        return f"{fallback}\n\n{task.description or ''}"


async def submit_mr(db: AsyncSession, task: Task, commit_message: str) -> list[dict]:
    """Commit and push changes across all repos.

    Returns a list of per-repo result dicts with status/error fields.
    State transition (REVIEWING → DONE) is handled by the router for consistency
    with other stage transitions.
    """
    repos = await fetch_project_repos(db, task.project_id)
    commit_msg = commit_message or f"feat: {task.name}"

    # Build list of (repo, resolved_path) for repos that have code
    active_repos = []
    for repo in repos:
        repo_path = resolve_repo_path(repo, task.id)
        if repo_path:
            active_repos.append((repo, repo_path))

    # Phase 1: commit all repos first (safer — all-or-nothing per phase)
    commit_results = []
    for repo, repo_path in active_repos:
        repo_label = repo.git_url or repo.local_path
        try:
            await commit(repo_path, commit_msg)
            commit_results.append({"repo": repo_label, "committed": True})
        except Exception as e:
            commit_results.append({"repo": repo_label, "committed": False, "error": str(e)})

    # Phase 2: push only successfully committed repos
    results = []
    for (repo, repo_path), cr in zip(active_repos, commit_results):
        repo_label = repo.git_url or repo.local_path
        if not cr.get("committed"):
            results.append({"repo": repo_label, "status": "error", "error": cr.get("error", "commit failed")})
            continue
        try:
            await push(repo_path, task.branch)
            results.append({"repo": repo_label, "status": "success"})
        except Exception as e:
            results.append({"repo": repo_label, "status": "error", "error": str(e)})

    return results
