"""Plan agent: generates technical plan from task description."""

import base64
import json
import logging
from pathlib import Path

from sqlalchemy import select

from daiflow.agents import AgentConfig, AgentContext, register_agent
from daiflow.config import TASKS_DIR
from daiflow.prompts import PLAN_CHAT_PREFIX, PLAN_PROMPT_TEMPLATE
from daiflow.services.cody_service import append_path_boundary
from daiflow.session_runner import make_file_write_detector

logger = logging.getLogger(__name__)

# Media type mapping for image extensions
_EXT_TO_MEDIA = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class PlanAgent(AgentConfig):
    agent_type = "plan"
    chattable = True

    async def build_prompt(self, ctx: AgentContext):
        task = ctx.task
        task_dir = Path(ctx.task_dir)
        plan_path = task_dir / "plan.md"
        text = PLAN_PROMPT_TEMPLATE.format(
            description=task.description or "",
            prd=task.prd or "",
            tech_plan=task.tech_plan or "",
            plan_path=str(plan_path),
        )
        text = append_path_boundary(text, ctx.task_dir, ctx.allowed_roots)

        # Check for PRD images
        image_filenames = json.loads(task.prd_images or "[]")
        if not image_filenames:
            return text

        # Build MultimodalPrompt with images
        try:
            from cody.core.prompt import MultimodalPrompt, ImageData
        except ImportError:
            logger.warning("cody.core.prompt not available, falling back to text-only prompt")
            return text

        images = []
        img_dir = TASKS_DIR / task.id / "prd_images"
        for filename in image_filenames:
            img_path = img_dir / filename
            if not img_path.exists():
                continue
            data = base64.b64encode(img_path.read_bytes()).decode()
            ext = img_path.suffix.lower()
            media_type = _EXT_TO_MEDIA.get(ext, "image/png")
            images.append(ImageData(data=data, media_type=media_type, filename=filename))

        if not images:
            return text

        return MultimodalPrompt(text=text, images=images)

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
        from daiflow.models import Task
        # Re-fetch task in case it was deleted during execution
        task = await ctx.db.get(Task, ctx.task.id)
        if not task:
            return
        plan_path = Path(ctx.task_dir) / "plan.md"
        if plan_path.exists():
            task.tech_plan = plan_path.read_text(encoding="utf-8")
            await ctx.db.commit()

    def chat_system_prefix(self, ctx: AgentContext) -> str | None:
        plan_path = Path(ctx.task_dir) / "plan.md"
        return PLAN_CHAT_PREFIX.format(plan_path=plan_path)


register_agent(PlanAgent())
