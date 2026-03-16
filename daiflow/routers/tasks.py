import json
import logging
import os
import shutil
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import TASKS_DIR, utc_iso
from daiflow.database import get_db
from daiflow.models import Session, SessionStatus, Task, TaskStatus, Todo
from daiflow.schemas import SubmitMR, TaskCreate, TaskResponse, TaskUpdate, TodoResponse
from daiflow.services import review_service
from daiflow.services.task_service import (
    execute_todo,
    generate_plan,
    generate_todos,
    init_task,
)
from daiflow.workflow import TaskWorkflow
from daiflow.workflow.orchestrator import (
    TransitionError,
    finish_task,
    lock_plan_and_generate_todos,
    start_coding_stage,
    start_review_stage,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _task_to_dict(t: Task) -> dict:
    return TaskResponse.model_validate(t).model_dump()


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
    # Block if project is currently generating knowledge
    running_init = await db.execute(
        select(Session).where(
            Session.ref_id == data.project_id,
            Session.type == "init",
            Session.status.in_([SessionStatus.WAITING, SessionStatus.RUNNING]),
        )
    )
    if running_init.scalars().first():
        raise HTTPException(
            status_code=409,
            detail="Project knowledge is being generated. Please wait for it to finish before creating a task.",
        )

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


ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
_EXT_TO_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


@router.get("/{task_id}/prd-images/{filename}")
async def get_prd_image(task_id: str, filename: str):
    """Serve a PRD image file."""
    img_path = TASKS_DIR / task_id / "prd_images" / filename
    # Prevent path traversal
    if ".." in filename or "/" in filename or not img_path.resolve().is_relative_to((TASKS_DIR / task_id / "prd_images").resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    ext = os.path.splitext(filename)[1].lower()
    media_type = _EXT_TO_MEDIA.get(ext, "application/octet-stream")
    return FileResponse(img_path, media_type=media_type)


@router.post("/{task_id}/prd-images")
async def upload_prd_image(
    task_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    """Upload an image for the task's PRD. Returns the image filename."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {file.content_type}")

    data = await file.read()
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="Image too large (max 10 MB)")

    # Determine extension from content type
    ext = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }[file.content_type]
    filename = f"{uuid.uuid4().hex[:12]}{ext}"

    img_dir = TASKS_DIR / task_id / "prd_images"
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / filename).write_bytes(data)

    # Update prd_images JSON array in DB
    images: list = json.loads(task.prd_images or "[]")
    images.append(filename)
    task.prd_images = json.dumps(images)
    await db.commit()

    return {"filename": filename}


@router.delete("/{task_id}/prd-images/{filename}")
async def delete_prd_image(
    task_id: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a PRD image by filename."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    images: list = json.loads(task.prd_images or "[]")
    if filename not in images:
        raise HTTPException(status_code=404, detail="Image not found")

    # Remove file
    img_path = TASKS_DIR / task_id / "prd_images" / filename
    if img_path.exists():
        img_path.unlink()

    # Update DB
    images.remove(filename)
    task.prd_images = json.dumps(images)
    await db.commit()

    return {"ok": True}


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

    try:
        await lock_plan_and_generate_todos(db, task)
    except TransitionError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    background_tasks.add_task(generate_todos, task_id)

    return {"ok": True, "status": task.status}


@router.post("/{task_id}/start-coding")
async def start_coding_route(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        await start_coding_stage(db, task)
    except TransitionError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    return {"ok": True, "status": task.status}


@router.post("/{task_id}/start-review")
async def start_review(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        await start_review_stage(db, task)
    except TransitionError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

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
            "started_at": utc_iso(s.started_at) if s.started_at else None,
            "finished_at": utc_iso(s.finished_at) if s.finished_at else None,
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
    diffs = await review_service.get_task_diffs(db, task)
    return {"diffs": diffs}


@router.post("/{task_id}/generate-commit-message")
async def generate_commit_message_route(task_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a commit message from the task's diff using AI."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    msg = await review_service.generate_commit_message(db, task)
    return {"commit_message": msg}


@router.post("/{task_id}/submit-mr")
async def submit_mr_route(
    task_id: str, data: SubmitMR, db: AsyncSession = Depends(get_db)
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    results = await review_service.submit_mr(db, task, data.commit_message)

    # State transition: REVIEWING → DONE (consistent with other transitions in router)
    has_success = any(r["status"] == "success" for r in results)
    if has_success:
        await finish_task(db, task)
    task.mr_info = json.dumps(results)
    await db.commit()

    return {"ok": True, "results": results}
