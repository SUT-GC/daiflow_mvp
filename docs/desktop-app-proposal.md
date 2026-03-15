# DaiFlow 桌面端改造方案

## 1. 背景与目标

DaiFlow 当前是一个 Web 应用（React SPA + FastAPI 后端），通过 `daiflow start` CLI 启动后端并自动打开浏览器访问 `http://localhost:8000`。

**目标：** 将 DaiFlow 包装为桌面端应用，提供原生窗口体验，同时保持现有 Web 架构不变，降低改造成本。

**技术选型：Electron**
- 成熟稳定，生态完善，社区资源丰富
- 本质是嵌入式 Chromium，与现有前端 100% 兼容
- 跨平台支持 macOS / Windows / Linux
- 支持自动更新、系统托盘、原生菜单等桌面特性

## 2. 整体架构

```
┌─────────────────────────────────────────────────┐
│                 Electron Shell                   │
│                                                  │
│  ┌──────────────┐     ┌───────────────────────┐ │
│  │  Main Process │     │   Renderer (BrowserWindow) │
│  │               │     │                       │ │
│  │  - 生命周期管理  │     │  React SPA            │ │
│  │  - venv 管理    │     │  (daiflow/static/)    │ │
│  │  - 后端子进程   │     │                       │ │
│  │  - 端口管理     │     │  HTTP → localhost:N   │ │
│  │  - Splash 页面  │     │  WS   → localhost:N   │ │
│  └──────┬───────┘     └───────────────────────┘ │
│         │                                        │
│         │ spawn 子进程                             │
│         ▼                                        │
│  ┌──────────────────────┐                        │
│  │  Python venv          │                        │
│  │  uvicorn daiflow.main │                        │
│  │  :app --port N        │                        │
│  └──────────┬───────────┘                        │
│             │                                    │
│             ▼                                    │
│  ┌──────────────────────┐                        │
│  │  {userData}/data/     │  (DAIFLOW_HOME)       │
│  │  ├── daiflow.db       │                        │
│  │  ├── sessions/        │                        │
│  │  ├── projects/        │                        │
│  │  └── tasks/           │                        │
│  └──────────────────────┘                        │
└─────────────────────────────────────────────────┘
```

## 3. 目录结构

在项目根目录新增 `electron/` 目录：

```
daiflow_mvp/
├── daiflow/                  # 现有后端（不改动）
├── frontend/                 # 现有前端（不改动）
├── electron/                 # 新增：Electron 壳
│   ├── main.js               # 主进程入口
│   ├── preload.js            # 主窗口预加载脚本（安全桥接）
│   ├── splash-preload.js     # Splash 窗口预加载脚本（接收状态更新 IPC）
│   ├── splash.html           # 启动加载页
│   ├── python-manager.js     # Python/venv 管理模块
│   ├── port-manager.js       # 端口管理模块
│   ├── backend-manager.js    # 后端子进程生命周期
│   └── icons/                # 应用图标（各平台格式）
│       ├── icon.icns          # macOS
│       ├── icon.ico           # Windows
│       └── icon.png           # Linux (512x512)
├── electron-builder.yml      # 打包配置
├── package.json              # Electron 依赖 & scripts（根目录）
└── ...
```

## 4. 详细设计

### 4.1 Python 环境检测与 venv 管理

**模块：** `electron/python-manager.js`

#### 4.1.1 Python 检测

启动时检测用户系统中的 Python 版本，按优先级查找：

```
查找顺序：python3 → python → 自定义路径（用户设置）
```

**检测逻辑：**

```javascript
const PYTHON_CANDIDATES = ['python3', 'python']
const MIN_PYTHON_VERSION = [3, 11]

async function findPython() {
  for (const cmd of PYTHON_CANDIDATES) {
    try {
      const result = spawnSync(cmd, ['--version'], { encoding: 'utf-8' })
      // 输出格式：Python 3.11.5
      const output = result.stdout || result.stderr || ''
      const match = output.match(/Python (\d+)\.(\d+)\.(\d+)/)
      if (match) {
        const [major, minor] = [parseInt(match[1]), parseInt(match[2])]
        if (major > MIN_PYTHON_VERSION[0] ||
            (major === MIN_PYTHON_VERSION[0] && minor >= MIN_PYTHON_VERSION[1])) {
          return { command: cmd, version: `${major}.${minor}.${match[3]}` }
        }
      }
    } catch { /* 继续尝试下一个 */ }
  }
  return null  // 未找到合适的 Python
}
```

**检测失败处理：** 弹出对话框提示用户安装 Python 3.11+，附带下载链接，然后退出。

#### 4.1.2 venv 创建与管理

**venv 位置：** `{app.getPath('userData')}/python-env/`

- macOS: `~/Library/Application Support/DaiFlow/python-env/`
- Windows: `%APPDATA%/DaiFlow/python-env/`
- Linux: `~/.config/DaiFlow/python-env/`

**venv 生命周期：**

```
首次启动：
  检测 Python → 创建 venv → pip install -r requirements.txt → pip install -e .

后续启动：
  检测 venv 是否存在 → 校验 requirements.txt 哈希是否变化
    → 未变化：直接启动
    → 已变化：重新 pip install → 更新哈希缓存
```

**哈希校验机制：**

在 venv 目录下保存 `.deps-hash` 文件，存储 `requirements.txt` + `pyproject.toml` 的联合 SHA256。任一文件变化即触发重新安装，避免遗漏 `pyproject.toml` 中的依赖变更。

```javascript
const crypto = require('crypto')

function getDepsHash() {
  const hash = crypto.createHash('sha256')
  // 同时覆盖 requirements.txt 和 pyproject.toml
  for (const file of ['requirements.txt', 'pyproject.toml']) {
    const filePath = path.join(appRoot, file)
    if (fs.existsSync(filePath)) {
      hash.update(fs.readFileSync(filePath))
    }
  }
  return hash.digest('hex')
}

async function ensureVenv(pythonCmd) {
  const venvDir = path.join(app.getPath('userData'), 'python-env')
  const pipCmd = getPipPath(venvDir)       // bin/pip 或 Scripts/pip.exe
  const pythonInVenv = getPythonPath(venvDir)
  const hashFile = path.join(venvDir, '.deps-hash')

  // Step 1: 创建 venv（如不存在）
  if (!fs.existsSync(venvDir)) {
    await execAsync(`${pythonCmd} -m venv "${venvDir}"`)
  }

  // Step 2: 检查依赖是否需要更新
  const currentHash = getDepsHash()
  const cachedHash = fs.existsSync(hashFile) ? fs.readFileSync(hashFile, 'utf-8') : ''

  if (currentHash !== cachedHash) {
    // 安装依赖
    await execAsync(`"${pipCmd}" install -r "${requirementsPath}"`)
    // 安装 daiflow 包本身
    // 开发模式用 -e，打包后用普通 install（editable symlink 在打包后路径可能失效）
    const installMode = app.isPackaged ? 'install' : 'install -e'
    await execAsync(`"${pipCmd}" ${installMode} "${appRoot}"`)
    // 更新哈希
    fs.writeFileSync(hashFile, currentHash)
  }

  return { pythonPath: pythonInVenv, venvDir }
}
```

**跨平台路径差异：**

| 平台 | Python 路径 | Pip 路径 |
|------|------------|---------|
| macOS/Linux | `{venv}/bin/python` | `{venv}/bin/pip` |
| Windows | `{venv}/Scripts/python.exe` | `{venv}/Scripts/pip.exe` |

### 4.2 端口管理

**模块：** `electron/port-manager.js`

自动查找可用端口，避免与其他服务冲突：

```javascript
const net = require('net')

function findAvailablePort(startPort = 18900, endPort = 18999) {
  return new Promise((resolve, reject) => {
    const tryPort = (port) => {
      if (port > endPort) return reject(new Error('No available port'))
      const server = net.createServer()
      server.listen(port, '127.0.0.1', () => {
        server.close(() => resolve(port))
      })
      server.on('error', () => tryPort(port + 1))
    }
    tryPort(startPort)
  })
}
```

**端口范围选择：** 使用 `18900-18999`（高位端口，冲突概率极低），不再使用 `8000`。

### 4.3 后端子进程管理

**模块：** `electron/backend-manager.js`

#### 4.3.1 启动后端

```javascript
function startBackend(pythonPath, port, daiflowHome) {
  const backendProcess = spawn(
    pythonPath,
    ['-m', 'uvicorn', 'daiflow.main:app', '--host', '127.0.0.1', '--port', String(port)],
    {
      cwd: appRoot,
      env: {
        ...process.env,
        DAIFLOW_HOME: daiflowHome,
        // Electron 模式下放宽 CORS（后端只监听 localhost，安全可控）
        DAIFLOW_CORS_ORIGINS: `http://localhost:${port},http://127.0.0.1:${port}`,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  )

  // 收集日志
  backendProcess.stdout.on('data', (data) => log.info(`[backend] ${data}`))
  backendProcess.stderr.on('data', (data) => log.warn(`[backend] ${data}`))

  backendProcess.on('exit', (code) => {
    if (code !== 0 && code !== null) {
      // 非正常退出，通知用户
      dialog.showErrorBox('DaiFlow 后端异常退出', `退出码: ${code}，请查看日志`)
    }
  })

  return backendProcess
}
```

#### 4.3.2 等待后端就绪

轮询 `/api/settings/check` 接口（现有接口，无需新增）：

```javascript
async function waitForBackend(port, maxRetries = 60, intervalMs = 500) {
  const url = `http://127.0.0.1:${port}/api/settings/check`

  for (let i = 0; i < maxRetries; i++) {
    try {
      const response = await net.fetch(url)  // Electron 内置 net 模块
      if (response.ok) return true
    } catch {
      // 连接被拒绝，后端还没起来
    }
    await new Promise(r => setTimeout(r, intervalMs))
  }

  throw new Error(`后端在 ${maxRetries * intervalMs / 1000} 秒内未启动`)
}
```

最多等 30 秒（60 次 × 500ms）。

#### 4.3.3 优雅关停

```javascript
async function stopBackend(backendProcess) {
  if (!backendProcess || backendProcess.killed) return

  return new Promise((resolve) => {
    const forceKillTimer = setTimeout(() => {
      backendProcess.kill('SIGKILL')
      resolve()
    }, 5000)  // 5 秒强制终止

    backendProcess.on('exit', () => {
      clearTimeout(forceKillTimer)
      resolve()
    })

    if (process.platform === 'win32') {
      // Windows 不支持 SIGTERM，用 taskkill 优雅关停
      spawn('taskkill', ['/pid', backendProcess.pid, '/T'])
    } else {
      backendProcess.kill('SIGTERM')
    }
  })
}
```

**关停时序：** `SIGTERM` → 等待 5 秒 → `SIGKILL`。确保 FastAPI 的 `lifespan` shutdown 钩子（`stop_monitor` 等）有机会执行。

### 4.4 Electron 主进程

**文件：** `electron/main.js`

```javascript
const { app, BrowserWindow, dialog, net } = require('electron')
const path = require('path')
const { findPython, ensureVenv } = require('./python-manager')
const { findAvailablePort } = require('./port-manager')
const { startBackend, waitForBackend, stopBackend } = require('./backend-manager')

const APP_ROOT = path.join(__dirname, '..')
let mainWindow = null
let splashWindow = null
let backendProcess = null
let backendPort = null
let isQuitting = false  // 防止 stopBackend 被重复调用

// 数据目录：与 CLI 模式隔离，避免冲突
const DAIFLOW_HOME = path.join(app.getPath('userData'), 'data')

// --- 关闭保护：检查是否有运行中的 Session ---
async function checkRunningSessions(port) {
  try {
    const resp = await net.fetch(`http://127.0.0.1:${port}/api/sessions/running`)
    const data = await resp.json()
    return data.count > 0
  } catch {
    return false  // 后端无响应时不阻止关闭
  }
}

function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 480, height: 360,
    frame: false, resizable: false,
    transparent: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'splash-preload.js'),  // Splash 专用 preload
    },
  })
  splashWindow.loadFile(path.join(__dirname, 'splash.html'))
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1440, height: 900,
    minWidth: 1024, minHeight: 680,
    // macOS 使用默认标题栏，避免需要前端额外适配拖拽区域
    // 如需沉浸式标题栏，须在前端顶部添加 -webkit-app-region: drag 的拖拽条
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  mainWindow.loadURL(`http://127.0.0.1:${backendPort}`)

  // 关闭前检查是否有正在运行的 session
  mainWindow.on('close', async (e) => {
    if (isQuitting) return  // 用户已确认强制关闭，不再拦截

    e.preventDefault()
    const hasRunning = await checkRunningSessions(backendPort)
    if (hasRunning) {
      const { response } = await dialog.showMessageBox(mainWindow, {
        type: 'warning',
        buttons: ['继续等待', '强制关闭'],
        defaultId: 0,
        cancelId: 0,
        title: '任务运行中',
        message: '当前有 AI 任务正在执行',
        detail: '强制关闭可能导致任务中断和数据不一致。建议等待任务完成后再关闭。',
      })
      if (response === 1) {
        isQuitting = true
        mainWindow.close()  // 重新触发 close，此时 isQuitting=true 会放行
      }
    } else {
      isQuitting = true
      mainWindow.close()
    }
  })

  mainWindow.on('closed', () => { mainWindow = null })
}

async function bootstrap() {
  createSplashWindow()

  try {
    // Step 1: 检测 Python
    updateSplash('正在检测 Python 环境...')
    const python = await findPython()
    if (!python) {
      dialog.showErrorBox(
        'Python 未找到',
        'DaiFlow 需要 Python 3.11 或更高版本。\n请安装后重启应用。'
      )
      app.quit()
      return
    }

    // Step 2: 确保 venv 和依赖
    updateSplash('正在准备 Python 环境...')
    const { pythonPath } = await ensureVenv(python.command)

    // Step 3: 查找可用端口
    backendPort = await findAvailablePort()

    // Step 4: 启动后端
    updateSplash('正在启动 DaiFlow 服务...')
    backendProcess = startBackend(pythonPath, backendPort, DAIFLOW_HOME)

    // Step 5: 等待后端就绪
    await waitForBackend(backendPort)

    // Step 6: 运行数据库迁移（确保 schema 与最新版本一致）
    updateSplash('正在检查数据库...')
    await runMigrations(pythonPath)

    // Step 7: 打开主窗口
    createMainWindow()
    splashWindow.close()

  } catch (err) {
    dialog.showErrorBox('启动失败', err.message)
    app.quit()
  }
}

// 运行 Alembic 数据库迁移
async function runMigrations(pythonPath) {
  return execAsync(`"${pythonPath}" -m alembic upgrade head`, { cwd: APP_ROOT })
}

function updateSplash(message) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send('status', message)
  }
}

app.whenReady().then(bootstrap)

app.on('window-all-closed', async () => {
  await stopBackend(backendProcess)
  app.quit()
})

// macOS: 点击 dock 图标重新打开窗口
app.on('activate', () => {
  if (mainWindow === null && backendProcess) {
    isQuitting = false  // 重置标志，新窗口需要重新拦截
    createMainWindow()
  }
})
```

### 4.5 启动加载页（Splash）

**文件：** `electron/splash.html`

展示品牌 Logo + 加载状态文案，使用项目现有的设计系统（Sora 字体 + 主题色）。

**状态文案流转：**
```
正在检测 Python 环境...
正在准备 Python 环境...（首次启动较慢）
正在安装依赖...（pip install 时显示）
正在启动 DaiFlow 服务...
即将就绪...
```

Splash 页面通过 IPC 接收状态更新，需要 `splash-preload.js` 暴露接口：

```javascript
// electron/splash-preload.js
const { contextBridge, ipcRenderer } = require('electron')
contextBridge.exposeInMainWorld('electronAPI', {
  onStatus: (callback) => ipcRenderer.on('status', (_event, msg) => callback(msg)),
})
```

Splash HTML 中通过 `window.electronAPI.onStatus(msg => ...)` 更新文案。

### 4.6 关闭保护：运行中 Session 检测

当用户尝试关闭窗口时，Electron 主进程调用后端接口检查是否有正在运行的 session，有则弹窗提醒。

**Electron 端检测函数：**

```javascript
async function checkRunningSessions(port) {
  try {
    const resp = await net.fetch(`http://127.0.0.1:${port}/api/sessions/running`)
    const data = await resp.json()
    return data.count > 0
  } catch {
    return false  // 后端无响应时不阻止关闭
  }
}
```

**后端新增接口（仅需 ~10 行）：**

在 `daiflow/routers/sessions.py` 中新增：

```python
@router.get("/api/sessions/running")
async def get_running_sessions(db: AsyncSession = Depends(get_db)):
    """返回当前正在运行的 session 数量，供 Electron 关闭保护使用。"""
    from sqlalchemy import func, select
    from daiflow.models import Session, SessionStatus

    result = await db.execute(
        select(func.count()).where(Session.status == SessionStatus.RUNNING)
    )
    count = result.scalar() or 0
    return {"count": count}
```

**交互流程：**

```
用户点击关闭 / Cmd+Q
  → Electron 拦截 close 事件
  → 调用 GET /api/sessions/running
  → count > 0?
    → 是：弹窗 "当前有 AI 任务正在执行，建议等待完成"
         [继续等待]  [强制关闭]
    → 否：正常关闭
```

### 4.7 CORS 适配

**现状：** `daiflow/main.py` 中 CORS origins 通过 `DAIFLOW_CORS_ORIGINS` 环境变量配置，默认值为 `http://localhost:3000,http://localhost:8000`。

**改造：** 无需修改后端代码（CORS 部分）。Electron 启动后端时通过环境变量注入当前端口即可：

```javascript
env: {
  DAIFLOW_CORS_ORIGINS: `http://localhost:${port},http://127.0.0.1:${port}`
}
```

由于 Electron 的 `BrowserWindow.loadURL('http://127.0.0.1:N')` 发起的请求 origin 就是 `http://127.0.0.1:N`，与标准浏览器行为一致，**CORS 完全兼容，无需改动后端**。

### 4.8 WebSocket 兼容性

**现状分析：**

前端 `WebSocketClient.ts` 中 WebSocket URL 构建方式：

```typescript
private getWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/ws`
}
```

**兼容性：** 在 Electron 中 `window.location.host` 会正确返回 `127.0.0.1:N`，协议为 `http:` 对应 `ws:`，**完全兼容，无需改动**。

**重连机制：** 前端已实现完善的重连策略（指数退避 5 次 + 60 秒兜底重连），满足桌面端需求（窗口最小化/休眠恢复）。

### 4.9 数据目录隔离

**设计决策：** 桌面端使用独立的 `DAIFLOW_HOME`，与 CLI 模式（`~/.daiflow/`）隔离，避免混用导致数据冲突。

| 模式 | DAIFLOW_HOME |
|------|-------------|
| CLI (`daiflow start`) | `~/.daiflow/` |
| Electron 桌面端 | `{app.getPath('userData')}/data/` |

**各平台实际路径：**

| 平台 | 路径 |
|------|------|
| macOS | `~/Library/Application Support/DaiFlow/data/` |
| Windows | `%APPDATA%/DaiFlow/data/` |
| Linux | `~/.config/DaiFlow/data/` |

**目录结构（与 CLI 模式一致）：**
```
{userData}/
├── data/                    # DAIFLOW_HOME
│   ├── daiflow.db
│   ├── sessions/
│   ├── projects/
│   └── tasks/
└── python-env/              # venv（独立于 DAIFLOW_HOME）
    ├── bin/ (或 Scripts/)
    ├── lib/
    └── .deps-hash
```

### 4.10 前端构建产物集成

**方案：复用现有机制**

当前 Vite build 配置已将产物输出到 `daiflow/static/`，FastAPI 已实现 SPA fallback（`main.py:139-157`）。Electron 直接加载 `http://127.0.0.1:{port}` 即可，**前端零改动**。

**构建流程：**
```bash
cd frontend && npm run build    # 输出到 daiflow/static/
# Electron 打包时将 daiflow/static/ 包含在内
```

### 4.11 package.json 与打包配置

**根目录 `package.json`：**

```json
{
  "name": "daiflow-desktop",
  "version": "0.1.0",
  "description": "DaiFlow - AI-powered programming workbench",
  "main": "electron/main.js",
  "scripts": {
    "electron:dev": "electron .",
    "electron:build-frontend": "cd frontend && npm install && npm run build",
    "electron:pack": "npm run electron:build-frontend && electron-builder --dir",
    "electron:dist": "npm run electron:build-frontend && electron-builder",
    "electron:dist-mac": "npm run electron:build-frontend && electron-builder --mac",
    "electron:dist-win": "npm run electron:build-frontend && electron-builder --win",
    "electron:dist-linux": "npm run electron:build-frontend && electron-builder --linux"
  },
  "devDependencies": {
    "electron": "^35.0.0",
    "electron-builder": "^26.0.0"
  }
}
```

**`electron-builder.yml`：**

```yaml
appId: com.daiflow.desktop
productName: DaiFlow
copyright: Copyright © 2025-2026

directories:
  output: dist-electron

files:
  - electron/**/*
  - daiflow/**/*
  - requirements.txt
  - pyproject.toml
  - "!**/__pycache__"
  - "!**/node_modules"
  - "!tests"
  - "!docs"
  - "!demo"
  - "!frontend/node_modules"
  - "!frontend/src"       # 只需要 build 产物，源码不需要

mac:
  category: public.app-category.developer-tools
  icon: electron/icons/icon.icns
  target:
    - dmg
    - zip

win:
  icon: electron/icons/icon.ico
  target:
    - nsis

linux:
  icon: electron/icons/icon.png
  category: Development
  target:
    - AppImage
    - deb

nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
```

## 5. 后端代码改动清单

**改动极小，全部向后兼容（不影响 CLI 模式）：**

### 5.1 无需改动的部分

| 模块 | 原因 |
|------|------|
| 前端代码（整个 `frontend/`） | API 用相对路径 `/api`，WS 用 `window.location.host`，天然兼容 |
| CORS 配置 | 已支持 `DAIFLOW_CORS_ORIGINS` 环境变量，Electron 启动时注入即可 |
| WebSocket | URL 动态构建，重连机制完善 |
| 数据目录 | 已支持 `DAIFLOW_HOME` 环境变量 |
| 数据库 | SQLite 本地文件，路径跟随 `DAIFLOW_HOME` |
| Session/日志 | 路径跟随 `DAIFLOW_HOME` |

### 5.2 建议改动（可选优化）

| 改动 | 说明 | 影响范围 |
|------|------|---------|
| 运行中 Session 查询接口 | `GET /api/sessions/running` — 返回当前运行中的 session 数量，供关闭保护使用 | `routers/sessions.py` ~10 行 |
| 数据库迁移集成 | Electron 启动时自动运行 `alembic upgrade head`，确保应用更新后 schema 与代码一致 | 无代码改动，复用现有 Alembic |
| CLI 增加 `--port 0` 支持 | 让 uvicorn 自动选端口，简化端口管理 | `cli.py` 1 行（可选） |
| 健康检查接口 | 可在 `/api/health` 新增一个轻量端点（返回 `{"ok": true}`），避免依赖 settings 逻辑 | `main.py` 3 行（可选） |

## 6. 实施步骤

### Phase 1: 基础框架搭建（1 天）

1. 创建 `electron/` 目录结构
2. 实现 `main.js` 主进程（窗口管理、生命周期）
3. 实现 `python-manager.js`（Python 检测、venv 创建、依赖安装）
4. 实现 `port-manager.js`（端口检测）
5. 实现 `backend-manager.js`（子进程启动、等待、关停）
6. 实现 `splash.html`（启动加载页）
7. 根目录 `package.json` 配置

### Phase 2: 开发模式验证（0.5 天）

1. `npm run electron:dev` 能跑通完整流程
2. 验证首次启动（venv 创建 + pip install）
3. 验证二次启动（依赖跳过，快速启动）
4. 验证所有功能：项目管理、任务流、WebSocket 实时通信
5. 验证窗口关闭时后端正确关停

### Phase 3: 打包与分发（1-2 天）

1. 配置 `electron-builder.yml`
2. 前端 build 集成到打包流程
3. 各平台测试打包产物（macOS .dmg / Windows .exe / Linux .AppImage）
4. 应用图标设计与适配
5. 代码签名（macOS notarization / Windows code signing）— 如果需要公开分发

### Phase 4: 体验优化（1 天，可选）

1. 系统托盘支持（关闭窗口时最小化到托盘，后端保持运行）
2. 原生菜单栏（文件、编辑、视图、帮助）
3. 开发者工具入口（Help → Toggle DevTools）
4. 自动更新集成（`electron-updater`）
5. 错误上报 / 日志收集

## 7. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 用户无 Python 环境 | 无法启动 | 启动时检测并提示下载链接；远期可考虑内嵌 Python（如 python-build-standalone） |
| pip install 网络失败 | 首次启动失败 | 重试机制 + 离线包方案（将 wheels 预打包到安装包中） |
| pip install 耗时过长 | 用户体验差 | Splash 页展示进度；使用 `--prefer-binary` 加速 |
| Electron 包体过大 | 安装包 ~150MB+ | 可接受范围；远期可评估迁移到 Tauri |
| cody-ai 依赖特殊 | 可能有平台兼容问题 | 各平台提前验证 `pip install cody-ai` |
| Windows 进程管理差异 | SIGTERM 不生效 | 已在设计中用 `taskkill` 处理 |
| 数据库锁冲突 | 同时运行 CLI + 桌面端 | 数据目录隔离（不同 DAIFLOW_HOME） |

## 8. 总结

| 维度 | 评估 |
|------|------|
| **后端改动** | 零改动（环境变量注入解决所有配置差异） |
| **前端改动** | 零改动（相对路径 + 动态 host，天然兼容） |
| **新增代码** | ~300-400 行 JavaScript（Electron 壳） |
| **工作量** | 基础可用：2 天；打包分发：+2 天；体验优化：+1 天 |
| **维护成本** | 低（Electron 壳与业务逻辑完全解耦） |
