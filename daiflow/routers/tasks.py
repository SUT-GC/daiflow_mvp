import json
import shutil

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import TASKS_DIR, get_language_setting
from daiflow.database import get_db
from daiflow.models import ProjectRepo, Session, Task, TaskStatus, Todo
from daiflow.services.cody_service import build_cody_client
from daiflow.services.git_service import commit, get_diff, push
from daiflow.services.skill_service import get_task_dir
from daiflow.services.task_service import (
    execute_todo,
    generate_plan,
    generate_todos,
    init_task,
    start_coding,
    sync_todos_from_file,
)
from daiflow.session_runner import make_file_write_detector, run_stage_chat

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

VALID_TRANSITIONS = {
    TaskStatus.PLANNING: {TaskStatus.PLAN_LOCKED},
    TaskStatus.PLAN_LOCKED: {TaskStatus.TODO_READY},
    TaskStatus.TODO_READY: {TaskStatus.CODING},
    TaskStatus.CODING: {TaskStatus.REVIEWING},
    TaskStatus.REVIEWING: {TaskStatus.DONE},
}


def _check_transition(task: Task, target: TaskStatus):
    current = TaskStatus(task.status)
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from {current.name} to {target.name}"
        )


class TaskCreate(BaseModel):
    name: str
    project_id: str
    description: str = ""
    branch: str = ""
    prd: str = ""
    tech_plan: str = ""


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    branch: str | None = None
    prd: str | None = None
    tech_plan: str | None = None


class ChatMessage(BaseModel):
    message: str


def _task_to_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "project_id": t.project_id,
        "description": t.description,
        "branch": t.branch,
        "prd": t.prd,
        "tech_plan": t.tech_plan,
        "status": t.status,
        "mr_info": json.loads(t.mr_info) if t.mr_info else {},
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


async def _get_task_repos(db: AsyncSession, project_id: str):
    """Get repos and allowed_roots for a task's project."""
    result = await db.execute(
        select(ProjectRepo).where(ProjectRepo.project_id == project_id)
    )
    repos = result.scalars().all()
    allowed_roots = [r.local_path for r in repos if r.local_path]
    return repos, allowed_roots


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
        status=TaskStatus.INITIALIZING,
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

    for field, value in data.model_dump(exclude_none=True).items():
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
    _check_transition(task, TaskStatus.PLAN_LOCKED)
    task.status = TaskStatus.PLAN_LOCKED
    await db.commit()

    background_tasks.add_task(generate_todos, task_id)

    return {"ok": True, "status": task.status}


@router.post("/{task_id}/start-coding")
async def start_coding_route(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _check_transition(task, TaskStatus.CODING)
    await start_coding(task_id, db)
    await db.refresh(task)
    return {"ok": True, "status": task.status}


@router.post("/{task_id}/start-review")
async def start_review(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    _check_transition(task, TaskStatus.REVIEWING)

    session_id = f"task:{task_id}:review"
    existing = await db.get(Session, session_id)
    if not existing:
        session = Session(session_id=session_id, type="review", ref_id=task_id, status=0)
        db.add(session)

    task.status = TaskStatus.REVIEWING
    await db.commit()
    return {"ok": True, "status": task.status}


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
    background_tasks.add_task(generate_plan, task_id)
    return {"ok": True}


@router.post("/{task_id}/plan/chat")
async def plan_chat(
    task_id: str, data: ChatMessage, db: AsyncSession = Depends(get_db)
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    session_id = f"task:{task_id}:plan"
    task_dir = get_task_dir(task_id)
    plan_path = task_dir / "plan.md"

    _, allowed_roots = await _get_task_repos(db, task.project_id)
    client = await build_cody_client(db, str(task_dir), allowed_roots)

    async def on_plan_match(_file_path):
        if plan_path.exists():
            content = plan_path.read_text(encoding="utf-8")
            task.tech_plan = content
            await db.commit()
            return content
        return None

    on_tool_result = make_file_write_detector("plan.md", "plan_updated", on_plan_match)
    lang = await get_language_setting(db)

    async def generator():
        async with client:
            async for chunk in run_stage_chat(
                session_id, client, task.plan_cody_session_id, data.message, on_tool_result, language=lang
            ):
                yield chunk

    return StreamingResponse(generator(), media_type="text/event-stream")


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
    background_tasks.add_task(generate_todos, task_id)
    return {"ok": True}


@router.post("/{task_id}/todo/chat")
async def todo_chat(
    task_id: str, data: ChatMessage, db: AsyncSession = Depends(get_db)
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    session_id = f"task:{task_id}:todo_split"
    task_dir = get_task_dir(task_id)
    todo_path = task_dir / "todo.json"

    _, allowed_roots = await _get_task_repos(db, task.project_id)
    client = await build_cody_client(db, str(task_dir), allowed_roots)

    async def on_todo_match(_file_path):
        if todo_path.exists():
            content = todo_path.read_text(encoding="utf-8")
            await sync_todos_from_file(db, task_id, content)
            return content
        return None

    on_tool_result = make_file_write_detector("todo.json", "todo_updated", on_todo_match)
    lang = await get_language_setting(db)

    async def generator():
        async with client:
            async for chunk in run_stage_chat(
                session_id, client, task.plan_cody_session_id, data.message, on_tool_result, language=lang
            ):
                yield chunk

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.get("/{task_id}/todos")
async def get_todos(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Todo).where(Todo.task_id == task_id).order_by(Todo.seq)
    )
    todos = result.scalars().all()
    return [
        {
            "id": t.id,
            "seq": t.seq,
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "cody_session_id": t.cody_session_id,
        }
        for t in todos
    ]


# ── Review Stage ──


@router.get("/{task_id}/diff")
async def get_task_diff(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    repos, _ = await _get_task_repos(db, task.project_id)

    diffs = []
    for repo in repos:
        if repo.local_path:
            try:
                diff = await get_diff(repo.local_path, task.branch)
                if diff:
                    diffs.append({"repo": repo.git_url, "repo_type": repo.repo_type, "diff": diff})
            except Exception as e:
                diffs.append({"repo": repo.git_url, "repo_type": repo.repo_type, "diff": "", "error": str(e)})

    return {"diffs": diffs}


@router.post("/{task_id}/review/chat")
async def review_chat(
    task_id: str, data: ChatMessage, db: AsyncSession = Depends(get_db)
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    session_id = f"task:{task_id}:review"
    task_dir = get_task_dir(task_id)

    _, allowed_roots = await _get_task_repos(db, task.project_id)
    client = await build_cody_client(db, str(task_dir), allowed_roots)

    on_tool_result = make_file_write_detector(None, "code_updated")
    lang = await get_language_setting(db)

    async def generator():
        async with client:
            async for chunk in run_stage_chat(
                session_id, client, task.review_cody_session_id, data.message, on_tool_result, language=lang
            ):
                yield chunk

    return StreamingResponse(generator(), media_type="text/event-stream")


class SubmitMR(BaseModel):
    commit_message: str = ""


@router.post("/{task_id}/submit-mr")
async def submit_mr(
    task_id: str, data: SubmitMR, db: AsyncSession = Depends(get_db)
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    repos, _ = await _get_task_repos(db, task.project_id)

    commit_msg = data.commit_message or f"feat: {task.name}"

    results = []
    for repo in repos:
        if repo.local_path:
            try:
                await commit(repo.local_path, commit_msg)
                await push(repo.local_path, task.branch)
                results.append({"repo": repo.git_url, "status": "success"})
            except Exception as e:
                results.append({"repo": repo.git_url, "status": "error", "error": str(e)})

    task.status = TaskStatus.DONE
    task.mr_info = json.dumps(results)
    await db.commit()

    return {"ok": True, "results": results}
