import json
import logging
import shutil
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.services.settings_service import get_language_setting
from daiflow.database import get_background_db
from daiflow.models import Project, ProjectRepo, Session, SessionStatus, Task, TaskStatus, Todo, TodoStatus
from daiflow.services.cody_service import append_path_boundary, build_cody_client
from daiflow.services.git_service import checkout_branch
from daiflow.services.project_service import _repo_dir_name
from daiflow.services.skill_service import get_project_dir, get_task_dir, sync_skills_to_task
from daiflow.session_runner import SessionRunner, make_file_write_detector

logger = logging.getLogger(__name__)

PLAN_PROMPT_TEMPLATE = (
    "You are a senior software architect. Your task is to generate a comprehensive technical plan.\n\n"
    "## Context\n"
    "1. First, read `project.md` in the current working directory for project knowledge.\n"
    "2. Then, read the relevant skill files in `.cody/skills/` for detailed module understanding.\n\n"
    "## Task Description\n{description}\n\n"
    "## PRD (Product Requirements)\n{prd}\n\n"
    "## Existing Technical Ideas\n{tech_plan}\n\n"
    "## Instructions\n"
    "Write a complete technical plan to `{plan_path}`. The plan MUST include:\n"
    "1. **Background & Goals** — What problem this solves\n"
    "2. **Backend Changes** — API endpoints, services, models to add/modify\n"
    "3. **Frontend Changes** — Components, pages, hooks to add/modify\n"
    "4. **Data Changes** — Database schema, migration needs\n"
    "5. **Impact Scope** — What existing features may be affected\n"
    "6. **Implementation Order** — Recommended sequence of development\n\n"
    "Use Markdown format with clear headings and bullet points."
)

TODO_PROMPT_TEMPLATE = (
    "You are a technical lead decomposing a plan into actionable tasks.\n\n"
    "## Context\n"
    "1. Read `project.md` for project knowledge.\n"
    "2. Read `plan.md` for the technical plan to decompose.\n\n"
    "## Instructions\n"
    "Based on the technical plan in `plan.md`, decompose the implementation into an ordered list of TODO items.\n"
    "Each TODO should be an independently executable unit of work (one API endpoint, one component, etc.).\n\n"
    "Write the result as a JSON array to `{todo_path}` with this exact format:\n"
    "```json\n"
    '[{{"seq": 1, "title": "Short title", "description": "Detailed description of what to implement and how"}}]\n'
    "```\n\n"
    "Guidelines:\n"
    "- Order todos by dependency (implement foundations first)\n"
    "- Each todo should be completable in a single coding session\n"
    "- Include both backend and frontend tasks\n"
    "- Be specific about files to create/modify"
)

TODO_EXECUTE_PROMPT_TEMPLATE = (
    "You are a senior developer implementing a specific TODO item.\n\n"
    "## Context\n"
    "1. Read `project.md` for project knowledge.\n"
    "2. Read `plan.md` for the overall technical plan.\n\n"
    "## TODO #{seq}: {title}\n"
    "{description}\n\n"
    "## Instructions\n"
    "Implement the changes described in this TODO item. Follow the technical plan in `plan.md`.\n"
    "- Write clean, production-quality code\n"
    "- Follow existing code conventions in the project\n"
    "- Include necessary imports and type annotations\n"
    "- Do NOT modify files outside the scope of this TODO"
)


def _copy_code_to_task(project_id: str, task_id: str, repos: list):
    """Copy cloned code from project/code/ to task/code/ for git-only repos.

    Only copies repos that have git_url but no local_path.
    Repos with local_path are used in-place (user's working directory).
    """
    project_dir = get_project_dir(project_id)
    task_dir = get_task_dir(task_id)

    for r in repos:
        if r.git_url and not r.local_path:
            repo_name = _repo_dir_name(r.git_url)
            src = project_dir / "code" / repo_name
            dst = task_dir / "code" / repo_name
            if src.exists():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                logger.info("Copied code %s -> %s", src, dst)


def _resolve_task_roots(task_id: str, repos: list) -> list[str]:
    """Resolve allowed_roots for a task.

    - Repos with local_path: use local_path directly (user's working directory)
    - Repos with git_url only: use task/code/{repo_name} (isolated copy)
    """
    task_dir = get_task_dir(task_id)
    roots = []
    for r in repos:
        if r.local_path:
            roots.append(r.local_path)
        elif r.git_url:
            roots.append(str(task_dir / "code" / _repo_dir_name(r.git_url)))
    return roots


async def init_task(task_id: str):
    """Initialize a task: sync skills, checkout branch, then generate plan.

    Uses an independent DB session for background execution.
    """
    try:
        async with get_background_db() as db:
            task = await db.get(Task, task_id)
            if not task:
                return

            project = await db.get(Project, task.project_id)
            if not project:
                return

            # Mark as initializing
            task.status = TaskStatus.INITIALIZING
            await db.commit()

            # Sync skills
            sync_skills_to_task(task.project_id, task_id)

            # Fetch repos and prepare code directories
            result = await db.execute(
                select(ProjectRepo).where(ProjectRepo.project_id == task.project_id)
            )
            repos = result.scalars().all()

            # Copy cloned code to task directory for git-only repos
            _copy_code_to_task(task.project_id, task_id, repos)

            # Checkout branch on all working directories
            if task.branch:
                for repo in repos:
                    if repo.local_path:
                        # User's local repo — checkout branch directly
                        try:
                            await checkout_branch(repo.local_path, task.branch)
                        except Exception as e:
                            logger.warning("Branch checkout for %s on %s: %s", task.branch, repo.local_path, e)
                    elif repo.git_url:
                        # Task's isolated copy — checkout branch there
                        task_repo_path = str(get_task_dir(task_id) / "code" / _repo_dir_name(repo.git_url))
                        try:
                            await checkout_branch(task_repo_path, task.branch)
                        except Exception as e:
                            logger.warning("Branch checkout for %s on %s: %s", task.branch, task_repo_path, e)

            # Update status to planning
            task.status = TaskStatus.PLANNING
            await db.commit()

        # Then generate plan
        await generate_plan(task_id)

    except Exception:
        logger.exception("init_task failed for task %s", task_id)
        # Reset to CREATED so user can retry
        try:
            async with get_background_db() as db:
                task = await db.get(Task, task_id)
                if task and task.status in (TaskStatus.INITIALIZING, TaskStatus.PLANNING):
                    task.status = TaskStatus.CREATED
                    await db.commit()
        except Exception:
            logger.exception("Failed to reset task %s status after init failure", task_id)


async def generate_plan(task_id: str):
    """Generate technical plan for a task.

    Uses an independent DB session for background execution.
    """
    async with get_background_db() as db:
        task = await db.get(Task, task_id)
        if not task:
            logger.debug("Task %s deleted before plan generation started", task_id)
            return

        task_dir = get_task_dir(task_id)
        plan_path = task_dir / "plan.md"

        # Resolve allowed roots (local_path or task/code/ copy)
        result = await db.execute(
            select(ProjectRepo).where(ProjectRepo.project_id == task.project_id)
        )
        repos = result.scalars().all()
        allowed_roots = _resolve_task_roots(task_id, repos)

        # Create session record (idempotent — skip if already exists)
        session_id = f"task:{task_id}:plan"
        existing_session = await db.get(Session, session_id)
        if not existing_session:
            session = Session(session_id=session_id, type="plan", ref_id=task_id)
            db.add(session)
            await db.commit()

        # Build prompt
        prompt = PLAN_PROMPT_TEMPLATE.format(
            description=task.description or "",
            prd=task.prd or "",
            tech_plan=task.tech_plan or "",
            plan_path=str(plan_path),
        )
        prompt = append_path_boundary(prompt, str(task_dir), allowed_roots)

        # Run Cody via SessionRunner
        lang = await get_language_setting(db)
        client = await build_cody_client(db, str(task_dir), allowed_roots)
        runner = SessionRunner(client)
        async with client:
            await runner.run(db, session_id, prompt, language=lang)

        # Re-check task existence before updating (task may have been deleted)
        task = await db.get(Task, task_id)
        if not task:
            logger.debug("Task %s deleted before plan write", task_id)
            return

        # Store cody_session_id for plan/todo session sharing
        if runner.last_cody_session_id:
            task.plan_cody_session_id = runner.last_cody_session_id

        # Read plan.md and store in task
        if plan_path.exists():
            task.tech_plan = plan_path.read_text(encoding="utf-8")
        await db.commit()


async def generate_todos(task_id: str):
    """Generate todo decomposition from the plan.

    Reuses the plan's Cody session for context continuity.
    Uses an independent DB session for background execution.
    """
    async with get_background_db() as db:
        task = await db.get(Task, task_id)
        if not task:
            logger.debug("Task %s deleted before todo generation started", task_id)
            return

        task_dir = get_task_dir(task_id)
        todo_path = task_dir / "todo.json"

        result = await db.execute(
            select(ProjectRepo).where(ProjectRepo.project_id == task.project_id)
        )
        repos = result.scalars().all()
        allowed_roots = _resolve_task_roots(task_id, repos)

        session_id = f"task:{task_id}:todo_split"
        existing_session = await db.get(Session, session_id)
        if not existing_session:
            session = Session(session_id=session_id, type="todo_split", ref_id=task_id)
            db.add(session)
        await db.commit()

        prompt = TODO_PROMPT_TEMPLATE.format(todo_path=str(todo_path))
        prompt = append_path_boundary(prompt, str(task_dir), allowed_roots)

        # Reuse plan's Cody session for context continuity
        lang = await get_language_setting(db)
        client = await build_cody_client(db, str(task_dir), allowed_roots)
        runner = SessionRunner(client)
        async with client:
            await runner.run(
                db, session_id, prompt,
                cody_session_id=task.plan_cody_session_id,
                language=lang,
            )

        # Re-check task existence before updating (task may have been deleted)
        task = await db.get(Task, task_id)
        if not task:
            logger.debug("Task %s deleted before todo write", task_id)
            return

        # Parse todo.json and insert todos into DB
        if todo_path.exists():
            try:
                todos_data = json.loads(todo_path.read_text(encoding="utf-8"))
                for item in todos_data:
                    todo = Todo(
                        task_id=task_id,
                        seq=item.get("seq", 0),
                        title=item.get("title", ""),
                        description=item.get("description", ""),
                    )
                    db.add(todo)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.error("Failed to parse todo.json for task %s: %s", task_id, e)
                # Still transition to TODO_READY so user can retry via chat
        else:
            logger.warning("todo.json not found for task %s after generation", task_id)

        task.status = TaskStatus.TODO_READY
        await db.commit()


async def sync_todos_from_file(db: AsyncSession, task_id: str, content: str):
    """Parse todo.json content and sync to database.

    Deletes existing todos and re-creates them from the file content.
    Used by todo/chat to keep DB in sync after AI edits todo.json.
    """
    try:
        todos_data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("Failed to parse todo.json content for task %s: %s", task_id, e)
        raise ValueError(f"Invalid todo.json format: {e}") from e

    # Delete only pending todos — preserve running/done/failed
    _preserve_statuses = (TodoStatus.RUNNING, TodoStatus.DONE, TodoStatus.FAILED)
    result = await db.execute(
        select(Todo).where(Todo.task_id == task_id)
    )
    existing = result.scalars().all()
    preserved = {t.seq: t for t in existing if t.status in _preserve_statuses}
    for t in existing:
        if t.status not in _preserve_statuses:
            await db.delete(t)

    # Insert new todos, skipping sequences that are preserved (running/done)
    for item in todos_data:
        seq = item.get("seq", 0)
        if seq in preserved:
            continue
        todo = Todo(
            task_id=task_id,
            seq=seq,
            title=item.get("title", ""),
            description=item.get("description", ""),
        )
        db.add(todo)
    await db.commit()


async def start_coding(task_id: str, db: AsyncSession):
    """Parse todo.json (if not already parsed), update task status to coding."""
    task = await db.get(Task, task_id)
    if not task:
        return

    # Check if todos already exist (from generate_todos)
    result = await db.execute(
        select(Todo).where(Todo.task_id == task_id)
    )
    existing_todos = result.scalars().all()

    if not existing_todos:
        # Fallback: parse todo.json if generate_todos didn't do it
        task_dir = get_task_dir(task_id)
        todo_path = task_dir / "todo.json"

        if todo_path.exists():
            try:
                todos_data = json.loads(todo_path.read_text(encoding="utf-8"))
                for item in todos_data:
                    todo = Todo(
                        task_id=task_id,
                        seq=item.get("seq", 0),
                        title=item.get("title", ""),
                        description=item.get("description", ""),
                    )
                    db.add(todo)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.error("Failed to parse todo.json for task %s: %s", task_id, e)

    task.status = TaskStatus.CODING
    await db.commit()


async def execute_todo(todo_id: str):
    """Execute a single todo item.

    Uses an independent DB session for background execution.
    """
    async with get_background_db() as db:
        todo = await db.get(Todo, todo_id)
        if not todo:
            return

        task = await db.get(Task, todo.task_id)
        if not task:
            return

        task_dir = get_task_dir(task.id)

        result = await db.execute(
            select(ProjectRepo).where(ProjectRepo.project_id == task.project_id)
        )
        repos = result.scalars().all()
        allowed_roots = _resolve_task_roots(task.id, repos)

        session_id = f"task:{task.id}:todo:{todo_id}"
        existing_session = await db.get(Session, session_id)
        if not existing_session:
            session = Session(session_id=session_id, type="todo_exec", ref_id=todo_id)
            db.add(session)
        todo.status = TodoStatus.RUNNING
        await db.commit()

        prompt = TODO_EXECUTE_PROMPT_TEMPLATE.format(
            seq=todo.seq,
            title=todo.title,
            description=todo.description,
        )
        prompt = append_path_boundary(prompt, str(task_dir), allowed_roots)

        lang = await get_language_setting(db)
        client = await build_cody_client(db, str(task_dir), allowed_roots)
        runner = SessionRunner(client)
        on_tool_result = make_file_write_detector(None, "code_updated")
        async with client:
            await runner.run(db, session_id, prompt, on_tool_result=on_tool_result, language=lang)

        # Update todo status
        if runner.last_cody_session_id:
            todo.cody_session_id = runner.last_cody_session_id

        session_rec = await db.get(Session, session_id)
        todo.status = TodoStatus.DONE if (session_rec and session_rec.status == SessionStatus.DONE) else TodoStatus.FAILED
        await db.commit()
