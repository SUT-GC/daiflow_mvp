# 黑盒测试 — 错误处理与边界测试

> **目标：** 验证系统在异常输入、错误状态下的行为
> **原则：** 系统应返回明确的错误码和错误信息，不应 500 崩溃

---

## 1. 资源不存在 (404)

对每个支持 `:id` 的端点，使用不存在的 ID 请求：

```bash
# 项目
curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/projects/nonexistent"
# 预期: 404

# 任务
curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/tasks/nonexistent"
# 预期: 404

# 删除不存在的项目
curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE_URL/api/projects/nonexistent"
# 预期: 404

# 删除不存在的任务
curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE_URL/api/tasks/nonexistent"
# 预期: 404

# 执行不存在的 Todo
curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/todos/nonexistent/execute"
# 预期: 404

# 不存在的阶段转换
curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/tasks/nonexistent/lock-plan"
# 预期: 404

curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/tasks/nonexistent/start-coding"
# 预期: 404

curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/tasks/nonexistent/start-review"
# 预期: 404
```

### 验证要点

- 状态码统一为 `404`
- 响应体包含 `detail` 字段说明原因
- 服务端日志不应有 500 错误或 traceback

---

## 2. 参数校验 (422)

### 缺少必填字段

```bash
# 创建项目不传 name
curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d '{}'
# 预期: 422

# 创建任务不传 name
curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "xxx"}'
# 预期: 422
```

### 无效 JSON

```bash
curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE_URL/api/settings" \
  -H "Content-Type: application/json" \
  -d 'not json'
# 预期: 422
```

### 无效 Content-Type

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: text/plain" \
  -d '{"name": "test"}'
# 预期: 422
```

---

## 3. 非法状态转换 (400)

Task 状态机有严格的转换规则。测试非法转换应返回 400：

```bash
# 创建任务（状态 = INITIALIZING(1)）
TASK_ID=$(curl -s -X POST "$BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"ST Test\", \"project_id\": \"$PROJECT_ID\"}" | jq -r '.id')

# 从 INITIALIZING 不能直接 lock-plan（需要先到 PLANNING）
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$BASE_URL/api/tasks/$TASK_ID/lock-plan")
[ "$STATUS" = "400" ] && echo "PASS" || echo "FAIL: $STATUS"

# 从 INITIALIZING 不能 start-coding
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$BASE_URL/api/tasks/$TASK_ID/start-coding")
[ "$STATUS" = "400" ] && echo "PASS" || echo "FAIL: $STATUS"

# 从 INITIALIZING 不能 start-review
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$BASE_URL/api/tasks/$TASK_ID/start-review")
[ "$STATUS" = "400" ] && echo "PASS" || echo "FAIL: $STATUS"

# 验证错误信息
ERROR=$(curl -s -X POST "$BASE_URL/api/tasks/$TASK_ID/lock-plan" | jq -r '.detail')
echo "$ERROR" | grep -q "Cannot transition" && echo "PASS: clear error msg" || echo "FAIL"
```

### 完整的非法转换矩阵

对每个阶段转换 API，在每个不合法的起始状态下调用，验证返回 400：

| API | 合法起始状态 | 非法状态（应返回 400） |
|-----|------------|---------------------|
| lock-plan | PLANNING(2) | 0, 1, 3, 4, 5, 6, 7 |
| start-coding | TODO_READY(4) | 0, 1, 2, 3, 5, 6, 7 |
| start-review | CODING(5) | 0, 1, 2, 3, 4, 6, 7 |

---

## 4. 边界条件

### 空字符串

```bash
# 创建项目名为空字符串
curl -s -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": ""}' | jq .
# 观察行为：应该拒绝（422）或接受

# Settings 空值不应覆盖
curl -s -X PUT "$BASE_URL/api/settings" \
  -H "Content-Type: application/json" \
  -d '{"cody_model": "real-model"}'

curl -s -X PUT "$BASE_URL/api/settings" \
  -H "Content-Type: application/json" \
  -d '{"cody_model": ""}'

MODEL=$(curl -s "$BASE_URL/api/settings" | jq -r '.cody_model')
# 预期: "real-model"（空字符串应被跳过）
```

### 超长字符串

```bash
LONG_NAME=$(python3 -c "print('x' * 10000)")
curl -s -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"$LONG_NAME\"}" | jq '.id'
# 观察：是否正常处理，不应 500
```

### 特殊字符

```bash
# 项目名包含特殊字符
curl -s -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "项目 <script>alert(1)</script> 测试 & \"quotes\""}' | jq '.name'
# 预期：原样存储和返回，不做 HTML 转义（由前端处理）
```

### 重复操作

```bash
# 连续创建同名项目
ID1=$(curl -s -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "Dup Project"}' | jq -r '.id')

ID2=$(curl -s -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "Dup Project"}' | jq -r '.id')

# 预期：两个都成功，ID 不同（允许同名）
[ "$ID1" != "$ID2" ] && echo "PASS: different IDs" || echo "FAIL"

# 清理
curl -s -X DELETE "$BASE_URL/api/projects/$ID1" > /dev/null
curl -s -X DELETE "$BASE_URL/api/projects/$ID2" > /dev/null
```

### 删除后关联

```bash
# 删除项目后，该项目的任务应该如何处理？
PID=$(curl -s -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "Del Test"}' | jq -r '.id')

TID=$(curl -s -X POST "$BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"Task\", \"project_id\": \"$PID\"}" | jq -r '.id')

# 删除项目
curl -s -X DELETE "$BASE_URL/api/projects/$PID" > /dev/null

# 检查任务是否还在（级联删除 or 孤立？）
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/tasks/$TID")
echo "Task after project delete: HTTP $STATUS"
# 记录实际行为（级联删除则 404，保留则 200）
```

---

## 5. 并发安全

### 同时创建多个资源

```bash
# 并发创建 10 个项目
for i in $(seq 1 10); do
  curl -s -X POST "$BASE_URL/api/projects" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"Concurrent $i\"}" &
done
wait

# 验证全部创建成功
COUNT=$(curl -s "$BASE_URL/api/projects" | jq '[.[] | select(.name | startswith("Concurrent"))] | length')
[ "$COUNT" = "10" ] && echo "PASS: all 10 created" || echo "FAIL: only $COUNT created"

# 清理
for id in $(curl -s "$BASE_URL/api/projects" | jq -r '.[] | select(.name | startswith("Concurrent")) | .id'); do
  curl -s -X DELETE "$BASE_URL/api/projects/$id" > /dev/null
done
```

### 同时更新同一资源

```bash
PID=$(curl -s -X POST "$BASE_URL/api/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "Race Test"}' | jq -r '.id')

# 并发更新
for i in $(seq 1 5); do
  curl -s -X PUT "$BASE_URL/api/projects/$PID" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"Update $i\"}" &
done
wait

# 验证最终状态一致（应是某一次更新的值，不是乱码）
NAME=$(curl -s "$BASE_URL/api/projects/$PID" | jq -r '.name')
echo "$NAME" | grep -q "Update" && echo "PASS: consistent state" || echo "FAIL: $NAME"

curl -s -X DELETE "$BASE_URL/api/projects/$PID" > /dev/null
```

---

## 6. 服务端日志检查

每轮测试后，检查服务端日志是否有异常：

```bash
# 如果服务端日志输出到终端，检查：
# - 不应有 500 Internal Server Error
# - 不应有 Python traceback（除非是预期的 400/404）
# - 不应有 "database is locked" 错误

# 也可以通过统计 HTTP 状态码分布来判断：
# 预期：只有 200, 400, 404, 422，没有 500
```

---

## 测试报告模板

```markdown
## ERR: 错误处理 (N/N)

| 用例 | 预期 | 结果 |
|------|------|------|
| ERR-01 不存在的项目 | 404 | ✓/✗ |
| ERR-02 不存在的任务 | 404 | ✓/✗ |
| ERR-03 缺少必填字段 | 422 | ✓/✗ |
| ERR-04 非法状态转换 | 400 + "Cannot transition" | ✓/✗ |
| ERR-05 空字符串不覆盖 | 原值保留 | ✓/✗ |
| ERR-06 并发创建 | 全部成功 | ✓/✗ |
| ERR-07 服务端无 500 | 日志干净 | ✓/✗ |
```
