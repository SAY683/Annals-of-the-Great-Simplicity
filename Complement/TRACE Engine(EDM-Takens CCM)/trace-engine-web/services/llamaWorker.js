/**
 * TRACE Engine Web — LLaMA 常驻 Worker 管理模块
 * =====================================
 * 抽取自 server.js：probeLlamaModels、spawnLlamaWorker、ensureLlamaWorker、
 * waitForLlamaWorkerIdle、releaseLlamaWorker、dispatchLlamaMessage、logWorker。
 */
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const state = require('../lib/state');
const utils = require('../lib/utils');
const {
  CONFIG,
  WORK_DIR,
  OUTPUT_DIR,
  llamaState,
  MAX_WORKER_LOGS,
  activeJobs,
  activeJobResponses,
} = state;
const { logToFile, killProcessWithFallback } = utils;

// 通过 Python Skill 探测模型目录（兼容开发布局与层级成品布局）
function probeLlamaModels() {
  const models = [];
  const skillDir = CONFIG.skillDir;

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
    const probePythonCmd = process.env.TRACE_PYTHON_CMD || process.env.PYTHON_CMD || 'python';
    // P0 修复 (2026-07-30 审计): 改用 spawnSync + 参数数组，避免 shell 解释。
    // 原代码 execSync 的 shell 拼接在环境变量被污染时有命令注入风险。
    const spawnResult = require('child_process').spawnSync(
      probePythonCmd, [tmpFile],
      { encoding: 'utf-8', timeout: 15000, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }
    );
    const result = spawnResult.stdout || '';
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

function getLlamaWorkerScript() {
  return path.resolve(__dirname, '..', 'llama_worker.py');
}

function logWorker(line) {
  llamaState.logs.push({ time: new Date().toISOString(), line });
  if (llamaState.logs.length > MAX_WORKER_LOGS) llamaState.logs.shift();
}

function dispatchLlamaMessage(obj) {
  if (llamaState.currentHandler) {
    llamaState.currentHandler(obj);
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

  // P1-9：worker 为常驻进程，此处一次性挂载 stdin 'error' 监听器即可
  worker.stdin.on('error', (err) => {
    logToFile('error', `LLaMA Worker stdin 错误: ${err.message}`);
  });

  worker.on('close', (code) => {
    logToFile('warn', `LLaMA Worker 退出 (code=${code})，清理状态`);
    // 仅通知当前关联的 SUPER 任务（通过 currentLlamaHandler 追踪的 outputId）
    if (llamaState.currentHandler && llamaState.currentHandler.outputId) {
      const activeId = llamaState.currentHandler.outputId;
      if (activeJobs.has(activeId)) {
        utils.recordJob(activeId, 'super', 'cancelled', `Worker 退出 code=${code}`);
        activeJobs.delete(activeId);
        const jobRes = activeJobResponses.get(activeId);
        if (jobRes) {
          try {
            // 注意：sendSSE 由 analysis.js 提供，这里用 require 兜底避免循环依赖
            const analysis = require('./analysis');
            analysis.sendSSE(jobRes.res, 'error', { message: `LLaMA Worker 退出 (code=${code})` });
            analysis.sendSSE(jobRes.res, 'done', { code: -1 });
            jobRes.res.end();
          } catch (_) {}
          activeJobResponses.delete(activeId);
        }
      }
    }
    llamaState.worker = null;
    llamaState.ready = false;
    llamaState.starting = false;
    llamaState.busy = false;
    llamaState.currentHandler = null;
    // 唤醒所有等待 Worker 空闲的任务，避免 Worker 崩溃后永久死锁
    const jobWaiters = llamaState.jobWaiters; llamaState.jobWaiters = [];
    jobWaiters.forEach((fn) => fn());
    // reject 所有等待 Worker 启动的请求
    const startWaiters = llamaState.startWaiters; llamaState.startWaiters = [];
    startWaiters.forEach((w) => w.reject(new Error('LLaMA Worker 退出')));
    // 触发队列处理（避免循环依赖，通过事件总线或直接 require）
    try { require('./analysis').processJobQueue(); } catch (_) {}
  });

  worker.on('error', (err) => {
    logToFile('error', `LLaMA Worker 启动错误: ${err.message}`);
    llamaState.worker = null;
    llamaState.ready = false;
    llamaState.starting = false;
    llamaState.busy = false;
    llamaState.currentHandler = null;
    // 同样唤醒所有 waiters，避免错误后死锁
    const jobWaiters = llamaState.jobWaiters; llamaState.jobWaiters = [];
    jobWaiters.forEach((fn) => fn());
    const startWaiters = llamaState.startWaiters; llamaState.startWaiters = [];
    startWaiters.forEach((w) => w.reject(new Error('LLaMA Worker 启动错误: ' + err.message)));
  });

  return worker;
}

function ensureLlamaWorker() {
  return new Promise((resolve, reject) => {
    if (llamaState.worker && llamaState.ready) return resolve(llamaState.worker);
    if (llamaState.starting) {
      llamaState.startWaiters.push({ resolve, reject });
      return;
    }
    llamaState.starting = true;
    llamaState.worker = spawnLlamaWorker();
    if (!llamaState.worker) {
      llamaState.starting = false;
      return reject(new Error('LLaMA Worker 启动失败（llama_worker.py 不存在或环境缺失）'));
    }
    // 等待 Worker 就绪日志
    const timer = setTimeout(() => {
      llamaState.starting = false;
      // P1-8：超时后清理所有等待启动的 waiter
      const waiters = llamaState.startWaiters; llamaState.startWaiters = [];
      waiters.forEach((w) => w.reject(new Error('LLaMA Worker 启动超时')));
      if (llamaState.worker) {
        // P1-6 修复 (ROUND27 12维度核对): 原用 worker.kill() (SIGTERM),
        // Windows 上 SIGTERM 不可靠. 改用 killProcessWithFallback (SIGTERM→5s→SIGKILL),
        // 与 server.js gracefulShutdown 中的清理逻辑对齐.
        try { killProcessWithFallback(llamaState.worker); } catch (_) {}
        llamaState.worker = null;
      }
      llamaState.ready = false;
      reject(new Error('LLaMA Worker 启动超时'));
    }, 120000);

    const onData = (chunk) => {
      const text = chunk.toString('utf-8');
      if (text.includes('LLaMA Worker') && text.includes('等待任务')) {
        clearTimeout(timer);
        llamaState.worker.stdout.off('data', onData);
        llamaState.ready = true;
        llamaState.starting = false;
        resolve(llamaState.worker);
        for (const waiter of llamaState.startWaiters) waiter.resolve(llamaState.worker);
        llamaState.startWaiters = [];
      }
    };
    llamaState.worker.stdout.on('data', onData);
  });
}

function waitForLlamaWorkerIdle() {
  return new Promise((resolve) => {
    if (!llamaState.busy) return resolve();
    llamaState.jobWaiters.push(resolve);
  });
}

function releaseLlamaWorker() {
  llamaState.busy = false;
  llamaState.currentHandler = null;
  const next = llamaState.jobWaiters.shift();
  if (next) next();
}

// 优雅关闭时显式终止 Worker
function terminateLlamaWorker() {
  if (llamaState.worker) {
    try { killProcessWithFallback(llamaState.worker); } catch (_) {}
    llamaState.worker = null;
    llamaState.ready = false;
  }
}

module.exports = {
  probeLlamaModels,
  getLlamaWorkerScript,
  spawnLlamaWorker,
  ensureLlamaWorker,
  waitForLlamaWorkerIdle,
  releaseLlamaWorker,
  dispatchLlamaMessage,
  logWorker,
  terminateLlamaWorker,
};
