# 黑盒测试 — SSE 实时推送测试

> **目标：** 验证 Server-Sent Events (SSE) 流式推送功能
> **难点：** SSE 是长连接流式协议，测试方法与普通 REST API 不同

---

## SSE 基础知识

### 什么是 SSE

SSE (Server-Sent Events) 是 HTTP 长连接协议，服务端持续向客户端推送事件：

```
Content-Type: text/event-stream

data: {"type": "text_delta", "content": "Hello"}

data: {"type": "thinking", "content": "Let me think..."}

data: {"type": "done"}
```

### DaiFlow 中的 SSE 端点

| 端点 | 用途 | 触发条件 |
|------|------|---------|
| `GET /api/sessions/{id}/stream` | 单个 session 实时流 | session 正在运行 |
| `GET /api/projects/{id}/init/stream` | 项目初始化总线 | 有 init session 在运行 |
| `POST /api/tasks/{id}/plan/chat` | Plan 阶段对话 | 用户发送消息 |
| `POST /api/tasks/{id}/todo/chat` | Todo 阶段对话 | 用户发送消息 |
| `POST /api/todos/{id}/chat` | Todo 执行中对话 | 用户发送消息 |
| `POST /api/tasks/{id}/review/chat` | Review 阶段对话 | 用户发送消息 |

### DaiFlow SSE 事件类型

| 事件类型 | 说明 | 来源 |
|---------|------|------|
| `text_delta` | AI 文本输出增量 | Cody SDK chunk |
| `thinking` | AI 思考过程 | Cody SDK chunk |
| `tool_call` | AI 调用工具 | Cody SDK chunk |
| `tool_result` | 工具执行结果 | Cody SDK chunk |
| `done` | 会话结束 | Cody SDK chunk |
| `status_change` | session 状态变更 | SessionRunner |
| `plan_updated` | 技术方案被修改 | 文件写入检测 |
| `todo_updated` | Todo 列表被修改 | 文件写入检测 |
| `code_updated` | 代码被修改 | 文件写入检测 |
| `session_status` | init 总线事件 | 项目初始化 |

---

## 测试方法

### 方法 1: curl 带超时

最简单的方式，适合验证 SSE 可用性：

```bash
# -N: 禁用缓冲（关键！否则看不到流式输出）
# --max-time: 超时限制（秒）
curl -N "$BASE_URL/api/sessions/$ENCODED_SESSION_ID/stream" --max-time 10
```

### 方法 2: curl 管道处理

适合提取和验证特定事件：

```bash
# 捕获 SSE 输出到文件
timeout 10 curl -N -s "$BASE_URL/api/sessions/$ENCODED_SESSION_ID/stream" > /tmp/sse_output.txt 2>/dev/null

# 分析事件
grep "^data:" /tmp/sse_output.txt | head -5
```

### 方法 3: Python 脚本

适合复杂的 SSE 测试：

```python
import httpx
import json

with httpx.stream("GET", f"{base_url}/api/sessions/{session_id}/stream") as r:
    for line in r.iter_lines():
        if line.startswith("data:"):
            event = json.loads(line[5:].strip())
            print(f"Event: {event['type']}")
            if event["type"] == "done":
                break
```

---

## 测试用例

### E-01: SSE Content-Type 验证

```bash
CONTENT_TYPE=$(curl -s -o /dev/null -w "%{content_type}" \
  "$BASE_URL/api/projects/$PROJECT_ID/init/stream")
echo "$CONTENT_TYPE" | grep -q "text/event-stream" && echo "PASS" || echo "FAIL"
```

### E-02: 项目初始化 SSE 流

```bash
# 1. 先触发项目初始化
curl -s -X POST "$BASE_URL/api/projects/$PROJECT_ID/init" > /dev/null

# 2. 立即监听 SSE 流
timeout 30 curl -N -s "$BASE_URL/api/projects/$PROJECT_ID/init/stream" > /tmp/init_sse.txt 2>/dev/null &
SSE_PID=$!

# 3. 等待完成
wait $SSE_PID 2>/dev/null

# 4. 验证收到了 session_status 事件
grep -c "data:" /tmp/init_sse.txt
# 预期：多条 data: 行
```

### E-03: Plan 对话 SSE 流

```bash
# 发送对话消息，同时捕获 SSE 输出
timeout 30 curl -N -s -X POST "$BASE_URL/api/tasks/$TASK_ID/plan/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello"}' > /tmp/chat_sse.txt 2>/dev/null

# 验证收到 text_delta 事件
grep "text_delta" /tmp/chat_sse.txt
# 预期：至少 1 条 text_delta 事件

# 验证以 done 事件结束
tail -5 /tmp/chat_sse.txt | grep "done"
# 预期：最后几行包含 done 事件
```

### E-04: Session 实时流

```bash
# 需要一个正在运行的 session
# 如果有 todo 正在执行：
curl -s -X POST "$BASE_URL/api/todos/$TODO_ID/execute" > /dev/null

SESSION_ID="todo:$TODO_ID"
ENCODED_ID=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$SESSION_ID', safe=''))")

timeout 60 curl -N -s "$BASE_URL/api/sessions/$ENCODED_ID/stream" > /tmp/session_sse.txt 2>/dev/null

# 验证事件序列
echo "=== Event types received ==="
grep "^data:" /tmp/session_sse.txt | \
  python3 -c "
import sys, json
for line in sys.stdin:
    try:
        event = json.loads(line[5:].strip())
        print(event.get('type', 'unknown'))
    except: pass
" | sort | uniq -c | sort -rn
```

### E-05: SSE 事件格式验证

每条 SSE 事件应该是合法的 JSON：

```bash
INVALID_COUNT=0
while IFS= read -r line; do
  if [[ "$line" == data:* ]]; then
    JSON="${line#data: }"
    echo "$JSON" | python3 -c "import json, sys; json.load(sys.stdin)" 2>/dev/null
    if [ $? -ne 0 ]; then
      INVALID_COUNT=$((INVALID_COUNT + 1))
      echo "INVALID JSON: $JSON"
    fi
  fi
done < /tmp/chat_sse.txt

[ "$INVALID_COUNT" = "0" ] && echo "PASS: all events are valid JSON" || echo "FAIL: $INVALID_COUNT invalid events"
```

---

## SSE 测试的注意事项

### 1. 缓冲问题

`curl` 默认会缓冲输出，必须使用 `-N`（`--no-buffer`）来禁用缓冲，否则 SSE 事件会被批量延迟输出。

### 2. 超时控制

SSE 是长连接，如果不设置超时，`curl` 会一直挂起。使用 `--max-time` 或 `timeout` 命令。

### 3. 时序问题

SSE 流需要在事件产生**之前**或**同时**建立连接。如果连接太晚，可能错过事件。

**推荐模式：**
```bash
# 先建立 SSE 监听（后台）
timeout 30 curl -N -s "$BASE_URL/api/xxx/stream" > /tmp/sse.txt &

# 再触发产生事件的操作
curl -s -X POST "$BASE_URL/api/xxx/trigger"

# 等待并检查结果
wait
grep "data:" /tmp/sse.txt
```

### 4. 并发连接

可以同时监听多个 SSE 流，验证频道隔离：
```bash
# 监听两个不同的 session
timeout 10 curl -N -s "$BASE_URL/api/sessions/session1/stream" > /tmp/sse1.txt &
timeout 10 curl -N -s "$BASE_URL/api/sessions/session2/stream" > /tmp/sse2.txt &
wait

# 验证两个流的事件互不干扰
```

### 5. 已完成的 session

对已完成（status=done）的 session 发起 stream 请求：
- 应立即返回并关闭连接
- 或返回一个 `done` 事件后关闭
- 不应无限挂起
