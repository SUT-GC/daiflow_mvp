/**
 * macOS 公证脚本 — electron-builder afterSign hook。
 *
 * 需要以下环境变量：
 *   APPLE_ID          — Apple 开发者账号邮箱
 *   APPLE_ID_PASSWORD — App-specific password (非账号密码)
 *   APPLE_TEAM_ID     — 开发者团队 ID
 *
 * 未设置环境变量时跳过公证（适用于本地开发构建）。
 */
const path = require('path');
const { notarize } = require('@electron/notarize');

exports.default = async function notarizing(context) {
  const { electronPlatformName, appOutDir } = context;

  // 仅 macOS 需要公证
  if (electronPlatformName !== 'darwin') {
    return;
  }

  const appleId = process.env.APPLE_ID;
  const appleIdPassword = process.env.APPLE_ID_PASSWORD;
  const teamId = process.env.APPLE_TEAM_ID;

  if (!appleId || !appleIdPassword || !teamId) {
    console.log('Skipping notarization: APPLE_ID, APPLE_ID_PASSWORD, or APPLE_TEAM_ID not set');
    return;
  }

  const appName = context.packager.appInfo.productFilename;
  const appPath = path.join(appOutDir, `${appName}.app`);

  console.log(`Notarizing ${appPath}...`);

  await notarize({
    appPath,
    appleId,
    appleIdPassword,
    teamId,
  });

  console.log('Notarization complete');
};
