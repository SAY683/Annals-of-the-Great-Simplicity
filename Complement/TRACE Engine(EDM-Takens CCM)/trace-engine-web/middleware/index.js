/**
 * TRACE Engine Web — 通用中间件模块
 * =====================================
 * 抽取自 server.js：traceId、CORS（debt-15：修正通配符）、错误处理。
 */
const crypto = require('crypto');

const utils = require('../lib/utils');
const { reqLog } = utils;

// ── 请求追踪 ID（便于多云环境日志串联） ─────────────────────────────
function traceIdMiddleware(req, _res, next) {
  req.traceId = req.headers['x-trace-id'] || crypto.randomUUID();
  next();
}

// ── CORS（debt-15：默认拒绝通配符 '*'，强制精确来源） ──────────────
// 当 TRACE_CORS_ORIGIN 未设置时，仅允许 localhost（开发模式兼容）。
// 生产/多云部署必须通过 TRACE_CORS_ORIGIN 指定精确来源。
// debt-12.15 隧道支持: 自动读取 tunnel_url.txt，把 trycloudflare 域名加入白名单
// P1-5 修复 (ROUND27 12维度核对): 原 url.includes('trycloudflare.com') 可被
// https://attacker.com/?trycloudflare.com 绕过. 现用 new URL() 严格解析 hostname.
function _loadTunnelOrigins() {
  try {
    const fs = require('fs');
    const path = require('path');
    const tunnelFile = path.join(__dirname, '..', 'tunnel_url.txt');
    if (fs.existsSync(tunnelFile)) {
      const raw = fs.readFileSync(tunnelFile, 'utf-8').trim();
      if (!raw) return [];
      const parsed = new URL(raw);  // 严格解析, 非 URL 会抛异常
      // 仅允许 trycloudflare.com 子域 (hostname 以 .trycloudflare.com 结尾)
      if (parsed.hostname.endsWith('.trycloudflare.com') &&
          parsed.protocol === 'https:') {
        return [parsed.origin];  // origin = protocol + host (无尾斜杠)
      }
    }
  } catch (e) { /* 静默降级 */ }
  return [];
}

function corsMiddleware() {
  const origin = process.env.TRACE_CORS_ORIGIN;
  // 允许的来源列表：未设置时回退到 localhost 系列 + 隧道域名
  const allowedOrigins = origin
    ? origin.split(',').map((s) => s.trim()).filter(Boolean)
    : ['http://localhost:3000', 'http://127.0.0.1:3000', 'http://localhost'].concat(_loadTunnelOrigins());

  return function corsHandler(req, res, next) {
    const reqOrigin = req.headers['origin'];
    if (reqOrigin && allowedOrigins.includes(reqOrigin)) {
      res.setHeader('Access-Control-Allow-Origin', reqOrigin);
      res.setHeader('Vary', 'Origin');
    } else if (!origin) {
      // 开发模式：未配置 TRACE_CORS_ORIGIN 时允许 localhost
      // P1-4 修复 (ROUND27 12维度核对): 移除 trycloudflare 通配符正则分支,
      // 隧道域名已由 _loadTunnelOrigins() 从 tunnel_url.txt 读取精确域名加入
      // allowedOrigins, 不再需要通配符放行任意 *.trycloudflare.com (CSRF 风险).
      if (reqOrigin && /https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/.test(reqOrigin)) {
        res.setHeader('Access-Control-Allow-Origin', reqOrigin);
        res.setHeader('Vary', 'Origin');
      }
    }
    // P1-2 修复 (Round 27 审计): 补充 DELETE，与 routes/jobs.js 的 router.delete('/:id') 对齐，
    // 否则跨域（含隧道模式）DELETE 预检会被阻断。
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Trace-Config, X-Trace-Id, Last-Event-ID');
    res.setHeader('Access-Control-Expose-Headers', 'Last-Event-ID');
    next();
  };
}

// OPTIONS 预检
function optionsHandler(_req, res) {
  res.sendStatus(204);
}

// ── 全局错误处理（保留 traceId 串联） ───────────────────────────────
function errorHandler(err, req, res, _next) {
  // body-parser / express.json() 解析失败时抛出 SyntaxError，且 err.status === 400、'body' in err
  // 此类错误属于客户端请求体问题，应返回 400 Bad Request 而非 500
  if (err instanceof SyntaxError && err.status === 400 && 'body' in err) {
    reqLog(req, 'warn', `JSON 解析失败: ${err.message}`);
    res.status(400).json({
      success: false,
      error: '请求体不是合法的 JSON',
      code: 'INVALID_JSON',
      traceId: req.traceId,
    });
    return;
  }
  // P1 修复: 显式捕获 PayloadTooLargeError (413)
  if (err.type === 'entity.too.large' || err.status === 413) {
    reqLog(req, 'warn', `请求体过大: ${err.message}`);
    return res.status(413).json({ error: 'PAYLOAD_TOO_LARGE', detail: 'Request body exceeds 20MB limit' });
  }
  reqLog(req, 'error', `Express 错误: ${err.message}`);  // 完整错误记录到服务端日志
  // P1-3 修复 (ROUND27 12维度核对): 5xx 不回显 err.message, 避免泄露 Python stderr/
  // 文件路径/库版本/堆栈片段. 完整错误已在上方 reqLog 记录, 前端仅显示通用文案.
  res.status(500).json({ success: false, error: '服务器内部错误，请查看服务端日志获取详细信息', traceId: req.traceId });
}

module.exports = {
  traceIdMiddleware,
  corsMiddleware,
  optionsHandler,
  errorHandler,
};
