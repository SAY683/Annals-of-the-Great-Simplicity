/**
 * TRACE Engine Web MVP — NodeJS 服务端（debt-07/08 拆分后入口）
 * =====================================
 * 仅保留 app 创建、中间件挂载、路由挂载、监听、gracefulShutdown。
 * 实际逻辑分布在 lib/、services/、routes/、middleware/ 模块中。
 *
 * 端点（20 routes，全部保持向后兼容）:
 *   POST /api/analyze-text         分析纯文本 (JSON: {text, mode})
 *   POST /api/analyze-file         上传文本文件分析 (multipart: file, mode)
 *   GET  /api/analyze-stream?id=   SSE 实时流（阶段+日志+结果）
 *   POST /api/analyze-stream       SSE 流（POST 别名）
 *   POST /api/cancel/:id           取消分析任务
 *   GET  /api/result/:id           获取分析结果 (JSON)
 *   GET  /api/report/:id           获取 Markdown 报告
 *   GET  /api/jobs                 任务历史列表
 *   GET  /api/jobs/export          导出任务历史 (JSON/CSV)
 *   POST /api/jobs/clear           清空任务历史（管理员，debt-12）
 *   GET  /api/jobs/:id             查询单个任务状态
 *   POST /api/retry/:id            重试任务（SUPER 模式不支持）
 *   POST /api/admin/cleanup        手动触发输出目录 TTL 清理（管理员，debt-12）
 *   GET  /api/health               健康检查
 *   GET  /api/config               当前配置 + bridgeParamSchema
 *   GET  /api/queue                任务队列状态
 *   GET  /api/version              版本信息
 *   GET  /api/presets              参数预设（从 presets.yaml 加载，debt-16）
 *   GET  /api/schema               Bridge 参数 Schema + resultSchema（debt-10）
 *   GET  /api/metrics              运行时指标
 *   GET  /                         前端页面
 */

const express = require('express');
const path = require('path');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');

// 共享状态与工具
const state = require('./lib/state');
const utils = require('./lib/utils');
const {
  CONFIG,
  WORK_DIR,
  BUILD_INFO,
  VERSION,
  activeJobs,
  activeJobResponses,
  jobHistory,
  resultCache,
  jobQueue,
  llamaState,
} = state;
const {
  logToFile,
  loadJobHistory,
  validateSkillDir,
  checkPythonEnv,
  loadBridgeParamSchema,
  startCacheTtlSweeper,
} = utils;

// 服务模块
const llamaWorkerSvc = require('./services/llamaWorker');

// 中间件
const middleware = require('./middleware');
const { createAuthMiddleware } = require('./middleware/auth');

// 路由
const analysisRoutes = require('./routes/analysis');
const jobsRoutes = require('./routes/jobs');
const systemRoutes = require('./routes/system');
const adminRoutes = require('./routes/admin');

// ── 应用初始化 ──────────────────────────────────────────────────────
const app = express();
const PORT = CONFIG.port;

// 启动时加载任务历史
loadJobHistory();

// 探测 LLaMA 模型（工作目录已就绪）
const PROBED_LLAMA_MODELS = llamaWorkerSvc.probeLlamaModels();

// 加载桥接参数 Schema（debt-16：优先 build_bridge_schema.py，回退 schema/bridge_schema.json）
const BRIDGE_PARAM_SCHEMA = loadBridgeParamSchema(null, PROBED_LLAMA_MODELS);
const SUPER_BRIDGE_PARAM_SCHEMA = loadBridgeParamSchema('llama', PROBED_LLAMA_MODELS);

// Skill 目录校验
const skillValidation = validateSkillDir();
if (!skillValidation.ok) {
  console.warn(`[WARN] Skill 目录校验未通过: ${CONFIG.skillDir}`);
  console.warn(`  存在: ${skillValidation.exists}, 缺失文件: ${skillValidation.missing.join(', ') || '无'}`);
  logToFile('warn', `Skill 目录校验未通过: exists=${skillValidation.exists} missing=${skillValidation.missing.join(',')}`);
}

// Python 环境检查
const pythonEnv = checkPythonEnv();
if (!pythonEnv.ok) {
  console.warn(`[WARN] Python 环境检查未通过: ${pythonEnv.error}`);
  logToFile('warn', `Python 环境检查未通过: ${pythonEnv.error}`);
}

// ── 安全与生产中间件（debt-15） ─────────────────────────────────────
// helmet：设置安全 HTTP 头（CSP/X-Frame-Options/X-Content-Type-Options 等）。
// 注意：前端内联脚本与样式需要 unsafe-inline，CSP 适当放宽。
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'", "'unsafe-inline'"],
      styleSrc: ["'self'", "'unsafe-inline'"],
      imgSrc: ["'self'", 'data:'],
      connectSrc: ["'self'"],
    },
  },
  crossOriginEmbedderPolicy: false,
}));
app.use(express.json({ limit: '20mb' }));
app.use(express.urlencoded({ extended: true, limit: '20mb' }));

// 静态文件
app.use(express.static(path.join(__dirname, 'public')));

// traceId 中间件
app.use(middleware.traceIdMiddleware);

// CORS（debt-15：默认拒绝通配符 '*'，强制精确来源）
app.use(middleware.corsMiddleware());
app.options('*', middleware.optionsHandler);

// ── 鉴权（debt-12：分级保护） ───────────────────────────────────────
app.use(createAuthMiddleware());

// ── 限流（debt-15：/api/analyze-* 每分钟 10 次，防止 GPU 被刷爆） ──
// debt-15 audit 修复：使用 express-rate-limit 内置 ipKeyGenerator 助手，
// 避免 IPv6 场景下的 ValidationError 与限流绕过。
const { ipKeyGenerator } = require('express-rate-limit');
const analyzeLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 10,
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    success: false,
    error: '请求过于频繁：分析接口限制每分钟 10 次，请稍后再试',
    code: 'RATE_LIMITED',
  },
  // 深度复审修复：req.path 在挂载点是相对路径（如 '/text'），
  // 必须用 req.originalUrl 检查原始路径才能正确匹配。
  keyGenerator: (req, res) => ipKeyGenerator(req, res),
  skip: (req) => !req.originalUrl.startsWith('/api/analyze-'),
});
app.use('/api/analyze-', analyzeLimiter);

// ── 路由挂载 ────────────────────────────────────────────────────────
// 注入运行时上下文到路由模块
analysisRoutes.setSchemaContext({
  bridgeParamSchema: BRIDGE_PARAM_SCHEMA,
  superBridgeParamSchema: SUPER_BRIDGE_PARAM_SCHEMA,
  probedLlamaModels: PROBED_LLAMA_MODELS,
});
systemRoutes.setRuntimeContext({
  probedLlamaModels: PROBED_LLAMA_MODELS,
  bridgeParamSchema: BRIDGE_PARAM_SCHEMA,
  superBridgeParamSchema: SUPER_BRIDGE_PARAM_SCHEMA,
  pythonEnv,
});

// /api/analyze-*、/api/cancel/:id、/api/result/:id、/api/report/:id、/api/retry/:id
// 注意：analysis 路由内部路径不含 /api 前缀（由 mount 时拼接）
app.use('/api', analysisRoutes.router);
app.use('/api/jobs', jobsRoutes);
app.use('/api', systemRoutes.router);
app.use('/api/admin', adminRoutes.router);

// 全局错误处理
app.use(middleware.errorHandler);

// ── 周期性清理（debt-14：含 inputs 清理） ─────────────────────────
const adminCleanup = require('./routes/admin');
const cleanupInterval = setInterval(adminCleanup.cleanupOldOutputs, Math.min(CONFIG.outputTtlMs, 3600000));
const startupCleanupTimer = setTimeout(adminCleanup.cleanupOldOutputs, 5000);
// debt-14：缓存 TTL 定期清理
const cacheTtlInterval = startCacheTtlSweeper();

// ── 启动监听 ────────────────────────────────────────────────────────
// P1 修缮 (2026-07-25 元审计 Round 12.10): host 收窄到 127.0.0.1
// 原实现 app.listen(PORT) 未指定 host，等价于隐式 0.0.0.0（暴露至 LAN/公网）
// 默认仅本机访问；如需外部访问，显式设置 TRACE_HOST=0.0.0.0
const HOST = process.env.TRACE_HOST || '127.0.0.1';
const server = app.listen(PORT, HOST, () => {
  console.log(`TRACE Engine Web MVP 运行在 http://${HOST}:${PORT}`);
  console.log(`工作目录: ${WORK_DIR}`);
  console.log(`Skill 目录: ${CONFIG.skillDir}`);
  console.log(`输出 TTL: ${CONFIG.outputTtlMs}ms`);
  console.log(`最大并发任务: ${CONFIG.maxConcurrentJobs}, 超时: ${CONFIG.jobTimeoutMs}ms`);
  if (process.env.TRACE_API_KEY) {
    console.log(`API 鉴权: 已启用（TRACE_API_KEY 已配置）`);
  } else {
    console.log(`API 鉴权: 未启用（开发模式，TRACE_API_KEY 未设置）`);
  }
  logToFile('info', `服务启动 port=${PORT} work=${WORK_DIR} skill=${CONFIG.skillDir}`);
});

// ── 优雅关闭 ────────────────────────────────────────────────────────
function gracefulShutdown(signal) {
  console.log(`[${signal}] 正在优雅关闭服务...`);
  logToFile('info', `收到 ${signal}，开始优雅关闭`);
  server.close(() => {
    // 遍历活跃任务，区分真实子进程与 SUPER 占位对象分别处理
    for (const [id, proc] of activeJobs.entries()) {
      try {
        if (proc && typeof proc.kill === 'function') {
          utils.killProcessWithFallback(proc);
        } else if (proc && typeof proc.cancel === 'function') {
          proc.cancel();
        }
        utils.recordJob(id, null, 'terminated_by_shutdown');
      } catch (_) {}
    }
    // 显式终止常驻 LLaMA Worker
    llamaWorkerSvc.terminateLlamaWorker();
    // 清理全局定时器
    try { clearInterval(cleanupInterval); } catch (_) {}
    try { clearTimeout(startupCleanupTimer); } catch (_) {}
    try { clearInterval(cacheTtlInterval); } catch (_) {}
    utils.persistJobHistory();
    console.log('[shutdown] 服务已关闭');
    process.exit(0);
  });
}
process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));
process.on('uncaughtException', (err) => {
  logToFile('fatal', `未捕获异常: ${err.stack || err.message}`);
  console.error('未捕获异常:', err);
  process.exit(1);
});

// 暴露内部对象给路由模块（仅在 gracefulShutdown 中需要）
module.exports = { app, server, BUILD_INFO, VERSION };
