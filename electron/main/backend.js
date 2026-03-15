const { spawn } = require('child_process');
const { getPythonPath, buildVenvEnv } = require('./python-env');

/**
 * 启动 uvicorn 后端子进程。
 *
 * @param {object} options
 * @param {string} options.appRoot - 应用根目录（backend 目录）
 * @param {string} options.venvDir - venv 目录路径
 * @param {number} options.port - 监听端口
 * @param {string} options.dataDir - DAIFLOW_HOME 数据目录
 * @param {string} options.corsOrigins - CORS 允许的源
 * @param {() => void} options.onCrash - 进程意外退出回调
 * @returns {{ process: ChildProcess, stop: () => Promise<void> }}
 */
function startBackend({ appRoot, venvDir, port, dataDir, corsOrigins, onCrash }) {
  const pythonPath = getPythonPath(venvDir);

  console.log(`[backend] Starting uvicorn in directory: ${appRoot}`);

  const child = spawn(pythonPath, [
    '-m', 'uvicorn',
    'daiflow.main:app',
    '--host', '127.0.0.1',
    '--port', String(port),
    '--no-access-log',
  ], {
    cwd: appRoot,  // 设置工作目录
    env: {
      ...buildVenvEnv(venvDir, dataDir),
      DAIFLOW_CORS_ORIGINS: corsOrigins,
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

    // 进程已退出，无需再做任何事
    if (child.exitCode !== null || child.signalCode !== null) return;

    return new Promise((resolve) => {
      let killTimer = null;

      // 兜底超时：10 秒后强制 resolve 防止 promise 挂住
      const fallbackTimer = setTimeout(() => {
        console.warn('[backend] stop() timed out after 10s, forcing resolve');
        resolve();
      }, 10000);

      // 统一的退出回调：清理所有定时器 + resolve
      child.once('exit', () => {
        clearTimeout(fallbackTimer);
        if (killTimer) clearTimeout(killTimer);
        resolve();
      });

      if (process.platform === 'win32') {
        // Windows: 使用 taskkill 终止整个进程树
        const { execFile } = require('child_process');
        execFile('taskkill', ['/T', '/F', '/PID', String(child.pid)], (err) => {
          if (err) {
            console.error('[backend] taskkill failed:', err.message);
            clearTimeout(fallbackTimer);
            resolve();
          }
          // taskkill 成功时等待 exit 事件或兜底超时
        });
      } else {
        // Unix: SIGTERM + 5 秒后兜底 SIGKILL
        child.kill('SIGTERM');
        killTimer = setTimeout(() => {
          try {
            child.kill('SIGKILL');
          } catch {
            // 进程可能已退出
          }
        }, 5000);
      }
    });
  }

  return { process: child, stop };
}

/**
 * 轮询后端健康检查接口，等待后端就绪。
 * 使用 Electron 内置的 net.fetch（不受 CORS 限制）。
 */
async function waitForBackend(port, maxRetries = 60, intervalMs = 500) {
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
