# 黑盒测试 — 环境准备

> **目标：** 从零搭建测试环境，确保后端服务正常运行

---

## 第一步：安装后端依赖

```bash
cd <project-root>
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

验证安装成功：
```bash
.venv/bin/python -c "import daiflow; print('OK')"
```

## 第二步：构建前端（可选）

如果需要测试静态文件服务（`GET /`），需要先构建前端：

```bash
cd frontend && npm install && npm run build && cd ..
```

如果只测 API 层，可跳过此步。

## 第三步：配置 AI 模型

DaiFlow 需要 AI 模型才能执行端到端流程测试（Plan 生成、Todo 拆解等）。有两种方式：

### 方式 A：通过环境变量

先扫描用户是否有下面的环境变量，有的话，可以直接拿来用

```bash
export CODY_MODEL=qwen3.5-plus
export CODY_MODEL_API_KEY=<your-api-key>
export CODY_MODEL_BASE_URL=https://coding.dashscope.aliyuncs.com/v1
```

如果用户没有，那就需要向用户要这些变量

要到变量后，启动服务后，调用设置 API：

```bash
curl -s -X PUT http://localhost:8000/api/settings \
  -H "Content-Type: application/json" \
  -d '{
    "cody_model": "qwen3.5-plus",
    "cody_base_url": "https://coding.dashscope.aliyuncs.com/v1",
    "cody_api_key": "<your-api-key>"
  }'
```

> **注意：** 如果没有 AI 模型配置，CRUD 测试和错误处理测试仍可正常执行，但端到端流程测试（Plan 生成等）将失败。

## 第四步：启动后端服务

```bash
cd <project-root>
.venv/bin/uvicorn daiflow.main:app --host 127.0.0.1 --port 8000 &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"
```

或使用 CLI 入口：
```bash
.venv/bin/daiflow start
```

## 第五步：验证服务可达

```bash
# 验证 API 可达
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/settings
# 预期输出: 200

# 验证静态文件服务（如果构建了前端）
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/
# 预期输出: 200
```

## 第六步：确认测试工具

```bash
# 确认 jq 可用（用于 JSON 解析）
jq --version

# 确认 sqlite3 可用（用于数据库检查）
sqlite3 --version

# 确认 curl 支持 SSE
curl --version | head -1
```

如果缺少 `jq`：
```bash
# macOS
brew install jq

# Ubuntu/Debian
apt-get install jq
```

---

## 测试环境变量

为了方便后续测试脚本使用，设置以下变量：

```bash
export BASE_URL="http://localhost:8000"
export DAIFLOW_HOME="$HOME/.daiflow"
export DB_PATH="$DAIFLOW_HOME/daiflow.db"
```

---

## 清理环境（测试结束后）

```bash
# 停止服务
kill $SERVER_PID

# 可选：清理测试数据（危险！会删除所有 DaiFlow 数据）
# rm -rf ~/.daiflow
```

---

## 检查清单

在开始正式测试前，确认以下条件：

- [ ] `.venv` 已激活，依赖已安装
- [ ] 后端服务在 `localhost:8000` 运行
- [ ] `curl -s http://localhost:8000/api/settings` 返回 200
- [ ] `jq` 和 `sqlite3` 可用
- [ ] （端到端测试需要）AI 模型已配置
- [ ] `~/.daiflow/` 目录存在

全部确认后，进入 `04_api_crud_testing.md` 开始 API 测试。
