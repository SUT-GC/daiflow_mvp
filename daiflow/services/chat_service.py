"""Extracted chat preparation logic shared by WS handler and HTTP routes.

Each stage chat needs: session_id, cody_client, cody_session_id, on_tool_result, language.
This module provides prepare_stage_chat() to build that context from DB state.
"""

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.exceptions import InvalidStateError, NotFoundError
from daiflow.models import Session, Task, TaskStatus, Todo
from daiflow.prompts import PLAN_CHAT_PREFIX, TODO_CHAT_PREFIX
from daiflow.services.cody_service import build_task_cody_client
from daiflow.services.settings_service import get_language_setting
from daiflow.services.skill_service import get_task_dir
from daiflow.services.task_service import sync_todos_from_file
from daiflow.session_ids import task_plan, task_review, task_todo_exec, task_todo_split
from daiflow.session_runner import make_file_write_detector


@dataclass
class StageChatContext:
    session_id: str
    cody_client: Any  # AsyncCodyClient (context manager)
    cody_session_id: str | None
    on_tool_result: Callable | None
    language: str | None
    system_prefix: str | None = None  # Prepended to user message for context


async def prepare_stage_chat(
    db: AsyncSession,
    stage: str,
    entity_id: str,
) -> StageChatContext:
    """Build everything needed to run a stage chat.

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
    lang = await get_language_setting(db)

    if stage == "plan":
        task = await db.get(Task, entity_id)
        if not task:
            raise NotFoundError(f"Task {entity_id} not found")

        session_id = task_plan(entity_id)
        task_dir = get_task_dir(entity_id)
        plan_path = task_dir / "plan.md"
        client = await build_task_cody_client(db, entity_id, task.project_id)

        async def on_plan_match(_file_path):
            if plan_path.exists():
                content = plan_path.read_text(encoding="utf-8")
                task.tech_plan = content
                await db.commit()
                return content
            return None

        on_tool_result = make_file_write_detector("plan.md", "plan_updated", on_plan_match)

        system_prefix = PLAN_CHAT_PREFIX.format(plan_path=plan_path)

        # Look up cody_session_id via task_id FK
        result = await db.execute(
            select(Session.cody_session_id).where(
                Session.task_id == entity_id, Session.type == "plan",
            )
        )
        plan_cody_sid = result.scalar()

        return StageChatContext(
            session_id=session_id,
            cody_client=client,
            cody_session_id=plan_cody_sid,
            on_tool_result=on_tool_result,
            language=lang,
            system_prefix=system_prefix,
        )

    elif stage == "todo":
        task = await db.get(Task, entity_id)
        if not task:
            raise NotFoundError(f"Task {entity_id} not found")

        session_id = task_todo_split(entity_id)
        task_dir = get_task_dir(entity_id)
        todo_path = task_dir / "todo.json"
        client = await build_task_cody_client(db, entity_id, task.project_id)

        async def on_todo_match(_file_path):
            if todo_path.exists():
                content = todo_path.read_text(encoding="utf-8")
                await sync_todos_from_file(db, entity_id, content)
                return content
            return None

        on_tool_result = make_file_write_detector("todo.json", "todo_updated", on_todo_match)

        system_prefix = TODO_CHAT_PREFIX.format(todo_path=todo_path)

        # Todo chat reuses plan's cody session — look up via task_id FK
        result = await db.execute(
            select(Session.cody_session_id).where(
                Session.task_id == entity_id, Session.type == "plan",
            )
        )
        plan_cody_sid = result.scalar()

        return StageChatContext(
            session_id=session_id,
            cody_client=client,
            cody_session_id=plan_cody_sid,
            on_tool_result=on_tool_result,
            language=lang,
            system_prefix=system_prefix,
        )

    elif stage == "todo_exec":
        todo = await db.get(Todo, entity_id)
        if not todo:
            raise NotFoundError(f"Todo {entity_id} not found")

        task = await db.get(Task, todo.task_id)
        if not task:
            raise NotFoundError(f"Task {todo.task_id} not found")
        if task.status != TaskStatus.CODING:
            raise InvalidStateError("Task is not in coding stage")

        session_id = task_todo_exec(task.id, entity_id)
        client = await build_task_cody_client(db, task.id, task.project_id)
        on_tool_result = make_file_write_detector(None, "code_updated")

        return StageChatContext(
            session_id=session_id,
            cody_client=client,
            cody_session_id=todo.cody_session_id,
            on_tool_result=on_tool_result,
            language=lang,
        )

    elif stage == "review":
        task = await db.get(Task, entity_id)
        if not task:
            raise NotFoundError(f"Task {entity_id} not found")

        session_id = task_review(entity_id)
        client = await build_task_cody_client(db, entity_id, task.project_id)
        on_tool_result = make_file_write_detector(None, "code_updated")

        # Look up cody_session_id via task_id FK
        result = await db.execute(
            select(Session.cody_session_id).where(
                Session.task_id == entity_id, Session.type == "review",
            )
        )
        review_cody_sid = result.scalar()

        return StageChatContext(
            session_id=session_id,
            cody_client=client,
            cody_session_id=review_cody_sid,
            on_tool_result=on_tool_result,
            language=lang,
        )

    else:
        raise InvalidStateError(f"Unknown stage: {stage}")
