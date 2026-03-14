"""Unified agent executor.

Replaces the repeated pattern in task_service (generate_plan, generate_todos,
execute_todo) with a single entry point that delegates to AgentConfig.
"""

import logging
import traceback

from sqlalchemy import update

from daiflow.agents import AgentConfig, AgentContext, get_agent_config
from daiflow.models import Session, SessionStatus, Task, Todo
from daiflow.services.cody_service import build_task_cody_client
from daiflow.services.settings_service import get_language_setting
from daiflow.services.skill_service import get_task_dir
from daiflow.services.task_service import get_task_context
from daiflow.session_runner import SessionRunner

logger = logging.getLogger(__name__)


async def _reset_or_create_session(db, session_id: str, session_type: str, ref_id: str, task_id: str):
    """Create a new Session record or reset an existing one to WAITING."""
    existing = await db.get(Session, session_id)
    if existing:
        existing.status = SessionStatus.WAITING
        existing.error = None
        existing.cody_session_id = None
        existing.started_at = None
        existing.finished_at = None
    else:
        db.add(Session(session_id=session_id, type=session_type, ref_id=ref_id, task_id=task_id))
    await db.commit()


async def _build_context(
    db,
    entity_id: str,
    agent_type: str,
    task_id: str | None = None,
) -> AgentContext:
    """Build AgentContext by loading task/todo from DB and resolving paths."""
    ctx = AgentContext(db=db, session_id="", entity_id=entity_id)

    if agent_type == "todo_exec":
        # entity_id is todo_id
        todo = await db.get(Todo, entity_id)
        if not todo:
            raise ValueError(f"Todo {entity_id} not found")
        task = await db.get(Task, todo.task_id)
        if not task:
            raise ValueError(f"Task {todo.task_id} not found")
        ctx.todo = todo
        ctx.task = task
        ctx.project_id = task.project_id
        ctx.task_dir = str(get_task_dir(task.id))
        _, ctx.allowed_roots = await get_task_context(db, task.id, task.project_id)
    else:
        # entity_id is task_id
        effective_task_id = task_id or entity_id
        task = await db.get(Task, effective_task_id)
        if not task:
            raise ValueError(f"Task {effective_task_id} not found")
        ctx.task = task
        ctx.project_id = task.project_id
        ctx.task_dir = str(get_task_dir(task.id))
        _, ctx.allowed_roots = await get_task_context(db, task.id, task.project_id)

    return ctx


async def run_agent(
    db,
    agent_type: str,
    entity_id: str,
    session_id: str,
    task_id: str | None = None,
    extra_channels: list[str] | None = None,
) -> None:
    """Execute an agent with full lifecycle management.

    This is the unified replacement for generate_plan(), generate_todos(),
    and execute_todo() in task_service.

    Args:
        db: AsyncSession (must be a background session, not request-scoped)
        agent_type: Registered agent type (e.g. "plan", "todo_split", "todo_exec")
        entity_id: Business entity ID (task_id or todo_id)
        session_id: DaiFlow session ID
        task_id: Explicit task_id (needed when entity_id is a todo_id)
        extra_channels: Additional WS channels to publish status to
    """
    config = get_agent_config(agent_type)

    try:
        # 1. Build context
        ctx = await _build_context(db, entity_id, agent_type, task_id)
        ctx.session_id = session_id

        # 2. Create/reset session record
        await _reset_or_create_session(db, session_id, agent_type, ctx.task.id if agent_type == "todo_exec" else entity_id, ctx.task.id)

        # 3. Get language setting
        lang = await get_language_setting(db)

        # 4. Build Cody client
        client = await build_task_cody_client(db, ctx.task.id, ctx.project_id)

        # 5. Build prompt
        prompt = await config.build_prompt(ctx)

        # 6. Resolve cody_session_id for context continuity
        cody_session_id = await config.resolve_cody_session_id(ctx)

        # 7. Build artifact detector
        on_tool_result = config.build_artifact_detector(ctx)

        # 8. Execute via SessionRunner
        runner = SessionRunner(client)
        async with client:
            await runner.run(
                db, session_id, prompt,
                extra_channels=extra_channels,
                on_tool_result=on_tool_result,
                cody_session_id=cody_session_id,
                language=lang,
            )

        # 9. Post-execution hook
        await config.on_complete(ctx)

    except Exception:
        logger.exception("Agent %s execution failed for entity %s", agent_type, entity_id)
        # Mark session as failed if SessionRunner hasn't already
        try:
            session = await db.get(Session, session_id)
            if session and session.status != SessionStatus.FAILED:
                error_msg = traceback.format_exc()
                await db.execute(
                    update(Session)
                    .where(Session.session_id == session_id)
                    .values(status=SessionStatus.FAILED, error=error_msg)
                )
                await db.commit()
        except Exception:
            logger.exception("Failed to mark session %s as failed", session_id)


async def prepare_chat(
    db,
    agent_type: str,
    entity_id: str,
    session_id: str,
):
    """Build chat context for a stage. Replaces chat_service.prepare_stage_chat().

    Args:
        db: AsyncSession
        agent_type: One of "plan", "todo", "todo_exec", "review"
        entity_id: task_id (or todo_id for todo_exec)
        session_id: DaiFlow session ID

    Returns:
        StageChatContext with all fields populated.
    """
    from daiflow.services.chat_service import StageChatContext

    config = get_agent_config(agent_type)

    # Build context
    ctx = await _build_context(db, entity_id, agent_type)
    ctx.session_id = session_id

    # Build Cody client
    client = await build_task_cody_client(db, ctx.task.id, ctx.project_id)

    # Resolve cody_session_id
    cody_session_id = await config.resolve_cody_session_id(ctx)

    # For todo_exec, use the stored cody_session_id from the todo record
    if agent_type == "todo_exec" and ctx.todo:
        cody_session_id = ctx.todo.cody_session_id

    # Build artifact detector
    on_tool_result = config.build_artifact_detector(ctx)

    # Get language
    lang = await get_language_setting(db)

    # System prefix
    system_prefix = config.chat_system_prefix(ctx)

    return StageChatContext(
        session_id=session_id,
        cody_client=client,
        cody_session_id=cody_session_id,
        on_tool_result=on_tool_result,
        language=lang,
        system_prefix=system_prefix,
    )
