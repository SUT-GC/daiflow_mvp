"""Extracted chat preparation logic shared by WS handler and HTTP routes.

Each stage chat needs: session_id, cody_client, cody_session_id, on_tool_result, language.
This module provides prepare_stage_chat() which delegates to agent_executor.prepare_chat().
"""

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.exceptions import InvalidStateError, NotFoundError
from daiflow.models import Task, TaskStatus, Todo
from daiflow.session_ids import task_plan, task_review, task_todo_exec, task_todo_split


@dataclass
class StageChatContext:
    session_id: str
    cody_client: Any  # AsyncCodyClient (context manager)
    cody_session_id: str | None
    on_tool_result: Callable | None
    language: str | None
    system_prefix: str | None = None  # Prepended to user message for context


# Map stage names to (agent_type, session_id_fn, entity_is_todo)
_STAGE_MAP = {
    "plan": ("plan", task_plan, False),
    "todo": ("todo_split", task_todo_split, False),
    "todo_exec": ("todo_exec", None, True),  # session_id needs task_id + todo_id
    "review": ("review", task_review, False),
}


async def prepare_stage_chat(
    db: AsyncSession,
    stage: str,
    entity_id: str,
) -> StageChatContext:
    """Build everything needed to run a stage chat.

    Delegates to agent_executor.prepare_chat() for the actual construction,
    but handles entity validation and session_id resolution here.

    Args:
        db: Database session.
        stage: One of "plan", "todo", "todo_exec", "review".
        entity_id: task_id for plan/todo/review, todo_id for todo_exec.

    Returns:
        StageChatContext with all fields populated.

    Raises:
        NotFoundError: If the entity is not found.
        InvalidStateError: If the entity is in an invalid state for chat.
    """
    from daiflow.agent_executor import prepare_chat

    if stage not in _STAGE_MAP:
        raise InvalidStateError(f"Unknown stage: {stage}")

    agent_type, session_id_fn, entity_is_todo = _STAGE_MAP[stage]

    # Validate entity and compute session_id
    if entity_is_todo:
        # todo_exec: entity_id is todo_id
        todo = await db.get(Todo, entity_id)
        if not todo:
            raise NotFoundError(f"Todo {entity_id} not found")
        task = await db.get(Task, todo.task_id)
        if not task:
            raise NotFoundError(f"Task {todo.task_id} not found")
        if task.status != TaskStatus.CODING:
            raise InvalidStateError("Task is not in coding stage")
        session_id = task_todo_exec(task.id, entity_id)
    else:
        # plan/todo/review: entity_id is task_id
        task = await db.get(Task, entity_id)
        if not task:
            raise NotFoundError(f"Task {entity_id} not found")
        session_id = session_id_fn(entity_id)

    return await prepare_chat(db, agent_type, entity_id, session_id)
