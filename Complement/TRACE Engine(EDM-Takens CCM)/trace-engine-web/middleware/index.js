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
function corsMiddleware() {
  const origin = process.env.TRACE_CORS_ORIGIN;
  // 允许的来源列表：未设置时回退到 localhost 系列
  const allowedOrigins = origin
    ? origin.split(',').map((s) => s.trim()).filter(Boolean)
    : ['http://localhost:3000', 'http://127.0.0.1:3000', 'http://localhost'];

  return function corsHandler(req, res, next) {
    const reqOrigin = req.headers['origin'];
    if (reqOrigin && allowedOrigins.includes(reqOrigin)) {
      res.setHeader('Access-Control-Allow-Origin', reqOrigin);
      res.setHeader('Vary', 'Origin');
    } else if (!origin) {
      // 开发模式：未配置 TRACE_CORS_ORIGIN 时允许 localhost
      if (reqOrigin && /https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/.test(reqOrigin)) {
        res.setHeader('Access-Control-Allow-Origin', reqOrigin);
        res.setHeader('Vary', 'Origin');
      }
    }
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
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
  reqLog(req, 'error', `Express 错误: ${err.message}`);
  res.status(500).json({ success: false, error: err.message, traceId: req.traceId });
}

module.exports = {
  traceIdMiddleware,
  corsMiddleware,
  optionsHandler,
  errorHandler,
};
