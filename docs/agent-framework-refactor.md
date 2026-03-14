# DaiFlow Agent 统一框架改进方案

## 一、现状分析

### 1.1 当前 Agent 类型一览

DaiFlow 目前有 **6 种 Agent 类型**，按执行方式分为两类：

**SessionRunner 驱动（AI 流式执行）：**

| Agent 类型 | Session ID 模式 | 是否支持 Chat | Cody Session 策略 | 触发方式 |
|---|---|---|---|---|
| init（知识生成） | `init:{project_id}:{knowledge_type}` | ❌ | 每个独立 | 用户点击"初始化项目" |
| plan（技术方案） | `task:{task_id}:plan` | ✅ | 新建 | 用户点击"生成方案" |
| todo_split（任务拆解） | `task:{task_id}:todo_split` | ✅ | 复用 plan 的 cody_session | 用户点击"锁定方案" |
| todo_exec（代码执行） | `task:{task_id}:todo:{todo_id}` | ✅ | 每个独立 | 用户点击"执行" |

**非 SessionRunner 类型：**

| Agent 类型 | Session ID 模式 | 执行方式 | 触发方式 |
|---|---|---|---|
| task_init（任务初始化） | `task:{task_id}:init:*` | `run_simple_task()`（非 AI） | 创建任务时自动 |
| review（代码审查） | `task:{task_id}:review` | 直接调用 Cody client（不走 SessionRunner） | 用户点击"开始审查" |

> **注意：** review 阶段的 `generate_commit_message()` 直接使用 Cody client，不经过 SessionRunner 流式执行。但 review 的 **chat** 功能仍走 `run_stage_chat()` 路径。task_init 用 `run_simple_task()` 执行资源准备（如 skill fetch），不涉及 AI 调用。

**数量关系：**
- 一次项目初始化 = 11~12 个 init agent（4 层，层内并发）
- 一个开发任务 = 1 task_init + 1 plan + 1 todo_split + N todo_exec + 1 review = N+4 个 agent
- SessionRunner 驱动的 agent 执行模式完全一致：Cody SDK 流式输出 → .jsonl 日志 → WebSocket 推送 → DB 状态更新

### 1.2 当前架构的统一之处（保持不变）

以下部分已经做得很好，重构时保持不变：

- **SessionRunner** — 统一的 Cody 执行器，所有 agent 共用
- **WSManager** — 内存 pub/sub，channel 机制清晰
- **三层持久化** — DB 状态 + .jsonl 日志 + WebSocket 实时推送
- **session_ids.py** — 统一的 session ID 命名规则
- **WebSocketClient** — 前端统一 WS 客户端，支持订阅和双向聊天
- **StageLayout + ChatPanel** — 前端统一布局和对话组件

### 1.3 当前存在的问题

#### 问题 1：每个 stage 重复实现相同模式（后端）

`task_service.py` 中 `generate_plan()`、`generate_todos()`、`execute_todo()` 三个函数的代码结构几乎一样：

```python
# 三个函数都是这个模式：
async def generate_xxx(id: str):
    db = get_background_db()
    entity = await db.get(Model, id)                    # 1. 取实体
    session_id = xxx_session_id(id)                     # 2. 算 session ID
    await _reset_or_create_session(db, session_id, ...) # 3. 创建/重置 session
    client = await build_task_cody_client(db, ...)      # 4. 构建 Cody 客户端
    prompt = TEMPLATE.format(...)                       # 5. 构建 prompt
    on_tool_result = make_file_write_detector(...)      # 6. 文件写入检测
    runner = SessionRunner(client)
    async with client:
        await runner.run(db, session_id, prompt, ...)   # 7. 执行
    entity.field = read_output_file()                   # 8. 同步产出物到 DB
    await db.commit()
```

`chat_service.py` 的 `prepare_stage_chat()` 是一个 4 分支 if-elif 块（plan/todo/todo_exec/review），每个分支各自：
- 查询实体
- 构建 Cody 客户端
- 查找 cody_session_id（3 种不同的查询模式）
- 构建 on_tool_result 回调
- 返回 StageChatContext

**注意：** file-write 回调在 task_service 和 chat_service 中并非完全相同。plan 的回调逻辑一致（读 plan.md → 写 task.tech_plan），但 todo 的回调有差异：task_service 只返回内容，chat_service 额外调用 `sync_todos_from_file()` 同步 Todo 记录到 DB。重构时需注意统一为 chat_service 的完整版本。

另外，`run_stage_chat()` **会**写 JSONL 日志（通过 `_append_log()` 调用），与 `run()` 的日志机制一致，区别在于 `run_stage_chat()` 不更新 Session DB 状态。

**影响：** 新增一种 agent 需要改动 task_service.py + chat_service.py + router + 前端 hook，全靠 copy-paste。

#### 问题 2：崩溃恢复完全缺失

当前进程崩溃后：

| 数据 | 状态 | 后果 |
|---|---|---|
| Session.status | 永远卡在 RUNNING | 前端无限等待 |
| .jsonl 日志 | 保留到崩溃点 | 但重跑时被 `log_file.unlink()` 清空 |
| cody_session_id | 未存储（只在 DONE 时写入） | 无法恢复对话上下文 |
| task.tech_plan | 未同步（在 runner.run() 之后才写） | 产出物丢失 |
| 前端 | 无超时检测 | 用户无感知，一直转圈 |
| Init 层状态 | 无法重建 | 不知道哪层失败了 |

#### 问题 3：前端 stage hook 结构性重复

`usePlanStage`、`useTodoStage`、`useCodingStage` 三个 hook 结构一致（注意：`useReviewStage` 目前不存在，review 页面直接在组件内管理状态）：

```typescript
// 每个 hook 都是：
function useXxxStage(taskId: string) {
  const [task, setTask] = useState(null)           // 1. 加载业务实体
  const session = useSession(sessionId, refreshKey) // 2. 跟踪 session 状态
  const chat = useStageChat({                       // 3. 管理聊天
    sessionId, stage, entityId, onUpdated, logs
  })
  useEffect(() => { /* 加载/刷新 */ }, [deps])      // 4. 状态同步
  return { task, ...session, ...chat, actions }     // 5. 合并输出
}
```

差异仅在于：产出物类型（plan.md / todo.json / diff）和 onUpdated 回调逻辑。

#### 问题 4：Init 层间编排的恢复能力不足

`compute_init_sessions()` 计算出完整的 session 列表，在 router 层（`projects.py` 的 `init_project` 端点）预先创建到 DB。这一步已经做了落库，但存在以下不足：
- Session 预创建在 router 层而非 service 层，职责不清晰
- 崩溃后虽然 session 记录存在，但没有统一的层状态查询和重试机制
- 用户无法针对某一层的失败 session 进行定向重试

---

## 二、改进目标

1. **统一 Agent 抽象** — 消除后端 stage 重复代码，用注册制替代 if-elif
2. **统一前端 Hook** — 一个 `useAgent` 替代多个 stage hook，产出物渲染插件化
3. **崩溃恢复** — 启动时自动检测卡死 session，标记失败，前端感知并支持重试
4. **日志不丢失** — 重跑时追加而非清空，查询时只返回最新一轮
5. **Init 层状态持久化** — session 计划先落库，崩溃后可精确重建层状态
6. **不改变现有 UI 样式和用户操作流程** — 所有现有页面、布局、交互保持不变

---

## 三、后端改进方案

### 3.1 AgentConfig 注册制

新增 `daiflow/agents/` 目录，每种 agent 声明式注册：

```
daiflow/agents/
├── __init__.py          # 注册表 + AgentConfig 基类
├── plan_agent.py        # plan agent 配置
├── todo_split_agent.py  # todo_split agent 配置
├── todo_exec_agent.py   # todo_exec agent 配置
├── review_agent.py      # review agent 配置（仅 chat，不走 SessionRunner.run()）
└── init_agent.py        # init knowledge agent 配置
```

> **review 的特殊性：** review 阶段不通过 SessionRunner.run() 执行 AI 任务（`generate_commit_message` 直接调 Cody client），但它的 **chat 功能** 仍走 `run_stage_chat()` → 需要注册为 AgentConfig 以支持 `prepare_chat()`，但 `build_prompt()` 和 `on_complete()` 无需实现。

#### AgentConfig 基类

```python
# daiflow/agents/__init__.py

from dataclasses import dataclass, field
from typing import Callable, Any

@dataclass
class AgentConfig:
    """Agent 类型声明。每种 agent 注册一个实例。"""
    type: str                           # "plan", "todo_split", "todo_exec", "review", "init"
    chattable: bool = False             # 是否支持双向对话

    # --- 以下方法由子类实现 ---

    async def build_prompt(self, ctx: "AgentContext") -> str:
        """构建发送给 Cody 的 prompt。"""
        raise NotImplementedError

    async def build_cody_config(self, ctx: "AgentContext") -> dict:
        """返回 Cody 客户端配置：workdir, allowed_roots 等。"""
        raise NotImplementedError

    async def resolve_cody_session_id(self, ctx: "AgentContext") -> str | None:
        """获取要复用的 cody_session_id（如 todo_split 复用 plan 的）。"""
        return None

    def build_artifact_detector(self, ctx: "AgentContext") -> Callable | None:
        """构建 on_tool_result 回调，检测文件写入并推送产出物事件。"""
        return None

    async def on_complete(self, ctx: "AgentContext"):
        """Session 执行成功后的回调：同步产出物到 DB。"""
        pass

    # --- Chat 相关（仅 chattable=True 时需要实现）---

    def chat_system_prefix(self, ctx: "AgentContext") -> str | None:
        """Chat 消息的系统前缀（如"你正在编辑 plan.md"）。"""
        return None


@dataclass
class AgentContext:
    """Agent 执行上下文，由框架构建并传入。"""
    db: Any                             # AsyncSession
    session_id: str                     # DaiFlow session ID
    entity_id: str                      # 业务实体 ID（task_id 或 todo_id）
    task: Any = None                    # Task ORM 对象
    todo: Any = None                    # Todo ORM 对象（仅 todo_exec）
    project_id: str = ""
    task_dir: str = ""                  # ~/.daiflow/tasks/{task_id}/
    repos: list = field(default_factory=list)
    allowed_roots: list = field(default_factory=list)


# 全局注册表
_AGENT_REGISTRY: dict[str, AgentConfig] = {}

def register_agent(config: AgentConfig):
    _AGENT_REGISTRY[config.type] = config

def get_agent_config(agent_type: str) -> AgentConfig:
    return _AGENT_REGISTRY[agent_type]
```

#### Plan Agent 示例

```python
# daiflow/agents/plan_agent.py

from daiflow.agents import AgentConfig, AgentContext, register_agent
from daiflow.prompts import PLAN_PROMPT_TEMPLATE, PLAN_CHAT_PREFIX
from daiflow.session_runner import make_file_write_detector

class PlanAgent(AgentConfig):
    type = "plan"
    chattable = True

    async def build_prompt(self, ctx: AgentContext) -> str:
        return PLAN_PROMPT_TEMPLATE.format(
            description=ctx.task.description,
            prd=ctx.task.prd or "",
            existing_plan=ctx.task.tech_plan or "",
        )

    async def build_cody_config(self, ctx: AgentContext) -> dict:
        return {"workdir": ctx.task_dir, "allowed_roots": ctx.allowed_roots}

    async def resolve_cody_session_id(self, ctx: AgentContext) -> str | None:
        # Plan 创建新 session，不复用
        return None

    def build_artifact_detector(self, ctx: AgentContext):
        plan_path = Path(ctx.task_dir) / "plan.md"
        async def on_match(_fp):
            if plan_path.exists():
                content = plan_path.read_text(encoding="utf-8")
                ctx.task.tech_plan = content
                await ctx.db.commit()
                return content
            return None
        return make_file_write_detector("plan.md", "plan_updated", on_match)

    async def on_complete(self, ctx: AgentContext):
        plan_path = Path(ctx.task_dir) / "plan.md"
        if plan_path.exists():
            ctx.task.tech_plan = plan_path.read_text(encoding="utf-8")
            await ctx.db.commit()

    def chat_system_prefix(self, ctx: AgentContext) -> str:
        return PLAN_CHAT_PREFIX.format(plan_path=Path(ctx.task_dir) / "plan.md")

register_agent(PlanAgent())
```

#### TodoSplit Agent — 复用 Plan 的 Cody Session

```python
# daiflow/agents/todo_split_agent.py

class TodoSplitAgent(AgentConfig):
    type = "todo_split"
    chattable = True

    async def resolve_cody_session_id(self, ctx: AgentContext) -> str | None:
        # 复用 plan 的 cody_session_id，保持上下文连续
        from daiflow.models import Session
        result = await ctx.db.execute(
            select(Session.cody_session_id).where(
                Session.task_id == ctx.entity_id,
                Session.type == "plan",
            )
        )
        return result.scalar()

    # ... 其余方法类似 plan
```

#### Init Agent — chattable=False

```python
# daiflow/agents/init_agent.py

class InitAgent(AgentConfig):
    type = "init"
    chattable = False  # 不支持 chat

    async def build_prompt(self, ctx: AgentContext) -> str:
        return KNOWLEDGE_PROMPTS[ctx.knowledge_type]

    # 不需要实现 chat_system_prefix
    # 不需要实现 resolve_cody_session_id（每次独立）
```

### 3.2 AgentExecutor — 统一执行器（替代零散调用）

当前 `generate_plan()`、`generate_todos()`、`execute_todo()` 的公共逻辑提取为统一执行器：

```python
# daiflow/agent_executor.py

class AgentExecutor:
    """统一的 Agent 执行器。封装 session 生命周期管理。"""

    async def run(
        self,
        agent_type: str,
        entity_id: str,
        session_id: str,
        task_id: str | None = None,
        extra_channels: list[str] | None = None,
    ):
        config = get_agent_config(agent_type)
        db = await get_background_db()

        try:
            # 1. 构建上下文
            ctx = await self._build_context(db, config, entity_id, task_id)
            ctx.session_id = session_id

            # 2. 创建/重置 session（统一入口）
            await self._ensure_session(db, session_id, agent_type, entity_id, task_id)

            # 3. 构建 Cody 客户端
            cody_config = await config.build_cody_config(ctx)
            client = await build_cody_client(**cody_config)

            # 4. 构建 prompt
            prompt = await config.build_prompt(ctx)

            # 5. 获取 cody_session_id（如 todo_split 复用 plan 的）
            cody_session_id = await config.resolve_cody_session_id(ctx)

            # 6. 构建产出物检测器
            on_tool_result = config.build_artifact_detector(ctx)

            # 7. 执行
            runner = SessionRunner(client)
            async with client:
                await runner.run(
                    db, session_id, prompt,
                    extra_channels=extra_channels,
                    on_tool_result=on_tool_result,
                    cody_session_id=cody_session_id,
                )

            # 8. 完成后回调
            await config.on_complete(ctx)

        except Exception:
            # SessionRunner 内部已处理 session 状态更新
            # 这里处理 SessionRunner 之前的异常（如构建上下文失败）
            await self._mark_failed(db, session_id, traceback.format_exc())

    async def prepare_chat(
        self,
        agent_type: str,
        entity_id: str,
        session_id: str,
    ) -> StageChatContext:
        """统一的 chat 上下文准备，替代 chat_service.prepare_stage_chat()"""
        config = get_agent_config(agent_type)
        if not config.chattable:
            raise DaiFlowError(400, f"Agent type '{agent_type}' does not support chat")

        db = await get_background_db()
        ctx = await self._build_context(db, config, entity_id)

        cody_config = await config.build_cody_config(ctx)
        client = await build_cody_client(**cody_config)
        cody_session_id = await config.resolve_cody_session_id(ctx)
        on_tool_result = config.build_artifact_detector(ctx)
        system_prefix = config.chat_system_prefix(ctx)

        return StageChatContext(
            session_id=session_id,
            cody_client=client,
            cody_session_id=cody_session_id,
            on_tool_result=on_tool_result,
            system_prefix=system_prefix,
        )
```

**改动前 vs 改动后对比：**

```python
# === 改动前（task_service.py 每个 stage 各写一遍）===

async def generate_plan(task_id: str):
    db = ...
    task = await db.get(Task, task_id)
    session_id = task_plan(task_id)
    await _reset_or_create_session(db, session_id, "plan", task_id, task_id)
    repos, allowed_roots = await get_task_context(db, task_id, task.project_id)
    client = await build_task_cody_client(db, task_id, task.project_id)
    prompt = PLAN_PROMPT_TEMPLATE.format(...)
    on_tool_result = make_file_write_detector("plan.md", "plan_updated", ...)
    runner = SessionRunner(client)
    async with client:
        await runner.run(db, session_id, prompt, on_tool_result=on_tool_result)
    task.tech_plan = read_plan(...)
    await db.commit()

async def generate_todos(task_id: str):
    # ... 几乎一样的代码 ...

async def execute_todo(todo_id: str):
    # ... 几乎一样的代码 ...

# === 改动后（一行调用）===

async def generate_plan(task_id: str):
    executor = AgentExecutor()
    await executor.run("plan", entity_id=task_id, session_id=task_plan(task_id), task_id=task_id)

async def generate_todos(task_id: str):
    executor = AgentExecutor()
    await executor.run("todo_split", entity_id=task_id, session_id=task_todo_split(task_id), task_id=task_id)

async def execute_todo(todo_id: str):
    executor = AgentExecutor()
    await executor.run("todo_exec", entity_id=todo_id, session_id=task_todo_exec(task_id, todo_id), task_id=task_id)
```

### 3.3 崩溃恢复机制

#### 3.3.1 启动时扫描卡死 Session

```python
# daiflow/recovery.py

async def recover_stale_sessions(ws_manager: WSManager):
    """应用启动时调用。扫描所有 RUNNING 状态的 session 并标记为 FAILED。"""
    async with get_background_db() as db:
        stale_sessions = (await db.execute(
            select(Session).where(Session.status == SessionStatus.RUNNING)
        )).scalars().all()

        for session in stale_sessions:
            session.status = SessionStatus.FAILED
            session.error = "进程异常终止，session 未正常结束"
            session.finished_at = datetime.utcnow()

        await db.commit()

        # 推送 WS 事件，通知已连接的前端
        for session in stale_sessions:
            await ws_manager.publish(
                f"session:{session.session_id}",
                {"type": "status_change", "status": SessionStatus.FAILED,
                 "error": session.error}
            )

# main.py
@app.on_event("startup")
async def startup():
    await recover_stale_sessions(ws_manager)
```

#### 3.3.2 日志追加模式（不清空）

```python
# session_runner.py 修改

async def run(self, db, session_id, prompt, ...):
    log_file = _log_path(session_id)

    # 改动：不删除，追加 run_boundary 分隔符
    if log_file.exists():
        _append_event(log_file, {
            "type": "run_boundary",
            "attempt": await self._count_attempts(log_file) + 1,
            "ts": _now_iso(),
        })

    # ... 后续逻辑不变，继续追加事件 ...
```

#### 3.3.3 日志查询只返回最新一轮

```python
# daiflow/routers/sessions.py 修改

@router.get("/sessions/{session_id}/logs")
async def get_session_logs(session_id: str, all_attempts: bool = False):
    all_lines = _read_jsonl(log_path(session_id))

    if all_attempts:
        return all_lines  # Debug 页面用：返回全部

    # 默认：只返回最后一个 run_boundary 之后的日志
    last_boundary = -1
    for i, line in enumerate(all_lines):
        if line.get("type") == "run_boundary":
            last_boundary = i

    return all_lines[last_boundary + 1:] if last_boundary >= 0 else all_lines
```

#### 3.3.4 cody_session_id 在 RUNNING 时立即存储

```python
# session_runner.py 修改

async def run(self, db, session_id, prompt, ..., cody_session_id=None):
    # RUNNING 状态更新时，同时存储已知的 cody_session_id
    await db.execute(
        update(Session).where(Session.session_id == session_id).values(
            status=SessionStatus.RUNNING,
            started_at=datetime.utcnow(),
            cody_session_id=cody_session_id,  # 如果是复用的，立即存
        )
    )
    await db.commit()

    # ... 流式处理 ...

    # DONE 时更新为 Cody 返回的新 session_id（覆盖）
    await db.execute(
        update(Session).where(Session.session_id == session_id).values(
            status=SessionStatus.DONE,
            cody_session_id=result_cody_session_id,  # Cody 返回的
            finished_at=datetime.utcnow(),
        )
    )
```

### 3.4 Init 层状态管理改进

#### 3.4.1 Session 预创建下沉到 Service 层

当前 session 预创建在 router 层（`projects.py` 的 `init_project` 端点），建议下沉到 `project_service.py`，使职责更清晰：

```python
# project_service.py 修改 — 将 session 预创建从 router 移入 service

async def run_init(project_id: str, ws_manager=None):
    planned = compute_init_sessions(project_id, repos)

    # 改动：session 预创建移入 service 层（原在 router 层）
    for s in planned:
        existing = await db.get(Session, s["session_id"])
        if existing:
            # 重置（支持重新初始化）
            existing.status = SessionStatus.WAITING
            existing.error = None
        else:
            db.add(Session(
                session_id=s["session_id"],
                type="init",
                ref_id=project_id,
                layer=s["layer"],
                status=SessionStatus.WAITING,
            ))
    await db.commit()

    # 然后逐层执行（逻辑不变）
    for layer_num in [1, 2, 3, 4]:
        layer_sessions = [s for s in planned if s["layer"] == layer_num]
        await asyncio.gather(*[run_agent(s) for s in layer_sessions])
        # 检查层内是否有失败 ...
```

#### 3.4.2 崩溃恢复时重建层状态

```python
async def get_init_layer_status(project_id: str) -> list[dict]:
    """返回每层的聚合状态，用于前端展示和恢复判断。"""
    sessions = await db.execute(
        select(Session).where(
            Session.session_id.like(f"init:{project_id}:%"),
            Session.type == "init",
        )
    )

    layers = {}
    for s in sessions.scalars():
        layer = layers.setdefault(s.layer, {"layer": s.layer, "sessions": []})
        layer["sessions"].append({
            "session_id": s.session_id,
            "status": s.status,
            "error": s.error,
        })

    for layer in layers.values():
        statuses = [s["status"] for s in layer["sessions"]]
        if all(s == SessionStatus.DONE for s in statuses):
            layer["status"] = "done"
        elif any(s == SessionStatus.FAILED for s in statuses):
            layer["status"] = "failed"
        elif any(s == SessionStatus.RUNNING for s in statuses):
            layer["status"] = "running"
        else:
            layer["status"] = "waiting"

    return sorted(layers.values(), key=lambda x: x["layer"])
```

#### 3.4.3 用户手动重试某一层

```python
# 新增 API
@router.post("/projects/{project_id}/init/retry")
async def retry_init_layer(project_id: str, layer: int, background_tasks: BackgroundTasks):
    """用户点击重试按钮，只重跑指定层的失败 session。"""
    async with get_db() as db:
        # 重置该层所有 FAILED session 为 WAITING
        await db.execute(
            update(Session).where(
                Session.session_id.like(f"init:{project_id}:%"),
                Session.layer == layer,
                Session.status == SessionStatus.FAILED,
            ).values(status=SessionStatus.WAITING, error=None)
        )
        await db.commit()

    # 后台重跑该层
    background_tasks.add_task(_run_init_layer_retry, project_id, layer)
    return {"ok": True}
```

**不会自动重跑。** 启动时只做标记（RUNNING → FAILED），用户在 InitStage 页面看到失败状态后，手动点击「重试」才触发。

### 3.5 Chat 支持的统一处理

#### WS Handler 改造

```python
# daiflow/routers/ws.py 修改

async def _handle_chat(ws: WebSocket, data: dict):
    stage = data.get("chat_path", "")
    entity_id = data.get("entity_id", "")

    # 统一入口，替代 prepare_stage_chat 的 if-elif
    executor = AgentExecutor()
    ctx = await executor.prepare_chat(stage, entity_id)

    # ctx.chattable 已在 prepare_chat 内部校验
    # 如果 chattable=False 会抛 DaiFlowError(400)

    async for event in run_stage_chat(
        ctx.session_id, ctx.cody_client, ctx.cody_session_id,
        message, ctx.on_tool_result,
        system_prefix=ctx.system_prefix,
    ):
        await ws.send_json({"channel": channel, "event": event})
```

#### Agent Config 声明 chattable

```python
# init agent
class InitAgent(AgentConfig):
    type = "init"
    chattable = False    # ← 不支持 chat，WS chat 请求会被拒绝

# plan agent
class PlanAgent(AgentConfig):
    type = "plan"
    chattable = True     # ← 支持 chat
```

---

## 四、前端改进方案

### 4.1 统一 useAgent Hook（不改变页面）

将 `usePlanStage`、`useTodoStage`、`useCodingStage` 的公共逻辑下沉：

```typescript
// frontend/src/hooks/useAgent.ts

interface UseAgentOptions {
  sessionId: string | null
  agentType: string           // "plan", "todo", "todo_exec", "review"
  entityId: string
  chattable: boolean          // 是否展示聊天面板
  onArtifactUpdated?: (event: SessionEvent) => void
}

export function useAgent(options: UseAgentOptions) {
  const { sessionId, agentType, entityId, chattable, onArtifactUpdated } = options

  // 1. Session 状态跟踪（统一）
  const [refreshKey, setRefreshKey] = useState(0)
  const { status, logs, error } = useSession(sessionId, refreshKey)

  // 2. 聊天功能（仅 chattable=true）
  const chat = chattable
    ? useStageChat({ sessionId, stage: agentType, entityId, onUpdated: onArtifactUpdated, sessionLogs: logs })
    : null

  // 3. 超时检测
  const isStale = useStaleDetection(status, logs)

  // 4. 重试
  const retry = useCallback(() => setRefreshKey(k => k + 1), [])

  return {
    status, logs, error, isStale,
    // Chat（仅 chattable 时有值）
    messages: chat?.messages ?? [],
    streaming: chat?.streaming ?? false,
    sendMessage: chat?.sendMessage ?? null,
    // 操作
    retry,
  }
}
```

#### 各 Stage Hook 简化

```typescript
// usePlanStage.ts 改造后
export function usePlanStage(taskId: string) {
  const [task, setTask] = useState<Task | null>(null)
  const [planContent, setPlanContent] = useState("")
  const sessionId = task ? `task:${taskId}:plan` : null

  // 加载 task
  useEffect(() => { getTask(taskId).then(setTask) }, [taskId])

  // 统一 agent hook
  const agent = useAgent({
    sessionId,
    agentType: "plan",
    entityId: taskId,
    chattable: true,
    onArtifactUpdated: (event) => {
      if (event.type === "plan_updated" && event.content) {
        setPlanContent(event.content)
      }
    },
  })

  return { task, planContent, ...agent }
}
```

**改动量最小化：** `usePlanStage` 等 hook 仍然存在，对外接口不变，PlanStage.tsx 等页面组件**完全不用改**。

### 4.2 超时检测

```typescript
// frontend/src/hooks/useStaleDetection.ts

export function useStaleDetection(status: number, logs: SessionEvent[]) {
  const [isStale, setIsStale] = useState(false)
  const lastEventTimeRef = useRef(Date.now())

  useEffect(() => {
    if (status !== SessionStatus.RUNNING) {
      setIsStale(false)
      return
    }

    // 每次收到新 log，更新最后事件时间
    if (logs.length > 0) {
      lastEventTimeRef.current = Date.now()
    }

    // 60 秒没收到新事件 → 标记为 stale
    const timer = setInterval(() => {
      if (Date.now() - lastEventTimeRef.current > 60_000) {
        setIsStale(true)
      }
    }, 10_000)

    return () => clearInterval(timer)
  }, [status, logs.length])

  return isStale
}
```

前端感知到 stale 后，可以在现有 UI 上叠加一个提示条（不改变布局）：

```typescript
// StageLayout.tsx 中可选展示
{isStale && (
  <div className="stale-banner">
    Session 可能已中断。
    <button onClick={retry}>重试</button>
  </div>
)}
```

### 4.3 Agent 配置接口

后端新增一个轻量接口，告诉前端某个 agent type 的配置：

```python
# GET /api/agents/config/{agent_type}
@router.get("/agents/config/{agent_type}")
async def get_agent_type_config(agent_type: str):
    config = get_agent_config(agent_type)
    return {
        "type": config.type,
        "chattable": config.chattable,
    }
```

前端 useAgent 在初始化时查询，决定是否启用聊天面板。也可以直接在前端硬编码（因为 agent type 是有限的已知集合），避免多一次请求。

---

## 五、不受影响的部分（明确边界）

以下内容**保持完全不变**：

| 类别 | 不变的内容 |
|---|---|
| **页面** | InitStage、PlanStage、TodoStage、CodingStage、ReviewStage 页面组件 |
| **布局** | StageLayout 左右分栏、StageProgress 进度条、Topbar |
| **组件** | ChatPanel、MarkdownViewer、DiffViewer、ToolGroupBlock |
| **样式** | 所有 CSS、主题、字体、配色 |
| **路由** | 前端路由路径和导航逻辑 |
| **用户流程** | plan → lock → todo → code → review 操作步骤 |
| **WebSocket 协议** | subscribe/unsubscribe/chat/ping 消息格式不变 |
| **Session ID 规则** | session_ids.py 中的命名规则不变 |
| **数据库 Schema** | Session、Task、Todo 表结构不变（无需 migration） |
| **API 路径** | 现有所有 REST API 路径不变 |

---

## 六、实施计划

### 第一阶段：后端 Agent 抽象（不影响前端）

| 步骤 | 内容 | 影响范围 |
|---|---|---|
| 1 | 创建 `daiflow/agents/` 目录，定义 AgentConfig 基类和注册表 | 新增文件 |
| 2 | 实现 5 种 AgentConfig（plan、todo_split、todo_exec、init 走 SessionRunner；review 仅 chat） | 新增文件 |
| 3 | 实现 AgentExecutor，封装统一执行流程 | 新增文件 |
| 4 | 改造 task_service.py：generate_plan/todos/execute_todo 调用 AgentExecutor | 修改文件 |
| 5 | 改造 chat_service.py：prepare_stage_chat 调用 AgentExecutor.prepare_chat | 修改文件 |
| 6 | 验证：所有现有功能不受影响（单元测试通过） | 测试 |

### 第二阶段：崩溃恢复

| 步骤 | 内容 | 影响范围 |
|---|---|---|
| 7 | 实现 recovery.py：启动时扫描 RUNNING session | 新增文件 |
| 8 | 修改 session_runner.py：日志追加模式 + cody_session_id 立即存储 | 修改文件 |
| 9 | 修改 sessions router：日志查询支持 run_boundary 过滤 | 修改文件 |
| 10 | Init session 计划先落库 | 修改 project_service.py |
| 11 | 新增 init retry API | 新增路由 |
| 12 | 验证：模拟进程崩溃 + 重启后状态恢复 | 测试 |

### 第三阶段：前端统一 Hook

| 步骤 | 内容 | 影响范围 |
|---|---|---|
| 13 | 实现 useAgent hook + useStaleDetection | 新增文件 |
| 14 | 改造 usePlanStage/useTodoStage/useCodingStage 基于 useAgent | 修改 hook 文件 |
| 15 | StageLayout 增加 stale 提示条 | 修改组件 |
| 16 | 验证：所有 stage 页面功能不受影响 | 测试 |

### 第四阶段（可选）：Agent Dashboard

| 步骤 | 内容 | 影响范围 |
|---|---|---|
| 17 | 新增 Agent Dashboard 页面（全局 session 管理视图） | 新增页面 |
| 18 | InitStage 增加层级重试按钮 | 修改页面 |

---

## 七、风险评估

| 风险 | 等级 | 缓解措施 |
|---|---|---|
| Agent 抽象过度，增加理解成本 | 低 | AgentConfig 只有 6 个方法，逻辑直观 |
| 改造过程中引入回归 | 中 | 分阶段推进，每阶段有测试验证 |
| 日志追加模式导致文件过大 | 低 | 单个 session 通常只重跑 1-2 次 |
| Init retry 引入并发问题 | 低 | 同层 session 由 asyncio.gather 管理，无竞争 |
| 前端 hook 重构影响页面 | 低 | stage hook 对外接口不变，页面无需修改 |

---

## 八、实施结果与方案偏差

> 本节记录实际实施中与上述设计方案的偏差，作为代码 review 参考。

### 8.1 后端 Agent 抽象（对应第三章）

#### AgentConfig 基类偏差

| 设计 | 实际 | 原因 |
|------|------|------|
| 字段名 `type` | 字段名 `agent_type` | 避免遮蔽 Python 内置 `type()` |
| `@dataclass` 修饰 | 普通 class | 子类仅设置类属性，不需要 `__init__` |
| 有 `build_cody_config()` 方法 | 无此方法 | Cody 客户端配置统一在 `agent_executor` 中通过 `build_task_cody_client()` 构建，无需每个 agent 单独实现 |
| `AgentContext` 有 `repos` 字段 | 无 `repos` 字段 | 实际只需 `allowed_roots`，`repos` 列表不被 agent 使用 |
| Init agent 访问 `ctx.knowledge_type` | `AgentContext` 无此字段 | Init agent 是占位符，其 prompt 由 `project_service` 独立构建，不走 `AgentConfig.build_prompt()` |

#### AgentExecutor 偏差

| 设计 | 实际 | 原因 |
|------|------|------|
| `class AgentExecutor` | 模块级函数 `run_agent()` / `prepare_chat()` | 无状态实例无意义，函数更简洁 |
| DB 由 executor 内部创建 | DB 由调用方传入 `run_agent(db, ...)` | `execute_todo` 等需要在调用 `run_agent` 前做预处理（如记录 `commit_before`），共享同一 DB session 更安全 |
| 先构建上下文，后创建 session | 先创建 session，后构建上下文 | 若 `_build_context` 抛异常（如 entity 不存在），session 不存在会导致客户端永远 404 |
| 一行调用 `executor.run(...)` | 仍有 5~20 行前置逻辑 | `execute_todo` 需要记录 `commit_before` git hashes；所有函数需要验证 entity 存在性 |

#### 额外实现（设计文档未提及）

- **`_auto_register()` 机制** — `agents/__init__.py` 模块加载时自动导入所有 agent 子模块触发注册
- **`append_path_boundary()` 调用** — 所有 task 相关 agent 的 `build_prompt()` 都会调用此函数追加路径上下文
- **`on_complete` 防御性重载** — 所有 agent 的 `on_complete` 都会从 DB 重新加载 entity，防止长时间执行期间 entity 被删
- **`prepare_chat()` chattable 校验** — 非 chattable agent 尝试 chat 时抛出 `InvalidStateError`
- **`append_log()` 改名** — 原 `_append_log()` 被多个模块引用，重命名为公开 API `append_log()`

### 8.2 崩溃恢复（对应 3.3）

| 设计 | 实际 | 原因 |
|------|------|------|
| 独立 `recovery.py` 模块 | 内联在 `main.py` 的 `_recover_interrupted_sessions()` | 逻辑较简单，不值得独立模块 |
| `@app.on_event("startup")` | `lifespan` 上下文管理器 | FastAPI 推荐用 lifespan 替代已废弃的 on_event |
| 恢复后推送 WS 事件 | ✅ 已实现 | 通过全局 `ws_manager.publish()` 推送 `status_change` 事件 |
| `run_boundary` 含 `attempt` 计数 | 无 `attempt` 字段 | 简化实现，查询时只关心最后一个 boundary 的位置 |
| 恢复范围：仅 RUNNING session | 额外恢复 RUNNING 的 todo + 自动重试 init pipeline | 实际需求比设计更广 |

### 8.3 前端 Hook（对应第四章）

| 设计 | 实际 | 原因 |
|------|------|------|
| Stage hooks 基于 `useAgent` 重构 | ✅ 已实现 — `usePlanStage`/`useTodoStage`/`useCodingStage` 均使用 `useAgent` 作为基础 | 产出物加载逻辑各 hook 自行处理，session/chat/stale 由 `useAgent` 统一 |
| `useStaleDetection(status, logs: SessionEvent[])` | `useStaleDetection(status, logsLength: number, thresholdMs?)` | 只需 length 触发 effect，无需传整个数组；增加可配置阈值 |
| `useAgent` 选项中 `agentType` | `stage` (union type) | 更精确的类型约束 |
| `useAgent` 返回 `retry` | 返回 `refreshSession` + `sessionRefreshKey` | 命名更语义化 |
| `/api/agents/config` 接口 | 未实现（前端硬编码） | Agent type 是有限已知集合，无需运行时查询 |

### 8.4 Init 层管理（对应 3.4）

| 设计 | 实际 | 差异说明 |
|------|------|---------|
| Session 预创建下沉到 service 层 | ✅ 已实现 — `prepare_init_sessions()` 在 `project_service.py` | Router 调用 service 函数 |
| `get_init_layer_status()` 聚合函数 | ✅ 已实现 — 返回 per-layer aggregate status (`done`/`failed`/`running`/`waiting`) | `get_init_sessions` 端点直接调用 |
| retry 接收 `layer` 参数 | 自动检测最早失败层并级联重试后续层 | 实际需求比逐层重试更实用 |
| Init re-run 删除 log 文件 | 改为追加 `run_boundary` 标记 | 与崩溃恢复方案一致 |

### 8.5 实施状态汇总

| 阶段 | 状态 | 说明 |
|------|------|------|
| 第一阶段：后端 Agent 抽象 | ✅ 完成 | AgentConfig 注册表 + `run_agent()` / `prepare_chat()` + task_service 简化 + chat_service `_STAGE_MAP` |
| 第二阶段：崩溃恢复 | ✅ 完成 | 日志追加 + run_boundary 过滤 + cody_session_id 即时存储 + 启动恢复 |
| 第三阶段：前端统一 Hook | ✅ 完成 | `useAgent` + `useStaleDetection` + stage hooks 集成 + StageLayout stale banner |
| 第四阶段：Agent Dashboard | 🔲 未开始 | 可选，待需求明确后实施 |
