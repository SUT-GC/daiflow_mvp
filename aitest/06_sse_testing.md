# 黑盒测试 — WebSocket 实时推送测试

> **目标：** 验证 WebSocket 双向通信和频道订阅/推送功能
> **说明：** DaiFlow 使用单一 WebSocket 连接 (`WS /api/ws`) 多路复用所有实时通信

---

## WebSocket 基础知识

### DaiFlow WebSocket 协议

DaiFlow 使用单一 WebSocket 端点 `/api/ws`，通过 JSON 消息进行双向通信：

**Client → Server（动作消息）：**

```json
{"action": "ping"}
{"action": "subscribe", "channel": "session:task:42:plan"}
{"action": "unsubscribe", "channel": "session:task:42:plan"}
{"action": "chat", "id": "req_1", "chat_path": "plan", "entity_id": "task_42", "message": "调整方案"}
```

**Server → Client（事件推送）：**

```json
{"type": "pong"}
{"type": "subscribed", "channel": "session:task:42:plan"}
{"channel": "session:task:42:plan", "event": {"type": "text_delta", "content": "Hello"}}
{"type": "error", "code": "unknown_action", "message": "Unknown action: foobar"}
```

### DaiFlow 频道命名

| 频道格式 | 用途 | 触发条件 |
| ------- | ---- | ------- |
| `session:{session_id}` | 单个 session 实时流 | session 正在运行 |
| `project:init:{project_id}` | 项目初始化总线 | 有 init session 在运行 |
| `chat:{request_id}` | 聊天响应流（临时） | 用户发送 chat 消息 |

### DaiFlow 事件类型

| 事件类型 | 说明 | 来源 |
| ------- | ---- | ---- |
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

### 方法 1: websocat（命令行 WebSocket 客户端）

```bash
# 安装
brew install websocat  # macOS
# 或 cargo install websocat

# 连接并交互
echo '{"action": "ping"}' | websocat ws://localhost:8000/api/ws
```

### 方法 2: Python 脚本

```python
import asyncio
import json
import websockets

async def test_ws():
    async with websockets.connect("ws://localhost:8000/api/ws") as ws:
        # Ping
        await ws.send(json.dumps({"action": "ping"}))
        resp = json.loads(await ws.recv())
        assert resp["type"] == "pong"

        # Subscribe
        await ws.send(json.dumps({"action": "subscribe", "channel": "session:task:42:plan"}))
        resp = json.loads(await ws.recv())
        assert resp["type"] == "subscribed"

asyncio.run(test_ws())
```

---

## 测试用例

### E-01: Ping/Pong 心跳

```python
await ws.send(json.dumps({"action": "ping"}))
resp = json.loads(await ws.recv())
assert resp == {"type": "pong"}
```

### E-02: 频道订阅

```python
await ws.send(json.dumps({"action": "subscribe", "channel": "session:test:1"}))
resp = json.loads(await ws.recv())
assert resp == {"type": "subscribed", "channel": "session:test:1"}
```

### E-03: 未知 action 返回错误

```python
await ws.send(json.dumps({"action": "foobar"}))
resp = json.loads(await ws.recv())
assert resp["type"] == "error"
assert resp["code"] == "unknown_action"
```

### E-04: 项目初始化 WebSocket 订阅

```python
# 1. 先连接 WebSocket 并订阅
await ws.send(json.dumps({"action": "subscribe", "channel": f"project:init:{project_id}"}))
ack = json.loads(await ws.recv())
assert ack["type"] == "subscribed"

# 2. 触发项目初始化
requests.post(f"{base_url}/api/projects/{project_id}/init")

# 3. 接收 session_status 事件
events = []
while True:
    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
    if "event" in msg:
        events.append(msg["event"])
        if msg["event"].get("type") == "status_change" and msg["event"]["status"] in (2, 3):
            break

assert len(events) > 0
```

### E-05: Chat 通过 WebSocket

```python
# 发送 chat 消息
await ws.send(json.dumps({
    "action": "chat",
    "id": "req_1",
    "chat_path": "plan",
    "entity_id": task_id,
    "message": "Hello"
}))

# 接收 chat 响应流
events = []
while True:
    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
    if msg.get("channel", "").startswith("chat:"):
        events.append(msg["event"])
        if msg["event"]["type"] == "done":
            break

# 验证收到了 text_delta 事件
assert any(e["type"] == "text_delta" for e in events)
```

### E-06: Chat 缺少必填字段返回错误

```python
await ws.send(json.dumps({"action": "chat", "id": "req_2"}))
resp = json.loads(await ws.recv())
assert resp["type"] == "error"
assert resp["code"] == "invalid_request"
assert resp["id"] == "req_2"
```

### E-07: 断开连接清理订阅

```python
# 使用一个独立连接订阅，然后关闭
async with websockets.connect("ws://localhost:8000/api/ws") as ws2:
    await ws2.send(json.dumps({"action": "subscribe", "channel": "session:cleanup:test"}))
    await ws2.recv()  # subscribed ack
# ws2 关闭后，服务端应清理该连接的所有订阅
```

---

## WebSocket 测试的注意事项

### 1. 连接管理

WebSocket 是长连接，测试完成后需要正确关闭连接。使用 `async with` 确保自动关闭。

### 2. 超时控制

使用 `asyncio.wait_for(ws.recv(), timeout=N)` 避免无限等待。

### 3. 多路复用

DaiFlow 使用单连接多路复用，同一连接可以同时订阅多个频道。测试时注意区分来自不同频道的消息。

### 4. 消息顺序

WebSocket 保证消息顺序，但多个频道的事件可能交错到达。按 `channel` 字段过滤即可。

### 5. 重连测试

断开 WebSocket 后重新连接，验证：

- 需要重新订阅频道（服务端不保留断开连接的订阅）
- 可通过 `GET /api/sessions/{id}/status` + `/logs` 恢复状态
