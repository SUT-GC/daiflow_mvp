# DaiFlow MVP 代码审查报告

**审查日期**: 2026-03-14
**审查范围**: 全仓库（后端 Python + 前端 TypeScript/React + 测试 + 文档）

## 总体评价：7.5 / 10

对于一个早期 MVP 阶段的项目，DaiFlow 展现出了**扎实的架构设计能力和较高的工程素养**。后端采用清晰的分层架构（Router → Service → Model），前端遵循 React 最佳实践，核心抽象（SessionRunner、WSManager、Workflow 状态机）设计精巧。全部 211 个测试通过，说明核心功能有较好的质量保障。

---

## 做得好的地方

### 1. 架构设计清晰，层次分明
- **后端分层**：`routers/` → `services/` → `models.py` → `database.py`，职责边界清楚，无循环依赖
- **内部依赖图**干净：依赖方向始终为 routers → services → models/config，没有反向引用
- **Workflow 状态机**（`transitions` 库）将状态转换逻辑从路由层抽离，`TaskWorkflow` 和 `TodoWorkflow` 设计优雅，带条件守卫（`_has_todos`、`_prev_todo_completed`）

### 2. SessionRunner 统一抽象
- 所有 AI 交互统一通过 `SessionRunner.run()` → `.jsonl` 日志 → DB 状态 → WebSocket 推送
- `_ToolCallTracker` 巧妙地通过缓存 tool_call args 来丰富 tool_result 事件
- `make_file_write_detector` 工厂函数实现了灵活的文件写入检测回调机制
- `run_stage_chat` 作为异步生成器，复用核心逻辑，设计简洁

### 3. WebSocket 设计精良
- 单连接多路复用（channel-based pub/sub）避免了连接爆炸
- 前端 `WebSocketClient` 实现了自动重连（指数退避）、keepalive ping、断开时队列缓存
- 后端 `WSManager` 自动清理死连接，`cleanup_channel` 防止内存泄漏
- 并发 chat 限制（`MAX_CONCURRENT_CHATS = 5`）防止资源耗尽

### 4. 测试覆盖较好
- 211 个测试，覆盖 models、API 路由、WebSocket、SessionRunner、Workflow 等核心模块
- `conftest.py` 正确使用 in-memory SQLite + `get_background_db` 双重 mock
- 测试用 `httpx.AsyncClient` + ASGI transport，无需启动服务器

### 5. 前端工程化
- `useStageChat` hook 统一了 4 个阶段的 chat 逻辑，使用 `requestAnimationFrame` 节流避免高频渲染
- `useSession` hook 的日志累积 + rAF 批量更新策略正确
- 枚举与后端保持同步（`types/enums.ts`）
- API 层类型安全，统一的 `request<T>()` 泛型封装

### 6. 安全意识
- `git_service.py` 中的 `validate_branch_name()` 防止命令注入
- Settings API 掩码了 API key，且跳过掩码值的更新
- SPA fallback 有路径遍历防护（`is_relative_to` 检查）
- `cody_service.py` 的 `strict_read_boundary(True)` + prompt 级路径边界双重限制

---

## 需要改进的问题

### 严重问题 (P0)

#### 1. `session_runner.py:241` — `done_finished_at` 可能未定义

```python
# 第 203 行定义 done_finished_at
done_finished_at = _now()

# 第 241 行使用，但如果流中没有 "done" chunk，会 NameError
.values(status=SessionStatus.DONE, ..., finished_at=done_finished_at)
```

**问题**：如果 Cody SDK 流异常终止（没有发送 `done` chunk 就结束），`done_finished_at` 从未赋值，但代码仍会到达第 234 行（因为没有抛异常），导致 `NameError`。

**建议**：在流循环前初始化 `done_finished_at = _now()`，或在流结束后检查是否收到了 done 事件。

#### 2. `conftest.py:60-63` — `get_background_db` mock 不完整

```python
with patch("daiflow.database.get_background_db", override_get_background_db), \
     patch("daiflow.services.task_service.get_background_db", override_get_background_db), \
     patch("daiflow.services.project_service.get_background_db", override_get_background_db), \
     patch("daiflow.workflow.pipeline.get_background_db", override_get_background_db):
```

**问题**：`daiflow.main._recover_interrupted_sessions`、`daiflow.services.repo_monitor` 也使用了 `get_background_db`，但未被 patch。虽然目前的测试因为跳过了 lifespan 和 repo_monitor 没有触发问题，但如果添加相关测试会失败。

**建议**：考虑改为统一 patch `daiflow.database.get_background_db` 一处，让所有导入该模块的地方都受影响，或使用 `unittest.mock.patch.object` 针对模块级变量。

#### 3. `api/index.ts:146` — `retryInit` 函数名重复导出

```typescript
export const retryInit = (id: string) =>
  request<{ ok: boolean }>(`/projects/${id}/init/retry`, { method: 'POST' })
// ... 后面又有
export const retryInit = (id: string) =>  // 第 147 行
  request<{ ok: boolean; status: number }>(`/tasks/${id}/retry-init`, { method: 'POST' })
```

**问题**：两个同名 `retryInit` 导出，后者会覆盖前者。项目 init retry 的 API 调用将无法正确触达。

**建议**：重命名为 `retryProjectInit` 和 `retryTaskInit`。

---

### 建议改进 (P1)

#### 4. `task_service.py:374` — `_insert_todos` 是同步函数但操作 AsyncSession

```python
def _insert_todos(db: AsyncSession, task_id: str, todos_data: list[dict]):
    for item in todos_data:
        db.add(Todo(...))
```

**问题**：`db.add()` 本身不是 async 操作所以不会报错，但函数签名让人误以为它是同步的，而它依赖 AsyncSession。更关键的是，调用后没有 `await db.flush()`，依赖外部 `await db.commit()` 才生效，这个隐式耦合容易出错。

**建议**：改为 `async def` 并在内部 `await db.flush()`，或在文档注释中明确说明调用方必须 commit。

#### 5. `ws_manager.py` — `publish` 中的并发安全性

```python
for ws in conns:  # 遍历 set
    ...
    dead.append(ws)
for ws in dead:
    self.disconnect(ws)  # 修改 _channels[channel] 这个 set
```

**问题**：虽然当前实现是先收集 dead 再批量处理（安全的），但 `disconnect` 内部会修改 `_channels` 字典，如果并发调用 `publish` 可能导致问题。`WSManager` 没有并发保护。

**建议**：由于 Python asyncio 是协作式多任务，且 `publish` 内部有 `await`（让出控制权），建议在 `_channels` 操作处考虑加锁，或者在文档中明确标注 WSManager 非线程安全。

#### 6. 前端 WebSocket 最大重连 5 次后不再恢复

`WebSocketClient.ts:46` — `maxReconnectAttempts = 5`

**问题**：达到上限后用户需要手动刷新页面。对于一个长时间运行的开发工具来说，网络中断恢复不够鲁棒。

**建议**：达到上限后切换为低频重试（如每 60 秒一次），或提供 UI 提示让用户手动重连。

#### 7. `review_service.py:85-125` — `submit_mr` 没有事务性保障

**问题**：如果 commit 成功但 push 失败（网络问题），代码已经提交到本地但没有推送，用户可能不知道。虽然有 `results` 返回状态，但前端没有明确处理部分失败的场景。

**建议**：在 push 失败时提供更明确的恢复指引（"代码已提交到本地分支，请手动执行 git push"）。

#### 8. `project_service.py:278-282` — Layer 1 `asyncio.gather` 的异常处理

```python
await asyncio.gather(
    run_simple_task(..., _do_skill_fetch),
    run_simple_task(..., _do_repo_clone),
    return_exceptions=True,  # 异常被吞掉，返回结果被丢弃
)
```

**问题**：`return_exceptions=True` 意味着异常作为返回值而不是抛出，但返回结果被直接丢弃了。

**建议**：要么显式检查结果，要么移除 `return_exceptions=True` 并用 try/except 包裹。

#### 9. `schemas.py` — 缺少输入验证

`TaskCreate.branch` 和 `RepoCreate.git_url` 等字段没有 Pydantic 验证器。

**问题**：虽然 `git_service.validate_branch_name()` 在使用时验证，但恶意/错误输入会一路存到数据库才在后续操作中失败。

**建议**：在 Pydantic schema 层添加 `@field_validator("branch")` 进行早期验证。

#### 10. `main.py:118-126` — SPA fallback 路由可能拦截非 API 路由

```python
@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
```

**问题**：如果有新的非 `/api/` 前缀的路由被添加（如 `/health`），可能会被 SPA fallback 拦截。

**建议**：添加 `if full_path.startswith("api/"):` 保护，或将 SPA fallback 改为只在 static_dir 存在 index.html 时注册。

---

### 可选改进 (P2)

#### 11. 文档与代码不一致

- CLAUDE.md 提到 Task 模型有 `plan_cody_session_id` 和 `review_cody_session_id` 字段，但实际代码中没有
- `TodoStatus` 枚举：CLAUDE.md 记录 4 个值，实际有 5 个（多了 `SKIPPED = 4`）
- CLAUDE.md 文档的 DB Schema 标注为 6 表，实际已有 8 表（增加了 `jobs` 和 `job_runs`）

#### 12. 后端缺少请求限流

所有 POST 端点没有限流保护。如 `POST /api/tasks/{id}/plan` 可以被快速重复调用。

#### 13. 日志文件无清理机制

`.jsonl` 日志文件会持续增长，没有过期清理机制。

#### 14. 前端缺少测试

47 个 TypeScript/TSX 文件（3594 行代码），没有任何前端测试。

#### 15. `database.py:7` — 全局 engine 在模块加载时创建

模块导入时即创建 engine，如果 `DAIFLOW_HOME` 在导入后才被设置，会使用默认路径。

#### 16. 重复的 "fetch repos + resolve roots" 模式

`task_service.py`、`chat_service.py`、`review_service.py` 中都有类似代码，可以抽象为 `get_task_context()`。

---

## 代码量统计

| 模块 | 文件数 | 代码行数 |
|------|--------|---------|
| 后端 Python (daiflow/) | 32 | ~4430 |
| 测试 (tests/) | 15 | ~2886 |
| 前端 TypeScript/TSX | 47 | ~3594 |
| **合计** | **94** | **~10,910** |

## 维度评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构设计 | 8/10 | 分层清晰、抽象合理、无循环依赖 |
| 代码质量 | 7/10 | 命名规范、安全意识好，但有少量潜在运行时错误 |
| 可维护性 | 7.5/10 | 文档完善（CLAUDE.md 详尽），新人可快速上手 |
| 测试覆盖 | 7/10 | 后端覆盖好（211 tests），前端完全缺失 |
| 目标一致性 | 8/10 | 代码实现与文档描述高度一致，少量文档滞后 |
