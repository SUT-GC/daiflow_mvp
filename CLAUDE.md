# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DaiFlow is a local AI-powered programming workbench that productizes the full development workflow (requirement → technical plan → task decomposition → coding → code review → merge request). It uses an in-process AI engine (Cody SDK) to understand project context and assist developers.

**Current status:** MVP phase — technical spec, product docs, and UI prototypes are complete; backend/frontend implementation has not yet started.

## Tech Stack

- **Frontend:** React + TypeScript, built with Vite
- **Backend:** Python 3.11+ with FastAPI (async), SSE for streaming
- **AI Engine:** Cody SDK (`AsyncCodyClient`) — in-process, no external service
- **Database:** SQLite via SQLAlchemy ORM
- **Local Storage:** `~/.daiflow/` directory for projects, tasks, and skill files

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
├── routers/
│   ├── settings.py          # GET/PUT /api/settings, GET /api/settings/check
│   ├── projects.py          # CRUD /api/projects, POST /api/projects/{id}/init
│   ├── tasks.py             # CRUD /api/tasks, lock-plan/start-coding/start-review
│   ├── todos.py             # GET /api/tasks/{id}/todos, POST /api/todos/{id}/execute/stream
│   └── stream.py            # SSE streaming endpoints
├── services/
│   ├── project_service.py   # Project business logic + knowledge generation
│   ├── task_service.py      # Task lifecycle + plan/todo generation
│   ├── cody_service.py      # Cody SDK wrapper (build_cody_client, session mgmt)
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
│   ├── useSSE.ts            # SSE connection wrapper (EventSource)
│   └── useChat.ts           # Chat interaction logic
└── api/
    └── index.ts             # API client
```

### Cody Session Strategy

- Project knowledge generation: independent session per knowledge type (concurrent)
- Tech plan + todo decomposition: shared single session (context continuity via `tasks.plan_session_id`)
- Individual todo execution: independent session per todo (plan.md as shared context)

### Project Knowledge (Two-Layer Generation)

**Layer 1 (parallel, per-repo):** `frontend_structure`, `backend_structure`, `business_flow`, `component_usage`
**Layer 2 (parallel, cross-repo, after Layer 1 completes):** `module_overview`, `api_interaction`, `data_entity`, `dependencies`

After both layers: generate `project.md` index file.

Output: `~/.daiflow/projects/{project_id}/skills/{knowledge_type}/SKILL.md`

## Key API Routes

| Category | Key Endpoints |
|----------|--------------|
| Settings | `GET/PUT /api/settings`, `GET /api/settings/check` |
| Projects | CRUD `/api/projects`, `POST /api/projects/{id}/init`, `GET /api/projects/{id}/init/stream` (SSE) |
| Tasks | CRUD `/api/tasks`, `POST .../lock-plan`, `POST .../start-coding`, `POST .../start-review` |
| Dev Flow | `GET /api/tasks/{id}/plan/stream` (SSE), `POST .../plan/chat`, `GET .../todo/stream` (SSE), `POST /api/todos/{id}/execute/stream` (SSE) |
| Review | `GET /api/tasks/{id}/diff`, `POST /api/tasks/{id}/submit-mr` |

## Database Schema (5 tables)

- **projects** — id, name, description, skill_names (JSON array)
- **project_repos** — id, project_id (FK), git_url, local_path, repo_type (frontend/backend/custom), description
- **tasks** — id, name, project_id (FK), description, branch, prd, tech_plan, status, plan_session_id, mr_info
- **todos** — id, task_id (FK), seq, title, description, status, session_id, result
- **settings** — key/value pairs: `cody_model`, `cody_base_url`, `cody_api_key`, `theme`
- **project_init_sessions** — id, project_id (FK), knowledge_type, session_id, status

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
- All AI streaming uses SSE (`StreamingResponse` with `text/event-stream`)
- SSE event types: `text_delta`, `tool_call`, `tool_result`, `done` (includes session_id), `error`
- Multi-repo support via `allowed_roots` in Cody client config
- Frontend routing: settings guard checks `/api/settings/check` before allowing access to main app
- Documentation is in Chinese (产品文档 = product doc, 技术方案 = tech spec)
- UI supports dark/light theme via `data-theme` attribute and CSS custom properties
- Fonts: Sora (sans-serif UI) + JetBrains Mono (code/monospace)
