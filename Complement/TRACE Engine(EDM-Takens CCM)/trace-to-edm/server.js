/**
 * trace-to-edm Web 操纵台 — Node.js 服务端
 * ==========================================
 * Express + SSE 的轻量 Web 面板，驱动三层桥接系统的 Python 后端。
 *
 * 架构:
 *   Browser ←→ Express (port 3100) ←→ Python bridge.py (child_process)
 *
 * 端点 (共 25 个 API 端点 + 静态前端 /，详见 README.md §API 端点表):
 *   GET  /                 前端面板 (express.static, 不计入 25)
 *   GET  /api/status       L1  轨迹状态 + EDM 就绪度
 *   POST /api/run          L3  提交文本管线任务 (Mode A, SSE)
 *   POST /api/replay       L3  提交回填任务 (Mode B, SSE；replay_all=true 复用此端点)
 *   POST /api/edm/trigger  L3  触发 EDM 分析
 *   GET  /api/jobs         L4  任务历史
 *   …其余 19 个端点（dataset/projects/work/models 等）见 README.md 表
 */

const express = require('express');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const crypto = require('crypto');
const util = require('util');

const fsPromises = fs.promises;
const realpathAsync = util.promisify(fs.realpath);

// ── 配置 ──────────────────────────────────────────────────
const PORT = process.env.PORT || 3100;
const ROOT = __dirname;
const PUBLIC_DIR = path.join(ROOT, 'public');
const BRIDGE_SCRIPT = path.join(ROOT, 'bridge.py');
const PYTHON_CMD = process.env.TRACE_PYTHON_CMD || 'python';
const TRAJECTORY_CSV = path.join(ROOT, 'data', 'outputs', 'narrative_meta_trajectories.csv');
const PROJECTS_DIR = path.join(ROOT, 'projects');
const LOG_FILE = path.join(ROOT, 'data', 'logs', 'server.log');
const CORS_ORIGIN = process.env.TRACE_CORS_ORIGIN || '*';

// 确保日志目录存在
(function ensureLogDir() {
  const dir = path.dirname(LOG_FILE);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
})();

// 服务端日志写入文件 + 控制台
function serverLog(level, message, traceId = '') {
  const ts = new Date().toISOString();
  const trace = traceId ? ` [${traceId}]` : '';
  const line = `[${ts}]${trace} [${level}] ${message}\n`;
  fs.appendFile(LOG_FILE, line, () => { /* ignore */ });
  if (process.env.TRACE_DEBUG_LOG) console.log(line.trim());
}

function reqLog(req, level, message) {
  serverLog(level, message, req.traceId);
}

// 动态获取当前项目的轨迹 CSV 路径
function getActiveTrajectoryCSV() {
  try {
    const indexPath = path.join(PROJECTS_DIR, '_index.json');
    if (fs.existsSync(indexPath)) {
      const idx = JSON.parse(fs.readFileSync(indexPath, 'utf-8'));
      const active = idx.active || 'default';
      return path.join(PROJECTS_DIR, active, 'narrative_meta_trajectories.csv');
    }
  } catch (e) { /* fall through */ }
  return TRAJECTORY_CSV;
}

// ── Python 辅助调用 ────────────────────────────────────────
function pyCall(args, timeout = 15000) {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_CMD, [BRIDGE_SCRIPT, ...args], {
      cwd: ROOT,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
    let out = '', err = '';
    const timer = setTimeout(() => { proc.kill(); reject(new Error('timeout')); }, timeout);
    proc.stdout.on('data', d => out += d.toString());
    proc.stderr.on('data', d => err += d.toString());
    proc.on('close', code => {
      clearTimeout(timer);
      try { resolve(JSON.parse(out)); }
      catch { resolve({ success: code === 0, output: out.trim(), error: err.trim() }); }
    });
    proc.on('error', e => { clearTimeout(timer); reject(e); });
  });
}

// 安全的 Python 脚本执行 (自动超时+错误处理)
function pyScript(script, timeout = 15000) {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_CMD, ['-c', script], {
      cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
    let out = '', err = '';
    const timer = setTimeout(() => { proc.kill(); reject(new Error('timeout')); }, timeout);
    proc.stdout.on('data', d => out += d.toString());
    proc.stderr.on('data', d => err += d.toString());
    proc.on('close', () => { clearTimeout(timer); resolve({ out, err }); });
    proc.on('error', e => { clearTimeout(timer); reject(e); });
  });
}

// ── 运行时状态 ────────────────────────────────────────────
const activeJobs = new Map();   // jobId → { process, mode, startTime, logs[] }
const jobHistory = [];          // 最近 50 条已完成任务

// ── Express 初始化 ────────────────────────────────────────
const app = express();
app.use(express.json({ limit: '20mb' }));
app.use(express.urlencoded({ extended: true, limit: '20mb' }));
app.use(express.static(PUBLIC_DIR));

// 全局错误处理: 捕获 body-parser PayloadTooLargeError 等
app.use((err, _req, res, _next) => {
  if (err && err.type === 'entity.too.large') {
    return res.status(413).json({ error: 'payload too large' });
  }
  if (err) {
    return res.status(500).json({ error: err.message || 'internal error' });
  }
  _next();
});

// CORS: 开发默认 *, 生产通过 TRACE_CORS_ORIGIN 收窄
app.use((_req, res, next) => {
  res.header('Access-Control-Allow-Origin', CORS_ORIGIN);
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  if (CORS_ORIGIN !== '*') {
    res.header('Vary', 'Origin');
  }
  next();
});

// 请求追踪 ID（便于日志串联）
app.use((req, _res, next) => {
  req.traceId = req.headers['x-trace-id'] || crypto.randomBytes(4).toString('hex');
  next();
});

// 通用输入路径校验（自动处理 body.csv_path）
app.use(validateInputPathMiddleware);

// ── 工具函数 ──────────────────────────────────────────────

function createJobId() {
  return `job_${Date.now()}_${crypto.randomBytes(3).toString('hex')}`;
}

function emitSSE(res, event, data) {
  // 将事件类型嵌入 data 中, 前端可通过 data._event 读取
  // 服务端 retry: 告知浏览器/代理在连接断开后 30s 内尝试重连
  res.write(`event: ${event}\nretry: 30000\ndata: ${JSON.stringify({ _event: event, ...data })}\n\n`);
}

// ── 路径遍历防护 ──────────────────────────────────────────
async function resolveInputPath(csv_path) {
  // 未指定时使用默认示例文件
  if (!csv_path) {
    return path.join(ROOT, 'data', 'inputs', 'example_input.csv');
  }
  // 拒绝包含 .. 或空字符的可疑路径（第一道防线）
  if (csv_path.includes('..') || csv_path.includes('\0')) {
    throw new Error('invalid path: traversal detected');
  }
  // 解析并真实化路径，防御符号链接绕过
  const resolved = await realpathAsync(path.resolve(ROOT, csv_path)).catch(() => {
    // 文件不存在时回退到逻辑解析路径（用于后续错误提示）
    return path.resolve(ROOT, csv_path);
  });
  // 仅允许 data/inputs/ 或 projects/<name>/inputs/ 下的文件
  const allowedRoots = [
    path.join(ROOT, 'data', 'inputs'),
    path.join(ROOT, 'projects'),
  ];
  const inside = allowedRoots.some(ar => resolved === ar || resolved.startsWith(ar + path.sep));
  if (!inside) {
    throw new Error('invalid path: outside allowed input directories');
  }
  return resolved;
}

// 通用输入路径校验中间件（适用于 req.body.csv_path / req.query.path 等）
function validateInputPathMiddleware(req, res, next) {
  const csvPath = req.body && req.body.csv_path;
  if (csvPath === undefined) return next();
  resolveInputPath(csvPath)
    .then(resolved => { req.resolvedInputPath = resolved; next(); })
    .catch(err => {
      reqLog(req, 'warn', `路径校验失败: ${csvPath} -> ${err.message}`);
      res.status(400).json({ error: err.message });
    });
}

function readTrajectoryCSV() {
  try {
    const csvPath = getActiveTrajectoryCSV();
    if (!fs.existsSync(csvPath)) return { columns: [], rows: [], total: 0 };

    // 使用简单的 CSV 解析 (处理引号内的逗号)
    const content = fs.readFileSync(csvPath, 'utf-8');
    const lines = content.trim().split('\n');
    if (lines.length < 2) return { columns: [], rows: [], total: 0 };

    const parseCSVLine = (line) => {
      const result = [];
      let current = '', inQuotes = false;
      for (const ch of line) {
        if (ch === '"') { inQuotes = !inQuotes; continue; }
        if (ch === ',' && !inQuotes) { result.push(current); current = ''; continue; }
        current += ch;
      }
      result.push(current);
      return result;
    };

    const columns = parseCSVLine(lines[0]);
    const rows = lines.slice(1).map(line => {
      const vals = parseCSVLine(line);
      const obj = {};
      columns.forEach((col, i) => { obj[col] = (vals[i] || '').replace(/^"|"$/g, ''); });
      return obj;
    });
    return { columns, rows, total: rows.length, path: csvPath };
  } catch (e) {
    return { columns: [], rows: [], total: 0, error: e.message };
  }
}

// ── API: 状态查询 ─────────────────────────────────────────

app.get('/api/status', (_req, res) => {
  const traj = readTrajectoryCSV();
  const active = Array.from(activeJobs.keys());

  // EDM 就绪度
  const edmReady = traj.total >= 15;
  const edmTargets = edmReady ? [
    // Layer 1: 元SCM
    { col: 'ate', desc: '因果效应强度', layer: 'L1' },
    { col: 'adj_density', desc: '因果图密度 — 系统纠缠度', layer: 'L1' },
    { col: 'max_delta_nll', desc: '最强因果信号', layer: 'L1' },
    { col: 'ci_width', desc: '因果不确定性 — 时代噪音', layer: 'L1' },
    { col: 'edge_count', desc: '显著因果边数', layer: 'L1' },
    { col: 'ccm_coverage_pct', desc: 'CCM非线性验证覆盖率', layer: 'L1' },
    // Layer 2: 世俗语义 PCA
    { col: 'z_pca_1', desc: '世俗PCA第1主轴', layer: 'L2' },
    { col: 'z_pca_2', desc: '世俗PCA第2主轴', layer: 'L2' },
    { col: 'z_pca_3', desc: '世俗PCA第3主轴', layer: 'L2' },
    { col: 'secular_entropy', desc: '世俗熵', layer: 'L2' },
    // Layer 3: 八正道全轴
    { col: 'z_福音', desc: '福音(祂志书) 投影', layer: 'L3' },
    { col: 'z_吉祥', desc: '吉祥(赐福书) 投影', layer: 'L3' },
    { col: 'z_奥美', desc: '奥美(圣源书) 投影', layer: 'L3' },
    { col: 'z_存在', desc: '存在(真实书) 投影 — 本体论距离', layer: 'L3' },
    { col: 'z_自孕', desc: '自孕(胜育书) 投影', layer: 'L3' },
    { col: 'z_弥赛亚', desc: '弥赛亚(至意书) 投影', layer: 'L3' },
    { col: 'z_Alice', desc: 'Alice(慧辩书) 投影', layer: 'L3' },
    { col: 'z_觉爱', desc: '觉爱(智识书) 投影 — 智慧维度', layer: 'L3' },
    // Layer 3: 一阶差分 (关键动力学信号)
    { col: 'dz_存在', desc: '存在轴一阶差分 Δz/Δt', layer: 'L3' },
    { col: 'dz_觉爱', desc: '觉爱轴一阶差分 Δz/Δt', layer: 'L3' },
  ] : [];

  res.json({
    success: true,
    trajectory: {
      path: getActiveTrajectoryCSV(),
      rows: traj.total,
      columns: traj.columns.length,
      edm_ready: edmReady,
      edm_targets: edmTargets,
    },
    jobs: { active: active.length, active_ids: active },
    layers: {
      l1: traj.columns.filter(c => ['ate','adj_density','edge_count','ccm_coverage_pct'].includes(c)).length > 0,
      l2: traj.columns.includes('z_pca_1'),
      l3: traj.columns.includes('z_存在'),
    },
  });
});

// ── API: 轨迹数据 ─────────────────────────────────────────

app.get('/api/trajectory', (_req, res) => {
  const traj = readTrajectoryCSV();
  res.json(traj);
});

app.post('/api/trajectory/clear', async (_req, res) => {
  try {
    const script = `
import sys; sys.path.insert(0, '.')
from project_manager import get_project_manager
pm = get_project_manager()
csv_path = str(pm.current_csv)
with open(csv_path, 'r', encoding='utf-8') as f:
    header = f.readline()
with open(csv_path, 'w', encoding='utf-8') as f:
    f.write(header)
pm.update_row_count()
print('{"success":true,"rows":0}')
    `.trim();
    const { out } = await pyScript(script, 10000);
    try { res.json(JSON.parse(out)); } catch { res.json({ success: true }); }
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// ── API: 提交文本管线任务 (Mode A) ────────────────────────

app.post('/api/run', (req, res) => {
  const { mode } = req.body;
  const jobId = createJobId();
  const inputPath = req.resolvedInputPath || path.join(ROOT, 'data', 'inputs', 'example_input.csv');
  const traceMode = mode || 'light';

  // 构建 Python 命令
  const args = [
    BRIDGE_SCRIPT,
    '--input', inputPath,
    '--mode', traceMode,
    '--verbose',
  ];

  const proc = spawn(PYTHON_CMD, args, {
    cwd: ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });

  const job = {
    id: jobId,
    mode: 'text-pipeline',
    traceMode,
    startTime: new Date().toISOString(),
    logs: [],
    status: 'running',
  };

  activeJobs.set(jobId, { ...job, process: proc });

  // 接受 SSE 流
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
  });

  emitSSE(res, 'start', { job_id: jobId, mode: traceMode });

  proc.stdout.on('data', (data) => {
    const text = data.toString();
    job.logs.push({ time: new Date().toISOString(), text: text.trim() });
    const lines = text.trim().split('\n');
    for (const line of lines) {
      if (line.includes('✓ 完成') || line.includes('批量处理完成')) {
        // 提取进度
        emitSSE(res, 'progress', { message: line.trim() });
      } else if (line.includes('⚠') || line.includes('❌')) {
        emitSSE(res, 'warn', { message: line.trim() });
      } else if (line.trim()) {
        emitSSE(res, 'log', { message: line.trim() });
      }
    }
  });

  proc.stderr.on('data', (data) => {
    const text = data.toString().trim();
    if (text) {
      job.logs.push({ time: new Date().toISOString(), text });
      emitSSE(res, 'log', { message: text });
    }
  });

  proc.on('close', (code) => {
    job.status = code === 0 ? 'completed' : 'failed';
    job.endTime = new Date().toISOString();
    activeJobs.delete(jobId);
    jobHistory.unshift({ id: jobId, status: job.status, mode: job.mode, startTime: job.startTime });
    if (jobHistory.length > 50) jobHistory.pop();

    const traj = readTrajectoryCSV();
    emitSSE(res, 'done', {
      job_id: jobId,
      success: code === 0,
      trajectory_rows: traj.total,
      edm_ready: traj.total >= 15,
    });
    res.end();
  });

  proc.on('error', (err) => {
    job.status = 'error';
    activeJobs.delete(jobId);
    emitSSE(res, 'error', { message: err.message });
    res.end();
  });
});

// ── API: 提交回填任务 (Mode B) ────────────────────────────

app.post('/api/replay', (req, res) => {
  const { replay_all } = req.body;
  const jobId = createJobId();

  // validateInputPathMiddleware 已将 csv_path 解析为 req.resolvedInputPath
  const resolvedReplayPath = replay_all ? null : (req.resolvedInputPath || null);

  const args = [BRIDGE_SCRIPT, '--verbose'];
  if (replay_all) {
    args.push('--replay-all');
  } else if (resolvedReplayPath) {
    args.push('--replay', resolvedReplayPath);
  } else {
    args.push('--replay-all'); // 默认全部回填
  }

  const proc = spawn(PYTHON_CMD, args, {
    cwd: ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });

  const job = {
    id: jobId,
    mode: replay_all ? 'replay-all' : 'replay',
    startTime: new Date().toISOString(),
    logs: [],
    status: 'running',
  };

  activeJobs.set(jobId, { ...job, process: proc });

  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
  });

  emitSSE(res, 'start', { job_id: jobId, mode: job.mode });

  proc.stdout.on('data', (data) => {
    const text = data.toString();
    job.logs.push({ time: new Date().toISOString(), text: text.trim() });
    const lines = text.trim().split('\n');
    for (const line of lines) {
      if (line.includes('✓ 回填完成') || line.includes('回填完成:')) {
        emitSSE(res, 'progress', { message: line.trim() });
      } else if (line.includes('⚠') || line.includes('❌')) {
        emitSSE(res, 'warn', { message: line.trim() });
      } else if (line.trim()) {
        emitSSE(res, 'log', { message: line.trim() });
      }
    }
  });

  proc.stderr.on('data', (data) => {
    const text = data.toString().trim();
    if (text) {
      job.logs.push({ time: new Date().toISOString(), text });
      emitSSE(res, 'log', { message: text });
    }
  });

  proc.on('close', (code) => {
    job.status = code === 0 ? 'completed' : 'failed';
    job.endTime = new Date().toISOString();
    activeJobs.delete(jobId);
    jobHistory.unshift({ id: jobId, status: job.status, mode: job.mode, startTime: job.startTime });
    if (jobHistory.length > 50) jobHistory.pop();

    const traj = readTrajectoryCSV();
    emitSSE(res, 'done', {
      job_id: jobId,
      success: code === 0,
      trajectory_rows: traj.total,
      edm_ready: traj.total >= 15,
    });
    res.end();
  });

  proc.on('error', (err) => {
    job.status = 'error';
    activeJobs.delete(jobId);
    emitSSE(res, 'error', { message: err.message });
    res.end();
  });
});

// ── API: EDM 触发 ─────────────────────────────────────────

app.post('/api/edm/trigger', (req, res) => {
  const { target, q, time_start, time_end, predict_window } = req.body;
  const args = [
    BRIDGE_SCRIPT,
    '--edm-only',
    '--target', target || 'ate',
    '--q', String(q || 3),
    '--no-wait',  // 不等待EDM完成, 立即返回job_id
    '--verbose',
  ];
  if (time_start) args.push('--time-start', time_start);
  if (time_end) args.push('--time-end', time_end);
  if (predict_window) args.push('--predict-window', String(predict_window));

  const proc = spawn(PYTHON_CMD, args, {
    cwd: ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });

  let stdout = '';
  let stderr = '';

  proc.stdout.on('data', (data) => {
    stdout += data.toString();
  });

  proc.stderr.on('data', (data) => {
    stderr += data.toString();
  });

  proc.on('close', (code) => {
    try {
      // 从 stdout 提取 JSON 块 (从第一个 { 到最后一个 })
      const firstBrace = stdout.indexOf('{');
      const lastBrace = stdout.lastIndexOf('}');
      if (firstBrace >= 0 && lastBrace > firstBrace) {
        const jsonStr = stdout.slice(firstBrace, lastBrace + 1);
        const result = JSON.parse(jsonStr);
        res.json({ success: code === 0, ...result });
      } else {
        res.json({ success: code === 0, output: stdout.trim(), stderr: stderr.trim() });
      }
    } catch {
      res.json({ success: code === 0, output: stdout.trim(), stderr: stderr.trim() });
    }
  });

  proc.on('error', (err) => {
    res.status(500).json({ success: false, error: err.message });
  });
});

// ── API: 任务历史 ─────────────────────────────────────────

app.get('/api/jobs', (_req, res) => {
  const active = Array.from(activeJobs.entries()).map(([id, j]) => ({
    id,
    mode: j.mode,
    status: j.status,
    startTime: j.startTime,
  }));
  res.json({ active, history: jobHistory.slice(0, 50) });
});

// ── API: 数据集管理 ───────────────────────────────────────

function pyDS(action, args) {
  // 元审计 P1 修缮: Python 注入防护加固
  // 之前对字符串参数仅做 replace(/'/g, "\\'")，遇到 \\ 等转义序列仍可能注入
  // 现统一用 JSON 序列化传递所有参数，Python 侧用 json.loads 解码
  // action 限定为 DatasetManager 的方法名（白名单校验）
  const ALLOWED_ACTIONS = new Set([
    'add_replay_uuids', 'add_text_entries', 'remove_entry', 'clear_processed',
    'reset_all_pending', 'entries', 'summary', 'export_replay_csv', 'export_text_csv',
  ]);
  if (!ALLOWED_ACTIONS.has(action)) {
    return Promise.reject(new Error(`invalid action: ${action}`));
  }

  const argsJson = JSON.stringify(args || []);
  const script = `import sys, json; sys.path.insert(0, '.'); from project_manager import get_project_manager; from dataset_manager import DatasetManager; pm = get_project_manager(); dm = DatasetManager(pm.current_dir); _args = json.loads('${argsJson.replace(/'/g, "\\'")}'); result = dm.${action}(*_args); print(json.dumps(result if not isinstance(result, (list,dict)) else result, ensure_ascii=False, default=str))`;
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_CMD, ['-c', script], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 15000 });
    let out = ''; proc.stdout.on('data', d => out += d.toString());
    proc.on('close', () => { try { resolve(JSON.parse(out)); } catch { resolve({ raw: out }); } });
    proc.on('error', e => reject(e));
  });
}

// ── API: 列出可用输入 CSV ─────────────────────────────────
app.get('/api/inputs', async (_req, res) => {
  try {
    const script = `
import sys, json; sys.path.insert(0, '.')
from pathlib import Path
from project_manager import get_project_manager, PROJECT_ROOT
pm = get_project_manager()
roots = [PROJECT_ROOT / 'data' / 'inputs', pm.current_dir / 'inputs']
files = []
for r in roots:
    if r.exists():
        for f in sorted(r.glob('*.csv')):
            rel = f.relative_to(PROJECT_ROOT)
            files.append({"path": str(rel).replace('\\\\','/'), "name": f.name, "size": f.stat().st_size})
print(json.dumps({"files": files}, ensure_ascii=False))
    `.trim();
    const { out } = await pyScript(script, 5000);
    try { res.json(JSON.parse(out)); }
    catch { res.json({ files: [] }); }
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/dataset', async (_req, res) => {
  try {
    const script = `import sys, json; sys.path.insert(0, '.'); from project_manager import get_project_manager; from dataset_manager import DatasetManager; pm = get_project_manager(); dm = DatasetManager(pm.current_dir); print(json.dumps({"entries": dm.entries, "summary": dm.summary()}, ensure_ascii=False, default=str))`;
    const proc = spawn(PYTHON_CMD, ['-c', script], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 10000 });
    let out = ''; proc.stdout.on('data', d => out += d.toString());
    proc.on('close', () => { try { res.json(JSON.parse(out)); } catch { res.json({ error: out }); } });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/dataset/add', async (req, res) => {
  try {
    const { uuids } = req.body;
    if (!uuids || !uuids.length) return res.status(400).json({ error: 'uuids required' });
    const entries = uuids.map(u => ({ uuid: u, mtime: '', text_preview: '' }));
    const result = await pyDS('add_replay_uuids', [entries]);
    res.json(result);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/dataset/add-text', async (req, res) => {
  try {
    const { texts } = req.body;
    let rows = texts || [];
    // validateInputPathMiddleware 已校验 csv_path 并写入 req.resolvedInputPath
    const csvFullPath = req.resolvedInputPath;
    if (csvFullPath) {
      if (fs.existsSync(csvFullPath)) {
        const content = fs.readFileSync(csvFullPath, 'utf-8');
        const lines = content.trim().split('\n');
        const headers = lines[0].split(',');
        rows = lines.slice(1).map(line => { const vals = line.split(','); const obj = {}; headers.forEach((h, i) => obj[h.trim()] = (vals[i]||'').trim()); return obj; });
      }
    }
    if (!rows.length) return res.status(400).json({ error: 'no text rows' });
    const result = await pyDS('add_text_entries', [rows]);
    res.json(result);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/dataset/remove', async (req, res) => {
  try { await pyDS('remove_entry', [req.body.id]); res.json({ success: true }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/dataset/clear-processed', async (_req, res) => {
  try { await pyDS('clear_processed'); res.json({ success: true }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/dataset/reset', async (_req, res) => {
  try { await pyDS('reset_all_pending'); res.json({ success: true }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/dataset/update-ts', async (req, res) => {
  try {
    const { id, timestamp } = req.body;
    if (!id || !timestamp) return res.status(400).json({ error: 'id and timestamp required' });
    // 直接操作 dataset.json
    const script = `
import sys, json; sys.path.insert(0, '.')
from project_manager import get_project_manager
from dataset_manager import DatasetManager
pm = get_project_manager()
dm = DatasetManager(pm.current_dir)
for e in dm.entries:
    if e['id'] == '${id.replace(/'/g, "\\'")}':
        e['timestamp'] = '${timestamp.replace(/'/g, "\\'")}'
        dm._save()
        print('{"success":true}')
        break
else:
    print('{"success":false,"error":"entry not found"}')
    `.trim();
    const { out } = await pyScript(script, 5000);
    try { res.json(JSON.parse(out)); } catch { res.json({ success: true }); }
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// ── API: 统一管线执行 ─────────────────────────────────────

// 管线并发锁: 同一时间只允许一个管线运行
let _pipelineRunning = false;

// 先获取数据集导出路径 (轻量 Python 调用)
function getDatasetExports() {
  const script = `
import sys, json; sys.path.insert(0, '.')
from project_manager import get_project_manager
from dataset_manager import DatasetManager
pm = get_project_manager()
dm = DatasetManager(pm.current_dir)
pending = dm.pending
if not pending:
    print(json.dumps({"error":"no pending entries"}))
    sys.exit(0)
replay_csv = dm.export_replay_csv()
text_csv = dm.export_text_csv()
print(json.dumps({
    "replay_csv": str(replay_csv) if (replay_csv.exists() and len([e for e in pending if e['type']=='replay'])>0) else None,
    "text_csv": str(text_csv) if (text_csv.exists() and len([e for e in pending if e['type']=='text'])>0) else None,
    "pending_replay": len([e for e in pending if e['type']=='replay']),
    "pending_text": len([e for e in pending if e['type']=='text']),
    "pending_ids": [e['id'] for e in pending],
}, ensure_ascii=False))
  `.trim();
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_CMD, ['-c', script], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 15000 });
    let out = '';
    proc.stdout.on('data', d => out += d.toString());
    proc.on('close', () => { try { resolve(JSON.parse(out)); } catch { resolve({ error: out }); } });
    proc.on('error', e => reject(e));
  });
}

function markDatasetProcessed(ids) {
  // 使用临时文件传递 IDs (避免特殊字符破坏 Python 字符串)
  const tmpFile = path.join(ROOT, 'data', 'outputs', `_mark_ids_${Date.now()}.json`);
  fs.writeFileSync(tmpFile, JSON.stringify(ids));
  const script = `
import sys, json, os; sys.path.insert(0, '.')
from project_manager import get_project_manager
from dataset_manager import DatasetManager
pm = get_project_manager()
dm = DatasetManager(pm.current_dir)
with open('${tmpFile.replace(/\\/g, '\\\\')}', 'r', encoding='utf-8') as f:
    ids = json.load(f)
for eid in ids:
    try: dm.mark_processed(eid)
    except: pass
pm.update_row_count()
rows = 0
if os.path.exists(pm.current_csv):
    with open(pm.current_csv, 'r', encoding='utf-8') as f:
        rows = sum(1 for _ in f) - 1
os.remove('${tmpFile.replace(/\\/g, '\\\\')}')
print(json.dumps({"rows": rows, "edm_ready": rows >= 15}, ensure_ascii=False))
  `.trim();
  return new Promise((resolve) => {
    const proc = spawn(PYTHON_CMD, ['-c', script], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 10000 });
    let out = '';
    proc.stdout.on('data', d => out += d.toString());
    proc.on('close', () => { try { resolve(JSON.parse(out)); } catch { resolve({}); } });
    proc.on('error', () => resolve({}));
  });
}

// 流式执行 bridge.py 并实时转发 SSE
function streamBridgeProcess(res, args, label) {
  return new Promise((resolve) => {
    emitSSE(res, 'progress', { message: `▶ ${label}` });
    const proc = spawn(PYTHON_CMD, [BRIDGE_SCRIPT, ...args, '--verbose'], {
      cwd: ROOT,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });

    proc.stdout.on('data', data => {
      const text = data.toString();
      text.split('\n').filter(l => l.trim()).forEach(line => {
        if (line.includes('✓') || line.includes('完成')) emitSSE(res, 'progress', { message: line.trim() });
        else if (line.includes('⚠') || line.includes('❌')) emitSSE(res, 'warn', { message: line.trim() });
        else if (line.trim()) emitSSE(res, 'log', { message: line.trim() });
      });
    });

    proc.stderr.on('data', data => {
      const text = data.toString().trim();
      if (text && !text.includes('Loading weights')) emitSSE(res, 'log', { message: text });
    });

    proc.on('close', code => resolve(code === 0));
    proc.on('error', err => { emitSSE(res, 'error', { message: err.message }); resolve(false); });
  });
}

app.post('/api/pipeline/run', async (req, res) => {
  // 防重入: 管线已在运行中
  if (_pipelineRunning) {
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
    emitSSE(res, 'warn', { message: '管线正在运行中, 请等待完成后再试' });
    emitSSE(res, 'done', { job_id: 'rejected', success: false });
    return res.end();
  }
  _pipelineRunning = true;

  const jobId = createJobId();
  const job = { id: jobId, mode: 'pipeline', startTime: new Date().toISOString(), status: 'running' };
  activeJobs.set(jobId, job);

  res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive' });
  emitSSE(res, 'start', { job_id: jobId });

  try {
    // 1. 获取数据集导出
      emitSSE(res, 'log', { message: '准备数据集...' });
      const exports = await getDatasetExports();

      if (exports.error) {
        emitSSE(res, 'warn', { message: exports.error });
        emitSSE(res, 'done', { job_id: jobId, success: true, message: 'no pending entries' });
        return;
      }

      emitSSE(res, 'log', { message: `待处理: ${exports.pending_replay} 回填 + ${exports.pending_text} 文本` });

      let allOk = true;

      // 2. 处理回填条目 (实时流式)
      if (exports.replay_csv) {
        emitSSE(res, 'progress', { message: `--- 回填管线 (${exports.pending_replay}条) ---` });
        const ok = await streamBridgeProcess(res, ['--replay', exports.replay_csv], `Mode B: 回填 ${exports.pending_replay} 条`);
        if (!ok) { emitSSE(res, 'warn', { message: '回填管线部分失败' }); allOk = false; }
        emitSSE(res, 'progress', { message: '回填管线完成 ✓' });
      }

      // 3. 处理文本条目 (实时流式)
      if (exports.text_csv) {
        emitSSE(res, 'progress', { message: `--- 文本管线 (${exports.pending_text}条, LIGHT模式) ---` });
        const ok = await streamBridgeProcess(res, ['--input', exports.text_csv, '--mode', 'light'], `Mode A: 文本分析 ${exports.pending_text} 条`);
        if (!ok) { emitSSE(res, 'warn', { message: '文本管线部分失败' }); allOk = false; }
        emitSSE(res, 'progress', { message: '文本管线完成 ✓' });
      }

      // 4. 标记已处理 + 更新统计
      emitSSE(res, 'log', { message: '更新数据集状态...' });
      const stats = await markDatasetProcessed(exports.pending_ids);

      job.status = allOk ? 'completed' : 'failed';
      job.endTime = new Date().toISOString();

      emitSSE(res, 'done', {
        job_id: jobId,
        success: allOk,
        trajectory_rows: stats.rows || 0,
        edm_ready: stats.edm_ready || false,
      });

  } catch (e) {
    job.status = 'error';
    emitSSE(res, 'error', { message: e.message });
  } finally {
    _pipelineRunning = false;
    activeJobs.delete(jobId);
    res.end();
  }
});

// ── API: 模型配置 ─────────────────────────────────────────

app.get('/api/models', async (_req, res) => {
  try {
    const script = "import sys, json; sys.path.insert(0, '.'); from layer3_sacred import list_models, get_active_model; print(json.dumps({'models': list_models(), 'active': get_active_model()}, ensure_ascii=False))";
    const result = await pyScript(script, 30000);
    try { res.json(JSON.parse(result.out)); } catch { res.json({ error: result.out }); }
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/models/activate', async (req, res) => {
  const { model } = req.body;
  if (!model) return res.status(400).json({ error: 'model key required' });

  // 元审计 P1 修缮: Python 注入防护
  // 之前用字符串拼接 + replace(/'/g, '') 不够健壮
  // 现采用白名单校验 + JSON 参数传递，彻底消除注入
  const ALLOWED_MODELS = ['qwen2.5-1.5b', 'qwen2.5-3b'];
  if (!ALLOWED_MODELS.includes(model)) {
    return res.status(400).json({
      error: `invalid model key: ${model}`,
      allowed: ALLOWED_MODELS,
    });
  }

  try {
    // 用 JSON 序列化传递参数，避免任何字符串拼接
    const modelJson = JSON.stringify(model);
    const script = `import sys, json; sys.path.insert(0, '.'); from layer3_sacred import set_active_model, get_active_model; ok = set_active_model(json.loads('${modelJson}')); print(json.dumps({'success': ok, 'active': get_active_model()}, ensure_ascii=False))`;
    const result = await pyScript(script, 15000);
    try { res.json(JSON.parse(result.out)); } catch { res.json({ success: false }); }
  } catch (e) { res.status(500).json({ error: e.message }); }
});


// ── API: 项目管理 ─────────────────────────────────────────

app.get('/api/projects', async (_req, res) => {
  try {
    const result = await pyCall(['--list-projects']);
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post('/api/projects', async (req, res) => {
  const { name, description } = req.body;
  if (!name) return res.status(400).json({ error: 'name required' });
  try {
    const result = await pyCall(['--create-project', name]);
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.put('/api/projects/activate', async (req, res) => {
  const { name } = req.body;
  if (!name) return res.status(400).json({ error: 'name required' });
  try {
    const result = await pyCall(['--project', name]);
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.delete('/api/projects/:name', async (req, res) => {
  try {
    const result = await pyCall(['--delete-project', req.params.name]);
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ── API: 工作目录扫描 ─────────────────────────────────────

app.get('/api/work-scan', async (_req, res) => {
  try {
    const result = await pyCall(['--scan-work']);
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.delete('/api/work-uuid/:uuid', async (req, res) => {
  // P1 修复: UUID 格式校验，防止注入
  const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (!UUID_RE.test(req.params.uuid)) {
    return res.status(400).json({ error: 'INVALID_UUID', detail: 'UUID format required' });
  }
  try {
    const script = `
import sys, json; sys.path.insert(0, '.')
from work_scanner import WorkScanner
ws = WorkScanner()
result = ws.delete_uuids(['${req.params.uuid}'], dry_run=False)
print(json.dumps(result, ensure_ascii=False))
    `.trim();
    const proc = spawn(PYTHON_CMD, ['-c', script], {
      cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 10000,
    });
    let out = '';
    proc.stdout.on('data', d => out += d.toString());
    proc.on('close', () => { try { res.json(JSON.parse(out)); } catch { res.json({ raw: out }); } });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/work-clean', async (req, res) => {
  const dryRun = req.body.dry_run !== false;
  const orphansOnly = req.body.orphans_only === true;
  try {
    const script = `
import sys, json
sys.path.insert(0, '.')
from work_scanner import WorkScanner
ws = WorkScanner()
result = ws.delete_invalid(dry_run=${dryRun}) if not ${orphansOnly} else ws.delete_orphans(dry_run=${dryRun})
print(json.dumps(result, ensure_ascii=False))
    `.trim();
    const { out } = await pyScript(script, 15000);
    try { res.json(JSON.parse(out)); } catch { res.json({ raw: out.trim() }); }
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ── API: 选定 UUID 回填到当前项目 ─────────────────────────

app.post('/api/replay-uuids', async (req, res) => {
  const { uuids } = req.body;
  if (!uuids || !uuids.length) return res.status(400).json({ error: 'uuids required' });

  const jobId = createJobId();
  const tmpCsv = path.join(ROOT, 'data', 'outputs', `_replay_selected_${jobId}.csv`);
  const uuidsFile = path.join(ROOT, 'data', 'outputs', `_uuids_${jobId}.json`);

  try {
    // 将 UUID 写入临时 JSON 文件 (避免命令行参数注入)
    fs.writeFileSync(uuidsFile, JSON.stringify(uuids));

    const { out, err: setupErr } = await pyScript(`
import sys, json; sys.path.insert(0, '.')
from work_scanner import WorkScanner
from pathlib import Path
ws = WorkScanner()
with open('${uuidsFile.replace(/\\/g, '\\\\')}', 'r', encoding='utf-8') as f:
    uuids = json.load(f)
count = ws.export_replay_csv(uuids, Path('${tmpCsv.replace(/\\/g, '\\\\')}'))
print(json.dumps({"count": count}))
    `.trim(), 15000);

    if (!fs.existsSync(tmpCsv)) {
      return res.status(500).json({ error: 'Failed to create replay CSV', detail: setupErr });
    }

    // 直接 spawn bridge.py (实时 SSE)
    const args = [BRIDGE_SCRIPT, '--replay', tmpCsv, '--verbose'];
    const proc = spawn(PYTHON_CMD, args, { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });

    const job = { id: jobId, mode: 'replay-uuids', startTime: new Date().toISOString(), status: 'running' };
    activeJobs.set(jobId, { ...job, process: proc });

    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive' });
    emitSSE(res, 'start', { job_id: jobId, mode: 'replay-uuids', count: uuids.length });

    proc.stdout.on('data', data => {
      const text = data.toString();
      text.trim().split('\n').filter(l => l.trim()).forEach(line => {
        if (line.includes('✓') || line.includes('完成')) emitSSE(res, 'progress', { message: line.trim() });
        else if (line.includes('⚠') || line.includes('❌')) emitSSE(res, 'warn', { message: line.trim() });
        else emitSSE(res, 'log', { message: line.trim() });
      });
    });

    proc.stderr.on('data', data => { const t = data.toString().trim(); if (t) emitSSE(res, 'log', { message: t }); });

    proc.on('close', code => {
      job.status = code === 0 ? 'completed' : 'failed';
      job.endTime = new Date().toISOString();
      activeJobs.delete(jobId);
      jobHistory.unshift({ id: jobId, status: job.status, mode: job.mode, startTime: job.startTime });
      if (jobHistory.length > 50) jobHistory.pop();
      emitSSE(res, 'done', { job_id: jobId, success: code === 0 });
      res.end();
      try { fs.unlinkSync(tmpCsv); fs.unlinkSync(uuidsFile); } catch {}
    });

    proc.on('error', err => {
      job.status = 'error'; activeJobs.delete(jobId);
      emitSSE(res, 'error', { message: err.message }); res.end();
      try { fs.unlinkSync(tmpCsv); fs.unlinkSync(uuidsFile); } catch {}
    });

  } catch (e) {
    res.status(500).json({ error: e.message });
    try { fs.unlinkSync(uuidsFile); } catch {}
  }
});

// ── 启动 ──────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log('');
  console.log('╔══════════════════════════════════════════════════╗');
  console.log('║   trace-to-edm Web 操纵台 v0.1.0                ║');
  console.log('║   元因果控制论桥接系统 — 可视化面板               ║');
  console.log(`║   http://localhost:${PORT}                          ║`);
  console.log('╠══════════════════════════════════════════════════╣');
  console.log('║   Mode A: 文本管线  POST /api/run               ║');
  console.log('║   Mode B: 回填管线  POST /api/replay            ║');
  console.log('║   EDM 触发         POST /api/edm/trigger        ║');
  console.log('║   轨迹查询         GET  /api/trajectory          ║');
  console.log('╚══════════════════════════════════════════════════╝');
  console.log('');
});
