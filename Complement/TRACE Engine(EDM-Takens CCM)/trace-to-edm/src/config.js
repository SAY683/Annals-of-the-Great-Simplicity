const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const PUBLIC_DIR = path.join(ROOT, 'public');
const BRIDGE_SCRIPT = path.join(ROOT, 'bridge.py');
const PYTHON_CMD = process.env.TRACE_PYTHON_CMD || 'python';
const TRAJECTORY_CSV = process.env.TRACE_TO_EDM_TRAJECTORY_CSV || path.join(ROOT, 'data', 'outputs', 'narrative_meta_trajectories.csv');
const PROJECTS_DIR = process.env.TRACE_TO_EDM_PROJECTS_DIR || path.join(ROOT, 'projects');
const LOG_FILE = process.env.TRACE_TO_EDM_LOG_FILE || path.join(ROOT, 'data', 'logs', 'server.log');

function loadTunnelOrigins() {
  try {
    const tunnelFile = path.join(ROOT, 'tunnel_url.txt');
    if (fs.existsSync(tunnelFile)) {
      const url = fs.readFileSync(tunnelFile, 'utf-8').trim();
      if (url && url.includes('trycloudflare.com')) return [url];
    }
  } catch (_) { /* silent fallback */ }
  return [];
}

const CORS_ORIGIN = process.env.TRACE_CORS_ORIGIN || 'http://127.0.0.1:3100';
const CORS_ALLOWED_ORIGINS = [
  CORS_ORIGIN,
  'http://127.0.0.1:3100',
  'http://localhost:3100',
  'http://127.0.0.1:3000',
  'http://localhost:3000',
  'http://127.0.0.1:5173',
  'http://localhost:5173',
  ...loadTunnelOrigins(),
];

const PACKAGE_VERSION = (() => {
  try { return require(path.join(ROOT, 'package.json')).version || '0.0.0-dev'; }
  catch (error) { console.error(`[trace-to-edm] 读取 package.json 版本失败: ${error.message}，回退到 'unknown'`); return 'unknown'; }
})();

const logDir = path.dirname(LOG_FILE);
if (!fs.existsSync(logDir)) fs.mkdirSync(logDir, { recursive: true });

module.exports = {
  ROOT, PUBLIC_DIR, BRIDGE_SCRIPT, PYTHON_CMD, TRAJECTORY_CSV, PROJECTS_DIR,
  LOG_FILE, CORS_ORIGIN, CORS_ALLOWED_ORIGINS, PACKAGE_VERSION,
};
