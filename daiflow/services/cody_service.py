from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import CODY_DB_PATH
from daiflow.exceptions import ConfigurationError
from daiflow.models import Setting


async def get_cody_settings(db: AsyncSession) -> dict:
    """Fetch cody_model, cody_base_url, cody_api_key from settings table."""
    result = await db.execute(
        select(Setting).where(Setting.key.in_(["cody_model", "cody_base_url", "cody_api_key"]))
    )
    settings = {s.key: s.value for s in result.scalars().all()}
    return settings


async def build_cody_client(
    db: AsyncSession,
    workdir: str,
    allowed_roots: list[str] | None = None,
    skill_dir: str | None = None,
):
    """Create an AsyncCodyClient from settings."""
    from cody import Cody

    settings = await get_cody_settings(db)
    model = settings.get("cody_model", "")
    base_url = settings.get("cody_base_url", "")
    api_key = settings.get("cody_api_key", "")

    if not all([model, base_url, api_key]):
        raise ConfigurationError("AI model not configured. Please set cody_model, cody_base_url, and cody_api_key in Settings.")

    builder = (
        Cody()
        .workdir(workdir)
        .model(model)
        .base_url(base_url)
        .api_key(api_key)
        .db_path(str(CODY_DB_PATH))
    )

    roots = [workdir]
    if allowed_roots:
        roots.extend(allowed_roots)
    builder = builder.allowed_roots(roots).strict_read_boundary(True)

    if skill_dir:
        if hasattr(builder, "skill_dir"):
            builder = builder.skill_dir(skill_dir)
        else:
            import logging
            logging.getLogger(__name__).warning(
                "Cody SDK does not support skill_dir() — upgrade to cody-ai>=1.10.2 for explicit skill directory support"
            )

    return builder.build()


async def build_task_cody_client(db: AsyncSession, task_id: str, project_id: str):
    """Build a Cody client configured for a task context.

    Convenience wrapper that resolves task directory, allowed roots,
    and skill directory — the common pattern used by task_service,
    chat_service, and review_service.
    """
    from daiflow.services.skill_service import get_task_dir, get_task_skills_dir
    from daiflow.services.task_service import get_task_context

    task_dir = get_task_dir(task_id)
    _, allowed_roots = await get_task_context(db, task_id, project_id)
    skill_dir = str(get_task_skills_dir(task_id))
    return await build_cody_client(db, str(task_dir), allowed_roots, skill_dir=skill_dir)


def append_path_boundary(prompt: str, workdir: str, allowed_roots: list[str]) -> str:
    """Append path boundary instructions to a prompt.

    Soft restriction via prompt to prevent Cody from accessing files
    outside allowed_roots (complements strict_read_boundary in SDK).
    """
    all_roots = [workdir]
    for r in (allowed_roots or []):
        if r != workdir:
            all_roots.append(r)
    roots_list = "\n".join(f"- {r}" for r in all_roots)
    return prompt + (
        "\n\n## IMPORTANT: Path Boundary\n"
        "You MUST ONLY access files within the following directories:\n"
        f"{roots_list}\n"
        "Do NOT explore parent directories, sibling directories, or any path outside the listed roots. "
        "Do NOT use exec_command (ls, find, cat, etc.) to access files outside these directories."
    )
