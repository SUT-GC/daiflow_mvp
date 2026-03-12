from daiflow.config import DEFAULT_LANGUAGE
from daiflow.models import Setting


async def get_language_setting(db) -> str:
    """Get the configured language from the settings table."""
    setting = await db.get(Setting, "language")
    return setting.value if setting and setting.value else DEFAULT_LANGUAGE
