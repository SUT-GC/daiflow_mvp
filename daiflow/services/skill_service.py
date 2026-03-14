import json
import shutil
import tempfile
from pathlib import Path

from daiflow.config import PROJECTS_DIR, TASKS_DIR


def get_project_skills_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id / "skills"


def get_task_skills_dir(task_id: str) -> Path:
    return TASKS_DIR / task_id / ".cody" / "skills"


def sync_skills_to_task(project_id: str, task_id: str):
    """Copy project skills to task .cody/skills/ directory."""
    src = get_project_skills_dir(project_id)
    dst = get_task_skills_dir(task_id)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if src.exists():
        # Atomic swap: copy to temp dir first, then rename
        tmp_dst = Path(tempfile.mkdtemp(dir=dst.parent))
        try:
            shutil.copytree(src, tmp_dst / "skills")
            if dst.exists():
                shutil.rmtree(dst)
            (tmp_dst / "skills").rename(dst)
        finally:
            if tmp_dst.exists():
                shutil.rmtree(tmp_dst, ignore_errors=True)
    else:
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True, exist_ok=True)

    # Also copy project.md if it exists
    project_md_src = PROJECTS_DIR / project_id / "project.md"
    project_md_dst = TASKS_DIR / task_id / "project.md"
    if project_md_src.exists():
        shutil.copy2(project_md_src, project_md_dst)


def get_task_dir(task_id: str) -> Path:
    d = TASKS_DIR / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_project_dir(project_id: str) -> Path:
    d = PROJECTS_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d
