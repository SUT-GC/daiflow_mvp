const { execFile } = require('child_process');
const { promisify } = require('util');
const path = require('path');
const fs = require('fs');

const { runProcess } = require('./process-runner');
const { getPythonPath, buildVenvEnv } = require('./python-env');

const execFileAsync = promisify(execFile);

/**
 * 执行 Alembic 数据库迁移（upgrade head）。
 *
 * @param {string}   appRoot    - 项目根目录（含 alembic.ini）
 * @param {string}   venvDir    - venv 目录
 * @param {string}   dataDir    - DAIFLOW_HOME 数据目录
 * @param {function} onStatus   - 进度回调函数（可选）
 */
async function runMigrations(appRoot, venvDir, dataDir, onStatus) {
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
    if (onStatus) onStatus({ type: 'status', message: '初始化数据库...' });

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

  // 3. 运行 Alembic 迁移（使用 runProcess 捕获输出）
  console.log('[migration] Running alembic upgrade head...');
  if (onStatus) onStatus({ type: 'status', message: '正在应用数据库迁移...' });

  let completedMigrations = 0;

  await runProcess({
    command: pythonPath,
    args: ['-m', 'alembic', 'upgrade', 'head'],
    spawnOpts: { cwd: appRoot, env },
    timeout: 60000,
    label: 'Alembic migration',
    onStdout(line) {
      // 解析迁移步骤：匹配 "Running upgrade ... -> <revision>, <description>"
      const upgradeMatch = line.match(/Running upgrade .* -> \w+, (.+)/);
      if (upgradeMatch) {
        completedMigrations++;
        const migrationName = upgradeMatch[1];

        if (onStatus) {
          onStatus({
            type: 'progress',
            stage: 'db-migrate',
            message: `应用迁移 ${completedMigrations}/${totalMigrations}...`,
            progress: {
              current: completedMigrations,
              total: totalMigrations,
              label: migrationName,
            },
            detail: line,
          });
        }
      }

      if (onStatus) onStatus({ type: 'log', detail: line });
    },
    onStderr(line) {
      if (onStatus) onStatus({ type: 'log', detail: line });
    },
  });

  console.log('[migration] Done');
}

module.exports = { runMigrations };
