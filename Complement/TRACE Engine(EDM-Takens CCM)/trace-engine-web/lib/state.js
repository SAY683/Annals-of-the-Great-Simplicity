/**
 * TRACE Engine Web — 共享状态模块
 * =====================================
 * 集中管理跨模块复用的运行时状态、配置与路径，避免循环依赖。
 * 所有模块通过 require('../lib/state') 读取同一份单例状态。
 */
const path = require('path');
const fs = require('fs');

// ── 版本与构建信息 ─────────────────────────────────────────────────────
function loadPackageVersion() {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf-8'));
    return pkg.version || '0.2.0';
  } catch (_) {
    return '0.2.0';
  }
}

const VERSION = process.env.TRACE_WEB_VERSION || loadPackageVersion();
const BUILD_INFO = {
  version: VERSION,
  node: process.version,
  platform: process.platform,
  startedAt: new Date().toISOString(),
};

// ── 工作目录 ───────────────────────────────────────────────────────────
const WORK_DIR = process.env.TRACE_WORK_DIR
  ? path.resolve(process.env.TRACE_WORK_DIR)
  : path.resolve(__dirname, '..', 'work');
const UPLOAD_DIR = path.join(WORK_DIR, 'uploads');
const OUTPUT_DIR = path.join(WORK_DIR, 'outputs');
const INPUTS_DIR = path.join(WORK_DIR, 'inputs');
const HISTORY_FILE = path.join(WORK_DIR, 'job_history.json');
const LOG_FILE = path.join(WORK_DIR, 'server.log');
const MAX_LOG_SIZE = parseInt(process.env.TRACE_MAX_LOG_SIZE || '10485760', 10); // 10MB
const MAX_LOG_BACKUPS = parseInt(process.env.TRACE_MAX_LOG_BACKUPS || '3', 10);

function ensureDir(d) {
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
}

function initWorkDir() {
  try {
    ensureDir(WORK_DIR);
    ensureDir(UPLOAD_DIR);
    ensureDir(OUTPUT_DIR);
    ensureDir(INPUTS_DIR);
  } catch (err) {
    console.error(`[FATAL] 无法创建工作目录 ${WORK_DIR}: ${err.message}`);
    process.exit(1);
  }
}
initWorkDir();

// ── 系统配置 ───────────────────────────────────────────────────────────
const CONFIG = {
  port: parseInt(process.env.PORT || '3000', 10),
  skillDir: process.env.TRACE_ENGINE_SKILL_DIR
    ? path.resolve(process.env.TRACE_ENGINE_SKILL_DIR)
    : path.resolve(__dirname, '..', '..', 'trace-engine', 'examples', 'counterfactual_hybrid'),
  outputTtlMs: parseInt(process.env.TRACE_OUTPUT_TTL_MS || '86400000', 10),
  inputsTtlMs: parseInt(process.env.TRACE_INPUTS_TTL_MS || '86400000', 10),
  maxCacheEntries: parseInt(process.env.TRACE_MAX_CACHE || '32', 10),
  cacheTtlMs: parseInt(process.env.TRACE_CACHE_TTL_MS || (30 * 60 * 1000).toString(), 10), // 30 分钟
  maxJobHistory: parseInt(process.env.TRACE_MAX_JOB_HISTORY || '100', 10),
  maxTextLength: parseInt(process.env.TRACE_MAX_TEXT_LENGTH || '500000', 10),
  pythonCmd: process.env.TRACE_PYTHON_CMD || 'python',
  maxConcurrentJobs: parseInt(process.env.TRACE_MAX_CONCURRENT || '2', 10),
  jobTimeoutMs: parseInt(process.env.TRACE_JOB_TIMEOUT_MS || '600000', 10),
  deepJobTimeoutMs: parseInt(process.env.TRACE_DEEP_JOB_TIMEOUT_MS || '1320000', 10), // DEEP 模式：反驳+六战士+稳定性 最长约 22 分钟
  bridgeConfig: process.env.TRACE_BRIDGE_CONFIG || '',
};

// ── 运行时状态（跨模块共享） ──────────────────────────────────────────
// 活跃任务表（用于取消与状态查询）
const activeJobs = new Map();
// 活跃任务响应对象，用于取消时通知前端
const activeJobResponses = new Map();
// 已完成任务历史（启动时尝试从磁盘恢复）
const jobHistory = [];
// 结果缓存: key=hash(text+mode+config), value={id, timestamp}
const resultCache = new Map();
// 任务队列（用于并发控制）
const jobQueue = [];

// SUPER 模式常驻 LLaMA Worker 状态（由 services/llamaWorker.js 维护）
const llamaState = {
  worker: null,
  ready: false,
  starting: false,
  busy: false,
  startWaiters: [],
  jobWaiters: [],
  logs: [],
  currentHandler: null,
};
const MAX_WORKER_LOGS = 200;

// SSE 事件 ID 计数器（用于 debt-11 重连支持）
let sseEventIdCounter = 0;
function nextSseEventId() {
  sseEventIdCounter += 1;
  return sseEventIdCounter;
}

// 启动时间戳（用于运行时指标）
const startedAt = new Date();

module.exports = {
  // 版本与构建信息
  VERSION,
  BUILD_INFO,
  // 工作目录
  WORK_DIR,
  UPLOAD_DIR,
  OUTPUT_DIR,
  INPUTS_DIR,
  HISTORY_FILE,
  LOG_FILE,
  MAX_LOG_SIZE,
  MAX_LOG_BACKUPS,
  ensureDir,
  // 配置
  CONFIG,
  // 共享状态
  activeJobs,
  activeJobResponses,
  jobHistory,
  resultCache,
  jobQueue,
  llamaState,
  MAX_WORKER_LOGS,
  // SSE 事件 ID
  nextSseEventId,
  // 启动时间
  startedAt,
};
