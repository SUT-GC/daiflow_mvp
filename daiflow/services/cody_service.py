from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import CODY_DB_PATH
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
):
    """Create an AsyncCodyClient from settings."""
    from cody import Cody

    settings = await get_cody_settings(db)
    model = settings.get("cody_model", "")
    base_url = settings.get("cody_base_url", "")
    api_key = settings.get("cody_api_key", "")

    if not all([model, base_url, api_key]):
        raise ValueError("AI model not configured. Please set cody_model, cody_base_url, and cody_api_key in Settings.")

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
    builder = builder.allowed_roots(roots)

    return builder.build()
