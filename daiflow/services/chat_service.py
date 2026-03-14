"""Extracted chat preparation logic shared by WS handler and HTTP routes.

Each stage chat needs: session_id, cody_client, cody_session_id, on_tool_result, language.
This module provides prepare_stage_chat() to build that context from DB state.
"""

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.models import Session, Task, TaskStatus, Todo
from daiflow.prompts import PLAN_CHAT_PREFIX, TODO_CHAT_PREFIX
from daiflow.services.cody_service import build_cody_client
from daiflow.services.settings_service import get_language_setting
from daiflow.services.skill_service import get_task_dir, get_task_skills_dir
from daiflow.services.task_service import resolve_task_roots, fetch_project_repos, sync_todos_from_file
from daiflow.session_runner import make_file_write_detector


@dataclass
class StageChatContext:
    session_id: str
    cody_client: Any  # AsyncCodyClient (context manager)
    cody_session_id: str | None
    on_tool_result: Callable | None
    language: str | None
    system_prefix: str | None = None  # Prepended to user message for context


async def _get_task_allowed_roots(db: AsyncSession, task_id: str, project_id: str) -> list[str]:
    """Get allowed_roots for a task, including both local repos and git-cloned copies."""
    repos = await fetch_project_repos(db, project_id)
    return resolve_task_roots(task_id, repos)


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
        ValueError: If the entity is not found or in an invalid state.
    """
    lang = await get_language_setting(db)

    if stage == "plan":
        task = await db.get(Task, entity_id)
        if not task:
            raise ValueError(f"Task {entity_id} not found")

        session_id = f"task:{entity_id}:plan"
        task_dir = get_task_dir(entity_id)
        plan_path = task_dir / "plan.md"
        allowed_roots = await _get_task_allowed_roots(db, entity_id, task.project_id)
        skill_dir = str(get_task_skills_dir(entity_id))
        client = await build_cody_client(db, str(task_dir), allowed_roots, skill_dir=skill_dir)

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
            raise ValueError(f"Task {entity_id} not found")

        session_id = f"task:{entity_id}:todo_split"
        task_dir = get_task_dir(entity_id)
        todo_path = task_dir / "todo.json"
        allowed_roots = await _get_task_allowed_roots(db, entity_id, task.project_id)
        skill_dir = str(get_task_skills_dir(entity_id))
        client = await build_cody_client(db, str(task_dir), allowed_roots, skill_dir=skill_dir)

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
            raise ValueError(f"Todo {entity_id} not found")

        task = await db.get(Task, todo.task_id)
        if not task:
            raise ValueError(f"Task {todo.task_id} not found")
        if task.status != TaskStatus.CODING:
            raise ValueError("Task is not in coding stage")

        session_id = f"task:{task.id}:todo:{entity_id}"
        task_dir = get_task_dir(task.id)
        allowed_roots = await _get_task_allowed_roots(db, task.id, task.project_id)
        skill_dir = str(get_task_skills_dir(task.id))
        client = await build_cody_client(db, str(task_dir), allowed_roots, skill_dir=skill_dir)
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
            raise ValueError(f"Task {entity_id} not found")

        session_id = f"task:{entity_id}:review"
        task_dir = get_task_dir(entity_id)
        allowed_roots = await _get_task_allowed_roots(db, entity_id, task.project_id)
        skill_dir = str(get_task_skills_dir(entity_id))
        client = await build_cody_client(db, str(task_dir), allowed_roots, skill_dir=skill_dir)
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
        raise ValueError(f"Unknown stage: {stage}")
