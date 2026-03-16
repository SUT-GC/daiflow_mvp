import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.database import get_db
from daiflow.models import Setting
from daiflow.schemas import ConnectionTest, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = logging.getLogger(__name__)

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
    # Skip API key update if the value is a masked placeholder
    if "cody_api_key" in updates and "****" in updates["cody_api_key"]:
        del updates["cody_api_key"]

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


@router.post("/test")
async def test_connection(data: ConnectionTest, db: AsyncSession = Depends(get_db)):
    """Test AI model connection with the provided credentials (without saving)."""
    import tempfile

    from cody import Cody

    # If api_key is masked, resolve the real key from DB
    api_key = data.cody_api_key
    if "****" in api_key:
        result = await db.execute(
            select(Setting).where(Setting.key == "cody_api_key")
        )
        row = result.scalar_one_or_none()
        if not row or not row.value:
            raise HTTPException(status_code=400, detail="API key not found. Please enter a new key.")
        api_key = row.value

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = (
                Cody()
                .workdir(tmpdir)
                .model(data.cody_model)
                .base_url(data.cody_base_url)
                .api_key(api_key)
                .build()
            )
            async with client:
                await asyncio.wait_for(client.run("hi"), timeout=15)
        return {"ok": True, "model": data.cody_model}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=422, detail="Connection timed out. Please check the API URL and network.")
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "403" in msg or "auth" in msg or "unauthorized" in msg:
            detail = "Authentication failed. Please check the API key."
        elif "404" in msg or "not found" in msg or "model" in msg:
            detail = f"Model not found: {data.cody_model}. Please check the model name."
        elif "connect" in msg or "resolve" in msg or "refused" in msg:
            detail = "Cannot connect to the API URL. Please check the URL."
        else:
            detail = str(e)
        logger.warning("Connection test failed: %s", e)
        raise HTTPException(status_code=422, detail=detail)
