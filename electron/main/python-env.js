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
 */
async function runMigrations(appRoot, venvDir, dataDir) {
  const alembicDir = path.join(appRoot, 'alembic');

  if (!fs.existsSync(alembicDir)) {
    console.log('[migration] alembic directory not found, skipping');
    return;
  }

  console.log('[migration] Running alembic upgrade head...');
  const pythonPath = getPythonPath(venvDir);
  await execFileAsync(pythonPath, [
    '-m', 'alembic', 'upgrade', 'head'
  ], {
    cwd: appRoot,
    env: buildVenvEnv(venvDir, dataDir),
    timeout: 60000,
  });
  console.log('[migration] Done');
}

module.exports = {
  findPython,
  ensurePythonEnv,
  getPythonPath,
  getPipPath,
  buildVenvEnv,
  runMigrations,
};
