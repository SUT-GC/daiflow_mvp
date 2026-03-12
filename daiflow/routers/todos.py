from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.database import get_db
from daiflow.models import Task, TaskStatus, Todo, TodoStatus
from daiflow.services.task_service import execute_todo

router = APIRouter(prefix="/api/todos", tags=["todos"])


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


