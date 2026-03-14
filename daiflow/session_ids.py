"""Centralized session ID construction.

All DaiFlow business session IDs should be built through these helpers
to avoid string duplication and ensure consistency across modules.
"""


def task_plan(task_id: str) -> str:
    return f"task:{task_id}:plan"


def task_todo_split(task_id: str) -> str:
    return f"task:{task_id}:todo_split"


def task_todo_exec(task_id: str, todo_id: str) -> str:
    return f"task:{task_id}:todo:{todo_id}"


def task_review(task_id: str) -> str:
    return f"task:{task_id}:review"


def task_init_fetch(task_id: str) -> str:
    return f"task:{task_id}:init:fetch_code"


def task_init_skills(task_id: str) -> str:
    return f"task:{task_id}:init:sync_skills"


def task_init_bus(task_id: str) -> str:
    return f"task:init:{task_id}"


def project_init(project_id: str, knowledge_type: str) -> str:
    return f"init:{project_id}:{knowledge_type}"


def project_init_bus(project_id: str) -> str:
    return f"project:init:{project_id}"
