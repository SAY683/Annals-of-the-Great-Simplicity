/**
 * TRACE Engine Web — 分析任务执行模块
 * =====================================
 * 抽取自 server.js：sendSSE（含 SSE id/retry，debt-11）、runPythonAnalysisStream、
 * runSuperAnalysisStream、runPythonAnalysisSync、buildSuperReport、processJobQueue。
 */
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { v4: uuidv4 } = require('uuid');

const state = require('../lib/state');
const utils = require('../lib/utils');
const llamaWorkerSvc = require('./llamaWorker');
const {
  CONFIG,
  WORK_DIR,
  OUTPUT_DIR,
  activeJobs,
  activeJobResponses,
  jobHistory,
  resultCache,
  jobQueue,
  llamaState,
  nextSseEventId,
} = state;
const {
  logToFile,
  recordJob,
  cacheKey,
  setResultCache,
  killProcessWithFallback,
  writeWithDrain,
} = utils;

// ── SSE 发送（debt-11：递增 id + retry 重连间隔） ───────────────────
// 每个事件分配递增 id，重连时客户端通过 Last-Event-ID 头携带最后接收的 id，
// 服务端可基于此续传（当前实现：res.on('close') 仍取消任务，但客户端重连可
// 通过 /api/result/:id 获取已完成任务的结果）。
function sendSSE(res, event, data) {
  const id = nextSseEventId();
  res.write(`id: ${id}\n`);
  res.write(`event: ${event}\n`);
  res.write(`data: ${JSON.stringify(data)}\n\n`);
}

// 在 SSE 响应头之后发送 retry: 5000（5 秒重连间隔，debt-11）
function sendSSERetryHeader(res) {
  try { res.write('retry: 5000\n\n'); } catch (_) {}
}

/**
 * 流式调用 Python 桥接脚本分析文本（LIGHT / DEEP）
 */
function runPythonAnalysisStream(text, outputId, mode, bridgeConfig, res, schemaCtx = {}) {
  const skillDir = CONFIG.skillDir;
  const pyScript = path.resolve(__dirname, '..', 'py_bridge.py');
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
      TRACE_BRIDGE_CONFIG: cfg,
    },
  });

  activeJobs.set(outputId, py);

  let stdoutBuffer = '';
  let timeoutId = null;
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
    killProcessWithFallback(py);
    recordJob(outputId, mode, 'timeout');
  }, CONFIG.jobTimeoutMs);

  py.stdin.write(text, 'utf-8');
  py.stdin.end();

  // P2-9：SSE 客户端提前断开时清理 LIGHT/DEEP 资源
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

  // SSE 保活：每 30 秒发送一条注释
  const heartbeat = setInterval(() => {
    try { res.write(':heartbeat\n\n'); } catch (_) {}
  }, 30000);

  py.stdout.on('data', (chunk) => {
    stdoutBuffer += chunk.toString('utf-8');
    const lines = stdoutBuffer.split('\n');
    stdoutBuffer = lines.pop();

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
          setResultCache(cacheKey(text, mode, cfgObj), outputId);
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

  // P1-1/P1-2：入口处立即在 activeJobs 占位
  const placeholder = {
    isSuperQueued: true,
    cancelled: false,
    cancel: () => { placeholder.cancelled = true; },
  };
  activeJobs.set(outputId, placeholder);

  const modelNameLower = (cfgObj?.model || 'shehui-llama').toLowerCase();
  const isLightModel = modelNameLower.includes('shehui') && !modelNameLower.includes('archive');
  const isLargeModel = modelNameLower.includes('shenji') || modelNameLower.includes('archive');
  const superTimeoutMs = 24 * 60 * 60 * 1000;
  const _envStageTimeout = parseInt(process.env.TRACE_STAGE_TIMEOUT_MS, 10);
  const stageHangMs = Number.isFinite(_envStageTimeout) && _envStageTimeout > 0
    ? _envStageTimeout
    : 15 * 60 * 1000;
  if (isLargeModel) {
    sendSSE(res, 'log', { level: 'warn', message: '当前 SUPER 模式使用 470M 级 LLaMA 模型（Shenji/Archive 均为 1.88GB 左右），推理速度较慢。界面会实时显示处理速率与预计剩余时间；如无法接受等待时长，可随时点击"停止计算"。LLaMA 预设会自动设置 window_size=128 / max_segments=3 以平衡显存与因果覆盖。' });
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
    llamaWorkerSvc.releaseLlamaWorker();
    activeJobs.delete(outputId);
    activeJobResponses.delete(outputId);
    sendSSE(res, 'done', { code: doneCode });
    res.end();
    processJobQueue();
  };

  try {
    const worker = await llamaWorkerSvc.ensureLlamaWorker();
    await llamaWorkerSvc.waitForLlamaWorkerIdle();
    if (placeholder.cancelled) {
      llamaWorkerSvc.releaseLlamaWorker();
      activeJobs.delete(outputId);
      activeJobResponses.delete(outputId);
      recordJob(outputId, 'super', 'cancelled', '等待 Worker 期间被取消');
      logToFile('info', `SUPER 任务在等待 Worker 期间被取消 job=${outputId}`);
      try { sendSSE(res, 'error', { message: '用户主动停止计算' }); sendSSE(res, 'done', { code: 125 }); res.end(); } catch (_) {}
      processJobQueue();
      return;
    }
    llamaState.busy = true;

    timeoutId = setTimeout(() => {
      const elapsed = Date.now() - taskStartTime;
      const stageDur = Date.now() - lastStageTime;
      const msg = `SUPER 分析已运行超过 24 小时安全兜底。任务在 [${lastStageName}] 阶段停留约 ${stageDur}ms，总耗时 ${elapsed}ms。系统已强制终止；如仍需分析，请缩短文本、减小 window_size / max_segments、切换到 DEEP 模式，或检查模型/算力状态。`;
      logToFile('warn', `SUPER 安全兜底触发 job=${outputId} model=${cfgObj?.model || 'shehui-llama'} stage=${lastStageName} elapsed=${elapsed}`);
      sendSSE(res, 'error', { message: msg });
      recordJob(outputId, 'super', 'timeout');
      finish(124);
    }, superTimeoutMs);

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

    placeholder.isRunning = true;
    activeJobs.set(outputId, worker);

    llamaState.currentHandler = (obj) => {
      llamaState.currentHandler.outputId = outputId;
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
        setResultCache(cacheKey(text, 'super', cfgObj), outputId);
        recordJob(outputId, 'super', 'completed');
        logToFile('info', `SUPER 分析完成 job=${outputId}`);
        finish(0);
      }
    };

    // P1-3：SSE 客户端断开连接时清理 SUPER 资源
    res.on('close', () => {
      if (finished) return;
      logToFile('info', `SSE 客户端断开，清理 SUPER 任务 job=${outputId}`);
      try {
        worker.stdin.write(JSON.stringify({ type: 'cancel', id: outputId }) + '\n', 'utf-8');
      } catch (_) {}
      recordJob(outputId, 'super', 'cancelled', '客户端断开连接');
      finished = true;
      cleanupTimeout();
      if (keepAlive) clearInterval(keepAlive);
      llamaState.currentHandler = null;
      llamaWorkerSvc.releaseLlamaWorker();
      activeJobs.delete(outputId);
      activeJobResponses.delete(outputId);
      processJobQueue();
    });

    // P2-8：使用背压感知写入
    await writeWithDrain(worker.stdin, JSON.stringify({
      id: outputId,
      text,
      model: cfgObj && cfgObj.model ? cfgObj.model : 'shehui-llama',
      mode: 'super',
      config: cfgObj || {},
      timeout_ms: superTimeoutMs,
    }) + '\n', 'utf-8');

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

// 同步分析（旧接口，保留兼容）
function runPythonAnalysisSync(text, outputId, mode = 'light', bridgeConfig = '') {
  return new Promise((resolve, reject) => {
    const skillDir = CONFIG.skillDir;
    const pyScript = path.resolve(__dirname, '..', 'py_bridge.py');
    const outDir = path.join(OUTPUT_DIR, outputId);
    const cfgObj = bridgeConfig ? (() => { try { return JSON.parse(bridgeConfig); } catch (_) { return null; } })() : null;

    if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

    recordJob(outputId, mode, 'running', null, { text, config: bridgeConfig || CONFIG.bridgeConfig || '' });

    // 深度复审修复：sync 路径也需注册 activeJobs，否则绕过并发限制且无法取消
    activeJobs.set(outputId, py);

    const args = [pyScript, skillDir, outDir, mode];
    const cfg = bridgeConfig || CONFIG.bridgeConfig || '';
    if (cfg) args.push(cfg);

    const py = spawn(CONFIG.pythonCmd, args, {
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });

    let stdout = '';
    let stderr = '';
    let finished = false;

    py.stdin.write(text, 'utf-8');
    py.stdin.end();

    py.stdout.on('data', (data) => { stdout += data.toString('utf-8'); });
    py.stderr.on('data', (data) => { stderr += data.toString('utf-8'); });

    py.on('close', (code) => {
      if (finished) return;
      finished = true;
      activeJobs.delete(outputId);
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
        setResultCache(cacheKey(text, mode, cfgObj), outputId);
        // 深度复审修复：内层 result.success=false 时标 error 而非 completed
        const finalStatus = (result && result.success === false) ? 'error' : 'completed';
        recordJob(outputId, mode, finalStatus);
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
      if (finished) return;
      finished = true;
      activeJobs.delete(outputId);
      recordJob(outputId, mode, 'error', err.message);
      reject(err);
    });
  });
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

module.exports = {
  sendSSE,
  sendSSERetryHeader,
  runPythonAnalysisStream,
  runSuperAnalysisStream,
  runPythonAnalysisSync,
  buildSuperReport,
  processJobQueue,
};
