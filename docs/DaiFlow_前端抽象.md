# DaiFlow 前端抽象

> 版本：v0.1 MVP
> 更新时间：2026-03-15

---

## 一、概述

DaiFlow 前端是一个 React 19 + TypeScript SPA，基于 Vite 6 构建。核心抽象集中在以下三层：

```
页面层（Pages）
  ├─ StageLayout 统一布局
  ├─ 阶段专属 Hook（usePlanStage / useCodingStage ...）
  │    └─ useAgent 组合 Hook
  │         ├─ useSession（Session 追踪 + WS 订阅）
  │         ├─ useStageChat（Chat 交互 + 历史回放）
  │         └─ useStaleDetection（超时检测）
  └─ 通用组件（ChatPanel / DiffViewer / MarkdownViewer ...）

通信层
  └─ WebSocketClient 单例（频道订阅 + Chat 流式通信）
  └─ API 服务层（REST 请求 + 错误处理）

全局状态层
  ├─ ThemeContext（主题切换）
  ├─ LocaleContext（国际化）
  └─ SettingsContext（配置状态）
```

---

## 二、全局状态管理

DaiFlow 使用 React Context API 管理轻量全局状态，无需 Redux/Zustand。

### 2.1 ThemeContext

**文件：** `frontend/src/hooks/useTheme.ts`

- 管理 `dark` / `light` 主题，通过 `data-theme` HTML 属性切换
- 持久化到 `localStorage`（key: `daiflow-theme`）
- 在 `main.tsx` 启动时立即应用，避免闪屏
- Provider: `useThemeProvider()` → `{ theme, toggleTheme }`
- Consumer: `useTheme()` Hook

### 2.2 LocaleContext

**文件：** `frontend/src/hooks/useLocale.ts`

- 管理 `en` / `zh` 语言切换
- 持久化到 `localStorage`（key: `daiflow-locale`）
- Provider: `useLocaleProvider()` → `{ locale, setLocale, t }`
- Consumer: `useLocale()` Hook，`t(key)` 函数返回翻译文本
- 翻译文件：`i18n/en.ts`（English）、`i18n/zh.ts`（中文）
- TypeScript 安全：`TranslationKey` 类型从 `en.ts` 导出，编译期检查 key 合法性

### 2.3 SettingsContext

**文件：** `frontend/src/App.tsx`

- 缓存 `/api/settings/check` 结果，避免每次页面加载重复请求
- 提供 `{ configured, model, recheck }`
- 被 SettingsGuard 用于控制页面访问权限

---

## 三、路由与守卫

### 3.1 路由结构

**文件：** `frontend/src/App.tsx`

使用 React Router v7，DevFlow 部分有 5 个阶段路由：

```
/                          → 重定向到 /tasks
/tasks                     → 任务列表
/projects                  → 项目列表
/projects/:projectId       → 项目详情
/settings                  → 设置页面
/debug                     → 调试页面
/devflow/:taskId/init      → 初始化阶段
/devflow/:taskId/plan      → 技术方案阶段
/devflow/:taskId/todo      → 任务拆解阶段
/devflow/:taskId/coding    → 代码实现阶段
/devflow/:taskId/review    → 代码审查阶段
```

### 3.2 守卫层

**三层守卫：**

1. **SettingsGuard**：检查 Cody 配置是否完成，未配置则重定向到 `/settings`
2. **DevFlowGuard**：校验任务状态是否匹配当前阶段 URL，不匹配则重定向到正确阶段
3. **StageErrorBoundary**：包裹 DevFlow 页面，出错时保留导航壳，提供「返回任务列表」按钮

---

## 四、WebSocket 通信

### 4.1 WebSocketClient 单例

**文件：** `frontend/src/ws/WebSocketClient.ts`

全局唯一的 WebSocket 客户端，管理与后端的实时通信：

```typescript
class WebSocketClient {
    // 频道订阅（广播模式）
    subscribe(channel: string, handler: (event) => void): () => void

    // 双向 Chat（请求-响应模式）
    sendChat(stage, entityId, message, onEvent): () => void  // 返回取消函数
}
```

**两种通信模式：**

| 模式 | 用途 | 频道示例 |
|------|------|---------|
| Pub/Sub 订阅 | 接收 Session 事件流 | `session:task:42:plan` |
| 双向 Chat | 阶段内对话交互 | `chat:{requestId}`（临时） |

**容错机制：**
- 断线指数退避重连（1s → 30s 上限，之后 60s 兜底）
- 重连后自动重新订阅所有频道
- 每 25s 发送心跳 ping
- 断线时清理所有 pending chat handler 并推送 error 事件

### 4.2 useWebSocket Hook

**文件：** `frontend/src/hooks/useWebSocket.ts`

在 App 挂载时初始化全局 WebSocket 连接，无参数，仅调用一次。

---

## 五、核心 Hook 体系

### 5.1 useAgent（组合 Hook）

**文件：** `frontend/src/hooks/useAgent.ts`

**核心抽象**：将三个子 Hook 组合为统一的 AI 交互接口：

```typescript
useAgent({
    sessionId: string | null,    // Session 业务 ID
    stage: 'plan' | 'todo' | 'todo_exec' | 'review',
    entityId: string,            // task_id 或 todo_id
    chattable?: boolean,         // 是否启用 Chat
    onUpdated?: (event) => void, // 产物更新回调
}): {
    // 来自 useSession
    status: SessionStatus,
    logs: SessionEvent[],
    error: string | null,

    // 来自 useStaleDetection
    isStale: boolean,

    // 来自 useStageChat
    messages: ChatMessage[],
    streaming: boolean,
    sendMessage: (text: string) => void,

    // 刷新能力
    refreshSession: () => void,
    sessionRefreshKey: number,
}
```

**被阶段专属 Hook 使用**，作为 AI 交互的基础构建块。

### 5.2 useSession（Session 追踪）

**文件：** `frontend/src/hooks/useSession.ts`

- 挂载时调用 API 获取 Session 状态 + 日志
- **订阅 WebSocket** 频道 `session:{sessionId}` 接收实时事件
- **rAF 批量更新**：使用 `requestAnimationFrame` 合并日志更新，避免渲染抖动
- 返回 `{ status, logs, error }`

### 5.3 useStageChat（Chat 交互）

**文件：** `frontend/src/hooks/useStageChat.ts`

- **历史恢复**：从 `.jsonl` 日志重建消息历史
- **实时 Chat**：`sendMessage()` 调用 `wsClient.sendChat()`，流式接收事件
- **rAF 优化**：`text_delta` 更新节流到 `requestAnimationFrame`
- **工具分组**：追踪 `tool_call` / `tool_result` 事件，归组到消息元数据
- 返回 `{ messages, sendMessage, streaming }`

### 5.4 useStaleDetection（超时检测）

**文件：** `frontend/src/hooks/useStaleDetection.ts`

- 检测 Session 处于 RUNNING 但超过 300 秒（5 分钟）无事件
- 每 10 秒检查一次
- 返回 `isStale: boolean`，UI 显示重试横幅
- 收到新日志事件时重置计时器

### 5.5 阶段专属 Hook

每个 DevFlow 阶段有专属 Hook，封装该阶段的完整业务逻辑：

| Hook | 文件 | 职责 |
|------|------|------|
| `usePlanStage(taskId)` | `hooks/usePlanStage.ts` | 加载任务 + Plan 内容，触发方案生成，从日志提取 `plan_updated` |
| `useTodoStage(taskId)` | `hooks/useTodoStage.ts` | 加载任务 + Todo 列表，监听 `todo_updated` 刷新 |
| `useCodingStage(taskId)` | `hooks/useCodingStage.ts` | 跟踪选中 Todo，获取 Diff，执行/跳过 Todo，防抖 `code_updated` |
| `useCommitModal(taskId)` | `hooks/useCommitModal.ts` | 生成 Commit Message，提交 MR，管理 Modal 状态 |
| `useInitProgress(projectId)` | `hooks/useInitProgress.ts` | 跟踪 4 层 Init 进度，订阅 `project:init:{projectId}` |

---

## 六、组件层

### 6.1 布局组件

#### Shell（应用外壳）

**文件：** `frontend/src/components/Shell/Shell.tsx`

- 响应式侧边栏（可折叠，状态持久化）
- 导航菜单：项目 / 任务 / 调试 / 设置
- Model 状态指示器（配置完成显示绿色）

#### Topbar（页面顶栏）

**文件：** `frontend/src/components/Topbar/Topbar.tsx`

- 返回导航按钮
- 标题 + 副标题
- 分支名 + 任务状态徽章
- 主题切换按钮
- 顶部固定定位

#### StageLayout（阶段统一布局）

**文件：** `frontend/src/components/StageLayout/StageLayout.tsx`

**核心布局抽象**：所有 DevFlow 页面共享的容器组件：

```typescript
<StageLayout
    task={task}
    stageNumber={1-5}
    content={<主内容区/>}
    actions={<操作按钮区/>}
    chatTitle="..."
    chatMessages={messages}
    chatOnSend={sendMessage}
    chatStreaming={streaming}
    isStale={isStale}
    onRetry={refreshSession}
    readonly={isStageReadonly(task.status, currentStage)}
/>
```

渲染结构：`Topbar → StageProgress → ResizableSplitPane(Content + ChatPanel) → Actions`

### 6.2 交互组件

#### ChatPanel（聊天面板）

**文件：** `frontend/src/components/ChatPanel/ChatPanel.tsx`

- 消息列表：用户/AI 头像区分
- 自动滚动到底部（接近底部时触发）
- 用户消息折叠（超过 3 行时可展开）
- 工具调用分组渲染（ToolGroupBlock）
- AI 状态指示器（加载中 / 完成）
- 文本输入框：Enter 发送 / Shift+Enter 换行
- readonly 和 streaming 状态下禁用输入

#### ToolGroupBlock（工具组块）

**文件：** `frontend/src/components/ChatPanel/ToolGroupBlock.tsx`

- 可折叠的工具调用 + 结果组
- 展开后显示参数 / 结果 JSON
- 用于 Chat 消息和 Session 日志

#### StageProgress（阶段进度条）

**文件：** `frontend/src/components/StageProgress/StageProgress.tsx`

- 5 阶段视觉步进器：Init → Plan → Todo → Coding → Review
- 状态显示：完成（✓）、进行中（实心）、待处理（空心）、禁用（淡色）
- 可点击节点导航到已到达的阶段
- 根据 Task 状态计算可达性

### 6.3 内容查看器

#### MarkdownViewer

**文件：** `frontend/src/components/MarkdownViewer/MarkdownViewer.tsx`

- 渲染 Markdown + 语法高亮
- 使用 `react-markdown` + `remark-gfm` + `react-syntax-highlighter`
- 主题感知：Prism oneDark / oneLight 切换
- 响应式行内代码 + 代码块

#### DiffViewer

**文件：** `frontend/src/components/DiffViewer/DiffViewer.tsx`

- 解析 unified git diff 格式
- 两种视图模式：Unified（传统） / Split（并排）
- 文件折叠、增/删/上下文行高亮
- 按语言语法高亮
- 统计信息：+additions -deletions
- 二进制文件检测

### 6.4 通用组件

| 组件 | 文件 | 功能 |
|------|------|------|
| `ResizableSplitPane` | `components/ResizableSplitPane/` | 左右可拖拽分割面板，双击折叠 |
| `Modal` | `components/Modal/` | Portal 弹窗，ESC 关闭，Tab 焦点循环 |
| `Loading` | `components/Loading/` | 加载动画 |
| `ErrorBoundary` | `components/ErrorBoundary/` | 全局错误边界 + 重试 |
| `StageErrorBoundary` | `components/ErrorBoundary/` | 阶段级错误边界，保留导航 |

---

## 七、API 服务层

**文件：** `frontend/src/api/index.ts`

薄封装层：30 秒超时 + AbortController + 统一错误处理。

**核心 API 按阶段分组：**

| 阶段 | API | 用途 |
|------|-----|------|
| 全局 | `GET /api/settings/check` | 检查 Cody 配置 |
| 方案 | `POST /api/tasks/{id}/plan` | 触发方案生成 |
| 方案 | `POST /api/tasks/{id}/lock-plan` | 锁定方案 |
| 拆解 | `POST /api/tasks/{id}/todo` | 触发 Todo 生成 |
| 编码 | `POST /api/todos/{id}/execute` | 执行 Todo |
| 编码 | `POST /api/todos/{id}/skip` | 跳过 Todo |
| 编码 | `GET /api/todos/{id}/diff` | 获取单 Todo Diff |
| 审查 | `GET /api/tasks/{id}/diff` | 获取聚合 Diff |
| 审查 | `POST /api/tasks/{id}/generate-commit-message` | AI 生成提交信息 |
| 审查 | `POST /api/tasks/{id}/submit-mr` | 提交 MR |
| Session | `GET /api/sessions/{id}/status` | 获取 Session 状态 |
| Session | `GET /api/sessions/{id}/logs` | 回放 Session 日志 |

---

## 八、Session ID 构造

**文件：** `frontend/src/utils/sessionIds.ts`

前端镜像后端的 Session ID 构造，用于 WebSocket 频道路由：

```typescript
const sessionIds = {
    plan:        (taskId) => `task:${taskId}:plan`,
    todoSplit:   (taskId) => `task:${taskId}:todo_split`,
    todoExec:    (taskId, todoId) => `task:${taskId}:todo:${todoId}`,
    review:      (taskId) => `task:${taskId}:review`,
    taskInitBus: (taskId) => `task:init:${taskId}`,
}
```

---

## 九、状态枚举镜像

**文件：** `frontend/src/types/enums.ts`

前端精确镜像后端枚举值：

```typescript
TaskStatus    = { CREATED: 0, INITIALIZING: 1, PLANNING: 2, PLAN_LOCKED: 3,
                  TODO_READY: 4, CODING: 5, REVIEWING: 6, DONE: 7 }
TodoStatus    = { PENDING: 0, RUNNING: 1, DONE: 2, FAILED: 3, SKIPPED: 4 }
SessionStatus = { WAITING: 0, RUNNING: 1, DONE: 2, FAILED: 3 }
```

**阶段映射工具** (`taskStages.ts`)：
- `getStageFromStatus(status)` → 将 TaskStatus (0-7) 映射到 Stage (1-5)
- `getDevFlowPath(taskId, status)` → 将状态映射到正确的 DevFlow URL
- `STATUS_TAGS` → 状态徽章 CSS 类名映射

---

## 十、阶段页面统一模式

所有 5 个 DevFlow 页面遵循统一模式：

```
XxxStage
  ├── useParams() → taskId
  ├── useXxxStage(taskId) → 阶段专属 Hook
  │     └── useAgent() → AI 交互
  │           ├── useSession() → Session 追踪
  │           ├── useStageChat() → Chat 交互
  │           └── useStaleDetection() → 超时检测
  ├── StageLayout 统一布局
  │     ├── content:  主内容区（MarkdownViewer / DiffViewer / TodoList）
  │     ├── actions:  操作按钮区（Lock / Next / Execute / Submit）
  │     ├── chat:     ChatPanel 配置
  │     └── readonly: 基于 isStageReadonly(task.status, currentStage) 计算
  └── Modal（ReviewStage 的 CommitModal）
```

---

## 十一、实时数据流

### 11.1 Session 事件流

```
后端（Cody 执行）
  │ 推送事件 via WebSocket
  ▼
wsClient 订阅 session:{sessionId}
  │ 调用 event handler
  ▼
useSession 累积日志（rAF 批量更新）
  │ setLogs(newLogs)
  ▼
useStageChat 从日志重建消息
  │ setMessages([...])
  ▼
ChatPanel 重新渲染，自动滚动
```

### 11.2 Chat 流式通信

```
用户输入 → sendMessage()
  │
  ▼
wsClient.sendChat(stage, entityId, message, onEvent)
  │ 发送到 WebSocket
  ▼
后端执行 → 流式返回 chunks
  │
  ▼
wsClient 路由到 chat:{reqId} 频道
  │ 调用 onEvent(WSEvent)
  ▼
useStageChat 累积 text_delta + tool 事件（rAF 批量）
  │ setMessages([...])
  ▼
ChatPanel 渲染流式消息 + 工具调用
```

### 11.3 产物更新

```
后端检测文件写入 → 发送 plan_updated / todo_updated / code_updated
  │
  ▼
wsClient 路由到 session:{sessionId}
  │
  ▼
useStageChat 的 onUpdated 回调触发
  │
  ▼
阶段 Hook 刷新数据（Plan 内容 / Todo 列表 / Diff）
  │
  ▼
UI 更新
```

---

## 十二、性能优化

| 优化 | 位置 | 手段 |
|------|------|------|
| 日志批量更新 | useSession | `requestAnimationFrame` 合并多次 setLogs |
| Chat 流式更新 | useStageChat | `requestAnimationFrame` 节流 text_delta |
| Diff 防抖 | useCodingStage | `code_updated` 防抖 500ms 后再请求 Diff |
| Markdown 记忆化 | MarkdownViewer | Prism 高亮结果缓存 |
| 拖拽无重渲染 | ResizableSplitPane | 自定义 resize handle 避免拖拽期间重渲染 |
| 消息折叠 | ChatPanel | 长用户消息默认折叠，按需展开 |

---

## 十三、主题与样式

### 13.1 主题系统

- `data-theme="dark" | "light"` 属性设置在 `<html>` 和 `<body>` 上
- CSS 自定义属性（变量）定义颜色、间距
- 语法高亮跟随主题切换（Prism oneDark / oneLight）
- `localStorage` 持久化（key: `daiflow-theme`）
- Topbar 中的切换按钮

### 13.2 字体

- **Sora**：sans-serif UI 字体
- **JetBrains Mono**：代码 / 等宽字体

### 13.3 样式组织

- `frontend/src/styles/global.css`：设计令牌、布局、通用组件样式
- 每个组件目录下 `.css` 文件：作用域样式
- 响应式设计：Flexbox + CSS Grid

---

## 十四、关键文件索引

| 文件 / 目录 | 职责 |
|-------------|------|
| `frontend/src/App.tsx` | 路由 + 守卫 + 全局 Context Provider |
| `frontend/src/main.tsx` | 入口，主题初始化 |
| `frontend/src/hooks/useAgent.ts` | AI 交互组合 Hook |
| `frontend/src/hooks/useSession.ts` | Session 追踪 + WS 订阅 |
| `frontend/src/hooks/useStageChat.ts` | Chat 交互 + 历史回放 |
| `frontend/src/hooks/useStaleDetection.ts` | Session 超时检测 |
| `frontend/src/hooks/usePlanStage.ts` | Plan 阶段业务逻辑 |
| `frontend/src/hooks/useTodoStage.ts` | Todo 阶段业务逻辑 |
| `frontend/src/hooks/useCodingStage.ts` | Coding 阶段业务逻辑 |
| `frontend/src/hooks/useCommitModal.ts` | Commit 提交逻辑 |
| `frontend/src/hooks/useInitProgress.ts` | Init 进度追踪 |
| `frontend/src/ws/WebSocketClient.ts` | WebSocket 单例客户端 |
| `frontend/src/api/index.ts` | REST API 服务层 |
| `frontend/src/components/StageLayout/` | 阶段统一布局组件 |
| `frontend/src/components/ChatPanel/` | 聊天面板组件 |
| `frontend/src/components/DiffViewer/` | Diff 查看器组件 |
| `frontend/src/components/MarkdownViewer/` | Markdown 渲染器 |
| `frontend/src/components/Shell/` | 应用外壳 + 导航 |
| `frontend/src/utils/sessionIds.ts` | Session ID 构造 |
| `frontend/src/types/enums.ts` | 状态枚举镜像 |
| `frontend/src/i18n/` | 国际化翻译文件 |
