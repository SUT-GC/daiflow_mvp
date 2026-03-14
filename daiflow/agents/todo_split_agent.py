"""Todo-split agent: decomposes technical plan into actionable todos."""

from pathlib import Path

from sqlalchemy import select

from daiflow.agents import AgentConfig, AgentContext, register_agent
from daiflow.models import Session
from daiflow.prompts import TODO_CHAT_PREFIX, TODO_PROMPT_TEMPLATE
from daiflow.services.cody_service import append_path_boundary
from daiflow.session_runner import make_file_write_detector


class TodoSplitAgent(AgentConfig):
    agent_type = "todo_split"
    chattable = True

    async def build_prompt(self, ctx: AgentContext) -> str:
        task_dir = Path(ctx.task_dir)
        todo_path = task_dir / "todo.json"
        prompt = TODO_PROMPT_TEMPLATE.format(todo_path=str(todo_path))
        return append_path_boundary(prompt, ctx.task_dir, ctx.allowed_roots)

    async def resolve_cody_session_id(self, ctx: AgentContext) -> str | None:
        # Reuse plan's cody_session_id for context continuity
        result = await ctx.db.execute(
            select(Session.cody_session_id).where(
                Session.task_id == ctx.entity_id,
                Session.type == "plan",
            )
        )
        return result.scalar()

    def build_artifact_detector(self, ctx: AgentContext):
        todo_path = Path(ctx.task_dir) / "todo.json"

        async def on_todo_match(_file_path):
            if todo_path.exists():
                content = todo_path.read_text(encoding="utf-8")
                # In chat mode, sync_todos_from_file is called;
                # in initial generation, raw content is returned and caller handles parsing.
                # Unify: always call sync when available.
                from daiflow.services.task_service import sync_todos_from_file
                await sync_todos_from_file(ctx.db, ctx.entity_id, content)
                return content
            return None

        return make_file_write_detector("todo.json", "todo_updated", on_todo_match)

    async def on_complete(self, ctx: AgentContext) -> None:
        import logging
        from daiflow.services.task_service import sync_todos_from_file
        from daiflow.workflow import TaskWorkflow

        logger = logging.getLogger(__name__)
        task = ctx.task

        # Re-fetch task (may have been deleted during execution)
        task = await ctx.db.get(type(task), task.id)
        if not task:
            return

        # Final sync of todos from todo.json (idempotent: delete-then-insert)
        todo_path = Path(ctx.task_dir) / "todo.json"
        if todo_path.exists():
            try:
                content = todo_path.read_text(encoding="utf-8")
                await sync_todos_from_file(ctx.db, ctx.entity_id, content)
            except Exception as e:
                logger.error("Failed to sync todo.json for task %s: %s", task.id, e)
        else:
            logger.warning("todo.json not found for task %s after generation", task.id)

        # Transition: plan_locked → todo_ready
        wf = TaskWorkflow(task, ctx.db)
        await wf.todos_ready()
        await ctx.db.commit()

    def chat_system_prefix(self, ctx: AgentContext) -> str | None:
        todo_path = Path(ctx.task_dir) / "todo.json"
        return TODO_CHAT_PREFIX.format(todo_path=todo_path)


register_agent(TodoSplitAgent())
