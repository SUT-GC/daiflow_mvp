# DaiFlow Agent Session 流程抽象

> 版本：v0.1 MVP
> 更新时间：2026-03-14

---

## 一、概述

DaiFlow 中所有 AI 交互共享统一的 Session 抽象：

```
AgentConfig（配置） → agent_executor（编排） → SessionRunner（执行） → WSManager（推送）
```

核心设计原则：
- **统一模式**：所有 AI 任务（方案生成、Todo 拆解、代码实现、审查）走同一条执行通道
- **注册派发**：通过 AgentRegistry 注册不同 Agent 类型，消除 if-elif 分支
- **双 ID 体系**：DaiFlow 业务 session_id + Cody SDK 的 cody_session_id
- **持久化恢复**：所有事件写入 `.jsonl` 日志，重启后可完整回放

---

## 二、核心组件

### 2.1 组件关系图

```
┌──────────────────────────────────────────────────────┐
│                    Frontend (React)                   │
│  useSession ← subscribe(session:{id}) ← WSManager    │
│  useStageChat ← sendChat() → WS → run_stage_chat()  │
└───────────────────────┬──────────────────────────────┘
                        │ WebSocket (/api/ws)
┌───────────────────────▼──────────────────────────────┐
│                  routers/ws.py                        │
│  subscribe / unsubscribe / chat / ping                │
└───────────┬──────────────────────┬───────────────────┘
            │                      │
            ▼                      ▼
┌───────────────────┐   ┌─────────────────────────┐
│  WSManager        │   │  chat_service            │
│  publish(ch, evt) │   │  prepare_stage_chat()    │
│  subscribe(ws,ch) │   │  → run_stage_chat()      │
└─────────▲─────────┘   └─────────────────────────┘
          │
┌─────────┴──────────────────────────────────────────┐
│              agent_executor.run_agent()              │
│  1. reset/create Session                            │
│  2. build AgentContext                              │
│  3. get AgentConfig from registry                   │
│  4. build prompt + resolve cody_session_id          │
│  5. create SessionRunner → run()                    │
│  6. on_complete() post-hook                         │
└─────────────────────────┬──────────────────────────┘
                          │
┌─────────────────────────▼──────────────────────────┐
│              SessionRunner.run()                     │
│  1. update session → RUNNING                        │
│  2. stream from Cody SDK                            │
│  3. convert chunks → events                         │
│  4. log to .jsonl + publish via WSManager            │
│  5. detect artifacts (file writes)                   │
│  6. update session → DONE / FAILED                  │
└─────────────────────────┬──────────────────────────┘
                          │
┌─────────────────────────▼──────────────────────────┐
│           Cody SDK (AsyncCodyClient)                 │
│           stream chunks → text/tool/done             │
└────────────────────────────────────────────────────┘
```

### 2.2 文件索引

| 文件 | 职责 |
|------|------|
| `daiflow/session_runner.py` | 核心执行器：流式处理 + 日志 + 事件推送 |
| `daiflow/ws_manager.py` | 进程内 WebSocket pub/sub |
| `daiflow/agent_executor.py` | Agent 编排器：上下文构建 + 派发 |
| `daiflow/agents/__init__.py` | AgentConfig 基类 + 全局注册表 |
| `daiflow/agents/plan_agent.py` | Plan Agent 配置 |
| `daiflow/agents/todo_split_agent.py` | Todo Split Agent 配置 |
| `daiflow/agents/todo_exec_agent.py` | Todo Exec Agent 配置 |
| `daiflow/agents/review_agent.py` | Review Agent 配置 |
| `daiflow/agents/init_agent.py` | Init Agent 配置 |
| `daiflow/services/chat_service.py` | 阶段 Chat 上下文准备 |
| `daiflow/routers/ws.py` | WebSocket 路由 |
| `daiflow/session_ids.py` | Session ID 构造函数 |
| `daiflow/prompts/__init__.py` | Prompt 模板 |
| `daiflow/models.py` | Session 模型 |

---

## 三、双 ID 体系

### 3.1 session_id（业务 ID）

由 `daiflow/session_ids.py` 统一构造，作为 Session 表主键：

```python
task_plan(task_id)                  # "task:{task_id}:plan"
task_todo_split(task_id)            # "task:{task_id}:todo_split"
task_todo_exec(task_id, todo_id)    # "task:{task_id}:todo:{todo_id}"
task_review(task_id)                # "task:{task_id}:review"
task_init_fetch(task_id)            # "task:{task_id}:init:fetch_code"
task_init_skills(task_id)           # "task:{task_id}:init:sync_skills"
task_init_bus(task_id)              # "task:init:{task_id}"
project_init(project_id, type)      # "init:{project_id}:{knowledge_type}"
project_init_bus(project_id)        # "project:init:{project_id}"
```

### 3.2 cody_session_id（Cody SDK 内部 UUID）

- Cody SDK 每次对话分配的 UUID，存储在 `sessions.cody_session_id`
- 用于**上下文连续性**：同一个 `cody_session_id` 可让 AI "记住"之前的对话
- 在 `done` 事件中捕获，持久化到数据库

### 3.3 Channel 命名

WebSocket 频道名基于 session_id 构造：

| 频道 | 用途 |
|------|------|
| `session:{session_id}` | 单个 Session 事件流 |
| `chat:{request_id}` | 临时 Chat 响应流（完成后自动清理） |
| `project:init:{project_id}` | 项目知识生成聚合总线 |
| `task:init:{task_id}` | 任务初始化聚合总线 |

---

## 四、Agent 注册机制

### 4.1 AgentConfig 基类

```python
@dataclass
class AgentContext:
    db: AsyncSession
    session_id: str
    entity_id: str           # task_id 或 todo_id
    task: Task | None
    todo: Todo | None
    project_id: str
    task_dir: str
    allowed_roots: list[str]

class AgentConfig:
    agent_type: str          # 注册名
    chattable: bool          # 是否支持阶段 Chat

    async def build_prompt(ctx) -> str           # 构造 Prompt
    async def resolve_cody_session_id(ctx)       # 复用之前的 Session?
    async def build_artifact_detector(ctx)       # 文件写入检测回调
    async def on_complete(ctx)                   # 执行后钩子
    async def chat_system_prefix(ctx) -> str     # Chat 系统前缀
```

### 4.2 注册与派发

```python
# 注册
_AGENT_REGISTRY: dict[str, AgentConfig] = {}

def register_agent(config: AgentConfig):
    _AGENT_REGISTRY[config.agent_type] = config

# 各 Agent 文件末尾自注册
register_agent(PlanAgent())
register_agent(TodoSplitAgent())
register_agent(TodoExecAgent())
register_agent(ReviewAgent())

# 查询
def get_agent_config(agent_type: str) -> AgentConfig:
    return _AGENT_REGISTRY[agent_type]
```

### 4.3 五种 Agent 类型

| Agent 类型 | 可 Chat | Cody Session 策略 | 产物 | 产物事件 |
|-----------|---------|------------------|------|---------|
| `plan` | ✓ | 独立 Session | `plan.md` | `plan_updated` |
| `todo_split` | ✓ | 复用 Plan 的 Session | `todo.json` | `todo_updated` |
| `todo_exec` | ✓ | 每个 Todo 独立 | 代码文件 | `code_updated` |
| `review` | ✓ | 独立 Session | 代码文件 | `code_updated` |
| `init` | ✗ | 每个知识类型独立 | `SKILL.md` | `skill_loaded` |

---

## 五、Session 生命周期

### 5.1 状态枚举

```python
class SessionStatus(IntEnum):
    WAITING = 0   # 已创建，等待执行
    RUNNING = 1   # 执行中
    DONE    = 2   # 完成
    FAILED  = 3   # 失败
```

### 5.2 完整生命周期

```
                              run_agent() 调用
                                    │
                                    ▼
                         ┌──────────────────┐
                         │  WAITING          │  reset_or_create_session()
                         │  创建 Session 记录 │
                         └────────┬─────────┘
                                  │ SessionRunner.run() 开始
                                  ▼
                         ┌──────────────────┐
                         │  RUNNING          │  写入 .jsonl + 推送 WS 事件
                         │  流式处理 Cody 输出 │
                         └───┬──────────┬───┘
                             │          │
                    done chunk       exception
                             │          │
                             ▼          ▼
                    ┌────────────┐ ┌──────────┐
                    │  DONE      │ │  FAILED   │
                    │  捕获 cody │ │  记录 error│
                    │  session_id│ │  推送错误  │
                    └────────────┘ └──────────┘
```

### 5.3 重启恢复

- 所有事件持久化到 `~/.daiflow/sessions/{safe_filename(session_id)}.jsonl`
- 前端通过 `GET /api/sessions/{id}/logs` 回放完整事件流
- 中断的 Session 在重启后标记为 FAILED，支持用户重试

---

## 六、SessionRunner 详解

### 6.1 核心执行流程

`daiflow/session_runner.py` 中的 `SessionRunner.run()` 方法：

```python
async def run(
    db: AsyncSession,
    session_id: str,
    prompt: str,
    extra_channels: list[str] | None = None,
    on_tool_result=None,              # 文件写入检测回调
    cody_session_id: str | None = None,  # 复用之前的 Session
    language: str | None = None,
):
```

**执行步骤：**

1. **追加运行边界标记**到已有 `.jsonl` 日志（支持同一 Session 多次运行）
2. **更新 Session 状态** → RUNNING
3. **记录 user_message** 到日志
4. **流式处理 Cody 输出**：
   - `text_delta` → 记录日志 + 推送 WS
   - `thinking` → 记录日志 + 推送 WS
   - `tool_call` → 记录日志 + 推送 WS
   - `tool_result` → 调用 `on_tool_result` 检测文件写入 → 记录日志 + 推送 WS
   - `done` → 捕获 `cody_session_id`，更新 Session 状态 → DONE
   - `compact` → 仅记录日志（不推送 WS）
5. **异常处理**：记录错误到日志和 DB，推送 `status_change` 事件（FAILED）

### 6.2 事件类型

| 事件类型 | 来源 | 说明 |
|---------|------|------|
| `text_delta` | Cody SDK | AI 文本片段 |
| `thinking` | Cody SDK | AI 推理过程 |
| `tool_call` | Cody SDK | 工具调用（含参数） |
| `tool_result` | Cody SDK | 工具返回结果 |
| `done` | Cody SDK | 流完成（含 token 用量） |
| `compact` | Cody SDK | 内部日志（不推送） |
| `status_change` | SessionRunner | Session 状态变更 |
| `plan_updated` | PlanAgent | plan.md 被写入 |
| `todo_updated` | TodoSplitAgent | todo.json 被写入 |
| `code_updated` | TodoExecAgent / ReviewAgent | 代码文件被写入 |
| `skill_loaded` | SessionRunner | Cody 读取了技能文件 |
| `session_status` | SessionRunner | 聚合总线状态（init 用） |
| `user_message` | 日志记录 | 用户输入（仅日志，不推送） |
| `error` | SessionRunner | 执行错误 |

### 6.3 产物检测机制

`make_file_write_detector()` 工厂函数为每个 Agent 创建 `on_tool_result` 回调：

```python
FILE_WRITE_TOOLS = frozenset({"write_file", "edit_file", "create_file"})
```

当 Cody 调用上述工具时：
1. 检测到文件写入
2. 读取文件内容（对 plan.md / todo.json）
3. 更新数据库（`task.tech_plan` / `todos` 表）
4. 推送阶段特定事件（`plan_updated` / `todo_updated` / `code_updated`）

---

## 七、WSManager 详解

### 7.1 进程内 Pub/Sub

`daiflow/ws_manager.py` 实现了轻量级的进程内频道订阅系统：

```python
class WSManager:
    _channels: dict[str, set[WebSocket]]    # 频道 → 订阅者集合
    _conn_channels: dict[int, set[str]]     # 连接 → 已订阅频道集合

    def subscribe(ws, channel)               # 订阅频道
    def unsubscribe(ws, channel)             # 取消订阅
    def disconnect(ws)                       # 断开连接（清理所有订阅）
    async def publish(channel, event)        # 广播事件到频道所有订阅者
    async def send_to(ws, channel, event)    # 定向发送
    def cleanup_channel(channel)             # 清理频道
```

### 7.2 消息格式

**Server → Client：**
```json
{"channel": "session:task:42:plan", "event": {"type": "text_delta", "text": "..."}}
```

**Client → Server：**
```json
{"action": "subscribe", "channel": "session:task:42:plan"}
{"action": "chat", "id": "req_1", "chat_path": "plan", "entity_id": "abc", "message": "..."}
{"action": "ping"}
```

---

## 八、双向 Chat 流程

### 8.1 概述

所有 4 个阶段（Plan / Todo / Coding / Review）的 Chat 共享统一模式：

```
前端 useStageChat → wsClient.sendChat() → WS → routers/ws.py → chat_service → run_stage_chat() → Cody
```

### 8.2 Chat 准备

`chat_service.prepare_stage_chat()` 委托给 `agent_executor.prepare_chat()`：

```python
@dataclass
class StageChatContext:
    session_id: str
    cody_client: AsyncCodyClient
    cody_session_id: str | None      # 复用之前的 Session
    on_tool_result: Callable | None  # 文件写入检测
    language: str | None
    system_prefix: str | None        # Chat 系统前缀
```

### 8.3 Chat 执行

`run_stage_chat()` 是一个异步生成器，逐个 yield 事件：

1. 前端发送 Chat 消息 → WS Router 接收
2. 调用 `prepare_stage_chat()` 构建上下文
3. 调用 `run_stage_chat()` 流式执行
4. 每个事件通过 `send_to(ws, "chat:{req_id}", event)` 推送
5. 事件同时写入 `.jsonl` 日志

### 8.4 Chat 系统前缀

每个 Agent 有专门的 Chat 前缀，引导 AI 聚焦当前阶段：

| Agent | 前缀作用 |
|-------|---------|
| Plan | 引导 AI 修改 plan.md |
| Todo Split | 引导 AI 修改 todo.json |
| Todo Exec | 引导 AI 修改当前 Todo 的代码 |
| Review | 引导 AI 修改代码文件 |

---

## 九、Cody Session 复用策略

### 9.1 策略总览

| 场景 | 策略 | 原因 |
|------|------|------|
| 项目知识生成 | 每种知识类型独立 Session | 可并发执行 |
| 技术方案 | 独立 Session | 新对话 |
| 任务拆解 | **复用 Plan 的 Session** | 保持上下文连续性 |
| Todo 执行 | 每个 Todo 独立 Session | 互不干扰 |
| 代码审查 | 独立 Session | 新对话 |
| 阶段 Chat | **复用该阶段的 Session** | 保持对话连续性 |

### 9.2 复用实现

以 TodoSplitAgent 为例：

```python
class TodoSplitAgent(AgentConfig):
    async def resolve_cody_session_id(self, ctx):
        # 查找 Plan 阶段的 cody_session_id
        result = await ctx.db.execute(
            select(Session.cody_session_id).where(
                Session.task_id == ctx.entity_id,
                Session.type == "plan",
            )
        )
        return result.scalar()  # 返回 Plan 的 cody_session_id
```

效果：Todo 拆解时 AI 能"记住"之前的方案讨论，生成更准确的 Todo 列表。

---

## 十、日志持久化

### 10.1 存储格式

每个 Session 对应一个 `.jsonl` 文件：

```
~/.daiflow/sessions/{safe_filename(session_id)}.jsonl
```

文件名转换：将 session_id 中的特殊字符（`:` `/` `*` 等）替换为 `_`。

### 10.2 日志内容

每行一个 JSON 对象，包含时间戳：

```jsonl
{"type": "user_message", "ts": "2026-03-14T10:00:00", "text": "..."}
{"type": "text_delta", "ts": "2026-03-14T10:00:01", "text": "..."}
{"type": "tool_call", "ts": "2026-03-14T10:00:02", "tool_name": "read_file", "args": {...}}
{"type": "tool_result", "ts": "2026-03-14T10:00:03", "content": "..."}
{"type": "plan_updated", "ts": "2026-03-14T10:00:04", "content": "..."}
{"type": "done", "ts": "2026-03-14T10:00:05", "usage": {...}}
```

### 10.3 三种数据访问模式

| 方式 | API | 特点 |
|------|-----|------|
| DB 快照 | `GET /api/sessions/{id}/status` | 轻量，只有状态 + 错误信息 |
| 日志回放 | `GET /api/sessions/{id}/logs` | 完整事件流，重启后可用 |
| 实时推送 | `WS subscribe session:{id}` | WebSocket 实时事件 |

---

## 十一、关键配置常量

来自 `daiflow/config.py`：

```python
DAIFLOW_HOME = Path(os.environ.get("DAIFLOW_HOME", Path.home() / ".daiflow"))
SESSIONS_DIR = DAIFLOW_HOME / "sessions"
FILE_WRITE_TOOLS = frozenset({"write_file", "edit_file", "create_file"})
STREAM_TIMEOUT_SECONDS = 300          # 5 分钟流超时
MAX_TOOL_CALL_ARGS = 200              # 产物检测参数缓存上限
LOG_RETENTION_DAYS = 30               # 日志保留天数
MAX_CONCURRENT_CHATS = 5              # 每个 WS 连接最大并发 Chat 数

LANGUAGE_INSTRUCTIONS = {
    "zh": "[IMPORTANT: 请用中文(简体)生成所有输出内容...]",
    "en": "[IMPORTANT: Please write ALL output in English.]",
}
```
