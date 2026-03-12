# DaiFlow

本地 AI 编程工作台，将开发全流程（需求 → 技术方案 → 任务拆解 → 编码实现 → 代码审查 → 提交 MR）产品化，通过内置 AI 引擎（Cody SDK）理解项目上下文并辅助开发者。

## 功能概览

- **项目管理** — 创建项目、关联多仓库（前端/后端/自定义）、自动生成项目知识库
- **四阶段 DevFlow** — 技术方案 → 任务拆解 → 编码实现 → 代码审查，每个阶段都支持 AI 对话
- **实时流式交互** — WebSocket 推送 AI 执行过程，所见即所得
- **三层数据持久化** — DB（状态） + JSONL（事件回放） + WebSocket（实时推送），重启可恢复
- **多仓库支持** — 项目可关联多个 Git 仓库，AI 具有跨仓上下文感知能力
- **主题切换** — 深色/浅色主题

## 技术栈

| 层 | 技术 |
|---|------|
| 前端 | React 19 + TypeScript, Vite |
| 后端 | Python 3.11+, FastAPI (async), WebSocket |
| AI 引擎 | Cody SDK（进程内，无外部服务） |
| 数据库 | SQLite (SQLAlchemy ORM + aiosqlite) |
| 迁移 | Alembic |
| 本地存储 | `~/.daiflow/` |

## 快速开始

### 环境要求

- Python >= 3.11
- Node.js >= 18

### 安装 & 启动

```bash
# 克隆项目
git clone <repo-url> && cd daiflow

# 后端
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

# 前端
cd frontend && npm install && npm run build && cd ..

# 启动（自动打开浏览器）
daiflow start
```

服务启动在 `http://localhost:8000`，React 构建产物作为静态文件挂载。

### 开发模式

```bash
# 终端 1：后端（热重载）
uvicorn daiflow.main:app --reload --port 8000

# 终端 2：前端（HMR）
cd frontend && npm run dev
```

### 首次使用

1. 进入 Settings 页面，配置 AI 模型、Base URL、API Key
2. 创建项目，关联本地 Git 仓库
3. 等待项目知识生成完成（四层并发生成）
4. 创建任务，进入 DevFlow 四阶段工作流

## 项目结构

```
daiflow/
├── daiflow/                  # 后端 Python 包
│   ├── main.py               # FastAPI 入口
│   ├── config.py             # 全局配置（~/.daiflow 路径等）
│   ├── database.py           # SQLAlchemy 初始化
│   ├── models.py             # ORM 模型（6 张表）
│   ├── ws_manager.py         # WebSocket 发布订阅管理器
│   ├── session_runner.py     # AI 任务统一执行器
│   ├── cli.py                # CLI 入口（daiflow start）
│   ├── routers/              # HTTP 路由层
│   │   ├── settings.py       # 设置 API
│   │   ├── projects.py       # 项目 CRUD + 初始化
│   │   ├── tasks.py          # 任务 CRUD + 阶段转换 + 对话
│   │   ├── todos.py          # Todo 执行 + 对话
│   │   ├── sessions.py       # Session 状态/日志/流
│   │   └── ws.py             # WebSocket 端点
│   └── services/             # 业务逻辑层
│       ├── project_service.py  # 项目初始化（四层知识生成）
│       ├── task_service.py     # 任务生命周期管理
│       ├── cody_service.py     # Cody SDK 封装
│       ├── chat_service.py     # 阶段对话公共逻辑
│       ├── git_service.py      # Git 操作
│       └── skill_service.py    # Skill 文件管理
├── frontend/                 # 前端 React SPA
│   └── src/
│       ├── pages/            # 页面组件
│       │   ├── Settings/     # 模型配置
│       │   ├── Projects/     # 项目管理
│       │   ├── Tasks/        # 任务列表
│       │   └── DevFlow/      # 四阶段工作流
│       │       ├── PlanStage/
│       │       ├── TodoStage/
│       │       ├── CodingStage/
│       │       └── ReviewStage/
│       ├── components/       # 通用组件
│       ├── hooks/            # React Hooks
│       ├── api/              # API 客户端
│       └── ws/               # WebSocket 客户端
├── tests/                    # 后端测试
├── alembic/                  # 数据库迁移
├── docs/                     # 文档
└── demo/daiflow-ui/          # UI 原型（HTML/CSS）
```

## 架构

```
┌─────────────────┐
│  React SPA      │
│  (Vite + TS)    │
└────────┬────────┘
         │ HTTP REST + WebSocket
┌────────┴────────┐
│  FastAPI         │
│  (async Python)  │
├─────────┬────────┤
│ Cody SDK│ SQLite │
│ (AI)    │ (ORM)  │
└─────────┴────────┘
```

### 核心模式：SessionRunner + WSManager

所有 AI 交互共享统一模式：**SessionRunner** 执行 Cody → 写日志到 `.jsonl` → 更新 DB 状态 → 通过 WSManager 广播；客户端通过 WebSocket 单连接订阅频道接收推送。

三个统一 API 覆盖所有场景：

- `GET /api/sessions/{id}/status` — DB 快照（重启存活）
- `GET /api/sessions/{id}/logs` — `.jsonl` 回放（重启存活）
- `WS /api/ws` — WebSocket 单连接多路复用（频道订阅 + 对话）

### 四阶段 DevFlow

| 阶段 | 功能 | Cody Session 策略 |
|------|------|------------------|
| 1. 技术方案 | AI 生成 + 对话调整 | 独立 session |
| 2. 任务拆解 | AI 拆解为 Todo 列表 | 复用方案阶段 session |
| 3. 编码实现 | 逐个 Todo 执行 + Diff | 每个 Todo 独立 session |
| 4. 代码审查 | 全量 Diff + 提交 MR | 独立 session |

### 项目知识生成（四层流水线）

| 层 | 内容 | 并发策略 |
|----|------|---------|
| Layer 1 | Skill 拉取（占位） | 并行 |
| Layer 2 | 按仓库：前端结构、后端结构、业务流、组件用法 | 并行 |
| Layer 3 | 跨仓库：模块概览、API 交互、数据实体、依赖关系 | 并行 |
| Layer 4 | 生成 `project.md` 索引 | 串行 |

## 数据库

6 张表：`projects`、`project_repos`、`tasks`、`todos`、`sessions`、`settings`

### 迁移

```bash
# 生成迁移
alembic revision --autogenerate -m "description"

# 执行迁移
alembic upgrade head
```

## API 概览

| 分类 | 端点 |
|------|------|
| 设置 | `GET/PUT /api/settings`, `GET /api/settings/check` |
| 项目 | CRUD `/api/projects`, `POST .../init`, `GET .../init/sessions` |
| 任务 | CRUD `/api/tasks`, `POST .../lock-plan`, `POST .../start-coding`, `POST .../start-review` |
| DevFlow | `POST /api/tasks/{id}/plan`, `.../plan/chat`, `.../todo`, `.../todo/chat`, `POST /api/todos/{id}/execute`, `.../chat`, `.../review/chat` |
| Session | `GET /api/sessions/{id}/status`, `.../logs` |
| WebSocket | `WS /api/ws`（subscribe / chat / ping） |
| 审查 | `GET /api/tasks/{id}/diff`, `POST /api/tasks/{id}/submit-mr` |

## 测试

```bash
# 运行全部后端测试
.venv/bin/python -m pytest tests/ -v

# 运行特定模块
.venv/bin/python -m pytest tests/test_api_projects.py -v
```

## 本地文件布局

```
~/.daiflow/
├── daiflow.db                          # SQLite 数据库
├── cody_sessions.db                    # Cody SDK session 持久化
├── sessions/                           # Session 日志（.jsonl）
├── projects/{project_id}/              # 项目知识
│   ├── project.md                      # 项目索引
│   └── skills/{knowledge_type}/SKILL.md
└── tasks/{task_id}/                    # 任务工作目录
    ├── plan.md                         # 技术方案
    ├── todo.json                       # Todo 列表
    ├── project.md                      # 从项目复制
    └── .cody/skills/                   # 从项目复制
```

## License

Private
