# DaiFlow Workflow 抽象

> 版本：v0.1 MVP
> 更新时间：2026-03-15

---

## 一、概述

DaiFlow 将软件开发流程抽象为一个 **4 阶段线性状态机**，每个任务（Task）从创建到完成依次经历：

```
技术方案 → 任务拆解 → 代码实现 → 代码审查
```

所有阶段切换均由**用户主动触发**（按钮点击），AI 执行过程在后台异步完成。状态机保证流程不可跳跃、不可回退（除了方案阶段可重新生成）。

---

## 二、状态定义

### 2.1 TaskStatus（8 个状态）

定义在 `daiflow/models.py`：

```python
class TaskStatus(IntEnum):
    CREATED      = 0   # 任务创建完毕
    INITIALIZING = 1   # 拉取代码 + 同步技能
    PLANNING     = 2   # AI 生成技术方案
    PLAN_LOCKED  = 3   # 方案锁定，准备生成 Todo
    TODO_READY   = 4   # Todo 生成完毕
    CODING       = 5   # 逐个执行 Todo（AI 编码）
    REVIEWING    = 6   # 用户审查 Diff
    DONE         = 7   # 任务完成
```

### 2.2 TodoStatus（5 个状态）

```python
class TodoStatus(IntEnum):
    PENDING  = 0   # 等待执行
    RUNNING  = 1   # 执行中
    DONE     = 2   # 完成
    FAILED   = 3   # 失败
    SKIPPED  = 4   # 跳过
```

### 2.3 状态转换图

```
CREATED
  │ POST /api/tasks（自动触发后台 init）
  ▼
INITIALIZING
  │ POST /api/tasks/{id}/confirm-init（用户确认）
  ▼
PLANNING ◄──── POST /api/tasks/{id}/plan（重新生成）
  │ POST /api/tasks/{id}/lock-plan（锁定方案）
  ▼
PLAN_LOCKED
  │ 后台自动生成 Todo → 完成后自动切换
  ▼
TODO_READY
  │ POST /api/tasks/{id}/start-coding（用户进入编码）
  ▼
CODING
  │ POST /api/tasks/{id}/start-review（所有 Todo 完成/跳过后）
  ▼
REVIEWING
  │ POST /api/tasks/{id}/submit-mr（提交 MR）
  ▼
DONE
```

---

## 三、状态机实现

### 3.1 transitions 库

DaiFlow 使用 Python `transitions` 库的异步扩展实现状态机，核心代码在 `daiflow/workflow/` 目录：

| 文件 | 职责 |
|------|------|
| `task_machine.py` | Task 状态机（8 状态，6 个 transition） |
| `todo_machine.py` | Todo 状态机（5 状态，含重试和跳过） |
| `orchestrator.py` | 状态转换编排器（统一入口） |

### 3.2 TaskWorkflow

```python
class TaskWorkflow:
    machine = AsyncMachine(
        states=[TaskStatus],
        transitions=[
            # trigger           source         dest           conditions
            ("plan_ready",      INITIALIZING,  PLANNING),
            ("lock_plan",       PLANNING,      PLAN_LOCKED),
            ("todos_ready",     PLAN_LOCKED,   TODO_READY,    ["_has_todos"]),
            ("start_coding",    TODO_READY,    CODING,        ["_has_todos"]),
            ("start_review",    CODING,        REVIEWING,     ["_all_todos_done"]),
            ("finish",          REVIEWING,     DONE),
        ],
        after_state_change="_sync_status",  # 自动同步 DB
    )
```

**关键 Guard 条件：**

- `_has_todos()`：Task 必须有至少一个 Todo 才能进入编码阶段
- `_all_todos_done()`：所有 Todo 必须为 DONE 或 SKIPPED 才能进入审查阶段

### 3.3 TodoWorkflow

```
PENDING ──── start ───→ RUNNING ──── complete ───→ DONE
                           │
                         fail
                           │
                           ▼
                        FAILED ──── retry ───→ RUNNING

PENDING / FAILED ──── skip ───→ SKIPPED
```

**顺序约束：** `_prev_todo_completed()` 确保 Todo 必须按 `seq` 顺序执行——前一个 Todo 必须为 DONE 或 SKIPPED 才能执行下一个。

### 3.4 Orchestrator（编排器）

`daiflow/workflow/orchestrator.py` 将状态转换集中管理，保持 Router 层薄而简洁：

```python
# 锁定方案 + 触发 Todo 生成
async def lock_plan_and_generate_todos(db, task_id)

# 进入编码阶段（含 Todo 加载兜底）
async def start_coding_stage(db, task_id)

# 进入审查阶段 + 创建 Session 记录
async def start_review_stage(db, task_id)

# 完成任务
async def finish_task(db, task_id)
```

所有函数在状态机拒绝转换时抛出 `TransitionError`。

---

## 四、各阶段详解

### 4.1 初始化阶段（CREATED → INITIALIZING）

**触发方式：** 创建任务时自动启动后台任务

**执行内容：**
1. 从项目仓库拉取/复制代码到任务工作目录
2. 同步项目技能文件到任务目录

**相关 Session：**
- `task:{task_id}:init:fetch_code`
- `task:{task_id}:init:sync_skills`
- `task:init:{task_id}`（聚合总线）

### 4.2 技术方案阶段（PLANNING）

**触发方式：** 用户点击「确认初始化」→ 自动启动 AI 生成方案

**执行内容：**
- AI 读取任务描述 + 项目上下文，生成 `plan.md`
- 方案内容写入 `task.tech_plan` 字段
- 用户可通过 Chat 与 AI 讨论并修改方案
- 可重新生成（`POST /api/tasks/{id}/plan`）

**Session ID：** `task:{task_id}:plan`

**产物检测：** 检测 `plan.md` 文件写入 → 推送 `plan_updated` 事件

### 4.3 任务拆解阶段（PLAN_LOCKED → TODO_READY）

**触发方式：** 用户锁定方案后自动触发

**执行内容：**
- AI 基于方案生成 `todo.json`（有序数组）
- 解析 JSON 并同步到数据库 `todos` 表
- 复用 Plan 阶段的 Cody Session（上下文连续性）

**Session ID：** `task:{task_id}:todo_split`

**Cody Session 策略：** 复用 Plan 的 `cody_session_id`，AI 能"记住"之前的方案讨论

### 4.4 代码实现阶段（CODING）

**触发方式：** 用户手动进入 + 逐个执行 Todo

**执行内容：**
- 每个 Todo 独立创建 Cody Session
- AI 读取 `plan.md` 作为共享上下文
- 检测文件写入 → 推送 `code_updated` 事件
- 用户可通过 Chat 与 AI 讨论当前 Todo 实现
- 支持 Skip 跳过 Todo

**Session ID：** `task:{task_id}:todo:{todo_id}`

**顺序执行：** 后端强制按 `seq` 顺序执行，前一个 Todo 必须完成/跳过

### 4.5 代码审查阶段（REVIEWING → DONE）

**触发方式：** 所有 Todo 完成/跳过后，用户进入审查

**执行内容：**
1. 聚合所有仓库的 Diff
2. AI 可辅助生成 Commit Message
3. 用户审查 Diff → 确认提交
4. 提交流程：先 Commit 所有仓库 → 再 Push 到远程
5. 记录 MR 信息到 `task.mr_info`

**API 端点：**
- `GET /api/tasks/{id}/diff` — 获取聚合 Diff
- `POST /api/tasks/{id}/generate-commit-message` — AI 生成提交信息
- `POST /api/tasks/{id}/submit-mr` — 提交并推送

---

## 五、API 端点总览

| 端点 | 阶段 | 触发方式 | 说明 |
|------|------|---------|------|
| `POST /api/tasks` | 创建 | 用户 | 创建任务 + 后台初始化 |
| `POST /api/tasks/{id}/confirm-init` | 初始化 → 方案 | 用户 | 确认初始化完成 |
| `POST /api/tasks/{id}/plan` | 方案 | 用户 | （重新）生成方案 |
| `POST /api/tasks/{id}/lock-plan` | 方案 → 拆解 | 用户 | 锁定方案 + 触发 Todo 生成 |
| `POST /api/tasks/{id}/todo` | 拆解 | 用户 | 重新生成 Todo |
| `POST /api/tasks/{id}/start-coding` | 就绪 → 编码 | 用户 | 进入编码阶段 |
| `POST /api/todos/{id}/execute` | 编码 | 用户 | 执行单个 Todo |
| `POST /api/todos/{id}/skip` | 编码 | 用户 | 跳过 Todo |
| `POST /api/tasks/{id}/start-review` | 编码 → 审查 | 用户 | 进入审查（需所有 Todo 完成） |
| `GET /api/tasks/{id}/diff` | 审查 | 用户 | 获取聚合 Diff |
| `POST /api/tasks/{id}/generate-commit-message` | 审查 | 用户 | AI 生成提交信息 |
| `POST /api/tasks/{id}/submit-mr` | 审查 → 完成 | 用户 | 提交 MR |

---

## 六、阶段间数据传递

| 阶段 | 输入 | 输出 | Cody Session 策略 |
|------|------|------|------------------|
| 技术方案 | 任务描述 + 项目上下文 | `task.tech_plan` + `plan.md` | 独立 Cody Session |
| 任务拆解 | `plan.md`（上下文连续） | `todo.json` → `todos` 表 | 复用 Plan 的 Session |
| 代码实现 | `todo.description` + `plan.md` | 代码文件变更 | 每个 Todo 独立 Session |
| 代码审查 | 仓库 Diff | Commit + Push | 独立 Cody Session |

---

## 七、关键设计决策

### 7.1 用户主动控制

所有阶段切换由用户触发，而非自动流转。这确保用户在每个关键节点都有审查和决策权。

### 7.2 后台异步执行

AI 执行（方案生成、Todo 生成、代码实现）均在后台运行，通过 WebSocket 实时推送进度，不阻塞用户操作。

### 7.3 状态机 Guard

通过 `_has_todos` 和 `_all_todos_done` 条件约束，确保只有在满足前置条件时才能进入下一阶段，避免无效操作。

### 7.4 Todo 顺序执行

后端强制 Todo 按序号（`seq`）顺序执行。这保证后续 Todo 能看到前面 Todo 的代码变更，避免冲突。

### 7.5 错误恢复

- 失败的 Todo 可重试（`FAILED → RUNNING`）
- 阻塞的 Todo 可跳过（`PENDING/FAILED → SKIPPED`）
- 中断的 Session 在重启后标记为 FAILED，支持重试

---

## 八、关键文件索引

| 文件 | 职责 |
|------|------|
| `daiflow/models.py` | Task/Todo 模型 + 状态枚举 |
| `daiflow/workflow/task_machine.py` | Task 状态机定义 |
| `daiflow/workflow/todo_machine.py` | Todo 状态机定义 |
| `daiflow/workflow/orchestrator.py` | 状态转换编排 |
| `daiflow/routers/tasks.py` | Task CRUD + 阶段切换 API |
| `daiflow/routers/todos.py` | Todo 执行 / 跳过 API |
| `daiflow/services/task_service.py` | 后台任务执行 |
| `daiflow/services/review_service.py` | Diff 聚合 / Commit / Push |
| `daiflow/agent_executor.py` | 统一 Agent 执行入口 |
| `daiflow/session_ids.py` | Session ID 构造 |
