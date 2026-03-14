import json
import logging
import shutil

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from transitions.core import MachineError

from daiflow.config import TASKS_DIR
from daiflow.database import get_db
from daiflow.models import Session, SessionStatus, Task, TaskStatus, Todo
from daiflow.schemas import SubmitMR, TaskCreate, TaskResponse, TaskUpdate, TodoResponse
from daiflow.services.git_service import commit, get_diff, push
from daiflow.services.project_service import repo_dir_name
from daiflow.services.skill_service import get_task_dir
from daiflow.services.task_service import (
    execute_todo,
    fetch_project_repos,
    generate_plan,
    generate_todos,
    init_task,
    start_coding,
)
from daiflow.workflow import TaskWorkflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _task_to_dict(t: Task) -> dict:
    return TaskResponse.model_validate(t).model_dump()


async def _get_task_repos(db: AsyncSession, project_id: str):
    """Get repos and local allowed_roots for a task's project."""
    repos = await fetch_project_repos(db, project_id)
    allowed_roots = [r.local_path for r in repos if r.local_path]
    return repos, allowed_roots


def _resolve_repo_path(repo, task_id: str) -> str | None:
    """Resolve the actual filesystem path for a repo in a task context.

    - Repos with local_path: code lives in user's working directory
    - Git-only repos: code lives in task/code/{repo_name} (isolated copy)
    """
    if repo.local_path:
        return repo.local_path
    elif repo.git_url:
        return str(get_task_dir(task_id) / "code" / repo_dir_name(repo.git_url))
    return None


# ── CRUD ──


@router.get("")
async def list_tasks(
    project_id: str | None = None, db: AsyncSession = Depends(get_db)
):
    query = select(Task).order_by(Task.created_at.desc())
    if project_id:
        query = query.where(Task.project_id == project_id)
    result = await db.execute(query)
    return [_task_to_dict(t) for t in result.scalars().all()]


@router.get("/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_dict(task)


@router.post("")
async def create_task(
    data: TaskCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    task = Task(
        name=data.name,
        project_id=data.project_id,
        description=data.description,
        branch=data.branch,
        prd=data.prd,
        tech_plan=data.tech_plan,
        status=TaskStatus.CREATED,
    )
    db.add(task)
    await db.commit()

    task_id = task.id
    background_tasks.add_task(init_task, task_id)

    return _task_to_dict(task)


@router.put("/{task_id}")
async def update_task(
    task_id: str, data: TaskUpdate, db: AsyncSession = Depends(get_db)
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Only allow updating user-editable fields (not workflow-controlled ones)
    editable_fields = {"name", "description", "branch", "prd"}
    for field, value in data.model_dump(exclude_none=True).items():
        if field in editable_fields:
            setattr(task, field, value)
    await db.commit()
    return _task_to_dict(task)


@router.delete("/{task_id}")
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.delete(task)
    await db.commit()

    task_dir = TASKS_DIR / task_id
    if task_dir.exists():
        shutil.rmtree(task_dir, ignore_errors=True)

    return {"ok": True}


# ── Stage Transitions ──


@router.post("/{task_id}/lock-plan")
async def lock_plan(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    wf = TaskWorkflow(task, db)
    try:
        await wf.lock_plan()
    except MachineError:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from {TaskStatus(task.status).name} to PLAN_LOCKED",
        )
    await db.commit()

    background_tasks.add_task(generate_todos, task_id)

    return {"ok": True, "status": task.status}


@router.post("/{task_id}/start-coding")
async def start_coding_route(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Ensure todos are loaded
    await start_coding(task_id, db)

    # Transition: todo_ready → coding (with _has_todos guard)
    wf = TaskWorkflow(task, db)
    try:
        result = await wf.start_coding()
    except MachineError:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from {TaskStatus(task.status).name} to CODING",
        )
    if not result:
        raise HTTPException(status_code=400, detail="Task has no todos")
    await db.commit()
    return {"ok": True, "status": task.status}


@router.post("/{task_id}/start-review")
async def start_review(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Transition: coding → reviewing (with _all_todos_done guard)
    wf = TaskWorkflow(task, db)
    try:
        result = await wf.start_review()
    except MachineError:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from {TaskStatus(task.status).name} to REVIEWING",
        )
    if not result:
        raise HTTPException(status_code=400, detail="All todos must be done or skipped before review")

    session_id = f"task:{task_id}:review"
    existing = await db.get(Session, session_id)
    if not existing:
        session = Session(session_id=session_id, type="review", ref_id=task_id, task_id=task_id, status=SessionStatus.WAITING)
        db.add(session)

    await db.commit()
    return {"ok": True, "status": task.status}


# ── Init Stage ──


@router.post("/{task_id}/confirm-init")
async def confirm_init(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """User confirms init is done, transition INITIALIZING → PLANNING and start plan generation."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.INITIALIZING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot confirm init in {TaskStatus(task.status).name} state",
        )

    # Transition: initializing → planning
    wf = TaskWorkflow(task, db)
    await wf.plan_ready()
    await db.commit()

    background_tasks.add_task(generate_plan, task_id)
    return {"ok": True, "status": task.status}


@router.post("/{task_id}/retry-init")
async def retry_init(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Retry init after failure. Task must be in CREATED state (reset by failed init)."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.CREATED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry init in {TaskStatus(task.status).name} state",
        )

    # Clean up old init sessions so they get re-created
    old_sessions = await db.execute(
        select(Session).where(Session.task_id == task_id, Session.type == "task_init")
    )
    for s in old_sessions.scalars().all():
        await db.delete(s)
    await db.commit()

    background_tasks.add_task(init_task, task_id)
    return {"ok": True, "status": task.status}


@router.get("/{task_id}/init/sessions")
async def get_init_sessions(task_id: str, db: AsyncSession = Depends(get_db)):
    """Get init subtask sessions for a task."""
    result = await db.execute(
        select(Session).where(
            Session.task_id == task_id,
            Session.type == "task_init",
        ).order_by(Session.session_id)
    )
    sessions = result.scalars().all()
    return [
        {
            "session_id": s.session_id,
            "status": s.status,
            "error": s.error,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        }
        for s in sessions
    ]


# ── Plan Stage ──


@router.post("/{task_id}/plan")
async def trigger_plan(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Only allow plan generation in PLANNING state
    if task.status != TaskStatus.PLANNING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot generate plan in {TaskStatus(task.status).name} state",
        )
    background_tasks.add_task(generate_plan, task_id)
    return {"ok": True}


# ── Todo Stage ──


@router.post("/{task_id}/todo")
async def trigger_todo(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Only allow todo generation in PLAN_LOCKED state
    if task.status != TaskStatus.PLAN_LOCKED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot generate todos in {TaskStatus(task.status).name} state",
        )
    background_tasks.add_task(generate_todos, task_id)
    return {"ok": True}


@router.get("/{task_id}/todos")
async def get_todos(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Todo).where(Todo.task_id == task_id).order_by(Todo.seq)
    )
    todos = result.scalars().all()
    return [TodoResponse.model_validate(t).model_dump() for t in todos]


# ── Review Stage ──


@router.get("/{task_id}/diff")
async def get_task_diff(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    repos, _ = await _get_task_repos(db, task.project_id)

    diffs = []
    for repo in repos:
        repo_path = _resolve_repo_path(repo, task_id)
        if not repo_path:
            continue
        repo_label = repo.git_url or repo.local_path
        try:
            diff = await get_diff(repo_path, task.branch)
            if diff:
                diffs.append({"repo": repo_label, "repo_type": repo.repo_type, "diff": diff})
        except Exception as e:
            diffs.append({"repo": repo_label, "repo_type": repo.repo_type, "diff": "", "error": str(e)})

    return {"diffs": diffs}


@router.post("/{task_id}/generate-commit-message")
async def generate_commit_message(task_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a commit message from the task's diff using AI."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    repos, allowed_roots = await _get_task_repos(db, task.project_id)

    # Collect diffs
    diff_texts = []
    for repo in repos:
        repo_path = _resolve_repo_path(repo, task_id)
        if not repo_path:
            continue
        try:
            d = await get_diff(repo_path, task.branch)
            if d:
                diff_texts.append(d)
        except Exception:
            pass

    if not diff_texts:
        return {"commit_message": f"feat: {task.name}"}

    # Truncate diff if too large (keep first 8000 chars)
    combined_diff = "\n".join(diff_texts)
    if len(combined_diff) > 8000:
        combined_diff = combined_diff[:8000] + "\n... (truncated)"

    prompt = (
        "Generate a concise git commit message for the following changes.\n"
        "Use conventional commit format (feat/fix/refactor/docs/chore).\n"
        "Include a short subject line and a brief body with bullet points.\n\n"
        f"Task: {task.name}\n"
        f"Description: {task.description or 'N/A'}\n\n"
        f"Diff:\n```\n{combined_diff}\n```\n\n"
        "Output ONLY the commit message, nothing else."
    )

    try:
        from daiflow.services.cody_service import build_cody_client
        # Resolve workdir: prefer first allowed_root, fallback to resolved repo path or task dir
        if allowed_roots:
            workdir = allowed_roots[0]
        else:
            resolved = [_resolve_repo_path(r, task_id) for r in repos]
            resolved = [p for p in resolved if p]
            workdir = resolved[0] if resolved else str(get_task_dir(task_id))
            allowed_roots = resolved or [workdir]
        client = await build_cody_client(db, workdir, allowed_roots)
        result_text = ""
        async with client:
            async for chunk in client.stream(prompt):
                if chunk.type == "text_delta":
                    result_text += chunk.content
                elif chunk.type == "done":
                    break
        return {"commit_message": result_text.strip() or f"feat: {task.name}"}
    except Exception:
        logger.warning("AI commit message generation failed for task %s", task_id, exc_info=True)
        return {"commit_message": f"feat: {task.name}\n\n{task.description or ''}"}


@router.post("/{task_id}/submit-mr")
async def submit_mr(
    task_id: str, data: SubmitMR, db: AsyncSession = Depends(get_db)
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    repos, _ = await _get_task_repos(db, task.project_id)

    commit_msg = data.commit_message or f"feat: {task.name}"

    # Build list of (repo, resolved_path) for repos that have code
    active_repos = []
    for repo in repos:
        repo_path = _resolve_repo_path(repo, task_id)
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

    # Only mark as DONE if at least one repo succeeded
    has_success = any(r["status"] == "success" for r in results)
    if has_success:
        wf = TaskWorkflow(task, db)
        try:
            await wf.finish()
        except MachineError:
            logger.warning("Could not transition task %s to DONE", task_id)
    task.mr_info = json.dumps(results)
    await db.commit()

    return {"ok": True, "results": results}
