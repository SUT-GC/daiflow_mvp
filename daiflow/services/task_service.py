import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.services.settings_service import get_language_setting
from daiflow.database import get_background_db
from daiflow.models import Project, ProjectRepo, Session, SessionStatus, Task, TaskStatus, Todo, TodoStatus
from daiflow.services.cody_service import append_path_boundary, build_cody_client
from daiflow.services.git_service import checkout_branch, get_head_hash
from daiflow.services.project_service import repo_dir_name
from daiflow.services.skill_service import get_project_dir, get_task_dir, get_task_skills_dir, sync_skills_to_task
from daiflow.session_runner import SessionRunner, make_file_write_detector
from daiflow.workflow import TaskWorkflow, TodoWorkflow
from daiflow.ws_manager import ws_manager

logger = logging.getLogger(__name__)


async def fetch_project_repos(db: AsyncSession, project_id: str) -> list:
    """Fetch all ProjectRepo records for a project. Shared by services and routers."""
    result = await db.execute(
        select(ProjectRepo).where(ProjectRepo.project_id == project_id)
    )
    return result.scalars().all()


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
            repo_name = repo_dir_name(r.git_url)
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
            roots.append(str(task_dir / "code" / repo_dir_name(r.git_url)))
    return roots


async def _do_fetch_code(db: AsyncSession, session_id: str, *, task_id: str, project_id: str, branch: str | None):
    """Subtask: copy code repos and checkout branch."""
    from daiflow.session_runner import _append_log

    repos = await fetch_project_repos(db, project_id)
    _copy_code_to_task(project_id, task_id, repos)

    now_iso = lambda: datetime.now(timezone.utc).isoformat()
    await _append_log(session_id, {"type": "text_delta", "ts": now_iso(), "content": f"Copied {len(repos)} repo(s) to task directory\n"})

    if branch:
        for repo in repos:
            if repo.local_path:
                try:
                    await checkout_branch(repo.local_path, branch)
                    await _append_log(session_id, {"type": "text_delta", "ts": now_iso(), "content": f"✓ Checked out branch '{branch}' on {repo.local_path}\n"})
                except Exception as e:
                    logger.warning("Branch checkout for %s on %s: %s", branch, repo.local_path, e)
                    await _append_log(session_id, {"type": "text_delta", "ts": now_iso(), "content": f"⚠ Branch checkout failed on {repo.local_path}: {e}\n"})
            elif repo.git_url:
                task_repo_path = str(get_task_dir(task_id) / "code" / repo_dir_name(repo.git_url))
                try:
                    await checkout_branch(task_repo_path, branch)
                    await _append_log(session_id, {"type": "text_delta", "ts": now_iso(), "content": f"✓ Checked out branch '{branch}' on {repo_dir_name(repo.git_url)}\n"})
                except Exception as e:
                    logger.warning("Branch checkout for %s on %s: %s", branch, task_repo_path, e)
                    await _append_log(session_id, {"type": "text_delta", "ts": now_iso(), "content": f"⚠ Branch checkout failed on {repo_dir_name(repo.git_url)}: {e}\n"})


async def _do_sync_skills(db: AsyncSession, session_id: str, *, task_id: str, project_id: str):
    """Subtask: sync project skills to task directory."""
    from daiflow.session_runner import _append_log

    sync_skills_to_task(project_id, task_id)
    await _append_log(session_id, {"type": "text_delta", "ts": datetime.now(timezone.utc).isoformat(), "content": "✓ Synced project skills to task\n"})


async def init_task(task_id: str):
    """Initialize a task: fetch code + sync skills, then wait for user confirmation.

    Creates Session records for each subtask so the frontend can show progress.
    Does NOT auto-trigger plan generation — user must confirm via /confirm-init.
    """
    from daiflow.workflow.pipeline import run_simple_task

    init_bus = f"task:init:{task_id}"

    try:
        async with get_background_db() as db:
            task = await db.get(Task, task_id)
            if not task:
                return

            project = await db.get(Project, task.project_id)
            if not project:
                return

            # Transition: created → initializing
            wf = TaskWorkflow(task, db)
            await wf.initialize()

            # Create session records for init subtasks
            fetch_sid = f"task:{task_id}:init:fetch_code"
            skills_sid = f"task:{task_id}:init:sync_skills"
            for sid in (fetch_sid, skills_sid):
                existing = await db.get(Session, sid)
                if not existing:
                    db.add(Session(session_id=sid, type="task_init", ref_id=task_id, task_id=task_id, status=SessionStatus.WAITING))
            await db.commit()

        # Run subtasks sequentially
        await run_simple_task(
            fetch_sid, init_bus,
            lambda db, sid: _do_fetch_code(db, sid, task_id=task_id, project_id=task.project_id, branch=task.branch),
        )
        await run_simple_task(
            skills_sid, init_bus,
            lambda db, sid: _do_sync_skills(db, sid, task_id=task_id, project_id=task.project_id),
        )

        # Publish init done event
        await ws_manager.publish(init_bus, {"type": "done"})

    except Exception:
        logger.exception("init_task failed for task %s", task_id)
        # Notify frontend that init is done (with failures)
        await ws_manager.publish(init_bus, {"type": "done"})
        # Reset to CREATED so user can retry
        try:
            async with get_background_db() as db:
                task = await db.get(Task, task_id)
                if task and task.status == TaskStatus.INITIALIZING:
                    wf = TaskWorkflow(task, db)
                    await wf.reset()
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
        repos = await fetch_project_repos(db, task.project_id)
        allowed_roots = _resolve_task_roots(task_id, repos)

        # Create or reset session record
        session_id = f"task:{task_id}:plan"
        existing_session = await db.get(Session, session_id)
        if existing_session:
            existing_session.status = SessionStatus.WAITING
            existing_session.error = None
            existing_session.cody_session_id = None
            existing_session.started_at = None
            existing_session.finished_at = None
        else:
            db.add(Session(session_id=session_id, type="plan", ref_id=task_id, task_id=task_id))
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
        skill_dir = str(get_task_skills_dir(task_id))
        client = await build_cody_client(db, str(task_dir), allowed_roots, skill_dir=skill_dir)

        async def on_plan_match(_file_path):
            if plan_path.exists():
                content = plan_path.read_text(encoding="utf-8")
                task.tech_plan = content
                await db.commit()
                return content
            return None

        on_tool_result = make_file_write_detector("plan.md", "plan_updated", on_plan_match)

        runner = SessionRunner(client)
        async with client:
            await runner.run(db, session_id, prompt, language=lang, on_tool_result=on_tool_result)

        # Re-check task existence before updating (task may have been deleted)
        task = await db.get(Task, task_id)
        if not task:
            logger.debug("Task %s deleted before plan write", task_id)
            return

        # cody_session_id is stored in sessions table by SessionRunner

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

        repos = await fetch_project_repos(db, task.project_id)
        allowed_roots = _resolve_task_roots(task_id, repos)

        session_id = f"task:{task_id}:todo_split"
        existing_session = await db.get(Session, session_id)
        if existing_session:
            existing_session.status = SessionStatus.WAITING
            existing_session.error = None
            existing_session.cody_session_id = None
            existing_session.started_at = None
            existing_session.finished_at = None
        else:
            db.add(Session(session_id=session_id, type="todo_split", ref_id=task_id, task_id=task_id))
        await db.commit()

        prompt = TODO_PROMPT_TEMPLATE.format(todo_path=str(todo_path))
        prompt = append_path_boundary(prompt, str(task_dir), allowed_roots)

        # Reuse plan's Cody session for context continuity
        lang = await get_language_setting(db)
        skill_dir = str(get_task_skills_dir(task_id))
        client = await build_cody_client(db, str(task_dir), allowed_roots, skill_dir=skill_dir)

        # Look up plan's cody_session_id via task_id FK
        result = await db.execute(
            select(Session.cody_session_id).where(
                Session.task_id == task_id, Session.type == "plan",
            )
        )
        plan_cody_sid = result.scalar()

        async def on_todo_match(_file_path):
            if todo_path.exists():
                return todo_path.read_text(encoding="utf-8")
            return None

        on_tool_result = make_file_write_detector("todo.json", "todo_updated", on_todo_match)

        runner = SessionRunner(client)
        async with client:
            await runner.run(
                db, session_id, prompt,
                cody_session_id=plan_cody_sid,
                language=lang,
                on_tool_result=on_tool_result,
            )

        # Re-check task existence before updating (task may have been deleted)
        task = await db.get(Task, task_id)
        if not task:
            logger.debug("Task %s deleted before todo write", task_id)
            return

        # Parse todo.json and insert todos into DB
        if todo_path.exists():
            try:
                _insert_todos(db, task_id, _parse_todos_json(todo_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.error("Failed to parse todo.json for task %s: %s", task_id, e)
                # Still transition to TODO_READY so user can retry via chat
        else:
            logger.warning("todo.json not found for task %s after generation", task_id)

        # Transition: plan_locked → todo_ready
        wf = TaskWorkflow(task, db)
        await wf.todos_ready()
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
    _preserve_statuses = (TodoStatus.RUNNING, TodoStatus.DONE, TodoStatus.FAILED, TodoStatus.SKIPPED)
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


def _parse_todos_json(content: str) -> list[dict]:
    """Parse todo.json content into a list of todo dicts. Raises on invalid JSON."""
    data = json.loads(content)
    return [
        {"seq": item.get("seq", 0), "title": item.get("title", ""), "description": item.get("description", "")}
        for item in data
    ]


def _insert_todos(db: AsyncSession, task_id: str, todos_data: list[dict]):
    """Add parsed todo items to the DB session (does not commit)."""
    for item in todos_data:
        db.add(Todo(task_id=task_id, seq=item["seq"], title=item["title"], description=item["description"]))


async def start_coding(task_id: str, db: AsyncSession):
    """Parse todo.json (if not already parsed), update task status to coding.

    Status transition is handled by TaskWorkflow in the router layer.
    This function only ensures todos are loaded into DB.
    """
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
                _insert_todos(db, task_id, _parse_todos_json(todo_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.error("Failed to parse todo.json for task %s: %s", task_id, e)

    await db.commit()


async def execute_todo(todo_id: str):
    """Execute a single todo item.

    The router has already transitioned the todo to RUNNING.
    This function runs Cody and transitions to done/failed.
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

        repos = await fetch_project_repos(db, task.project_id)
        allowed_roots = _resolve_task_roots(task.id, repos)

        session_id = f"task:{task.id}:todo:{todo_id}"
        existing_session = await db.get(Session, session_id)
        if not existing_session:
            session = Session(session_id=session_id, type="todo_exec", ref_id=todo_id, task_id=task.id)
            db.add(session)

        # Record HEAD hash of each repo before execution
        head_before: dict[str, str] = {}
        for root in allowed_roots:
            try:
                head_before[root] = await get_head_hash(root)
            except Exception:
                pass
        todo.commit_before = json.dumps(head_before)
        await db.commit()

        prompt = TODO_EXECUTE_PROMPT_TEMPLATE.format(
            seq=todo.seq,
            title=todo.title,
            description=todo.description,
        )
        prompt = append_path_boundary(prompt, str(task_dir), allowed_roots)

        lang = await get_language_setting(db)
        skill_dir = str(get_task_skills_dir(task.id))
        client = await build_cody_client(db, str(task_dir), allowed_roots, skill_dir=skill_dir)
        runner = SessionRunner(client)
        on_tool_result = make_file_write_detector(None, "code_updated")
        async with client:
            await runner.run(db, session_id, prompt, on_tool_result=on_tool_result, language=lang)

        # Record HEAD hash of each repo after execution
        head_after: dict[str, str] = {}
        for root in allowed_roots:
            try:
                head_after[root] = await get_head_hash(root)
            except Exception:
                pass
        todo.commit_after = json.dumps(head_after)

        # Update todo status
        if runner.last_cody_session_id:
            todo.cody_session_id = runner.last_cody_session_id

        # Transition: running → done or running → failed
        session_rec = await db.get(Session, session_id)
        succeeded = session_rec and session_rec.status == SessionStatus.DONE
        todo_wf = TodoWorkflow(todo, db)
        if succeeded:
            await todo_wf.complete()
        else:
            await todo_wf.fail()
        await db.commit()
