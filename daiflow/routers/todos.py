import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from transitions.core import MachineError

from daiflow.database import get_db
from daiflow.models import Task, TaskStatus, Todo, TodoStatus
from daiflow.services.task_service import execute_todo
from daiflow.services.git_service import get_diff_between
from daiflow.workflow import TodoWorkflow

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

    # Use may_execute / may_retry to validate without actually transitioning
    # (transitions auto-generates may_<trigger> methods that check source state + conditions)
    wf = TodoWorkflow(todo, db)
    if todo.status == TodoStatus.PENDING:
        if not await wf.may_execute():
            raise HTTPException(status_code=400, detail="Previous todo must be completed first")
    elif todo.status == TodoStatus.FAILED:
        if not await wf.may_retry():
            raise HTTPException(status_code=400, detail="Previous todo must be completed first")
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Todo is {TodoStatus(todo.status).name}, cannot execute",
        )

    background_tasks.add_task(execute_todo, todo_id)
    return {"ok": True}


@router.post("/{todo_id}/skip")
async def skip_todo_route(
    todo_id: str,
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

    wf = TodoWorkflow(todo, db)
    try:
        await wf.skip()
    except MachineError:
        raise HTTPException(
            status_code=400,
            detail=f"Todo is {TodoStatus(todo.status).name}, only PENDING or FAILED todos can be skipped",
        )
    await db.commit()
    return {"ok": True}


@router.get("/{todo_id}/diff")
async def get_todo_diff(todo_id: str, db: AsyncSession = Depends(get_db)):
    """Get the diff produced by a specific todo execution."""
    todo = await db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    before = json.loads(todo.commit_before or "{}")
    after = json.loads(todo.commit_after or "{}")

    if not before or not after:
        return {"diffs": []}

    diffs = []
    for repo_path, hash_before in before.items():
        hash_after = after.get(repo_path)
        if not hash_after or hash_before == hash_after:
            continue
        try:
            diff = await get_diff_between(repo_path, hash_before, hash_after)
            if diff:
                diffs.append({"repo": repo_path, "diff": diff})
        except Exception:
            pass

    return {"diffs": diffs}


