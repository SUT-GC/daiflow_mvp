# Task & Todo Workflow 改造方案

> 版本：v0.1 草案
> 更新时间：2026-03-13

---

## 一、现状问题

### 1.1 表设计问题

**Task 表既是业务表又是状态机：**

```
tasks 表：
  name, description, prd, tech_plan     ← 业务数据
  status (0~7)                          ← 流程状态（8 个阶段塞在一个字段里）
  plan_cody_session_id                  ← plan 阶段的运行时信息
  review_cody_session_id                ← review 阶段的运行时信息
  mr_info                               ← submit 阶段的结果
```

- 一个 `status` 字段承载 8 个阶段，但每个阶段"需要什么、产出什么、谁来执行"全靠代码里散落的逻辑
- `plan_cody_session_id`、`review_cody_session_id` 是流程运行时信息，不应该放在业务表里
- Session 和 Task 的关系靠拼字符串（`task:{id}:plan`）维护，不是外键

**Todo 表缺少顺序执行的后端保障：**

```
todos 表：
  seq = 1, 2, 3...     ← 只是排序号，后端不校验前置依赖
  status                ← 没有"前一个完成了吗"的守卫
```

- 顺序执行完全靠前端 UI 控制，后端不强制
- 没有自动流转能力（todo 1 完成后不能自动开始 todo 2）

### 1.2 代码组织问题

状态流转逻辑散落在三层：

| 层 | 做了什么 | 位置 |
|----|---------|------|
| `routers/tasks.py` | `VALID_TRANSITIONS` 字典 + `_check_transition()` 校验 | 第 29~47 行 |
| `routers/tasks.py` | `bg.add_task(generate_todos, ...)` 手动触发下一步 | 各 route handler |
| `services/task_service.py` | `task.status = TaskStatus.XXX` 直接赋值（10+ 处） | 散落各函数 |

**后果：**
- 想加自动流转很难 —— 得在 service 末尾加逻辑，还得和 router 的校验对齐
- 想看全流程 —— 得同时读 router + service + session_runner 三个文件
- 想加新阶段 —— 得改枚举、改字典、改 router、改 service，至少 4 处

---

## 二、改造目标

1. **流程定义集中化** —— 一处定义全部状态 + 转换 + 回调，一目了然
2. **自动流转** —— plan 完成 → 自动 lock → 自动拆 todo → 自动进 coding → 自动执行 todo 链
3. **后端守卫** —— todo 顺序执行由后端强制，不依赖前端
4. **表结构归位** —— 业务数据和流程状态分离，关系用外键而非拼字符串

---

## 三、技术方案

### 3.1 引入 transitions 库

```bash
pip install transitions
```

使用 `transitions.extensions.asyncio.AsyncMachine`，原因：
- 原生 async 支持，与 FastAPI 无缝配合
- `conditions` 守卫 —— 状态转换前自动校验条件
- `before` / `after` 回调 —— 转换前后自动触发逻辑
- 非法转换自动抛 `MachineError`，不需要手写校验
- 零外部依赖，轻量

### 3.2 表结构变更

#### 3.2.1 tasks 表 —— 只保留业务数据

```
tasks 表（改后）：
  id, name, project_id, description, branch, prd   ← 业务数据不变
  tech_plan                                          ← 保留（plan 阶段产出）
  status                                             ← 保留（当前阶段，由状态机维护）
  mr_info                                            ← 保留（submit 阶段产出）
  created_at, updated_at

  删除：plan_cody_session_id                         ← 移到 sessions 表
  删除：review_cody_session_id                       ← 移到 sessions 表
```

> **说明**：`status` 字段保留，但不再由业务代码直接赋值，改由 transitions 状态机维护。`plan_cody_session_id` 和 `review_cody_session_id` 本质是 Session 运行时信息，移到 sessions 表通过外键关联。

#### 3.2.2 sessions 表 —— 增加 task_id 外键

```
sessions 表（改后）：
  session_id         ← 主键不变（如 task:abc:plan）
  task_id            ← 新增外键 → tasks.id（取代拼字符串查找）
  cody_session_id    ← 不变
  type               ← 不变（plan / todo_split / todo_exec / review）
  ref_id             ← 不变
  layer              ← 不变（init 专用）
  status, error      ← 不变
  started_at, finished_at, created_at
```

> **收益**：查 task 的 plan session 不再需要拼 `task:{id}:plan`，直接 `WHERE task_id = ? AND type = 'plan'`。`plan_cody_session_id` 通过 `sessions.cody_session_id WHERE type='plan'` 获取。

#### 3.2.3 todos 表 —— 无结构变更

```
todos 表（不变）：
  id, task_id, seq, title, description
  status, cody_session_id
  commit_before, commit_after, result
  created_at, updated_at
```

> **说明**：表结构不变，顺序执行的守卫由 transitions 的 `conditions` 在运行时校验。通过查询 `seq - 1` 的 todo status 实现。

### 3.3 Task 状态机定义

```python
# daiflow/workflow/task_machine.py

from transitions.extensions.asyncio import AsyncMachine


class TaskWorkflow:
    """Task 四阶段工作流状态机。

    状态图：
    created → initializing → planning ⇄ (regenerate)
                                ↓
                           plan_locked → todo_ready → coding → reviewing → done
                                                        ↑         |
                                                        └─ (retry) ┘
    """

    states = [
        'created',
        'initializing',
        'planning',
        'plan_locked',
        'todo_ready',
        'coding',
        'reviewing',
        'done',
    ]

    transitions = [
        # 初始化阶段
        {
            'trigger': 'initialize',
            'source': 'created',
            'dest': 'initializing',
            'after': '_on_initializing',
        },
        {
            'trigger': 'plan_ready',
            'source': 'initializing',
            'dest': 'planning',
        },

        # Plan 阶段
        {
            'trigger': 'lock_plan',
            'source': 'planning',
            'dest': 'plan_locked',
            'after': '_on_plan_locked',       # 自动触发 todo 拆解
        },
        {
            'trigger': 'regenerate_plan',
            'source': 'planning',
            'dest': 'planning',               # 自环：重新生成 plan
            'after': '_on_regenerate_plan',
        },

        # Todo 拆解阶段
        {
            'trigger': 'todos_ready',
            'source': 'plan_locked',
            'dest': 'todo_ready',
        },

        # Coding 阶段
        {
            'trigger': 'start_coding',
            'source': 'todo_ready',
            'dest': 'coding',
            'conditions': '_has_todos',       # 守卫：必须有 todo 才能开始
            'after': '_on_coding_start',      # 自动执行第一个 todo
        },

        # Review 阶段
        {
            'trigger': 'start_review',
            'source': 'coding',
            'dest': 'reviewing',
            'conditions': '_all_todos_done',  # 守卫：所有 todo 必须完成
        },

        # 完成
        {
            'trigger': 'finish',
            'source': 'reviewing',
            'dest': 'done',
        },

        # 失败回滚
        {
            'trigger': 'reset',
            'source': ['initializing', 'planning'],
            'dest': 'created',
        },
    ]

    def __init__(self, task_id: str, current_status: str, db_session):
        self.task_id = task_id
        self.db = db_session
        self.machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=current_status,
            send_event=True,          # 回调接收 EventData 对象
        )

    # ── 守卫条件 ──

    async def _has_todos(self, event):
        """检查 task 下是否存在 todo。"""
        result = await self.db.execute(
            select(Todo).where(Todo.task_id == self.task_id).limit(1)
        )
        return result.scalar() is not None

    async def _all_todos_done(self, event):
        """检查所有 todo 是否完成（done 或 skipped）。"""
        result = await self.db.execute(
            select(Todo).where(
                Todo.task_id == self.task_id,
                Todo.status.notin_([TodoStatus.DONE, TodoStatus.SKIPPED])
            ).limit(1)
        )
        return result.scalar() is None

    # ── 自动回调（after）──

    async def _on_initializing(self, event):
        """初始化：同步 skills、checkout 分支、生成 plan。"""
        await _persist_status(self.db, self.task_id, 'initializing')
        # 实际执行逻辑委托给 task_service.init_task()

    async def _on_plan_locked(self, event):
        """Plan 锁定后自动触发 todo 拆解。"""
        await _persist_status(self.db, self.task_id, 'plan_locked')
        await generate_todos(self.task_id)
        await self.todos_ready()  # 链式触发：拆解完 → todo_ready

    async def _on_regenerate_plan(self, event):
        """重新生成 plan（自环，不改状态值）。"""
        await generate_plan(self.task_id)

    async def _on_coding_start(self, event):
        """进入 coding 后自动执行第一个 todo。"""
        await _persist_status(self.db, self.task_id, 'coding')
        await execute_next_todo(self.task_id)
```

### 3.4 Todo 顺序执行守卫

```python
# daiflow/workflow/todo_machine.py

from transitions.extensions.asyncio import AsyncMachine


class TodoWorkflow:
    """单个 Todo 的执行状态机。

    状态图：
    pending → running → done
                 ↓       ↑
               failed → (retry)

    pending → skipped
    """

    states = ['pending', 'running', 'done', 'failed', 'skipped']

    transitions = [
        {
            'trigger': 'execute',
            'source': 'pending',
            'dest': 'running',
            'conditions': '_prev_todo_completed',   # 守卫：前一个 todo 必须完成
        },
        {
            'trigger': 'complete',
            'source': 'running',
            'dest': 'done',
            'after': '_on_done',                    # 自动触发下一个 todo
        },
        {
            'trigger': 'fail',
            'source': 'running',
            'dest': 'failed',
        },
        {
            'trigger': 'retry',
            'source': 'failed',
            'dest': 'running',
            'conditions': '_prev_todo_completed',
        },
        {
            'trigger': 'skip',
            'source': 'pending',
            'dest': 'skipped',
            'after': '_on_done',                    # skip 也触发下一个
        },
    ]

    def __init__(self, todo_id: str, task_id: str, seq: int, current_status: str, db_session):
        self.todo_id = todo_id
        self.task_id = task_id
        self.seq = seq
        self.db = db_session
        self.machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=current_status,
            send_event=True,
        )

    async def _prev_todo_completed(self, event):
        """守卫：seq=1 直接通过；seq>1 需要前一个 todo 为 done 或 skipped。"""
        if self.seq <= 1:
            return True
        result = await self.db.execute(
            select(Todo).where(
                Todo.task_id == self.task_id,
                Todo.seq == self.seq - 1,
            )
        )
        prev = result.scalar()
        return prev is not None and prev.status in (TodoStatus.DONE, TodoStatus.SKIPPED)

    async def _on_done(self, event):
        """当前 todo 完成后，自动触发下一个 todo 执行。"""
        await _persist_todo_status(self.db, self.todo_id, self.state)

        # 查找下一个 pending 的 todo
        result = await self.db.execute(
            select(Todo).where(
                Todo.task_id == self.task_id,
                Todo.seq == self.seq + 1,
                Todo.status == TodoStatus.PENDING,
            )
        )
        next_todo = result.scalar()
        if next_todo:
            await execute_next_todo(self.task_id)   # 链式触发
        else:
            # 所有 todo 执行完毕，检查是否可以自动进入 review
            # 由上层 TaskWorkflow 决定是否 auto_review
            pass
```

### 3.5 Router 层改造

改造前后对比：

```python
# ── 改造前（routers/tasks.py）──

@router.post("/{task_id}/lock-plan")
async def lock_plan_route(task_id: str, bg: BackgroundTasks, db=Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404)
    _check_transition(task, TaskStatus.PLAN_LOCKED)      # 手写校验
    task.status = TaskStatus.PLAN_LOCKED                  # 手动改状态
    await db.commit()
    bg.add_task(generate_todos, task_id)                  # 手动触发下一步
    return _task_to_dict(task)


# ── 改造后 ──

@router.post("/{task_id}/lock-plan")
async def lock_plan_route(task_id: str, bg: BackgroundTasks, db=Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404)
    wf = TaskWorkflow(task.id, TaskStatus(task.status).name, db)
    try:
        await wf.lock_plan()          # 校验 + 改状态 + 触发 todo 拆解，全自动
    except MachineError:
        raise HTTPException(400, f"Cannot lock plan in {TaskStatus(task.status).name} state")
    await db.commit()
    return _task_to_dict(task)
```

### 3.6 需要删除的旧代码

| 文件 | 删除内容 |
|------|---------|
| `routers/tasks.py` | `VALID_TRANSITIONS` 字典（第 29~37 行） |
| `routers/tasks.py` | `_check_transition()` 函数（第 40~47 行） |
| `routers/tasks.py` | 各 route 中的 `_check_transition()` 调用 |
| `routers/tasks.py` | 各 route 中的 `bg.add_task(...)` 手动触发 |
| `services/task_service.py` | 10+ 处 `task.status = TaskStatus.XXX` 直接赋值 |
| `models.py` | `Task.plan_cody_session_id` 字段 |
| `models.py` | `Task.review_cody_session_id` 字段 |

---

## 四、文件结构

```
daiflow/
  workflow/                    ← 新增目录
    __init__.py
    task_machine.py            ← TaskWorkflow 状态机
    todo_machine.py            ← TodoWorkflow 状态机
    helpers.py                 ← _persist_status, execute_next_todo 等工具函数
  models.py                   ← 删除 plan/review_cody_session_id，sessions 加 task_id
  routers/tasks.py             ← 精简，用 TaskWorkflow 替换手写逻辑
  routers/todos.py             ← 精简，用 TodoWorkflow 替换手写逻辑
  services/task_service.py     ← 保留纯业务逻辑（generate_plan, generate_todos, execute_todo）
                                  删除所有 status 赋值代码
```

---

## 五、数据库迁移

```bash
# 需要一个 Alembic migration
alembic revision --autogenerate -m "workflow refactor: sessions add task_id, tasks drop cody session ids"
```

迁移内容：
1. `sessions` 表新增 `task_id` 列（nullable，因为 init 类 session 没有 task_id）
2. `tasks` 表删除 `plan_cody_session_id` 和 `review_cody_session_id` 列
3. 数据迁移：从现有 session_id 字符串（如 `task:abc:plan`）中解析 task_id 回填

---

## 六、改造范围与影响

### 6.1 后端改动

| 模块 | 改动程度 | 说明 |
|------|---------|------|
| `models.py` | 小改 | 删 2 字段，sessions 加 1 字段 |
| `routers/tasks.py` | 中改 | 删除校验逻辑，改用 TaskWorkflow |
| `routers/todos.py` | 小改 | 改用 TodoWorkflow |
| `services/task_service.py` | 中改 | 删除 status 赋值，保留纯业务逻辑 |
| `workflow/` | 新增 | 3 个文件，约 200 行 |
| `session_runner.py` | 不动 | SessionRunner 本身不涉及状态流转 |
| `ws_manager.py` | 不动 | WebSocket 推送逻辑不变 |

### 6.2 前端影响

- **无 API 变更** —— 路由路径和请求/响应格式不变
- **状态值不变** —— TaskStatus、TodoStatus 的数值含义不变
- **行为变化** —— 部分原来需要手动点按钮触发的步骤会自动流转，前端需要通过 WebSocket 事件感知状态变化并更新 UI

### 6.3 测试改动

- `tests/test_api_tasks.py` —— 需要适配新的自动流转行为
- 新增 `tests/test_task_workflow.py` —— 单独测试状态机转换逻辑
- 新增 `tests/test_todo_workflow.py` —— 单独测试 todo 顺序执行守卫

---

## 七、待讨论

1. **自动流转的粒度** —— lock_plan 后是否一路自动到 coding？还是在 todo_ready 暂停等用户确认？
2. **Todo 自动执行** —— todo 1 完成后自动开始 todo 2？还是保持手动触发（但加后端守卫）？
3. **Review 自动触发** —— 所有 todo 完成后是否自动进入 review？
4. **错误恢复策略** —— todo 执行失败后是阻断后续还是允许跳过继续？
