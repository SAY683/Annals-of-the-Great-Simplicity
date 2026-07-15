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
 *
 * 端点:
 *   POST /api/analyze-text         分析纯文本 (JSON: {text, mode})
 *   POST /api/analyze-file         上传文本文件分析 (multipart: file, mode)
 *   GET  /api/analyze-stream?id=   SSE 实时流（阶段+日志+结果）
 *   POST /api/cancel/:id           取消分析任务
 *   GET  /api/result/:id           获取分析结果 (JSON)
 *   GET  /api/report/:id           获取 Markdown 报告
 *   GET  /api/jobs                 任务历史列表
 *   GET  /api/health               健康检查
 *   GET  /api/config               当前配置
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
    for name in ['shehui-llama', 'shenji-llama', 'Shehui-LLaMA', 'Shenji-LLaMA']:
        d = p.model_dir(name)
        if d.exists() and (d / 'model.safetensors').exists():
            print(json.dumps({'id': name.lower(), 'name': name, 'path': str(d)}))
except Exception as e:
    print(json.dumps({'error': str(e)}))
`;
  try {
    fs.writeFileSync(tmpFile, script, { encoding: 'utf-8' });
    const result = require('child_process').execSync(
      `${process.env.PYTHON_CMD || 'python'} "${tmpFile}"`,
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

  worker.on('close', (code) => {
    logToFile('warn', `LLaMA Worker 退出 (code=${code})，清理状态`);
    // 通知当前关联的 SUPER 任务（若存在）
    if (currentLlamaHandler && activeJobs.size > 0) {
      const activeId = Array.from(activeJobs.keys()).find(() => true);
      if (activeId) {
        // 通过历史记录查找对应的 res 较复杂；这里依赖 runSuperAnalysisStream 内的 finish 兜底
        recordJob(activeId, 'super', 'cancelled', `Worker 退出 code=${code}`);
        activeJobs.delete(activeId);
      }
    }
    llamaWorker = null;
    llamaWorkerReady = false;
    llamaWorkerStarting = false;
    llamaWorkerBusy = false;
    currentLlamaHandler = null;
    processJobQueue();
  });

  worker.on('error', (err) => {
    logToFile('error', `LLaMA Worker 启动错误: ${err.message}`);
    llamaWorker = null;
    llamaWorkerReady = false;
    llamaWorkerStarting = false;
    llamaWorkerBusy = false;
    currentLlamaHandler = null;
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

// 日志持久化 + 简单轮转
function rotateLogIfNeeded() {
  try {
    if (fs.existsSync(LOG_FILE)) {
      const stats = fs.statSync(LOG_FILE);
      if (stats.size >= MAX_LOG_SIZE) {
        for (let i = MAX_LOG_BACKUPS - 1; i >= 1; i--) {
          const src = `${LOG_FILE}.${i}`;
          const dst = `${LOG_FILE}.${i + 1}`;
          if (fs.existsSync(src)) fs.renameSync(src, dst);
        }
        fs.renameSync(LOG_FILE, `${LOG_FILE}.1`);
      }
    }
  } catch (_) { /* ignore */ }
}

function logToFile(level, message, traceId = null) {
  const trace = traceId ? ` [${traceId}]` : '';
  const line = `[${new Date().toISOString()}]${trace} [${level}] ${message}\n`;
  try {
    rotateLogIfNeeded();
    fs.appendFileSync(LOG_FILE, line);
  } catch (_) { /* ignore */ }
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
    concept_min_freq: { type: 'integer', min: 1, max: 1000, default: 1, description: '概念最小出现频次' },
    min_valid_tokens: { type: 'integer', min: 1, max: 10000, default: 10, description: '最小有效 token 数' },
    min_concepts: { type: 'integer', min: 2, max: 128, default: 3, description: '最小概念数' },
    max_edges_for_dowhy: { type: 'integer', min: 1, max: 100, default: 12, description: '传入 DoWhy 的最大边数' },
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
  if (config && typeof config === 'object') {
    // SUPER 模式下 model 参数白名单校验
    if (mode === 'super' && config.model !== undefined) {
      const allowedModels = PROBED_LLAMA_MODELS.length > 0
        ? PROBED_LLAMA_MODELS.map((m) => m.id)
        : ['shehui-llama'];
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
      const unique = `${Date.now()}-${Math.round(Math.random() * 1e9)}-${file.originalname}`;
      cb(null, unique);
    },
  }),
  limits: { fileSize: 10 * 1024 * 1024 },
  fileFilter: (_req, file, cb) => {
    const allowed = ['text/plain', 'text/markdown', 'application/octet-stream'];
    if (allowed.includes(file.mimetype) || file.originalname.endsWith('.txt') || file.originalname.endsWith('.md')) {
      cb(null, true);
    } else {
      cb(new Error('仅支持 .txt / .md 文本文件'));
    }
  },
});

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
  const entry = {
    id,
    mode,
    status,
    createdAt: existing ? existing.createdAt : now,
    updatedAt: now,
    completedAt: ['completed', 'error', 'timeout', 'cancelled'].includes(status) ? now : undefined,
    durationMs: existing && existing.createdAt && ['completed', 'error', 'timeout', 'cancelled'].includes(status)
      ? Date.now() - new Date(existing.createdAt).getTime()
      : undefined,
    error,
    ...meta,
  };
  const idx = jobHistory.findIndex((j) => j.id === id);
  if (idx >= 0) {
    // 保留已有字段（如 text、config），避免后续更新时覆盖
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
setInterval(cleanupOldOutputs, Math.min(CONFIG.outputTtlMs, 3600000));
setTimeout(cleanupOldOutputs, 5000);

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
      TRACE_BRIDGE_CONFIG: CONFIG.bridgeConfig,
    },
  });

  activeJobs.set(outputId, py);

  let stdoutBuffer = '';
  let timeoutId = null;

  const cleanupTimeout = () => {
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
  };

  timeoutId = setTimeout(() => {
    logToFile('warn', `分析超时 job=${outputId}，强制终止`);
    sendSSE(res, 'error', { message: `分析超时（>${CONFIG.jobTimeoutMs}ms），已强制终止。请尝试 LIGHT 模式或缩短文本。` });
    try { py.kill('SIGTERM'); } catch (_) {}
    recordJob(outputId, mode, 'timeout');
  }, CONFIG.jobTimeoutMs);

  py.stdin.write(text, 'utf-8');
  py.stdin.end();

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

  // SUPER 模式不再使用固定超时硬限制，改为实时速率/ETA + 用户主动停止
  const modelNameLower = (cfgObj?.model || 'shehui-llama').toLowerCase();
  const isLargeModel = modelNameLower.includes('shenji') || modelNameLower.includes('shehui');
  // 保留 24 小时安全兜底，防止进程彻底失控；正常流程依赖用户主动停止
  const superTimeoutMs = 24 * 60 * 60 * 1000;
  if (isLargeModel) {
    sendSSE(res, 'log', { level: 'warn', message: '当前 SUPER 模式使用 470M 级 LLaMA 模型（Shehui/Shenji 均为 1.88GB 左右），推理速度较慢。界面会实时显示处理速率与预计剩余时间；如无法接受等待时长，可随时点击“停止计算”。超大模型会自动限制 window_size≤32 / max_segments≤2 以控制显存与耗时。' });
  }

  let timeoutId = null;
  let finished = false;
  let lastStageName = 'init';
  let lastStageTime = Date.now();
  const taskStartTime = Date.now();
  let keepAlive = null;

  const cleanupTimeout = () => {
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
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

    activeJobs.set(outputId, worker);

    currentLlamaHandler = (obj) => {
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

    worker.stdin.write(JSON.stringify({
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
  const bridgeConfig = parseBridgeConfig(req.query.config || req.body.config);

  const cfgObj = bridgeConfig ? (() => { try { return JSON.parse(bridgeConfig); } catch (_) { return null; } })() : null;
  const validation = validateAnalysisInput(text, mode, cfgObj);
  if (!validation.ok) {
    reqLog(req, 'warn', `SSE 输入校验失败: ${validation.error} (${validation.code || ''})`);
    return res.status(400).json({ success: false, error: validation.error, code: validation.code, field: validation.field, traceId: req.traceId });
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
    const bridgeConfig = parseBridgeConfig(req.body.config);
    const cfgObj = bridgeConfig ? JSON.parse(bridgeConfig) : null;

    const validation = validateAnalysisInput(text, mode, cfgObj);
    if (!validation.ok) {
      reqLog(req, 'warn', `输入校验失败: ${validation.error} (${validation.code || ''})`);
      return res.status(400).json({ success: false, error: validation.error, code: validation.code, field: validation.field, traceId: req.traceId });
    }
    if (mode === 'super') {
      return res.status(400).json({ success: false, error: 'SUPER 模式请使用 /api/analyze-stream 流式接口', code: 'SUPER_REQUIRES_STREAM', traceId: req.traceId });
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
    const bridgeConfig = parseBridgeConfig(req.body.config);
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

app.get('/api/result/:id', (req, res) => {
  const resultPath = path.join(OUTPUT_DIR, req.params.id, 'result.json');
  if (!fs.existsSync(resultPath)) return res.status(404).json({ error: '结果不存在' });
  res.setHeader('Content-Type', 'application/json');
  res.sendFile(resultPath);
});

app.get('/api/report/:id', (req, res) => {
  const reportPath = path.join(OUTPUT_DIR, req.params.id, 'report.md');
  if (!fs.existsSync(reportPath)) return res.status(404).json({ error: '报告不存在' });
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

  // 2. 若任务正在运行，终止对应进程并通知前端
  const proc = activeJobs.get(id);
  const jobRes = activeJobResponses.get(id);
  if (!proc) {
    return res.status(404).json({ success: false, error: '未找到运行中任务' });
  }
  try {
    proc.kill('SIGTERM');
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
    concept_min_freq: 1,
    min_concepts: 3,
    min_valid_tokens: 10,
    max_edges_for_dowhy: 12,
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
    timestamp: new Date().toISOString(),
  });
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
  if (!old.text) {
    return res.status(400).json({ success: false, error: '历史记录中未保留原始文本，无法重试' });
  }
  // SUPER 模式依赖常驻 LLaMA Worker 与 SSE 流，同步重试无法承载模型加载与流式输出。
  if (old.mode === 'super') {
    return res.status(400).json({ success: false, error: 'SUPER 模式不支持同步重试，请在前端重新提交分析', code: 'SUPER_RETRY_NOT_SUPPORTED', originalId: id });
  }
  const newId = uuidv4();
  try {
    const data = await runPythonAnalysisSync(old.text, newId, old.mode || 'light', old.config || '');
    res.json({ success: true, message: '重试任务已启动', originalId: id, newId, data });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// 任务历史管理：导出 / 清空（注意：必须在 /api/jobs/:id 之前定义，避免被 id 路由吞掉）
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
function gracefulShutdown(signal) {
  console.log(`[${signal}] 正在优雅关闭服务...`);
  logToFile('info', `收到 ${signal}，开始优雅关闭`);
  server.close(() => {
    for (const [id, py] of activeJobs.entries()) {
      try {
        py.kill('SIGTERM');
        recordJob(id, null, 'terminated_by_shutdown');
      } catch (_) {}
    }
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
