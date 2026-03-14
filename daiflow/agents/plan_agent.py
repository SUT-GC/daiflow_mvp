"""Plan agent: generates technical plan from task description."""

from pathlib import Path

from sqlalchemy import select

from daiflow.agents import AgentConfig, AgentContext, register_agent
from daiflow.prompts import PLAN_CHAT_PREFIX, PLAN_PROMPT_TEMPLATE
from daiflow.services.cody_service import append_path_boundary
from daiflow.session_runner import make_file_write_detector


class PlanAgent(AgentConfig):
    agent_type = "plan"
    chattable = True

    async def build_prompt(self, ctx: AgentContext) -> str:
        task = ctx.task
        task_dir = Path(ctx.task_dir)
        plan_path = task_dir / "plan.md"
        prompt = PLAN_PROMPT_TEMPLATE.format(
            description=task.description or "",
            prd=task.prd or "",
            tech_plan=task.tech_plan or "",
            plan_path=str(plan_path),
        )
        return append_path_boundary(prompt, ctx.task_dir, ctx.allowed_roots)

    def build_artifact_detector(self, ctx: AgentContext):
        plan_path = Path(ctx.task_dir) / "plan.md"

        async def on_plan_match(_file_path):
            if plan_path.exists():
                content = plan_path.read_text(encoding="utf-8")
                ctx.task.tech_plan = content
                await ctx.db.commit()
                return content
            return None

        return make_file_write_detector("plan.md", "plan_updated", on_plan_match)

    async def on_complete(self, ctx: AgentContext) -> None:
        plan_path = Path(ctx.task_dir) / "plan.md"
        if plan_path.exists():
            ctx.task.tech_plan = plan_path.read_text(encoding="utf-8")
            await ctx.db.commit()

    def chat_system_prefix(self, ctx: AgentContext) -> str | None:
        plan_path = Path(ctx.task_dir) / "plan.md"
        return PLAN_CHAT_PREFIX.format(plan_path=plan_path)


register_agent(PlanAgent())
