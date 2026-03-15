const { spawn } = require('child_process');

/**
 * 通用子进程执行器：spawn 子进程 → 解析 stdout/stderr → 超时控制 → Promise 包装。
 *
 * 用于 pip install、alembic migrate 等需要实时解析输出并汇报进度的场景。
 *
 * @param {object} options
 * @param {string}   options.command     - 可执行文件路径
 * @param {string[]} options.args        - 命令参数
 * @param {object}   [options.spawnOpts] - 传给 child_process.spawn 的额外选项（cwd, env 等）
 * @param {number}   [options.timeout]   - 超时毫秒数（默认 120000）
 * @param {function} [options.onStdout]  - 逐行处理 stdout 的回调 (line: string) => void
 * @param {function} [options.onStderr]  - 逐行处理 stderr 的回调 (line: string) => void
 * @param {string}   [options.label]     - 用于日志的描述标签（如 "pip install"）
 * @returns {Promise<void>}
 */
function runProcess({
  command,
  args,
  spawnOpts = {},
  timeout = 120000,
  onStdout,
  onStderr,
  label = 'process',
}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, spawnOpts);

    const timer = setTimeout(() => {
      child.kill('SIGTERM');
      reject(new Error(`${label} timeout after ${timeout / 1000}s`));
    }, timeout);

    if (onStdout) {
      child.stdout.on('data', (data) => {
        const lines = data.toString().split('\n');
        for (const line of lines) {
          if (line.trim()) onStdout(line.trim());
        }
      });
    }

    if (onStderr) {
      child.stderr.on('data', (data) => {
        const lines = data.toString().split('\n');
        for (const line of lines) {
          if (line.trim()) onStderr(line.trim());
        }
      });
    }

    child.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${label} failed with exit code ${code}`));
      }
    });

    child.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

module.exports = { runProcess };
