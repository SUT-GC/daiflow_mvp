from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.database import get_db
from daiflow.models import Setting
from daiflow.schemas import SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

SETTING_KEYS = ["cody_model", "cody_base_url", "cody_api_key", "theme", "language"]


@router.get("")
async def get_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Setting))
    settings = {s.key: s.value for s in result.scalars().all()}
    # Mask API key - never return the raw key
    if "cody_api_key" in settings and settings["cody_api_key"]:
        key = settings["cody_api_key"]
        if len(key) > 8:
            settings["cody_api_key"] = key[:4] + "*" * (len(key) - 8) + key[-4:]
        else:
            settings["cody_api_key"] = "****"
    return settings


@router.put("")
async def update_settings(data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    updates = data.model_dump(exclude_none=True)
    # Validate required AI fields are not empty
    required_keys = {"cody_model", "cody_base_url", "cody_api_key"}
    for key in required_keys:
        if key in updates and not updates[key].strip():
            raise HTTPException(
                status_code=400,
                detail=f"Field '{key}' cannot be empty",
            )
    for key, value in updates.items():
        existing = await db.get(Setting, key)
        if existing:
            existing.value = value
        else:
            db.add(Setting(key=key, value=value))
    await db.commit()
    return {"ok": True}


@router.get("/check")
async def check_settings(db: AsyncSession = Depends(get_db)):
    """Check if AI model is configured. Returns {configured: bool}."""
    result = await db.execute(
        select(Setting).where(Setting.key.in_(["cody_model", "cody_base_url", "cody_api_key"]))
    )
    settings = {s.key: s.value for s in result.scalars().all()}
    configured = all(
        settings.get(k) for k in ["cody_model", "cody_base_url", "cody_api_key"]
    )
    return {"configured": configured, "model": settings.get("cody_model", "")}
