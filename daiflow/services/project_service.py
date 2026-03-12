import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from daiflow.config import get_language_setting
from daiflow.database import get_background_db
from daiflow.models import ProjectRepo, Session, SessionStatus
from daiflow.services.cody_service import build_cody_client
from daiflow.services.skill_service import get_project_dir
from daiflow.session_runner import SessionRunner
from daiflow.ws_manager import ws_manager

logger = logging.getLogger(__name__)

# Knowledge types per layer
LAYER_2_TYPES = {
    "frontend": ["frontend_structure", "business_flow", "component_usage"],
    "backend": ["backend_structure"],
    "custom": ["backend_structure", "business_flow"],
}
LAYER_3_TYPES = ["module_overview", "api_interaction", "data_entity", "dependencies"]

# Prompt templates for each knowledge type
KNOWLEDGE_PROMPTS = {
    "frontend_structure": (
        "Please read project.md first for context. "
        "Analyze the frontend repository and generate a comprehensive skill document about the frontend directory structure. "
        "Cover: directory organization, module responsibilities, naming conventions, and architectural patterns. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: frontend_structure, description: Frontend directory structure analysis, user-invocable: false)."
    ),
    "backend_structure": (
        "Please read project.md first for context. "
        "Analyze the backend repository and generate a comprehensive skill document about the backend directory structure. "
        "Cover: directory organization, module responsibilities, naming conventions, and architectural patterns. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: backend_structure, description: Backend directory structure analysis, user-invocable: false)."
    ),
    "business_flow": (
        "Please read project.md first for context. "
        "Analyze the repository and generate a comprehensive skill document about business flows. "
        "Cover: key user flows per module, state transitions, and data flow patterns. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: business_flow, description: Business flow analysis per module, user-invocable: false)."
    ),
    "component_usage": (
        "Please read project.md first for context. "
        "Analyze the frontend repository and generate a comprehensive skill document about component usage. "
        "Cover: shared components, usage patterns, props interfaces, and composition patterns. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: component_usage, description: Frontend component structure and reuse patterns, user-invocable: false)."
    ),
    "module_overview": (
        "Please read project.md first for context. "
        "Analyze all repositories and generate a comprehensive skill document about module breakdown. "
        "Cover: all modules across frontend and backend, their responsibilities and boundaries. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: module_overview, description: Module breakdown and descriptions, user-invocable: false)."
    ),
    "api_interaction": (
        "Please read project.md first for context. "
        "Analyze all repositories and generate a comprehensive skill document about API interactions. "
        "Cover: API endpoints, request/response patterns, frontend-backend integration points. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: api_interaction, description: Frontend-backend API interaction relationships, user-invocable: false)."
    ),
    "data_entity": (
        "Please read project.md first for context. "
        "Analyze all repositories and generate a comprehensive skill document about data entities. "
        "Cover: data models, database schemas, data flow patterns, and entity relationships. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: data_entity, description: Data entities and data flows per module, user-invocable: false)."
    ),
    "dependencies": (
        "Please read project.md first for context. "
        "Analyze all repositories and generate a comprehensive skill document about dependencies. "
        "Cover: external dependencies, internal module dependencies, version requirements. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: dependencies, description: Downstream dependencies per module, user-invocable: false)."
    ),
}

PROJECT_MD_PROMPT = (
    "Read all SKILL.md files in the skills/ directory. "
    "Generate a project.md index file that summarizes all skills and serves as a knowledge base entry point. "
    "Write the output to {output_path}/project.md."
)


def compute_init_sessions(project_id: str, repos: list) -> list[dict]:
    """Compute all session records needed for project init."""
    sessions = []

    # Layer 1: skill_fetch (placeholder for now)
    sessions.append({
        "session_id": f"init:{project_id}:skill_fetch",
        "type": "init",
        "ref_id": project_id,
        "layer": 1,
    })

    # Layer 2: per-repo knowledge
    for repo in repos:
        repo_type = repo.repo_type
        types = LAYER_2_TYPES.get(repo_type, [])
        for kt in types:
            sessions.append({
                "session_id": f"init:{project_id}:{kt}",
                "type": "init",
                "ref_id": project_id,
                "layer": 2,
            })

    # Layer 3: cross-repo knowledge
    for kt in LAYER_3_TYPES:
        sessions.append({
            "session_id": f"init:{project_id}:{kt}",
            "type": "init",
            "ref_id": project_id,
            "layer": 3,
        })

    # Layer 4: project.md
    sessions.append({
        "session_id": f"init:{project_id}:project_md",
        "type": "init",
        "ref_id": project_id,
        "layer": 4,
    })

    return sessions


async def run_init(project_id: str):
    """Execute the 4-layer project knowledge generation pipeline.

    Uses an independent DB session for background execution.
    """
    async with get_background_db() as db:
        project_dir = get_project_dir(project_id)
        project_bus = f"project:init:{project_id}"

        # Fetch repos
        result = await db.execute(
            select(ProjectRepo).where(ProjectRepo.project_id == project_id)
        )
        repos = result.scalars().all()
        allowed_roots = [r.local_path for r in repos if r.local_path]

        # Layer 1: Skill fetch (placeholder - mark done)
        sid = f"init:{project_id}:skill_fetch"
        await db.execute(
            update(Session).where(Session.session_id == sid).values(
                status=SessionStatus.DONE, finished_at=datetime.now(timezone.utc)
            )
        )
        await db.commit()
        await ws_manager.publish(project_bus, {
            "type": "session_status", "session_id": sid, "status": SessionStatus.DONE, "layer": 1,
        })

        # Layer 2: Per-repo knowledge (concurrent)
        layer2_sessions = await db.execute(
            select(Session).where(Session.ref_id == project_id, Session.layer == 2)
        )
        layer2 = layer2_sessions.scalars().all()

        lang = await get_language_setting(db)

        async def run_knowledge(session_record: Session, knowledge_type: str):
            async with get_background_db() as task_db:
                skills_dir = project_dir / "skills" / knowledge_type
                skills_dir.mkdir(parents=True, exist_ok=True)
                prompt = KNOWLEDGE_PROMPTS[knowledge_type].format(output_path=str(skills_dir))
                client = await build_cody_client(task_db, str(project_dir), allowed_roots)
                runner = SessionRunner(client)
                async with client:
                    await runner.run(task_db, session_record.session_id, prompt, extra_channels=[project_bus], language=lang)

        async def run_layer(layer_sessions, layer_num: int) -> bool:
            """Run all tasks in a layer concurrently. Returns True if all succeeded."""
            layer_tasks = []
            session_ids = []
            for s in layer_sessions:
                kt = s.session_id.split(":")[-1]
                if kt in KNOWLEDGE_PROMPTS:
                    layer_tasks.append(run_knowledge(s, kt))
                    session_ids.append(s.session_id)
            if not layer_tasks:
                return True

            results = await asyncio.gather(*layer_tasks, return_exceptions=True)
            has_failure = False
            for s_id, r in zip(session_ids, results):
                if isinstance(r, Exception):
                    has_failure = True
                    logger.error("Layer %d task %s failed: %s", layer_num, s_id, r)
            return not has_failure

        layer2_ok = await run_layer(layer2, 2)

        if not layer2_ok:
            logger.warning("Layer 2 had failures, continuing to Layer 3...")

        # Layer 3: Cross-repo knowledge (concurrent)
        layer3_sessions = await db.execute(
            select(Session).where(Session.ref_id == project_id, Session.layer == 3)
        )
        layer3 = layer3_sessions.scalars().all()

        layer3_ok = await run_layer(layer3, 3)

        if not layer3_ok:
            logger.warning("Layer 3 had failures, continuing to Layer 4...")

        # Layer 4: Generate project.md (uses independent DB session to avoid stale connection)
        sid = f"init:{project_id}:project_md"
        try:
            async with get_background_db() as layer4_db:
                prompt = PROJECT_MD_PROMPT.format(output_path=str(project_dir))
                client = await build_cody_client(layer4_db, str(project_dir), allowed_roots)
                runner = SessionRunner(client)
                async with client:
                    await runner.run(layer4_db, sid, prompt, extra_channels=[project_bus], language=lang)
        except Exception as e:
            logger.error("Layer 4 project.md generation failed: %s", e)

        # Send final done event on project bus
        await ws_manager.publish(project_bus, {"type": "done"})


async def run_init_retry(project_id: str, failed_session_ids: list[str], from_layer: int):
    """Re-run failed sessions in from_layer + all sessions in subsequent layers."""
    async with get_background_db() as db:
        project_dir = get_project_dir(project_id)
        project_bus = f"project:init:{project_id}"

        # Fetch repos for allowed_roots
        result = await db.execute(
            select(ProjectRepo).where(ProjectRepo.project_id == project_id)
        )
        repos = result.scalars().all()
        allowed_roots = [r.local_path for r in repos if r.local_path]

        lang = await get_language_setting(db)

        async def run_knowledge(session_record: Session, knowledge_type: str):
            async with get_background_db() as task_db:
                skills_dir = project_dir / "skills" / knowledge_type
                skills_dir.mkdir(parents=True, exist_ok=True)
                prompt = KNOWLEDGE_PROMPTS[knowledge_type].format(output_path=str(skills_dir))
                client = await build_cody_client(task_db, str(project_dir), allowed_roots)
                runner = SessionRunner(client)
                async with client:
                    await runner.run(task_db, session_record.session_id, prompt, extra_channels=[project_bus], language=lang)

        async def run_layer(layer_sessions, layer_num: int) -> bool:
            layer_tasks = []
            session_ids = []
            for s in layer_sessions:
                kt = s.session_id.split(":")[-1]
                if kt in KNOWLEDGE_PROMPTS:
                    layer_tasks.append(run_knowledge(s, kt))
                    session_ids.append(s.session_id)
            if not layer_tasks:
                return True
            results = await asyncio.gather(*layer_tasks, return_exceptions=True)
            has_failure = False
            for s_id, r in zip(session_ids, results):
                if isinstance(r, Exception):
                    has_failure = True
                    logger.error("Retry layer %d task %s failed: %s", layer_num, s_id, r)
            return not has_failure

        # Run failed sessions in from_layer
        failed_results = await db.execute(
            select(Session).where(Session.session_id.in_(failed_session_ids))
        )
        failed_sessions = failed_results.scalars().all()
        if failed_sessions:
            await run_layer(failed_sessions, from_layer)

        # Run all sessions in subsequent layers
        for layer_num in range(from_layer + 1, 5):  # layers go up to 4
            if layer_num == 4:
                # Layer 4: project.md
                sid = f"init:{project_id}:project_md"
                try:
                    async with get_background_db() as layer4_db:
                        prompt = PROJECT_MD_PROMPT.format(output_path=str(project_dir))
                        client = await build_cody_client(layer4_db, str(project_dir), allowed_roots)
                        runner = SessionRunner(client)
                        async with client:
                            await runner.run(layer4_db, sid, prompt, extra_channels=[project_bus], language=lang)
                except Exception as e:
                    logger.error("Retry layer 4 project.md failed: %s", e)
            else:
                layer_results = await db.execute(
                    select(Session).where(
                        Session.ref_id == project_id, Session.layer == layer_num
                    )
                )
                layer_sessions = layer_results.scalars().all()
                await run_layer(layer_sessions, layer_num)

        await ws_manager.publish(project_bus, {"type": "done"})
