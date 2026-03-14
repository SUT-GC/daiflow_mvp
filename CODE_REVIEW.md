# DaiFlow MVP 代码审查报告

> 审查日期：2026-03-13
> 代码规模：后端 ~4,300 行 Python | 前端 ~7,800 行 TS/TSX/CSS | 测试 ~2,600 行 Python
> 测试状态：196 tests passed (全部通过)

---

## 总体评价：6.5 / 10

DaiFlow 作为一个 MVP 阶段的项目，展现了合理的架构设计和清晰的开发规划。FastAPI + React 的技术选型恰当，WebSocket 实时通信架构设计得当，状态机驱动的工作流模式是亮点。但代码中存在若干安全隐患、数据一致性风险和测试覆盖不足的问题，需要在进入生产前重点解决。

---

## 做得好的地方

1. **架构设计清晰**：SessionRunner → WSManager → WebSocket 的统一推送模式，使得所有 AI 交互共享一致的数据流。Channel-based pub/sub 的 WebSocket 协议设计优雅。

2. **状态机驱动工作流**：使用 `transitions` 库实现 `TaskMachine` 和 `TodoMachine`，状态流转有明确的条件守卫，文档注释中的状态图清晰直观。

3. **文档充实**：CLAUDE.md 和技术方案文档详尽，对新人理解项目架构有很大帮助。Key API Routes、Status Enums、Session Architecture 等关键信息一目了然。

4. **后端测试基础扎实**：196 个测试全部通过，覆盖了 models、API CRUD、WebSocket 基本行为、配置和工作流状态机。`conftest.py` 的 fixture 设计合理（内存 SQLite + ASGI transport）。

5. **国际化框架**：前端建立了 `useLocale` + `i18n` 的多语言支持体系，中英文翻译文件结构清晰。

6. **项目配置合理**：Alembic 迁移使用 `render_as_batch=True` 正确支持 SQLite，`DAIFLOW_HOME` 环境变量解耦了存储路径。

---

## 需要改进的问题

### 严重 (Critical) — 必须修复

#### C1. 安全：API Key 可被掩码值覆盖
**文件**：`daiflow/routers/settings.py`
**问题**：`GET /api/settings` 返回掩码后的 API key（如 `sk-12****abcd`）。如果前端将该值原样回传给 `PUT /api/settings`，真实 key 被掩码字符串覆盖，导致 Cody SDK 连接失败。
**建议**：`update_settings` 中检测掩码模式，若值匹配 `*` 通配符则跳过更新：
```python
if "cody_api_key" in data and "****" in data["cody_api_key"]:
    del data["cody_api_key"]  # 保留原值
```

#### C2. 安全：Task 更新绕过状态机
**文件**：`daiflow/routers/tasks.py:111-113`
**问题**：`update_task` 使用 `setattr` 遍历所有非空字段并直接赋值。如果 `TaskUpdate` schema 包含 `status` 字段，客户端可以直接设置任意状态值，绕过 `TaskMachine` 的状态守卫。
**建议**：在 `setattr` 循环中排除工作流控制字段（`status`、`plan_cody_session_id` 等），或在 `TaskUpdate` schema 中移除这些字段。

#### C3. 安全：`serve_spa` 路径遍历风险
**文件**：`daiflow/main.py:119-125`
**问题**：`full_path` 参数来自 URL，直接用于构造文件路径。虽然 `StaticFiles` 中间件本身是安全的，但手动 `FileResponse` 分支没有验证 `file_path` 是否在 `static_dir` 内。`../../etc/passwd` 等路径可能逃逸。
**建议**：添加路径验证：
```python
file_path = (static_dir / full_path).resolve()
if not file_path.is_relative_to(static_dir.resolve()):
    return FileResponse(static_dir / "index.html")
```

#### C4. 数据一致性：Todo 替换非原子操作
**文件**：`daiflow/services/task_service.py:356-364`
**问题**：`sync_todos_from_file` 先删除所有 todo 再插入新的。如果进程在删除后、插入前崩溃，所有 todo 数据永久丢失。
**建议**：使用事务内的先插后删策略，或在数据库层面使用 SAVEPOINT。

#### C5. 数据一致性：Skill 同步非原子操作
**文件**：`daiflow/services/skill_service.py:22`
**问题**：`sync_skills_to_task` 先 `shutil.rmtree(dst)` 再 `shutil.copytree(src, dst)`。中断时 skill 数据永久丢失。
**建议**：先复制到临时目录，然后原子重命名。

#### C6. Bug：`done_finished_at` 变量可能未绑定
**文件**：`daiflow/session_runner.py:241`
**问题**：如果 Cody stream 不产生 `done` chunk（空流或立即出错），`done_finished_at` 未赋值，访问时抛出 `UnboundLocalError`。
**建议**：在循环前初始化 `done_finished_at = None`，并在后续使用时做空值检查。

---

### 建议 (Important) — 应该修复

#### I1. Layer 1 失败时后续 Session 永远停留在 WAITING
**文件**：`daiflow/services/project_service.py:353-358`
**问题**：Layer 1 失败时直接发布 `done` 事件并返回，Layer 2-4 的 session 永远保持 WAITING 状态，不会被清理。
**建议**：Layer 1 失败时，将后续 layer 的 session 批量标记为 FAILED。

#### I2. 后台任务引用未保存
**文件**：`daiflow/main.py:68`、`daiflow/services/repo_monitor.py:89`
**问题**：`asyncio.create_task()` 返回值未保存，task 可能被垃圾回收，异常被静默丢弃。
**建议**：维护一个 `background_tasks: set[asyncio.Task]` 集合，使用 `task.add_done_callback(tasks.discard)` 模式。

#### I3. WebSocket publish 并发迭代不安全
**文件**：`daiflow/ws_manager.py:60`
**问题**：`for ws in conns:` 迭代 live set 时，`await ws.send_json()` 让出控制权，其他协程可能同时修改 `_channels`，导致 `RuntimeError: Set changed size during iteration`。
**建议**：迭代 `list(conns)` 快照而非 live set。

#### I4. 计划/Todo 触发缺少状态守卫
**文件**：`daiflow/routers/tasks.py:215-241`
**问题**：`trigger_plan` 和 `trigger_todo` 没有验证 task 是否处于合法的工作流状态就启动后台任务。一个已在 CODING 状态的 task 可以被重新触发 plan 生成。
**建议**：调用前先通过 `TaskMachine` 验证状态转换的合法性。

#### I5. `ToolCallTracker` 在 SessionRunner 实例间共享
**文件**：`daiflow/session_runner.py`
**问题**：`_tracker` 是 SessionRunner 实例属性，但当 runner 在 plan + todo 阶段复用时，session A 的 tool_call ID 可能错误地影响 session B 的事件增强。
**建议**：在每次 `run()` 调用开始时重置 tracker。

#### I6. 前端完全没有测试
**文件**：`frontend/` 全目录
**问题**：0 个前端测试文件，没有 vitest/jest 配置。核心 hooks（`useStageChat`、`usePlanStage`、`useCodingStage`）和 WebSocket 客户端完全无覆盖。
**建议**：至少为核心 hooks 和 API 层添加单元测试，安装 vitest + @testing-library/react。

#### I7. 核心后端功能测试缺失
**问题**：以下核心模块无测试覆盖：
- `SessionRunner.run()` — AI 编排核心
- `chat_service.py` — 阶段对话
- `cody_service.py` — Cody SDK 封装
- `git_service.py` — Git 操作
- Task diff/submit-MR API 端点
**建议**：优先为 `SessionRunner.run()` 添加集成测试（mock Cody SDK），其次覆盖 git_service。

#### I8. `pyproject.toml` 缺少关键依赖
**文件**：`pyproject.toml`
**问题**：`requirements.txt` 包含 `alembic>=1.13.0` 和 `transitions>=0.9.0`，但 `pyproject.toml` 中未列出。`pip install -e .` 不会安装这两个运行时必需的包。
**建议**：将所有 `requirements.txt` 中的依赖同步到 `pyproject.toml` 的 `dependencies` 列表。

#### I9. Repo Monitor 部分失败标记为成功
**文件**：`daiflow/services/repo_monitor.py:71`
**问题**：状态判断逻辑 `FAILED if error_msgs and not changed` 意味着如果同时有错误和成功的 repo，整体被标记为 SUCCESS。
**建议**：添加 `PARTIAL` 状态或在有错误时始终标记为 FAILED。

#### I10. 文档与代码不一致
**问题**：
- CLAUDE.md 说 6 张表，实际 8 张（缺 `jobs`、`job_runs`）
- CLAUDE.md 说 `TodoStatus` 有 4 个值，实际有 5 个（缺 `SKIPPED=4`）
- CLAUDE.md 文档说 `tasks` 表有 `plan_cody_session_id`/`review_cody_session_id`，实际已改为 `Session.task_id` FK
- CLAUDE.md 未记录 `Todo.commit_before`/`commit_after` 和 `Session.task_id`
- README 的项目结构树缺少 `workflow/`、`routers/jobs.py`、`services/repo_monitor.py`
**建议**：全面更新 CLAUDE.md 和 README.md 的 schema 和结构描述。

---

### 可选 (Nice to Have) — 建议改进

#### N1. 前端硬编码中文破坏国际化
- `components/Shell/Topbar.tsx:5-14`：`STATUS_CONFIG` 全部中文标签，不走 i18n
- `components/ChatPanel/ChatPanel.tsx:29`：`展开`/`收起` 硬编码

#### N2. 前端变量名遮蔽 `t`（翻译函数）
- `ProjectInit.tsx:97,104`、`Tasks.tsx:36`、`ReviewStage.tsx:27`、`Debug.tsx:133`：`.map(t => ...)` 遮蔽外层 `useLocale()` 的 `t`

#### N3. 前端使用 `alert()`/`confirm()` 而非 Modal
- `ProjectForm.tsx:73`、`Tasks.tsx:57`、`ReviewStage.tsx:59`、`Projects.tsx:53`

#### N4. `taskId!` 非空断言不安全
- `PlanStage.tsx:37`、`TodoStage.tsx:41`、`CodingStage.tsx:58`、`ReviewStage.tsx:79`

#### N5. 同步文件 I/O 在 async 函数中
- `skill_service.py`、`chat_service.py`、`project_service.py` 中 `path.read_text()`、`path.exists()`、`shutil` 操作应使用 `asyncio.to_thread()`

#### N6. chat_service.py 四个阶段分支大量重复代码
- plan/todo/todo_exec/review 的 `prepare_stage_chat` 分支模式几乎相同，应提取共享 helper

#### N7. 私有函数跨模块导入
- `_append_log`（session_runner → project_service）、`_resolve_task_roots`（task_service → chat_service）应去掉前缀 `_` 表示公开接口

#### N8. 死代码清理
- `pipeline.py`：未使用的 `select`、`update`、`get_language_setting`、`get_project_dir`、`ProjectRepo` 导入
- `settings.py:11`：`SETTING_KEYS` 定义后未引用
- `project_service.py:130`：`_build_repos_context` 的 `allowed_roots` 参数未使用

#### N9. WebSocket 重连上限过低
- `WebSocketClient.ts:46`：`maxReconnectAttempts = 5`，断线 5 次后永久放弃，无重置机制

#### N10. `conftest.py` 临时目录未清理
- `_tmpdir = tempfile.mkdtemp()` 在模块级创建，测试结束后不删除，每次运行遗留孤儿目录

#### N11. Context Provider 值未 memo 化
- `App.tsx` 中 `ThemeContext` 和 `LocaleContext` 的 value prop 每次渲染创建新对象，导致整棵组件树不必要地重渲染

#### N12. `window.location.reload()` 反模式
- `ProjectInit.tsx:131,143`：应使用 React 状态更新而非硬刷新

#### N13. `setattr` 批量更新的 `except Exception: pass`
- `tasks.py:299`、`todos.py:102-103`：bare except 静默吞掉错误，应至少记录日志

#### N14. 状态机缺少反向状态转换
- `TaskMachine`：无法从 `plan_locked` 回退到 `planning`，无法从 `coding` 回退到 `todo_ready`
- `TodoMachine`：无法从 `done` 重新执行，无法从 `skipped` 恢复

---

## 架构总结

```
                ┌─────────────────────────────────────────┐
                │               整体架构  ✅ 合理          │
                │  React SPA ←→ FastAPI ←→ Cody SDK       │
                │      ↕ WebSocket (pub/sub)  ↕ SQLite    │
                └─────────────────────────────────────────┘

  ✅ 目录结构清晰（routers / services / workflow 三层分离）
  ✅ 模块职责基本单一（但 task_service.py ~500行偏大）
  ⚠️ 循环依赖通过 late import 规避（main.py, session_runner.py）
  ⚠️ 私有函数跨模块调用破坏封装边界
  ✅ 前端组件/hooks/pages 组织清晰
  ⚠️ 前端无状态管理库（全靠 hooks + props drilling），随功能增长可能难以维护
```

| 维度 | 评分 | 说明 |
|------|------|------|
| 目标一致性 | 7/10 | 核心4阶段工作流实现完整，文档与代码存在滞后但不影响功能 |
| 架构设计 | 7/10 | 整体架构合理，WebSocket 设计优秀，部分模块职责过大 |
| 代码质量 | 6/10 | 存在安全隐患和数据一致性风险，错误处理不够完善 |
| 可维护性 | 6/10 | 文档基础好但过时，前端无测试，核心后端逻辑测试覆盖不足 |

---

*本报告由 Claude Code 自动生成，基于对全部源代码、测试和文档的逐文件审阅。*
