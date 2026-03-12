# 黑盒测试 — API CRUD 测试方法

> **目标：** 对每个 REST API 端点进行增删改查的完整测试
> **方法：** curl 请求 + jq 断言 + 数据库交叉验证

---

## 通用测试模式

每个资源的 CRUD 测试遵循相同模式：

```
1. List (GET) — 确认初始状态（空列表或已有数据）
2. Create (POST) — 创建资源，保存返回的 ID
3. Get (GET /:id) — 用 ID 获取，验证字段正确
4. Update (PUT /:id) — 修改字段，验证更新生效
5. List again (GET) — 确认列表中包含新资源
6. Delete (DELETE /:id) — 删除资源
7. Get again (GET /:id) — 确认返回 404
```

### 通用断言方式

```bash
# 断言 HTTP 状态码
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/xxx")
[ "$STATUS" = "200" ] && echo "PASS" || echo "FAIL: expected 200, got $STATUS"

# 断言 JSON 字段值
VALUE=$(curl -s "$BASE_URL/api/xxx" | jq -r '.field')
[ "$VALUE" = "expected" ] && echo "PASS" || echo "FAIL: expected 'expected', got '$VALUE'"

# 断言数组长度
COUNT=$(curl -s "$BASE_URL/api/xxx" | jq 'length')
[ "$COUNT" -ge 1 ] && echo "PASS" || echo "FAIL: expected >=1 items, got $COUNT"
```

---

## 1. Settings API

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings` | 获取所有设置 |
| PUT | `/api/settings` | 更新设置 |
| GET | `/api/settings/check` | 检查 AI 是否已配置 |

### 测试用例

#### C-01: 获取设置（初始状态）

```bash
curl -s "$BASE_URL/api/settings" | jq .
# 预期：返回 JSON 对象，包含 cody_model、cody_base_url、cody_api_key、theme 字段
# 值可能为 null（未配置时）
```

#### C-02: 更新设置

```bash
curl -s -X PUT "$BASE_URL/api/settings" \
  -H "Content-Type: application/json" \
  -d '{"cody_model": "test-model", "cody_base_url": "https://test.api.com/v1", "cody_api_key": "sk-test-key-12345678"}' \
  | jq .

# 验证回写
curl -s "$BASE_URL/api/settings" | jq -r '.cody_model'
# 预期: test-model
```

#### C-03: API Key 掩码

```bash
API_KEY=$(curl -s "$BASE_URL/api/settings" | jq -r '.cody_api_key')
# 预期：
# - 包含 * 字符（中间部分被掩码）
# - 首尾各保留几个字符可见
# - 如果原始 key 很短（<8 字符），全部掩码为 ****
echo "$API_KEY" | grep -q '\*' && echo "PASS: masked" || echo "FAIL: not masked"
```

#### C-04: 配置检查

```bash
# 已配置时
curl -s "$BASE_URL/api/settings/check" | jq .
# 预期: {"configured": true, "model": "test-model"}

# 如果 model 和 api_key 都为空，configured 应为 false
```

#### C-05: 主题切换

```bash
curl -s -X PUT "$BASE_URL/api/settings" \
  -H "Content-Type: application/json" \
  -d '{"theme": "light"}' | jq -r '.theme'
# 预期: light

curl -s -X PUT "$BASE_URL/api/settings" \
  -H "Content-Type: application/json" \
  -d '{"theme": "dark"}' | jq -r '.theme'
# 预期: dark
```

#### C-06: 空值不覆盖

```bash
# 先设置 model
curl -s -X PUT "$BASE_URL/api/settings" \
  -H "Content-Type: application/json" \
  -d '{"cody_model": "my-model"}'

# 只更新 theme，不传 model
curl -s -X PUT "$BASE_URL/api/settings" \
  -H "Content-Type: application/json" \
  -d '{"theme": "light"}'

# 验证 model 没有被清空
MODEL=$(curl -s "$BASE_URL/api/settings" | jq -r '.cody_model')
[ "$MODEL" = "my-model" ] && echo "PASS" || echo "FAIL: model was cleared"
```

---

## 2. Projects API

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects` | 列表 |
| POST | `/api/projects` | 创建 |
| GET | `/api/projects/:id` | 获取 |
| PUT | `/api/projects/:id` | 更新 |
| DELETE | `/api/projects/:id` | 删除 |
| POST | `/api/projects/:id/init` | 触发初始化 |
| GET | `/api/projects/:id/init/sessions` | 获取初始化 session 列表 |

### 测试用例

#### P-01: 创建项目

```bash
PROJECT_ID=$(curl -s -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Project",
    "repos": [
      {
        "local_path": "/tmp/test-repo",
        "git_url": "https://github.com/test/repo.git",
        "repo_type": "backend",
        "repo_type_label": "后端"
      }
    ]
  }' | jq -r '.id')

echo "Project ID: $PROJECT_ID"
# 预期：非空的 hex 字符串（32 位）
[ ${#PROJECT_ID} -eq 32 ] && echo "PASS" || echo "FAIL"
```

#### P-02: 获取项目

```bash
curl -s "$BASE_URL/api/projects/$PROJECT_ID" | jq .
# 验证：
# - name == "Test Project"
# - repos 数组长度 == 1
# - repos[0].repo_type == "backend"
```

#### P-03: 更新项目名

```bash
curl -s -X PUT "$BASE_URL/api/projects/$PROJECT_ID" \
  -H "Content-Type: application/json" \
  -d '{"name": "Updated Project"}' | jq -r '.name'
# 预期: Updated Project
```

#### P-04: 更新 Repos（Diff 模式验证）

这是一个关键测试：更新 repos 时，匹配的 repo 应保持 ID 不变。

```bash
# 记录原始 repo ID
OLD_REPO_ID=$(curl -s "$BASE_URL/api/projects/$PROJECT_ID" | jq -r '.repos[0].id')

# 更新 repos（保持同一个 repo，修改 description）
curl -s -X PUT "$BASE_URL/api/projects/$PROJECT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "repos": [
      {
        "local_path": "/tmp/test-repo",
        "git_url": "https://github.com/test/repo.git",
        "repo_type": "backend",
        "repo_type_label": "后端",
        "description": "Updated description"
      }
    ]
  }'

NEW_REPO_ID=$(curl -s "$BASE_URL/api/projects/$PROJECT_ID" | jq -r '.repos[0].id')

# 关键断言：repo ID 不变
[ "$OLD_REPO_ID" = "$NEW_REPO_ID" ] && echo "PASS: repo ID preserved" || echo "FAIL: repo ID changed"
```

#### P-05: 项目列表排序

```bash
# 创建第二个项目
P2=$(curl -s -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "Second Project"}' | jq -r '.id')

# 列表应按创建时间倒序（最新的在前）
FIRST_NAME=$(curl -s "$BASE_URL/api/projects" | jq -r '.[0].name')
[ "$FIRST_NAME" = "Second Project" ] && echo "PASS: newest first" || echo "FAIL"

# 清理
curl -s -X DELETE "$BASE_URL/api/projects/$P2"
```

#### P-06: 删除项目

```bash
curl -s -X DELETE "$BASE_URL/api/projects/$PROJECT_ID" | jq .
# 预期: {"ok": true}

# 验证已删除
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/projects/$PROJECT_ID")
[ "$STATUS" = "404" ] && echo "PASS" || echo "FAIL"
```

---

## 3. Tasks API

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 列表（支持 `?project_id=` 筛选） |
| POST | `/api/tasks` | 创建 |
| GET | `/api/tasks/:id` | 获取 |
| PUT | `/api/tasks/:id` | 更新 |
| DELETE | `/api/tasks/:id` | 删除 |
| GET | `/api/tasks/:id/todos` | 获取 todos |
| GET | `/api/tasks/:id/diff` | 获取代码 diff |

### 前置条件

Task 依赖 Project，需先创建 Project：

```bash
PROJECT_ID=$(curl -s -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "Task Test Project"}' | jq -r '.id')
```

### 测试用例

#### T-01: 创建任务

```bash
TASK_ID=$(curl -s -X POST "$BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"Test Task\",
    \"project_id\": \"$PROJECT_ID\",
    \"description\": \"Task description\",
    \"branch\": \"feature/test\"
  }" | jq -r '.id')

echo "Task ID: $TASK_ID"
```

> **注意：** 创建任务会触发后台的 `init_task`，这会尝试调用 Cody SDK。如果没有配置 AI 模型，后台任务会失败，但 API 仍返回 200。

#### T-02: 验证初始状态

```bash
STATUS=$(curl -s "$BASE_URL/api/tasks/$TASK_ID" | jq '.status')
[ "$STATUS" = "1" ] && echo "PASS: INITIALIZING" || echo "FAIL: status=$STATUS"
```

#### T-03: 按项目筛选

```bash
TASKS=$(curl -s "$BASE_URL/api/tasks?project_id=$PROJECT_ID" | jq 'length')
[ "$TASKS" -ge 1 ] && echo "PASS" || echo "FAIL"
```

#### T-04: 更新任务

```bash
curl -s -X PUT "$BASE_URL/api/tasks/$TASK_ID" \
  -H "Content-Type: application/json" \
  -d '{"description": "Updated description"}' | jq -r '.description'
# 预期: Updated description
```

#### T-05: PRD 存储

```bash
PRD_TASK=$(curl -s -X POST "$BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"PRD Task\",
    \"project_id\": \"$PROJECT_ID\",
    \"prd\": \"# Requirements\n- Feature A\"
  }" | jq -r '.prd')

echo "$PRD_TASK" | grep -q "Feature A" && echo "PASS" || echo "FAIL"
```

#### T-06: Todos 初始为空

```bash
TODOS=$(curl -s "$BASE_URL/api/tasks/$TASK_ID/todos" | jq 'length')
[ "$TODOS" = "0" ] && echo "PASS" || echo "FAIL"
```

#### T-07: Diff 端点可用

```bash
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/tasks/$TASK_ID/diff")
[ "$STATUS" = "200" ] && echo "PASS" || echo "FAIL"
```

#### T-08: 删除任务

```bash
curl -s -X DELETE "$BASE_URL/api/tasks/$TASK_ID" | jq .

STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/tasks/$TASK_ID")
[ "$STATUS" = "404" ] && echo "PASS" || echo "FAIL"
```

#### 清理

```bash
curl -s -X DELETE "$BASE_URL/api/projects/$PROJECT_ID"
```

---

## 4. Sessions API

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions/:id/status` | 获取 session 状态 |
| GET | `/api/sessions/:id/logs` | 获取 session 日志 |
| WS | `/api/ws` | WebSocket 实时推送（见 06_sse_testing.md） |

### 测试用例

#### SS-01: Session 状态查询

Session ID 格式为 `task:{task_id}:plan`、`init:{project_id}:{knowledge_type}` 等。

```bash
# 假设已有一个任务创建后的 session
# session_id 需要 URL 编码（包含冒号）
SESSION_ID="task:${TASK_ID}:plan"
ENCODED_ID=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$SESSION_ID', safe=''))")

curl -s "$BASE_URL/api/sessions/$ENCODED_ID/status" | jq .
# 预期：返回 session 状态对象，包含 status、started_at 等字段
# 如果 session 不存在，返回 404
```

#### SS-02: Session 日志

```bash
curl -s "$BASE_URL/api/sessions/$ENCODED_ID/logs" | jq .
# 预期：返回 JSON 数组
# - 如果日志文件不存在，返回空数组 []
# - 如果存在，每条记录包含事件数据
```

### 注意事项

- Session ID 包含冒号 `:`，在 URL 中需要编码为 `%3A`
- `curl` 会自动处理 URL 编码，但拼接时要注意
- WebSocket 实时推送见 `06_sse_testing.md`

---

## 5. 数据库交叉验证

API 测试后，可直接查询 SQLite 数据库验证数据一致性：

```bash
DB_PATH="$HOME/.daiflow/daiflow.db"

# 检查表是否存在
sqlite3 "$DB_PATH" ".tables"
# 预期: projects  project_repos  tasks  todos  sessions  settings

# 检查表数量
TABLE_COUNT=$(sqlite3 "$DB_PATH" "SELECT count(*) FROM sqlite_master WHERE type='table';")
[ "$TABLE_COUNT" = "6" ] && echo "PASS" || echo "FAIL"

# 验证 settings 表数据
sqlite3 "$DB_PATH" "SELECT key, value FROM settings;"

# 验证 projects 数量
sqlite3 "$DB_PATH" "SELECT count(*) FROM projects;"
```

---

## 6. 本地文件验证

```bash
# 验证 DaiFlow 目录结构
[ -d "$HOME/.daiflow" ] && echo "PASS" || echo "FAIL"
[ -d "$HOME/.daiflow/sessions" ] && echo "PASS" || echo "FAIL"
[ -d "$HOME/.daiflow/projects" ] && echo "PASS" || echo "FAIL"
[ -d "$HOME/.daiflow/tasks" ] && echo "PASS" || echo "FAIL"
[ -f "$HOME/.daiflow/daiflow.db" ] && echo "PASS" || echo "FAIL"
```

---

## 测试执行顺序建议

1. Settings（无依赖）
2. Projects（无依赖）
3. Tasks（依赖 Project）
4. Sessions（依赖 Task 创建后产生的 session）
5. 数据库验证
6. 文件验证

每个分类测试完后清理测试数据，避免影响下一个分类。
