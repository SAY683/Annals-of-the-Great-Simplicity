/**
 * TRACE Engine Web MVP — NodeJS 服务端
 * =====================================
 * 提供 HTTP + SSE 接口，接收文本上传，实时流式调用 Python Skill 进行因果计算。
 *
 * 系统工程增强:
 *   - 任务历史与状态查询
 *   - 简单内存缓存（相同文本+模式复用结果）
 *   - 输出目录 TTL 清理
 *   - 健康检查与配置端点
 *   - SUPER 模式常驻 LLaMA Worker
 *   - 任务队列与并发控制
 *
 * 端点 (20 routes):
 *   POST /api/analyze-text         分析纯文本 (JSON: {text, mode})
 *   POST /api/analyze-file         上传文本文件分析 (multipart: file, mode)
 *   GET  /api/analyze-stream?id=   SSE 实时流（阶段+日志+结果）
 *   POST /api/analyze-stream       SSE 流（POST 别名）
 *   POST /api/cancel/:id           取消分析任务
 *   GET  /api/result/:id           获取分析结果 (JSON)
 *   GET  /api/report/:id           获取 Markdown 报告
 *   GET  /api/jobs                 任务历史列表
 *   GET  /api/jobs/export          导出任务历史 (JSON/CSV)
 *   POST /api/jobs/clear           清空任务历史
 *   GET  /api/jobs/:id             查询单个任务状态
 *   POST /api/retry/:id            重试任务（SUPER 模式不支持）
 *   POST /api/admin/cleanup        手动触发输出目录 TTL 清理
 *   GET  /api/health               健康检查
 *   GET  /api/config               当前配置 + bridgeParamSchema
 *   GET  /api/queue                任务队列状态
 *   GET  /api/version              版本信息
 *   GET  /api/presets              参数预设（含 SUPER）
 *   GET  /api/schema               Bridge 参数 Schema
 *   GET  /api/metrics              运行时指标
 *   GET  /                         前端页面
 */

const express = require('express');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { spawn } = require('child_process');
const { v4: uuidv4 } = require('uuid');

const app = express();
const PORT = process.env.PORT || 3000;

// 版本与构建信息（用于多云部署时的服务识别）
// 优先从 package.json 读取版本，保证 package.json / README / 运行时一致
function loadPackageVersion() {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, 'package.json'), 'utf-8'));
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

// 通过 Python Skill 探测模型目录（兼容开发布局与层级成品布局）
function probeLlamaModels() {
  const models = [];
  const skillDir = process.env.TRACE_ENGINE_SKILL_DIR
    ? path.resolve(process.env.TRACE_ENGINE_SKILL_DIR)
    : path.resolve(__dirname, '..', 'trace-engine', 'examples', 'counterfactual_hybrid');

  const tmpFile = path.join(WORK_DIR, `_probe_models_${Date.now()}.py`);
  const script = `import sys, json
sys.path.insert(0, ${JSON.stringify(skillDir)})
try:
    from project_paths import resolve_paths
    p = resolve_paths()
    for name in ['shehui-llama', 'shenji-llama', 'shehui-llama-v4-archive', 'Shehui-LLaMA', 'Shenji-LLaMA']:
        d = p.model_dir(name)
        if d.exists() and (d / 'model.safetensors').exists():
            print(json.dumps({'id': name.lower(), 'name': name, 'path': str(d)}))
except Exception as e:
    print(json.dumps({'error': str(e)}))
`;
  try {
    fs.writeFileSync(tmpFile, script, { encoding: 'utf-8' });
    // S18：统一 Python 命令变量——优先 TRACE_PYTHON_CMD（与 CONFIG.pythonCmd 一致），
    // 回退 PYTHON_CMD（向后兼容），最后回退 'python'，避免探测与分析使用不同解释器
    const probePythonCmd = process.env.TRACE_PYTHON_CMD || process.env.PYTHON_CMD || 'python';
    const result = require('child_process').execSync(
      `${probePythonCmd} "${tmpFile}"`,
      { encoding: 'utf-8', timeout: 15000, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }
    );
    for (const line of result.trim().split(/\r?\n/)) {
      if (!line.trim()) continue;
      try {
        const obj = JSON.parse(line);
        if (obj.error) {
          console.warn('[probeLlamaModels] Python probe error:', obj.error);
          continue;
        }
        if (!models.some(m => m.id === obj.id)) models.push(obj);
      } catch (e) { /* ignore */ }
    }
  } catch (err) {
    console.warn('[probeLlamaModels] probe failed:', err.message);
  } finally {
    try { fs.unlinkSync(tmpFile); } catch (e) { /* ignore */ }
  }
  return models;
}

// 工作目录（可通过环境变量覆盖，便于容器化与沙箱外部署）
const WORK_DIR = process.env.TRACE_WORK_DIR
  ? path.resolve(process.env.TRACE_WORK_DIR)
  : path.resolve(__dirname, 'work');
const UPLOAD_DIR = path.join(WORK_DIR, 'uploads');
const OUTPUT_DIR = path.join(WORK_DIR, 'outputs');
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
  } catch (err) {
    console.error(`[FATAL] 无法创建工作目录 ${WORK_DIR}: ${err.message}`);
    process.exit(1);
  }
}
initWorkDir();

// 工作目录就绪后再探测模型（probe 需要写临时脚本）
const PROBED_LLAMA_MODELS = probeLlamaModels();

// 系统配置（可从环境变量覆盖）
const CONFIG = {
  port: PORT,
  skillDir: process.env.TRACE_ENGINE_SKILL_DIR
    ? path.resolve(process.env.TRACE_ENGINE_SKILL_DIR)
    : path.resolve(__dirname, '..', 'trace-engine', 'examples', 'counterfactual_hybrid'),
  outputTtlMs: parseInt(process.env.TRACE_OUTPUT_TTL_MS || '86400000', 10), // 默认 24h
  maxCacheEntries: parseInt(process.env.TRACE_MAX_CACHE || '32', 10),
  maxJobHistory: parseInt(process.env.TRACE_MAX_JOB_HISTORY || '100', 10),
  maxTextLength: parseInt(process.env.TRACE_MAX_TEXT_LENGTH || '500000', 10),
  pythonCmd: process.env.TRACE_PYTHON_CMD || 'python',
  maxConcurrentJobs: parseInt(process.env.TRACE_MAX_CONCURRENT || '2', 10),
  jobTimeoutMs: parseInt(process.env.TRACE_JOB_TIMEOUT_MS || '300000', 10), // 默认 5min
  bridgeConfig: process.env.TRACE_BRIDGE_CONFIG || '',
};

// 活跃任务表（用于取消与状态查询）
const activeJobs = new Map();
// 活跃任务响应对象，用于取消时通知前端
const activeJobResponses = new Map();
// 已完成任务历史（启动时尝试从磁盘恢复）
const jobHistory = [];
// 结果缓存: key=hash(text+mode), value={id, timestamp}
const resultCache = new Map();
// 任务队列（用于并发控制）
const jobQueue = [];

// SUPER 模式常驻 LLaMA Worker
let llamaWorker = null;
let llamaWorkerReady = false;
let llamaWorkerStarting = false;
let llamaWorkerBusy = false;
let llamaWorkerStartWaiters = [];
let llamaWorkerJobWaiters = [];
let llamaWorkerLogs = [];
let currentLlamaHandler = null;
const MAX_WORKER_LOGS = 200;

function logWorker(line) {
  llamaWorkerLogs.push({ time: new Date().toISOString(), line });
  if (llamaWorkerLogs.length > MAX_WORKER_LOGS) llamaWorkerLogs.shift();
}

function getLlamaWorkerScript() {
  return path.resolve(__dirname, 'llama_worker.py');
}

function dispatchLlamaMessage(obj) {
  if (currentLlamaHandler) {
    currentLlamaHandler(obj);
  } else if (obj.type === 'log') {
    logWorker(`[worker] ${obj.level}: ${obj.message}`);
  } else {
    logWorker(JSON.stringify(obj));
  }
}

function spawnLlamaWorker() {
  const script = getLlamaWorkerScript();
  if (!fs.existsSync(script)) {
    logToFile('warn', `llama_worker.py 不存在，SUPER 模式不可用: ${script}`);
    return null;
  }
  logToFile('info', '正在启动 LLaMA Worker...');
  // 不强制覆盖 TRACE_ROOT，让 llama_worker.py 内部的 _config.py 自动探测：
  //   - 开发布局: 向上找到 <project_root>/TRACE
  //   - 层级成品布局: 识别 trace-engine/models/<model>/model.safetensors
  // 用户仍可通过环境变量 TRACE_ROOT 显式覆盖。
  const worker = spawn(CONFIG.pythonCmd, [script], {
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
    },
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  let stdoutBuffer = '';
  worker.stdout.on('data', (chunk) => {
    stdoutBuffer += chunk.toString('utf-8');
    const lines = stdoutBuffer.split('\n');
    stdoutBuffer = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const obj = JSON.parse(line);
        dispatchLlamaMessage(obj);
      } catch (err) {
        logWorker(line);
      }
    }
  });

  worker.stderr.on('data', (chunk) => {
    const lines = chunk.toString('utf-8').split('\n').filter(Boolean);
    for (const line of lines) {
      logWorker(line);
    }
  });

  // P1-9：worker 为常驻进程，此处一次性挂载 stdin 'error' 监听器即可，
  // 避免在 runSuperAnalysisStream 每次任务中重复挂载导致 listener 累积泄漏。
  // stdin 写入失败（如 Worker 已退出）时仅记录日志，真正的任务级错误处理
  // 由 worker 'close'/'error' 事件及 currentLlamaHandler 错误分支完成。
  worker.stdin.on('error', (err) => {
    logToFile('error', `LLaMA Worker stdin 错误: ${err.message}`);
  });

  worker.on('close', (code) => {
    logToFile('warn', `LLaMA Worker 退出 (code=${code})，清理状态`);
    // 仅通知当前关联的 SUPER 任务（通过 currentLlamaHandler 追踪的 outputId）
    if (currentLlamaHandler && currentLlamaHandler.outputId) {
      const activeId = currentLlamaHandler.outputId;
      if (activeJobs.has(activeId)) {
        recordJob(activeId, 'super', 'cancelled', `Worker 退出 code=${code}`);
        activeJobs.delete(activeId);
        const jobRes = activeJobResponses.get(activeId);
        if (jobRes) {
          try {
            sendSSE(jobRes.res, 'error', { message: `LLaMA Worker 退出 (code=${code})` });
            sendSSE(jobRes.res, 'done', { code: -1 });
            jobRes.res.end();
          } catch (_) {}
          activeJobResponses.delete(activeId);
        }
      }
    }
    llamaWorker = null;
    llamaWorkerReady = false;
    llamaWorkerStarting = false;
    llamaWorkerBusy = false;
    currentLlamaHandler = null;
    // 唤醒所有等待 Worker 空闲的任务，避免 Worker 崩溃后永久死锁
    const jobWaiters = llamaWorkerJobWaiters; llamaWorkerJobWaiters = [];
    jobWaiters.forEach((fn) => fn());
    // reject 所有等待 Worker 启动的请求
    const startWaiters = llamaWorkerStartWaiters; llamaWorkerStartWaiters = [];
    startWaiters.forEach((w) => w.reject(new Error('LLaMA Worker 退出')));
    processJobQueue();
  });

  worker.on('error', (err) => {
    logToFile('error', `LLaMA Worker 启动错误: ${err.message}`);
    llamaWorker = null;
    llamaWorkerReady = false;
    llamaWorkerStarting = false;
    llamaWorkerBusy = false;
    currentLlamaHandler = null;
    // 同样唤醒所有 waiters，避免错误后死锁
    const jobWaiters = llamaWorkerJobWaiters; llamaWorkerJobWaiters = [];
    jobWaiters.forEach((fn) => fn());
    const startWaiters = llamaWorkerStartWaiters; llamaWorkerStartWaiters = [];
    startWaiters.forEach((w) => w.reject(new Error('LLaMA Worker 启动错误: ' + err.message)));
  });

  return worker;
}

function ensureLlamaWorker() {
  return new Promise((resolve, reject) => {
    if (llamaWorker && llamaWorkerReady) return resolve(llamaWorker);
    if (llamaWorkerStarting) {
      llamaWorkerStartWaiters.push({ resolve, reject });
      return;
    }
    llamaWorkerStarting = true;
    llamaWorker = spawnLlamaWorker();
    if (!llamaWorker) {
      llamaWorkerStarting = false;
      return reject(new Error('LLaMA Worker 启动失败（llama_worker.py 不存在或环境缺失）'));
    }
    // 等待 Worker 就绪日志
    const timer = setTimeout(() => {
      llamaWorkerStarting = false;
      // P1-8：超时后清理所有等待启动的 waiter，避免永久挂起；杀死超时的 Worker 进程
      const waiters = llamaWorkerStartWaiters; llamaWorkerStartWaiters = [];
      waiters.forEach((w) => w.reject(new Error('LLaMA Worker 启动超时')));
      if (llamaWorker) {
        try { llamaWorker.kill(); } catch (_) {}
        llamaWorker = null;
      }
      llamaWorkerReady = false;
      reject(new Error('LLaMA Worker 启动超时'));
    }, 120000);

    const onData = (chunk) => {
      const text = chunk.toString('utf-8');
      if (text.includes('LLaMA Worker') && text.includes('等待任务')) {
        clearTimeout(timer);
        llamaWorker.stdout.off('data', onData);
        llamaWorkerReady = true;
        llamaWorkerStarting = false;
        resolve(llamaWorker);
        for (const waiter of llamaWorkerStartWaiters) waiter.resolve(llamaWorker);
        llamaWorkerStartWaiters = [];
      }
    };
    llamaWorker.stdout.on('data', onData);
  });
}

function waitForLlamaWorkerIdle() {
  return new Promise((resolve) => {
    if (!llamaWorkerBusy) return resolve();
    llamaWorkerJobWaiters.push(resolve);
  });
}

function releaseLlamaWorker() {
  llamaWorkerBusy = false;
  currentLlamaHandler = null;
  const next = llamaWorkerJobWaiters.shift();
  if (next) next();
}

// P2-7：终止子进程的兜底机制——先发 SIGTERM，若 delayMs（默认 5s）后仍未退出则发 SIGKILL 强制结束
// 防止 Python 子进程忽略 SIGTERM 导致僵尸进程长期占用资源
function killProcessWithFallback(proc, delayMs = 5000) {
  // 仅对真实 ChildProcess 生效（activeJobs 中可能存在 SUPER 占位对象）
  if (!proc || typeof proc.kill !== 'function' || typeof proc.once !== 'function') return;
  if (proc.exitCode !== null || proc.signalCode !== null) return;
  let killed = false;
  let fallbackTimer = null;
  const onExit = () => { killed = true; if (fallbackTimer) clearTimeout(fallbackTimer); };
  try { proc.once('exit', onExit); } catch (_) {}
  try { proc.kill('SIGTERM'); } catch (_) {}
  fallbackTimer = setTimeout(() => {
    if (killed) return;
    try { proc.kill('SIGKILL'); } catch (_) {}
  }, delayMs);
}

// P2-8：背压感知写入——write 返回 false 时等待 drain 事件，避免内部缓冲区无限膨胀
// 用于向 Worker stdin 写入较大载荷（如 SUPER 任务文本可达 500KB）
function writeWithDrain(stream, chunk, encoding = 'utf-8') {
  return new Promise((resolve, reject) => {
    const onError = (err) => { stream.off('drain', onDrain); reject(err); };
    const onDrain = () => { stream.off('error', onError); resolve(); };
    let ok;
    try {
      ok = stream.write(chunk, encoding);
    } catch (err) {
      reject(err);
      return;
    }
    if (ok) {
      resolve();
    } else {
      stream.once('drain', onDrain);
      stream.once('error', onError);
    }
  });
}

// 日志持久化 + 简单轮转
// P2-5：轮转与写入均改为异步，避免同步 fs 调用阻塞事件循环
// P2-10：引入轮转锁，避免高频日志写入触发并发轮转导致 rename 竞态
let _logRotating = false;
async function rotateLogIfNeeded() {
  if (_logRotating) return;
  _logRotating = true;
  try {
    const exists = await fs.promises.access(LOG_FILE).then(() => true).catch(() => false);
    if (!exists) return;
    const stats = await fs.promises.stat(LOG_FILE);
    if (stats.size >= MAX_LOG_SIZE) {
      for (let i = MAX_LOG_BACKUPS - 1; i >= 1; i--) {
        const src = `${LOG_FILE}.${i}`;
        const dst = `${LOG_FILE}.${i + 1}`;
        const srcExists = await fs.promises.access(src).then(() => true).catch(() => false);
        if (srcExists) await fs.promises.rename(src, dst);
      }
      await fs.promises.rename(LOG_FILE, `${LOG_FILE}.1`);
    }
  } catch (_) { /* ignore */ }
  finally {
    _logRotating = false;
  }
}

function logToFile(level, message, traceId = null) {
  const trace = traceId ? ` [${traceId}]` : '';
  const line = `[${new Date().toISOString()}]${trace} [${level}] ${message}\n`;
  // P2-5：使用异步写入避免阻塞事件循环；日志为 best-effort，错误忽略
  rotateLogIfNeeded()
    .then(() => { fs.appendFile(LOG_FILE, line, () => { /* ignore */ }); })
    .catch(() => { /* ignore */ });
}

function reqLog(req, level, message) {
  logToFile(level, message, req.traceId);
}

function loadJobHistory() {
  try {
    if (fs.existsSync(HISTORY_FILE)) {
      const data = JSON.parse(fs.readFileSync(HISTORY_FILE, 'utf-8'));
      if (Array.isArray(data)) {
        jobHistory.push(...data.slice(-CONFIG.maxJobHistory));
      }
    }
  } catch (_) { /* ignore */ }
}

function persistJobHistory() {
  try {
    fs.writeFileSync(HISTORY_FILE, JSON.stringify(jobHistory.slice(-CONFIG.maxJobHistory), null, 2));
  } catch (_) { /* ignore */ }
}

loadJobHistory();

// Skill 目录健壮性校验
function validateSkillDir() {
  const required = ['counterfactual_bridge.py', 'run_cli.py', '_token_filters.py'];
  const exists = fs.existsSync(CONFIG.skillDir);
  const missing = exists
    ? required.filter((f) => !fs.existsSync(path.join(CONFIG.skillDir, f)))
    : required;
  return { exists, missing, ok: exists && missing.length === 0 };
}

const skillValidation = validateSkillDir();
if (!skillValidation.ok) {
  console.warn(`[WARN] Skill 目录校验未通过: ${CONFIG.skillDir}`);
  console.warn(`  存在: ${skillValidation.exists}, 缺失文件: ${skillValidation.missing.join(', ') || '无'}`);
  logToFile('warn', `Skill 目录校验未通过: exists=${skillValidation.exists} missing=${skillValidation.missing.join(',')}`);
}

// Python 环境检查（启动时一次，供健康检查与问题排查）
// 优先复用 trace-engine/health_check.py，与 engine 端保持一致的诊断口径。
function checkPythonEnv() {
  const engineHealthScript = path.resolve(CONFIG.skillDir, '..', '..', 'health_check.py');
  if (fs.existsSync(engineHealthScript)) {
    try {
      const result = require('child_process').spawnSync(
        CONFIG.pythonCmd,
        [engineHealthScript],
        { encoding: 'utf-8', timeout: 30000, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }
      );
      if (result.status === 0) {
        try {
          const report = JSON.parse(result.stdout);
          return {
            ok: report.status === 'healthy',
            python: report.python,
            deps: report.deps,
            engineHealth: report,
          };
        } catch (_) {
          // 回退到内联检查
        }
      }
    } catch (err) {
      // 回退到内联检查
    }
  }

  try {
    const script = `
import sys
print('PYTHON_VERSION', sys.version.split()[0])
try:
    import dowhy
    print('DOWHY', getattr(dowhy, '__version__', 'unknown'))
except Exception:
    print('DOWHY', 'missing')
try:
    import numpy
    print('NUMPY', numpy.__version__)
except Exception:
    print('NUMPY', 'missing')
try:
    import pandas
    print('PANDAS', pandas.__version__)
except Exception:
    print('PANDAS', 'missing')
try:
    import sklearn
    print('SKLEARN', sklearn.__version__)
except Exception:
    print('SKLEARN', 'missing')
`;
    const result = require('child_process').spawnSync(CONFIG.pythonCmd, ['-c', script], {
      encoding: 'utf-8',
      timeout: 15000,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
    if (result.status !== 0) {
      return { ok: false, error: result.stderr || 'Python 检查失败' };
    }
    const deps = {};
    for (const line of result.stdout.split('\n')) {
      const parts = line.trim().split(' ');
      if (parts.length === 2) {
        deps[parts[0].toLowerCase()] = parts[1];
      }
    }
    return { ok: true, python: deps.python_version, deps };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

const pythonEnv = checkPythonEnv();
if (!pythonEnv.ok) {
  console.warn(`[WARN] Python 环境检查未通过: ${pythonEnv.error}`);
  logToFile('warn', `Python 环境检查未通过: ${pythonEnv.error}`);
}

// 静态文件
app.use(express.static(path.join(__dirname, 'public')));
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));

// 请求追踪 ID（便于多云环境日志串联）
app.use((req, _res, next) => {
  req.traceId = req.headers['x-trace-id'] || crypto.randomUUID();
  next();
});

// CORS（多云/跨域部署支持）
// P2-4：默认 Allow-Origin: '*' 仅适用于本地开发场景（同机浏览器访问无跨域凭证需求）。
// 生产/多云部署应通过环境变量 TRACE_CORS_ORIGIN 指定精确来源（如 https://trace.example.com），
// 避免通配符导致任意站点跨域调用本服务。
app.use((_req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', process.env.TRACE_CORS_ORIGIN || '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Trace-Config');
  next();
});
app.options('*', (_req, res) => res.sendStatus(204));

// 桥接参数 Schema（用于校验、文档、前端表单生成）
// 优先从 trace-engine/build_bridge_schema.py 读取，与 engine presets.yaml 保持统一。
function loadBridgeParamSchema(preset = null) {
  const fallback = {
    threshold: { type: 'number', min: 0, max: 10, default: 0.03, description: '因果边显著性阈值（过拟合 LLaMA 模型建议 0.01-0.05）' },
    window_size: { type: 'integer', min: 2, max: 256, default: 64, description: 'TRACE 滑动窗口大小' },
    max_segments: { type: 'integer', min: 1, max: 16, default: 4, description: 'LLaMA TRACE 最大分段数' },
    max_concepts: { type: 'integer', min: 1, max: 128, default: 12, description: '最大概念数' },
    concept_min_freq: { type: 'integer', min: 1, max: 1000, default: 2, description: '概念最小出现频次' },
    min_valid_tokens: { type: 'integer', min: 1, max: 10000, default: 10, description: '最小有效 token 数' },
    min_concepts: { type: 'integer', min: 2, max: 128, default: 3, description: '最小概念数' },
    max_edges_for_dowhy: { type: 'integer', min: 1, max: 100, default: 8, description: '传入 DoWhy 的最大边数' },
    filter_mode: { type: 'string', default: 'topn', description: '边过滤模式 (topn / percentile / adaptive)' },
    filter_percentile: { type: 'integer', min: 50, max: 99, default: 85, description: 'percentile 模式的百分位' },
    random_state: { type: 'integer', min: 0, max: 999999, default: 42, description: '随机种子' },
    classical_mode: { type: 'boolean', default: false, description: '古汉语模式（Shenji 古文保留之/乎/者/也等虚词）' },
  };
  const llamaFallback = {
    threshold: { type: 'number', min: 0, max: 10, default: 0.01, description: '因果边显著性阈值（LLaMA V4 过拟合模型专属，建议 0.01-0.03）' },
    window_size: { type: 'integer', min: 2, max: 256, default: 128, description: 'TRACE 滑动窗口大小（LLaMA V4 专属）' },
    max_segments: { type: 'integer', min: 1, max: 16, default: 3, description: 'LLaMA TRACE 最大分段数（LLaMA V4 专属）' },
    max_concepts: { type: 'integer', min: 1, max: 128, default: 12, description: '最大概念数' },
    concept_min_freq: { type: 'integer', min: 1, max: 1000, default: 1, description: '概念最小出现频次（LLaMA V4 专属，放宽低频）' },
    min_valid_tokens: { type: 'integer', min: 1, max: 10000, default: 10, description: '最小有效 token 数' },
    min_concepts: { type: 'integer', min: 2, max: 128, default: 3, description: '最小概念数' },
    max_edges_for_dowhy: { type: 'integer', min: 1, max: 100, default: 12, description: '传入 DoWhy 的最大边数' },
    filter_mode: { type: 'string', default: 'topn', description: '边过滤模式 (topn / percentile / adaptive)' },
    filter_percentile: { type: 'integer', min: 50, max: 99, default: 85, description: 'percentile 模式的百分位' },
    random_state: { type: 'integer', min: 0, max: 999999, default: 42, description: '随机种子' },
    classical_mode: { type: 'boolean', default: false, description: '古汉语模式（Shenji 古文保留之/乎/者/也等虚词）' },
  };
  const schemaScript = path.resolve(CONFIG.skillDir, '..', '..', 'build_bridge_schema.py');
  const baseFallback = preset === 'llama' ? llamaFallback : fallback;
  if (!fs.existsSync(schemaScript)) {
    return baseFallback;
  }
  try {
    const args = [schemaScript, CONFIG.skillDir];
    if (preset) args.push('--preset', preset);
    const result = require('child_process').spawnSync(
      CONFIG.pythonCmd,
      args,
      { encoding: 'utf-8', timeout: 15000, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }
    );
    if (result.status !== 0) {
      logToFile('warn', `build_bridge_schema.py 失败: ${result.stderr || 'unknown'}`);
      return baseFallback;
    }
    const schema = JSON.parse(result.stdout);
    logToFile('info', `已从 presets.yaml 加载桥接参数 Schema (${preset || 'default'})，共 ${Object.keys(schema).length} 项`);
    return schema;
  } catch (err) {
    logToFile('warn', `加载桥接参数 Schema 失败: ${err.message}`);
    return baseFallback;
  }
}

const BRIDGE_PARAM_SCHEMA = loadBridgeParamSchema();
const SUPER_BRIDGE_PARAM_SCHEMA = loadBridgeParamSchema('llama');

// 参数校验辅助
function validateAnalysisInput(text, mode, config) {
  if (typeof text !== 'string' || text.trim().length === 0) {
    return { ok: false, error: '文本不能为空', code: 'EMPTY_TEXT' };
  }
  if (text.length > CONFIG.maxTextLength) {
    return { ok: false, error: `文本长度超过限制 ${CONFIG.maxTextLength}`, code: 'TEXT_TOO_LONG' };
  }
  if (!['light', 'deep', 'super'].includes(mode)) {
    return { ok: false, error: 'mode 必须是 light、deep 或 super', code: 'INVALID_MODE' };
  }
  // S16：SUPER 模式依赖探测到的 LLaMA 模型，未探测到时直接禁用而非回退硬编码白名单，
  // 避免允许不存在的模型导致运行时失败
  if (mode === 'super' && PROBED_LLAMA_MODELS.length === 0) {
    return { ok: false, error: 'SUPER 模式不可用：未探测到任何 LLaMA 模型，请检查模型目录或 TRACE_ENGINE_SKILL_DIR 配置', code: 'SUPER_NO_MODELS', field: 'model' };
  }
  if (config && typeof config === 'object') {
    // SUPER 模式下 model 参数白名单校验（仅基于探测结果，不再回退硬编码白名单）
    if (mode === 'super' && config.model !== undefined) {
      const allowedModels = PROBED_LLAMA_MODELS.map((m) => m.id);
      if (!allowedModels.includes(config.model)) {
        return { ok: false, error: `SUPER 模式不支持模型 ${config.model}，可用: ${allowedModels.join(', ')}`, code: 'INVALID_MODEL', field: 'model' };
      }
    }
    const schemaToValidate = mode === 'super' ? SUPER_BRIDGE_PARAM_SCHEMA : BRIDGE_PARAM_SCHEMA;
    for (const [k, schema] of Object.entries(schemaToValidate)) {
      if (config[k] === undefined) continue;
      const v = config[k];
      if (schema.type === 'integer' && (!Number.isInteger(v) || v < schema.min || v > schema.max)) {
        return { ok: false, error: `参数 ${k} 必须是 [${schema.min}, ${schema.max}] 之间的整数`, code: 'INVALID_PARAM', field: k };
      }
      if (schema.type === 'number' && (typeof v !== 'number' || Number.isNaN(v) || v < schema.min || v > schema.max)) {
        return { ok: false, error: `参数 ${k} 必须在 [${schema.min}, ${schema.max}] 之间`, code: 'INVALID_PARAM', field: k };
      }
      // P2-1：boolean 类型必须严格校验，防止字符串/数字被当作真值注入
      if (schema.type === 'boolean' && typeof v !== 'boolean') {
        return { ok: false, error: `参数 ${k} 必须是布尔值 (true/false)`, code: 'INVALID_PARAM', field: k };
      }
    }
    // P2-1：filter_mode 白名单校验，防止注入非法过滤模式
    if (config.filter_mode !== undefined && !['topn', 'percentile', 'adaptive'].includes(config.filter_mode)) {
      return { ok: false, error: '参数 filter_mode 必须是 topn / percentile / adaptive 之一', code: 'INVALID_PARAM', field: 'filter_mode' };
    }
    // P2-1：过滤 config 中未在 schema 定义的字段，仅保留 schema 已知键（SUPER 模式额外保留 model）
    const allowedKeys = new Set(Object.keys(schemaToValidate));
    if (mode === 'super') allowedKeys.add('model');
    for (const k of Object.keys(config)) {
      if (!allowedKeys.has(k)) {
        delete config[k];
      }
    }
  }
  return { ok: true };
}

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
    // P2-9：移除 application/octet-stream 白名单，仅靠扩展名 + 文本 mimetype 判断，避免上传任意二进制
    const allowed = ['text/plain', 'text/markdown'];
    if (allowed.includes(file.mimetype) || file.originalname.endsWith('.txt') || file.originalname.endsWith('.md')) {
      cb(null, true);
    } else {
      cb(new Error('仅支持 .txt / .md 文本文件'));
    }
  },
});

// 发送 SSE 事件到客户端
// S4：done 事件 code 语义统一约定（前端据此判定任务终态）：
//   0   = 正常完成（LIGHT/DEEP 为 Python 退出码 0，SUPER 为 finish(0)）
//   124 = 超时（SUPER 安全兜底 24h 超时 / 阶段 hang 看门狗触发）
//   125 = 取消（用户主动停止 / 客户端断开连接）
//   -1  = 错误（Python 异常退出 / SUPER 启动或运行错误 / Worker 退出）
//   其他非零值 = LIGHT/DEEP 模式 Python 子进程原始退出码（如 1/2）
function sendSSE(res, event, data) {
  res.write(`event: ${event}\n`);
  res.write(`data: ${JSON.stringify(data)}\n\n`);
}

function cacheKey(text, mode, cfgObj = null) {
  const cfgPart = cfgObj ? `:${JSON.stringify(cfgObj)}` : '';
  return crypto.createHash('sha256').update(`${mode}:${text}${cfgPart}`).digest('hex');
}

function recordJob(id, mode, status, error = null, meta = {}) {
  const now = new Date().toISOString();
  const existing = jobHistory.find((j) => j.id === id);
  // 当 mode 为 null 时保留已有记录的 mode（用于 gracefulShutdown 等场景）
  const effectiveMode = mode || (existing ? existing.mode : 'unknown');
  // S7：历史记录不存全量 text，只存 textHash + textPreview（前 200 字符摘要），
  // 全量 text 落盘到 work/inputs/<id>.txt 供 /api/retry 读取，避免 job_history.json 膨胀
  const entryMeta = { ...meta };
  if (entryMeta.text !== undefined) {
    const fullText = entryMeta.text;
    entryMeta.textHash = crypto.createHash('sha256').update(fullText).digest('hex');
    entryMeta.textPreview = fullText.slice(0, 200);
    try {
      ensureDir(path.join(WORK_DIR, 'inputs'));
      fs.writeFileSync(path.join(WORK_DIR, 'inputs', `${id}.txt`), fullText, 'utf-8');
    } catch (err) {
      logToFile('warn', `保存任务输入文本失败 job=${id}: ${err.message}`);
    }
    delete entryMeta.text;
  }
  const entry = {
    id,
    mode: effectiveMode,
    status,
    createdAt: existing ? existing.createdAt : now,
    updatedAt: now,
    completedAt: ['completed', 'error', 'timeout', 'cancelled'].includes(status) ? now : undefined,
    durationMs: existing && existing.createdAt && ['completed', 'error', 'timeout', 'cancelled'].includes(status)
      ? Date.now() - new Date(existing.createdAt).getTime()
      : undefined,
    error,
    ...entryMeta,
  };
  const idx = jobHistory.findIndex((j) => j.id === id);
  if (idx >= 0) {
    // 保留已有字段（如 textHash、config），避免后续更新时覆盖
    jobHistory[idx] = { ...jobHistory[idx], ...entry };
  } else {
    jobHistory.push(entry);
  }
  while (jobHistory.length > CONFIG.maxJobHistory) {
    jobHistory.shift();
  }
  persistJobHistory();
}

function cleanupOldOutputs() {
  const now = Date.now();
  try {
    const dirs = fs.readdirSync(OUTPUT_DIR);
    let cleaned = 0;
    for (const dir of dirs) {
      const full = path.join(OUTPUT_DIR, dir);
      try {
        const stat = fs.statSync(full);
        if (now - stat.mtimeMs > CONFIG.outputTtlMs) {
          fs.rmSync(full, { recursive: true, force: true });
          cleaned += 1;
        }
      } catch (_) { /* ignore */ }
    }
    if (cleaned > 0) {
      console.log(`[cleanup] 已清理 ${cleaned} 个过期输出目录`);
    }
  } catch (err) {
    console.error('[cleanup] 清理失败:', err.message);
  }
}

// 启动时与周期性清理
// S6：保存 timer 句柄，便于 gracefulShutdown 时清理，避免进程因未清除的定时器延迟退出
const cleanupInterval = setInterval(cleanupOldOutputs, Math.min(CONFIG.outputTtlMs, 3600000));
const startupCleanupTimer = setTimeout(cleanupOldOutputs, 5000);

/**
 * 流式调用 Python 桥接脚本分析文本
 */
function runPythonAnalysisStream(text, outputId, mode, bridgeConfig, res) {
  const skillDir = CONFIG.skillDir;
  const pyScript = path.resolve(__dirname, 'py_bridge.py');
  const outDir = path.join(OUTPUT_DIR, outputId);
  const cfgObj = bridgeConfig ? (() => { try { return JSON.parse(bridgeConfig); } catch (_) { return null; } })() : null;

  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

  recordJob(outputId, mode, 'running', null, { text, config: bridgeConfig || CONFIG.bridgeConfig || '' });
  activeJobResponses.set(outputId, { res, mode });
  logToFile('info', `启动分析 job=${outputId} mode=${mode} text_len=${text.length}`);

  const args = [pyScript, skillDir, outDir, mode];
  const cfg = bridgeConfig || CONFIG.bridgeConfig || '';
  if (cfg) {
    args.push(cfg);
  }

  const py = spawn(CONFIG.pythonCmd, args, {
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      // P2-2：使用当前任务的 bridgeConfig，而非全局 CONFIG.bridgeConfig，避免任务级配置被全局空串覆盖
      TRACE_BRIDGE_CONFIG: cfg,
    },
  });

  activeJobs.set(outputId, py);

  let stdoutBuffer = '';
  let timeoutId = null;
  // P2-9：与 SUPER 模式一致，使用 finished 标记防止 close/error 重复处理，
  // 并在客户端提前断开时清理资源。
  let finished = false;

  const cleanupTimeout = () => {
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    if (heartbeat) {
      clearInterval(heartbeat);
    }
  };

  timeoutId = setTimeout(() => {
    logToFile('warn', `分析超时 job=${outputId}，强制终止`);
    sendSSE(res, 'error', { message: `分析超时（>${CONFIG.jobTimeoutMs}ms），已强制终止。请尝试 LIGHT 模式或缩短文本。` });
    // P2-7：SIGTERM 后 5 秒未退出则 SIGKILL 兜底
    killProcessWithFallback(py);
    recordJob(outputId, mode, 'timeout');
  }, CONFIG.jobTimeoutMs);

  py.stdin.write(text, 'utf-8');
  py.stdin.end();

  // P2-9：SSE 客户端提前断开时清理 LIGHT/DEEP 资源，避免悬挂的 Python 进程与定时器
  res.on('close', () => {
    if (finished) return;
    logToFile('info', `SSE 客户端断开，清理 ${mode} 任务 job=${outputId}`);
    finished = true;
    cleanupTimeout();
    killProcessWithFallback(py);
    recordJob(outputId, mode, 'cancelled', '客户端断开连接');
    activeJobs.delete(outputId);
    activeJobResponses.delete(outputId);
    processJobQueue();
  });

  // SSE 保活：每 30 秒发送一条注释，防止浏览器/代理因长时间无数据而断开连接
  const heartbeat = setInterval(() => {
    try { res.write(':heartbeat\n\n'); } catch (_) {}
  }, 30000);

  py.stdout.on('data', (chunk) => {
    stdoutBuffer += chunk.toString('utf-8');
    const lines = stdoutBuffer.split('\n');
    stdoutBuffer = lines.pop(); // 保留未完整的一行

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const obj = JSON.parse(line);
        if (obj.type === 'stage') {
          sendSSE(res, 'stage', obj);
        } else if (obj.type === 'log') {
          sendSSE(res, 'log', obj);
        } else if (obj.type === 'result') {
          cleanupTimeout();
          const resultData = {
            id: outputId,
            result: obj.payload,
            reportPath: fs.existsSync(path.join(outDir, 'report.md')) ? `/api/report/${outputId}` : null,
            resultPath: `/api/result/${outputId}`,
          };
          sendSSE(res, 'result', resultData);
          // 缓存结果
          resultCache.set(cacheKey(text, mode, cfgObj), { id: outputId, timestamp: Date.now() });
          while (resultCache.size > CONFIG.maxCacheEntries) {
            const firstKey = resultCache.keys().next().value;
            resultCache.delete(firstKey);
          }
          recordJob(outputId, mode, 'completed');
          logToFile('info', `分析完成 job=${outputId}`);
        } else if (obj.type === 'error') {
          cleanupTimeout();
          sendSSE(res, 'error', { message: obj.message });
          recordJob(outputId, mode, 'error', obj.message);
          logToFile('error', `分析错误 job=${outputId}: ${obj.message}`);
        }
      } catch (err) {
        sendSSE(res, 'log', { level: 'raw', message: line });
      }
    }
  });

  py.stderr.on('data', (chunk) => {
    const lines = chunk.toString('utf-8').split('\n').filter(Boolean);
    for (const line of lines) {
      sendSSE(res, 'log', { level: 'stderr', message: line });
    }
  });

  py.on('close', (code) => {
    // P2-9：标记结束，阻止 res.on('close') 重复清理
    finished = true;
    cleanupTimeout();
    activeJobs.delete(outputId);
    activeJobResponses.delete(outputId);
    if (code !== 0) {
      const msg = `Python 进程异常退出 (code=${code})`;
      sendSSE(res, 'error', { message: msg });
      recordJob(outputId, mode, 'error', msg);
      logToFile('error', `Python 异常退出 job=${outputId} code=${code}`);
    }
    sendSSE(res, 'done', { code });
    res.end();
    processJobQueue();
  });

  py.on('error', (err) => {
    // P2-9：标记结束，阻止 res.on('close') 重复清理
    finished = true;
    cleanupTimeout();
    activeJobs.delete(outputId);
    activeJobResponses.delete(outputId);
    sendSSE(res, 'error', { message: err.message });
    recordJob(outputId, mode, 'error', err.message);
    logToFile('error', `Python 启动错误 job=${outputId}: ${err.message}`);
    sendSSE(res, 'done', { code: -1 });
    res.end();
    processJobQueue();
  });
}

/**
 * SUPER 模式：调用常驻 LLaMA Worker 执行真正的 TRACE 因果发现
 */
async function runSuperAnalysisStream(text, outputId, bridgeConfig, res) {
  const outDir = path.join(OUTPUT_DIR, outputId);
  const cfgObj = bridgeConfig ? (() => { try { return JSON.parse(bridgeConfig); } catch (_) { return null; } })() : null;

  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
  recordJob(outputId, 'super', 'running', null, { text, config: bridgeConfig || '' });
  activeJobResponses.set(outputId, { res, mode: 'super' });
  logToFile('info', `启动 SUPER 分析 job=${outputId} text_len=${text.length} model=${cfgObj?.model || 'shehui-llama'}`);

  // P1-1/P1-2：入口处立即在 activeJobs 占位，使并发检查生效并支持取消等待中的任务
  const placeholder = {
    isSuperQueued: true,
    cancelled: false,
    cancel: () => { placeholder.cancelled = true; },
  };
  activeJobs.set(outputId, placeholder);

  // SUPER 模式不再使用固定超时硬限制，改为实时速率/ETA + 用户主动停止
  const modelNameLower = (cfgObj?.model || 'shehui-llama').toLowerCase();
  // 区分轻量模型（shehui-llama 27M）与重量级模型（shenji-llama / shehui-llama-v4-archive 470M）
  const isLightModel = modelNameLower.includes('shehui') && !modelNameLower.includes('archive');
  const isLargeModel = modelNameLower.includes('shenji') || modelNameLower.includes('archive');
  // 保留 24 小时安全兜底，防止进程彻底失控；正常流程依赖用户主动停止
  const superTimeoutMs = 24 * 60 * 60 * 1000;
  // P2-6：阶段性进度检测——默认 15 分钟内无 stage 更新则判定 hang 并终止；
  // 可通过环境变量 TRACE_STAGE_TIMEOUT_MS（毫秒）覆盖，便于大模型场景调优
  const _envStageTimeout = parseInt(process.env.TRACE_STAGE_TIMEOUT_MS, 10);
  const stageHangMs = Number.isFinite(_envStageTimeout) && _envStageTimeout > 0
    ? _envStageTimeout
    : 15 * 60 * 1000;
  if (isLargeModel) {
    sendSSE(res, 'log', { level: 'warn', message: '当前 SUPER 模式使用 470M 级 LLaMA 模型（Shenji/Archive 均为 1.88GB 左右），推理速度较慢。界面会实时显示处理速率与预计剩余时间；如无法接受等待时长，可随时点击“停止计算”。LLaMA 预设会自动设置 window_size=128 / max_segments=3 以平衡显存与因果覆盖。' });
  } else if (isLightModel) {
    sendSSE(res, 'log', { level: 'info', message: '当前 SUPER 模式使用 Shehui-LLaMA（27M 轻量级，108MB），推理速度极快。因果视野 256 tokens，适合高密度因果文本的快速刨析。' });
  }

  let timeoutId = null;
  let finished = false;
  let lastStageName = 'init';
  let lastStageTime = Date.now();
  const taskStartTime = Date.now();
  let keepAlive = null;
  let stageWatchdog = null;

  const cleanupTimeout = () => {
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    // P2-6：清理阶段性进度看门狗
    if (stageWatchdog) {
      clearInterval(stageWatchdog);
      stageWatchdog = null;
    }
  };

  const finish = (doneCode) => {
    if (finished) return;
    finished = true;
    cleanupTimeout();
    if (keepAlive) clearInterval(keepAlive);
    releaseLlamaWorker();
    activeJobs.delete(outputId);
    activeJobResponses.delete(outputId);
    sendSSE(res, 'done', { code: doneCode });
    res.end();
    processJobQueue();
  };

  try {
    const worker = await ensureLlamaWorker();
    await waitForLlamaWorkerIdle();
    // P1-2：等待期间被取消则直接退出，释放 Worker 槽位给下一个任务
    if (placeholder.cancelled) {
      releaseLlamaWorker();
      activeJobs.delete(outputId);
      activeJobResponses.delete(outputId);
      recordJob(outputId, 'super', 'cancelled', '等待 Worker 期间被取消');
      logToFile('info', `SUPER 任务在等待 Worker 期间被取消 job=${outputId}`);
      try { sendSSE(res, 'error', { message: '用户主动停止计算' }); sendSSE(res, 'done', { code: 125 }); res.end(); } catch (_) {}
      processJobQueue();
      return;
    }
    llamaWorkerBusy = true;

    timeoutId = setTimeout(() => {
      const elapsed = Date.now() - taskStartTime;
      const stageDur = Date.now() - lastStageTime;
      const msg = `SUPER 分析已运行超过 24 小时安全兜底。任务在 [${lastStageName}] 阶段停留约 ${stageDur}ms，总耗时 ${elapsed}ms。系统已强制终止；如仍需分析，请缩短文本、减小 window_size / max_segments、切换到 DEEP 模式，或检查模型/算力状态。`;
      logToFile('warn', `SUPER 安全兜底触发 job=${outputId} model=${cfgObj?.model || 'shehui-llama'} stage=${lastStageName} elapsed=${elapsed}`);
      sendSSE(res, 'error', { message: msg });
      recordJob(outputId, 'super', 'timeout');
      finish(124);
    }, superTimeoutMs);

    // P2-6：阶段性进度看门狗——每 60 秒检查一次，若 stageHangMs 内无 stage 更新则判定 hang 并终止
    stageWatchdog = setInterval(() => {
      if (finished) return;
      const stageSilence = Date.now() - lastStageTime;
      if (stageSilence >= stageHangMs) {
        const elapsed = Date.now() - taskStartTime;
        const msg = `SUPER 分析在 [${lastStageName}] 阶段停留超过 ${Math.round(stageHangMs / 60000)} 分钟无进度更新（已停留 ${Math.round(stageSilence / 60000)} 分钟，总耗时 ${Math.round(elapsed / 60000)} 分钟），判定为 hang，系统已强制终止。建议检查模型加载/算力状态，或缩短文本、减小 window_size / max_segments。`;
        logToFile('warn', `SUPER 阶段 hang 触发 job=${outputId} model=${cfgObj?.model || 'shehui-llama'} stage=${lastStageName} silence=${stageSilence}ms elapsed=${elapsed}ms`);
        sendSSE(res, 'error', { message: msg });
        recordJob(outputId, 'super', 'timeout', 'stage_hang');
        finish(124);
      }
    }, 60000);

    // 占位对象替换为实际 Worker 引用，并标记取消时发送取消信号
    placeholder.isRunning = true;
    activeJobs.set(outputId, worker);

    currentLlamaHandler = (obj) => {
      currentLlamaHandler.outputId = outputId;
      if (obj.type === 'stage') {
        lastStageName = obj.stage || lastStageName;
        lastStageTime = Date.now();
        sendSSE(res, 'stage', obj);
      } else if (obj.type === 'log') {
        sendSSE(res, 'log', obj);
      } else if (obj.type === 'stats') {
        sendSSE(res, 'stats', obj.stats);
      } else if (obj.type === 'error') {
        cleanupTimeout();
        sendSSE(res, 'error', { message: obj.message });
        recordJob(outputId, 'super', 'error', obj.message);
        logToFile('error', `SUPER 错误 job=${outputId}: ${obj.message}`);
        finish(-1);
      } else if (obj.type === 'result') {
        cleanupTimeout();
        const payload = obj.payload || {};
        try {
          fs.writeFileSync(path.join(outDir, 'result.json'), JSON.stringify(payload, null, 2), 'utf-8');
          const reportText = buildSuperReport(payload);
          fs.writeFileSync(path.join(outDir, 'report.md'), reportText, 'utf-8');
        } catch (err) {
          logToFile('warn', `SUPER 结果持久化失败 job=${outputId}: ${err.message}`);
        }
        const resultData = {
          id: outputId,
          result: payload,
          reportPath: `/api/report/${outputId}`,
          resultPath: `/api/result/${outputId}`,
        };
        sendSSE(res, 'result', resultData);
        resultCache.set(cacheKey(text, 'super', cfgObj), { id: outputId, timestamp: Date.now() });
        while (resultCache.size > CONFIG.maxCacheEntries) {
          const firstKey = resultCache.keys().next().value;
          resultCache.delete(firstKey);
        }
        recordJob(outputId, 'super', 'completed');
        logToFile('info', `SUPER 分析完成 job=${outputId}`);
        finish(0);
      }
    };

    // P1-9：worker.stdin 的 'error' 监听器已迁移至 spawnLlamaWorker 内一次性挂载，
    // 避免每次 SUPER 任务都新增 listener 导致在常驻 worker 上累积泄漏。
    // Worker 通信失败会通过 worker 'close' / 'error' 事件以及 currentLlamaHandler 中的错误处理链路捕获。

    // P1-3：SSE 客户端断开连接时清理 SUPER 资源（发送取消信号，释放 Worker）
    res.on('close', () => {
      if (finished) return;
      logToFile('info', `SSE 客户端断开，清理 SUPER 任务 job=${outputId}`);
      // 向 Worker 发送取消信号，中断当前计算
      try {
        worker.stdin.write(JSON.stringify({ type: 'cancel', id: outputId }) + '\n', 'utf-8');
      } catch (_) {}
      recordJob(outputId, 'super', 'cancelled', '客户端断开连接');
      // 标记结束并释放资源，阻止后续 handler 写入已关闭的响应
      finished = true;
      cleanupTimeout();
      if (keepAlive) clearInterval(keepAlive);
      currentLlamaHandler = null;
      releaseLlamaWorker();
      activeJobs.delete(outputId);
      activeJobResponses.delete(outputId);
      processJobQueue();
    });

    // P2-8：使用背压感知写入，避免大文本（可达 500KB）撑爆 stdin 内部缓冲区
    await writeWithDrain(worker.stdin, JSON.stringify({
      id: outputId,
      text,
      model: cfgObj && cfgObj.model ? cfgObj.model : 'shehui-llama',
      mode: 'super',
      config: cfgObj || {},
      timeout_ms: superTimeoutMs,
    }) + '\n', 'utf-8');

    // SSE 保活：每 30 秒发送一条注释，防止浏览器/代理因长时间无数据而断开连接
    keepAlive = setInterval(() => {
      if (finished) return;
      try { res.write(':heartbeat\n\n'); } catch (_) {}
    }, 30000);
  } catch (err) {
    cleanupTimeout();
    if (keepAlive) clearInterval(keepAlive);
    sendSSE(res, 'error', { message: err.message });
    recordJob(outputId, 'super', 'error', err.message);
    logToFile('error', `SUPER 启动失败 job=${outputId}: ${err.message}`);
    finish(-1);
  }
}

function buildSuperReport(payload) {
  const lines = [];
  lines.push('# TRACE SUPER 模式分析报告');
  lines.push('');
  lines.push(`**分析模型**: ${payload.model || 'shehui-llama'}`);
  lines.push(`**概念数量**: ${(payload.concepts || []).length}`);
  lines.push(`**显著因果边**: ${payload.n_significant_edges || 0}`);
  lines.push(`**ATE**: ${payload.ate !== null ? payload.ate.toFixed(3) : 'N/A'}`);
  lines.push(`**可识别性**: ${payload.identifiable ? '是' : '否'}`);
  lines.push('');
  lines.push('## 核心概念');
  (payload.concepts || []).forEach((c) => lines.push(`- ${c}`));
  lines.push('');
  lines.push('## Top 因果边');
  (payload.top_edges || []).forEach((e) => {
    const s = typeof e.strength === 'number' ? e.strength.toFixed(3) : 'N/A';
    lines.push(`- ${e.source || '?'} → ${e.target || '?'} (ΔNLL=${s})`);
  });
  lines.push('');
  lines.push('## 审计结果');
  if (payload.auditor) {
    lines.push(`- 裁决: ${payload.auditor.verdict}`);
    lines.push(`- PASS/WARN/FAIL: ${payload.auditor.n_pass}/${payload.auditor.n_warn}/${payload.auditor.n_fail}`);
  } else {
    lines.push('- 审计不可用');
  }
  return lines.join('\n');
}



// 任务队列处理
function processJobQueue() {
  if (jobQueue.length === 0) return;
  if (activeJobs.size >= CONFIG.maxConcurrentJobs) return;
  const next = jobQueue.shift();
  if (!next) return;
  logToFile('info', `从队列取出任务 job=${next.id}, mode=${next.mode}, 当前活跃=${activeJobs.size}`);
  if (next.mode === 'super') {
    runSuperAnalysisStream(next.text, next.id, next.bridgeConfig, next.res);
  } else {
    runPythonAnalysisStream(next.text, next.id, next.mode, next.bridgeConfig, next.res);
  }
}

// 解析桥接配置（query/body -> JSON 字符串）
function parseBridgeConfig(raw) {
  if (!raw) return CONFIG.bridgeConfig || '';
  try {
    const obj = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return JSON.stringify(obj);
  } catch (_) {
    return String(raw);
  }
}

// SSE 流式分析入口（GET 兼容旧版/简单调用；POST 用于长文本避免 URL 长度限制）
function handleAnalyzeStream(req, res) {
  const id = req.query.id || req.body.id || crypto.randomUUID();
  const text = req.query.text || req.body.text;
  const mode = (req.query.mode || req.body.mode || 'light').toLowerCase();
  let bridgeConfig = parseBridgeConfig(req.query.config || req.body.config);

  const cfgObj = bridgeConfig ? (() => { try { return JSON.parse(bridgeConfig); } catch (_) { return null; } })() : null;
  const validation = validateAnalysisInput(text, mode, cfgObj);
  if (!validation.ok) {
    reqLog(req, 'warn', `SSE 输入校验失败: ${validation.error} (${validation.code || ''})`);
    return res.status(400).json({ success: false, error: validation.error, code: validation.code, field: validation.field, traceId: req.traceId });
  }
  // P2-1：基于校验后已过滤未知字段的 cfgObj 重新序列化 bridgeConfig，确保下游使用净化后的配置
  if (cfgObj && typeof cfgObj === 'object') {
    bridgeConfig = JSON.stringify(cfgObj);
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  if (activeJobs.size >= CONFIG.maxConcurrentJobs) {
    jobQueue.push({ id, text, mode, bridgeConfig, res });
    const msg = `当前并发任务已满（${activeJobs.size}/${CONFIG.maxConcurrentJobs}），任务 ${id ? id.slice(0, 8) : '未知'} 已进入队列，前面还有 ${jobQueue.length - 1} 个任务。`;
    sendSSE(res, 'log', { level: 'warn', message: msg });
    logToFile('warn', msg);
    return;
  }

  if (mode === 'super') {
    runSuperAnalysisStream(text, id, bridgeConfig, res);
  } else {
    runPythonAnalysisStream(text, id, mode, bridgeConfig, res);
  }
}

// P2-11：GET /api/analyze-stream 仅用于短文本探针/快速调用（text 通过 URL query 传递，受浏览器与服务器 URL 长度限制，通常 < 2KB）。
// 长文本必须改用 POST /api/analyze-stream（text 放入 body，支持至 maxTextLength，默认 500KB），避免 URL 截断或 414 URI Too Long。
app.get('/api/analyze-stream', handleAnalyzeStream);
app.post('/api/analyze-stream', handleAnalyzeStream);

// 同步分析（旧接口，保留兼容，支持 mode 与 config）
function runPythonAnalysisSync(text, outputId, mode = 'light', bridgeConfig = '') {
  return new Promise((resolve, reject) => {
    const skillDir = CONFIG.skillDir;
    const pyScript = path.resolve(__dirname, 'py_bridge.py');
    const outDir = path.join(OUTPUT_DIR, outputId);
    const cfgObj = bridgeConfig ? (() => { try { return JSON.parse(bridgeConfig); } catch (_) { return null; } })() : null;

    if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

    recordJob(outputId, mode, 'running', null, { text, config: bridgeConfig || CONFIG.bridgeConfig || '' });

    const args = [pyScript, skillDir, outDir, mode];
    const cfg = bridgeConfig || CONFIG.bridgeConfig || '';
    if (cfg) args.push(cfg);

    const py = spawn(CONFIG.pythonCmd, args, {
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });

    let stdout = '';
    let stderr = '';

    py.stdin.write(text, 'utf-8');
    py.stdin.end();

    py.stdout.on('data', (data) => { stdout += data.toString('utf-8'); });
    py.stderr.on('data', (data) => { stderr += data.toString('utf-8'); });

    py.on('close', (code) => {
      if (code !== 0) {
        recordJob(outputId, mode, 'error', stderr || stdout);
        reject(new Error(`Python 退出码 ${code}: ${stderr || stdout}`));
        return;
      }
      try {
        const resultPath = path.join(outDir, 'result.json');
        const reportPath = path.join(outDir, 'report.md');
        const lines = stdout.split('\n').filter(Boolean);
        let result = null;
        for (let i = lines.length - 1; i >= 0; i--) {
          try {
            const obj = JSON.parse(lines[i]);
            if (obj.type === 'result') {
              result = obj.payload;
              break;
            }
          } catch (_) { /* ignore */ }
        }
        if (!result && fs.existsSync(resultPath)) {
          result = JSON.parse(fs.readFileSync(resultPath, 'utf-8'));
        }
        resultCache.set(cacheKey(text, mode, cfgObj), { id: outputId, timestamp: Date.now() });
        recordJob(outputId, mode, 'completed');
        resolve({
          id: outputId,
          result,
          reportPath: fs.existsSync(reportPath) ? `/api/report/${outputId}` : null,
          resultPath: `/api/result/${outputId}`,
        });
      } catch (err) {
        recordJob(outputId, mode, 'error', err.message);
        reject(new Error(`解析 Python 输出失败: ${err.message}\n${stdout}\n${stderr}`));
      }
    });

    py.on('error', (err) => {
      recordJob(outputId, mode, 'error', err.message);
      reject(err);
    });
  });
}

app.post('/api/analyze-text', async (req, res) => {
  try {
    const text = req.body.text || '';
    const mode = (req.body.mode || 'light').toLowerCase();
    let bridgeConfig = parseBridgeConfig(req.body.config);
    const cfgObj = bridgeConfig ? JSON.parse(bridgeConfig) : null;

    const validation = validateAnalysisInput(text, mode, cfgObj);
    if (!validation.ok) {
      reqLog(req, 'warn', `输入校验失败: ${validation.error} (${validation.code || ''})`);
      return res.status(400).json({ success: false, error: validation.error, code: validation.code, field: validation.field, traceId: req.traceId });
    }
    if (mode === 'super') {
      return res.status(400).json({ success: false, error: 'SUPER 模式请使用 /api/analyze-stream 流式接口', code: 'SUPER_REQUIRES_STREAM', traceId: req.traceId });
    }
    // P2-1：基于校验后已过滤未知字段的 cfgObj 重新序列化 bridgeConfig，确保下游使用净化后的配置
    if (cfgObj && typeof cfgObj === 'object') {
      bridgeConfig = JSON.stringify(cfgObj);
    }

    // 缓存命中检查（缓存键包含 config，避免不同参数复用错误结果）
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

app.post('/api/analyze-file', upload.single('file'), async (req, res) => {
  try {
    if (!req.file) return res.status(400).json({ success: false, error: '未上传文件' });
    const text = fs.readFileSync(req.file.path, 'utf-8');
    const mode = (req.body.mode || 'light').toLowerCase();
    let bridgeConfig = parseBridgeConfig(req.body.config);
    const cfgObj = bridgeConfig ? JSON.parse(bridgeConfig) : null;

    const validation = validateAnalysisInput(text, mode, cfgObj);
    if (!validation.ok) {
      fs.unlinkSync(req.file.path);
      reqLog(req, 'warn', `文件上传输入校验失败: ${validation.error}`);
      return res.status(400).json({ success: false, error: validation.error, code: validation.code, field: validation.field, traceId: req.traceId });
    }
    if (mode === 'super') {
      fs.unlinkSync(req.file.path);
      return res.status(400).json({ success: false, error: 'SUPER 模式请使用 /api/analyze-stream 流式接口', code: 'SUPER_REQUIRES_STREAM', traceId: req.traceId });
    }
    // P2-1：基于校验后已过滤未知字段的 cfgObj 重新序列化 bridgeConfig，确保下游使用净化后的配置
    if (cfgObj && typeof cfgObj === 'object') {
      bridgeConfig = JSON.stringify(cfgObj);
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

// 合法 ID 校验：仅允许 UUID 形态，防止路径遍历（如 ../foo）
const UUID_RE = /^[0-9a-f-]{36}$/i;
function isValidId(id) {
  return typeof id === 'string' && UUID_RE.test(id);
}

app.get('/api/result/:id', (req, res) => {
  // P1-6：校验 ID 格式，避免路径遍历
  if (!isValidId(req.params.id)) {
    return res.status(400).json({ success: false, error: '非法的任务 ID', code: 'ERROR' });
  }
  const resultPath = path.join(OUTPUT_DIR, req.params.id, 'result.json');
  if (!fs.existsSync(resultPath)) return res.status(404).json({ success: false, error: '结果不存在', code: 'ERROR' });
  res.setHeader('Content-Type', 'application/json');
  res.sendFile(resultPath);
});

app.get('/api/report/:id', (req, res) => {
  // P1-6：校验 ID 格式，避免路径遍历
  if (!isValidId(req.params.id)) {
    return res.status(400).json({ success: false, error: '非法的任务 ID', code: 'ERROR' });
  }
  const reportPath = path.join(OUTPUT_DIR, req.params.id, 'report.md');
  if (!fs.existsSync(reportPath)) return res.status(404).json({ success: false, error: '报告不存在', code: 'ERROR' });
  res.setHeader('Content-Type', 'text/markdown; charset=utf-8');
  res.sendFile(reportPath);
});

// 任务历史
app.get('/api/jobs', (_req, res) => {
  res.json({
    success: true,
    active: Array.from(activeJobs.keys()),
    history: jobHistory.slice(-50),
    cacheSize: resultCache.size,
  });
});

// 主动取消正在运行的任务（支持 SUPER 模式常驻 Worker 与普通 Python 子进程）
app.post('/api/cancel/:id', (req, res) => {
  const id = req.params.id;
  // 1. 若任务仍在队列中，直接移除
  const queueIdx = jobQueue.findIndex((j) => j.id === id);
  if (queueIdx >= 0) {
    const removed = jobQueue.splice(queueIdx, 1)[0];
    try { removed.res.end(); } catch (_) {}
    recordJob(id, removed.mode, 'cancelled', '任务在队列中被取消');
    logToFile('info', `任务在队列中取消 job=${id}`);
    return res.json({ success: true, cancelled: true, reason: 'removed_from_queue' });
  }

  // 2. 若任务正在运行/等待，区分 SUPER 与普通进程分别处理
  const proc = activeJobs.get(id);
  const jobRes = activeJobResponses.get(id);
  if (!proc) {
    return res.status(404).json({ success: false, error: '未找到运行中任务' });
  }

  // 2a. SUPER 模式：等待中的占位任务（isSuperQueued），通过标记取消并释放槽位
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
    recordJob(id, 'super', 'cancelled', '等待 Worker 期间被用户取消');
    logToFile('info', `用户取消等待中的 SUPER 任务 job=${id}`);
    return res.json({ success: true, cancelled: true, reason: 'super_queued_cancelled' });
  }

  // 2b. SUPER 模式：正在 Worker 上运行的任务，发送取消信号而非杀死常驻 Worker（P0-3）
  if (jobRes && jobRes.mode === 'super') {
    try {
      proc.stdin.write(JSON.stringify({ type: 'cancel', id }) + '\n', 'utf-8');
    } catch (err) {
      logToFile('warn', `SUPER 取消信号发送失败 job=${id}: ${err.message}`);
    }
    // 置空 handler 防止 Worker 后续 error 事件重复写已关闭的响应；释放 Worker 给下一任务
    currentLlamaHandler = null;
    releaseLlamaWorker();
    activeJobs.delete(id);
    activeJobResponses.delete(id);
    if (jobRes) {
      try {
        sendSSE(jobRes.res, 'error', { message: '用户主动停止计算' });
        sendSSE(jobRes.res, 'done', { code: 125 });
        jobRes.res.end();
      } catch (_) {}
    }
    recordJob(id, 'super', 'cancelled', '用户主动停止');
    logToFile('info', `用户主动取消 SUPER 任务（发送取消信号）job=${id}`);
    return res.json({ success: true, cancelled: true, reason: 'super_cancel_signal' });
  }

  // 2c. 普通子进程：终止进程并通知前端
  // P2-7：SIGTERM 后 5 秒未退出则 SIGKILL 兜底，防止僵尸进程
  try {
    killProcessWithFallback(proc);
  } catch (err) {
    logToFile('warn', `取消任务 kill 失败 job=${id}: ${err.message}`);
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
  recordJob(id, jobRes?.mode || 'unknown', 'cancelled', '用户主动停止');
  logToFile('info', `用户主动取消任务 job=${id}`);
  res.json({ success: true, cancelled: true, reason: 'process_terminated' });
});



// 磁盘空间检查（生产环境避免写满）
function getDiskSpaceInfo() {
  try {
    const stats = fs.statSync(WORK_DIR);
    // Windows 下无法直接通过 fs 获取总空间，这里仅作目录可写性探针
    const testFile = path.join(WORK_DIR, '.space_probe');
    fs.writeFileSync(testFile, '1');
    fs.unlinkSync(testFile);
    return { writable: true };
  } catch (err) {
    return { writable: false, error: err.message };
  }
}

// 健康检查
app.get('/api/health', (_req, res) => {
  const validation = validateSkillDir();
  const disk = getDiskSpaceInfo();
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

// 配置信息
app.get('/api/config', (_req, res) => {
  const llamaScript = getLlamaWorkerScript();
  const llamaAvailable = fs.existsSync(llamaScript);

  res.json({
    success: true,
    config: { ...CONFIG, skillDir: CONFIG.skillDir },
    bridgeParamSchema: BRIDGE_PARAM_SCHEMA,
    superBridgeParamSchema: SUPER_BRIDGE_PARAM_SCHEMA,
    modes: {
      light: { label: 'LIGHT', description: '快速 jieba 概念图 + 简化流程' },
      deep: { label: 'DEEP', description: '完整六战士 + 稳定性检查（jieba 概念图）' },
      super: { label: 'SUPER', description: 'LLaMA TRACE 模型驱动 + 完整六合一（最慢最准）', available: llamaAvailable && PROBED_LLAMA_MODELS.length > 0 },
    },
    presets: ['default', 'sensitive', 'broad', 'deep', 'llama'],
    llamaModels: {
      default: 'shehui-llama',
      available: PROBED_LLAMA_MODELS,
    },
    llamaWorker: {
      available: llamaAvailable,
      script: llamaScript,
      ready: llamaWorkerReady,
      busy: llamaWorkerBusy,
    },
    buildInfo: BUILD_INFO,
  });
});

// 队列状态
app.get('/api/queue', (_req, res) => {
  res.json({
    success: true,
    active: Array.from(activeJobs.keys()),
    queued: jobQueue.map((j) => ({ id: j.id, mode: j.mode, textLength: j.text.length })),
    maxConcurrent: CONFIG.maxConcurrentJobs,
  });
});

// 版本与服务识别（多云部署/负载均衡探针）
app.get('/api/version', (_req, res) => {
  res.json({
    success: true,
    ...BUILD_INFO,
    skillReady: validateSkillDir().ok,
    pythonCmd: CONFIG.pythonCmd,
  });
});

// 参数预设（便于前端一键切换业务场景）
// 与 presets.yaml 中的 trace2dowhy + super 段对齐，便于多云参数穿透。
app.get('/api/presets', (_req, res) => {
  const base = {
    threshold: 0.03,
    window_size: 8,
    max_concepts: 12,
    concept_min_freq: 2,
    min_valid_tokens: 10,
    max_edges_for_dowhy: 8,
    filter_mode: 'topn',
    filter_percentile: 85,
    random_state: 42,
  };
  res.json({
    success: true,
    presets: {
      default: { ...base, threshold: 0.03, window_size: 8, max_segments: 4, classical_mode: false, min_valid_tokens: 10 },
      sensitive: { ...base, threshold: 0.3, window_size: 6, max_concepts: 16, concept_min_freq: 2, max_segments: 3, classical_mode: false, min_valid_tokens: 8 },
      broad: { ...base, threshold: 0.8, window_size: 12, max_concepts: 24, max_segments: 6, classical_mode: false, min_valid_tokens: 12 },
      deep: { ...base, threshold: 0.2, window_size: 8, max_concepts: 24, max_edges_for_dowhy: 15, filter_mode: 'percentile', filter_percentile: 80, max_segments: 4, classical_mode: false, min_valid_tokens: 10 },
      llama: { threshold: 0.01, window_size: 128, max_segments: 3, max_concepts: 12, concept_min_freq: 1, max_edges_for_dowhy: 12, filter_mode: 'topn', filter_percentile: 85, random_state: 42, classical_mode: false, min_valid_tokens: 10 },
    },
  });
});

// 参数 Schema（便于前端自动生成表单、多云参数校验）
app.get('/api/schema', (_req, res) => {
  res.json({
    success: true,
    schema: BRIDGE_PARAM_SCHEMA,
    superSchema: SUPER_BRIDGE_PARAM_SCHEMA,
    modes: ['light', 'deep', 'super'],
    presets: ['default', 'sensitive', 'broad', 'deep', 'llama'],
  });
});

// 运行时指标（便于监控与多云负载感知）
app.get('/api/metrics', (_req, res) => {
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
    // S17：暴露 LLaMA Worker 运行时状态，便于监控 SUPER 模式可用性与排队情况
    llamaWorkerReady,
    llamaWorkerBusy,
    llamaWorkerJobWaiters: llamaWorkerJobWaiters.length,
    timestamp: new Date().toISOString(),
  });
});

// 任务历史管理：导出 / 清空（必须在 /api/jobs/:id 之前定义，避免被 :id 路由吞掉）
app.get('/api/jobs/export', (_req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Content-Disposition', 'attachment; filename="trace_jobs.json"');
  res.json({ success: true, exportedAt: new Date().toISOString(), jobs: jobHistory });
});

app.post('/api/jobs/clear', (_req, res) => {
  jobHistory.length = 0;
  persistJobHistory();
  res.json({ success: true, message: '任务历史已清空' });
});

// 单任务查询（便于轮询或前端状态同步）
app.get('/api/jobs/:id', (req, res) => {
  const id = req.params.id;
  const active = activeJobs.has(id);
  const history = jobHistory.find((j) => j.id === id);
  const outputExists = fs.existsSync(path.join(OUTPUT_DIR, id, 'result.json'));
  if (!active && !history && !outputExists) {
    return res.status(404).json({ success: false, error: '任务不存在' });
  }
  res.json({
    success: true,
    id,
    active,
    history: history || null,
    resultPath: outputExists ? `/api/result/${id}` : null,
    reportPath: fs.existsSync(path.join(OUTPUT_DIR, id, 'report.md')) ? `/api/report/${id}` : null,
  });
});

// 任务重试（人性化操作：失败/超时任务一键重跑）
app.post('/api/retry/:id', async (req, res) => {
  const id = req.params.id;
  const old = jobHistory.find((j) => j.id === id);
  if (!old) {
    return res.status(404).json({ success: false, error: '未找到该任务历史' });
  }
  if (!['error', 'timeout', 'cancelled'].includes(old.status)) {
    return res.status(400).json({ success: false, error: `当前状态 ${old.status} 不支持重试` });
  }
  // S7：历史记录不再存全量 text，优先用 old.text（旧记录兼容），否则从 inputs 文件读取
  let retryText = old.text;
  if (!retryText) {
    const inputPath = path.join(WORK_DIR, 'inputs', `${id}.txt`);
    if (!fs.existsSync(inputPath)) {
      return res.status(400).json({ success: false, error: '历史记录中未保留原始文本，无法重试' });
    }
    try {
      retryText = fs.readFileSync(inputPath, 'utf-8');
    } catch (err) {
      return res.status(400).json({ success: false, error: `读取历史文本失败: ${err.message}` });
    }
  }
  // SUPER 模式依赖常驻 LLaMA Worker 与 SSE 流，同步重试无法承载模型加载与流式输出。
  if (old.mode === 'super') {
    return res.status(400).json({ success: false, error: 'SUPER 模式不支持同步重试，请在前端重新提交分析', code: 'SUPER_RETRY_NOT_SUPPORTED', originalId: id });
  }
  // S13：重试前对历史 text 与 config 重新走 validateAnalysisInput，
  // 防止历史记录中过长的 text 或非法 config 绕过校验直接进入分析流程
  let retryCfgObj = null;
  if (old.config) {
    try { retryCfgObj = JSON.parse(old.config); } catch (_) { retryCfgObj = null; }
  }
  const retryValidation = validateAnalysisInput(retryText, old.mode || 'light', retryCfgObj);
  if (!retryValidation.ok) {
    return res.status(400).json({ success: false, error: retryValidation.error, code: retryValidation.code || 'RETRY_VALIDATION_FAILED', field: retryValidation.field, originalId: id });
  }
  // 基于校验后已过滤未知字段的 cfgObj 重新序列化 config
  const retryConfig = retryCfgObj && typeof retryCfgObj === 'object' ? JSON.stringify(retryCfgObj) : (old.config || '');
  const newId = uuidv4();
  try {
    const data = await runPythonAnalysisSync(retryText, newId, old.mode || 'light', retryConfig);
    res.json({ success: true, message: '重试任务已启动', originalId: id, newId, data });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// 结果目录清理（手动触发，便于运维）
app.post('/api/admin/cleanup', (_req, res) => {
  cleanupOldOutputs();
  res.json({ success: true, message: '输出目录清理完成' });
});

app.use((err, req, res, _next) => {
  reqLog(req, 'error', `Express 错误: ${err.message}`);
  res.status(500).json({ success: false, error: err.message, traceId: req.traceId });
});

const server = app.listen(PORT, () => {
  console.log(`TRACE Engine Web MVP 运行在 http://localhost:${PORT}`);
  console.log(`工作目录: ${WORK_DIR}`);
  console.log(`Skill 目录: ${CONFIG.skillDir}`);
  console.log(`输出 TTL: ${CONFIG.outputTtlMs}ms`);
  console.log(`最大并发任务: ${CONFIG.maxConcurrentJobs}, 超时: ${CONFIG.jobTimeoutMs}ms`);
  logToFile('info', `服务启动 port=${PORT} work=${WORK_DIR} skill=${CONFIG.skillDir}`);
});

// 优雅关闭：收到终止信号时先停止接收新连接，再清理活跃任务
// S6：修复多类缺陷——使用 killProcessWithFallback 防止僵尸进程、
// 区分 SUPER 占位对象（无 kill 方法）、显式终止 LLaMA Worker、清理全局定时器
function gracefulShutdown(signal) {
  console.log(`[${signal}] 正在优雅关闭服务...`);
  logToFile('info', `收到 ${signal}，开始优雅关闭`);
  server.close(() => {
    // 遍历活跃任务，区分真实子进程与 SUPER 占位对象分别处理
    for (const [id, proc] of activeJobs.entries()) {
      try {
        if (proc && typeof proc.kill === 'function') {
          // 真实子进程：SIGTERM 后 5 秒未退出则 SIGKILL 兜底
          killProcessWithFallback(proc);
        } else if (proc && typeof proc.cancel === 'function') {
          // SUPER 占位对象（等待 Worker 中的任务）无 kill 方法，调用 cancel 标记取消
          proc.cancel();
        }
        recordJob(id, null, 'terminated_by_shutdown');
      } catch (_) {}
    }
    // 显式终止常驻 LLaMA Worker，避免僵尸进程残留
    if (llamaWorker) {
      try { killProcessWithFallback(llamaWorker); } catch (_) {}
      llamaWorker = null;
      llamaWorkerReady = false;
    }
    // 清理全局定时器，避免进程因活跃句柄延迟退出
    try { clearInterval(cleanupInterval); } catch (_) {}
    try { clearTimeout(startupCleanupTimer); } catch (_) {}
    persistJobHistory();
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
