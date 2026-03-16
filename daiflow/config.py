import os
import re
from pathlib import Path

DAIFLOW_HOME = Path(os.environ.get("DAIFLOW_HOME", Path.home() / ".daiflow"))
DB_PATH = DAIFLOW_HOME / "daiflow.db"
SESSIONS_DIR = DAIFLOW_HOME / "sessions"
CODY_DB_PATH = DAIFLOW_HOME / "cody_sessions.db"
PROJECTS_DIR = DAIFLOW_HOME / "projects"
TASKS_DIR = DAIFLOW_HOME / "tasks"

DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

# Tool names that indicate file writes (used by on_tool_result detection)
FILE_WRITE_TOOLS = frozenset({"write_file", "edit_file", "create_file"})


def safe_filename(session_id: str) -> str:
    """Replace characters unsafe for filenames (colons, etc.)."""
    return re.sub(r'[:\\/*?"<>|]', '_', session_id)


def utc_iso(dt) -> str:
    """Format a datetime as ISO string with 'Z' suffix for UTC."""
    s = dt.isoformat()
    if s.endswith("+00:00"):
        return s[:-6] + "Z"
    return s + "Z"


LANGUAGE_INSTRUCTIONS = {
    "zh": "\n\n[IMPORTANT: 请用中文(简体)生成所有输出内容，包括文档、分析、计划和回复。]",
    "en": "\n\n[IMPORTANT: Please write ALL output in English.]",
}
DEFAULT_LANGUAGE = "en"


# Session log retention (days). Logs older than this are cleaned up on startup.
LOG_RETENTION_DAYS = int(os.environ.get("DAIFLOW_LOG_RETENTION_DAYS", "30"))


def init_daiflow_dir():
    """Create the ~/.daiflow/ directory structure if it doesn't exist."""
    for d in [DAIFLOW_HOME, SESSIONS_DIR, PROJECTS_DIR, TASKS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def cleanup_old_logs():
    """Delete .jsonl log files older than LOG_RETENTION_DAYS."""
    import time
    cutoff = time.time() - LOG_RETENTION_DAYS * 86400
    count = 0
    for f in SESSIONS_DIR.glob("*.jsonl"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                count += 1
        except OSError:
            pass
    return count
