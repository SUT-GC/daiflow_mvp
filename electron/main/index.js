const { app, BrowserWindow, dialog } = require('electron');
const path = require('path');
const fs = require('fs');

const { ensurePythonEnv, runMigrations } = require('./python-env');
const { findAvailablePort } = require('./port-manager');
const { startBackend, waitForBackend } = require('./backend');

// ─── APP_ROOT: 项目根目录（含 daiflow/, requirements.txt 等） ───
// 打包后 extraResources 将后端文件复制到 resources/backend/
// 开发时指向项目根目录
const APP_ROOT = app.isPackaged
  ? path.join(process.resourcesPath, 'backend')
  : path.resolve(__dirname, '..', '..');

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

// ─── 应用启动 ───
async function onAppReady() {
  // 确保数据目录存在
  fs.mkdirSync(DATA_DIR, { recursive: true });

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
   * @param {string|object} data - 状态消息（字符串）或进度对象
   */
  function sendStatus(data) {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.webContents.send('status', data);
    }
    const message = typeof data === 'string' ? data : data.message;
    console.log(`[startup] ${message}`);
  }

  try {
    // 2. Python 环境准备
    const venvDir = path.join(app.getPath('userData'), 'python-env');
    await ensurePythonEnv(APP_ROOT, venvDir, sendStatus);
    sendStatus({ type: 'stage-complete' });

    // 3. 数据库迁移
    sendStatus('正在更新数据库...');
    await runMigrations(APP_ROOT, venvDir, DATA_DIR, sendStatus);
    sendStatus({ type: 'stage-complete' });

    // 4. 端口分配
    sendStatus('正在分配端口...');
    backendPort = await findAvailablePort();
    sendStatus({ type: 'stage-complete' });

    // 5. 启动后端
    sendStatus('正在启动后端服务...');
    const corsOrigins = `http://127.0.0.1:${backendPort},http://localhost:${backendPort}`;

    backend = startBackend({
      appRoot: APP_ROOT,
      venvDir,
      port: backendPort,
      dataDir: DATA_DIR,
      corsOrigins,
      onCrash: handleBackendCrash,
    });
    sendStatus({ type: 'stage-complete' });

    // 6. 等待后端就绪
    sendStatus('等待后端就绪...');
    await waitForBackend(backendPort);
    sendStatus({ type: 'stage-complete' });

    // 7. 创建主窗口
    sendStatus('正在加载界面...');
    createMainWindow();
    sendStatus({ type: 'stage-complete' });

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

  const msgBoxOpts = {
    type: 'error',
    title: '后端服务异常',
    message: `DaiFlow 后端意外退出（代码: ${code}）。是否重新启动？`,
    buttons: ['重新启动', '退出'],
    defaultId: 0,
  };

  const msgBoxPromise = focusWindow
    ? dialog.showMessageBox(focusWindow, msgBoxOpts)
    : dialog.showMessageBox(msgBoxOpts);

  msgBoxPromise.then(({ response: buttonIndex }) => {
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
    isQuitting = false; // 重建窗口后恢复关闭保护
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
