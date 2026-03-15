const { execFile, spawn } = require('child_process');
const { promisify } = require('util');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');

const execFileAsync = promisify(execFile);

/**
 * 候选 Python 命令列表（按平台）。
 * Unix 优先 python3（避免误用系统 python2），Windows 优先 python 和 py launcher。
 * macOS 上包含 Homebrew 的常见安装路径。
 */
function getPythonCandidates() {
  if (process.platform === 'win32') {
    return ['python', 'py'];
  }

  // macOS/Linux: 先尝试 PATH 中的命令，再尝试常见路径
  const candidates = ['python3', 'python'];

  if (process.platform === 'darwin') {
    // macOS Homebrew 路径（Apple Silicon 和 Intel）
    candidates.push(
      '/opt/homebrew/bin/python3',  // Apple Silicon
      '/usr/local/bin/python3',     // Intel Mac
      '/usr/bin/python3'             // 系统自带
    );
  } else {
    // Linux 常见路径
    candidates.push('/usr/bin/python3');
  }

  return candidates;
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
 * 获取内置 Python 的路径（如果应用已打包）。
 * 根据当前架构选择对应的 Python 版本。
 */
function getBundledPythonPath() {
  const { app } = require('electron');

  if (!app.isPackaged) {
    // 开发模式：检查本地 python-runtime 目录
    const arch = process.arch === 'arm64' ? 'arm64' : 'x64';
    const devPythonPath = path.join(__dirname, '..', 'python-runtime', `darwin-${arch}`, 'bin', 'python3');
    if (fs.existsSync(devPythonPath)) {
      return devPythonPath;
    }
    return null;
  }

  // 打包模式：从 resources 目录获取
  const arch = process.arch === 'arm64' ? 'arm64' : 'x64';
  const bundledPythonPath = path.join(
    process.resourcesPath,
    `python-${arch}`,
    'bin',
    'python3'
  );

  return fs.existsSync(bundledPythonPath) ? bundledPythonPath : null;
}

/**
 * 检测可用的 Python >= 3.11，返回命令路径。
 * 优先使用内置 Python，然后尝试系统 Python。
 */
async function findPython() {
  // 1. 优先尝试内置 Python（开箱即用）
  const bundledPython = getBundledPythonPath();
  if (bundledPython) {
    try {
      const result = await execFileAsync(bundledPython, ['--version'], { timeout: 5000 });
      const output = result.stdout || result.stderr;
      const version = parseVersion(output);
      if (version && (version[0] > 3 || (version[0] === 3 && version[1] >= 11))) {
        console.log(`[python] Using bundled Python: ${bundledPython} (${output.trim()})`);
        return { cmd: bundledPython, args: [] };
      }
    } catch (err) {
      console.warn('[python] Bundled Python check failed:', err.message);
    }
  }

  // 2. 回退到系统 Python（如果用户已安装）
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
        console.log(`[python] Using system Python: ${cmd} (${output.trim()})`);
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
    'Python >= 3.11 not found. This should not happen with bundled Python.\n' +
    'Please report this issue at https://github.com/anthropics/daiflow/issues'
  );
}

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
 * 使用 spawn 安装 pip 包，捕获实时输出并解析进度。
 *
 * @param {string} pipPath - pip 可执行文件路径
 * @param {string[]} args - pip 命令参数
 * @param {string} requirementsPath - requirements.txt 路径（用于预估总数）
 * @param {function} onStatus - 进度回调函数
 * @param {number} timeout - 超时时间（毫秒）
 */
function installPipPackages(pipPath, args, requirementsPath, onStatus, timeout) {
  return new Promise((resolve, reject) => {
    // 预估总包数：读取 requirements.txt 行数 × 3.5（传递依赖系数）
    let estimatedTotal = 40;
    if (requirementsPath && fs.existsSync(requirementsPath)) {
      const lines = fs.readFileSync(requirementsPath, 'utf-8')
        .split('\n')
        .filter(line => line.trim() && !line.trim().startsWith('#'));
      estimatedTotal = Math.ceil(lines.length * 3.5);
    }

    let installedCount = 0;
    let currentPackage = '';

    const pip = spawn(pipPath, args, { timeout });

    // 超时处理
    const timer = setTimeout(() => {
      pip.kill('SIGTERM');
      reject(new Error('Pip install timeout'));
    }, timeout);

    pip.stdout.on('data', (data) => {
      const lines = data.toString().split('\n');

      for (const line of lines) {
        if (!line.trim()) continue;

        // 解析包名：匹配 "Collecting <package>" 或 "Downloading <package>"
        const collectingMatch = line.match(/Collecting\s+([^\s(]+)/);
        const downloadingMatch = line.match(/Downloading\s+([^\s-]+)/);

        if (collectingMatch || downloadingMatch) {
          const packageName = (collectingMatch || downloadingMatch)[1];

          // 过滤掉版本号和特殊字符
          currentPackage = packageName.split('>=')[0].split('==')[0].split('<')[0];
          installedCount++;

          // 动态调整总数（如果超出预估）
          if (installedCount > estimatedTotal) {
            estimatedTotal = installedCount + 5;
          }

          onStatus({
            type: 'progress',
            stage: 'pip-install',
            message: `正在安装 ${currentPackage}...`,
            progress: {
              current: installedCount,
              total: estimatedTotal,
              label: currentPackage
            },
            detail: line.trim()
          });
        }

        // 发送详细日志
        onStatus({ type: 'log', detail: line.trim() });
      }
    });

    pip.stderr.on('data', (data) => {
      const lines = data.toString().split('\n');
      for (const line of lines) {
        if (line.trim()) {
          onStatus({ type: 'log', detail: line.trim() });
        }
      }
    });

    pip.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`Pip install failed with code ${code}`));
      }
    });

    pip.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

/**
 * 确保 Python venv 就绪，返回 venv 目录路径。
 *
 * @param {string} appRoot - 项目根目录（含 requirements.txt 等）
 * @param {string} venvDir - venv 存放目录
 * @param {(msg: string|object) => void} onStatus - 状态回调（更新 Splash 显示）
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
      await installPipPackages(getPipPath(venvDir), [
        'install', '-r', requirementsPath, '--prefer-binary'
      ], requirementsPath, onStatus, 600000);
    }

    // 安装 daiflow 包本身
    onStatus('正在安装 DaiFlow 包...');
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

/**
 * 构造子进程的环境变量：将 venv bin 目录加到 PATH 最前面 + 设置 DAIFLOW_HOME。
 * 所有需要在 venv 中执行 Python 命令的地方都应该使用此函数，避免重复构造。
 */
function buildVenvEnv(venvDir, dataDir) {
  const pythonPath = getPythonPath(venvDir);
  return {
    ...process.env,
    DAIFLOW_HOME: dataDir,
    PATH: path.dirname(pythonPath) + path.delimiter + (process.env.PATH || ''),
  };
}

/**
 * 执行 Alembic 数据库迁移（upgrade head）。
 *
 * @param {string} appRoot - 项目根目录（含 alembic.ini）
 * @param {string} venvDir - venv 目录
 * @param {string} dataDir - DAIFLOW_HOME 数据目录
 * @param {function} onProgress - 进度回调函数（可选）
 */
async function runMigrations(appRoot, venvDir, dataDir, onProgress) {
  const alembicDir = path.join(appRoot, 'alembic');

  if (!fs.existsSync(alembicDir)) {
    console.log('[migration] alembic directory not found, skipping');
    return;
  }

  const pythonPath = getPythonPath(venvDir);
  const env = buildVenvEnv(venvDir, dataDir);

  // 1. 检查数据库是否存在
  const dbPath = path.join(dataDir, 'daiflow.db');
  const dbExists = fs.existsSync(dbPath);

  // 如果数据库不存在，先初始化表，然后标记所有迁移为已应用
  if (!dbExists) {
    console.log('[migration] Database does not exist, initializing...');
    if (onProgress) onProgress({ type: 'status', message: '初始化数据库...' });

    const initScript = path.join(appRoot, 'daiflow', 'init_db_script.py');
    if (fs.existsSync(initScript)) {
      await execFileAsync(pythonPath, [initScript], {
        cwd: appRoot,
        env,
        timeout: 30000,
      });

      // 标记所有迁移为已应用（stamp head）
      console.log('[migration] Marking migrations as applied...');
      await execFileAsync(pythonPath, ['-m', 'alembic', 'stamp', 'head'], {
        cwd: appRoot,
        env,
        timeout: 10000,
      });

      console.log('[migration] Database initialized successfully');
      return; // 初始化完成，无需运行迁移
    }
  }

  // 2. 获取迁移总数
  const versionsDir = path.join(alembicDir, 'versions');
  let totalMigrations = 0;
  if (fs.existsSync(versionsDir)) {
    const migrationFiles = fs.readdirSync(versionsDir).filter(f => f.endsWith('.py'));
    totalMigrations = migrationFiles.length;
  }

  // 3. 运行 Alembic 迁移（使用 spawn 捕获输出）
  console.log('[migration] Running alembic upgrade head...');
  if (onProgress) onProgress({ type: 'status', message: '正在应用数据库迁移...' });

  return new Promise((resolve, reject) => {
    const alembic = spawn(pythonPath, ['-m', 'alembic', 'upgrade', 'head'], {
      cwd: appRoot,
      env,
      timeout: 60000
    });

    let completedMigrations = 0;

    // 超时处理
    const timer = setTimeout(() => {
      alembic.kill('SIGTERM');
      reject(new Error('Alembic migration timeout'));
    }, 60000);

    alembic.stdout.on('data', (data) => {
      const lines = data.toString().split('\n');

      for (const line of lines) {
        if (!line.trim()) continue;

        // 解析迁移步骤：匹配 "Running upgrade ... -> <revision>, <description>"
        const upgradeMatch = line.match(/Running upgrade .* -> \w+, (.+)/);
        if (upgradeMatch) {
          completedMigrations++;
          const migrationName = upgradeMatch[1];

          if (onProgress) {
            onProgress({
              type: 'progress',
              stage: 'db-migrate',
              message: `应用迁移 ${completedMigrations}/${totalMigrations}...`,
              progress: {
                current: completedMigrations,
                total: totalMigrations,
                label: migrationName
              },
              detail: line.trim()
            });
          }
        }

        // 发送详细日志
        if (onProgress) {
          onProgress({ type: 'log', detail: line.trim() });
        }
      }
    });

    alembic.stderr.on('data', (data) => {
      const lines = data.toString().split('\n');
      for (const line of lines) {
        if (line.trim() && onProgress) {
          onProgress({ type: 'log', detail: line.trim() });
        }
      }
    });

    alembic.on('close', (code) => {
      clearTimeout(timer);
      console.log('[migration] Done');
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`Alembic migration failed with code ${code}`));
      }
    });

    alembic.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

module.exports = {
  findPython,
  ensurePythonEnv,
  getPythonPath,
  getPipPath,
  buildVenvEnv,
  runMigrations,
};
