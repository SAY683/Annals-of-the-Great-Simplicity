const express = require('express');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const crypto = require('crypto');

const { ROOT, PUBLIC_DIR, BRIDGE_SCRIPT, PYTHON_CMD, TRAJECTORY_CSV, PROJECTS_DIR, CORS_ALLOWED_ORIGINS, PACKAGE_VERSION } = require('./config');
const { serverLog, reqLog } = require('./services/logger');
const { getCached, setCached, invalidateCache } = require('./lib/cache');
const { pyCall, pyScript, errorResponse } = require('./services/python-service');
const { getActiveTrajectoryCSV, readTrajectoryCSV, buildTrajectoryReport, buildTrajectoryReportHTML } = require('./services/trajectory-service');
const { activeJobs, jobHistory, createJobId, emitSSE, streamBridgeProcess } = require('./services/job-service');
const { pyDS, getDatasetExports, markDatasetProcessed } = require('./services/dataset-service');
const { validateInputPathMiddleware } = require('./middleware/input-path');
const { installAsyncBoundary } = require('./lib/async-boundary');
const { createMcpRouter } = require('../mcp');

function createApp({ getPort }) {
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
  // 请求追踪 ID（便于日志串联）
  app.use((req, _res, next) => {
    req.traceId = req.headers['x-trace-id'] || crypto.randomBytes(4).toString('hex');
    next();
  });

  // P1-4: API Key 认证中间件（通过 CROSS_PROJECT_API_KEY 环境变量启用）
  // P1-1 修复: 生产模式拒绝静默降级；开发模式回退到内置最小鉴权（环回地址放行）
  try {
    const sharedAuth = require('../../shared/auth_middleware');
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
  app.use('/mcp', createMcpRouter(getPort));

  // P2 maintainability: HTTP routes are grouped by capability under src/routes/.
  // The context preserves the existing helper/state contract while keeping route
  // modules free of process-global imports.
  const pipelineState = { running: false };
  const routeContext = {
    fs, path, spawn, crypto, ROOT, PROJECTS_DIR, TRAJECTORY_CSV, PYTHON_CMD,
    BRIDGE_SCRIPT, PACKAGE_VERSION, serverLog, reqLog, getActiveTrajectoryCSV,
    pyCall, pyScript, errorResponse, activeJobs, jobHistory, createJobId, emitSSE,
    streamBridgeProcess, readTrajectoryCSV, buildTrajectoryReport,
    buildTrajectoryReportHTML, getCached, setCached, invalidateCache, pyDS,
    getDatasetExports, markDatasetProcessed, pipelineState,
  };
  installAsyncBoundary(app);
  require('./routes')(app, routeContext);

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

  return app;
}

module.exports = { createApp };
