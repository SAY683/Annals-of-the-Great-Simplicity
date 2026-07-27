/**
 * TRACE Engine Web — 分析相关路由（debt-08）
 * =====================================
 * 包含：/api/analyze-text、/api/analyze-file、/api/analyze-stream（GET/POST）、
 * /api/cancel/:id、/api/result/:id、/api/report/:id、/api/retry/:id
 */
const express = require('express');
const path = require('path');
const fs = require('fs');
const multer = require('multer');
const { v4: uuidv4 } = require('uuid');

const router = express.Router();

const state = require('../lib/state');
const utils = require('../lib/utils');
const analysis = require('../services/analysis');
const {
  CONFIG,
  UPLOAD_DIR,
  OUTPUT_DIR,
  INPUTS_DIR,
  activeJobs,
  activeJobResponses,
  jobQueue,
  jobHistory,
  resultCache,
} = state;
const {
  reqLog,
  isValidId,
  parseBridgeConfig,
  validateAnalysisInput,
  killProcessWithFallback,
  cacheKey,
} = utils;
const { sendSSE, sendSSERetryHeader, runPythonAnalysisStream, runSuperAnalysisStream, runPythonAnalysisSync, processJobQueue } = analysis;

// 文件上传配置（使用 diskStorage，兼容 multer 1.x 与 2.x）
const upload = multer({
  storage: multer.diskStorage({
    destination: (_req, _file, cb) => {
      if (!fs.existsSync(UPLOAD_DIR)) fs.mkdirSync(UPLOAD_DIR, { recursive: true });
      cb(null, UPLOAD_DIR);
    },
    filename: (_req, file, cb) => {
      const safeName = path.basename(file.originalname).replace(/[^\w.\-]/g, '_');
      const unique = `${Date.now()}-${Math.round(Math.random() * 1e9)}-${safeName}`;
      cb(null, unique);
    },
  }),
  limits: { fileSize: 10 * 1024 * 1024 },
  fileFilter: (_req, file, cb) => {
    const allowed = ['text/plain', 'text/markdown'];
    if (allowed.includes(file.mimetype) || file.originalname.endsWith('.txt') || file.originalname.endsWith('.md')) {
      cb(null, true);
    } else {
      cb(new Error('仅支持 .txt / .md 文本文件'));
    }
  },
});

// Schema 上下文（由 server.js 注入，包含 bridgeParamSchema/superBridgeParamSchema/probedLlamaModels）
let _schemaCtx = {
  bridgeParamSchema: null,
  superBridgeParamSchema: null,
  probedLlamaModels: [],
};
function setSchemaContext(ctx) {
  _schemaCtx = { ..._schemaCtx, ...ctx };
}

// ── SSE 流式分析入口 ────────────────────────────────────────────────
function handleAnalyzeStream(req, res) {
  const id = req.query.id || req.body.id || uuidv4();
  const text = req.query.text || req.body.text;
  const mode = (req.query.mode || req.body.mode || 'light').toLowerCase();
  let bridgeConfig = parseBridgeConfig(req.query.config || req.body.config);

  const cfgObj = bridgeConfig ? (() => { try { return JSON.parse(bridgeConfig); } catch (_) { return null; } })() : null;
  const validation = validateAnalysisInput(text, mode, cfgObj, _schemaCtx);
  if (!validation.ok) {
    reqLog(req, 'warn', `SSE 输入校验失败: ${validation.error} (${validation.code || ''})`);
    return res.status(400).json({ success: false, error: validation.error, code: validation.code, field: validation.field, traceId: req.traceId });
  }
  if (cfgObj && typeof cfgObj === 'object') {
    bridgeConfig = JSON.stringify(cfgObj);
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  // debt-11：发送 retry: 30000，告知客户端 30 秒重连间隔（跨项目契约对齐 trace-to-edm/server.js）
  sendSSERetryHeader(res);

  if (activeJobs.size >= CONFIG.maxConcurrentJobs) {
    jobQueue.push({ id, text, mode, bridgeConfig, res });
    const msg = `当前并发任务已满（${activeJobs.size}/${CONFIG.maxConcurrentJobs}），任务 ${id ? id.slice(0, 8) : '未知'} 已进入队列，前面还有 ${jobQueue.length - 1} 个任务。`;
    sendSSE(res, 'log', { level: 'warn', message: msg });
    reqLog(req, 'warn', msg);
    return;
  }

  if (mode === 'super') {
    runSuperAnalysisStream(text, id, bridgeConfig, res);
  } else {
    runPythonAnalysisStream(text, id, mode, bridgeConfig, res, _schemaCtx);
  }
}

// P2-11：GET 仅用于短文本探针；长文本必须改用 POST
router.get('/analyze-stream', handleAnalyzeStream);
router.post('/analyze-stream', handleAnalyzeStream);

// ── 同步分析：纯文本 ────────────────────────────────────────────────
router.post('/analyze-text', async (req, res) => {
  try {
    const text = req.body.text || '';
    const mode = (req.body.mode || 'light').toLowerCase();
    let bridgeConfig = parseBridgeConfig(req.body.config);
    const cfgObj = bridgeConfig ? JSON.parse(bridgeConfig) : null;

    const validation = validateAnalysisInput(text, mode, cfgObj, _schemaCtx);
    if (!validation.ok) {
      reqLog(req, 'warn', `输入校验失败: ${validation.error} (${validation.code || ''})`);
      return res.status(400).json({ success: false, error: validation.error, code: validation.code, field: validation.field, traceId: req.traceId });
    }
    if (mode === 'super') {
      return res.status(400).json({ success: false, error: 'SUPER 模式请使用 /api/analyze-stream 流式接口', code: 'SUPER_REQUIRES_STREAM', traceId: req.traceId });
    }
    if (cfgObj && typeof cfgObj === 'object') {
      bridgeConfig = JSON.stringify(cfgObj);
    }

    // 深度复审修复：sync 路径也需检查并发限制，否则可绕过 maxConcurrentJobs
    if (activeJobs.size >= CONFIG.maxConcurrentJobs) {
      return res.status(429).json({
        success: false,
        error: `并发数已达上限（${CONFIG.maxConcurrentJobs}），请使用 /api/analyze-stream 排队或稍后重试`,
        code: 'TOO_MANY_CONCURRENT',
        traceId: req.traceId,
      });
    }

    // 缓存命中检查
    const cacheK = cacheKey(text, mode, cfgObj);
    const cached = resultCache.get(cacheK);
    if (cached && fs.existsSync(path.join(OUTPUT_DIR, cached.id, 'result.json'))) {
      return res.json({
        success: true,
        cached: true,
        traceId: req.traceId,
        data: {
          id: cached.id,
          result: JSON.parse(fs.readFileSync(path.join(OUTPUT_DIR, cached.id, 'result.json'), 'utf-8')),
          reportPath: fs.existsSync(path.join(OUTPUT_DIR, cached.id, 'report.md'))
            ? `/api/report/${cached.id}`
            : null,
          resultPath: `/api/result/${cached.id}`,
        },
      });
    }

    const id = uuidv4();
    const data = await runPythonAnalysisSync(text, id, mode, bridgeConfig);
    res.json({ success: true, cached: false, traceId: req.traceId, data });
  } catch (err) {
    reqLog(req, 'error', `分析失败: ${err.message}`);
    res.status(500).json({ success: false, error: err.message, traceId: req.traceId });
  }
});

// ── 同步分析：文件上传 ──────────────────────────────────────────────
router.post('/analyze-file', upload.single('file'), async (req, res) => {
  try {
    if (!req.file) return res.status(400).json({ success: false, error: '未上传文件' });
    const text = fs.readFileSync(req.file.path, 'utf-8');
    const mode = (req.body.mode || 'light').toLowerCase();
    let bridgeConfig = parseBridgeConfig(req.body.config);
    const cfgObj = bridgeConfig ? JSON.parse(bridgeConfig) : null;

    const validation = validateAnalysisInput(text, mode, cfgObj, _schemaCtx);
    if (!validation.ok) {
      fs.unlinkSync(req.file.path);
      reqLog(req, 'warn', `文件上传输入校验失败: ${validation.error}`);
      return res.status(400).json({ success: false, error: validation.error, code: validation.code, field: validation.field, traceId: req.traceId });
    }
    if (mode === 'super') {
      fs.unlinkSync(req.file.path);
      return res.status(400).json({ success: false, error: 'SUPER 模式请使用 /api/analyze-stream 流式接口', code: 'SUPER_REQUIRES_STREAM', traceId: req.traceId });
    }
    if (cfgObj && typeof cfgObj === 'object') {
      bridgeConfig = JSON.stringify(cfgObj);
    }
    // 深度复审修复：sync 路径并发检查
    if (activeJobs.size >= CONFIG.maxConcurrentJobs) {
      fs.unlinkSync(req.file.path);
      return res.status(429).json({
        success: false,
        error: `并发数已达上限（${CONFIG.maxConcurrentJobs}），请使用 /api/analyze-stream 排队或稍后重试`,
        code: 'TOO_MANY_CONCURRENT',
        traceId: req.traceId,
      });
    }
    const id = uuidv4();
    const data = await runPythonAnalysisSync(text, id, mode, bridgeConfig);
    fs.unlinkSync(req.file.path);
    res.json({ success: true, traceId: req.traceId, data });
  } catch (err) {
    if (req.file && req.file.path && fs.existsSync(req.file.path)) {
      try { fs.unlinkSync(req.file.path); } catch (_) {}
    }
    reqLog(req, 'error', `文件分析失败: ${err.message}`);
    res.status(500).json({ success: false, error: err.message, traceId: req.traceId });
  }
});

// ── 主动取消任务 ────────────────────────────────────────────────────
router.post('/cancel/:id', (req, res) => {
  const id = req.params.id;
  const queueIdx = jobQueue.findIndex((j) => j.id === id);
  if (queueIdx >= 0) {
    const removed = jobQueue.splice(queueIdx, 1)[0];
    // P1-e 修缮：队列取消时补发 SSE error + done 事件，与其他三条取消路径对齐
    // 之前仅 res.end() 导致前端看不到终止信号，可能触发自动重连
    try {
      sendSSE(removed.res, 'error', { message: '任务在队列中被取消' });
      sendSSE(removed.res, 'done', { code: 125 });
      removed.res.end();
    } catch (_) {}
    utils.recordJob(id, removed.mode, 'cancelled', '任务在队列中被取消');
    reqLog(req, 'info', `任务在队列中取消 job=${id}`);
    return res.json({ success: true, cancelled: true, reason: 'removed_from_queue' });
  }

  const proc = activeJobs.get(id);
  const jobRes = activeJobResponses.get(id);
  if (!proc) {
    return res.status(404).json({ success: false, error: '未找到运行中任务' });
  }

  // SUPER 等待中
  if (proc.isSuperQueued && !proc.isRunning) {
    proc.cancel();
    activeJobs.delete(id);
    activeJobResponses.delete(id);
    if (jobRes) {
      try {
        sendSSE(jobRes.res, 'error', { message: '用户主动停止计算' });
        sendSSE(jobRes.res, 'done', { code: 125 });
        jobRes.res.end();
      } catch (_) {}
    }
    utils.recordJob(id, 'super', 'cancelled', '等待 Worker 期间被用户取消');
    reqLog(req, 'info', `用户取消等待中的 SUPER 任务 job=${id}`);
    return res.json({ success: true, cancelled: true, reason: 'super_queued_cancelled' });
  }

  // SUPER 运行中
  if (jobRes && jobRes.mode === 'super') {
    try {
      proc.stdin.write(JSON.stringify({ type: 'cancel', id }) + '\n', 'utf-8');
    } catch (err) {
      reqLog(req, 'warn', `SUPER 取消信号发送失败 job=${id}: ${err.message}`);
    }
    state.llamaState.currentHandler = null;
    // 复用 llamaWorker 释放逻辑（避免循环依赖，直接操作状态）
    state.llamaState.busy = false;
    state.llamaState.currentHandler = null;
    const next = state.llamaState.jobWaiters.shift();
    if (next) next();
    activeJobs.delete(id);
    activeJobResponses.delete(id);
    if (jobRes) {
      try {
        sendSSE(jobRes.res, 'error', { message: '用户主动停止计算' });
        sendSSE(jobRes.res, 'done', { code: 125 });
        jobRes.res.end();
      } catch (_) {}
    }
    utils.recordJob(id, 'super', 'cancelled', '用户主动停止');
    reqLog(req, 'info', `用户主动取消 SUPER 任务（发送取消信号）job=${id}`);
    return res.json({ success: true, cancelled: true, reason: 'super_cancel_signal' });
  }

  // 普通子进程
  try {
    killProcessWithFallback(proc);
  } catch (err) {
    reqLog(req, 'warn', `取消任务 kill 失败 job=${id}: ${err.message}`);
  }
  activeJobs.delete(id);
  activeJobResponses.delete(id);
  if (jobRes) {
    try {
      sendSSE(jobRes.res, 'error', { message: '用户主动停止计算' });
      sendSSE(jobRes.res, 'done', { code: 125 });
      jobRes.res.end();
    } catch (_) {}
  }
  utils.recordJob(id, jobRes?.mode || 'unknown', 'cancelled', '用户主动停止');
  reqLog(req, 'info', `用户主动取消任务 job=${id}`);
  res.json({ success: true, cancelled: true, reason: 'process_terminated' });
});

// ── 获取结果 JSON ───────────────────────────────────────────────────
router.get('/result/:id', (req, res) => {
  if (!isValidId(req.params.id)) {
    return res.status(400).json({ success: false, error: '非法的任务 ID', code: 'ERROR' });
  }
  const resultPath = path.join(OUTPUT_DIR, req.params.id, 'result.json');
  if (!fs.existsSync(resultPath)) return res.status(404).json({ success: false, error: '结果不存在', code: 'ERROR' });
  res.setHeader('Content-Type', 'application/json');
  res.sendFile(resultPath);
});

// ── 获取报告 Markdown ───────────────────────────────────────────────
router.get('/report/:id', (req, res) => {
  if (!isValidId(req.params.id)) {
    return res.status(400).json({ success: false, error: '非法的任务 ID', code: 'ERROR' });
  }
  const reportPath = path.join(OUTPUT_DIR, req.params.id, 'report.md');
  if (!fs.existsSync(reportPath)) return res.status(404).json({ success: false, error: '报告不存在', code: 'ERROR' });
  res.setHeader('Content-Type', 'text/markdown; charset=utf-8');
  res.sendFile(reportPath);
});

// ── 任务重试 ────────────────────────────────────────────────────────
router.post('/retry/:id', async (req, res) => {
  const id = req.params.id;
  // P0-1 (Round 21 §P0-A): 路径遍历防护 — retry 路由的 :id 会进入 path.join(INPUTS_DIR, ${id}.txt)
  // 必须先校验 UUID 格式, 否则攻击者可传 id=../../etc/passwd 读取任意文件
  if (!isValidId(id)) {
    return res.status(400).json({ success: false, error: '非法的任务 ID', code: 'INVALID_ID', traceId: req.traceId });
  }
  const old = jobHistory.find((j) => j.id === id);
  if (!old) {
    return res.status(404).json({ success: false, error: '未找到该任务历史', code: 'JOB_NOT_FOUND', traceId: req.traceId });
  }
  if (!['error', 'timeout', 'cancelled'].includes(old.status)) {
    return res.status(400).json({ success: false, error: `当前状态 ${old.status} 不支持重试` });
  }
  let retryText = old.text;
  if (!retryText) {
    const inputPath = path.join(INPUTS_DIR, `${id}.txt`);
    if (!fs.existsSync(inputPath)) {
      return res.status(400).json({ success: false, error: '历史记录中未保留原始文本，无法重试' });
    }
    try {
      retryText = fs.readFileSync(inputPath, 'utf-8');
    } catch (err) {
      return res.status(400).json({ success: false, error: `读取历史文本失败: ${err.message}` });
    }
  }
  if (old.mode === 'super') {
    return res.status(400).json({ success: false, error: 'SUPER 模式不支持同步重试，请在前端重新提交分析', code: 'SUPER_RETRY_NOT_SUPPORTED', originalId: id });
  }
  let retryCfgObj = null;
  if (old.config) {
    try { retryCfgObj = JSON.parse(old.config); } catch (_) { retryCfgObj = null; }
  }
  const retryValidation = validateAnalysisInput(retryText, old.mode || 'light', retryCfgObj, _schemaCtx);
  if (!retryValidation.ok) {
    return res.status(400).json({ success: false, error: retryValidation.error, code: retryValidation.code || 'RETRY_VALIDATION_FAILED', field: retryValidation.field, originalId: id });
  }
  const retryConfig = retryCfgObj && typeof retryCfgObj === 'object' ? JSON.stringify(retryCfgObj) : (old.config || '');
  const newId = uuidv4();
  try {
    const data = await runPythonAnalysisSync(retryText, newId, old.mode || 'light', retryConfig);
    res.json({ success: true, message: '重试任务已启动', originalId: id, newId, data });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

module.exports = {
  router,
  setSchemaContext,
};
