/**
 * TRACE Engine Web — 系统路由（debt-08）
 * =====================================
 * 包含：/api/health、/api/config、/api/version、/api/queue、/api/metrics、
 * /api/schema（含 resultSchema，debt-10）、/api/presets（从 presets.yaml 加载，debt-16）
 */
const express = require('express');
const fs = require('fs');
const path = require('path');

const router = express.Router();

const state = require('../lib/state');
const utils = require('../lib/utils');
const llamaWorkerSvc = require('../services/llamaWorker');
const {
  CONFIG,
  WORK_DIR,
  BUILD_INFO,
  VERSION,
  activeJobs,
  jobQueue,
  resultCache,
  jobHistory,
  llamaState,
  startedAt,
} = state;
const {
  validateSkillDir,
  loadResultSchema,
  loadPresets,
} = utils;

// 由 server.js 注入的运行时上下文
let _runtimeCtx = {
  probedLlamaModels: [],
  bridgeParamSchema: null,
  superBridgeParamSchema: null,
  pythonEnv: { ok: false },
  cleanupInterval: null,
};
function setRuntimeContext(ctx) {
  _runtimeCtx = { ..._runtimeCtx, ...ctx };
}

// 磁盘空间检查
function getDiskSpaceInfo() {
  try {
    const testFile = path.join(WORK_DIR, '.space_probe');
    fs.writeFileSync(testFile, '1');
    fs.unlinkSync(testFile);
    return { writable: true };
  } catch (err) {
    return { writable: false, error: err.message };
  }
}

// ── 健康检查 ────────────────────────────────────────────────────────
router.get('/health', (_req, res) => {
  const validation = validateSkillDir();
  const disk = getDiskSpaceInfo();
  const pythonEnv = _runtimeCtx.pythonEnv || { ok: false };
  const status = validation.ok && disk.writable && pythonEnv.ok ? 'healthy' : 'degraded';
  res.json({
    success: true,
    status,
    skillReady: validation.ok,
    pythonReady: pythonEnv.ok,
    skillDir: CONFIG.skillDir,
    skillValidation: validation,
    pythonEnv,
    workDir: WORK_DIR,
    disk,
    activeJobs: activeJobs.size,
    queuedJobs: jobQueue.length,
    cacheSize: resultCache.size,
    jobHistory: jobHistory.length,
    timestamp: new Date().toISOString(),
  });
});

// ── 配置信息 ────────────────────────────────────────────────────────
router.get('/config', (_req, res) => {
  const llamaScript = llamaWorkerSvc.getLlamaWorkerScript();
  const llamaAvailable = fs.existsSync(llamaScript);

  res.json({
    success: true,
    config: { ...CONFIG, skillDir: CONFIG.skillDir },
    bridgeParamSchema: _runtimeCtx.bridgeParamSchema || {},
    superBridgeParamSchema: _runtimeCtx.superBridgeParamSchema || {},
    modes: {
      light: { label: 'LIGHT', description: '快速 jieba 概念图 + 简化流程' },
      deep: { label: 'DEEP', description: '完整六战士 + 稳定性检查（jieba 概念图）' },
      super: { label: 'SUPER', description: 'LLaMA TRACE 模型驱动 + 完整六合一（最慢最准）', available: llamaAvailable && _runtimeCtx.probedLlamaModels.length > 0 },
    },
    presets: Object.keys(loadPresets()),
    llamaModels: {
      default: 'shehui-llama',
      available: _runtimeCtx.probedLlamaModels,
    },
    llamaWorker: {
      available: llamaAvailable,
      script: llamaScript,
      ready: llamaState.ready,
      busy: llamaState.busy,
    },
    buildInfo: BUILD_INFO,
  });
});

// ── 队列状态 ────────────────────────────────────────────────────────
router.get('/queue', (_req, res) => {
  res.json({
    success: true,
    active: Array.from(activeJobs.keys()),
    queued: jobQueue.map((j) => ({ id: j.id, mode: j.mode, textLength: j.text.length })),
    maxConcurrent: CONFIG.maxConcurrentJobs,
  });
});

// ── 版本与服务识别 ──────────────────────────────────────────────────
router.get('/version', (_req, res) => {
  res.json({
    success: true,
    ...BUILD_INFO,
    skillReady: validateSkillDir().ok,
    pythonCmd: CONFIG.pythonCmd,
  });
});

// ── 参数预设（debt-16：从 presets.yaml / bridge_schema.json 加载） ──
router.get('/presets', (_req, res) => {
  const presets = utils.loadPresets();
  res.json({
    success: true,
    presets,
  });
});

// ── 参数 Schema + 结果 Schema（debt-10） ────────────────────────────
router.get('/schema', (_req, res) => {
  const resultSchema = loadResultSchema();
  res.json({
    success: true,
    schema: _runtimeCtx.bridgeParamSchema || {},
    superSchema: _runtimeCtx.superBridgeParamSchema || {},
    resultSchema: resultSchema || null,
    modes: ['light', 'deep', 'super'],
    presets: Object.keys(loadPresets()),
  });
});

// ── 运行时指标 ──────────────────────────────────────────────────────
router.get('/metrics', (_req, res) => {
  const statusCounts = jobHistory.reduce((acc, j) => {
    acc[j.status] = (acc[j.status] || 0) + 1;
    return acc;
  }, {});
  res.json({
    success: true,
    activeJobs: activeJobs.size,
    queuedJobs: jobQueue.length,
    cacheSize: resultCache.size,
    jobHistoryTotal: jobHistory.length,
    statusCounts,
    skillReady: validateSkillDir().ok,
    llamaWorkerReady: llamaState.ready,
    llamaWorkerBusy: llamaState.busy,
    llamaWorkerJobWaiters: llamaState.jobWaiters.length,
    uptimeSeconds: Math.floor((Date.now() - startedAt.getTime()) / 1000),
    timestamp: new Date().toISOString(),
  });
});

module.exports = {
  router,
  setRuntimeContext,
};
