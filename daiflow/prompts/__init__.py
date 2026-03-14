"""Prompt templates for DaiFlow AI tasks.

All prompts are centralized here so they can be tuned without modifying service logic.
"""

# ── Task stage prompts ──

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

COMMIT_MESSAGE_PROMPT_TEMPLATE = (
    "Generate a concise git commit message for the following changes.\n"
    "Use conventional commit format (feat/fix/refactor/docs/chore).\n"
    "Include a short subject line and a brief body with bullet points.\n\n"
    "Task: {task_name}\n"
    "Description: {task_description}\n\n"
    "Diff:\n```\n{diff}\n```\n\n"
    "Output ONLY the commit message, nothing else."
)

# ── Stage chat system prefixes ──

PLAN_CHAT_PREFIX = (
    "You are a senior software architect helping refine a technical plan.\n"
    "Your primary task is to discuss and modify the technical plan in `plan.md`.\n\n"
    "## Context\n"
    "- Read `project.md` in the current working directory for project knowledge.\n"
    "- The current technical plan is in `plan.md` — read it first if you haven't.\n"
    "- Plan file path: `{plan_path}`\n\n"
    "## Important Rules\n"
    "- When the user asks for changes, update `plan.md` directly by writing to the file.\n"
    "- Keep the plan in proper Markdown format with clear headings and bullet points.\n"
    "- Focus solely on the technical plan — do not implement code or make other changes.\n\n"
    "## User Message\n"
)

TODO_CHAT_PREFIX = (
    "You are a technical lead helping refine task decomposition.\n"
    "Your primary task is to discuss and modify the todo list in `todo.json`.\n\n"
    "## Context\n"
    "- Read `project.md` in the current working directory for project knowledge.\n"
    "- Read `plan.md` for the technical plan that the todos are based on.\n"
    "- The current todo list is in `todo.json` — read it first if you haven't.\n"
    "- Todo file path: `{todo_path}`\n\n"
    "## Important Rules\n"
    "- When the user asks for changes, update `todo.json` directly by writing to the file.\n"
    "- Keep the JSON format: an array of objects with `seq`, `title`, `description` fields.\n"
    "- Each todo should be an independently executable unit of work.\n"
    "- Focus solely on the todo decomposition — do not implement code or modify the plan.\n\n"
    "## User Message\n"
)

# ── Project knowledge prompts ──

KNOWLEDGE_PROMPTS = {
    "frontend-structure": (
        "You have access to the following repositories:\n{repos_context}\n\n"
        "Analyze the frontend repositories and generate a comprehensive skill document about the frontend directory structure. "
        "Cover: directory organization, module responsibilities, naming conventions, and architectural patterns. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: frontend-structure, description: Frontend directory structure analysis, user-invocable: false)."
    ),
    "backend-structure": (
        "You have access to the following repositories:\n{repos_context}\n\n"
        "Analyze the backend repositories and generate a comprehensive skill document about the backend directory structure. "
        "Cover: directory organization, module responsibilities, naming conventions, and architectural patterns. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: backend-structure, description: Backend directory structure analysis, user-invocable: false)."
    ),
    "business-flow": (
        "You have access to the following repositories:\n{repos_context}\n\n"
        "Analyze the repositories and generate a comprehensive skill document about business flows. "
        "Cover: key user flows per module, state transitions, and data flow patterns. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: business-flow, description: Business flow analysis per module, user-invocable: false)."
    ),
    "component-usage": (
        "You have access to the following repositories:\n{repos_context}\n\n"
        "Analyze the frontend repositories and generate a comprehensive skill document about component usage. "
        "Cover: shared components, usage patterns, props interfaces, and composition patterns. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: component-usage, description: Frontend component structure and reuse patterns, user-invocable: false)."
    ),
    "module-overview": (
        "You have access to the following repositories:\n{repos_context}\n\n"
        "Analyze all repositories and generate a comprehensive skill document about module breakdown. "
        "Cover: all modules across frontend and backend, their responsibilities and boundaries. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: module-overview, description: Module breakdown and descriptions, user-invocable: false)."
    ),
    "api-interaction": (
        "You have access to the following repositories:\n{repos_context}\n\n"
        "Analyze all repositories and generate a comprehensive skill document about API interactions. "
        "Cover: API endpoints, request/response patterns, frontend-backend integration points. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: api-interaction, description: Frontend-backend API interaction relationships, user-invocable: false)."
    ),
    "data-entity": (
        "You have access to the following repositories:\n{repos_context}\n\n"
        "Analyze all repositories and generate a comprehensive skill document about data entities. "
        "Cover: data models, database schemas, data flow patterns, and entity relationships. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: data-entity, description: Data entities and data flows per module, user-invocable: false)."
    ),
    "dependencies": (
        "You have access to the following repositories:\n{repos_context}\n\n"
        "Analyze all repositories and generate a comprehensive skill document about dependencies. "
        "Cover: external dependencies, internal module dependencies, version requirements. "
        "Write the output to {output_path}/SKILL.md in Agent Skills format with YAML frontmatter "
        "(name: dependencies, description: Downstream dependencies per module, user-invocable: false)."
    ),
}

PROJECT_MD_PROMPT = (
    "Read all SKILL.md files under {output_path}/skills/ directory (each subdirectory contains one SKILL.md). "
    "Generate a project.md index file that summarizes all skills and serves as a knowledge base entry point. "
    "Write the output to {output_path}/project.md."
)
