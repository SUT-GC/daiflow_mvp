# DaiFlow MVP 验收文档

> 版本：v0.1 MVP
> 更新时间：2026-03-11

---

## 一、验收范围

本文档覆盖 DaiFlow v0.1 MVP 的全部功能验收，包括：

1. 应用启动与配置
2. 项目管理（创建、编辑、删除、初始化）
3. 任务管理（创建、列表、删除）
4. 开发流程四阶段（技术方案 → 任务拆解 → 编写代码 → 代码审查 & 提交）

---

## 二、前置条件

| 项目 | 要求 |
|------|------|
| Python | 3.11+ |
| Node.js | 16+ |
| Git | 已安装，且有可用的本地代码仓库 |
| AI 模型 | 可用的模型 API（model 名称、base_url、api_key） |
| 测试仓库 | 至少准备一个前端仓库 + 一个后端仓库，已 clone 到本地 |

---

## 三、验收用例

### 3.1 应用启动

| 编号 | 用例 | 操作步骤 | 预期结果 | 通过 |
|------|------|---------|---------|------|
| S-01 | 首次启动 | 执行 `daiflow start` | 1. 自动创建 `~/.daiflow/` 目录<br>2. 初始化 SQLite 数据库（6 张表）<br>3. 启动 FastAPI 服务，监听 `http://localhost:8000`<br>4. 自动打开浏览器 | ☐ |
| S-02 | 首次访问重定向 | 浏览器访问 `http://localhost:8000` | 未配置 AI 模型时，自动跳转到 `/settings` 配置页 | ☐ |
| S-03 | 再次启动 | 关闭服务后再次执行 `daiflow start` | 不重复创建目录和数据库，正常启动，数据保留 | ☐ |

---

### 3.2 全局设置

| 编号 | 用例 | 操作步骤 | 预期结果 | 通过 |
|------|------|---------|---------|------|
| C-01 | 配置页面展示 | 进入 `/settings` 页面 | 页面包含三个输入项：Model、Base URL、API Key，以及主题切换（Dark/Light） | ☐ |
| C-02 | 保存配置 | 填写 Model、Base URL、API Key，点击保存 | 1. 保存成功提示<br>2. API Key 脱敏展示（如 `sk-***xxx`）<br>3. 侧边栏底部显示模型名称和连接状态 | ☐ |
| C-03 | 配置校验 | 不填写必填项直接保存 | 提示必填字段不能为空 | ☐ |
| C-04 | 配置完成后路由放行 | 配置保存后访问 `/`（项目列表） | 正常进入项目列表页，不再跳转设置页 | ☐ |
| C-05 | 主题切换 | 在设置页切换 Dark / Light 主题 | 全局 UI 实时切换主题配色 | ☐ |

---

### 3.3 项目管理

| 编号 | 用例 | 操作步骤 | 预期结果 | 通过 |
|------|------|---------|---------|------|
| P-01 | 项目列表 | 进入项目管理页 | 以卡片网格展示已有项目，每个卡片显示项目名称、描述、关联仓库标签 | ☐ |
| P-02 | 创建项目 | 点击「新建项目」卡片 | 进入创建页面，包含：项目名称、项目描述、仓库列表（可添加多个）、Skill 名称列表 | ☐ |
| P-03 | 仓库配置 | 在创建页面添加仓库 | 每个仓库可配置：Git 地址、本地路径、仓库类型（前端/后端/自定义）、仓库介绍 | ☐ |
| P-04 | 多仓库支持 | 添加 2 个以上仓库 | 支持动态添加和删除仓库条目 | ☐ |
| P-05 | 自定义仓库类型 | 仓库类型选择「自定义」 | 出现额外的文本框，允许手动输入类型名称 | ☐ |
| P-06 | 保存并初始化 | 填写完项目信息，点击保存 | 1. 项目创建成功，数据写入 projects 和 project_repos 表<br>2. 自动触发项目初始化流程 | ☐ |
| P-07 | Skill 拉取 | 项目初始化 - Skill 拉取 | 根据配置的 skill 名称列表，从 Skill 中心拉取文件到 `projects/{id}/skills/` | ☐ |
| P-08 | 知识库生成 - 第一层 | 项目初始化 - AI 分析 | 并发生成 4 个第一层知识点：<br>- `frontend_structure`（前端仓库）<br>- `backend_structure`（后端仓库）<br>- `business_flow`（前端仓库）<br>- `component_usage`（前端仓库）<br>每个生成独立 Cody session | ☐ |
| P-09 | 知识库生成 - 第二层 | 第一层全部完成后 | 并发生成 4 个第二层知识点：<br>- `module_overview`<br>- `data_entity`<br>- `api_interaction`<br>- `dependencies`<br>均基于前端+后端跨仓库整合 | ☐ |
| P-10 | 知识库生成 - 索引 | 两层全部完成后 | 生成 `projects/{id}/project.md` 索引文件，包含项目信息和所有知识文件路径 | ☐ |
| P-11 | SKILL.md 格式 | 检查生成的 SKILL.md 文件 | 每个文件包含 YAML frontmatter（name、description、`user-invocable: false`）+ Markdown 正文 | ☐ |
| P-12 | 初始化进度展示 | 初始化过程中观察页面 | SSE 实时推送每个知识点的生成进度和 Cody 执行日志 | ☐ |
| P-13 | 初始化 session 记录 | 检查数据库 | `project_init_sessions` 表记录每个知识点的 session_id 和 status | ☐ |
| P-14 | 编辑项目 | 在项目列表点击已有项目编辑 | 可修改项目名称、描述、仓库列表、Skill 名称 | ☐ |
| P-15 | 删除项目 | 删除一个项目 | 1. 数据库中删除 project 和关联的 project_repos 记录<br>2. 本地 `projects/{id}/` 目录清理 | ☐ |

---

### 3.4 任务管理

| 编号 | 用例 | 操作步骤 | 预期结果 | 通过 |
|------|------|---------|---------|------|
| T-01 | 任务列表 | 进入任务管理页 | 展示所有任务，显示任务名称、所属项目、当前状态 | ☐ |
| T-02 | 创建任务 | 点击创建任务 | 表单包含：任务名称、关联项目（选择）、任务描述、开发分支、PRD（Markdown）、技术方案（Markdown） | ☐ |
| T-03 | 任务初始化 - Skill 同步 | 保存任务 | 将项目 `skills/` 目录和 `project.md` 同步到 `tasks/{task_id}/.cody/skills/` 和 `tasks/{task_id}/project.md` | ☐ |
| T-04 | 任务初始化 - 切分支 | 保存任务 | 在所有关联仓库本地路径执行 `git checkout -b {branch}` 或 `git checkout {branch}` | ☐ |
| T-05 | 任务状态流转 | 创建任务后 | 任务状态从 created(0) → initializing(1) → planning(2)，自动进入技术方案阶段 | ☐ |
| T-06 | 删除任务 | 删除一个任务 | 数据库中删除 task 及关联的 todos 记录，清理本地 `tasks/{task_id}/` 目录 | ☐ |

---

### 3.5 开发流程 - 阶段一：技术方案

| 编号 | 用例 | 操作步骤 | 预期结果 | 通过 |
|------|------|---------|---------|------|
| F1-01 | 页面布局 | 进入任务开发流程 | 1. 顶部显示四阶段进度条，当前高亮「技术方案」<br>2. 左侧展示 plan.md 内容区<br>3. 右侧展示 AI 对话框 + SSE 执行日志 | ☐ |
| F1-02 | 自动生成方案 | 进入技术方案阶段 | AI 自动开始生成技术方案：<br>1. SSE 实时推送生成进度（text_delta、tool_call、tool_result 事件）<br>2. 左侧实时更新 plan.md 内容<br>3. 完成后收到 done 事件，包含 session_id | ☐ |
| F1-03 | 方案内容质量 | 查看生成的 plan.md | 包含：前端改动、后端改动、数据变更、影响范围、实施顺序 | ☐ |
| F1-04 | AI 对话调整 | 在右侧对话框输入修改建议 | 1. AI 理解用户反馈<br>2. 修改反映到 plan.md<br>3. 使用相同的 session_id 保持上下文 | ☐ |
| F1-05 | 多轮对话 | 连续发送多条修改意见 | 对话历史正常保留，AI 基于完整上下文回复 | ☐ |
| F1-06 | 锁定方案 | 点击「锁定方案」按钮 | 1. 任务状态变更为 plan_locked(3)<br>2. plan.md 不可再编辑<br>3. 自动进入任务拆解阶段 | ☐ |

---

### 3.6 开发流程 - 阶段二：任务拆解

| 编号 | 用例 | 操作步骤 | 预期结果 | 通过 |
|------|------|---------|---------|------|
| F2-01 | 页面布局 | 进入任务拆解阶段 | 1. 顶部进度条高亮「任务拆解」<br>2. 左侧展示 todo 列表<br>3. 右侧展示 AI 对话框 | ☐ |
| F2-02 | 自动生成 Todo | 锁定方案后 | AI 基于 plan.md 自动拆解，SSE 实时推送生成过程，使用与技术方案阶段相同的 session_id | ☐ |
| F2-03 | Todo 列表展示 | 生成完毕后 | 左侧展示有序的 todo 列表，每条包含序号、标题、详细描述 | ☐ |
| F2-04 | Todo 数据持久化 | 检查文件和数据库 | 1. `tasks/{task_id}/todo.json` 写入 JSON 格式 todo 列表<br>2. todos 数据库表中写入对应记录（seq、title、description、status=pending） | ☐ |
| F2-05 | AI 对话调整 | 在对话框中要求调整 todo | AI 修改同步到 todo.json 和数据库 todos 表 | ☐ |
| F2-06 | 确认执行编码 | 点击「执行编码」按钮 | 1. 任务状态变更为 todo_ready(4)<br>2. 进入编写代码阶段 | ☐ |

---

### 3.7 开发流程 - 阶段三：编写代码

| 编号 | 用例 | 操作步骤 | 预期结果 | 通过 |
|------|------|---------|---------|------|
| F3-01 | 页面布局 | 进入编写代码阶段 | 三栏布局：<br>1. 左侧：todo 列表，显示各 todo 状态<br>2. 中间：执行日志 + diff 展示区<br>3. 右侧：AI 对话框 | ☐ |
| F3-02 | 执行单个 Todo | 点击某个 todo 的执行按钮 | 1. todo 状态变为 running(1)<br>2. 任务状态变为 coding(5)<br>3. 中间区域 SSE 实时展示执行进度 | ☐ |
| F3-03 | Todo 独立 Session | 执行 todo | 每个 todo 有独立的 session_id，存储在 todos.session_id 字段 | ☐ |
| F3-04 | 执行结果展示 | todo 执行完成 | 1. 中间区域展示该 todo 产生的代码改动（diff 视图）<br>2. todo 状态变为 done(2)<br>3. 收到 SSE done 事件 | ☐ |
| F3-05 | 执行失败处理 | todo 执行出错 | 1. todo 状态变为 failed(3)<br>2. 中间区域展示错误信息<br>3. 收到 SSE error 事件 | ☐ |
| F3-06 | Todo 后对话 | todo 执行完成后在右侧对话框发消息 | 可与 AI 沟通补充或调整该 todo 的改动结果，使用该 todo 的 session_id | ☐ |
| F3-07 | 顺序执行 | 依次执行多个 todo | 每个 todo 独立执行，前一个完成后再执行下一个，todo 间通过 plan.md 共享上下文 | ☐ |
| F3-08 | 全部完成 | 所有 todo 执行完毕 | 出现「下一步」按钮，可进入代码审查阶段 | ☐ |

---

### 3.8 开发流程 - 阶段四：代码审查 & 提交

| 编号 | 用例 | 操作步骤 | 预期结果 | 通过 |
|------|------|---------|---------|------|
| F4-01 | 页面布局 | 进入代码审查阶段 | 1. 顶部进度条高亮「代码审查」<br>2. 左侧展示整体 git diff（类似 GitHub MR 视图）<br>3. 右侧展示 AI 对话框 + 「生成 MR」按钮 | ☐ |
| F4-02 | Diff 展示 | 查看 diff 内容 | 1. 调用后端 `/api/tasks/{id}/diff` 获取所有关联仓库的 git diff<br>2. 使用 react-diff-viewer 渲染，支持 split/unified 两种模式<br>3. 支持语法高亮 | ☐ |
| F4-03 | 审查阶段对话 | 在对话框中提出修改意见 | AI 可以继续调整代码，diff 视图实时更新 | ☐ |
| F4-04 | 生成 MR | 点击「生成 MR」 | 1. AI 自动生成 commit message<br>2. 系统执行 git commit（所有关联仓库）<br>3. 系统执行 git push 到配置的开发分支<br>4. 任务状态变更为 done(7) | ☐ |
| F4-05 | 任务状态 reviewing | 进入审查阶段 | 任务状态为 reviewing(6) | ☐ |

---

### 3.9 SSE 流式推送

| 编号 | 用例 | 操作步骤 | 预期结果 | 通过 |
|------|------|---------|---------|------|
| E-01 | SSE 事件格式 | 在任意 SSE 流式阶段观察 | 事件格式为 `data: {JSON}\n\n`，包含以下类型：<br>- `text_delta`：文本增量，含 content 字段<br>- `tool_call`：工具调用，含 tool_name 和 args<br>- `tool_result`：工具结果，含 tool_name 和 content<br>- `done`：完成，含 session_id<br>- `error`：错误，含 message | ☐ |
| E-02 | SSE 连接建立 | 触发流式操作 | 前端通过 EventSource 建立连接，实时接收事件 | ☐ |
| E-03 | SSE 连接关闭 | 收到 done 事件 | 前端主动关闭 EventSource 连接 | ☐ |

---

### 3.10 API 接口验收

| 编号 | 接口 | 验证项 | 通过 |
|------|------|--------|------|
| A-01 | `GET /api/settings` | 返回所有配置，api_key 脱敏 | ☐ |
| A-02 | `PUT /api/settings` | 保存配置项到 settings 表 | ☐ |
| A-03 | `GET /api/settings/check` | 返回 `{"configured": true/false}` | ☐ |
| A-04 | `GET /api/projects` | 返回项目列表 | ☐ |
| A-05 | `POST /api/projects` | 创建项目及关联仓库 | ☐ |
| A-06 | `GET /api/projects/{id}` | 返回项目详情，包含仓库列表 | ☐ |
| A-07 | `PUT /api/projects/{id}` | 更新项目信息 | ☐ |
| A-08 | `DELETE /api/projects/{id}` | 删除项目及关联数据 | ☐ |
| A-09 | `POST /api/projects/{id}/init` | 触发项目初始化 | ☐ |
| A-10 | `GET /api/projects/{id}/init/stream` | SSE 推送初始化进度 | ☐ |
| A-11 | `GET /api/tasks` | 返回任务列表 | ☐ |
| A-12 | `POST /api/tasks` | 创建任务并执行初始化 | ☐ |
| A-13 | `GET /api/tasks/{id}` | 返回任务详情 | ☐ |
| A-14 | `DELETE /api/tasks/{id}` | 删除任务及关联 todos | ☐ |
| A-15 | `POST /api/tasks/{id}/lock-plan` | 锁定方案，status → 3 | ☐ |
| A-16 | `POST /api/tasks/{id}/start-coding` | 确认 todo，status → 4 | ☐ |
| A-17 | `POST /api/tasks/{id}/start-review` | 进入审查，status → 6 | ☐ |
| A-18 | `GET /api/tasks/{id}/plan/stream` | SSE 生成技术方案 | ☐ |
| A-19 | `POST /api/tasks/{id}/plan/chat` | 方案阶段对话，返回 JSON | ☐ |
| A-20 | `GET /api/tasks/{id}/todo/stream` | SSE 生成 todo 列表 | ☐ |
| A-21 | `POST /api/tasks/{id}/todo/chat` | 拆解阶段对话 | ☐ |
| A-22 | `GET /api/tasks/{id}/todos` | 返回 todo 列表 | ☐ |
| A-23 | `POST /api/todos/{id}/execute/stream` | SSE 执行单个 todo | ☐ |
| A-24 | `POST /api/todos/{id}/chat` | todo 执行后对话 | ☐ |
| A-25 | `GET /api/tasks/{id}/diff` | 返回整体 git diff | ☐ |
| A-26 | `POST /api/tasks/{id}/submit-mr` | 生成 commit message 并提交 MR | ☐ |

---

### 3.11 数据库验收

| 编号 | 用例 | 验证项 | 通过 |
|------|------|--------|------|
| D-01 | 表结构 | 确认 6 张表已正确创建：projects、project_repos、tasks、todos、settings、project_init_sessions | ☐ |
| D-02 | 外键关系 | project_repos.project_id → projects.id<br>tasks.project_id → projects.id<br>todos.task_id → tasks.id<br>project_init_sessions.project_id → projects.id | ☐ |
| D-03 | 状态枚举一致性 | tasks.status 使用 0-7 枚举，todos.status 使用 0-3 枚举，project_init_sessions.status 使用 0-3 枚举 | ☐ |

---

### 3.12 本地文件系统验收

| 编号 | 用例 | 验证项 | 通过 |
|------|------|--------|------|
| L-01 | 根目录 | `~/.daiflow/` 目录存在，包含 `daiflow.db` | ☐ |
| L-02 | 项目目录 | 创建项目后 `~/.daiflow/projects/{project_id}/` 目录创建 | ☐ |
| L-03 | Skill 文件 | 初始化后 `projects/{id}/skills/` 下生成 8 个知识点目录，每个含 `SKILL.md` | ☐ |
| L-04 | project.md | 初始化完成后 `projects/{id}/project.md` 存在且内容完整 | ☐ |
| L-05 | 任务目录 | 创建任务后 `~/.daiflow/tasks/{task_id}/` 目录创建 | ☐ |
| L-06 | Skill 同步 | 任务目录下 `.cody/skills/` 与项目 `skills/` 内容一致 | ☐ |
| L-07 | plan.md | 技术方案生成后 `tasks/{task_id}/plan.md` 存在 | ☐ |
| L-08 | todo.json | 任务拆解后 `tasks/{task_id}/todo.json` 存在且格式正确（JSON 数组，含 title + description） | ☐ |

---

### 3.13 UI 通用验收

| 编号 | 用例 | 验证项 | 通过 |
|------|------|--------|------|
| U-01 | 侧边栏导航 | 侧边栏包含：Logo、项目入口、任务入口、设置入口、底部模型状态 | ☐ |
| U-02 | 导航高亮 | 当前页面对应的侧边栏导航项高亮 | ☐ |
| U-03 | 暗色主题 | Dark 模式下所有页面 UI 配色正确 | ☐ |
| U-04 | 亮色主题 | Light 模式下所有页面 UI 配色正确 | ☐ |
| U-05 | 阶段进度条 | 开发流程页面顶部展示四阶段进度条，当前阶段高亮，已完成阶段标记完成 | ☐ |
| U-06 | Markdown 渲染 | plan.md 内容在左侧正确渲染为格式化 Markdown | ☐ |
| U-07 | Diff 渲染 | 代码 diff 正确渲染，支持新增（绿色）和删除（红色）高亮 | ☐ |

---

## 四、端到端验收流程

以下为完整的端到端验收路径，建议按顺序执行：

```
1. daiflow start → 首次启动，确认目录和数据库初始化
       ↓
2. 配置 AI 模型（Settings 页面） → 保存，确认脱敏和路由放行
       ↓
3. 创建项目 → 填写名称、描述、添加前端+后端仓库、填写 Skill 名称
       ↓
4. 等待项目初始化 → 观察 SSE 进度，确认 8 个知识点 + project.md 生成
       ↓
5. 创建任务 → 填写名称、选择项目、填写分支名、粘贴 PRD
       ↓
6. 技术方案阶段 → 观察 AI 自动生成 plan.md，通过对话调整，点击「锁定方案」
       ↓
7. 任务拆解阶段 → 观察 AI 自动生成 todo 列表，通过对话调整，点击「执行编码」
       ↓
8. 编写代码阶段 → 逐个点击 todo 执行，观察 SSE 日志和 diff，与 AI 对话调整
       ↓
9. 代码审查阶段 → 查看整体 diff，确认无误后点击「生成 MR」
       ↓
10. 验证 → git log 确认 commit，git remote 确认 push 成功
```

---

## 五、验收结果汇总

| 模块 | 用例数 | 通过 | 未通过 | 备注 |
|------|--------|------|--------|------|
| 应用启动 | 3 | | | |
| 全局设置 | 5 | | | |
| 项目管理 | 15 | | | |
| 任务管理 | 6 | | | |
| 技术方案 | 6 | | | |
| 任务拆解 | 6 | | | |
| 编写代码 | 8 | | | |
| 代码审查 | 5 | | | |
| SSE 推送 | 3 | | | |
| API 接口 | 26 | | | |
| 数据库 | 3 | | | |
| 文件系统 | 8 | | | |
| UI 通用 | 7 | | | |
| **合计** | **101** | | | |

---

验收人：________________  日期：________________

确认签字：________________
