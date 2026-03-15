# DaiFlow 桌面端方案

> 版本：v0.2
> 更新时间：2026-03-15
>
> **注意：** 实际实现代码在 `electron/` 目录中，与本文档有以下差异：
> - 打包改用 `extraResources`（而非 `asarUnpack`），后端文件复制到 `resources/backend/`
> - `APP_ROOT` 打包后指向 `path.join(process.resourcesPath, 'backend')`
> - `stop()` 增加了 10 秒兜底超时 + 进程已退出检测
> - `handleBackendCrash` 支持无父窗口的对话框
> - macOS `activate` 时重置 `isQuitting` 标志
> - `waitForBackend` 超时从 15 秒增加到 30 秒

---

## 一、背景与目标

### 1.1 背景

DaiFlow 当前以 CLI 工具形式发布（`pip install daiflow` → `daiflow start`），用户需自行准备 Python 3.11+ 环境。这对开发者用户尚可接受，但存在以下痛点：

- **环境门槛高：** 非 Python 用户需安装 Python、配置 pip，Windows 用户常遇到环境变量和权限问题
- **启动流程长：** 打开终端 → 激活环境 → 运行命令 → 等待浏览器打开，步骤繁琐
- **进程管理弱：** 用户需手动管理后端进程，关闭终端即丢失服务
- **缺少系统集成：** 无法像原生应用一样出现在应用启动器、Dock 栏、系统托盘中

### 1.2 目标

提供跨平台（macOS / Windows / Linux）桌面应用，实现：

1. **零环境依赖：** 应用内自动管理 Python 虚拟环境，用户无需手动安装
2. **一键启动：** 双击图标即可使用，等同原生应用体验
3. **进程托管：** 后端生命周期由 Electron 管理，含崩溃恢复、优雅关闭
4. **最小改动：** 复用现有 FastAPI 后端和 React 前端，后端仅新增 ~10 行代码

---

## 二、技术选型

### 2.1 选择 Electron

| 维度 | Electron | Tauri | 说明 |
|------|----------|-------|------|
| 渲染引擎 | Chromium（自带） | 系统 WebView | DaiFlow 重度使用 WebSocket + Monaco，需一致性 |
| Node.js 能力 | 内置 | 无 | 需要 Node.js 管理 Python 子进程、文件系统操作 |
| 跨平台一致性 | ★★★★★ | ★★★☆ | Tauri 受系统 WebView 版本影响 |
| 包体积 | ~150MB | ~10MB | 可接受，DaiFlow 本身含 Python 环境 |
| 生态成熟度 | 极高 | 较高 | electron-builder 打包链成熟稳定 |

**结论：** DaiFlow 的核心是管理 Python 子进程 + 提供一致的 Web 渲染环境，Electron 在这两方面优势明显。包体积劣势在 DaiFlow 场景下可忽略（Python venv 本身 ~200MB）。

### 2.2 关键依赖

| 包 | 版本 | 用途 |
|----|------|------|
| electron | ^33.0 | 主框架 |
| electron-builder | ^25.0 | 打包分发 |

---

## 三、整体架构

```
┌──────────────────────────────────────────────────────────┐
│                    Electron 主进程                         │
│                                                          │
│  ┌──────────┐  ┌────────────┐  ┌───────────────────────┐ │
│  │ 端口管理  │  │ venv 管理  │  │  后端子进程管理        │ │
│  │ (probe)  │  │ (pip/venv) │  │  (spawn uvicorn)      │ │
│  └──────────┘  └────────────┘  └───────────┬───────────┘ │
│                                            │ stdio       │
│  ┌──────────────────────┐                  │             │
│  │   Splash Window      │    ┌─────────────▼───────────┐ │
│  │   (加载状态显示)      │    │   Python 子进程          │ │
│  └──────────────────────┘    │   uvicorn → FastAPI     │ │
│                              │   localhost:{port}      │ │
│  ┌──────────────────────┐    └─────────────┬───────────┘ │
│  │   Main BrowserWindow │                  │             │
│  │   (React SPA)        │◄── HTTP/WS ─────┘             │
│  │   关闭保护 / 崩溃恢复 │                               │
│  └──────────────────────┘                                │
│                                                          │
│  数据目录: {userData}/data/  (隔离于 CLI 的 ~/.daiflow)    │
└──────────────────────────────────────────────────────────┘
```

**核心流程：** 启动 Electron → 显示 Splash → 检测/创建 Python venv → 安装依赖 → 运行 Alembic 迁移 → 启动 uvicorn → 轮询 `/api/settings/check` → 关闭 Splash → 打开主窗口加载 `http://localhost:{port}`。

---

## 四、目录结构

```
electron/
├── package.json              # Electron 项目配置 + electron-builder 脚本
├── electron-builder.yml      # 打包配置
├── main/
│   ├── index.js              # 主进程入口
│   ├── python-env.js         # Python 环境检测与 venv 管理
│   ├── port-manager.js       # 动态端口探测
│   ├── backend.js            # 后端子进程管理
│   └── splash-preload.js     # Splash 窗口 preload 脚本
├── splash/
│   └── index.html            # Splash 加载页
└── icons/                    # 应用图标 (icns/ico/png)
```

前端构建产物仍然输出到 `daiflow/static/`，由 FastAPI 静态托管。Electron 的 BrowserWindow 直接加载 `http://localhost:{port}`，无需额外处理静态文件。

---

## 五、详细设计

### 5.1 Python 环境检测与 venv 管理

Python venv 存储在 Electron 的 `userData` 目录下，与系统 Python 隔离：

- macOS: `~/Library/Application Support/DaiFlow/python-env/`
- Windows: `%APPDATA%/DaiFlow/python-env/`
- Linux: `~/.config/DaiFlow/python-env/`

#### 5.1.1 检测系统 Python

```js
// electron/main/python-env.js
const { execFile } = require('child_process');
const { promisify } = require('util');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');

const execFileAsync = promisify(execFile);

/**
 * 候选 Python 命令列表（按平台）。
 * Unix 优先 python3（避免误用系统 python2），Windows 优先 python 和 py launcher。
 */
function getPythonCandidates() {
  if (process.platform === 'win32') {
    return ['python', 'py'];
  }
  return ['python3', 'python'];
}

/**
 * 解析 "Python 3.x.y" 版本字符串，返回 [major, minor, patch]，
 * 解析失败返回 null。
 */
function parseVersion(versionStr) {
  const match = versionStr.match(/Python (\d+)\.(\d+)\.(\d+)/);
  if (!match) return null;
  return [parseInt(match[1], 10), parseInt(match[2], 10), parseInt(match[3], 10)];
}

/**
 * 检测可用的 Python >= 3.11，返回命令路径。
 * 注意：某些平台 python --version 输出到 stderr，因此需检查两者。
 */
async function findPython() {
  const candidates = getPythonCandidates();
  for (const cmd of candidates) {
    try {
      const args = process.platform === 'win32' && cmd === 'py'
        ? ['-3', '--version']
        : ['--version'];
      const result = await execFileAsync(cmd, args, { timeout: 10000 });
      const output = result.stdout || result.stderr;
      const version = parseVersion(output);
      if (version && (version[0] > 3 || (version[0] === 3 && version[1] >= 11))) {
        // py launcher 需要带 -3 参数执行
        return process.platform === 'win32' && cmd === 'py'
          ? { cmd: 'py', args: ['-3'] }
          : { cmd, args: [] };
      }
    } catch {
      // 命令不存在或执行失败，尝试下一个
    }
  }
  throw new Error(
    'Python >= 3.11 not found. Please install Python 3.11+ from https://www.python.org/downloads/'
  );
}
```

#### 5.1.2 venv 创建与依赖安装

```js
/**
 * 获取 venv 内 Python 可执行文件路径。
 */
function getPythonPath(venvDir) {
  return process.platform === 'win32'
    ? path.join(venvDir, 'Scripts', 'python.exe')
    : path.join(venvDir, 'bin', 'python');
}

/**
 * 获取 venv 内 pip 可执行文件路径。
 */
function getPipPath(venvDir) {
  return process.platform === 'win32'
    ? path.join(venvDir, 'Scripts', 'pip.exe')
    : path.join(venvDir, 'bin', 'pip');
}

/**
 * 计算依赖文件的 hash，用于判断是否需要重新安装。
 * 依据 requirements.txt 和 pyproject.toml 的内容计算 SHA256。
 */
function computeDepsHash(appRoot) {
  const hash = crypto.createHash('sha256');
  const files = ['requirements.txt', 'pyproject.toml'];
  for (const file of files) {
    const filePath = path.join(appRoot, file);
    if (fs.existsSync(filePath)) {
      hash.update(fs.readFileSync(filePath));
    }
  }
  return hash.digest('hex');
}

/**
 * 确保 Python venv 就绪，返回 venv 目录路径。
 *
 * @param {string} appRoot - 项目根目录（含 requirements.txt 等）
 * @param {string} venvDir - venv 存放目录
 * @param {(msg: string) => void} onStatus - 状态回调（更新 Splash 显示）
 */
async function ensurePythonEnv(appRoot, venvDir, onStatus) {
  const { app } = require('electron');

  // 1. 检测系统 Python
  onStatus('正在检测 Python 环境...');
  const python = await findPython();

  // 2. 创建 venv（如不存在）
  const pythonPath = getPythonPath(venvDir);
  if (!fs.existsSync(pythonPath)) {
    onStatus('正在创建 Python 虚拟环境...');
    const createArgs = [...python.args, '-m', 'venv', venvDir];
    await execFileAsync(python.cmd, createArgs, { timeout: 120000 });
  }

  // 3. 检查依赖是否需要更新
  const depsHash = computeDepsHash(appRoot);
  const hashFile = path.join(venvDir, '.deps-hash');
  const existingHash = fs.existsSync(hashFile)
    ? fs.readFileSync(hashFile, 'utf-8').trim()
    : '';

  if (depsHash !== existingHash) {
    onStatus('正在安装依赖（首次启动可能较慢）...');

    // 安装 requirements.txt
    const requirementsPath = path.join(appRoot, 'requirements.txt');
    if (fs.existsSync(requirementsPath)) {
      await execFileAsync(getPipPath(venvDir), [
        'install', '-r', requirementsPath, '--prefer-binary'
      ], { timeout: 600000 });
    }

    // 安装 daiflow 包本身
    // 打包后使用常规安装，开发模式使用 -e 安装
    if (app.isPackaged) {
      await execFileAsync(getPipPath(venvDir), [
        'install', appRoot, '--prefer-binary'
      ], { timeout: 300000 });
    } else {
      await execFileAsync(getPipPath(venvDir), [
        'install', '-e', appRoot, '--prefer-binary'
      ], { timeout: 300000 });
    }

    // 写入 hash 标记
    fs.writeFileSync(hashFile, depsHash, 'utf-8');
  }

  return venvDir;
}

module.exports = { findPython, ensurePythonEnv, getPythonPath, getPipPath };
```

**设计要点：**

- 使用 `execFileAsync`（`promisify(execFile)`）而非 `exec`，避免 shell 注入风险
- `--prefer-binary` 优先使用预编译 wheel，避免在用户机器上编译 C 扩展
- 依赖 hash 基于 `requirements.txt` + `pyproject.toml` 内容，文件变更时自动重装
- `app.isPackaged` 区分打包模式（常规 install）和开发模式（`-e` editable install）

---

### 5.2 端口管理

动态分配端口，范围 18900–18999，避免与常见服务冲突：

```js
// electron/main/port-manager.js
const net = require('net');

/**
 * 探测端口是否可用。
 * 通过尝试 bind + listen 确认端口未被占用。
 */
function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => {
      server.close(() => resolve(true));
    });
    server.listen(port, '127.0.0.1');
  });
}

/**
 * 在指定范围内找到第一个可用端口。
 * 默认范围 18900-18999。
 */
async function findAvailablePort(start = 18900, end = 18999) {
  for (let port = start; port <= end; port++) {
    if (await isPortAvailable(port)) {
      return port;
    }
  }
  throw new Error(`No available port found in range ${start}-${end}`);
}

module.exports = { findAvailablePort };
```

---

### 5.3 后端子进程管理

```js
// electron/main/backend.js
const { spawn } = require('child_process');
const path = require('path');
const { getPythonPath } = require('./python-env');

/**
 * 启动 uvicorn 后端子进程。
 *
 * @param {object} options
 * @param {string} options.venvDir - venv 目录路径
 * @param {number} options.port - 监听端口
 * @param {string} options.dataDir - DAIFLOW_HOME 数据目录
 * @param {string} options.corsOrigins - CORS 允许的源
 * @param {() => void} options.onCrash - 进程意外退出回调
 * @returns {{ process: ChildProcess, stop: () => Promise<void> }}
 */
function startBackend({ venvDir, port, dataDir, corsOrigins, onCrash }) {
  const pythonPath = getPythonPath(venvDir);

  const child = spawn(pythonPath, [
    '-m', 'uvicorn',
    'daiflow.main:app',
    '--host', '127.0.0.1',
    '--port', String(port),
    '--no-access-log',
  ], {
    env: {
      ...process.env,
      DAIFLOW_HOME: dataDir,
      DAIFLOW_CORS_ORIGINS: corsOrigins,
      // 确保 venv 的 Python 优先
      PATH: path.dirname(pythonPath) + path.delimiter + (process.env.PATH || ''),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let stopped = false;

  child.stdout.on('data', (data) => {
    console.log(`[backend stdout] ${data.toString().trimEnd()}`);
  });

  child.stderr.on('data', (data) => {
    console.error(`[backend stderr] ${data.toString().trimEnd()}`);
  });

  child.on('exit', (code, signal) => {
    console.log(`[backend] exited with code=${code} signal=${signal}`);
    if (!stopped && onCrash) {
      onCrash(code, signal);
    }
  });

  /**
   * 优雅关闭后端：
   * - Unix: SIGTERM → 等待 5s → SIGKILL
   * - Windows: taskkill /T /F（终止进程树）
   */
  async function stop() {
    if (stopped || !child.pid) return;
    stopped = true;

    return new Promise((resolve) => {
      child.on('exit', () => resolve());

      if (process.platform === 'win32') {
        // Windows: 使用 taskkill 终止整个进程树
        const { execFile: execFileSync } = require('child_process');
        execFileSync('taskkill', ['/T', '/F', '/PID', String(child.pid)], (err) => {
          if (err) {
            console.error('[backend] taskkill failed:', err.message);
          }
          resolve();
        });
      } else {
        // Unix: SIGTERM + 5 秒超时兜底 SIGKILL
        child.kill('SIGTERM');
        const killTimer = setTimeout(() => {
          try {
            child.kill('SIGKILL');
          } catch {
            // 进程可能已退出
          }
        }, 5000);
        child.on('exit', () => {
          clearTimeout(killTimer);
          resolve();
        });
      }
    });
  }

  return { process: child, stop };
}

/**
 * 轮询后端健康检查接口，等待后端就绪。
 * 使用 Electron 内置的 net.fetch（不受 CORS 限制）。
 */
async function waitForBackend(port, maxRetries = 30, intervalMs = 500) {
  const { net } = require('electron');
  const url = `http://127.0.0.1:${port}/api/settings/check`;

  for (let i = 0; i < maxRetries; i++) {
    try {
      const response = await net.fetch(url);
      if (response.ok) {
        return true;
      }
    } catch {
      // 连接拒绝，继续重试
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(`Backend failed to start within ${maxRetries * intervalMs / 1000}s`);
}

module.exports = { startBackend, waitForBackend };
```

**设计要点：**

- `spawn` 而非 `exec`：不经过 shell，安全且支持流式 stdout/stderr
- `stopped` 标志防止正常关闭时触发 `onCrash` 回调
- Windows 进程树终止必须使用 `taskkill /T /F`，因为 `child.kill()` 仅终止父进程
- `waitForBackend` 使用 `net.fetch`（Electron 内置），避免需要额外依赖

---

### 5.4 Electron 主进程

```js
// electron/main/index.js
const { app, BrowserWindow, dialog } = require('electron');
const path = require('path');

const { ensurePythonEnv } = require('./python-env');
const { findAvailablePort } = require('./port-manager');
const { startBackend, waitForBackend } = require('./backend');

// ─── APP_ROOT: 项目根目录（含 daiflow/, requirements.txt 等） ───
// 打包后资源在 asar.unpacked 中（因为需要 Python 读取文件系统）
const APP_ROOT = app.isPackaged
  ? path.join(process.resourcesPath, 'app.asar.unpacked')
  : path.join(__dirname, '..');

// ─── 数据目录：桌面端独立于 CLI ───
const DATA_DIR = path.join(app.getPath('userData'), 'data');

// ─── 状态变量 ───
let mainWindow = null;
let splashWindow = null;
let backend = null;      // { process, stop }
let backendPort = null;
let backendStopped = false;
let isQuitting = false;

// ─── 单实例锁 ───
const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
  // 已有实例运行，退出当前进程
  app.quit();
} else {
  app.on('second-instance', () => {
    // 第二个实例启动时，聚焦已有窗口
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(onAppReady);
}

// ─── Alembic 数据库迁移 ───
async function runMigrations(venvDir) {
  const { execFile } = require('child_process');
  const { promisify } = require('util');
  const execFileAsync = promisify(execFile);
  const { getPythonPath } = require('./python-env');

  const pythonPath = getPythonPath(venvDir);
  const alembicDir = path.join(APP_ROOT, 'alembic');
  const fs = require('fs');

  // 仅当 alembic 目录存在时执行迁移
  if (!fs.existsSync(alembicDir)) {
    console.log('[migration] alembic directory not found, skipping');
    return;
  }

  console.log('[migration] Running alembic upgrade head...');
  await execFileAsync(pythonPath, [
    '-m', 'alembic', 'upgrade', 'head'
  ], {
    cwd: APP_ROOT,
    env: {
      ...process.env,
      DAIFLOW_HOME: DATA_DIR,
    },
    timeout: 60000,
  });
  console.log('[migration] Done');
}

// ─── 应用启动 ───
async function onAppReady() {
  // 1. 创建 Splash 窗口
  splashWindow = new BrowserWindow({
    width: 400,
    height: 300,
    frame: false,
    resizable: false,
    transparent: false,
    alwaysOnTop: true,
    webPreferences: {
      preload: path.join(__dirname, 'splash-preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  splashWindow.loadFile(path.join(__dirname, '..', 'splash', 'index.html'));

  /**
   * 向 Splash 窗口发送状态消息。
   */
  function sendStatus(message) {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.webContents.send('status', message);
    }
    console.log(`[startup] ${message}`);
  }

  try {
    // 2. Python 环境准备
    const venvDir = path.join(app.getPath('userData'), 'python-env');
    await ensurePythonEnv(APP_ROOT, venvDir, sendStatus);

    // 3. 数据库迁移
    sendStatus('正在更新数据库...');
    await runMigrations(venvDir);

    // 4. 端口分配
    sendStatus('正在分配端口...');
    backendPort = await findAvailablePort();

    // 5. 启动后端
    sendStatus('正在启动后端服务...');
    const corsOrigins = `http://127.0.0.1:${backendPort},http://localhost:${backendPort}`;

    backend = startBackend({
      venvDir,
      port: backendPort,
      dataDir: DATA_DIR,
      corsOrigins,
      onCrash: handleBackendCrash,
    });

    // 6. 等待后端就绪
    sendStatus('等待后端就绪...');
    await waitForBackend(backendPort);

    // 7. 创建主窗口
    sendStatus('正在加载界面...');
    createMainWindow();

    // 8. 关闭 Splash
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.close();
      splashWindow = null;
    }
  } catch (err) {
    console.error('[startup] Fatal error:', err);
    dialog.showErrorBox('DaiFlow 启动失败', err.message);
    app.quit();
  }
}

// ─── 主窗口 ───
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    title: 'DaiFlow',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadURL(`http://127.0.0.1:${backendPort}`);

  // ─── 关闭保护：检查是否有运行中的 AI 会话 ───
  mainWindow.on('close', async (e) => {
    if (isQuitting) return; // 已确认退出，不再拦截

    e.preventDefault();

    try {
      const { net } = require('electron');
      const response = await net.fetch(
        `http://127.0.0.1:${backendPort}/api/sessions/running`
      );
      const data = await response.json();

      if (data.count > 0) {
        const { response: buttonIndex } = await dialog.showMessageBox(mainWindow, {
          type: 'warning',
          title: '确认关闭',
          message: `当前有 ${data.count} 个 AI 会话正在运行，关闭将中断这些任务。确定要关闭吗？`,
          buttons: ['取消', '强制关闭'],
          defaultId: 0,
          cancelId: 0,
        });

        if (buttonIndex === 0) return; // 用户取消
      }
    } catch {
      // 后端无响应，直接允许关闭
    }

    isQuitting = true;
    mainWindow.close();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ─── 后端崩溃恢复 ───
function handleBackendCrash(code, signal) {
  if (isQuitting || backendStopped) return;

  console.error(`[backend] Crashed with code=${code} signal=${signal}`);

  const focusWindow = mainWindow || splashWindow;

  dialog.showMessageBox(focusWindow, {
    type: 'error',
    title: '后端服务异常',
    message: `DaiFlow 后端意外退出（代码: ${code}）。是否重新启动？`,
    buttons: ['重新启动', '退出'],
    defaultId: 0,
  }).then(({ response: buttonIndex }) => {
    if (buttonIndex === 0) {
      // 重新启动
      app.relaunch();
      app.exit(0);
    } else {
      app.exit(1);
    }
  });
}

// ─── macOS 生命周期 ───
app.on('window-all-closed', () => {
  // macOS：关闭所有窗口后不退出，保留 Dock 图标
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  // macOS：点击 Dock 图标时重新创建窗口
  if (mainWindow === null && backendPort) {
    createMainWindow();
  }
});

// ─── 应用退出前：停止后端 ───
app.on('before-quit', async (e) => {
  if (backendStopped) return; // 已经停止，放行退出

  e.preventDefault();
  backendStopped = true;

  console.log('[shutdown] Stopping backend...');
  if (backend) {
    try {
      await backend.stop();
    } catch (err) {
      console.error('[shutdown] Error stopping backend:', err);
    }
  }
  console.log('[shutdown] Backend stopped');

  app.quit(); // 再次触发退出（backendStopped=true 会放行）
});
```

**关键设计说明：**

| 机制 | 说明 |
|------|------|
| 单实例锁 | `requestSingleInstanceLock()` 确保同一时间只有一个 DaiFlow 实例 |
| `APP_ROOT` | 打包后指向 `app.asar.unpacked`，开发时指向项目根目录 |
| `backendStopped` 标志 | 防止 `before-quit` → `app.quit()` 无限循环 |
| `isQuitting` 标志 | 防止关闭保护的 `close` 事件处理器被重复触发 |
| Alembic 迁移时机 | 在后端启动前执行，确保数据库 schema 已更新 |
| macOS 特殊处理 | `window-all-closed` 不退出 + `activate` 重建窗口 |

---

### 5.5 Splash 加载页

#### 5.5.1 Preload 脚本

```js
// electron/main/splash-preload.js
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  onStatus: (callback) => {
    ipcRenderer.on('status', (_event, message) => callback(message));
  },
});
```

#### 5.5.2 Splash 页面

```html
<!-- electron/splash/index.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100vh;
      background: #0f1117;
      color: #e0e0e0;
      -webkit-app-region: drag;
      user-select: none;
    }
    .logo {
      font-size: 32px;
      font-weight: 700;
      letter-spacing: 2px;
      margin-bottom: 40px;
      color: #7c5cfc;
    }
    .spinner {
      width: 36px;
      height: 36px;
      border: 3px solid rgba(124, 92, 252, 0.2);
      border-top-color: #7c5cfc;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin-bottom: 20px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    #status {
      font-size: 14px;
      color: #888;
      text-align: center;
      padding: 0 20px;
    }
  </style>
</head>
<body>
  <div class="logo">DaiFlow</div>
  <div class="spinner"></div>
  <div id="status">正在初始化...</div>
  <script>
    window.electronAPI.onStatus((message) => {
      document.getElementById('status').textContent = message;
    });
  </script>
</body>
</html>
```

#### 5.5.3 状态消息流

启动过程中，Splash 依次显示以下状态：

| 阶段 | 消息 |
|------|------|
| Python 检测 | 正在检测 Python 环境... |
| venv 创建 | 正在创建 Python 虚拟环境... |
| 依赖安装 | 正在安装依赖（首次启动可能较慢）... |
| 数据库迁移 | 正在更新数据库... |
| 端口分配 | 正在分配端口... |
| 后端启动 | 正在启动后端服务... |
| 后端就绪 | 等待后端就绪... |
| 界面加载 | 正在加载界面... |

---

### 5.6 关闭保护

用户关闭窗口时，需检查是否有正在运行的 AI 会话。需要在后端新增一个轻量级查询接口。

#### 5.6.1 新增后端接口

在 `daiflow/routers/sessions.py` 中新增：

```python
@router.get("/running")
async def get_running_sessions(db: AsyncSession = Depends(get_db)):
    """Return count of currently running sessions (for desktop close protection)."""
    result = await db.execute(
        select(Session).where(Session.status == SessionStatus.RUNNING)
    )
    sessions = result.scalars().all()
    return {"count": len(sessions)}
```

**注意：** sessions router 已定义 `prefix="/api/sessions"`，因此装饰器使用 `@router.get("/running")`，实际路由为 `GET /api/sessions/running`。

#### 5.6.2 关闭流程

```
用户点击关闭按钮
    │
    ▼
close 事件触发
    │
    ├─ isQuitting=true? → 放行关闭
    │
    ▼
e.preventDefault() 阻止关闭
    │
    ▼
GET /api/sessions/running
    │
    ├─ count=0 → 设置 isQuitting=true → mainWindow.close()
    │
    ├─ count>0 → 弹出确认对话框
    │              │
    │              ├─ 用户取消 → 返回，不关闭
    │              │
    │              └─ 用户确认 → 设置 isQuitting=true → mainWindow.close()
    │
    └─ 请求失败（后端已挂） → 设置 isQuitting=true → mainWindow.close()
```

---

### 5.7 CORS 适配

Electron 主窗口加载 `http://127.0.0.1:{port}`，前端所有 API 请求使用相对路径 `/api/...`，实际指向同源后端。**同源场景下 CORS 头不生效**，但为安全起见仍注入允许的 origins：

```js
// 在 startBackend 中设置
const corsOrigins = `http://127.0.0.1:${backendPort},http://localhost:${backendPort}`;
```

通过环境变量 `DAIFLOW_CORS_ORIGINS` 传递给后端，后端 `main.py` 已有读取逻辑，**无需任何后端代码改动**。

---

### 5.8 WebSocket 兼容性

前端 WebSocket 连接 URL 构建逻辑（来自 `frontend/src/ws/WebSocketClient.ts`）：

```ts
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
return `${protocol}//${window.location.host}/api/ws`;
```

在 Electron 中，`BrowserWindow.loadURL('http://127.0.0.1:{port}')` 后：

- `window.location.protocol` → `'http:'`
- `window.location.host` → `'127.0.0.1:{port}'`
- 最终 WebSocket URL → `ws://127.0.0.1:{port}/api/ws`

**完全兼容，无需任何改动。**

前端已实现指数退避重连（最多 5 次重试 + 60 秒兜底重连），可应对后端短暂不可用的情况。

---

### 5.9 数据目录隔离

桌面端和 CLI 使用不同的数据目录，避免互相干扰：

| 模式 | DAIFLOW_HOME | 路径示例 |
|------|-------------|---------|
| CLI | `~/.daiflow/` | `/Users/alice/.daiflow/` |
| 桌面端 macOS | `{userData}/data/` | `~/Library/Application Support/DaiFlow/data/` |
| 桌面端 Windows | `{userData}/data/` | `%APPDATA%/DaiFlow/data/` |
| 桌面端 Linux | `{userData}/data/` | `~/.config/DaiFlow/data/` |

通过环境变量 `DAIFLOW_HOME` 传递给后端子进程，后端 `config.py` 已支持该变量：

```python
DAIFLOW_HOME = Path(os.environ.get("DAIFLOW_HOME", Path.home() / ".daiflow"))
```

**无需任何后端代码改动。**

---

### 5.10 前端构建集成

现有流程：

1. `cd frontend && npm run build` → 产物输出到 `daiflow/static/`
2. FastAPI 的 `main.py` 自动检测并托管 `daiflow/static/` 目录

桌面端复用此机制：

- Electron BrowserWindow 加载 `http://127.0.0.1:{port}`
- FastAPI 返回 `daiflow/static/index.html` + 静态资源
- 前端所有 API 调用使用相对路径 `/api/...`，自动指向后端

**无需额外处理前端构建产物，无需任何改动。**

---

### 5.11 打包配置

#### 5.11.1 package.json

```json
{
  "name": "daiflow-desktop",
  "version": "0.1.0",
  "description": "DaiFlow Desktop - AI-powered programming workbench",
  "main": "main/index.js",
  "scripts": {
    "dev": "electron .",
    "build:frontend": "cd ../frontend && npm run build",
    "pack": "electron-builder --dir",
    "dist": "electron-builder",
    "dist:mac": "electron-builder --mac",
    "dist:win": "electron-builder --win",
    "dist:linux": "electron-builder --linux"
  },
  "devDependencies": {
    "electron": "^33.0.0",
    "electron-builder": "^25.0.0"
  }
}
```

#### 5.11.2 electron-builder.yml

```yaml
appId: com.daiflow.desktop
productName: DaiFlow
copyright: Copyright © 2026 DaiFlow

directories:
  output: dist

# 将 Python 后端代码、迁移脚本、依赖声明解压到 asar 外，
# 供 Python 子进程直接读取文件系统
asar: true
asarUnpack:
  - "daiflow/**/*"
  - "alembic/**/*"
  - "alembic.ini"
  - "requirements.txt"
  - "pyproject.toml"

# 额外文件（不在 asar 中的根级文件）
extraResources: []

files:
  - "main/**/*"
  - "splash/**/*"
  - "icons/**/*"
  - "daiflow/**/*"
  - "alembic/**/*"
  - "alembic.ini"
  - "requirements.txt"
  - "pyproject.toml"
  - "package.json"

mac:
  category: public.app-category.developer-tools
  icon: icons/icon.icns
  target:
    - target: dmg
      arch:
        - x64
        - arm64
    - target: zip
      arch:
        - x64
        - arm64

win:
  icon: icons/icon.ico
  target:
    - target: nsis
      arch:
        - x64

nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
  installerIcon: icons/icon.ico

linux:
  icon: icons
  category: Development
  target:
    - target: AppImage
      arch:
        - x64
    - target: deb
      arch:
        - x64
```

**关键配置说明：**

| 配置 | 说明 |
|------|------|
| `asarUnpack` | Python 子进程无法读取 asar 归档内的文件，必须解压 |
| `daiflow/**/*` | 包含后端代码 + `daiflow/static/` 前端构建产物 |
| `alembic/**/*` | 数据库迁移脚本 |
| `requirements.txt` + `pyproject.toml` | 用于依赖 hash 计算和 pip install |
| macOS dual arch | 同时构建 x64（Intel）和 arm64（Apple Silicon） |

---

## 六、后端代码改动清单

桌面端方案遵循**最小改动原则**，几乎所有适配通过环境变量和 Electron 主进程完成。

| 改动 | 文件 | 行数 | 说明 |
|------|------|------|------|
| 新增 `/running` 接口 | `daiflow/routers/sessions.py` | ~8 行 | 返回运行中会话数，用于关闭保护 |

完整改动：

```python
# 在 daiflow/routers/sessions.py 中新增（router 已有 prefix="/api/sessions"）

@router.get("/running")
async def get_running_sessions(db: AsyncSession = Depends(get_db)):
    """Return count of currently running sessions (for desktop close protection)."""
    result = await db.execute(
        select(Session).where(Session.status == SessionStatus.RUNNING)
    )
    sessions = result.scalars().all()
    return {"count": len(sessions)}
```

需要在文件顶部现有 import 中确认 `SessionStatus` 已导入。当前 `sessions.py` 导入了 `from daiflow.models import Session`，需补充为：

```python
from daiflow.models import Session, SessionStatus
```

**其余所有适配均在 Electron 主进程完成，后端零改动：**

- CORS 配置 → `DAIFLOW_CORS_ORIGINS` 环境变量（已支持）
- 数据目录 → `DAIFLOW_HOME` 环境变量（已支持）
- 前端资源 → `daiflow/static/` 静态托管（已支持）
- WebSocket → `window.location.host`（已兼容）

---

## 七、实施步骤

### 第一阶段：基础框架（1 周）

| 步骤 | 任务 | 产出 |
|------|------|------|
| 1 | 创建 `electron/` 目录结构，初始化 `package.json` | 项目骨架 |
| 2 | 实现 `port-manager.js`（端口探测） | 可测试的端口分配模块 |
| 3 | 实现 `python-env.js`（Python 检测 + venv 管理） | 跨平台 Python 环境管理 |
| 4 | 实现 `backend.js`（子进程启动/停止） | 后端生命周期管理 |
| 5 | 实现 `index.js` 主进程（串联以上模块） | 可运行的 Electron 应用 |

### 第二阶段：体验完善（1 周）

| 步骤 | 任务 | 产出 |
|------|------|------|
| 6 | 实现 Splash 窗口 + preload IPC | 启动过程可视化 |
| 7 | 新增后端 `/running` 接口 | 关闭保护数据源 |
| 8 | 实现关闭保护逻辑 | 防止误关闭中断任务 |
| 9 | 实现崩溃恢复对话框 | 后端异常时用户可选择重启 |
| 10 | macOS 生命周期适配（Dock 行为） | macOS 原生体验 |

### 第三阶段：打包分发（1 周）

| 步骤 | 任务 | 产出 |
|------|------|------|
| 11 | 配置 `electron-builder.yml` | 打包配置 |
| 12 | 前端构建脚本集成 | `npm run build:frontend` |
| 13 | macOS 签名 + 公证 | macOS 分发 |
| 14 | Windows NSIS 安装包测试 | Windows 分发 |
| 15 | Linux AppImage / deb 测试 | Linux 分发 |

### 第四阶段：测试验证（1 周）

| 步骤 | 任务 | 产出 |
|------|------|------|
| 16 | 三平台冒烟测试（启动 → 使用 → 关闭） | 基础功能验证 |
| 17 | 首次安装测试（无 venv、无依赖） | 冷启动流程验证 |
| 18 | 升级测试（依赖变更触发重装） | 热更新流程验证 |
| 19 | 异常测试（杀进程、断网、磁盘满） | 容错能力验证 |
| 20 | 性能测试（启动时间、内存占用） | 性能基线 |

---

## 八、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 用户未安装 Python 3.11+ | 无法启动 | Splash 显示明确错误信息 + 下载链接；未来可考虑内嵌 Python（python-build-standalone） |
| pip install 超时 / 网络异常 | 首次启动失败 | 使用 `--prefer-binary` 减少编译；缓存 venv，失败后重启可断点续装 |
| Python venv 损坏 | 启动失败 | 检测到关键文件缺失时自动删除 venv 目录并重建 |
| 端口 18900-18999 全部被占 | 无法启动 | 概率极低（100 个端口）；错误时提示用户释放端口 |
| Windows 杀毒软件拦截子进程 | 后端无法启动 | 文档说明白名单设置；签名 Electron 应用减少误报 |
| macOS Gatekeeper 阻止运行 | 未签名应用无法打开 | 正式发布需 Apple Developer 签名 + 公证 |
| asar.unpacked 体积过大 | 安装包膨胀 | 仅解包必要文件（Python 源码、迁移脚本、依赖声明）；前端构建产物压缩后 ~2MB |
| 后端崩溃导致数据丢失 | 用户工作中断 | SessionRunner 已有 `.jsonl` 日志持久化；重启后 `_recover_interrupted_sessions` 自动恢复 |
| CLI 与桌面端数据冲突 | 状态不一致 | 使用独立的 `DAIFLOW_HOME` 目录，完全隔离 |

---

## 九、总结

本方案以 **最小后端改动**（~10 行新增代码）实现 DaiFlow 的 Electron 桌面端封装，核心思路是：

1. **Electron 作为进程管理器：** 负责 Python 环境检测、venv 管理、后端子进程生命周期
2. **复用现有架构：** FastAPI 静态托管前端、`DAIFLOW_HOME` 环境变量、`DAIFLOW_CORS_ORIGINS` CORS 配置，均已具备，无需改动
3. **BrowserWindow 即浏览器：** 前端相对路径 API + `window.location.host` WebSocket 在 Electron 中天然兼容
4. **增量可选：** 桌面端是独立的 `electron/` 目录，不影响现有 CLI 发布流程

预计总工期 4 周，产出覆盖 macOS（Intel + Apple Silicon）、Windows（x64）、Linux（x64）三平台安装包。
