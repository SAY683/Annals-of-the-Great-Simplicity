/**
 * trace-to-edm Web 操纵台 — process entrypoint.
 *
 * HTTP app assembly lives in src/app.js. Routes live in src/routes/ by
 * capability; shared services live in src/services/.
 */
const { PACKAGE_VERSION } = require('./src/config');
const { createApp } = require('./src/app');

let PORT = parseInt(process.env.PORT || process.env.TRACE_TO_EDM_PORT || '3100', 10);
const HOST = process.env.TRACE_HOST || '127.0.0.1';

// ── 启动 ──────────────────────────────────────────────────

// P1 修缮 (2026-07-25 元审计 Round 12.10): host 收窄到 127.0.0.1
// 原实现 app.listen(PORT) 未指定 host，等价于隐式 0.0.0.0（暴露至 LAN/公网）
// 默认仅本机访问；如需外部访问，显式设置 TRACE_HOST=0.0.0.0
const app = createApp({ getPort: () => PORT });
function listenWithFallback(port) {
  PORT = port;
  const server = app.listen(port, HOST, () => {
  console.log('');
  console.log('╔══════════════════════════════════════════════════╗');
  console.log(`║   trace-to-edm Web 操纵台 v${PACKAGE_VERSION.padEnd(6)}            ║`);
  console.log('║   元因果控制论桥接系统 — 可视化面板               ║');
  console.log(`║   http://${HOST}:${PORT}                          ║`);
  console.log('╠══════════════════════════════════════════════════╣');
  console.log('║   Mode A: 文本管线  POST /api/run               ║');
  console.log('║   Mode B: 回填管线  POST /api/replay            ║');
  console.log('║   EDM 触发         POST /api/edm/trigger        ║');
  console.log('║   轨迹查询         GET  /api/trajectory          ║');
  console.log('║   版本查询         GET  /api/version             ║');
  console.log('╚══════════════════════════════════════════════════╝');
  console.log('');
  });
  server.on('error', (err) => {
    if (err.code === 'EADDRINUSE' && port < 3120) {
      console.warn('[port] ' + port + ' in use, trying ' + (port + 1) + '...');
      listenWithFallback(port + 1);
    } else {
      console.error('[fatal] listen failed: ' + err.message);
      process.exit(1);
    }
  });
}
listenWithFallback(PORT);
