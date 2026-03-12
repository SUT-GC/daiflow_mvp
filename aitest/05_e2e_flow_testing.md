# 黑盒测试 — 端到端流程测试

> **目标：** 验证 DaiFlow 的完整业务流程，从项目初始化到代码提交
> **前置条件：** AI 模型已配置（需要真实的 Cody SDK 调用）
> **耗时：** 每个端到端流程需要 30s~2min（取决于 AI 模型响应速度）

---

## 概述

DaiFlow 有两个核心端到端流程：

1. **项目初始化流程** — 创建项目 → 触发 init → 四层知识生成
2. **任务 DevFlow 流程** — 创建任务 → Plan → Todo → Coding → Review → 提交 MR

两个流程的共同特点：
- 涉及后台异步任务（BackgroundTasks）
- 需要等待 AI 模型返回
- 状态通过 DB + WebSocket 双通道可观察
- 需要验证状态机转换正确

---

## 流程一：项目初始化

### 步骤

```bash
# 1. 创建项目（关联一个真实的本地 git 仓库）
PROJECT_ID=$(curl -s -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "E2E Test Project",
    "repos": [
      {
        "local_path": "/path/to/real/git/repo",
        "git_url": "",
        "repo_type": "backend",
        "repo_type_label": "后端"
      }
    ]
  }' | jq -r '.id')

# 2. 触发初始化
curl -s -X POST "$BASE_URL/api/projects/$PROJECT_ID/init" | jq .
# 预期：返回 session 数组，每个 session 对应一个知识生成任务
```

### 验证点

#### F-01: Init 返回正确数量的 sessions

```bash
SESSIONS=$(curl -s -X POST "$BASE_URL/api/projects/$PROJECT_ID/init" | jq 'length')
# 预期：
# - 1 个 repo (backend) → 7 个 session:
#   Layer 1: skill_fetch (1)
#   Layer 2: backend_structure (1, 因为是 backend repo)
#   Layer 3: module_overview, api_interaction, data_entity, dependencies (4)
#   Layer 4: project_md (1)

echo "Sessions: $SESSIONS"
```

不同 repo 类型产生不同的 Layer 2 session：
- `frontend` repo → `frontend_structure`, `component_usage`
- `backend` repo → `backend_structure`
- `custom` repo → 无 Layer 2

#### F-02: Sessions 按 layer 分组

```bash
curl -s "$BASE_URL/api/projects/$PROJECT_ID/init/sessions" | jq .
# 预期：返回按 layer 分组的结构
# {
#   "1": [...],  // Layer 1 sessions
#   "2": [...],  // Layer 2 sessions
#   "3": [...],  // Layer 3 sessions
#   "4": [...]   // Layer 4 sessions
# }
```

#### F-03: 等待初始化完成

```bash
# 轮询检查所有 session 是否完成
for i in $(seq 1 60); do
  SESSIONS_JSON=$(curl -s "$BASE_URL/api/projects/$PROJECT_ID/init/sessions")

  # 检查是否所有 session 都是 done(2) 或 failed(3)
  ALL_DONE=$(echo "$SESSIONS_JSON" | jq '[.. | objects | select(.status != null) | .status] | all(. >= 2)')

  if [ "$ALL_DONE" = "true" ]; then
    echo "PASS: All sessions completed"
    break
  fi

  echo "Waiting... ($i/60)"
  sleep 2
done
```

#### F-04: 知识文件已生成

```bash
# 验证 project 目录下生成了 skill 文件
ls "$HOME/.daiflow/projects/$PROJECT_ID/skills/"
# 预期：包含各知识类型的子目录

# 验证 project.md 已生成
[ -f "$HOME/.daiflow/projects/$PROJECT_ID/project.md" ] && echo "PASS" || echo "FAIL"
```

---

## 流程二：任务 DevFlow（四阶段）

### 前置条件

需要已完成初始化的项目，且关联了一个真实的 git 仓库。

### 阶段 1: Plan（技术方案）

```bash
# 1. 创建任务
TASK_ID=$(curl -s -X POST "$BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"Add user login feature\",
    \"project_id\": \"$PROJECT_ID\",
    \"description\": \"Implement user login with email and password\",
    \"branch\": \"feature/login\"
  }" | jq -r '.id')

# 2. 初始状态应为 INITIALIZING(1)
STATUS=$(curl -s "$BASE_URL/api/tasks/$TASK_ID" | jq '.status')
echo "Initial status: $STATUS"  # 预期: 1
```

#### F-10: 等待 init_task 完成

创建任务后，后台会自动执行 `init_task`（同步 skill、checkout 分支），完成后自动触发 `generate_plan`。

```bash
# 轮询等待状态变化
for i in $(seq 1 30); do
  STATUS=$(curl -s "$BASE_URL/api/tasks/$TASK_ID" | jq '.status')
  echo "Status: $STATUS (attempt $i)"

  # 状态 >= 2 (PLANNING) 说明 init 完成
  [ "$STATUS" -ge 2 ] && break
  sleep 2
done
```

#### F-11: 等待 Plan 生成

```bash
# 继续等待 Plan 生成（状态到 PLANNING 后，generate_plan 在后台运行）
for i in $(seq 1 60); do
  TASK=$(curl -s "$BASE_URL/api/tasks/$TASK_ID")
  STATUS=$(echo "$TASK" | jq '.status')
  PLAN=$(echo "$TASK" | jq -r '.tech_plan // empty')

  if [ -n "$PLAN" ] && [ "$PLAN" != "null" ]; then
    echo "PASS: Plan generated"
    echo "Plan preview: $(echo "$PLAN" | head -3)"
    break
  fi

  echo "Waiting for plan... status=$STATUS ($i/60)"
  sleep 2
done
```

#### F-12: Plan 对话调整

```bash
# 对 Plan 进行对话（通过 WebSocket）
# 先建立 WS 连接，然后发送 chat action
wscat -c "ws://localhost:8000/api/ws" -x '{"action":"chat","id":"req_1","chat_path":"plan","entity_id":"'$TASK_ID'","message":"请把技术方案的第一步改为先设计数据库表结构"}'

# 预期：通过 WebSocket 返回流式事件
# 包含 text_delta 事件（AI 回复）
# 可能包含 plan_updated 事件（AI 修改了 plan.md）
```

#### F-13: Lock Plan（锁定方案）

```bash
# 等待状态变为 PLANNING(2)
STATUS=$(curl -s "$BASE_URL/api/tasks/$TASK_ID" | jq '.status')

if [ "$STATUS" = "2" ]; then
  curl -s -X POST "$BASE_URL/api/tasks/$TASK_ID/lock-plan" | jq .
  # 预期：status 变为 PLAN_LOCKED(3)
  # 同时自动触发 generate_todos（后台）
fi
```

### 阶段 2: Todo（任务拆解）

#### F-14: 等待 Todo 生成

```bash
for i in $(seq 1 60); do
  TODOS=$(curl -s "$BASE_URL/api/tasks/$TASK_ID/todos")
  TODO_COUNT=$(echo "$TODOS" | jq 'length')

  if [ "$TODO_COUNT" -gt 0 ]; then
    echo "PASS: $TODO_COUNT todos generated"
    echo "$TODOS" | jq '.[].title'
    break
  fi

  echo "Waiting for todos... ($i/60)"
  sleep 2
done
```

#### F-15: Todo 结构验证

```bash
# 验证每个 todo 的结构
curl -s "$BASE_URL/api/tasks/$TASK_ID/todos" | jq '.[0]'
# 预期字段：
# - id: 非空
# - seq: 序号（从 1 开始）
# - title: 标题
# - description: 描述
# - status: 0 (PENDING)
```

#### F-16: Todo 对话

```bash
curl -N -X POST "$BASE_URL/api/tasks/$TASK_ID/todo/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "请把第一个 todo 拆得更细一些"}' \
  --max-time 30
# 预期：流式事件，可能包含 todo_updated 事件
```

### 阶段 3: Coding（编码实现）

#### F-17: 进入 Coding 阶段

```bash
# 需要先确保状态为 TODO_READY(4)
# （generate_todos 完成后会自动设为 PLAN_LOCKED(3)，
#   但 start-coding 需要从某个合法状态转入）

# 检查当前状态
STATUS=$(curl -s "$BASE_URL/api/tasks/$TASK_ID" | jq '.status')
echo "Current status: $STATUS"

# 如果状态允许，开始编码
curl -s -X POST "$BASE_URL/api/tasks/$TASK_ID/start-coding" | jq .
# 预期：status 变为 CODING(5)
# 如果状态不对，返回 400 + 错误信息
```

#### F-18: 执行单个 Todo

```bash
# 获取第一个 todo 的 ID
TODO_ID=$(curl -s "$BASE_URL/api/tasks/$TASK_ID/todos" | jq -r '.[0].id')

# 执行 todo
curl -s -X POST "$BASE_URL/api/todos/$TODO_ID/execute" | jq .
# 预期：返回 todo 对象，status 变为 RUNNING(1)

# 等待执行完成
for i in $(seq 1 60); do
  TODO_STATUS=$(curl -s "$BASE_URL/api/tasks/$TASK_ID/todos" | jq -r ".[0].status")

  if [ "$TODO_STATUS" = "2" ]; then
    echo "PASS: Todo completed"
    break
  elif [ "$TODO_STATUS" = "3" ]; then
    echo "WARN: Todo failed"
    break
  fi

  echo "Executing... status=$TODO_STATUS ($i/60)"
  sleep 2
done
```

#### F-19: 查看 Diff

```bash
curl -s "$BASE_URL/api/tasks/$TASK_ID/diff" | jq .
# 预期：返回 diff 数据（如果 AI 修改了文件）
# 结构: {"diffs": [{"repo_path": "...", "diff": "..."}]}
```

### 阶段 4: Review（代码审查）

#### F-20: 进入 Review 阶段

```bash
curl -s -X POST "$BASE_URL/api/tasks/$TASK_ID/start-review" | jq .
# 预期：status 变为 REVIEWING(6)
```

#### F-21: Review 对话

```bash
curl -N -X POST "$BASE_URL/api/tasks/$TASK_ID/review/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "请检查这些代码变更是否有安全问题"}' \
  --max-time 30
# 预期：流式事件
```

#### F-22: 提交 MR

```bash
curl -s -X POST "$BASE_URL/api/tasks/$TASK_ID/submit-mr" \
  -H "Content-Type: application/json" \
  -d '{"commit_message": "feat: add user login feature"}' | jq .
# 预期：提交成功，status 变为 DONE(7)
# 注意：需要 git remote 配置正确才能 push
```

---

## 状态机转换验证

### 合法转换表

```
CREATED(0) → INITIALIZING(1)      # 创建任务时自动
INITIALIZING(1) → PLANNING(2)     # init_task 完成后
PLANNING(2) → PLAN_LOCKED(3)      # lock-plan API
PLAN_LOCKED(3) → TODO_READY(4)    # generate_todos 完成后
TODO_READY(4) → CODING(5)         # start-coding API
CODING(5) → REVIEWING(6)          # start-review API
REVIEWING(6) → DONE(7)            # submit-mr API
```

### ST-01: 非法转换应返回 400

```bash
# 创建一个新任务（状态为 INITIALIZING）
TASK_ID=$(curl -s -X POST "$BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"ST Test\", \"project_id\": \"$PROJECT_ID\"}" | jq -r '.id')

# 尝试非法转换
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$BASE_URL/api/tasks/$TASK_ID/lock-plan")
[ "$STATUS" = "400" ] && echo "PASS: lock-plan from INITIALIZING rejected" || echo "FAIL"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$BASE_URL/api/tasks/$TASK_ID/start-coding")
[ "$STATUS" = "400" ] && echo "PASS: start-coding from INITIALIZING rejected" || echo "FAIL"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$BASE_URL/api/tasks/$TASK_ID/start-review")
[ "$STATUS" = "400" ] && echo "PASS: start-review from INITIALIZING rejected" || echo "FAIL"
```

### ST-02: 错误信息包含状态说明

```bash
ERROR=$(curl -s -X POST "$BASE_URL/api/tasks/$TASK_ID/lock-plan" | jq -r '.detail')
echo "$ERROR" | grep -q "Cannot transition" && echo "PASS" || echo "FAIL"
```

---

## 端到端测试的注意事项

### 1. 超时处理

AI 模型调用可能很慢，建议：
- 单步等待上限 60s
- 整个流程等待上限 5min
- 使用 `--max-time` 限制 curl 超时

### 2. 清理

端到端测试创建的资源需要清理：
```bash
curl -s -X DELETE "$BASE_URL/api/tasks/$TASK_ID"
curl -s -X DELETE "$BASE_URL/api/projects/$PROJECT_ID"
```

### 3. Git 仓库要求

编码阶段（F-17~F-19）需要真实的 git 仓库：
- 仓库路径需要在创建项目时通过 `repos[].local_path` 指定
- 仓库需要有 `main` 或 `master` 分支
- AI 会在 task 的 `branch` 上创建代码变更

### 4. 不可控因素

AI 模型的输出不确定，端到端测试主要验证：
- 状态转换正确
- 数据写入成功（Plan/Todo 非空）
- 实时事件推送正常
- 不验证 AI 输出的具体内容质量
