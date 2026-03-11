# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DaiFlow is a local AI-powered programming workbench that productizes the full development workflow (requirement → technical plan → task decomposition → coding → code review → merge request). It uses an in-process AI engine (Cody SDK) to understand project context and assist developers.

**Current status:** MVP phase — technical spec, product docs, and UI prototypes are complete; backend/frontend implementation has not yet started.

## Tech Stack

- **Frontend:** React + TypeScript, built with Vite
- **Backend:** Python 3.11+ with FastAPI (async), SSE for streaming
- **AI Engine:** Cody SDK (`pip install cody-ai`, `from cody import AsyncCodyClient`) — in-process, no external service; see `docs/Cody_sdk.md` for full API
- **Database:** SQLite via SQLAlchemy ORM
- **Local Storage:** `~/.daiflow/` directory for projects, tasks, skill files, and session logs

## Development Commands

```bash
# Start the application (planned CLI entry point)
daiflow start
# Starts FastAPI on http://localhost:8000, serves React build as static files, auto-opens browser

# Backend (Python/FastAPI)
pip install -r requirements.txt
uvicorn daiflow.main:app --reload --port 8000

# Frontend (React/Vite)
cd frontend
npm install
npm run dev          # Dev server with HMR
npm run build        # Build to backend static/ directory
```

## Architecture

```
Frontend (React SPA)
    ↕  HTTP REST + SSE
Backend (FastAPI)
    ↕              ↕
Cody SDK       SQLite DB
```

### Core Workflow (4 Stages)

1. **Technical Plan** — AI generates plan from task description; user discusses/adjusts
2. **Task Decomposition** — Plan broken into sequential todos
3. **Code Implementation** — Each todo executed independently by AI; user reviews
4. **Code Review & Submit** — Review all diffs, generate commit message, push MR

### Planned Backend Structure

```
daiflow/
├── main.py                  # FastAPI entry, mounts static files
├── database.py              # SQLAlchemy init
├── models.py                # ORM models
├── config.py                # Global config (~/.daiflow path, etc.)
├── sse_manager.py           # SSEManager — in-process asyncio.Queue pub/sub
├── session_runner.py        # SessionRunner — unified AI task executor
├── routers/
│   ├── settings.py          # GET/PUT /api/settings, GET /api/settings/check
│   ├── projects.py          # CRUD /api/projects, POST /api/projects/{id}/init
│   ├── tasks.py             # CRUD /api/tasks, lock-plan/start-coding/start-review
│   ├── todos.py             # GET /api/tasks/{id}/todos, POST /api/todos/{id}/execute
│   └── sessions.py          # Unified session API (status / logs / stream)
├── services/
│   ├── project_service.py   # Project business logic + 4-layer init orchestration
│   ├── task_service.py      # Task lifecycle + plan/todo generation
│   ├── cody_service.py      # Cody SDK wrapper (build_cody_client)
│   ├── git_service.py       # Git operations (checkout, diff, commit, push)
│   └── skill_service.py     # Skill file sync and management
└── static/                  # React build output
```

### Planned Frontend Structure

```
src/
├── pages/
│   ├── Settings/            # Model/API config (cody_model, base_url, api_key, theme)
│   ├── Projects/            # Project CRUD + init trigger
│   ├── Tasks/               # Task list per project
│   └── DevFlow/             # 4-stage dev workflow
│       ├── PlanStage/       # Tech plan generation + AI chat
│       ├── TodoStage/       # Todo decomposition + AI chat
│       ├── CodingStage/     # Per-todo execution with diff viewer
│       └── ReviewStage/     # Full diff review + MR submission
├── components/
│   ├── ChatPanel/           # Reusable AI chat panel (right sidebar)
│   ├── MarkdownViewer/      # Markdown rendering
│   ├── DiffViewer/          # Code diff (react-diff-viewer)
│   └── StreamLog/           # SSE execution log display
├── hooks/
│   ├── useSession.ts        # Unified session hook (status restore + log replay + SSE)
│   ├── useStageChat.ts      # Common stage chat hook (shared by all 4 stages)
│   ├── useInitProgress.ts   # Init page hook (project-level SSE bus for all init sessions)
│   ├── usePlanStage.ts      # Plan stage hook (plan content + chat + plan_updated sync)
│   ├── useTodoStage.ts      # Todo stage hook (todo list + chat + todo_updated sync)
│   ├── useCodingStage.ts    # Coding stage hook (todo exec + diff + chat + code_updated)
│   ├── useSSE.ts            # Low-level SSE connection wrapper (EventSource)
│   └── useChat.ts           # Chat interaction logic
└── api/
    └── index.ts             # API client
```

### Session Architecture (SessionRunner + SSEManager)

All AI interactions share a unified pattern: **SessionRunner** executes Cody → writes logs to `.jsonl` → updates status in DB → pushes SSE via **SSEManager**. Three unified APIs serve all scenarios:
- `GET /api/sessions/{id}/status` — DB snapshot (survives restart)
- `GET /api/sessions/{id}/logs` — `.jsonl` file replay (survives restart)
- `GET /api/sessions/{id}/stream` — real-time SSE (in-memory Queue)

**Two IDs to distinguish:**
- `session_id` — DaiFlow business ID (e.g. `task:42:plan`, `init:proj_1:frontend_structure`)
- `cody_session_id` — Cody SDK's internal UUID (stored in sessions table for traceability)

**Project-level SSE bus:** Init page uses `GET /api/projects/{id}/init/stream` to receive all session status changes through one SSE connection (channel: `project:init:{project_id}`). Individual session detail uses the standard `useSession` hook.

### Cody Session Strategy

- Project knowledge generation: independent Cody session per knowledge type (concurrent)
- Tech plan + todo decomposition: shared single Cody session (context continuity via `tasks.plan_cody_session_id`)
- Individual todo execution: independent Cody session per todo (plan.md as shared context)
- Code review: independent Cody session (`tasks.review_cody_session_id`)

### Project Knowledge (Four-Layer Generation)

Layers execute serially (await), tasks within each layer run concurrently (asyncio.gather):

**Layer 1 (parallel):** Resource prep — Skill fetch + repo clone/pull
**Layer 2 (parallel, per-repo):** `frontend_structure`, `backend_structure`, `business_flow`, `component_usage`
**Layer 3 (parallel, cross-repo):** `module_overview`, `api_interaction`, `data_entity`, `dependencies`
**Layer 4:** Generate `project.md` index file

Output: `~/.daiflow/projects/{project_id}/skills/{knowledge_type}/SKILL.md`

## Key API Routes

| Category | Key Endpoints |
|----------|--------------|
| Settings | `GET/PUT /api/settings`, `GET /api/settings/check` |
| Projects | CRUD `/api/projects`, `POST .../init`, `GET .../init/sessions`, `GET .../init/stream` (SSE) |
| Tasks | CRUD `/api/tasks`, `POST .../lock-plan`, `POST .../start-coding`, `POST .../start-review` |
| Dev Flow | `POST /api/tasks/{id}/plan`, `POST .../plan/chat`, `POST .../todo`, `POST .../todo/chat`, `POST /api/todos/{id}/execute`, `POST .../todos/{id}/chat`, `POST .../review/chat` |
| Sessions | `GET /api/sessions/{id}/status`, `GET .../logs`, `GET .../stream` (SSE) |
| Review | `GET /api/tasks/{id}/diff`, `POST /api/tasks/{id}/submit-mr` |

## Database Schema (6 tables)

- **projects** — id, name, description, skill_names (JSON array)
- **project_repos** — id, project_id (FK), git_url, local_path, repo_type (frontend/backend/custom), description
- **tasks** — id, name, project_id (FK), description, branch, prd, tech_plan, status, plan_cody_session_id, review_cody_session_id, mr_info
- **todos** — id, task_id (FK), seq, title, description, status, cody_session_id, result
- **sessions** — session_id (PK, business ID), cody_session_id, type, ref_id, layer (init层级:1/2/3/4, 其他NULL), status, error, started_at, finished_at
- **settings** — key/value pairs: `cody_model`, `cody_base_url`, `cody_api_key`, `theme`

## Status Enums

- **Task:** 0=created, 1=initializing, 2=planning, 3=plan_locked, 4=todo_ready, 5=coding, 6=reviewing, 7=done
- **Todo:** 0=pending, 1=running, 2=done, 3=failed

## Key File Locations

- `docs/DaiFlow_技术方案.md` — Full technical specification (primary reference for implementation)
- `docs/DaiFlow_产品文档.md` — Product requirements document
- `demo/daiflow-ui/` — HTML/CSS UI prototypes (8 pages)
- `demo/daiflow-ui/shared.css` — Design system (theme tokens, color palette, typography)

## Conventions

- Skill files use YAML frontmatter + Markdown body, with `user-invocable: false`
- All AI tasks go through SessionRunner → SSEManager → unified Session API
- Cody SDK StreamChunk types: `text_delta`, `thinking`, `tool_call`, `tool_result`, `done`, `compact`
- DaiFlow SSE event types: above + `status_change` (converted from done), `plan_updated` / `todo_updated` / `code_updated` (file write detection per stage), `session_status` (init bus)
- All 4 stage chat endpoints return SSE streams (not JSON), share common pattern: `useStageChat` hook + `stage_chat()` backend template
- Stage-specific updated events: `plan_updated` (push full content), `todo_updated` (push full content), `code_updated` (push null, frontend re-fetches diff)
- Session logs persisted to `~/.daiflow/sessions/{session_id}.jsonl` for replay after restart
- Multi-repo support via `allowed_roots` in Cody client config
- Frontend routing: settings guard checks `/api/settings/check` before allowing access to main app
- Documentation is in Chinese (产品文档 = product doc, 技术方案 = tech spec)
- UI supports dark/light theme via `data-theme` attribute and CSS custom properties
- Fonts: Sora (sans-serif UI) + JetBrains Mono (code/monospace)
