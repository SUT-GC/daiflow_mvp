"""Extracted chat preparation logic shared by WS handler and HTTP routes.

Each stage chat needs: session_id, cody_client, cody_session_id, on_tool_result, language.
This module provides prepare_stage_chat() to build that context from DB state.
"""

from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.services.settings_service import get_language_setting
from daiflow.models import ProjectRepo, Task, TaskStatus, Todo, TodoStatus
from daiflow.services.cody_service import build_cody_client
from daiflow.services.skill_service import get_task_dir
from daiflow.services.task_service import sync_todos_from_file
from daiflow.session_runner import make_file_write_detector


@dataclass
class StageChatContext:
    session_id: str
    cody_client: Any  # AsyncCodyClient (context manager)
    cody_session_id: str | None
    on_tool_result: Callable | None
    language: str | None
    system_prefix: str | None = None  # Prepended to user message for context


async def _get_allowed_roots(db: AsyncSession, project_id: str) -> list[str]:
    result = await db.execute(
        select(ProjectRepo).where(ProjectRepo.project_id == project_id)
    )
    repos = result.scalars().all()
    return [r.local_path for r in repos if r.local_path]


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
        allowed_roots = await _get_allowed_roots(db, task.project_id)
        client = await build_cody_client(db, str(task_dir), allowed_roots)

        async def on_plan_match(_file_path):
            if plan_path.exists():
                content = plan_path.read_text(encoding="utf-8")
                task.tech_plan = content
                await db.commit()
                return content
            return None

        on_tool_result = make_file_write_detector("plan.md", "plan_updated", on_plan_match)

        system_prefix = (
            "You are a senior software architect helping refine a technical plan.\n"
            "Your primary task is to discuss and modify the technical plan in `plan.md`.\n\n"
            "## Context\n"
            "- Read `project.md` in the current working directory for project knowledge.\n"
            "- The current technical plan is in `plan.md` — read it first if you haven't.\n"
            f"- Plan file path: `{plan_path}`\n\n"
            "## Important Rules\n"
            "- When the user asks for changes, update `plan.md` directly by writing to the file.\n"
            "- Keep the plan in proper Markdown format with clear headings and bullet points.\n"
            "- Focus solely on the technical plan — do not implement code or make other changes.\n\n"
            "## User Message\n"
        )

        return StageChatContext(
            session_id=session_id,
            cody_client=client,
            cody_session_id=task.plan_cody_session_id,
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
        allowed_roots = await _get_allowed_roots(db, task.project_id)
        client = await build_cody_client(db, str(task_dir), allowed_roots)

        async def on_todo_match(_file_path):
            if todo_path.exists():
                content = todo_path.read_text(encoding="utf-8")
                await sync_todos_from_file(db, entity_id, content)
                return content
            return None

        on_tool_result = make_file_write_detector("todo.json", "todo_updated", on_todo_match)

        return StageChatContext(
            session_id=session_id,
            cody_client=client,
            cody_session_id=task.plan_cody_session_id,
            on_tool_result=on_tool_result,
            language=lang,
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
        allowed_roots = await _get_allowed_roots(db, task.project_id)
        client = await build_cody_client(db, str(task_dir), allowed_roots)
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
        allowed_roots = await _get_allowed_roots(db, task.project_id)
        client = await build_cody_client(db, str(task_dir), allowed_roots)
        on_tool_result = make_file_write_detector(None, "code_updated")

        return StageChatContext(
            session_id=session_id,
            cody_client=client,
            cody_session_id=task.review_cody_session_id,
            on_tool_result=on_tool_result,
            language=lang,
        )

    else:
        raise ValueError(f"Unknown stage: {stage}")
