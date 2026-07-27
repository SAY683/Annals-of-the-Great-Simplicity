/**
 * TRACE Engine Web — 通用工具模块
 * =====================================
 * 抽取自 server.js 的纯工具函数：日志、缓存键、任务记录、Schema 加载、
 * 进程终止兜底、背压写入、输入校验、ID 校验等。
 */
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');

const state = require('./state');
const {
  CONFIG,
  WORK_DIR,
  INPUTS_DIR,
  OUTPUT_DIR,
  HISTORY_FILE,
  LOG_FILE,
  MAX_LOG_SIZE,
  MAX_LOG_BACKUPS,
  ensureDir,
  jobHistory,
  activeJobs,
  activeJobResponses,
  resultCache,
  llamaState,
} = state;

// ── 日志持久化 + 简单轮转 ────────────────────────────────────────────
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
  rotateLogIfNeeded()
    .then(() => { fs.appendFile(LOG_FILE, line, () => { /* ignore */ }); })
    .catch(() => { /* ignore */ });
}

function reqLog(req, level, message) {
  logToFile(level, message, req.traceId);
}

// ── 任务历史持久化（debt-14：异步化） ────────────────────────────────
// 全局写锁：避免并发写覆盖（persistJobHistory 是 best-effort 串行化）
let _persistLock = Promise.resolve();
function persistJobHistory() {
  _persistLock = _persistLock.then(async () => {
    try {
      await fs.promises.writeFile(
        HISTORY_FILE,
        JSON.stringify(jobHistory.slice(-CONFIG.maxJobHistory), null, 2),
        'utf-8'
      );
    } catch (_) { /* ignore */ }
  });
  return _persistLock;
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

// ── 任务记录（含 textHash + textPreview + inputs 持久化） ───────────
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
    // R13-3 修缮：记录写盘是否成功，让详情面板能区分"未落盘"vs"已被清理"
    let inputPersisted = true;
    try {
      ensureDir(INPUTS_DIR);
      fs.writeFileSync(path.join(INPUTS_DIR, `${id}.txt`), fullText, 'utf-8');
    } catch (err) {
      inputPersisted = false;
      logToFile('warn', `保存任务输入文本失败 job=${id}: ${err.message}`);
    }
    entryMeta.inputPersisted = inputPersisted;
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

// ── 缓存键（含 config，避免不同参数复用错误结果） ──────────────────
function cacheKey(text, mode, cfgObj = null) {
  const cfgPart = cfgObj ? `:${JSON.stringify(cfgObj)}` : '';
  return crypto.createHash('sha256').update(`${mode}:${text}${cfgPart}`).digest('hex');
}

// ── 结果缓存写入（含 TTL，debt-14） ─────────────────────────────────
function setResultCache(key, id) {
  resultCache.set(key, { id, timestamp: Date.now(), expireAt: Date.now() + CONFIG.cacheTtlMs });
  while (resultCache.size > CONFIG.maxCacheEntries) {
    const firstKey = resultCache.keys().next().value;
    resultCache.delete(firstKey);
  }
}

// 定期清理过期缓存（debt-14：内存缓存 TTL）
function startCacheTtlSweeper(intervalMs = 5 * 60 * 1000) {
  return setInterval(() => {
    const now = Date.now();
    let cleaned = 0;
    for (const [k, v] of resultCache.entries()) {
      if (v.expireAt && v.expireAt < now) {
        resultCache.delete(k);
        cleaned += 1;
      }
    }
    if (cleaned > 0) {
      logToFile('info', `缓存 TTL 清理：移除 ${cleaned} 条过期条目，剩余 ${resultCache.size}`);
    }
  }, intervalMs);
}

// ── 桥接参数 Schema 加载（debt-16：复用 schema/bridge_schema.json） ─
function loadBridgeParamSchema(preset = null, probedLlamaModels = []) {
  // 优先尝试 trace-engine/build_bridge_schema.py（与 engine presets.yaml 一致）
  const schemaScript = path.resolve(CONFIG.skillDir, '..', '..', 'build_bridge_schema.py');
  if (fs.existsSync(schemaScript)) {
    try {
      const args = [schemaScript, CONFIG.skillDir];
      if (preset) args.push('--preset', preset);
      const result = require('child_process').spawnSync(
        CONFIG.pythonCmd,
        args,
        { encoding: 'utf-8', timeout: 15000, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }
      );
      if (result.status === 0) {
        const schema = JSON.parse(result.stdout);
        logToFile('info', `已从 presets.yaml 加载桥接参数 Schema (${preset || 'default'})，共 ${Object.keys(schema).length} 项`);
        return schema;
      }
      logToFile('warn', `build_bridge_schema.py 失败: ${result.stderr || 'unknown'}`);
    } catch (err) {
      logToFile('warn', `build_bridge_schema.py 异常: ${err.message}`);
    }
  }
  // 回退：从 schema/bridge_schema.json 读取统一兜底定义
  const fallbackFile = path.resolve(__dirname, '..', 'schema', 'bridge_schema.json');
  try {
    const raw = JSON.parse(fs.readFileSync(fallbackFile, 'utf-8'));
    return preset === 'llama' ? (raw.llama || raw.default) : raw.default;
  } catch (err) {
    logToFile('warn', `读取 bridge_schema.json 失败: ${err.message}`);
  }
  // 最终硬编码兜底（极少数情况）
  return _hardcodedBridgeFallback(preset === 'llama');
}

function _hardcodedBridgeFallback(isLlama = false) {
  const base = {
    threshold: { type: 'number', min: 0, max: 10, default: 0.03, description: '因果边显著性阈值' },
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
    classical_mode: { type: 'boolean', default: false, description: '古汉语模式' },
  };
  if (isLlama) {
    return Object.assign({}, base, {
      threshold: { type: 'number', min: 0, max: 10, default: 0.01, description: '因果边显著性阈值（LLaMA V4 专属）' },
      window_size: { type: 'integer', min: 2, max: 256, default: 128, description: 'TRACE 滑动窗口大小（LLaMA V4 专属）' },
      max_segments: { type: 'integer', min: 1, max: 16, default: 3, description: 'LLaMA TRACE 最大分段数（LLaMA V4 专属）' },
      concept_min_freq: { type: 'integer', min: 1, max: 1000, default: 1, description: '概念最小出现频次（LLaMA V4 专属）' },
      max_edges_for_dowhy: { type: 'integer', min: 1, max: 100, default: 12, description: '传入 DoWhy 的最大边数' },
    });
  }
  return base;
}

// ── 输入校验（LIGHT/DEEP/SUPER 通用） ──────────────────────────────
function validateAnalysisInput(text, mode, config, schemaCtx = {}) {
  const {
    bridgeParamSchema = null,
    superBridgeParamSchema = null,
    probedLlamaModels = [],
  } = schemaCtx;

  if (typeof text !== 'string' || text.trim().length === 0) {
    return { ok: false, error: '文本不能为空', code: 'EMPTY_TEXT' };
  }
  if (text.length > CONFIG.maxTextLength) {
    return { ok: false, error: `文本长度超过限制 ${CONFIG.maxTextLength}`, code: 'TEXT_TOO_LONG' };
  }
  if (!['light', 'deep', 'super'].includes(mode)) {
    return { ok: false, error: 'mode 必须是 light、deep 或 super', code: 'INVALID_MODE' };
  }
  // S16：SUPER 模式依赖探测到的 LLaMA 模型
  if (mode === 'super' && probedLlamaModels.length === 0) {
    return { ok: false, error: 'SUPER 模式不可用：未探测到任何 LLaMA 模型，请检查模型目录或 TRACE_ENGINE_SKILL_DIR 配置', code: 'SUPER_NO_MODELS', field: 'model' };
  }
  if (config && typeof config === 'object') {
    // SUPER 模式下 model 参数白名单校验（仅基于探测结果）
    if (mode === 'super' && config.model !== undefined) {
      const allowedModels = probedLlamaModels.map((m) => m.id);
      if (!allowedModels.includes(config.model)) {
        return { ok: false, error: `SUPER 模式不支持模型 ${config.model}，可用: ${allowedModels.join(', ')}`, code: 'INVALID_MODEL', field: 'model' };
      }
    }
    const schemaToValidate = mode === 'super' ? superBridgeParamSchema : bridgeParamSchema;
    if (schemaToValidate) {
      for (const [k, schema] of Object.entries(schemaToValidate)) {
        if (config[k] === undefined) continue;
        const v = config[k];
        if (schema.type === 'integer' && (!Number.isInteger(v) || v < schema.min || v > schema.max)) {
          return { ok: false, error: `参数 ${k} 必须是 [${schema.min}, ${schema.max}] 之间的整数`, code: 'INVALID_PARAM', field: k };
        }
        if (schema.type === 'number' && (typeof v !== 'number' || Number.isNaN(v) || v < schema.min || v > schema.max)) {
          return { ok: false, error: `参数 ${k} 必须在 [${schema.min}, ${schema.max}] 之间`, code: 'INVALID_PARAM', field: k };
        }
        if (schema.type === 'boolean' && typeof v !== 'boolean') {
          return { ok: false, error: `参数 ${k} 必须是布尔值 (true/false)`, code: 'INVALID_PARAM', field: k };
        }
      }
    }
    if (config.filter_mode !== undefined && !['topn', 'percentile', 'adaptive'].includes(config.filter_mode)) {
      return { ok: false, error: '参数 filter_mode 必须是 topn / percentile / adaptive 之一', code: 'INVALID_PARAM', field: 'filter_mode' };
    }
    // 过滤 config 中未在 schema 定义的字段
    if (schemaToValidate) {
      const allowedKeys = new Set(Object.keys(schemaToValidate));
      if (mode === 'super') allowedKeys.add('model');
      for (const k of Object.keys(config)) {
        if (!allowedKeys.has(k)) {
          delete config[k];
        }
      }
    }
  }
  return { ok: true };
}

// ── ID 合法性校验（防路径遍历） ─────────────────────────────────────
const UUID_RE = /^[0-9a-f-]{36}$/i;
function isValidId(id) {
  return typeof id === 'string' && UUID_RE.test(id);
}

// ── Skill 目录校验 ──────────────────────────────────────────────────
function validateSkillDir() {
  const required = ['counterfactual_bridge.py', 'run_cli.py', '_token_filters.py'];
  const exists = fs.existsSync(CONFIG.skillDir);
  const missing = exists
    ? required.filter((f) => !fs.existsSync(path.join(CONFIG.skillDir, f)))
    : required;
  return { exists, missing, ok: exists && missing.length === 0 };
}

// ── Python 环境检查 ─────────────────────────────────────────────────
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
        } catch (_) { /* 回退到内联检查 */ }
      }
    } catch (_) { /* 回退到内联检查 */ }
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

// ── 进程终止兜底（P2-7：SIGTERM -> SIGKILL） ──────────────────────
function killProcessWithFallback(proc, delayMs = 5000) {
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

// ── 背压感知写入（P2-8） ──────────────────────────────────────────
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

// ── 解析桥接配置（query/body -> JSON 字符串） ─────────────────────
function parseBridgeConfig(raw) {
  if (!raw) return CONFIG.bridgeConfig || '';
  try {
    const obj = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return JSON.stringify(obj);
  } catch (_) {
    return String(raw);
  }
}

// ── 结果 Schema 加载（debt-10） ───────────────────────────────────
let _resultSchemaCache = null;
function loadResultSchema() {
  if (_resultSchemaCache) return _resultSchemaCache;
  const schemaFile = path.resolve(__dirname, '..', 'schema', 'result_schema.json');
  try {
    _resultSchemaCache = JSON.parse(fs.readFileSync(schemaFile, 'utf-8'));
  } catch (err) {
    logToFile('warn', `读取 result_schema.json 失败: ${err.message}`);
    _resultSchemaCache = null;
  }
  return _resultSchemaCache;
}

// ── 预设加载（debt-16 audit 修复：真正从 presets.yaml 读取） ─
// 优先通过 build_bridge_schema.py --presets-only 读取 presets（与 engine 对齐），
// 失败则回退到 schema/bridge_schema.json 中的 presets 段，
// 最终硬编码兜底。
function loadPresets() {
  // 优先尝试 trace-engine/build_bridge_schema.py（与 loadBridgeParamSchema 一致）
  const schemaScript = path.resolve(CONFIG.skillDir, '..', '..', 'build_bridge_schema.py');
  if (fs.existsSync(schemaScript)) {
    try {
      const result = require('child_process').spawnSync(
        CONFIG.pythonCmd,
        [schemaScript, CONFIG.skillDir, '--presets-only'],
        { encoding: 'utf-8', timeout: 15000, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }
      );
      if (result.status === 0) {
        const presets = JSON.parse(result.stdout);
        if (presets && Object.keys(presets).length > 0) {
          logToFile('info', `已从 presets.yaml 加载预设 (${Object.keys(presets).length} 套)`);
          return presets;
        }
      }
      logToFile('warn', `build_bridge_schema.py --presets-only 失败: ${result.stderr || 'unknown'}`);
    } catch (err) {
      logToFile('warn', `build_bridge_schema.py --presets-only 异常: ${err.message}`);
    }
  }
  // 回退：从 schema/bridge_schema.json 读取
  const fallbackFile = path.resolve(__dirname, '..', 'schema', 'bridge_schema.json');
  try {
    const raw = JSON.parse(fs.readFileSync(fallbackFile, 'utf-8'));
    if (raw.presets) return raw.presets;
  } catch (_) {}
  // 最终硬编码兜底
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
  return {
    default: { ...base, threshold: 0.03, window_size: 8, max_segments: 4, classical_mode: false, min_valid_tokens: 10 },
    sensitive: { ...base, threshold: 0.3, window_size: 6, max_concepts: 16, concept_min_freq: 2, max_segments: 3, classical_mode: false, min_valid_tokens: 8 },
    broad: { ...base, threshold: 0.8, window_size: 12, max_concepts: 24, max_segments: 6, classical_mode: false, min_valid_tokens: 12 },
    deep: { ...base, threshold: 0.2, window_size: 8, max_concepts: 24, max_edges_for_dowhy: 15, filter_mode: 'percentile', filter_percentile: 80, max_segments: 4, classical_mode: false, min_valid_tokens: 10 },
    llama: { threshold: 0.01, window_size: 128, max_segments: 3, max_concepts: 12, concept_min_freq: 1, max_edges_for_dowhy: 12, filter_mode: 'topn', filter_percentile: 85, random_state: 42, classical_mode: false, min_valid_tokens: 10 },
  };
}

module.exports = {
  // 日志
  logToFile,
  reqLog,
  rotateLogIfNeeded,
  // 任务历史
  loadJobHistory,
  persistJobHistory,
  recordJob,
  // 缓存
  cacheKey,
  setResultCache,
  startCacheTtlSweeper,
  // Schema
  loadBridgeParamSchema,
  loadResultSchema,
  loadPresets,
  // 校验
  validateAnalysisInput,
  isValidId,
  validateSkillDir,
  checkPythonEnv,
  // 进程/IO
  killProcessWithFallback,
  writeWithDrain,
  parseBridgeConfig,
};
