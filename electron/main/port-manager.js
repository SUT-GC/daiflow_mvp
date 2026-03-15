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
