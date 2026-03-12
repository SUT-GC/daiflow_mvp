# DaiFlow 黑盒测试指南 — 总纲

> **适用对象：** AI Agent / 测试工程师
> **目标：** 在不阅读源码的前提下，对 DaiFlow 后端进行全面的黑盒测试
> **前置要求：** 已阅读 `README.md`，了解 DaiFlow 的功能和 API 概览

---

## 文档索引

| 文件 | 内容 | 何时使用 |
|------|------|---------|
| `00_blackbox_testing_guide.md` | 本文档：总纲、流程、原则 | 首先阅读 |
| `03_test_preparation.md` | 环境搭建、服务启动、工具准备 | 开始测试前 |
| `04_api_crud_testing.md` | REST API 端点的 CRUD 测试方法 | 测试各模块 API |
| `05_e2e_flow_testing.md` | 端到端全链路测试（四阶段 DevFlow） | 验证业务流程 |
| `06_sse_testing.md` | WebSocket 实时推送测试方法 | 验证实时交互 |
| `07_error_and_edge_cases.md` | 错误处理、边界条件、安全性测试 | 负向测试 |
| `01_blackbox_api_test.md` | 测试结果报告（参考） | 查看执行结果格式 |
| `02_unit_test_report.md` | 单元测试报告（参考） | 对比白盒测试 |

---

## 黑盒测试总体流程

```
1. 环境准备 (03_test_preparation.md)
   ├── 安装依赖、配置 AI 模型
   ├── 启动后端服务
   └── 验证服务可达

2. API CRUD 测试 (04_api_crud_testing.md)
   ├── Settings API（配置读写、掩码、检查）
   ├── Projects API（增删改查、排序、关联 repo）
   ├── Tasks API（增删改查、按项目筛选、PRD 存储）
   ├── Todos API（查询、执行）
   └── Sessions API（状态、日志）

3. 端到端流程测试 (05_e2e_flow_testing.md)
   ├── 项目初始化流程（四层知识生成）
   ├── 任务 DevFlow 四阶段流转
   │   ├── Plan 阶段（生成技术方案 + 对话调整）
   │   ├── Todo 阶段（任务拆解 + 对话调整）
   │   ├── Coding 阶段（逐个执行 + Diff）
   │   └── Review 阶段（审查 + 提交 MR）
   └── 状态机转换验证

4. WebSocket 测试 (06_sse_testing.md)
   ├── 项目初始化 WebSocket 订阅
   ├── Session 实时推送
   └── 阶段对话 WebSocket 流

5. 错误与边界测试 (07_error_and_edge_cases.md)
   ├── 404 资源不存在
   ├── 422 参数校验
   ├── 400 非法状态转换
   ├── 幂等性验证
   └── 并发安全

6. 生成报告
   └── 参考 01_blackbox_api_test.md 格式
```

---

## 核心测试原则

### 1. 不依赖源码

黑盒测试只依赖：
- `README.md` 中的 API 端点列表
- 实际的 HTTP 请求/响应
- 可观察的行为（数据库文件、本地文件、WebSocket 事件）

### 2. 测试数据自给自足

每个测试用例需要的数据由测试自己创建，测试结束后清理：
```
创建项目 → 创建任务 → 执行测试 → 删除任务 → 删除项目
```

### 3. 验证三层一致性

DaiFlow 有三层持久化，关键测试需要验证三层数据一致：
- **DB 层：** API 返回的 JSON 数据
- **文件层：** `~/.daiflow/` 下的文件（日志、方案、Todo）
- **WebSocket 层：** 实时推送的事件与 DB/文件状态一致

### 4. 状态机覆盖

Task 有 8 个状态，状态转换有严格约束：
```
CREATED(0) → INITIALIZING(1) → PLANNING(2) → PLAN_LOCKED(3)
→ TODO_READY(4) → CODING(5) → REVIEWING(6) → DONE(7)
```
必须验证：合法转换成功 + 非法转换返回 400

### 5. 用例命名规范

使用分类前缀，便于追踪：
- `S-xx` — 启动 (Startup)
- `C-xx` — 配置 (Config)
- `P-xx` — 项目 (Project)
- `T-xx` — 任务 (Task)
- `TD-xx` — Todo
- `SS-xx` — Session
- `E-xx` — WebSocket 事件 (Event)
- `ST-xx` — 状态转换 (State Transition)
- `ERR-xx` — 错误处理 (Error)
- `F-xx` — 全链路 (Full flow)

---

## 测试工具选择

| 工具 | 用途 | 备注 |
|------|------|------|
| `curl` | HTTP 请求 | 最通用，AI Agent 容易使用 |
| `jq` | JSON 解析 | 提取字段、验证结构 |
| `sqlite3` | 数据库检查 | 直接查询验证 DB 状态 |
| `ls` / `cat` | 文件检查 | 验证本地文件生成 |
| `websocat / Python websockets` | WebSocket 连接 | 用于订阅实时事件 |

---

## 报告格式

测试完成后，按 `01_blackbox_api_test.md` 的格式生成报告：

```markdown
# 测试报告标题

> **测试日期：** YYYY-MM-DD
> **测试方式：** ...
> **测试环境：** ...

## 测试总结
| 指标 | 值 |
|------|-----|
| 总用例数 | N |
| 通过 | N |
| 失败 | N |
| 通过率 | xx% |

## 分类1 (通过数/总数)
| 用例 | 预期 | 结果 |
|------|------|------|
| XX-01 描述 | 预期行为 | ✓ / ✗ |
```

---

## 快速开始

如果你是 AI Agent，按以下顺序执行：

1. 阅读 `03_test_preparation.md`，完成环境准备
2. 阅读 `04_api_crud_testing.md`，逐个执行 API 测试
3. 阅读 `05_e2e_flow_testing.md`，执行端到端流程测试
4. 阅读 `06_sse_testing.md`，验证 WebSocket 推送
5. 阅读 `07_error_and_edge_cases.md`，执行负向测试
6. 汇总结果，生成测试报告到 `aitest/` 目录
