# DaiFlow 技术方案文档

> 版本：v0.1 MVP
> 更新时间：2026-03-11

---

## 一、整体架构

### 1.1 架构概览

DaiFlow 是一个本地软件，整体分为三层：

```
┌─────────────────────────────────────────┐
│            前端 React SPA               │
│   项目管理 / 任务管理 / 开发流程界面       │
└─────────────────┬───────────────────────┘
                  │ HTTP REST + SSE
┌─────────────────▼───────────────────────┐
│           后端 FastAPI                   │
│   业务逻辑 / git 操作 / 文件管理           │
└──────────┬──────────────┬───────────────┘
           │              │
┌──────────▼──────┐  ┌────▼────────────────┐
│   Cody SDK      │  │   SQLite            │
│  AsyncCodyClient│  │   daiflow.db        │
└─────────────────┘  └─────────────────────┘
```

### 1.2 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 前端 | React + TypeScript | SPA，构建后由 FastAPI 静态托管 |
| 后端 | Python 3.11+ + FastAPI | 异步框架，原生支持 SSE |
| AI 引擎 | Cody SDK（AsyncCodyClient） | `pip install cody-ai`，in-process 调用，无需额外进程 |
| 数据库 | SQLite + SQLAlchemy | 本地存储结构化数据 |
| 本地存储 | 文件系统 | `.daiflow/` 目录管理文件数据 |

**依赖安装：**

```bash
pip install cody-ai
```

> Cody SDK 的 PyPI 包名为 `cody-ai`，安装后通过 `from cody import AsyncCodyClient` 引入。详细用法参见 `docs/Cody_sdk.md`。

### 1.3 启动方式

用户安装后通过命令行启动：

```bash
daiflow start
```

启动流程：
1. 检查 `~/.daiflow/` 目录，不存在则初始化
2. 初始化 SQLite 数据库（建表）
3. 启动 FastAPI 服务，监听 `http://localhost:8000`
4. FastAPI serve React 构建产物（静态文件）
5. 自动打开浏览器访问 `http://localhost:8000`

### 1.4 本地文件结构

```
~/.daiflow/
├── daiflow.db                        # SQLite 数据库
└── projects/
│   └── {project_id}/
│       ├── project.md                # 知识库索引文件
│       └── skills/                   # 项目 skill 文件
│           ├── frontend_structure/
│           │   └── SKILL.md
│           ├── backend_structure/
│           │   └── SKILL.md
│           ├── {其他知识点}/
│           │   └── SKILL.md
│           └── {从skill中心拉取的skill}/
│               └── SKILL.md
└── tasks/
    └── {task_id}/
        ├── project.md                # 从项目同步过来的索引文件
        ├── .cody/
        │   └── skills/               # 从项目 skills 同步过来，供 Cody 自动识别
        ├── plan.md                   # 技术方案文档
        └── todo.json                 # 任务拆解列表
```

---

## 二、数据库设计

使用 SQLite + SQLAlchemy ORM，数据库文件路径：`~/.daiflow/daiflow.db`

### 2.1 projects 项目表

```sql
CREATE TABLE projects (
    id          TEXT PRIMARY KEY,   -- UUID
    name        TEXT NOT NULL,
    description TEXT,
    skill_names TEXT,               -- JSON 数组，从 Skill 中心拉取的 skill 名称
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 project_repos 项目仓库表

```sql
CREATE TABLE project_repos (
    id               TEXT PRIMARY KEY,  -- UUID
    project_id       TEXT NOT NULL,     -- 关联 projects.id
    git_url          TEXT NOT NULL,     -- 远端仓库地址
    local_path       TEXT,              -- 本地代码路径，用户填写
    repo_type        TEXT,              -- frontend / backend / custom
    repo_type_label  TEXT,              -- custom 时人工输入的类型名称
    description      TEXT,              -- 仓库介绍，供 AI 参考
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
```

### 2.3 tasks 任务表

```sql
CREATE TABLE tasks (
    id              TEXT PRIMARY KEY,  -- UUID
    name            TEXT NOT NULL,
    project_id      TEXT NOT NULL,     -- 关联 projects.id
    description     TEXT,
    branch          TEXT,              -- 开发分支名
    prd             TEXT,              -- 产品需求，Markdown
    tech_plan       TEXT,              -- 技术方案输入，Markdown
    status          INTEGER DEFAULT 0,
    -- status 枚举：
    -- 0 = created       任务已创建
    -- 1 = initializing  初始化中（同步 skill、切分支）
    -- 2 = planning      技术方案生成中
    -- 3 = plan_locked   方案已锁定，进入任务拆解
    -- 4 = todo_ready    todo 已确认，可进入编码
    -- 5 = coding        编码中
    -- 6 = reviewing     代码审查中
    -- 7 = done          已提交 MR
    plan_session_id TEXT,              -- 技术方案+任务拆解共享的 Cody session id
    mr_info         TEXT,              -- MR 相关信息，JSON
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
```

### 2.4 todos 任务拆解表

```sql
CREATE TABLE todos (
    id          TEXT PRIMARY KEY,  -- UUID
    task_id     TEXT NOT NULL,     -- 关联 tasks.id
    seq         INTEGER NOT NULL,  -- 执行顺序，从 1 开始
    title       TEXT NOT NULL,
    description TEXT,              -- 详细描述
    status      INTEGER DEFAULT 0,
    -- status 枚举：0 = pending / 1 = running / 2 = done / 3 = failed
    session_id  TEXT,              -- 该 todo 对应的 Cody session id
    result      TEXT,              -- 执行结果摘要
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
```

### 2.5 settings 全局配置表

```sql
CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

预置 key：

| key | 说明 |
|-----|------|
| `cody_model` | 模型名称，如 `glm-4`、`qwen-plus` |
| `cody_base_url` | 模型 API 地址，如 `https://open.bigmodel.cn/api/paas/v4/` |
| `cody_api_key` | API Key |
| `theme` | 界面主题，`dark`（默认）或 `light` |

### 2.6 project_init_sessions 项目初始化 session 表

用于记录项目知识库生成时每个知识点对应的 Cody session，支持局部重新生成。

```sql
CREATE TABLE project_init_sessions (
    id           TEXT PRIMARY KEY,  -- UUID
    project_id   TEXT NOT NULL,     -- 关联 projects.id
    knowledge_type TEXT NOT NULL,   -- 知识点类型，如 frontend_structure / backend_structure /
                                    -- module_overview / business_flow / data_entity /
                                    -- api_interaction / dependencies / component_usage
    session_id   TEXT,              -- 对应的 Cody session id
    status       INTEGER DEFAULT 0,  -- 0 = pending / 1 = running / 2 = done / 3 = failed
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
```

---

## 三、后端设计

### 3.1 目录结构

```
daiflow/
├── main.py                  # FastAPI 入口，挂载静态文件
├── database.py              # SQLAlchemy 初始化
├── models.py                # ORM 模型
├── config.py                # 全局配置（daiflow 根目录路径等）
├── routers/
│   ├── settings.py          # 配置相关 API
│   ├── projects.py          # 项目相关 API
│   ├── tasks.py             # 任务相关 API
│   ├── todos.py             # Todo 相关 API
│   └── stream.py            # SSE 流式推送 API
├── services/
│   ├── project_service.py   # 项目业务逻辑
│   ├── task_service.py      # 任务业务逻辑
│   ├── cody_service.py      # Cody SDK 封装
│   ├── git_service.py       # git 操作封装
│   └── skill_service.py     # Skill 管理（同步、mock 拉取）
└── static/                  # React 构建产物（前端打包后放这里）
```

### 3.2 Cody Service 设计

Cody SDK 以 in-process 方式运行，`cody_service.py` 负责封装所有与 Cody 的交互。

**Client 创建规则：**

model、base_url、api_key 从 settings 表读取，每次创建 client 时动态获取：

```python
from cody import Cody

def build_cody_client(workdir: str, extra_roots: list[str] = []):
    model   = get_setting("cody_model")
    base_url = get_setting("cody_base_url")
    api_key  = get_setting("cody_api_key")

    return (
        Cody()
        .workdir(workdir)
        .allowed_roots([workdir] + extra_roots)
        .model(model)
        .base_url(base_url)
        .api_key(api_key)
        .build()
    )
```

- 项目知识生成：`workdir` 设为项目目录，`allowed_roots` 包含所有关联仓库的本地路径
- 任务开发阶段：`workdir` 设为 task 目录，`allowed_roots` 包含所有关联仓库的本地路径

**Session 管理策略：**

| 阶段 | session_id 来源 | 存储位置 |
|------|----------------|---------|
| 项目知识生成（每个知识点） | Cody 首次调用自动生成 | project_init_sessions.session_id |
| 技术方案 + 任务拆解 | Cody 首次调用自动生成 | tasks.plan_session_id |
| 每个 todo 执行 | Cody 首次调用自动生成 | todos.session_id |

### 3.3 SSE 流式推送设计

使用 FastAPI 的 `StreamingResponse` 实现 SSE，将 Cody stream 的输出实时推送给前端。

**SSE 事件格式：**

```
data: {"type": "text_delta", "content": "正在分析项目结构..."}

data: {"type": "tool_call", "tool_name": "read_file", "args": {"path": "src/index.ts"}}

data: {"type": "tool_result", "tool_name": "read_file", "content": "...文件内容..."}

data: {"type": "done", "session_id": "abc123"}

data: {"type": "error", "message": "执行失败"}
```

**FastAPI SSE 实现示例：**

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from cody import AsyncCodyClient
import json

async def cody_stream_generator(prompt: str, session_id: str | None, client):
    async for chunk in client.stream(prompt, session_id=session_id):
        data = {"type": chunk.type, "content": chunk.content}
        if chunk.tool_name:
            data["tool_name"] = chunk.tool_name
        if chunk.session_id:
            data["session_id"] = chunk.session_id
        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

@app.get("/api/tasks/{task_id}/plan/stream")
async def stream_plan(task_id: str):
    # 构建 prompt，创建 client...
    return StreamingResponse(
        cody_stream_generator(prompt, session_id, client),
        media_type="text/event-stream"
    )
```

### 3.4 Git Service 设计

封装本地 git 命令操作，使用 Python `subprocess` 执行：

```python
# 主要操作
git_service.checkout_branch(local_path, branch)   # 切换/创建分支
git_service.get_diff(local_path)                   # 获取 git diff
git_service.commit(local_path, message)            # git commit
git_service.push(local_path, branch)               # git push
```

### 3.5 主要 API 接口

#### 配置相关

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings` | 获取所有配置（api_key 脱敏返回） |
| PUT | `/api/settings` | 保存配置 |
| GET | `/api/settings/check` | 检查必填配置是否完整 |

#### 项目相关

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects` | 获取项目列表 |
| POST | `/api/projects` | 创建项目 |
| GET | `/api/projects/{id}` | 获取项目详情 |
| PUT | `/api/projects/{id}` | 更新项目 |
| DELETE | `/api/projects/{id}` | 删除项目 |
| POST | `/api/projects/{id}/init` | 触发项目初始化 |
| GET | `/api/projects/{id}/init/stream` | SSE：项目初始化进度推送 |

#### 任务相关

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 获取任务列表 |
| POST | `/api/tasks` | 创建任务（含初始化：同步 skill + 切分支） |
| GET | `/api/tasks/{id}` | 获取任务详情 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| POST | `/api/tasks/{id}/lock-plan` | 锁定技术方案，进入任务拆解 |
| POST | `/api/tasks/{id}/start-coding` | 确认 todo，task status → 4 |
| POST | `/api/tasks/{id}/start-review` | 所有 todo 完成后进入审查，task status → 6 |

#### 开发流程 SSE

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks/{id}/plan/stream` | SSE：生成技术方案 |
| POST | `/api/tasks/{id}/plan/chat` | 技术方案阶段对话（返回普通 JSON） |
| GET | `/api/tasks/{id}/todo/stream` | SSE：生成 todo 列表 |
| POST | `/api/tasks/{id}/todo/chat` | 任务拆解阶段对话 |
| GET | `/api/tasks/{id}/todos` | 获取 todo 列表 |
| POST | `/api/todos/{id}/execute/stream` | SSE：执行单个 todo |
| POST | `/api/todos/{id}/chat` | todo 执行后对话 |
| GET | `/api/tasks/{id}/diff` | 获取整体 git diff |
| POST | `/api/tasks/{id}/submit-mr` | 生成 commit message 并提交 MR |

---

## 四、前端设计

### 4.1 目录结构

```
src/
├── pages/
│   ├── Settings/            # 全局配置页（model / base_url / api_key / theme）
│   ├── Projects/            # 项目管理页
│   ├── Tasks/               # 任务管理页
│   └── DevFlow/             # 开发流程页
│       ├── PlanStage/       # 技术方案阶段
│       ├── TodoStage/       # 任务拆解阶段
│       ├── CodingStage/     # 编写代码阶段
│       └── ReviewStage/     # 代码审查阶段
├── components/
│   ├── StageProgress/       # 顶部阶段进度条
│   ├── ChatPanel/           # 右侧 AI 对话框（通用）
│   ├── MarkdownViewer/      # Markdown 渲染
│   ├── DiffViewer/          # 代码 diff 展示（react-diff-viewer）
│   ├── TodoList/            # Todo 列表
│   └── StreamLog/           # SSE 执行过程展示
├── hooks/
│   ├── useSSE.ts            # SSE 连接封装
│   └── useChat.ts           # 对话逻辑封装
└── api/
    └── index.ts             # API 请求封装
```

### 4.2 启动配置检查

应用启动时检查配置是否完整，未配置则强制跳转配置页，配置完成后才能进入项目：

```
用户访问 http://localhost:8000
        ↓
检查 settings 表是否有 cody_model / cody_base_url / cody_api_key
        ↓
未配置 → 强制跳转 /settings 配置页面
已配置 → 正常进入项目列表
```

**前端路由守卫：**

```typescript
// router.tsx
import { createBrowserRouter, Navigate } from "react-router-dom";

async function settingsGuard() {
  const res = await api.get("/api/settings/check");
  if (!res.data.configured) {
    return redirect("/settings");
  }
  return null;
}

const router = createBrowserRouter([
  {
    path: "/settings",
    element: <Settings />,
  },
  {
    path: "/",
    loader: settingsGuard,   // 所有其他页面进入前检查配置
    children: [
      { path: "/", element: <Projects /> },
      { path: "/tasks", element: <Tasks /> },
      { path: "/tasks/:id", element: <DevFlow /> },
    ],
  },
]);
```

**后端检查接口：**

```python
@app.get("/api/settings/check")
async def check_settings(db: Session = Depends(get_db)):
    required = ["cody_model", "cody_base_url", "cody_api_key"]
    configured = all(get_setting(db, k) for k in required)
    return {"configured": configured}
```

**配置页面字段：**

| 字段 | 说明 | 示例 |
|------|------|------|
| Model | 模型名称 | `glm-4`、`qwen-plus`、`deepseek-chat` |
| Base URL | API 地址 | `https://open.bigmodel.cn/api/paas/v4/` |
| API Key | 鉴权 Key | `sk-xxx`（保存后脱敏展示） |

### 4.3 SSE 前端封装

```typescript
// hooks/useSSE.ts
function useSSE(url: string) {
  const [logs, setLogs] = useState<StreamChunk[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const start = () => {
    const es = new EventSource(url);
    es.onmessage = (e) => {
      const chunk = JSON.parse(e.data);
      if (chunk.type === "done") {
        setSessionId(chunk.session_id);
        setDone(true);
        es.close();
      } else {
        setLogs(prev => [...prev, chunk]);
      }
    };
  };

  return { logs, sessionId, done, start };
}
```

### 4.4 开发流程页面布局

**技术方案阶段**
```
┌────────────────── 顶部：阶段进度条 ──────────────────┐
│  [技术方案] → 任务拆解 → 编写代码 → 代码审查          │
├──────────────────────────────────────────────────────┤
│                           │                          │
│   左侧：plan.md 内容       │   右侧：AI 对话框         │
│   （Markdown 渲染）        │   + SSE 执行日志          │
│                           │                          │
└───────────────────────────┴──────────────────────────┘
```

**编写代码阶段**
```
┌────────────────── 顶部：阶段进度条 ──────────────────┐
│  技术方案 → 任务拆解 → [编写代码] → 代码审查          │
├─────────────┬──────────────────┬────────────────────┤
│             │                  │                    │
│  左侧        │  中间             │  右侧              │
│  Todo 列表   │  执行日志 + diff  │  AI 对话框          │
│  （可点击执行）│  （SSE 实时推送） │                    │
│             │                  │                    │
└─────────────┴──────────────────┴────────────────────┘
```

**代码审查阶段**
```
┌────────────────── 顶部：阶段进度条 ──────────────────┐
│  技术方案 → 任务拆解 → 编写代码 → [代码审查]          │
├──────────────────────────────────────────────────────┤
│                           │                          │
│   左侧：整体 git diff       │   右侧：AI 对话框         │
│   （react-diff-viewer）    │                          │
│                           │   [生成 MR] 按钮          │
└───────────────────────────┴──────────────────────────┘
```

---

## 五、项目知识库生成流程

### 5.1 两层生成架构

知识库生成分两层执行，第一层各仓库独立分析，第二层基于第一层结果做跨仓库整合：

```
第一层（并发）：各仓库独立分析
├── 前端仓库 → frontend_structure / business_flow / component_usage
└── 后端仓库 → backend_structure
         ↓ 全部完成后
第二层（并发）：跨仓库整合分析
├── module_overview    （前端 + 后端）
├── data_entity        （前端 + 后端）
├── api_interaction    （前端 + 后端）
└── dependencies       （前端 + 后端）
         ↓ 全部完成后
最终生成 project.md（知识库索引文件）
```

### 5.2 知识点列表

| knowledge_type | 分层 | 依赖仓库 | 说明 |
|----------------|------|---------|------|
| `frontend_structure` | 第一层 | 前端仓库 | 前端目录结构、各目录职责和组织规范 |
| `backend_structure` | 第一层 | 后端仓库 | 后端目录结构、各目录职责和组织规范 |
| `business_flow` | 第一层 | 前端仓库 | 各模块业务流程，从前端交互视角梳理 |
| `component_usage` | 第一层 | 前端仓库 | 前端组件结构、复用情况、抽象的公共组件 |
| `module_overview` | 第二层 | 前端 + 后端 | 项目模块全景，前后端模块对应关系 |
| `data_entity` | 第二层 | 前端 + 后端 | 各模块数据实体、数据流、表结构 |
| `api_interaction` | 第二层 | 前端 + 后端 | 前后端接口交互关系、接口定义 |
| `dependencies` | 第二层 | 前端 + 后端 | 各模块对下游的依赖关系 |

### 5.3 生成流程

```
1. 用户保存项目配置，触发项目初始化
2. 后端为所有知识点创建 project_init_sessions 记录（status=0）
3. 并发执行第一层各知识点分析（按仓库类型分配）
4. 每个第一层知识点完成后：
   a. 生成内容写入 projects/{project_id}/skills/{knowledge_type}/SKILL.md
   b. 更新 project_init_sessions.status = 2（done）
5. 第一层全部完成后，并发执行第二层跨仓库整合分析
6. 第二层全部完成后，生成 project.md 知识库索引文件，写入 projects/{project_id}/project.md
7. 前端通过 SSE 实时展示每个知识点的生成进度和 Cody 执行日志
```

### 5.4 Skill 文件结构

```
projects/{project_id}/skills/
├── frontend_structure/
│   └── SKILL.md
├── backend_structure/
│   └── SKILL.md
├── business_flow/
│   └── SKILL.md
├── component_usage/
│   └── SKILL.md
├── module_overview/
│   └── SKILL.md
├── data_entity/
│   └── SKILL.md
├── api_interaction/
│   └── SKILL.md
├── dependencies/
│   └── SKILL.md
└── {从skill中心拉取的skill}/
    └── SKILL.md
```

任务初始化时，整个 `skills/` 目录会被同步到 `tasks/{task_id}/.cody/skills/`，Cody 自动识别并注入上下文。

### 5.5 SKILL.md 文件格式规范

所有知识库 skill 遵循 Agent Skills 开放标准（agentskills.io），每个 SKILL.md 包含 YAML frontmatter 和正文两部分。

**frontmatter 设计原则：**
- `user-invocable: false`：知识库 skill 是给 AI 读的背景知识，不是用户可执行的命令，不出现在 `/` 菜单
- `disable-model-invocation` 不设（默认 false）：允许 AI 在相关场景自动加载
- `description` 精准描述用途和触发场景：AI 靠这个判断什么时候加载

**各知识点 SKILL.md frontmatter 模板：**

#### frontend_structure
```yaml
---
name: frontend-structure
description: 前端仓库的目录结构和组织规范。新增前端文件时参考，需要了解前端目录约定、命名规范、技术栈时使用。
user-invocable: false
---

# 前端项目结构

## 技术栈
{AI 生成：框架、状态管理、路由、UI 组件库等}

## 目录结构
{AI 生成：完整目录树 + 每个目录的职责说明}

## 组织规范
{AI 生成：命名规范、模块划分方式、文件组织约定}
```

#### backend_structure
```yaml
---
name: backend-structure
description: 后端仓库的目录结构和组织规范。新增后端文件时参考，需要了解后端分层结构、命名规范、技术栈时使用。
user-invocable: false
---

# 后端项目结构

## 技术栈
{AI 生成：框架、ORM、数据库、中间件等}

## 目录结构
{AI 生成：完整目录树 + 每个目录的职责说明}

## 组织规范
{AI 生成：分层结构、命名规范、模块划分方式}
```

#### business_flow
```yaml
---
name: business-flow
description: 各业务模块的用户操作流程和业务逻辑。理解需求影响范围、分析业务逻辑时使用。
user-invocable: false
---

# 业务流程

## 模块列表
{AI 生成：各业务模块名称}

## 各模块业务流程
{AI 生成：每个模块的主要用户操作路径和业务逻辑}

## 模块间跳转关系
{AI 生成：模块间的页面跳转和数据传递}
```

#### component_usage
```yaml
---
name: component-usage
description: 前端已有公共组件列表和使用方式。开发前端功能前必读，优先复用已有组件，避免重复创建。
user-invocable: false
---

# 公共组件

## 组件列表
{AI 生成：公共组件名称、用途、props 接口}

## 使用场景
{AI 生成：各组件适用的业务场景}

## 复用规范
{AI 生成：什么情况下应该复用现有组件}
```

#### module_overview
```yaml
---
name: module-overview
description: 项目模块全景，前后端模块的对应关系。分析需求改动范围、评估影响时使用。
user-invocable: false
---

# 项目模块全景

## 模块列表
{AI 生成：所有业务模块}

## 前后端对应关系
{AI 生成：每个模块在前端和后端分别对应哪些目录和文件}

## 各模块核心功能
{AI 生成：每个模块的主要职责}
```

#### api_interaction
```yaml
---
name: api-interaction
description: 前后端接口交互清单，包含接口路径、参数和返回结构。新增或修改接口时参考，保持接口风格一致。
user-invocable: false
---

# 前后端接口清单

## 接口规范
{AI 生成：接口命名风格、统一的请求/响应格式、错误码规范}

## 各模块接口列表
{AI 生成：按模块分组，每个接口的路径、方法、主要参数、返回结构}
```

#### data_entity
```yaml
---
name: data-entity
description: 项目数据实体、数据表结构和前端类型定义。新增数据字段、设计数据结构时参考。
user-invocable: false
---

# 数据实体

## 数据表结构
{AI 生成：主要数据表名、字段、类型、约束}

## 前端类型定义
{AI 生成：主要 TypeScript interface/type 定义}

## 实体关系
{AI 生成：各数据实体之间的关联关系}
```

#### dependencies
```yaml
---
name: dependencies
description: 各模块的依赖关系，标注核心被依赖模块。评估改动影响范围时必读，避免改动影响到其他模块。
user-invocable: false
---

# 模块依赖关系

## 依赖图
{AI 生成：各模块依赖哪些其他模块或外部服务}

## 核心模块
{AI 生成：被多处依赖的关键模块，修改时需格外注意}

## 改动影响说明
{AI 生成：修改某个模块可能影响的范围}
```

### 5.6 各知识点 Prompt 模板

所有知识点 prompt 都要求 AI 按 Agent Skills 规范格式输出，包含完整的 frontmatter 和正文。

#### 第一层：frontend_structure

```
你是一个前端架构分析专家。请分析以下前端代码仓库的目录结构。

仓库信息：
- 仓库名称：{repo_name}
- 仓库介绍：{repo_description}
- 本地路径：{local_path}

请完成以下任务：
1. 扫描仓库完整目录结构
2. 分析各目录和关键文件的职责
3. 总结该前端项目的组织规范和约定（命名规范、目录约定、模块划分方式等）
4. 说明技术栈（框架、状态管理、路由、UI 组件库等）

将分析结果写入 {output_path}/SKILL.md，格式严格如下：

---
name: frontend-structure
description: 前端仓库的目录结构和组织规范。新增前端文件时参考，需要了解前端目录约定、命名规范、技术栈时使用。
user-invocable: false
---

（正文内容，包含技术栈、目录结构、组织规范，内容要具体，包含实际路径和文件名）
```

#### 第一层：backend_structure

```
你是一个后端架构分析专家。请分析以下后端代码仓库的目录结构。

仓库信息：
- 仓库名称：{repo_name}
- 仓库介绍：{repo_description}
- 本地路径：{local_path}

请完成以下任务：
1. 扫描仓库完整目录结构
2. 分析各目录和关键文件的职责
3. 总结该后端项目的组织规范和约定（分层结构、命名规范、模块划分方式等）
4. 说明技术栈（框架、ORM、数据库、中间件等）

将分析结果写入 {output_path}/SKILL.md，格式严格如下：

---
name: backend-structure
description: 后端仓库的目录结构和组织规范。新增后端文件时参考，需要了解后端分层结构、命名规范、技术栈时使用。
user-invocable: false
---

（正文内容，包含技术栈、目录结构、组织规范，内容要具体，包含实际路径和文件名）
```

#### 第一层：business_flow

```
你是一个业务分析专家。请通过分析前端代码，梳理各模块的业务流程。

仓库信息：
- 仓库名称：{repo_name}
- 仓库介绍：{repo_description}
- 本地路径：{local_path}

请完成以下任务：
1. 识别项目中的各业务模块（通常对应前端的页面或路由）
2. 对每个模块，梳理主要的用户操作流程和业务逻辑
3. 识别模块间的跳转和数据传递关系

将分析结果写入 {output_path}/SKILL.md，格式严格如下：

---
name: business-flow
description: 各业务模块的用户操作流程和业务逻辑。理解需求影响范围、分析业务逻辑时使用。
user-invocable: false
---

（正文内容）
```

#### 第一层：component_usage

```
你是一个前端组件分析专家。请分析以下前端仓库的组件使用情况。

仓库信息：
- 仓库名称：{repo_name}
- 仓库介绍：{repo_description}
- 本地路径：{local_path}

请完成以下任务：
1. 识别项目中抽象的公共组件（通常在 components/ 或 shared/ 目录下）
2. 说明每个公共组件的用途、props 接口和使用场景
3. 说明各业务模块中使用了哪些公共组件
4. 总结组件复用规范

将分析结果写入 {output_path}/SKILL.md，格式严格如下：

---
name: component-usage
description: 前端已有公共组件列表和使用方式。开发前端功能前必读，优先复用已有组件，避免重复创建。
user-invocable: false
---

（正文内容）
```

#### 第二层：module_overview

```
你是一个全栈架构分析专家。请基于已有的前后端分析结果，生成项目模块全景概览。

项目信息：
- 项目名称：{project_name}
- 项目描述：{project_description}

前端仓库：{frontend_repo_name}，路径：{frontend_local_path}
后端仓库：{backend_repo_name}，路径：{backend_local_path}

已有分析结果可参考：
- 前端结构：{frontend_structure_skill_path}/SKILL.md
- 后端结构：{backend_structure_skill_path}/SKILL.md

请完成以下任务：
1. 列出项目的所有业务模块
2. 对每个模块，说明其在前端和后端分别对应哪些目录/文件
3. 描述各模块的核心功能

将分析结果写入 {output_path}/SKILL.md，格式严格如下：

---
name: module-overview
description: 项目模块全景，前后端模块的对应关系。分析需求改动范围、评估影响时使用。
user-invocable: false
---

（正文内容）
```

#### 第二层：api_interaction

```
你是一个接口分析专家。请分析前后端的接口交互关系。

前端仓库：{frontend_repo_name}，路径：{frontend_local_path}
后端仓库：{backend_repo_name}，路径：{backend_local_path}

请完成以下任务：
1. 扫描前端的 API 调用代码（通常在 api/ 或 services/ 目录）
2. 扫描后端的路由定义
3. 梳理前后端接口的对应关系：接口路径、请求方法、主要参数、返回结构
4. 按业务模块归类整理
5. 总结接口命名风格和参数规范

将分析结果写入 {output_path}/SKILL.md，格式严格如下：

---
name: api-interaction
description: 前后端接口交互清单，包含接口路径、参数和返回结构。新增或修改接口时参考，保持接口风格一致。
user-invocable: false
---

（正文内容）
```

#### 第二层：data_entity

```
你是一个数据建模分析专家。请分析项目的数据实体和数据流。

前端仓库：{frontend_repo_name}，路径：{frontend_local_path}
后端仓库：{backend_repo_name}，路径：{backend_local_path}

请完成以下任务：
1. 从后端代码识别主要数据表和字段结构（ORM 模型或 migration 文件）
2. 从前端代码识别主要数据类型定义（TypeScript interface/type）
3. 梳理各业务模块的核心数据实体及其关系

将分析结果写入 {output_path}/SKILL.md，格式严格如下：

---
name: data-entity
description: 项目数据实体、数据表结构和前端类型定义。新增数据字段、设计数据结构时参考。
user-invocable: false
---

（正文内容）
```

#### 第二层：dependencies

```
你是一个架构分析专家。请分析项目各模块之间的依赖关系。

前端仓库：{frontend_repo_name}，路径：{frontend_local_path}
后端仓库：{backend_repo_name}，路径：{backend_local_path}

请完成以下任务：
1. 识别后端各模块对其他内部模块或外部服务的调用依赖
2. 识别前端各模块对公共服务或外部系统的依赖
3. 标注哪些模块是被多处依赖的核心模块，修改时需格外注意影响范围

将分析结果写入 {output_path}/SKILL.md，格式严格如下：

---
name: dependencies
description: 各模块的依赖关系，标注核心被依赖模块。评估改动影响范围时必读，避免改动影响到其他模块。
user-invocable: false
---

（正文内容）
```

### 5.6 project.md 索引文件

**生成时机**：第二层所有知识点生成完成后，单独跑一个 session 生成。

**生成 Prompt**：

```
请根据以下信息，生成一份项目知识库索引文档 project.md。

项目信息：
- 项目名称：{project_name}
- 项目描述：{project_description}

仓库列表：
{repos_info}  # 每个仓库的名称、类型、本地路径、介绍

已生成的知识库文件：
{skills_list}  # 每个 SKILL.md 的路径和一句话说明

要求：
1. 简要介绍项目整体情况
2. 列出所有仓库信息
3. 列出所有知识库文件的路径和用途说明
4. 格式清晰，让 AI 读完后能快速了解去哪里找什么信息

将结果写入：~/.daiflow/projects/{project_id}/project.md
```

**project.md 示例结构**：

```markdown
# 项目：ByteWorks Cost 模块

## 项目描述
ByteWorks 用工管理平台中的成本管理模块，负责仓库用工成本的计算、预测和报表展示。

## 仓库列表
| 仓库名 | 类型 | 本地路径 | 说明 |
|--------|------|---------|------|
| mmp/hc_frontend | 前端 | /Users/xxx/hc_frontend | 用工管理平台前端 Monorepo |
| mmp/hc_predict | 后端 | /Users/xxx/hc_predict | 成本计算和预测服务 |

## 知识库索引
| 文件路径 | 内容说明 |
|---------|---------|
| .cody/skills/frontend_structure/SKILL.md | 前端目录结构和组织规范，新增文件时参考 |
| .cody/skills/backend_structure/SKILL.md | 后端目录结构和组织规范，新增文件时参考 |
| .cody/skills/business_flow/SKILL.md | 各模块业务流程，理解需求时参考 |
| .cody/skills/component_usage/SKILL.md | 已有公共组件列表，开发前端时优先复用 |
| .cody/skills/module_overview/SKILL.md | 项目模块全景，定位改动范围时参考 |
| .cody/skills/api_interaction/SKILL.md | 前后端接口清单，新增接口时参考规范 |
| .cody/skills/data_entity/SKILL.md | 数据表结构和类型定义，数据建模时参考 |
| .cody/skills/dependencies/SKILL.md | 模块依赖关系，评估改动影响范围时参考 |
```

### 5.7 project.md 的使用方式

**任务初始化时**：`project.md` 和 `skills/` 目录一起同步到 `tasks/{task_id}/` 下。

**技术方案生成 prompt 中明确引导 AI 先读 project.md**：

```
开始分析前，请先阅读 project.md，了解项目整体结构和知识库索引，
然后根据需要读取对应的 SKILL.md 文件获取详细信息。
```

**Todo 执行 prompt 中同样引导**：

```
开始开发前，请先阅读 project.md 了解项目结构，
参考相关 SKILL.md 文件确保代码风格和规范与项目保持一致。
```

---

## 六、任务开发流程实现

### 6.1 任务初始化

创建任务后立即执行：

```python
async def initialize_task(task_id: str):
    task = get_task(task_id)
    project = get_project(task.project_id)

    # 1. 同步 project.md 到 task 目录
    src_md = f"~/.daiflow/projects/{task.project_id}/project.md"
    dst_md = f"~/.daiflow/tasks/{task_id}/project.md"
    copy_file(src_md, dst_md)

    # 2. 同步 skills 目录到 task 的 .cody/skills/
    src = f"~/.daiflow/projects/{task.project_id}/skills/"
    dst = f"~/.daiflow/tasks/{task_id}/.cody/skills/"
    copy_skills(src, dst)

    # 3. 切换代码分支
    for repo in project.repos:
        git_service.checkout_branch(repo.local_path, task.branch)

    update_task_status(task_id, 2)  # planning
```

### 6.2 技术方案生成

**Prompt 模板：**

```
开始分析前，请先阅读 project.md，了解项目整体结构和知识库索引，
然后根据需要读取对应的 SKILL.md 文件获取详细信息。

你是一个全栈开发工程师。请根据以下信息，生成一份详细的技术方案。

项目背景：
{project_description}

本次需求（PRD）：
{prd}

已有技术思路（可为空）：
{tech_plan}

请分析并输出以下内容：
1. 前端改动：需要新增或修改哪些页面和组件，涉及哪些文件路径
2. 后端改动：需要新增或修改哪些接口和 Service，涉及哪些文件路径
3. 数据变更：数据表或类型定义是否需要变化
4. 影响范围：会影响哪些其他模块，需要注意什么
5. 实施顺序：建议的开发顺序

将技术方案以 Markdown 格式写入 plan.md。
```

**Python 实现：**

```python
async def generate_plan_stream(task_id: str):
    task = get_task(task_id)
    project = get_project(task.project_id)

    extra_roots = [repo.local_path for repo in project.repos]
    client = build_cody_client(
        workdir=f"~/.daiflow/tasks/{task_id}",
        extra_roots=extra_roots
    )

    prompt = PLAN_PROMPT_TEMPLATE.format(
        project_description=project.description,
        prd=task.prd or "",
        tech_plan=task.tech_plan or ""
    )

    async with client:
        async for chunk in client.stream(prompt, session_id=task.plan_session_id):
            yield chunk
            if chunk.type == "done":
                update_task(task_id, plan_session_id=chunk.session_id)
```

### 6.3 任务拆解生成

**Prompt 模板：**

```
你是一个开发任务规划专家。请根据以下技术方案，拆解出有序的开发任务列表。

技术方案（plan.md）：
{plan_md_content}

拆解要求：
1. 每个 todo 是一个独立可执行的开发动作，粒度适中（不要太大也不要太小）
2. 按照合理的实施顺序排列（通常：数据层 → 后端接口 → 前端组件 → 前端页面集成）
3. 每个 todo 的 description 要足够详细，说明改哪个文件、做什么、注意什么
4. 严格按照技术方案执行，不要添加方案中没有的内容

将结果以 JSON 格式写入 todo.json：
[
  {
    "title": "简短标题，一句话说明做什么",
    "description": "详细说明：改哪个文件，具体做什么，需要注意什么"
  }
]
```

**Python 实现：**

```python
async def generate_todo_stream(task_id: str):
    task = get_task(task_id)
    plan_path = f"~/.daiflow/tasks/{task_id}/plan.md"
    plan_content = open(plan_path).read()

    extra_roots = [repo.local_path for repo in get_project(task.project_id).repos]
    client = build_cody_client(
        workdir=f"~/.daiflow/tasks/{task_id}",
        extra_roots=extra_roots
    )

    prompt = TODO_PROMPT_TEMPLATE.format(plan_md_content=plan_content)

    async with client:
        async for chunk in client.stream(prompt, session_id=task.plan_session_id):
            yield chunk
```

### 6.4 Todo 写入数据库

用户点击「执行编码」时，将 `todo.json` 批量写入 todos 表：

```python
async def start_coding(task_id: str):
    todo_path = f"~/.daiflow/tasks/{task_id}/todo.json"
    todos = json.load(open(todo_path))

    for i, todo in enumerate(todos):
        create_todo(
            task_id=task_id,
            seq=i + 1,
            title=todo["title"],
            description=todo["description"],
            status=0  # pending
        )

    update_task_status(task_id, 4)  # todo_ready，等待用户点击「执行编码」
```

### 6.5 Todo 执行

**Prompt 模板：**

```
开始开发前，请先阅读 project.md 了解项目结构，
参考相关 SKILL.md 文件确保代码风格和规范与项目保持一致。

你是一个全栈开发工程师。请完成以下开发任务。

当前任务：
- 标题：{todo_title}
- 详细描述：{todo_description}

技术方案参考（plan.md）：
{plan_md_content}

执行要求：
1. 严格按照任务描述执行，不要做超出范围的改动
2. 参考项目知识库，保持代码风格、命名规范与项目一致
3. 优先复用项目中已有的工具函数和公共组件
4. 完成后简要说明做了哪些改动
```

**Python 实现：**

```python
async def execute_todo_stream(todo_id: str):
    todo = get_todo(todo_id)
    task = get_task(todo.task_id)
    project = get_project(task.project_id)

    update_todo_status(todo_id, 1)  # running

    plan_content = open(f"~/.daiflow/tasks/{task.id}/plan.md").read()
    extra_roots = [repo.local_path for repo in project.repos]
    client = build_cody_client(
        workdir=f"~/.daiflow/tasks/{task.id}",
        extra_roots=extra_roots
    )

    prompt = TODO_EXECUTE_PROMPT_TEMPLATE.format(
        todo_title=todo.title,
        todo_description=todo.description,
        plan_md_content=plan_content
    )

    async with client:
        async for chunk in client.stream(prompt, session_id=todo.session_id):
            yield chunk
            if chunk.type == "done":
                update_todo(todo_id,
                    session_id=chunk.session_id,
                    status=2  # done
                )
```

---

## 七、打包与分发

### 7.1 构建流程

```bash
# 1. 构建前端
cd frontend && npm run build
# 产物输出到 frontend/dist/

# 2. 将前端产物复制到后端 static 目录
cp -r frontend/dist/* daiflow/static/

# 3. FastAPI 托管静态文件
# main.py 中挂载：
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# 4. 打包为可执行文件（使用 PyInstaller）
pyinstaller --onefile daiflow/cli.py
```

### 7.2 CLI 入口

```python
# cli.py
import click
import uvicorn
import webbrowser

@click.command()
def start():
    """启动 DaiFlow"""
    init_daiflow_dir()      # 初始化 ~/.daiflow/ 目录和数据库
    webbrowser.open("http://localhost:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000)

if __name__ == "__main__":
    start()
```

---

## 八、任务拆解 TODO

按照"基础设施 → 数据层 → 后端服务 → 前端页面"的顺序推进，确保每个阶段都可独立验证。

---

### 阶段一：项目初始化 & 基础设施

- [ ] 初始化项目仓库，确定前后端目录结构
- [ ] 搭建 FastAPI 后端框架，配置 uvicorn 启动
- [ ] 初始化 SQLAlchemy + SQLite，实现 `init_db()` 建表逻辑
- [ ] 创建所有数据库表：`settings`、`projects`、`project_repos`、`tasks`、`todos`、`project_init_sessions`
- [ ] 实现 `get_setting` / `set_setting` 工具函数
- [ ] 搭建 React + TypeScript 前端框架（Vite）
- [ ] 配置前端代理，开发阶段转发 `/api` 请求到后端
- [ ] 实现 CLI 入口 `daiflow start`：初始化 `~/.daiflow/` 目录、启动 FastAPI、打开浏览器
- [ ] 实现前端路由结构（react-router-dom）

---

### 阶段二：全局配置

- [ ] 后端：实现 `GET /api/settings`、`PUT /api/settings`、`GET /api/settings/check` 接口
- [ ] 前端：实现配置页面 `/settings`，包含 model / base_url / api_key 三个输入项，api_key 脱敏展示；包含外观设置（深色/浅色主题切换），主题配置保存到 settings 表并同步到前端
- [ ] 前端：实现路由守卫，启动时检查配置，未配置强制跳转 `/settings`
- [ ] 验证：配置完成后可正常进入项目列表页

---

### 阶段三：项目管理

- [ ] 后端：实现项目 CRUD 接口（`projects` + `project_repos`）
- [ ] 前端：实现项目列表页，展示所有项目
- [ ] 前端：实现创建/编辑项目表单，支持多仓库配置（仓库名、git_url、local_path、类型、介绍）
- [ ] 前端：实现 skill 名称列表输入
- [ ] 验证：项目可正常增删改查，仓库配置可正常保存

---

### 阶段四：项目知识库生成

- [ ] 后端：封装 `build_cody_client(workdir, extra_roots)`，从 settings 读取配置
- [ ] 后端：实现 `skill_service`，支持 mock 从 Skill 中心拉取 skill 文件
- [ ] 后端：实现第一层知识点生成（`frontend_structure`、`backend_structure`、`business_flow`、`component_usage`），每个知识点独立 session，并发执行
- [ ] 后端：实现第二层知识点生成（`module_overview`、`api_interaction`、`data_entity`、`dependencies`），第一层完成后触发
- [ ] 后端：实现 `project.md` 索引文件生成，第二层完成后触发
- [ ] 后端：实现 `POST /api/projects/{id}/init` 触发初始化，`GET /api/projects/{id}/init/stream` SSE 推送进度
- [ ] 前端：实现项目初始化进度页面，展示每个知识点的生成状态和 Cody 执行日志（StreamLog 组件）
- [ ] 验证：项目初始化后 `~/.daiflow/projects/{id}/skills/` 下有完整 SKILL.md 文件，`project.md` 生成正确

---

### 阶段五：任务管理

- [ ] 后端：实现任务 CRUD 接口
- [ ] 后端：实现任务初始化逻辑：同步 skill 到 `tasks/{id}/.cody/skills/`，同步 `project.md`，切换各仓库代码分支
- [ ] 后端：实现 `git_service`：`checkout_branch`、`get_diff`、`commit`、`push`
- [ ] 前端：实现任务列表页
- [ ] 前端：实现创建任务表单（任务名、关联项目、描述、分支、PRD、技术方案）
- [ ] 验证：任务创建后 skill 同步正确，代码分支切换成功

---

### 阶段六：开发流程 — 技术方案阶段

- [ ] 后端：实现技术方案生成 prompt 模板 `PLAN_PROMPT_TEMPLATE`
- [ ] 后端：实现 `GET /api/tasks/{id}/plan/stream` SSE 接口，触发 Cody 生成 `plan.md`
- [ ] 后端：实现 `POST /api/tasks/{id}/plan/chat` 对话接口，复用 `plan_session_id`
- [ ] 后端：实现 `POST /api/tasks/{id}/lock-plan` 锁定方案，更新 task status = 3
- [ ] 前端：实现技术方案阶段页面（左侧 Markdown 展示 plan.md，右侧 AI 对话 + SSE 执行日志）
- [ ] 前端：实现 `useSSE` hook
- [ ] 前端：实现 `ChatPanel` 通用对话组件
- [ ] 前端：实现顶部阶段进度条组件 `StageProgress`
- [ ] 验证：AI 生成 plan.md，人工对话可修改，锁定后进入下一阶段

---

### 阶段七：开发流程 — 任务拆解阶段

- [ ] 后端：实现任务拆解 prompt 模板 `TODO_PROMPT_TEMPLATE`
- [ ] 后端：实现 `GET /api/tasks/{id}/todo/stream` SSE 接口，触发 Cody 生成 `todo.json`
- [ ] 后端：实现 `POST /api/tasks/{id}/todo/chat` 对话接口
- [ ] 后端：实现 `POST /api/tasks/{id}/start-coding`：将 `todo.json` 批量写入 todos 表，task status = 4（todo_ready）；用户点击「执行编码」按钮后 task status 变为 5（coding）
- [ ] 前端：实现任务拆解阶段页面（左侧 todo 列表，右侧 AI 对话）
- [ ] 验证：AI 生成 todo.json，确认后 todos 写入 db，进入编码阶段

---

### 阶段八：开发流程 — 编写代码阶段

- [ ] 后端：实现 todo 执行 prompt 模板 `TODO_EXECUTE_PROMPT_TEMPLATE`
- [ ] 后端：实现 `POST /api/todos/{id}/execute/stream` SSE 接口，执行单个 todo
- [ ] 后端：实现 `POST /api/todos/{id}/chat` 对话接口，复用该 todo 的 `session_id`
- [ ] 后端：实现 `GET /api/tasks/{id}/todos` 获取 todo 列表及状态
- [ ] 前端：实现编写代码阶段页面（左侧 todo 列表含执行按钮，中间执行日志 + diff，右侧对话）
- [ ] 前端：实现 `DiffViewer` 组件（基于 react-diff-viewer）
- [ ] 前端：实现 `StreamLog` 组件，展示 tool_call / tool_result / text_delta 事件
- [ ] 验证：逐个执行 todo，代码改动可见，对话可补充修改

---

### 阶段九：开发流程 — 代码审查 & 提交

- [ ] 后端：实现 `POST /api/tasks/{id}/start-review`：task status = 6（reviewing）
- [ ] 后端：实现 `GET /api/tasks/{id}/diff`，调用 `git diff` 返回所有仓库的变更内容
- [ ] 后端：实现 `POST /api/tasks/{id}/submit-mr`：AI 生成 commit message，执行 git commit + push，task status = 7（done）
- [ ] 前端：实现代码审查阶段页面（左侧整体 diff 视图，右侧对话框，生成 MR 按钮）
- [ ] 验证：diff 展示正确，commit message 合理，push 成功

---

### 阶段十：集成测试 & 打包

- [ ] 端到端走通完整流程：配置 → 创建项目 → 知识库生成 → 创建任务 → 技术方案 → 任务拆解 → 编码 → 提交
- [ ] 构建前端产物，FastAPI 静态托管，验证单服务访问正常
- [ ] PyInstaller 打包为本地可执行文件，验证 `daiflow start` 可正常启动
