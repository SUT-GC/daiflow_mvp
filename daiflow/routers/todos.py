from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import get_language_setting
from daiflow.database import get_db
from daiflow.models import ProjectRepo, Task, TaskStatus, Todo, TodoStatus
from daiflow.services.cody_service import build_cody_client
from daiflow.services.skill_service import get_task_dir
from daiflow.services.task_service import execute_todo
from daiflow.session_runner import make_file_write_detector, run_stage_chat

router = APIRouter(prefix="/api/todos", tags=["todos"])


class ChatMessage(BaseModel):
    message: str


@router.post("/{todo_id}/execute")
async def execute_todo_route(
    todo_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    todo = await db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    task = await db.get(Task, todo.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.CODING:
        raise HTTPException(status_code=400, detail="Task is not in coding stage")
    if todo.status not in (TodoStatus.PENDING, TodoStatus.FAILED):
        raise HTTPException(status_code=400, detail=f"Todo is {TodoStatus(todo.status).name}, cannot execute")

    background_tasks.add_task(execute_todo, todo_id)
    return {"ok": True}


@router.post("/{todo_id}/chat")
async def todo_exec_chat(
    todo_id: str, data: ChatMessage, db: AsyncSession = Depends(get_db)
):
    todo = await db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    task = await db.get(Task, todo.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.CODING:
        raise HTTPException(status_code=400, detail="Task is not in coding stage")

    session_id = f"task:{task.id}:todo:{todo_id}"
    task_dir = get_task_dir(task.id)

    result = await db.execute(
        select(ProjectRepo).where(ProjectRepo.project_id == task.project_id)
    )
    repos = result.scalars().all()
    allowed_roots = [r.local_path for r in repos if r.local_path]

    client = await build_cody_client(db, str(task_dir), allowed_roots)

    on_tool_result = make_file_write_detector(None, "code_updated")
    lang = await get_language_setting(db)

    async def generator():
        async with client:
            async for chunk in run_stage_chat(
                session_id, client, todo.cody_session_id, data.message, on_tool_result, language=lang
            ):
                yield chunk

    return StreamingResponse(generator(), media_type="text/event-stream")
