/**
 * trace-to-edm Web 操纵台 — Node.js 服务端
 * ==========================================
 * Express + SSE 的轻量 Web 面板，驱动三层桥接系统的 Python 后端。
 *
 * 架构:
 *   Browser ←→ Express (port 3100) ←→ Python bridge.py (child_process)
 *
 * 端点 (共 33 个 API 端点 + 静态前端 /，详见 README.md §API 端点表):
 *   GET  /                 前端面板 (express.static, 不计入 33)
 *   GET  /api/health       L0  健康检查
 *   GET  /api/version      L0  版本查询 (debt-12.13: 从 package.json 读取)
 *   GET  /api/status       L1  轨迹状态 + EDM 就绪度
 *   POST /api/run          L3  提交文本管线任务 (Mode A, SSE)
 *   POST /api/replay       L3  提交回填任务 (Mode B, SSE；replay_all=true 复用此端点)
 *   GET  /api/edm/poll/:id L3  EDM轮询代理（避免CORS — P2修复）
 *   POST /api/edm/trigger  L3  触发 EDM 分析
 *   GET  /api/jobs         L4  任务历史
 *   …其余 25 个端点（dataset/projects/work/models 等）见 README.md 表
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
// P1修复: 默认 CORS 限制为本地回环，避免生产环境通配符风险 (原默认 '*')
// debt-12.15 隧道支持: 自动读取 tunnel_url.txt，把 trycloudflare 域名加入白名单
function _loadTunnelOrigins() {
  try {
    const tunnelFile = path.join(ROOT, 'tunnel_url.txt');
    if (fs.existsSync(tunnelFile)) {
      const url = fs.readFileSync(tunnelFile, 'utf-8').trim();
      if (url && url.includes('trycloudflare.com')) return [url];
    }
  } catch (e) { /* 静默降级 */ }
  return [];
}
// ENG-05 修复: CORS_ORIGIN 默认值与实际绑定地址 (127.0.0.1:3100) 对齐
// 原默认 'http://localhost:3100' 与 HOST='127.0.0.1' 不一致，可能导致预检请求 Origin 不匹配
const CORS_ORIGIN = process.env.TRACE_CORS_ORIGIN || 'http://127.0.0.1:3100';
// CORS 白名单: 环境变量 + 默认 localhost + 隧道域名
const CORS_ALLOWED_ORIGINS = [
  CORS_ORIGIN,
  'http://127.0.0.1:3100',
  'http://localhost:3100',
  ..._loadTunnelOrigins(),
];
// debt-12.13: 版本号从 package.json 读取，避免硬编码与实际版本漂移
const PACKAGE_VERSION = (() => {
  try {
    return require('./package.json').version || '0.0.0-dev';
  } catch (e) {
    console.error(`[trace-to-edm] 读取 package.json 版本失败: ${e.message}，回退到 'unknown'`);
    return 'unknown';
  }
})();

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
// debt-12.13 修缮: 当 stdout 不是合法 JSON 时，原先仅依据 exit code 判定
// success，会掩盖 Python 进程崩溃但 exit code=0 的场景（例如 Python 未捕获
// 异常被 sys.exit(0) 调用吞掉，或 stdout 被第三方日志污染）。
// 修复策略: success 必须同时满足 (a) JSON 解析成功且字段 success=true，或
// (b) JSON 解析失败但 exit code=0 且 stderr 为空。其余情况一律视为失败。
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
      const trimmedOut = out.trim();
      const trimmedErr = err.trim();
      // 尝试 JSON 解析
      if (trimmedOut) {
        try {
          const parsed = JSON.parse(trimmedOut);
          // 若 Python 输出了显式 success 字段，尊重该字段
          if (parsed && typeof parsed === 'object' && 'success' in parsed) {
            resolve(parsed);
            return;
          }
          // 数组是合法的无 success 字段输出（如 --list-projects 输出项目数组），
          // 原样返回，避免被 {...parsed} 展开为 {0: {...}, 1: {...}} 的畸形对象。
          // 回归修复 (debt-12.14): 上次 pyCall 修缮未覆盖数组输出路径，
          // 导致 /api/projects 下拉为空（前端 Array.isArray 检查失败）。
          if (Array.isArray(parsed)) {
            resolve(parsed);
            return;
          }
          // JSON 解析成功但无 success 字段: 仅当 exit code=0 且无 stderr 时才视为成功
          resolve({
            success: code === 0 && !trimmedErr,
            ...parsed,
            _warning: 'JSON 无显式 success 字段，依据 exit code 与 stderr 推断',
            exit_code: code,
            stderr: trimmedErr,
          });
          return;
        } catch (e) {
          // JSON 解析失败，进入下方 fallback
        }
      }
      // Fallback: stdout 不是 JSON。success 必须同时满足 exit code=0 且 stderr 为空。
      // 若 exit code!=0 或 stderr 非空，即使 exit code=0 也视为失败（stderr 表明 Python 报错）。
      resolve({
        success: code === 0 && !trimmedErr && !trimmedOut,
        output: trimmedOut,
        error: trimmedErr || (code !== 0 ? `Python 退出码非零: ${code}` : ''),
        exit_code: code,
      });
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

// ROUND28 P1-02: 错误响应辅助函数 — 生产模式不泄露内部细节
// 统一所有 catch 块的错误返回, 避免 e.message 直接暴露给客户端
const IS_PROD = process.env.NODE_ENV === 'production';
function errorResponse(e, defaultMessage = 'Internal Server Error') {
  console.error('[Server] 路由错误:', e);
  return { error: IS_PROD ? defaultMessage : (e.message || defaultMessage) };
}

// ── Express 初始化 ────────────────────────────────────────
const app = express();
// ROUND28 P1-06: body limit 收窄 20mb → 2mb, 防止 DoS 攻击面
// (如需大批量 CSV 上传, 应走分端点或分片上传)
// P1 修缮（2026-08-03）: 恢复 20mb 与 trace-engine-web 对齐。
// 原版 2mb 导致长文本（如完整新闻文章、哲学文本）触发 413/500。
// 2mb ≈ 100万字符中文，但 sacred_texts/ 中的文本可达 5mb+。
// DoS 防护通过 auth 中间件 + 限流 + 输入校验实现，不依赖 body limit。
app.use(express.json({ limit: '20mb' }));
app.use(express.urlencoded({ extended: true, limit: '20mb' }));
app.use(express.static(PUBLIC_DIR));

// ROUND28 P1-01: 安全 HTTP 头 (手动设置, 避免 helmet 依赖)
// 对齐 trace-engine-web / edm-takens-web 的 CSP 修缮标准
app.use((req, res, next) => {
  // CSP: script-src 'self' (移除 unsafe-inline, 与 base_nav.js 抽取对齐)
  res.header('Content-Security-Policy',
    "default-src 'self'; " +
    "script-src 'self'; " +
    "style-src 'self' 'unsafe-inline'; " +
    "img-src 'self' data: blob:; " +
    "connect-src 'self' http://127.0.0.1:* http://localhost:*; " +
    "font-src 'self' data:; " +
    "object-src 'none'; " +
    "base-uri 'self'; " +
    "frame-ancestors 'none'"
  );
  res.header('X-Content-Type-Options', 'nosniff');
  res.header('X-Frame-Options', 'DENY');
  res.header('Referrer-Policy', 'strict-origin-when-cross-origin');
  res.header('X-XSS-Protection', '1; mode=block');
  // HSTS: 仅 HTTPS 时生效
  if (req.secure || req.headers['x-forwarded-proto'] === 'https') {
    res.header('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  }
  next();
});

// 全局错误处理: 捕获 body-parser PayloadTooLargeError 等
app.use((err, _req, res, _next) => {
  if (err && err.type === 'entity.too.large') {
    return res.status(413).json({ error: 'payload too large' });
  }
  if (err) {
    // ROUND28 P1-02: 生产模式不泄露内部错误细节
    console.error('[Server] 全局错误:', err);
    const isDev = process.env.NODE_ENV !== 'production';
    return res.status(500).json({
      error: isDev ? (err.message || 'internal error') : 'Internal Server Error'
    });
  }
  _next();
});

// CORS: 白名单模式（localhost + 隧道域名），生产通过 TRACE_CORS_ORIGIN 收窄
// debt-12.15: 支持隧道域名自动放行，避免混合内容/CORS 阻断
app.use((req, res, next) => {
  const reqOrigin = req.headers['origin'];
  if (reqOrigin && CORS_ALLOWED_ORIGINS.includes(reqOrigin)) {
    res.header('Access-Control-Allow-Origin', reqOrigin);
    res.header('Vary', 'Origin');
  } else if (reqOrigin && /https:\/\/[a-z0-9-]+\.trycloudflare\.com/.test(reqOrigin)) {
    // 隧道模式: 允许任意 trycloudflare 隧道域名（quick tunnel 域名随机）
    res.header('Access-Control-Allow-Origin', reqOrigin);
    res.header('Vary', 'Origin');
  }
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Trace-Id');
  res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  next();
});

// P1-b 修缮：所有 /api/ GET 端点禁止浏览器缓存，防止前端获取过期数据
// SSE 端点已在各自的 writeHead 中设置 no-cache，此处覆盖其余 GET 数据端点
// （/api/models、/api/projects、/api/status、/api/trajectory 等）
app.use((req, res, next) => {
  if (req.method === 'GET' && req.path.startsWith('/api/')) {
    res.header('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate');
    res.header('Pragma', 'no-cache');
    res.header('Expires', '0');
  }
  next();
});

// P1-b 修缮：服务端内存缓存（TTL 5s），减少 Python 子进程冷启动开销
// _apiCache = { key: { data, expireAt, mtime? } }
const _apiCache = new Map();
const API_CACHE_TTL_MS = 5000;

function getCached(key) {
  const entry = _apiCache.get(key);
  if (!entry) return null;
  if (Date.now() > entry.expireAt) {
    _apiCache.delete(key);
    return null;
  }
  return entry.data;
}

function setCached(key, data) {
  _apiCache.set(key, { data, expireAt: Date.now() + API_CACHE_TTL_MS });
}

function invalidateCache(key) {
  if (key) {
    _apiCache.delete(key);
  } else {
    _apiCache.clear();
  }
}

// 请求追踪 ID（便于日志串联）
app.use((req, _res, next) => {
  req.traceId = req.headers['x-trace-id'] || crypto.randomBytes(4).toString('hex');
  next();
});

// P1-4: API Key 认证中间件（通过 CROSS_PROJECT_API_KEY 环境变量启用）
// P1-1 修复: 生产模式拒绝静默降级；开发模式回退到内置最小鉴权（环回地址放行）
try {
  const sharedAuth = require('../shared/auth_middleware');
  app.use(sharedAuth.createAuthMiddleware({ excludePaths: ['/api/health'] }));
} catch (_) {
  if (process.env.NODE_ENV === 'production') {
    console.error('[auth] ../shared/auth_middleware not found — refusing to start in production mode');
    process.exit(1);
  }
  console.warn('[auth] ../shared/auth_middleware not found — falling back to loopback-only access');
  // 内置最小鉴权: 仅允许环回地址访问，拒绝外部连接
  app.use((req, res, next) => {
    if (req.path === '/api/health') return next();
    const ip = req.ip || req.connection.remoteAddress;
    if (ip && (ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1')) {
      return next();
    }
    res.status(403).json({ error: 'auth middleware missing, external access denied', code: 'AUTH_FALLBACK' });
  });
}

// 通用输入路径校验（自动处理 body.csv_path）
app.use(validateInputPathMiddleware);

// ROUND29 MCP: 补齐 MCP 协议端点 (JSON-RPC 2.0 over HTTP)
// P0 修缮（2026-08-03）: 原版 MCP 挂载在 auth 之前, 导致 /mcp 完全绕过鉴权。
// 现移至 auth + 输入校验之后, 确保所有 MCP 工具调用都经过 CROSS_PROJECT_API_KEY 鉴权。
const { createMcpRouter } = require('./mcp');
app.use('/mcp', createMcpRouter(PORT));

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
    // ENG-10 修复: 用 /\r?\n/ 分割以兼容 Windows(\r\n) 与 Unix(\n) 行尾
    // 原实现 content.trim().split('\n') 在 Windows CSV 下会保留每行末尾的 \r,
    // 导致最后一列 (d2z_觉爱_zscore) 实际变为 "d2z_觉爱_zscore\r",
    // colLayer 的 endsWith('_zscore') 匹配失败，字段被误分类为 (其他)。
    const lines = content.trim().split(/\r?\n/);
    if (lines.length < 2) return { columns: [], rows: [], total: 0 };

    const parseCSVLine = (line) => {
      const result = [];
      let current = '', inQuotes = false;
      // ENG-10 防御: 兜底剥离行尾 \r (Windows 行尾残留)
      const sanitized = line.replace(/\r$/, '');
      for (const ch of sanitized) {
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

// ── P2 (§20.12): 生成人话版 Markdown 报告 ─────────────────
// 抽离为独立函数, 供 /api/trajectory/export/md 与 /api/trajectory/report 复用,
// 保证浏览器查看报告时总是拿到最新数据, 避免 stale latest.md.
function buildTrajectoryReport() {
  const traj = readTrajectoryCSV();
  const active = Array.from(activeJobs.entries()).map(([id, j]) => ({
    id, mode: j.mode, status: j.status, startTime: j.startTime,
  }));
  const history = jobHistory.slice(0, 20);

  // 当前项目名
  let projectName = 'default';
  try {
    const idxPath = path.join(PROJECTS_DIR, '_index.json');
    if (fs.existsSync(idxPath)) {
      const idx = JSON.parse(fs.readFileSync(idxPath, 'utf-8'));
      projectName = idx.active || 'default';
    }
  } catch (_) { /* ignore */ }

  const edmReady = traj.total >= 15;
  const fmtTs = (iso) => {
    if (!iso) return 'N/A';
    try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }); } catch (_) { return String(iso); }
  };

  // 列分层映射: 为全部 88 列提供层级, 不再出现 '(其他)'
  const colLayer = {
    time_step: 'L0 元信息', text_hash: 'L0 元信息', source_label: 'L0 元信息',
    trace_status: 'L0 元信息', trace_mode: 'L0 元信息', trace_error: 'L0 元信息',
    ate: 'L1 元SCM', adj_density: 'L1 元SCM', max_delta_nll: 'L1 元SCM',
    ci_width: 'L1 元SCM', edge_count: 'L1 元SCM', refuted_count: 'L1 元SCM',
    ccm_coverage_pct: 'L1 元SCM',
    ate_ci_lower: 'L1 元SCM', ate_ci_upper: 'L1 元SCM',
    identifiable: 'L1 元SCM', concept_count: 'L1 元SCM',
    signal_type: 'L1 元SCM', max_delta_nll_concept_level: 'L1 元SCM',
    concept_level_edge_count: 'L1 元SCM', concept_coverage: 'L1 元SCM',
    condition_number: 'L1 元SCM', unk_rate: 'L1 元SCM',
    ccm_verdict: 'L1 元SCM', refutations_attempted: 'L1 元SCM',
    ccm_algorithm_run: 'L1 元SCM',
    edm_rho_high: 'L2 EDM', edm_rho_mid: 'L2 EDM',
    havok_status: 'L2 HAVOK', havok_linear_pct: 'L2 HAVOK',
    causallearn_consensus: 'L2 因果学习', edge_stability_mean: 'L2 稳定性',
    permutation_p_value: 'L2 稳定性', total_ms: 'L0 元信息',
    consensus_score: 'L2 共识', consensus_direction: 'L2 共识',
    z_pca_1: 'L2 PCA', z_pca_2: 'L2 PCA', z_pca_3: 'L2 PCA', secular_entropy: 'L2 PCA',
    z_福音: 'L3 八正道', z_吉祥: 'L3 八正道', z_奥美: 'L3 八正道', z_存在: 'L3 八正道',
    z_自孕: 'L3 八正道', z_弥赛亚: 'L3 八正道', z_Alice: 'L3 八正道', z_觉爱: 'L3 八正道',
    dz_福音: 'L3 一阶差分', dz_吉祥: 'L3 一阶差分', dz_奥美: 'L3 一阶差分',
    dz_存在: 'L3 一阶差分', dz_自孕: 'L3 一阶差分', dz_弥赛亚: 'L3 一阶差分',
    dz_Alice: 'L3 一阶差分', dz_觉爱: 'L3 一阶差分',
    d2z_福音: 'L3 二阶差分', d2z_吉祥: 'L3 二阶差分', d2z_奥美: 'L3 二阶差分',
    d2z_存在: 'L3 二阶差分', d2z_自孕: 'L3 二阶差分', d2z_弥赛亚: 'L3 二阶差分',
    d2z_Alice: 'L3 二阶差分', d2z_觉爱: 'L3 二阶差分',
  };
  // 辅助: 为 zscore 列批量生成层级
  const allColumns = traj.columns || [];
  allColumns.forEach(col => {
    if (col.endsWith('_zscore') && !colLayer[col]) colLayer[col] = 'L3 标准化';
  });

  // 列含义: 为全部 88 列提供人话解释
  const colDesc = {
    time_step: '原始时间戳 — 轨迹行对应的文本事件时间',
    text_hash: '文本哈希 — 输入文本的短指纹, 用于去重与追踪',
    source_label: '来源标签 — 新闻/文本来源标识',
    trace_status: '轨迹状态 — OK/ERROR 表示该条文本是否成功完成因果推断',
    trace_mode: '分析模式 — light/deep/super, 决定计算深度',
    trace_error: '错误信息 — 若处理失败, 记录失败原因',
    ate: '因果效应强度 — ATE 数值, 反映处理→结果的因果关联大小; 负值 = 抑制, 零 = 无线性因果',
    adj_density: '因果图密度 — 系统纠缠度, 越高概念间因果链越密',
    max_delta_nll: '最强因果信号 — ΔNLL 最大值; 值越大非线性因果信号越强',
    ci_width: '因果不确定性 — 置信区间宽度, CI 越宽噪音越大',
    edge_count: '显著因果边数 — 通过统计显著性检验的边',
    refuted_count: '反驳测试被反驳数 — 0 在 light 模式为正常(未运行反驳)',
    ccm_coverage_pct: 'CCM 非线性验证覆盖率 — light 模式为 0(未运行 CCM)',
    ate_ci_lower: 'ATE 置信区间下限 — 因果效应的保守估计',
    ate_ci_upper: 'ATE 置信区间上限 — 因果效应的乐观估计',
    identifiable: '因果效应可识别性 — 1 表示估计量可被识别, 0 表示不可识别',
    concept_count: '识别出的概念数 — 文本中提取的语义概念数量',
    signal_type: '信号类型 — 当前最强因果信号的来源标记',
    max_delta_nll_concept_level: '概念级最强 ΔNLL — 概念粒度下的最强非线性信号',
    concept_level_edge_count: '概念级显著边数 — 概念聚合后的显著因果边',
    concept_coverage: '概念覆盖率 — 文本中被概念词典覆盖的比例',
    condition_number: '设计矩阵条件数 — 数值越大共线性越严重, 估计越不稳定',
    unk_rate: '未知词比例 — 文本中未识别词汇的占比',
    ccm_verdict: 'CCM 裁决 — 非线性验证的定性结论',
    refutations_attempted: '尝试的反驳测试数 — 0 表示 light 模式未运行',
    ccm_algorithm_run: 'CCM 算法是否执行 — 1 表示运行, 0 表示未运行',
    edm_rho_high: 'EDM 高嵌入维 ρ — 高维下的预测相关系数',
    edm_rho_mid: 'EDM 中嵌入维 ρ — 中等维度的预测相关系数',
    havok_status: 'HAVOK 分析状态 — 线性动力学分解是否成功',
    havok_linear_pct: 'HAVOK 线性占比 — 系统动力学中可线性解释的比例',
    causallearn_consensus: 'CausalLearn 共识 — 多种算法对因果方向的一致性投票',
    edge_stability_mean: '因果边稳定性均值 — 自助法下边强度的稳定程度',
    permutation_p_value: '置换检验 p 值 — 因果结构的统计显著性',
    total_ms: '总耗时(毫秒) — 该条文本的处理时间',
    consensus_score: '因果方向共识分 — 方向一致性的定量分数',
    consensus_direction: '共识方向 — positive/negative/ambiguous',
    z_pca_1: '世俗 PCA 第 1 主轴 — 经济/物质维度投影',
    z_pca_2: '世俗 PCA 第 2 主轴 — 社会/权力维度投影',
    z_pca_3: '世俗 PCA 第 3 主轴 — 技术/工具维度投影',
    secular_entropy: '世俗熵 — 话语多样性, 越高词汇/主题越分散',
    z_福音: '福音 (祂志书) 投影 — 信仰维度',
    z_吉祥: '吉祥 (赐福书) 投影 — 祝福维度',
    z_奥美: '奥美 (圣源书) 投影 — 美学维度',
    z_存在: '存在 (真实书) 投影 — 本体论距离, 越大越"超验"',
    z_自孕: '自孕 (胜育书) 投影 — 生命维度',
    z_弥赛亚: '弥赛亚 (至意书) 投影 — 救赎维度',
    z_Alice: 'Alice (慧辩书) 投影 — 逻辑维度',
    z_觉爱: '觉爱 (智识书) 投影 — 智慧维度',
    dz_福音: '福音轴一阶差分 Δz/Δt — 首行为空(因差分需至少2个点)',
    dz_吉祥: '吉祥轴一阶差分 Δz/Δt — 突变速率; 正 = 上升, 负 = 下降',
    dz_奥美: '奥美轴一阶差分 Δz/Δt',
    dz_存在: '存在轴一阶差分 Δz/Δt — 突变速率; 正 = 上升, 负 = 下降',
    dz_自孕: '自孕轴一阶差分 Δz/Δt',
    dz_弥赛亚: '弥赛亚轴一阶差分 Δz/Δt',
    dz_Alice: 'Alice轴一阶差分 Δz/Δt',
    dz_觉爱: '觉爱轴一阶差分 Δz/Δt — 智慧突变速率',
    d2z_福音: '福音轴二阶差分 Δ²z/Δt² — 首两行空(二阶差分需至少3个点)',
    d2z_吉祥: '吉祥轴二阶差分 Δ²z/Δt² — 加速度; 正 = 加速上升, 负 = 减速/转向',
    d2z_奥美: '奥美轴二阶差分 Δ²z/Δt²',
    d2z_存在: '存在轴二阶差分 Δ²z/Δt²',
    d2z_自孕: '自孕轴二阶差分 Δ²z/Δt²',
    d2z_弥赛亚: '弥赛亚轴二阶差分 Δ²z/Δt²',
    d2z_Alice: 'Alice轴二阶差分 Δ²z/Δt²',
    d2z_觉爱: '觉爱轴二阶差分 Δ²z/Δt²',
  };
  // 辅助: 为 zscore 列批量生成含义
  allColumns.forEach(col => {
    if (col.endsWith('_zscore') && !colDesc[col]) {
      const base = col.slice(0, -7);
      colDesc[col] = `${base} 的标准分数 — 该时刻值偏离其历史均值的标准差倍数`;
    }
  });

  const lines = [];
  lines.push(`# TRACE-TO-EDM 桥接报告: 项目 \`${projectName}\`\n`);
  lines.push(`> 自动生成 — 面向非技术读者的人话版解读. 报告基于轨迹 CSV + 任务历史.\n`);
  lines.push('');

  // 1. 概览
  lines.push('## 1. 概览\n');
  lines.push(`- **当前项目**: \`${projectName}\``);
  lines.push(`- **轨迹文件**: \`${traj.path || 'N/A'}\``);
  lines.push(`- **轨迹行数**: ${traj.total}`);
  lines.push(`- **轨迹列数**: ${traj.columns.length}`);
  lines.push(`- **EDM 就绪**: ${edmReady ? '✓ 是 (≥15 行, 可触发 EDM 分析)' : '✗ 否 (<15 行, 需更多数据)'}`);
  lines.push(`- **生成时间**: ${fmtTs(new Date().toISOString())}`);
  lines.push(`- **活动任务**: ${active.length}`);
  lines.push(`- **历史任务**: ${history.length} 条 (最近)`);
  lines.push('');

  // 2. 关键指标统计
  const numericStats = {};
  if (traj.rows.length > 0) {
    traj.columns.forEach(col => {
      const vals = traj.rows.map(r => parseFloat(r[col])).filter(v => !isNaN(v));
      if (vals.length === 0) return;
      const min = Math.min(...vals);
      const max = Math.max(...vals);
      const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
      const half = Math.floor(vals.length / 2);
      const firstHalf = vals.slice(0, half).reduce((a, b) => a + b, 0) / Math.max(half, 1);
      const secondHalf = vals.slice(half).reduce((a, b) => a + b, 0) / Math.max(vals.length - half, 1);
      const delta = secondHalf - firstHalf;
      const trend = Math.abs(delta) < Math.abs(mean) * 0.05
        ? '→ 平稳'
        : (delta > 0 ? '↗ 上升' : '↘ 下降');
      numericStats[col] = { min, max, mean, trend };
    });
  }

  lines.push('## 2. 指标详解 + 统计 + 趋势\n');
  if (traj.columns.length > 0) {
    lines.push('| 列名 | 层级 | 含义 | 最小 | 最大 | 均值 | 趋势 |');
    lines.push('|------|------|------|------|------|------|------|');
    const fmt = (v) => (Math.abs(v) >= 1000 ? v.toFixed(1) : v.toFixed(3));
    traj.columns.forEach(col => {
      const layer = colLayer[col] || '(其他)';
      const desc = colDesc[col] || '—';
      const st = numericStats[col];
      if (st) {
        lines.push(`| \`${col}\` | ${layer} | ${desc} | ${fmt(st.min)} | ${fmt(st.max)} | ${fmt(st.mean)} | ${st.trend} |`);
      } else {
        lines.push(`| \`${col}\` | ${layer} | ${desc} | — | — | — | — |`);
      }
    });
    lines.push('');
    lines.push('> **解读**: 趋势 = 后半段均值 vs 前半段均值. '
      + '↗/↘ 幅度 > 5% 均值才算"上升/下降", 否则视为"平稳". '
      + '空值 — 表示该列无非数值内容(如 trace_error).\n');
  } else {
    lines.push('- 轨迹文件为空或不存在.\n');
  }

  // 3. 数学正确性说明: 解释零值与负数
  lines.push('## 3. 关于零值与负数的数学说明\n');
  lines.push('- **ATE 为 0**: 在 LIGHT 模式下, 若文本过短或无可识别因果结构, OLS 估计会退化为 0. 这不代表算法错误, 而是"无显著线性因果"的统计结果.');
  lines.push('- **ATE 为负**: 表示"处理变量增加 → 结果变量减少"的抑制关系, 是因果效应的正常取值范围.');
  lines.push('- **refuted_count = 0**: LIGHT 模式不运行反驳测试, 故恒为 0; DEEP/SUPER 模式才会产生非零值.');
  lines.push('- **ccm_coverage_pct = 0**: LIGHT 模式不运行 CCM 非线性验证, 故恒为 0.');
  lines.push('- **dz_/d2z_ 首行空**: 一阶差分需要至少 2 个连续点, 二阶差分需要至少 3 个连续点, 因此首行/首两行无定义(显示为 —).');
  lines.push('- **z_pca / z_八正道 为负**: 投影以均值为 0 进行标准化, 负值表示"低于该维度的平均水平", 完全正常.');
  lines.push('- **zscore 为负/正**: 标准分数, 0 为均值, ±1 为一个标准差, 负值表示低于历史均值.');
  lines.push('');

  // 4. 轨迹数据预览
  lines.push('## 4. 轨迹数据预览 (Top 15)\n');
  if (traj.rows.length > 0) {
    const previewCols = traj.columns.slice(0, 8);  // 限制前 8 列
    lines.push('| # | ' + previewCols.map(c => `\`${c}\``).join(' | ') + ' |');
    lines.push('|---|' + previewCols.map(() => '------').join('|') + '|');
    traj.rows.slice(0, 15).forEach((row, i) => {
      const vals = previewCols.map(c => {
        const v = row[c] || '';
        const num = parseFloat(v);
        if (!isNaN(num) && v !== '') {
          return Math.abs(num) >= 1000 ? num.toFixed(1) : num.toFixed(3);
        }
        return String(v).slice(0, 20);
      });
      lines.push(`| ${i + 1} | ${vals.join(' | ')} |`);
    });
    if (traj.rows.length > 15) {
      lines.push('');
      lines.push(`_...共 ${traj.total} 行, 此处仅展示前 15 行._`);
    }
    lines.push('');
  } else {
    lines.push('- 轨迹为空.\n');
  }

  // 5. 任务历史
  lines.push('## 5. 任务历史 (最近 20 条)\n');
  if (history.length > 0) {
    lines.push('| # | 任务 ID | 模式 | 状态 | 开始时间 |');
    lines.push('|---|---------|------|------|----------|');
    history.forEach((j, i) => {
      const status = j.status === 'completed' ? '✓ 完成' : (j.status === 'failed' ? '✗ 失败' : j.status);
      lines.push(`| ${i + 1} | \`${j.id}\` | ${j.mode || '?'} | ${status} | ${fmtTs(j.startTime)} |`);
    });
    lines.push('');
  } else {
    lines.push('- 无任务历史.\n');
  }

  // 6. 总结
  lines.push('## 6. 一句话总结\n');
  const parts = [];
  if (traj.total > 0) parts.push(`已采集 ${traj.total} 条轨迹`);
  if (edmReady) parts.push('EDM 可触发');
  else parts.push(`需 ${Math.max(0, 15 - traj.total)} 条更多数据才能触发 EDM`);
  if (history.length > 0) {
    const completed = history.filter(j => j.status === 'completed').length;
    parts.push(`历史任务 ${completed}/${history.length} 完成`);
  }
  lines.push('**' + parts.join('; ') + '.**');
  lines.push('');
  lines.push('---');
  lines.push(`_报告由 trace-to-edm Web 自动生成于 ${fmtTs(new Date().toISOString())}._`);

  const mdContent = lines.join('\n');

  // 写入项目 reports/ 目录, 方便用户在文件系统中直接查阅
  const reportsDir = path.join(PROJECTS_DIR, projectName, 'reports');
  fs.mkdirSync(reportsDir, { recursive: true });
  fs.writeFileSync(path.join(reportsDir, 'latest.md'), mdContent, 'utf-8');

  return {
    mdContent,
    htmlContent: null, // 由 buildTrajectoryReportHTML() 按需生成
    projectName,
    generated: new Date().toISOString(),
    traj,
    numericStats,
    colLayer,
    colDesc,
    edmReady,
    active,
    history,
  };
}

// ── P2 (§20.12): 生成人话版 HTML 报告 ─────────────────────
// 暗色主题、可折叠卡片、按层级分组，减少 88 列大表的压迫感。
function buildTrajectoryReportHTML(baseReport) {
  const {
    projectName, generated, traj, numericStats, colLayer, colDesc, edmReady, active, history,
  } = baseReport;
  const fmtTs = (iso) => {
    if (!iso) return 'N/A';
    try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }); } catch (_) { return String(iso); }
  };
  const fmt = (v) => {
    if (v === undefined || v === null || Number.isNaN(v)) return '—';
    return Math.abs(v) >= 1000 ? v.toFixed(1) : v.toFixed(3);
  };

  // 按层级分组列
  const layers = {};
  traj.columns.forEach((col) => {
    const layer = colLayer[col] || '其他';
    if (!layers[layer]) layers[layer] = [];
    layers[layer].push(col);
  });
  const layerOrder = [
    'L0 元信息',
    'L1 元SCM',
    'L2 EDM',
    'L2 HAVOK',
    'L2 因果学习',
    'L2 稳定性',
    'L2 共识',
    'L2 PCA',
    'L3 八正道',
    'L3 一阶差分',
    'L3 二阶差分',
    'L3 标准化',
    '其他',
  ];

  // 内联数学/语义说明
  function inlineNote(col, st) {
    const notes = [];
    if (col === 'ate' && st) {
      if (Math.abs(st.mean) < 0.001) notes.push('均值接近 0：可能为 LIGHT 模式无线性因果或文本过短。');
      if (st.min < 0) notes.push('负值 = 抑制关系，属正常取值范围。');
    }
    if (col === 'refuted_count' || col === 'refutations_attempted') {
      notes.push('LIGHT 模式不运行反驳测试，0 为正常。');
    }
    if (col === 'ccm_coverage_pct' || col === 'ccm_algorithm_run') {
      notes.push('LIGHT 模式不运行 CCM 非线性验证，0 为正常。');
    }
    if (col.startsWith('dz_')) {
      notes.push('首行空：一阶差分需至少 2 个连续点。');
    }
    if (col.startsWith('d2z_')) {
      notes.push('首两行空：二阶差分需至少 3 个连续点。');
    }
    if ((col.startsWith('z_pca_') || col.startsWith('z_') || col.endsWith('_zscore')) && st && st.min < 0) {
      notes.push('负值表示低于该维度历史/平均水平，完全正常。');
    }
    if (!notes.length) return '';
    return `<span class="metric-note">${notes.join(' ')}</span>`;
  }

  function renderLayerCard(layerName, cols) {
    const rows = cols.map((col) => {
      const st = numericStats[col];
      const desc = colDesc[col] || '—';
      const trendBadge = st
        ? `<span class="trend ${st.trend.includes('上升') ? 'up' : (st.trend.includes('下降') ? 'down' : 'flat')}">${st.trend}</span>`
        : '<span class="trend flat">—</span>';
      const stats = st
        ? `<span class="stat">最小 ${fmt(st.min)}</span><span class="stat">最大 ${fmt(st.max)}</span><span class="stat">均值 ${fmt(st.mean)}</span>`
        : '<span class="stat dim">非数值列</span>';
      return `<div class="metric-row">
        <div class="metric-head">
          <code class="metric-name">${col}</code>
          <span class="metric-desc">${desc}</span>
          ${trendBadge}
        </div>
        <div class="metric-body">
          ${stats}
          ${inlineNote(col, st)}
        </div>
      </div>`;
    }).join('');
    const open = layerName.startsWith('L0') || layerName.startsWith('L1') ? 'open' : '';
    return `<details class="layer-card" ${open}>
      <summary><span class="layer-name">${layerName}</span><span class="layer-count">${cols.length} 项</span></summary>
      <div class="layer-body">${rows}</div>
    </details>`;
  }

  const layerCards = layerOrder
    .filter((l) => layers[l] && layers[l].length)
    .map((l) => renderLayerCard(l, layers[l]))
    .join('');

  // 数据预览（前 8 列，前 15 行）
  let previewTable = '<p class="dim">轨迹为空。</p>';
  if (traj.rows.length > 0) {
    const previewCols = traj.columns.slice(0, 8);
    const head = previewCols.map((c) => `<th><code>${c}</code></th>`).join('');
    const body = traj.rows.slice(0, 15).map((row, i) => {
      const cells = previewCols.map((c) => {
        const v = row[c] || '';
        const num = parseFloat(v);
        const display = (!isNaN(num) && v !== '') ? fmt(num) : String(v).slice(0, 20);
        return `<td>${display}</td>`;
      }).join('');
      return `<tr><td class="row-idx">${i + 1}</td>${cells}</tr>`;
    }).join('');
    const more = traj.rows.length > 15 ? `<p class="dim">…共 ${traj.total} 行，仅展示前 15 行</p>` : '';
    previewTable = `<div class="table-wrap"><table class="preview-table"><thead><tr><th>#</th>${head}</tr></thead><tbody>${body}</tbody></table></div>${more}`;
  }

  // 任务历史
  let historyHtml = '<p class="dim">无任务历史。</p>';
  if (history.length > 0) {
    historyHtml = `<div class="table-wrap"><table class="history-table">
      <thead><tr><th>#</th><th>任务 ID</th><th>模式</th><th>状态</th><th>开始时间</th></tr></thead>
      <tbody>${history.map((j, i) => {
    const statusClass = j.status === 'completed' ? 'ok' : (j.status === 'failed' ? 'err' : 'warn');
    const statusText = j.status === 'completed' ? '✓ 完成' : (j.status === 'failed' ? '✗ 失败' : j.status);
    return `<tr><td class="row-idx">${i + 1}</td><td><code>${j.id}</code></td><td>${j.mode || '?'}</td><td class="${statusClass}">${statusText}</td><td>${fmtTs(j.startTime)}</td></tr>`;
  }).join('')}</tbody>
    </table></div>`;
  }

  // 总结
  const parts = [];
  if (traj.total > 0) parts.push(`已采集 ${traj.total} 条轨迹`);
  if (edmReady) parts.push('EDM 可触发');
  else parts.push(`需 ${Math.max(0, 15 - traj.total)} 条更多数据才能触发 EDM`);
  if (history.length > 0) {
    const completed = history.filter((j) => j.status === 'completed').length;
    parts.push(`历史任务 ${completed}/${history.length} 完成`);
  }
  const summary = parts.join('；') + '。';

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TRACE-TO-EDM 桥接报告 — ${projectName}</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #020408;
      --bg-elevated: #05080f;
      --panel: rgba(8, 12, 20, 0.92);
      --panel-solid: #080c14;
      --panel-2: #0c1220;
      --accent: #66fcf1;
      --accent-dim: #45a29e;
      --accent2: #4da6ff;
      --warn: #f2c94c;
      --fail: #ff4d4d;
      --success: #03c988;
      --text: #d8dce6;
      --text-bright: #f0f2f7;
      --muted: #5e6a7d;
      --border: rgba(58, 68, 88, 0.85);
      --border-bright: #5a6678;
      --font-mono: "JetBrains Mono", "Fira Code", "Consolas", monospace;
      --font-ui: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: clamp(14px, 2vw, 28px);
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-ui);
      line-height: 1.6;
    }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .report-header {
      background: linear-gradient(180deg, rgba(10,14,24,0.95) 0%, rgba(8,12,20,0.92) 100%);
      border: 1px solid var(--border);
      border-left: 4px solid var(--accent);
      border-radius: 6px;
      padding: clamp(14px, 2vw, 22px);
      margin-bottom: 22px;
    }
    .report-header h1 {
      margin: 0 0 8px;
      font-size: clamp(1.15rem, 2.4vw, 1.6rem);
      color: var(--text-bright);
      font-family: var(--font-mono);
    }
    .report-header .subtitle { color: var(--muted); font-size: 0.85rem; margin: 0 0 14px; }
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      font-size: 0.82rem;
    }
    .meta-item { display: flex; gap: 8px; }
    .meta-item .label { color: var(--muted); white-space: nowrap; }
    .meta-item .value { color: var(--accent); font-family: var(--font-mono); }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 3px;
      font-size: 0.75rem;
      border: 1px solid var(--border-bright);
    }
    .badge.ok { color: var(--success); border-color: rgba(3, 201, 136, 0.5); background: rgba(3, 201, 136, 0.08); }
    .badge.warn { color: var(--warn); border-color: rgba(242, 201, 76, 0.5); background: rgba(242, 201, 76, 0.08); }
    .section-title {
      font-size: 0.9rem;
      color: var(--accent);
      margin: 28px 0 12px;
      font-family: var(--font-mono);
      border-bottom: 1px solid var(--border);
      padding-bottom: 6px;
    }
    .layer-card {
      background: var(--panel-solid);
      border: 1px solid var(--border);
      border-radius: 5px;
      margin-bottom: 12px;
      overflow: hidden;
    }
    .layer-card summary {
      cursor: pointer;
      padding: 12px 14px;
      background: var(--panel-2);
      display: flex;
      align-items: center;
      gap: 12px;
      user-select: none;
      list-style: none;
    }
    .layer-card summary::-webkit-details-marker { display: none; }
    .layer-card summary::before {
      content: "▶";
      color: var(--accent);
      font-size: 0.7rem;
      transition: transform 0.15s;
    }
    .layer-card[open] summary::before { transform: rotate(90deg); }
    .layer-name { color: var(--text-bright); font-weight: 600; font-family: var(--font-mono); }
    .layer-count { color: var(--muted); font-size: 0.72rem; margin-left: auto; }
    .layer-body { padding: 10px 14px 14px; }
    .metric-row {
      border-bottom: 1px solid rgba(58, 68, 88, 0.45);
      padding: 10px 0;
    }
    .metric-row:last-child { border-bottom: none; padding-bottom: 0; }
    .metric-head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 12px;
      margin-bottom: 6px;
    }
    .metric-name {
      background: rgba(102, 252, 241, 0.08);
      color: var(--accent);
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 0.78rem;
    }
    .metric-desc { color: var(--text); font-size: 0.82rem; flex: 1 1 auto; }
    .metric-body {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 14px;
      font-size: 0.78rem;
    }
    .stat {
      color: var(--text-bright);
      font-family: var(--font-mono);
      background: rgba(90, 102, 120, 0.18);
      padding: 2px 7px;
      border-radius: 3px;
    }
    .stat.dim { color: var(--muted); background: transparent; padding: 0; }
    .trend {
      font-family: var(--font-mono);
      font-size: 0.72rem;
      padding: 1px 6px;
      border-radius: 3px;
      border: 1px solid var(--border-bright);
    }
    .trend.up { color: var(--success); border-color: rgba(3, 201, 136, 0.45); background: rgba(3, 201, 136, 0.08); }
    .trend.down { color: var(--fail); border-color: rgba(255, 77, 77, 0.45); background: rgba(255, 77, 77, 0.08); }
    .trend.flat { color: var(--muted); border-color: var(--border); background: rgba(58, 68, 88, 0.15); }
    .metric-note {
      color: var(--warn);
      font-size: 0.74rem;
      border-left: 2px solid var(--warn);
      padding-left: 8px;
      max-width: 100%;
    }
    .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 4px; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.76rem;
      font-family: var(--font-mono);
    }
    th, td {
      padding: 6px 9px;
      text-align: left;
      border-bottom: 1px solid rgba(58, 68, 88, 0.45);
      white-space: nowrap;
    }
    th {
      background: var(--panel-2);
      color: var(--accent);
      font-weight: 600;
    }
    tr:last-child td { border-bottom: none; }
    .row-idx { color: var(--muted); }
    .ok { color: var(--success); }
    .err { color: var(--fail); }
    .warn { color: var(--warn); }
    .dim { color: var(--muted); }
    .summary-box {
      background: rgba(102, 252, 241, 0.06);
      border: 1px solid rgba(102, 252, 241, 0.25);
      border-radius: 5px;
      padding: 14px;
      font-size: 0.9rem;
      color: var(--text-bright);
    }
    .footer {
      margin-top: 28px;
      padding-top: 14px;
      border-top: 1px solid var(--border);
      color: var(--muted);
      font-size: 0.75rem;
      text-align: right;
    }
    @media (max-width: 640px) {
      .meta-grid { grid-template-columns: 1fr; }
      .metric-head { flex-direction: column; align-items: flex-start; }
    }
  </style>
</head>
<body>
  <div class="report-header">
    <h1>TRACE-TO-EDM 桥接报告</h1>
    <p class="subtitle">面向非技术读者的人话版解读 · 基于轨迹 CSV + 任务历史自动生成</p>
    <div class="meta-grid">
      <div class="meta-item"><span class="label">当前项目</span><span class="value">${projectName}</span></div>
      <div class="meta-item"><span class="label">轨迹文件</span><span class="value">${traj.path || 'N/A'}</span></div>
      <div class="meta-item"><span class="label">轨迹行数</span><span class="value">${traj.total}</span></div>
      <div class="meta-item"><span class="label">轨迹列数</span><span class="value">${traj.columns.length}</span></div>
      <div class="meta-item"><span class="label">EDM 就绪</span>${edmReady ? '<span class="badge ok">✓ 是（≥15 行）</span>' : '<span class="badge warn">✗ 否（<15 行）</span>'}</div>
      <div class="meta-item"><span class="label">活动任务</span><span class="value">${active.length}</span></div>
      <div class="meta-item"><span class="label">历史任务</span><span class="value">${history.length} 条（最近）</span></div>
      <div class="meta-item"><span class="label">生成时间</span><span class="value">${fmtTs(generated)}</span></div>
    </div>
  </div>

  <div class="section-title">◈ 指标层级卡片</div>
  <p class="dim" style="font-size:0.78rem;margin:-8px 0 14px;">趋势 = 后半段均值 vs 前半段均值；↗/↘ 幅度 &gt; 5% 均值才算“上升/下降”，否则为“平稳”。</p>
  ${layerCards}

  <div class="section-title">◈ 轨迹数据预览（Top 15）</div>
  ${previewTable}

  <div class="section-title">◈ 任务历史（最近 20 条）</div>
  ${historyHtml}

  <div class="section-title">◈ 一句话总结</div>
  <div class="summary-box">${summary}</div>

  <div class="footer">报告由 trace-to-edm Web 自动生成于 ${fmtTs(generated)} · <a href="/api/trajectory/report">Markdown 版</a></div>
</body>
</html>`;
}

// ── API: 健康检查 ─────────────────────────────────────────
// 盲审 P1-4 修缮 (2026-08-02):
//   原版仅返回固定字符串 {status:'ok'}, 未检查 Python/bridge.py/磁盘就绪情况,
//   违反"健康检查应反映真实状态"的工程惯例. 本版真实检查:
//     1. Python 可用 (bridge.py 依赖)
//     2. data/inputs 目录存在
//     3. projects 目录存在
//     4. bridge.py 脚本可访问
//   返回三态: healthy / degraded / unhealthy
app.get('/api/health', async (_req, res) => {
  const checks = {};
  let overall = 'healthy';

  // 1. Python 可用性 (bridge.py 依赖)
  try {
    const { execFileSync } = require('child_process');
    const pyOut = execFileSync(PYTHON_CMD, ['--version'], {
      encoding: 'utf-8',
      timeout: 3000,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    }).trim();
    checks['python'] = pyOut;
  } catch (e) {
    checks['python'] = `fail: ${e.message}`;
    overall = 'unhealthy'; // 无 Python 则 bridge.py 全部失效
  }

  // 2. data/inputs 目录存在
  const inputsDir = path.join(ROOT, 'data', 'inputs');
  try {
    if (fs.existsSync(inputsDir) && fs.statSync(inputsDir).isDirectory()) {
      checks['data_inputs_dir'] = 'ok';
    } else {
      checks['data_inputs_dir'] = 'missing';
      overall = 'degraded';
    }
  } catch (e) {
    checks['data_inputs_dir'] = `error: ${e.message}`;
    overall = 'degraded';
  }

  // 3. projects 目录存在 (任务产物存储)
  try {
    if (fs.existsSync(PROJECTS_DIR) && fs.statSync(PROJECTS_DIR).isDirectory()) {
      checks['projects_dir'] = 'ok';
    } else {
      checks['projects_dir'] = 'missing';
      overall = 'degraded';
    }
  } catch (e) {
    checks['projects_dir'] = `error: ${e.message}`;
    overall = 'degraded';
  }

  // 4. bridge.py 脚本可访问 (核心桥接逻辑)
  try {
    if (fs.existsSync(BRIDGE_SCRIPT) && fs.statSync(BRIDGE_SCRIPT).isFile()) {
      checks['bridge_py'] = 'ok';
    } else {
      checks['bridge_py'] = 'missing';
      overall = 'unhealthy'; // 无 bridge.py 则所有 Python 调用失效
    }
  } catch (e) {
    checks['bridge_py'] = `error: ${e.message}`;
    overall = 'unhealthy';
  }

  // 5. 活跃任务数 (便于监控)
  try {
    checks['active_jobs'] = activeJobs.size;
  } catch (e) {
    checks['active_jobs'] = 'unknown';
  }

  res.json({
    status: overall,
    service: 'trace-to-edm',
    version: PACKAGE_VERSION,
    time: new Date().toISOString(),
    checks,
  });
});

// debt-12.13: 暴露 /api/version 端点，版本号从 package.json 读取
// 与 trace-engine-web /api/version 契约对齐，便于便携式 verify 与运维监控
app.get('/api/version', (_req, res) => {
  res.json({
    success: true,
    service: 'trace-to-edm',
    version: PACKAGE_VERSION,
    node: process.version,
    time: new Date().toISOString(),
  });
});

// ── API: 状态查询 ─────────────────────────────────────────

// ROUND28 P0-04/P1-04: EDM 分级 confidence_level (与 edm_trigger.py 阈值对齐)
// 15-30 行 = exploratory (探索性), ≥30 行 = formal (正式), <15 = insufficient
// 阈值常量与 edm_trigger.EDM_FORMAL_THRESHOLD / config.EDM_MIN_ROWS_FOR_ANALYSIS 保持同步
const EDM_MIN_ROWS = 15;
const EDM_FORMAL_THRESHOLD = 30;
function computeEDMConfidence(nRows) {
  if (nRows < EDM_MIN_ROWS) {
    return {
      confidence_level: 'insufficient',
      confidence_disclaimer: `数据不足 (${nRows} < ${EDM_MIN_ROWS}), 无法触发 EDM 分析。`,
    };
  }
  if (nRows < EDM_FORMAL_THRESHOLD) {
    return {
      confidence_level: 'exploratory',
      confidence_disclaimer:
        `探索性分析 (${nRows} 行, < ${EDM_FORMAL_THRESHOLD}): ` +
        'EDM 动力学预测在小样本下不稳定, 可能产生伪相变信号。' +
        '结果仅供探索, 不得用于投资决策。建议积累 ≥30 行后再做正式分析。',
    };
  }
  return {
    confidence_level: 'formal',
    confidence_disclaimer:
      `正式分析 (${nRows} 行 ≥ ${EDM_FORMAL_THRESHOLD}): ` +
      '结果可用于报告, 但仍需注意 EDM-TAKENS 的 IAAFT/BH 统计保证边界。',
  };
}

app.get('/api/status', (_req, res) => {
  const traj = readTrajectoryCSV();
  const active = Array.from(activeJobs.keys());

  // EDM 就绪度 + 分级置信度 (ROUND28 P0-04)
  const edmReady = traj.total >= EDM_MIN_ROWS;
  const { confidence_level, confidence_disclaimer } = computeEDMConfidence(traj.total);

  // ROUND28 P1-04/05: L3 目标标注 interpretive + methodology_tag
  // 与 layer3_sacred.METHODOLOGY_TAG / METHODOLOGY_DISCLAIMER 对齐
  const L3_TAG = 'interpretive_zero_shot';
  const L3_DISCLAIMER =
    'Layer 3 是诠释性框架 (Interpretive Framework), 非统计推断。' +
    'z_* 值由八本私域经书的零样本余弦相似度确定, 不具备 Layer 1 那样的 ' +
    'refutation/p-value 统计保证。投资决策需与 L1 统计量交叉验证。';
  const mkL1 = (col, desc) => ({ col, desc, layer: 'L1', interpretive: false, methodology_tag: 'statistical' });
  const mkL2 = (col, desc) => ({ col, desc, layer: 'L2', interpretive: false, methodology_tag: 'statistical_pca' });
  const mkL3 = (col, desc) => ({ col, desc, layer: 'L3', interpretive: true, methodology_tag: L3_TAG, methodology_disclaimer: L3_DISCLAIMER });

  const edmTargets = edmReady ? [
    // Layer 1: 元SCM (科学层)
    mkL1('ate', '因果效应强度'),
    mkL1('adj_density', '因果图密度 — 系统纠缠度'),
    mkL1('max_delta_nll', '最强因果信号'),
    mkL1('ci_width', '因果不确定性 — 时代噪音'),
    mkL1('edge_count', '显著因果边数'),
    mkL1('ccm_coverage_pct', 'CCM非线性验证覆盖率'),
    // Layer 2: 世俗语义 PCA (科学层)
    mkL2('z_pca_1', '世俗PCA第1主轴'),
    mkL2('z_pca_2', '世俗PCA第2主轴'),
    mkL2('z_pca_3', '世俗PCA第3主轴'),
    mkL2('secular_entropy', '世俗熵'),
    // Layer 3: 八正道全轴 (诠释层 · 非统计推断)
    mkL3('z_福音', '福音(祂志书) 投影'),
    mkL3('z_吉祥', '吉祥(赐福书) 投影'),
    mkL3('z_奥美', '奥美(圣源书) 投影'),
    mkL3('z_存在', '存在(真实书) 投影 — 本体论距离'),
    mkL3('z_自孕', '自孕(胜育书) 投影'),
    mkL3('z_弥赛亚', '弥赛亚(至意书) 投影'),
    mkL3('z_Alice', 'Alice(慧辩书) 投影'),
    mkL3('z_觉爱', '觉爱(智识书) 投影 — 智慧维度'),
    // Layer 3: 一阶差分 (诠释层 · 关键动力学信号)
    mkL3('dz_存在', '存在轴一阶差分 Δz/Δt'),
    mkL3('dz_觉爱', '觉爱轴一阶差分 Δz/Δt'),
  ] : [];

  res.json({
    success: true,
    trajectory: {
      path: getActiveTrajectoryCSV(),
      rows: traj.total,
      columns: traj.columns.length,
      edm_ready: edmReady,
      edm_targets: edmTargets,
      // ROUND28 P0-04: 分级置信度披露
      confidence_level,
      confidence_disclaimer,
      formal_threshold: EDM_FORMAL_THRESHOLD,
      min_required: EDM_MIN_ROWS,
    },
    jobs: { active: active.length, active_ids: active },
    layers: {
      l1: traj.columns.filter(c => ['ate','adj_density','edge_count','ccm_coverage_pct'].includes(c)).length > 0,
      l2: traj.columns.includes('z_pca_1'),
      l3: traj.columns.includes('z_存在'),
    },
  });
});

// ── API: 八正道正交性报告 ─────────────────────────────────

app.get('/api/orthogonality', async (_req, res) => {
  try {
    // Q9 P1-11: 暴露 Frobenius 距离等元审计数据
    const script = `
import sys, json; sys.path.insert(0, '.')
from layer3_sacred import SacredProjector
sp = SacredProjector()
loaded = sp.load_sacred_texts()
if not loaded:
    print(json.dumps({"available": False, "error": "sacred texts not loaded"}))
else:
    report = sp.get_orthogonality_report()
    print(json.dumps(report, ensure_ascii=False, default=str))
    `.trim();
    const { out } = await pyScript(script, 30000);
    try { res.json(JSON.parse(out)); }
    catch { res.status(500).json({ error: 'invalid response', raw: out.slice(0, 500) }); }
  } catch (e) { res.status(500).json(errorResponse(e)); }
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
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

// ── P2 (§20.12): 一键导出人话版 Markdown 报告 ─────────────────────
// 复用 buildTrajectoryReport(), 生成后返回文件路径与生成时间.
app.get('/api/trajectory/export/md', async (_req, res) => {
  try {
    const report = buildTrajectoryReport();
    reqLog(_req, 'info', `人话版报告已生成: projects/${report.projectName}/reports/latest.md`);
    res.json({
      success: true,
      path: `projects/${report.projectName}/reports/latest.md`,
      project: report.projectName,
      generated: report.generated,
      report_url: `/api/trajectory/report`,
      html_url: `/api/trajectory/report?format=html`,
    });
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

// 查看最新人话版报告（每次访问均重新生成, 保证数据最新）
// 默认返回 Markdown; 支持 ?format=html 或 Accept: text/html 返回 HTML 版本.
app.get('/api/trajectory/report', (req, res) => {
  try {
    const report = buildTrajectoryReport();
    const accept = req.headers.accept || '';
    const wantsHtml = req.query.format === 'html' || accept.includes('text/html');
    if (wantsHtml) {
      res.setHeader('Content-Type', 'text/html; charset=utf-8');
      res.send(buildTrajectoryReportHTML(report));
    } else {
      res.setHeader('Content-Type', 'text/markdown; charset=utf-8');
      res.send(report.mdContent);
    }
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

// ── API: 提交文本管线任务 (Mode A) ────────────────────────

app.post('/api/run', (req, res) => {
  const { mode, text, source, ts } = req.body;
  const jobId = createJobId();
  // P1 修复: 白名单校验 mode 参数，防止注入 SUPER 等未授权模式
  const traceMode = ['light', 'deep'].includes(mode) ? mode : 'light';

  // P1 修复：/api/run 原先忽略 text 参数，总是跑示例 CSV；现在支持单条文本。
  const args = [BRIDGE_SCRIPT];
  if (text && typeof text === 'string') {
    args.push('--text', text);
    if (source) args.push('--source', String(source));
    if (ts) args.push('--ts', String(ts));
  } else {
    const inputPath = req.resolvedInputPath || path.join(ROOT, 'data', 'inputs', 'example_input.csv');
    args.push('--input', inputPath);
  }
  args.push('--mode', traceMode, '--verbose');

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

  // P0 修复: 客户端断连时清理子进程，防止孤儿进程泄漏
  let clientDisconnected = false;
  req.on('close', () => {
    if (clientDisconnected) return;
    clientDisconnected = true;
    try { proc.kill('SIGTERM'); } catch (_) {}
    activeJobs.delete(jobId);
  });

  // P1 修复 (ROUND32 三视角评审-算法工程师): 启动阶段首字节超时
  // 病灶: /api/run 仅依赖客户端断连清理, 若 Python 启动卡死 (torch/transformers
  // 导入失败但未崩溃), SSE 连接会无限挂起, 浏览器侧表现为"loading 永不结束".
  // 修复: 60s 首字节 timeout — Python 应在 60s 内输出任意 stdout/stderr,
  // 否则判定为启动卡死, kill 进程并返回 SPAWN_TIMEOUT 错误.
  let firstByteReceived = false;
  const SPAWN_TIMEOUT_MS = 60000;
  const spawnTimer = setTimeout(() => {
    if (firstByteReceived || clientDisconnected) return;
    try { proc.kill('SIGKILL'); } catch (_) {}
    job.status = 'timeout';
    activeJobs.delete(jobId);
    emitSSE(res, 'error', {
      message: `spawn timeout (${SPAWN_TIMEOUT_MS / 1000}s 无首字节输出, Python 启动卡死)`,
      code: 'SPAWN_TIMEOUT',
    });
    res.end();
  }, SPAWN_TIMEOUT_MS);

  const _markFirstByte = () => {
    if (!firstByteReceived) {
      firstByteReceived = true;
      clearTimeout(spawnTimer);
    }
  };

  emitSSE(res, 'start', { job_id: jobId, mode: traceMode });

  proc.stdout.on('data', (data) => {
    _markFirstByte();
    if (clientDisconnected) return;
    const chunk = data.toString();
    job.logs.push({ time: new Date().toISOString(), text: chunk.trim() });
    const lines = chunk.trim().split('\n');
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
    _markFirstByte();
    if (clientDisconnected) return;
    const stderrText = data.toString().trim();
    if (stderrText) {
      job.logs.push({ time: new Date().toISOString(), text: stderrText });
      emitSSE(res, 'log', { message: stderrText });
    }
  });

  proc.on('close', (code) => {
    clearTimeout(spawnTimer);
    if (clientDisconnected) return;
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
    clearTimeout(spawnTimer);
    if (clientDisconnected) return;
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

  // P0 修复 (ROUND32 三视角评审-算法工程师): /api/replay 缺失客户端断连清理
  // 与 /api/run 不一致, 长时间回填若客户端断开会留下孤儿进程.
  let clientDisconnected = false;
  req.on('close', () => {
    if (clientDisconnected) return;
    clientDisconnected = true;
    try { proc.kill('SIGTERM'); } catch (_) {}
    activeJobs.delete(jobId);
  });

  // P1 修复: 启动阶段首字节超时 (与 /api/run 对齐, 60s)
  let firstByteReceived = false;
  const SPAWN_TIMEOUT_MS = 60000;
  const spawnTimer = setTimeout(() => {
    if (firstByteReceived || clientDisconnected) return;
    try { proc.kill('SIGKILL'); } catch (_) {}
    job.status = 'timeout';
    activeJobs.delete(jobId);
    emitSSE(res, 'error', {
      message: `spawn timeout (${SPAWN_TIMEOUT_MS / 1000}s 无首字节输出, Python 启动卡死)`,
      code: 'SPAWN_TIMEOUT',
    });
    res.end();
  }, SPAWN_TIMEOUT_MS);

  const _markFirstByte = () => {
    if (!firstByteReceived) {
      firstByteReceived = true;
      clearTimeout(spawnTimer);
    }
  };

  emitSSE(res, 'start', { job_id: jobId, mode: job.mode });

  proc.stdout.on('data', (data) => {
    _markFirstByte();
    if (clientDisconnected) return;
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
    _markFirstByte();
    if (clientDisconnected) return;
    const text = data.toString().trim();
    if (text) {
      job.logs.push({ time: new Date().toISOString(), text });
      emitSSE(res, 'log', { message: text });
    }
  });

  proc.on('close', (code) => {
    clearTimeout(spawnTimer);
    if (clientDisconnected) return;
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
    clearTimeout(spawnTimer);
    if (clientDisconnected) return;
    job.status = 'error';
    activeJobs.delete(jobId);
    emitSSE(res, 'error', { message: err.message });
    res.end();
  });
});

// ── API: EDM 触发 ─────────────────────────────────────────

app.post('/api/edm/trigger', (req, res) => {
  const { target, q, time_start, time_end, predict_window } = req.body;

  // P0-4 (Round 21 §P0-A): 入参校验 — 防止恶意输入触发 Python 端异常或长时间运行
  // target: 字符串白名单 (ate/ci_width/refuted_count/identifiable 等已知列名)
  // q: 正整数 [2, 20]
  // time_start/time_end: 数字 (时间步索引)
  // predict_window: 非负整数 [0, 1000]
  const ALLOWED_TARGETS = new Set([
    'ate', 'ate_ci_lower', 'ate_ci_upper', 'ci_width', 'refuted_count',
    'identifiable', 'n_significant_edges', 'trace_status', 'trace_error',
  ]);
  if (target != null && (typeof target !== 'string' || !ALLOWED_TARGETS.has(target))) {
    return res.status(400).json({ success: false, error: `target 必须为白名单值: ${Array.from(ALLOWED_TARGETS).join('/')}`, code: 'INVALID_TARGET' });
  }
  const qNum = Number(q);
  if (q != null && (!Number.isInteger(qNum) || qNum < 2 || qNum > 20)) {
    return res.status(400).json({ success: false, error: 'q 必须为 [2, 20] 之间的整数', code: 'INVALID_Q' });
  }
  for (const [k, v] of [['time_start', time_start], ['time_end', time_end]]) {
    if (v != null && (typeof v !== 'number' || !Number.isFinite(v) || v < 0)) {
      return res.status(400).json({ success: false, error: `${k} 必须为非负数字`, code: 'INVALID_TIME' });
    }
  }
  const pwNum = Number(predict_window);
  if (predict_window != null && (!Number.isInteger(pwNum) || pwNum < 0 || pwNum > 1000)) {
    return res.status(400).json({ success: false, error: 'predict_window 必须为 [0, 1000] 之间的整数', code: 'INVALID_PW' });
  }

  const args = [
    BRIDGE_SCRIPT,
    '--edm-only',
    '--target', target || 'ate',
    '--q', String(qNum || 3),
    '--no-wait',  // 不等待EDM完成, 立即返回job_id
    '--verbose',
  ];
  if (time_start != null) args.push('--time-start', String(time_start));
  if (time_end != null) args.push('--time-end', String(time_end));
  if (predict_window != null) args.push('--predict-window', String(pwNum));

  const proc = spawn(PYTHON_CMD, args, {
    cwd: ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });

  // P1-2 修复: 增加 spawn 超时，防止 Python 启动挂起导致响应永不返回
  let responded = false;
  const spawnTimer = setTimeout(() => {
    if (!responded) {
      try { proc.kill('SIGKILL'); } catch (_) {}
      responded = true;
      res.status(504).json({ success: false, error: 'edm trigger spawn timeout (30s)', code: 'SPAWN_TIMEOUT' });
    }
  }, 30000);

  let stdout = '';
  let stderr = '';

  proc.stdout.on('data', (data) => {
    stdout += data.toString();
  });

  proc.stderr.on('data', (data) => {
    stderr += data.toString();
  });

  proc.on('close', (code) => {
    clearTimeout(spawnTimer);
    if (responded) return;  // 超时已响应
    responded = true;
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
    clearTimeout(spawnTimer);
    if (responded) return;
    responded = true;
    res.status(500).json({ success: false, error: err.message });
  });
});

// ── API: EDM 轮询代理 (P2-fix: 避免浏览器 CORS) ──────────
// 前端不能直接从 localhost:3100 fetch 到 localhost:8000
// (不同端口 = 跨域，edm-takens-web 的 CORS 白名单不含 localhost:3100)。
// 此后端端点代理转发轮询请求，服务器端 HTTP 无 CORS 限制。

const EDM_POLL_URL = process.env.EDM_API_URL || 'http://127.0.0.1:8000';

app.get('/api/edm/poll/:jobId', (req, res) => {
  const { jobId } = req.params;
  // P2-1 修复: 校验 jobId 格式，防止 SSRF 或路径注入
  if (!/^[\w\-]{1,128}$/.test(jobId)) {
    return res.status(400).json({ error: 'invalid jobId format', code: 'INVALID_JOB_ID' });
  }
  const mod = EDM_POLL_URL.startsWith('https') ? require('https') : require('http');
  const url = `${EDM_POLL_URL}/api/analyze/jobs/${encodeURIComponent(jobId)}`;

  reqLog(req, 'info', `EDM poll proxy → ${url}`);

  const upstream = mod.get(url, { timeout: 5000 }, (upRes) => {
    let body = '';
    upRes.on('data', chunk => body += chunk);
    upRes.on('end', () => {
      try {
        res.json(JSON.parse(body));
      } catch {
        res.status(502).json({ error: 'invalid upstream response', raw: body.slice(0, 200) });
      }
    });
  });

  upstream.on('error', (err) => {
    reqLog(req, 'warn', `EDM poll failed: ${err.message}`);
    res.status(502).json({
      error: `edm-takens-web unreachable: ${err.message}`,
      hint: '请确保 edm-takens-web 后端已启动 (python run_backend.py, 端口 8000)'
    });
  });

  upstream.setTimeout(5000, () => {
    upstream.destroy();
    res.status(504).json({ error: 'edm-takens-web timeout' });
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
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

app.get('/api/dataset', async (_req, res) => {
  try {
    const script = `import sys, json; sys.path.insert(0, '.'); from project_manager import get_project_manager; from dataset_manager import DatasetManager; pm = get_project_manager(); dm = DatasetManager(pm.current_dir); print(json.dumps({"entries": dm.entries, "summary": dm.summary()}, ensure_ascii=False, default=str))`;
    const proc = spawn(PYTHON_CMD, ['-c', script], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 10000 });
    let out = ''; proc.stdout.on('data', d => out += d.toString());
    proc.on('close', () => { try { res.json(JSON.parse(out)); } catch { res.json({ error: out }); } });
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/dataset/add', async (req, res) => {
  try {
    const { uuids } = req.body;
    if (!uuids || !uuids.length) return res.status(400).json({ error: 'uuids required' });
    const entries = uuids.map(u => ({ uuid: u, mtime: '', text_preview: '' }));
    const result = await pyDS('add_replay_uuids', [entries]);
    res.json(result);
  } catch (e) { res.status(500).json(errorResponse(e)); }
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
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/dataset/remove', async (req, res) => {
  try { await pyDS('remove_entry', [req.body.id]); res.json({ success: true }); }
  catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/dataset/clear-processed', async (_req, res) => {
  try { await pyDS('clear_processed'); res.json({ success: true }); }
  catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/dataset/reset', async (_req, res) => {
  try { await pyDS('reset_all_pending'); res.json({ success: true }); }
  catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/dataset/update-ts', async (req, res) => {
  try {
    const { id, timestamp } = req.body;
    if (!id || !timestamp) return res.status(400).json({ error: 'id and timestamp required' });
    // Q9 P0-4 修复：原代码字符串拼接 id/timestamp 进 Python 代码，存在注入风险。
    // 改为 JSON 序列化传参，Python 侧用 json.loads 解码（与 pyDS 同模式）。
    const argsJson = JSON.stringify([String(id), String(timestamp)]);
    const script = `
import sys, json; sys.path.insert(0, '.')
from project_manager import get_project_manager
from dataset_manager import DatasetManager
pm = get_project_manager()
dm = DatasetManager(pm.current_dir)
_args = json.loads('${argsJson.replace(/'/g, "\\'")}')
_target_id, _target_ts = _args
for e in dm.entries:
    if e['id'] == _target_id:
        e['timestamp'] = _target_ts
        dm._save()
        print('{"success":true}')
        break
else:
    print('{"success":false,"error":"entry not found"}')
    `.trim();
    const { out } = await pyScript(script, 5000);
    try { res.json(JSON.parse(out)); } catch { res.json({ success: true }); }
  } catch (e) { res.status(500).json(errorResponse(e)); }
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
errors = []
for eid in ids:
    try: dm.mark_processed(eid)
    except Exception as e: errors.append(str(e))
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
// P2 修缮：识别 ✖ TRACE 失败标记，升级为 error 事件；返回 'ok'|'partial'|'failed' 三态
function streamBridgeProcess(res, args, label) {
  return new Promise((resolve) => {
    emitSSE(res, 'progress', { message: `▶ ${label}` });
    const proc = spawn(PYTHON_CMD, [BRIDGE_SCRIPT, ...args, '--verbose'], {
      cwd: ROOT,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });

    let sawTraceFailure = false;  // P2：识别 bridge.py 内部的 ✖ TRACE 失败标记

    proc.stdout.on('data', data => {
      const text = data.toString();
      text.split('\n').filter(l => l.trim()).forEach(line => {
        const trimmed = line.trim();
        // P2 修缮：✖ 标记的 TRACE 失败升级为 error 事件，让前端能感知"全 0 行"的真正原因
        if (trimmed.includes('✖ TRACE') || trimmed.includes('✖ L1 提取失败') || trimmed.includes('TRACE 分析失败')) {
          sawTraceFailure = true;
          emitSSE(res, 'error', { message: trimmed });
        } else if (trimmed.includes('✓') || trimmed.includes('完成')) {
          emitSSE(res, 'progress', { message: trimmed });
        } else if (trimmed.includes('⚠') || trimmed.includes('❌')) {
          emitSSE(res, 'warn', { message: trimmed });
        } else if (trimmed) {
          emitSSE(res, 'log', { message: trimmed });
        }
      });
    });

    proc.stderr.on('data', data => {
      const text = data.toString().trim();
      if (text && !text.includes('Loading weights')) emitSSE(res, 'log', { message: text });
    });

    proc.on('close', code => {
      // P2：即使 exit=0，只要有 TRACE 失败标记就返回 'partial'，让 /api/pipeline/run 报告部分失败
      if (code === 0 && sawTraceFailure) {
        emitSSE(res, 'warn', { message: '管线完成但部分 TRACE 分析失败（轨迹 CSV 中 L1 字段可能为 0，trace_status=FAILED 已标记）' });
        resolve('partial');
      } else if (code === 0) {
        resolve('ok');
      } else {
        resolve('failed');
      }
    });
    proc.on('error', err => { emitSSE(res, 'error', { message: err.message }); resolve('failed'); });
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

  // P2 修缮：从前端读取 trace_mode（默认 light），允许 LIGHT/DEEP 切换
  // SUPER 模式不在此处支持（需经 trace-engine-web 的 LLaMA Worker）
  const body = req.body || {};
  const requestedMode = (typeof body.trace_mode === 'string' ? body.trace_mode : (req.query && req.query.trace_mode) || 'light').toLowerCase();
  const traceMode = ['light', 'deep'].includes(requestedMode) ? requestedMode : 'light';

  const jobId = createJobId();
  const job = { id: jobId, mode: `pipeline:${traceMode}`, startTime: new Date().toISOString(), status: 'running' };
  activeJobs.set(jobId, job);

  res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive' });
  emitSSE(res, 'start', { job_id: jobId, trace_mode: traceMode });

  try {
    // 1. 获取数据集导出
      emitSSE(res, 'log', { message: '准备数据集...' });
      const exports = await getDatasetExports();

      if (exports.error || exports.pending_replay === undefined || exports.pending_text === undefined) {
        const reason = exports.error || exports || '数据集导出异常';
        emitSSE(res, 'warn', { message: String(reason) || 'no pending entries' });
        emitSSE(res, 'done', { job_id: jobId, success: true, message: 'no pending entries' });
        return;
      }

      emitSSE(res, 'log', { message: `待处理: ${exports.pending_replay} 回填 + ${exports.pending_text} 文本 | TRACE 模式: ${traceMode.toUpperCase()}` });

      // P2 修缮：状态聚合改为 ok/partial/failed 三态
      let worstStatus = 'ok';  // ok > partial > failed

      // 2. 处理回填条目 (实时流式)
      if (exports.replay_csv) {
        emitSSE(res, 'progress', { message: `--- 回填管线 (${exports.pending_replay}条) ---` });
        const status = await streamBridgeProcess(res, ['--replay', exports.replay_csv], `Mode B: 回填 ${exports.pending_replay} 条`);
        if (status === 'failed') { emitSSE(res, 'warn', { message: '回填管线失败' }); worstStatus = 'failed'; }
        else if (status === 'partial' && worstStatus === 'ok') { worstStatus = 'partial'; }
        emitSSE(res, 'progress', { message: '回填管线完成 ✓' });
      }

      // 3. 处理文本条目 (实时流式)
      if (exports.text_csv) {
        emitSSE(res, 'progress', { message: `--- 文本管线 (${exports.pending_text}条, ${traceMode.toUpperCase()}模式) ---` });
        const status = await streamBridgeProcess(res, ['--input', exports.text_csv, '--mode', traceMode], `Mode A: 文本分析 ${exports.pending_text} 条 [${traceMode.toUpperCase()}]`);
        if (status === 'failed') { emitSSE(res, 'warn', { message: '文本管线失败' }); worstStatus = 'failed'; }
        else if (status === 'partial' && worstStatus === 'ok') { worstStatus = 'partial'; }
        emitSSE(res, 'progress', { message: '文本管线完成 ✓' });
      }

      // 4. 标记已处理 + 更新统计
      emitSSE(res, 'log', { message: '更新数据集状态...' });
      const stats = await markDatasetProcessed(exports.pending_ids);

      // P2：partial 也算"完成但有警告"，failed 才算失败
      job.status = worstStatus === 'failed' ? 'failed' : 'completed';
      job.endTime = new Date().toISOString();

      // P2：如果 partial，在 done 事件中显式提示
      if (worstStatus === 'partial') {
        emitSSE(res, 'warn', { message: '部分 TRACE 分析失败：轨迹 CSV 中 trace_status=FAILED 的行 L1 字段为 0，请检查 server.log 或前端 error 事件' });
      }

      emitSSE(res, 'done', {
        job_id: jobId,
        success: worstStatus !== 'failed',
        partial: worstStatus === 'partial',
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
  // P1-b：服务端 5s 内存缓存，减少 Python 冷启动开销
  const cached = getCached('models');
  if (cached) return res.json(cached);
  try {
    const script = "import sys, json; sys.path.insert(0, '.'); from layer3_sacred import list_models, get_active_model; print(json.dumps({'models': list_models(), 'active': get_active_model()}, ensure_ascii=False))";
    const result = await pyScript(script, 30000);
    let payload;
    try { payload = JSON.parse(result.out); } catch { payload = { error: result.out }; }
    setCached('models', payload);
    res.json(payload);
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/models/activate', async (req, res) => {
  const { model } = req.body;
  if (!model) return res.status(400).json({ error: 'model key required' });

  // 元审计 P1 修缮: Python 注入防护
  // 之前用字符串拼接 + replace(/'/g, '') 不够健壮
  // 现采用白名单校验 + JSON 参数传递，彻底消除注入
  // Q9 P1-16 修复: TRACE LLaMA 模型仅在前端展示，不允许在 L3 直接激活
  const ALLOWED_MODELS = ['qwen2.5-1.5b', 'qwen2.5-3b'];
  if (!ALLOWED_MODELS.includes(model)) {
    return res.status(400).json({
      error: `invalid model key: ${model}`,
      allowed: ALLOWED_MODELS,
      note: 'shehui-llama / shenji-llama 为 TRACE LLaMA 展示模型，请使用 trace-engine-web SUPER 模式',
    });
  }

  try {
    // 用 JSON 序列化传递参数，避免任何字符串拼接
    const modelJson = JSON.stringify(model);
    const script = `import sys, json; sys.path.insert(0, '.'); from layer3_sacred import set_active_model, get_active_model; ok = set_active_model(json.loads('${modelJson}')); print(json.dumps({'success': ok, 'active': get_active_model()}, ensure_ascii=False))`;
    const result = await pyScript(script, 15000);
    let payload;
    try { payload = JSON.parse(result.out); } catch { payload = { success: false }; }
    if (!payload.success) {
      return res.status(400).json({
        error: `model '${model}' cannot be activated (展示模型或未注册)`,
        allowed: ALLOWED_MODELS.filter(k => !['shehui-llama','shenji-llama'].includes(k)),
      });
    }
    // P1-b：模型切换后失效缓存，确保下次 GET /api/models 返回最新状态
    invalidateCache('models');
    res.json(payload);
  } catch (e) { res.status(500).json(errorResponse(e)); }
});


// ── API: 项目管理 ─────────────────────────────────────────

app.get('/api/projects', async (_req, res) => {
  // P1-b：服务端 5s 内存缓存
  const cached = getCached('projects');
  if (cached) return res.json(cached);
  try {
    const result = await pyCall(['--list-projects']);
    setCached('projects', result);
    res.json(result);
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

// P0-2/P0-3 (Round 21 §P0-A): 项目名称格式校验
// 防止 path traversal — name 会传给 Python project_manager 拼接路径
// 允许: 字母/数字/下划线/连字符/中文, 长度 1-64, 禁止 ../ \ / : 等路径字符
const PROJECT_NAME_RE = /^[A-Za-z0-9_\-\u4e00-\u9fa5]{1,64}$/;
function isValidProjectName(name) {
  return typeof name === 'string' && PROJECT_NAME_RE.test(name);
}

app.post('/api/projects', async (req, res) => {
  const { name, description } = req.body;
  if (!isValidProjectName(name)) {
    return res.status(400).json({ error: 'name 必须为 1-64 位字母/数字/下划线/连字符/中文', code: 'INVALID_NAME' });
  }
  try {
    const result = await pyCall(['--create-project', name]);
    invalidateCache('projects');  // P1-b：项目列表变更后失效缓存
    res.json(result);
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

app.put('/api/projects/activate', async (req, res) => {
  const { name } = req.body;
  if (!isValidProjectName(name)) {
    return res.status(400).json({ error: 'name 必须为 1-64 位字母/数字/下划线/连字符/中文', code: 'INVALID_NAME' });
  }
  try {
    const result = await pyCall(['--project', name]);
    // P1-b：项目切换后失效所有缓存（模型列表也因项目隔离而变化）
    invalidateCache();
    res.json(result);
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

app.delete('/api/projects/:name', async (req, res) => {
  const { name } = req.params;
  if (!isValidProjectName(name)) {
    return res.status(400).json({ error: 'name 必须为 1-64 位字母/数字/下划线/连字符/中文', code: 'INVALID_NAME' });
  }
  try {
    const result = await pyCall(['--delete-project', name]);
    invalidateCache('projects');  // P1-b：项目删除后失效缓存
    res.json(result);
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

// ── API: 工作目录扫描 ─────────────────────────────────────

app.get('/api/work-scan', async (_req, res) => {
  try {
    const result = await pyCall(['--scan-work']);
    res.json(result);
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

app.delete('/api/work-uuid/:uuid', async (req, res) => {
  // 安全校验: 允许标准UUID和非标准短名称(如test-abort)，但拒绝路径遍历和特殊字符
  const SAFE_NAME_RE = /^[A-Za-z0-9_\-]{1,64}$/;
  if (!SAFE_NAME_RE.test(req.params.uuid)) {
    return res.status(400).json({ error: 'INVALID_UUID', detail: 'Only alphanumeric, hyphen, underscore allowed (max 64 chars)' });
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
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/work-clean', async (req, res) => {
  const dryRun = req.body.dry_run !== false;
  const orphansOnly = req.body.orphans_only === true;
  // P0 修缮：JavaScript 的 true/false 插入 Python 代码必须转为 True/False
  // 否则 Python 会抛 NameError: name 'true' is not defined
  const dryRunPy = dryRun ? 'True' : 'False';
  const orphansOnlyPy = orphansOnly ? 'True' : 'False';
  try {
    const script = `
import sys, json
sys.path.insert(0, '.')
from work_scanner import WorkScanner
ws = WorkScanner()
result = ws.delete_invalid(dry_run=${dryRunPy}) if not ${orphansOnlyPy} else ws.delete_orphans(dry_run=${dryRunPy})
print(json.dumps(result, ensure_ascii=False))
    `.trim();
    const { out, err } = await pyScript(script, 15000);
    if (err && err.trim()) {
      console.warn('[work-clean] Python stderr:', err.trim());
    }
    try { res.json(JSON.parse(out)); } catch { res.json({ raw: out.trim(), error: err.trim() || undefined }); }
  } catch (e) {
    res.status(500).json(errorResponse(e));
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
    res.status(500).json(errorResponse(e));
    try { fs.unlinkSync(uuidsFile); } catch {}
  }
});

// ── API: 读取 replay UUID 的原始输入文本 ─────────────────
// 复用 bridge.py 的 _find_input_text()，从 work/inputs/{uuid}.txt 读回原文
// 用于前端数据集详情 modal 显示 replay 类型条目的完整文本
app.get('/api/work-uuid/:uuid/text', async (req, res) => {
  // 安全校验: 与 DELETE /api/work-uuid/:uuid 同一规则，防止路径遍历与命令注入
  const SAFE_NAME_RE = /^[A-Za-z0-9_\-]{1,64}$/;
  if (!SAFE_NAME_RE.test(req.params.uuid)) {
    return res.status(400).json({ error: 'INVALID_UUID', detail: 'Only alphanumeric, hyphen, underscore allowed (max 64 chars)' });
  }
  // P0 修缮: UUID 已通过白名单校验，可安全插值；桥接脚本固定单引号包裹
  const script = `
import sys, json; sys.path.insert(0, '.')
from bridge import _find_input_text
text = _find_input_text('${req.params.uuid}')
print(json.dumps({"text": text or ""}, ensure_ascii=False))
  `.trim();
  try {
    const { out, err } = await pyScript(script, 10000);
    if (err && err.trim()) {
      // bridge.py 在文件读取失败时会向 stderr 写警告，但不影响返回空文本
      console.warn(`[work-uuid/text] Python stderr for ${req.params.uuid}:`, err.trim());
    }
    try {
      const parsed = JSON.parse(out);
      res.json(parsed);
    } catch {
      // stdout 不是合法 JSON — 视为未找到
      res.status(404).json({ error: 'TEXT_NOT_FOUND', raw: out.trim() });
    }
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

// ── 启动 ──────────────────────────────────────────────────

// P1 修缮 (2026-07-25 元审计 Round 12.10): host 收窄到 127.0.0.1
// 原实现 app.listen(PORT) 未指定 host，等价于隐式 0.0.0.0（暴露至 LAN/公网）
// 默认仅本机访问；如需外部访问，显式设置 TRACE_HOST=0.0.0.0
const HOST = process.env.TRACE_HOST || '127.0.0.1';
app.listen(PORT, HOST, () => {
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
