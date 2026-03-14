# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DaiFlow is a local AI-powered programming workbench that productizes the full development workflow (requirement → technical plan → task decomposition → coding → code review → merge request). It uses an in-process AI engine (Cody SDK) to understand project context and assist developers.

**Current status:** Early implementation — backend skeleton (FastAPI + SQLAlchemy models + routers + services) and frontend scaffold (React + Vite with pages/hooks/components) are in place. Core business logic (SessionRunner, WSManager, Cody integration) is being built out.

## Tech Stack

- **Frontend:** React 19 + TypeScript, built with Vite 6, react-router-dom v7
- **Backend:** Python 3.11+ with FastAPI (async), WebSocket for streaming
- **AI Engine:** Cody SDK (`pip install cody-ai`, `from cody import AsyncCodyClient`) — in-process, no external service; see `docs/Cody_sdk.md` for full API
- **Database:** SQLite via SQLAlchemy async ORM (aiosqlite driver), Alembic for migrations
- **Local Storage:** `~/.daiflow/` directory for DB, sessions, projects, tasks (override with `DAIFLOW_HOME` env var)

## Development Commands

```bash
# Backend setup & run
pip install -r requirements.txt
pip install -e .                      # Install daiflow package in dev mode
uvicorn daiflow.main:app --reload --port 8000

# CLI entry point (after pip install -e .)
daiflow start                         # Starts server + auto-opens browser
daiflow start --port 9000 --no-browser

# Frontend
cd frontend
npm install
npm run dev          # Vite dev server with HMR
npm run build        # tsc + vite build

# Testing
pip install pytest pytest-asyncio httpx  # Test dependencies
pytest                                   # Run all tests
pytest tests/test_models.py              # Run a single test file
pytest tests/test_api_tasks.py -k "test_create_task"  # Run a single test

# Database migrations (Alembic)
alembic revision --autogenerate -m "description"  # Generate migration
alembic upgrade head                               # Apply migrations
# Note: alembic env.py auto-strips +aiosqlite from DATABASE_URL for sync Alembic
```

## Architecture

```
Frontend (React SPA)
    ↕  HTTP REST + WebSocket
Backend (FastAPI)
    ↕              ↕
Cody SDK       SQLite DB
```

### Core Workflow (4 Stages)

1. **Technical Plan** — AI generates plan from task description; user discusses/adjusts
2. **Task Decomposition** — Plan broken into sequential todos
3. **Code Implementation** — Each todo executed independently by AI; user reviews
4. **Code Review & Submit** — Review all diffs, generate commit message, push MR

### Session Architecture (SessionRunner + WSManager)

All AI interactions share a unified pattern: **SessionRunner** executes Cody → writes logs to `.jsonl` → updates status in DB → pushes events via **WSManager** (WebSocket). Three data access patterns:
- `GET /api/sessions/{id}/status` — DB snapshot (survives restart)
- `GET /api/sessions/{id}/logs` — `.jsonl` file replay (survives restart)
- `WS /api/ws` — single multiplexed WebSocket connection for all real-time events

**WebSocket Protocol:** Single connection, channel-based pub/sub. Client sends `{"action": "subscribe", "channel": "session:task:42:plan"}` to receive events; sends `{"action": "chat", "id": "req_1", "chat_path": "plan", "entity_id": "abc", "message": "..."}` for bidirectional chat. Server pushes `{"channel": "...", "event": {...}}`.

**Two IDs to distinguish:**
- `session_id` — DaiFlow business ID (e.g. `task:42:plan`, `init:proj_1:frontend-structure`)
- `cody_session_id` — Cody SDK's internal UUID (stored in sessions table for traceability)

**Channel naming:**

- `session:{session_id}` — individual session event stream
- `project:init:{project_id}` — project init aggregation bus
- `chat:{request_id}` — ephemeral chat response stream (auto-cleaned on done)

### Cody Session Strategy

- Project knowledge generation: independent Cody session per knowledge type (concurrent)
- Tech plan + todo decomposition: shared single Cody session (context continuity via `sessions` table lookup: `task_id` + `type="plan"`)
- Individual todo execution: independent Cody session per todo (plan.md as shared context)
- Code review: independent Cody session (tracked via `sessions` table: `task_id` + `type="review"`)

### Project Knowledge (Four-Layer Generation)

Layers execute serially (await), tasks within each layer run concurrently (asyncio.gather):

**Layer 1 (parallel):** Resource prep — Skill fetch + repo clone/pull
**Layer 2 (parallel, per-repo):** `frontend-structure`, `backend-structure`, `business-flow`, `component-usage`
**Layer 3 (parallel, cross-repo):** `module-overview`, `api-interaction`, `data-entity`, `dependencies`
**Layer 4:** Generate `project.md` index file

Output: `~/.daiflow/projects/{project_id}/skills/{knowledge_type}/SKILL.md`

## Testing Patterns

- Tests use `pytest` with `asyncio_mode = auto` (see `pytest.ini`)
- `conftest.py` sets `DAIFLOW_HOME` to a temp directory before any daiflow imports
- DB tests use in-memory SQLite (`sqlite+aiosqlite:///:memory:`)
- API tests use `httpx.AsyncClient` with ASGI transport against the FastAPI app
- `get_db` and `get_background_db` are both overridden in the test `client` fixture — when adding new services that use `get_background_db`, add corresponding patches in `conftest.py`

## Key API Routes

| Category | Key Endpoints |
|----------|--------------|
| Settings | `GET/PUT /api/settings`, `GET /api/settings/check` |
| Projects | CRUD `/api/projects`, `POST .../init`, `GET .../init/sessions` |
| Tasks | CRUD `/api/tasks`, `POST .../lock-plan`, `POST .../start-coding`, `POST .../start-review` |
| Dev Flow | `POST /api/tasks/{id}/plan`, `POST .../todo`, `POST /api/todos/{id}/execute` |
| Sessions | `GET /api/sessions/{id}/status`, `GET .../logs` |
| WebSocket | `WS /api/ws` — subscribe to channels, real-time events, stage chat |
| Review | `GET /api/tasks/{id}/diff`, `POST /api/tasks/{id}/submit-mr` |
| Jobs | CRUD `/api/jobs`, `GET .../runs`, `POST .../trigger` |

## Database Schema (8 tables)

Defined in `daiflow/models.py`. All primary keys use UUID hex strings (`uuid.uuid4().hex`).

- **projects** — id, name, description, skill_names (JSON array string)
- **project_repos** — id, project_id (FK), git_url, local_path, repo_type (frontend/backend/custom), repo_type_label, description, master_hash
- **tasks** — id, name, project_id (FK), description, branch, prd, tech_plan, status (int), mr_info (JSON string)
- **todos** — id, task_id (FK), seq, title, description, status (int), cody_session_id, commit_before (JSON), commit_after (JSON), result
- **sessions** — session_id (PK, business ID), task_id (FK nullable), cody_session_id, type, ref_id, layer (1-4 for init, NULL otherwise), status (int), error, started_at, finished_at
- **jobs** — id, project_id (FK), type, enabled, interval, config (JSON)
- **job_runs** — id, job_id (FK), status (int), result (JSON), error, started_at, finished_at
- **settings** — key/value pairs: `cody_model`, `cody_base_url`, `cody_api_key`, `theme`, `language`

## Status Enums (IntEnum in models.py)

- **TaskStatus:** 0=CREATED, 1=INITIALIZING, 2=PLANNING, 3=PLAN_LOCKED, 4=TODO_READY, 5=CODING, 6=REVIEWING, 7=DONE
- **TodoStatus:** 0=PENDING, 1=RUNNING, 2=DONE, 3=FAILED, 4=SKIPPED
- **SessionStatus:** 0=WAITING, 1=RUNNING, 2=DONE, 3=FAILED
- **JobRunStatus:** 0=RUNNING, 1=SUCCESS, 2=FAILED

## Key File Locations

- `docs/DaiFlow_技术方案.md` — Full technical specification (primary reference for implementation)
- `docs/DaiFlow_产品文档.md` — Product requirements document
- `docs/Cody_sdk.md` — Cody SDK API reference
- `demo/daiflow-ui/` — HTML/CSS UI prototypes (design reference)
- `demo/daiflow-ui/shared.css` — Design system (theme tokens, color palette, typography)

## Conventions

- Skill files use YAML frontmatter + Markdown body, with `user-invocable: false`
- All AI tasks go through SessionRunner → WSManager → WebSocket push
- Cody SDK StreamChunk types: `text_delta`, `thinking`, `tool_call`, `tool_result`, `done`, `compact`
- DaiFlow event types: above + `status_change` (converted from done), `plan_updated` / `todo_updated` / `code_updated` (file write detection per stage), `skill_loaded` (read_skill detection), `session_status` (init bus)
- All 4 stage chats go through `WS /api/ws` chat action, shared pattern: `useStageChat` hook + `chat_service.prepare_stage_chat()` + `run_stage_chat()` backend generator
- Stage-specific updated events: `plan_updated` (push full content), `todo_updated` (push full content), `code_updated` (push null, frontend re-fetches diff), `skill_loaded` (push skill_name when Cody calls read_skill)
- Session logs persisted to `~/.daiflow/sessions/{session_id}.jsonl` for replay after restart
- Multi-repo support via `allowed_roots` in Cody client config
- Frontend routing: settings guard checks `/api/settings/check` before allowing access to main app
- Documentation is in Chinese (产品文档 = product doc, 技术方案 = tech spec)
- UI supports dark/light theme via `data-theme` attribute and CSS custom properties
- Fonts: Sora (sans-serif UI) + JetBrains Mono (code/monospace)
- Alembic migrations use `render_as_batch=True` (required for SQLite ALTER TABLE support)
- `config.py` file-write detection uses `FILE_WRITE_TOOLS` frozenset to identify Cody tool calls that modify files
