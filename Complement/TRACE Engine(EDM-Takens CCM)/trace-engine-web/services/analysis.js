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
  INPUTS_DIR,
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
  // P0-1 修复 (ROUND27 12维度核对): 客户端断连后 res 可能已 destroy,
  // 裸 res.write 会触发 'error' 事件导致 unhandledException → gracefulShutdown.
  // 与 heartbeat (L178) 和 finish() (L355) 的 try/catch 对齐.
  try {
    res.write(`id: ${id}\n`);
    res.write(`event: ${event}\n`);
    res.write(`data: ${JSON.stringify(data)}\n\n`);
  } catch (_) {
    // 流已关闭, 静默忽略 — res.on('close') 会处理任务取消
  }
}

// 在 SSE 响应头之后发送 retry: 30000（30 秒重连间隔，debt-11；跨项目契约对齐 trace-to-edm/server.js）
function sendSSERetryHeader(res) {
  try { res.write('retry: 30000\n\n'); } catch (_) {}
}

/**
 * 流式调用 Python 桥接脚本分析文本（LIGHT / DEEP）
 */
function runPythonAnalysisStream(text, outputId, mode, bridgeConfig, res, schemaCtx = {}) {
  const skillDir = CONFIG.skillDir;
  const pyScript = path.resolve(__dirname, '..', 'py_bridge.py');
  const outDir = path.join(OUTPUT_DIR, outputId);
  const cfgObj = bridgeConfig ? (() => { try { return JSON.parse(bridgeConfig); } catch (_) { return null; } })() : null;

  // P0-2/P0-3 修复 (2026-07-30): resClosed 在 writeFileSync 之前声明，
  // 避免 TDZ 违规导致错误处理本身崩溃；mkdirSync 异常需捕获并优雅降级。
  let resClosed = false;
  try {
    if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
  } catch (mkdirErr) {
    logToFile('error', `创建输出目录失败 job=${outputId}: ${mkdirErr.message}`);
    sendSSE(res, 'error', { message: `创建输出目录失败: ${mkdirErr.message}` });
    recordJob(outputId, mode, 'error', mkdirErr.message);
    activeJobs.delete(outputId);  // P0-5: 清理占位符, 释放并发名额
    processJobQueue();
    return;
  }

  recordJob(outputId, mode, 'running', null, { text, config: bridgeConfig || CONFIG.bridgeConfig || '' });
  activeJobResponses.set(outputId, { res, mode });
  logToFile('info', `启动分析 job=${outputId} mode=${mode} text_len=${text.length}`);

  // P0 硬修复 (2026-07-29): Windows 下 Python 子进程 stdin 默认按系统代码页
  // (GBK) 解码，导致中文文本传入后乱码、有效词数变为 0。改为将文本写入
  // UTF-8 临时文件，通过命令行第 5 参数传给 py_bridge，从根本上规避 stdin
  // 编码问题，同时复用已有的 INPUTS_DIR TTL 清理机制。
  const inputFilePath = path.join(INPUTS_DIR, `${outputId}.txt`);
  try {
    fs.writeFileSync(inputFilePath, text, 'utf-8');
  } catch (err) {
    logToFile('error', `写入输入文件失败 job=${outputId}: ${err.message}`);
    if (!resClosed) sendSSE(res, 'error', { message: `写入输入文件失败: ${err.message}` });
    recordJob(outputId, mode, 'error', err.message);
    activeJobs.delete(outputId);  // P0-5: 清理占位符, 释放并发名额
    processJobQueue();
    return;
  }

  const args = [pyScript, skillDir, outDir, mode];
  const cfg = bridgeConfig || CONFIG.bridgeConfig || '';
  args.push(cfg || '{}');
  args.push(inputFilePath);

  const py = spawn(CONFIG.pythonCmd, args, {
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      TRACE_BRIDGE_CONFIG: cfg,
    },
  });

  activeJobs.set(outputId, py);

  // P1-g 修缮：立即发送握手事件，避免前端 firstEventTimeout(3s→15s) 误判为连接失败
  // Python 冷启动 + 模块 import 常需 3-5s，若此期间无任何 SSE 事件，前端会主动 abort
  sendSSE(res, 'log', { level: 'info', message: `[bridge] 已建立连接，启动 ${mode.toUpperCase()} 分析管道（Python 冷启动中...）` });

  let stdoutBuffer = '';
  let timeoutId = null;
  let finished = false;
  // resClosed 已在函数开头声明（P0-2 修复），此处不再重复声明

  const cleanupTimeout = () => {
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    if (heartbeat) {
      clearInterval(heartbeat);
    }
  };

  const jobTimeout = (mode === 'deep')
    ? CONFIG.deepJobTimeoutMs
    : CONFIG.jobTimeoutMs;

  timeoutId = setTimeout(() => {
    const limitMin = Math.round(jobTimeout / 60000);
    logToFile('warn', `分析超时 job=${outputId} mode=${mode}，强制终止`);
    sendSSE(res, 'error', { message: `分析超时（>${jobTimeout}ms / ${limitMin}min），已强制终止。${mode === 'deep' ? '可缩短文本或降低阈值加速。' : '请尝试 LIGHT 模式或缩短文本。'}` });
    killProcessWithFallback(py);
    recordJob(outputId, mode, 'timeout');
  }, jobTimeout);

  // P2-9 + 元审计 P1 修缮：SSE 客户端断开的宽限期机制
  // 之前 res.on('close') 立即取消任务，客户端重连后只能取 /api/result/:id
  // 现增加动态宽限期：客户端断开后不立即 kill 进程，
  // 若宽限期内客户端重连（通过 /api/result/:id 或重新触发 SSE）则恢复流式
  // 宽限期后仍未重连则真正清理资源（避免僵尸进程）
  // P1 修缮：根据模式动态调整宽限期，DEEP/SUPER 需要更长时间
  const gracePeriod = mode === 'super' ? 600000 : mode === 'deep' ? 120000 : 30000;
  // P0 修缮：标记 res 是否已关闭，避免向已关闭的 SSE 流写入 result/error 事件
  // 这是"任务完成但前端看不到结论"的根因——SSE 断开后 sendSSE 仍尝试写入
  res.on('close', () => {
    if (finished) return;
    resClosed = true;
    logToFile('info', `SSE 客户端断开，启动 ${gracePeriod/1000}s 宽限期 job=${outputId} mode=${mode}`);
    activeJobResponses.delete(outputId);  // 移除 res 引用，避免写已关闭的流

    // 宽限期：超时后若未重连则真正清理
    const graceTimer = setTimeout(() => {
      if (finished) return;
      logToFile('info', `宽限期超时，清理 ${mode} 任务 job=${outputId}`);
      finished = true;
      cleanupTimeout();
      killProcessWithFallback(py);
      // 仅当 activeJobs 仍指向当前 py 时才清理共享状态
      // （前端 sse.js 3 次指数退避重连可能已用新 py 覆盖 activeJobs[outputId]，
      //   此时若误删会导致新进程无法被取消，且 recordJob 会覆盖新任务状态）
      if (activeJobs.get(outputId) === py) {
        recordJob(outputId, mode, 'cancelled', `客户端断开连接且 ${gracePeriod/1000}s 内未重连`);
        activeJobs.delete(outputId);
        processJobQueue();
      }
    }, gracePeriod);

    // 若进程在宽限期内完成，清理定时器
    // P1-10 修复 (ROUND27 12维度核对): res.on('close') 可被多次触发 (前端 sse.js
    // 3 次指数退避重连), 每次 close 都给 py 挂 exit 监听器会累积, 超
    // defaultMaxListeners=10 触发警告. 用 once 替代 on, 确保只挂一次.
    py.once('exit', () => {
      clearTimeout(graceTimer);
    });
  });

  // SSE 保活：每 30 秒发送一条注释
  const heartbeat = setInterval(() => {
    try { res.write(':heartbeat\n\n'); } catch (_) {}
  }, 30000);

  py.stdout.on('data', (chunk) => {
    stdoutBuffer += chunk.toString('utf-8');
    // P2-7 修复 (ROUND27 12维度核对): stdout 缓冲区无上限, 若 Python 输出
    // 单行极长 (如 dump 大 JSON 无换行), stdoutBuffer 无限增长导致 OOM.
    // 限制单行最大 10MB, 超限截断并记录警告.
    const MAX_STDOUT_LINE = 10 * 1024 * 1024;
    if (stdoutBuffer.length > MAX_STDOUT_LINE) {
      logToFile('error', `stdout 缓冲区超限 (${stdoutBuffer.length} bytes), 截断 job=${outputId}`);
      stdoutBuffer = stdoutBuffer.slice(-MAX_STDOUT_LINE);
    }
    const lines = stdoutBuffer.split('\n');
    stdoutBuffer = lines.pop();

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const obj = JSON.parse(line);
        if (obj.type === 'stage') {
          if (!resClosed) sendSSE(res, 'stage', obj);
        } else if (obj.type === 'log') {
          if (!resClosed) sendSSE(res, 'log', obj);
        } else if (obj.type === 'result') {
          cleanupTimeout();
          const resultData = {
            id: outputId,
            result: obj.payload,
            reportPath: fs.existsSync(path.join(outDir, 'report.md')) ? `/api/report/${outputId}` : null,
            resultPath: `/api/result/${outputId}`,
          };
          // P0 修缮：SSE 断开后仍保存结果到缓存和 job 历史，
          // 前端可通过 /api/result/:id 或任务历史获取
          setResultCache(cacheKey(text, mode, cfgObj), outputId);
          recordJob(outputId, mode, 'completed');
          if (resClosed) {
            logToFile('info', `分析完成(SSE已断开,结果已缓存) job=${outputId}`);
          } else {
            sendSSE(res, 'result', resultData);
            logToFile('info', `分析完成 job=${outputId}`);
          }
        } else if (obj.type === 'error') {
          cleanupTimeout();
          recordJob(outputId, mode, 'error', obj.message);
          if (resClosed) {
            logToFile('error', `分析错误(SSE已断开) job=${outputId}: ${obj.message}`);
          } else {
            sendSSE(res, 'error', { message: obj.message });
            logToFile('error', `分析错误 job=${outputId}: ${obj.message}`);
          }
        }
      } catch (err) {
        if (!resClosed) sendSSE(res, 'log', { level: 'raw', message: line });
      }
    }
  });

  py.stderr.on('data', (chunk) => {
    if (resClosed) return;  // P0 修复: 防止向已关闭的 SSE 流写入导致进程崩溃
    const lines = chunk.toString('utf-8').split('\n').filter(Boolean);
    for (const line of lines) {
      sendSSE(res, 'log', { level: 'stderr', message: line });
    }
  });

  py.on('close', (code) => {
    finished = true;
    cleanupTimeout();
    // 仅当 activeJobs 仍指向当前 py 时才清理共享状态
    // （前端重连可能已用新 py 覆盖 activeJobs[outputId]，此时旧进程的
    //   close 事件不应误删新进程或覆盖新任务的 job 记录）
    const isCurrent = activeJobs.get(outputId) === py;
    if (isCurrent) {
      activeJobs.delete(outputId);
      activeJobResponses.delete(outputId);
    }
    if (code !== 0 && isCurrent) {
      const msg = `Python 进程异常退出 (code=${code})`;
      // P1-a 修缮：resClosed 守卫，避免向已关闭的 SSE 流写入
      if (!resClosed) sendSSE(res, 'error', { message: msg });
      recordJob(outputId, mode, 'error', msg);
      logToFile('error', `Python 异常退出 job=${outputId} code=${code}`);
    }
    if (isCurrent) {
      if (!resClosed) {
        sendSSE(res, 'done', { code, job_id: outputId });
        res.end();
      }
    }
    processJobQueue();
  });

  py.on('error', (err) => {
    finished = true;
    cleanupTimeout();
    activeJobs.delete(outputId);
    activeJobResponses.delete(outputId);
    if (!resClosed) sendSSE(res, 'error', { message: err.message });
    recordJob(outputId, mode, 'error', err.message);
    logToFile('error', `Python 启动错误 job=${outputId}: ${err.message}`);
    if (!resClosed) {
      sendSSE(res, 'done', { code: -1, job_id: outputId });
      res.end();
    }
    processJobQueue();
  });
}

/**
 * SUPER 模式：调用常驻 LLaMA Worker 执行真正的 TRACE 因果发现
 */
async function runSuperAnalysisStream(text, outputId, bridgeConfig, res) {
  const outDir = path.join(OUTPUT_DIR, outputId);
  const cfgObj = bridgeConfig ? (() => { try { return JSON.parse(bridgeConfig); } catch (_) { return null; } })() : null;

  // P0-3 修复 (2026-07-30): mkdirSync 异常需捕获，避免 async 函数中变成 unhandled rejection
  try {
    if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
  } catch (mkdirErr) {
    logToFile('error', `SUPER 创建输出目录失败 job=${outputId}: ${mkdirErr.message}`);
    sendSSE(res, 'error', { message: `创建输出目录失败: ${mkdirErr.message}` });
    sendSSE(res, 'done', { code: -1, job_id: outputId });
    try { res.end(); } catch (_) {}
    recordJob(outputId, 'super', 'error', mkdirErr.message);
    processJobQueue();
    return;
  }
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
  // P1-a 修缮：SUPER 模式同样需要 resClosed 守卫，避免向已关闭的 SSE 流写入
  let resClosed = false;

  // P0-2 修复 (ROUND27 12维度核对): res.on('close') 必须在 ensureLlamaWorker 之前注册,
  // 否则客户端在等待 Worker (最长 120s+ 空闲等待) 期间断连时, resClosed 保持 false,
  // Worker 就绪后向已关闭的 res 写入 → 触发 unhandledException. 与 runPythonAnalysisStream
  // (L147 spawn 后立即注册) 对齐.
  res.on('close', () => {
    if (finished) return;
    resClosed = true;
    activeJobResponses.delete(outputId);

    if (!placeholder.isRunning) {
      // Worker 尚未就绪: 标记取消, ensureLlamaWorker/waitForLlamaWorkerIdle 返回后
      // 会检查 placeholder.cancelled 并走取消路径 (L372-383)
      placeholder.cancelled = true;
      logToFile('info', `SSE 客户端在 Worker 等待期间断开 job=${outputId} mode=super`);
      return;
    }

    // Worker 已就绪: 启动 600s 宽限期
    const worker = activeJobs.get(outputId);
    logToFile('info', `SSE 客户端断开，启动 600s 宽限期 job=${outputId} mode=super`);
    const graceTimer = setTimeout(() => {
      if (finished) return;
      logToFile('info', `宽限期超时，清理 super 任务 job=${outputId}`);
      finished = true;
      cleanupTimeout();
      if (keepAlive) clearInterval(keepAlive);
      try {
        if (worker && worker.stdin && typeof worker.stdin.write === 'function') {
          worker.stdin.write(JSON.stringify({ type: 'cancel', id: outputId }) + '\n', 'utf-8');
        }
      } catch (_) {}
      recordJob(outputId, 'super', 'cancelled', '客户端断开连接且 600s 内未重连');
      llamaState.currentHandler = null;
      llamaWorkerSvc.releaseLlamaWorker();
      activeJobs.delete(outputId);
      processJobQueue();
    }, 600000);

    if (worker && typeof worker.on === 'function') {
      worker.on('exit', () => { clearTimeout(graceTimer); });
    }
  });

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
    // P1-a：SSE 已断开时仅记录日志，不再写入 res（结果已通过 resultCache + jobHistory 保留）
    if (!resClosed) {
      try { sendSSE(res, 'done', { code: doneCode, job_id: outputId }); res.end(); } catch (_) {}
    } else {
      logToFile('info', `SUPER finish(SSE已断开) job=${outputId} code=${doneCode}`);
    }
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
      if (!resClosed) {
        try { sendSSE(res, 'error', { message: '用户主动停止计算' }); sendSSE(res, 'done', { code: 125, job_id: outputId }); res.end(); } catch (_) {}
      }
      processJobQueue();
      return;
    }
    llamaState.busy = true;

    timeoutId = setTimeout(() => {
      const elapsed = Date.now() - taskStartTime;
      const stageDur = Date.now() - lastStageTime;
      const msg = `SUPER 分析已运行超过 24 小时安全兜底。任务在 [${lastStageName}] 阶段停留约 ${stageDur}ms，总耗时 ${elapsed}ms。系统已强制终止；如仍需分析，请缩短文本、减小 window_size / max_segments、切换到 DEEP 模式，或检查模型/算力状态。`;
      logToFile('warn', `SUPER 安全兜底触发 job=${outputId} model=${cfgObj?.model || 'shehui-llama'} stage=${lastStageName} elapsed=${elapsed}`);
      if (!resClosed) sendSSE(res, 'error', { message: msg });
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
        if (!resClosed) sendSSE(res, 'error', { message: msg });
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
        if (!resClosed) sendSSE(res, 'stage', obj);
      } else if (obj.type === 'log') {
        if (!resClosed) sendSSE(res, 'log', obj);
      } else if (obj.type === 'stats') {
        if (!resClosed) sendSSE(res, 'stats', obj.stats);
      } else if (obj.type === 'error') {
        cleanupTimeout();
        if (!resClosed) sendSSE(res, 'error', { message: obj.message });
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
        // P1-a：SSE 已断开时跳过 sendSSE，但结果已持久化 + 缓存 + jobHistory 保留
        if (!resClosed) {
          sendSSE(res, 'result', resultData);
          logToFile('info', `SUPER 分析完成 job=${outputId}`);
        } else {
          logToFile('info', `SUPER 分析完成(SSE已断开,结果已缓存) job=${outputId}`);
        }
        setResultCache(cacheKey(text, 'super', cfgObj), outputId);
        recordJob(outputId, 'super', 'completed');
        finish(0);
      }
    };

    // P0-2 修复: res.on('close') 已在 ensureLlamaWorker 之前注册 (见上方 L345),
    // 旧的金石 res.on('close') 注册已移除, 避免 Worker 等待期间断连信号丢失.

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
    if (!resClosed) sendSSE(res, 'error', { message: err.message });
    recordJob(outputId, 'super', 'error', err.message);
    logToFile('error', `SUPER 启动失败 job=${outputId}: ${err.message}`);
    finish(-1);
  }
}

// INT-04: buildSuperReport 复用 bridge.report() 的更丰富模板。
// 原 buildSuperReport 仅输出 6 行摘要，丢失了 SUPER 模式独有的六战士、稳定性、
// 反事实扫描、数据诊断等高价值信息。扩展后与 py_bridge.py / counterfactual_bridge.py
// 的 report() 模板对齐，让用户在 /api/report/:id 拿到的 Markdown 与 LIGHT/DEEP 同等丰富。
function buildSuperReport(payload) {
  const lines = [];
  const fmt = (v, d = 4) => (typeof v === 'number' && Number.isFinite(v)) ? v.toFixed(d) : 'N/A';
  const concepts = Array.isArray(payload.concepts) ? payload.concepts : [];
  const topEdges = Array.isArray(payload.top_edges) ? payload.top_edges : [];
  const refutations = Array.isArray(payload.refutations) ? payload.refutations : [];
  const scan = Array.isArray(payload.counterfactual_scan) ? payload.counterfactual_scan : [];
  const sixWarriors = (payload.six_warriors && typeof payload.six_warriors === 'object') ? payload.six_warriors : {};
  const auditor = payload.auditor || null;
  const stability = payload.stability_analysis || {};
  const diag = payload.data_diagnostics || {};
  const execProfile = payload.execution_profile || {};

  lines.push('# TRACE SUPER 模式分析报告');
  lines.push('');
  lines.push(`**分析模型**: ${payload.model || 'shehui-llama'}`);
  lines.push(`**分析模式**: ${payload.analysis_mode || 'super'}`);
  if (payload.text_hash) lines.push(`**文本哈希**: ${payload.text_hash}`);
  lines.push(`**后端**: ${payload.backend || 'DoWhy'}${payload.simulation ? ' (模拟)' : ''}`);
  lines.push('');

  // 1. 因果图摘要
  lines.push('## 1. 因果图摘要');
  lines.push(`- 概念节点: ${concepts.length}`);
  lines.push(`- 显著因果边: ${payload.n_significant_edges || 0}`);
  lines.push(`- 阈值 (threshold): ${payload.threshold != null ? payload.threshold : 'N/A'}`);
  lines.push(`- 窗口大小 (window_size): ${payload.window_size != null ? payload.window_size : 'N/A'}`);
  lines.push(`- 最大概念数 (max_concepts): ${payload.max_concepts != null ? payload.max_concepts : 'N/A'}`);
  if (diag.signal_type) lines.push(`- 信号类型: ${diag.signal_type}${diag.signal_type === 'delta_nll' ? ' (真实 ΔNLL)' : ' (共现计数)'}`);
  if (diag.max_delta_nll != null) lines.push(`- 最大 ΔNLL: ${diag.max_delta_nll}`);
  if (diag.adj_density != null) lines.push(`- 图密度 (adj_density): ${diag.adj_density}`);
  if (diag.concept_level_edge_count != null) lines.push(`- 概念级边数: ${diag.concept_level_edge_count}`);
  lines.push('');

  // 2. Top 因果边
  if (topEdges.length > 0) {
    lines.push('## 2. Top 因果边 (TRACE ΔNLL)');
    lines.push('| # | 原因 | 结果 | ΔNLL | 方向 |');
    lines.push('|---|------|------|------|------|');
    topEdges.slice(0, 10).forEach((e, i) => {
      const s = typeof e.strength === 'number' ? e.strength.toFixed(3) : 'N/A';
      lines.push(`| ${i + 1} | ${e.source || '?'} | ${e.target || '?'} | ${s} | ${e.direction || '→'} |`);
    });
    lines.push('');
  }

  // 3. 因果效应识别
  lines.push('## 3. 因果效应识别');
  lines.push(`- 处理变量 (treatment): ${payload.treatment || 'N/A'}`);
  lines.push(`- 结果变量 (outcome): ${payload.outcome || 'N/A'}`);
  lines.push(`- 可识别: ${payload.identifiable ? '✓ 是' : '✗ 否'}`);
  lines.push('');

  // 4. 因果效应估计
  lines.push('## 4. 因果效应估计');
  lines.push(`- 效应量 (ATE): ${payload.ate != null ? fmt(payload.ate) : 'N/A'}`);
  if (Array.isArray(payload.confidence_interval) && payload.confidence_interval.length === 2) {
    const ciLo = payload.confidence_interval[0];
    const ciHi = payload.confidence_interval[1];
    lines.push(`- 95% CI: [${ciLo != null ? fmt(ciLo) : 'N/A'}, ${ciHi != null ? fmt(ciHi) : 'N/A'}]`);
  }
  lines.push('');

  // 5. 反驳测试
  if (refutations.length > 0) {
    const nRefuted = refutations.filter(r => r.refuted).length;
    lines.push('## 5. 反驳测试');
    lines.push(`- 结论: ${nRefuted}/${refutations.length} 被反驳 ${nRefuted >= 2 ? '⚠️ 效应不稳定' : '✓ 效应稳健'}`);
    lines.push('');
    lines.push('| 反驳方法 | 新效应 | 是否反驳 | 指标 |');
    lines.push('|---------|--------|---------|------|');
    refutations.forEach(r => {
      const ne = r.new_effect != null ? fmt(r.new_effect) : 'N/A';
      const verdict = r.refuted ? '⚠️ 反驳' : '✓ 稳健';
      const metric = r.display_metric != null ? `${r.display_label || '指标'}=${(r.display_metric * 100).toFixed(1)}%` : '—';
      lines.push(`| ${r.method || '?'} | ${ne} | ${verdict} | ${metric} |`);
    });
    lines.push('');
  }

  // 6. 反事实扫描
  if (scan.length > 0) {
    lines.push('## 6. 反事实扫描（Top 边）');
    lines.push('| 原因 → 结果 | TRACE ΔNLL | ITE | 观测 | 反事实 |');
    lines.push('|------------|-----------|-----|------|--------|');
    scan.slice(0, 10).forEach(r => {
      lines.push(
        `| ${r.source || '?'} → ${r.target || '?'} `
        + `| ${r.trace_dnl != null ? fmt(r.trace_dnl, 2) : 'N/A'} `
        + `| ${r.ite != null ? fmt(r.ite) : 'N/A'} `
        + `| ${r.observed != null ? fmt(r.observed) : 'N/A'} `
        + `| ${r.counterfactual != null ? fmt(r.counterfactual) : 'N/A'} |`
      );
    });
    lines.push('');
  }

  // 7. 六战士诊断
  const warriorKeys = Object.keys(sixWarriors);
  if (warriorKeys.length > 0) {
    const deployed = warriorKeys.filter(k => sixWarriors[k] && sixWarriors[k].status === 'deployed').length;
    lines.push('## 7. 六战士诊断');
    lines.push(`- 部署: ${deployed}/${warriorKeys.length} deployed`);
    lines.push('');
    lines.push('| 战士 | 状态 | 裁决 | 关键发现 |');
    lines.push('|------|------|------|---------|');
    warriorKeys.forEach(k => {
      const w = sixWarriors[k];
      const name = w.name || k;
      const status = w.status || '?';
      const verdict = w.verdict || '—';
      const finding = (Array.isArray(w.findings) && w.findings.length > 0) ? w.findings[0] : '—';
      lines.push(`| ${name} | ${status} | ${verdict} | ${String(finding).slice(0, 60)} |`);
    });
    lines.push('');
  }

  // 8. 审计结果
  lines.push('## 8. 审计结果');
  if (auditor) {
    lines.push(`- 裁决: ${auditor.verdict || 'N/A'}`);
    lines.push(`- PASS/WARN/FAIL: ${auditor.n_pass || 0}/${auditor.n_warn || 0}/${auditor.n_fail || 0}`);
  } else {
    lines.push('- 审计不可用');
  }
  lines.push('');

  // 9. 稳定性分析
  if (stability && Object.keys(stability).length > 0) {
    lines.push('## 9. 稳定性分析');
    if (stability.edge_stability_mean != null) lines.push(`- 边稳定性均值: ${fmt(stability.edge_stability_mean, 3)}`);
    if (stability.edge_stability_std != null) lines.push(`- 边稳定性标准差: ${fmt(stability.edge_stability_std, 3)}`);
    if (stability.ate_bootstrap_ci && Array.isArray(stability.ate_bootstrap_ci)) {
      lines.push(`- ATE bootstrap CI: [${fmt(stability.ate_bootstrap_ci[0])}, ${fmt(stability.ate_bootstrap_ci[1])}] (${stability.ate_bootstrap_method || 'percentile'})`);
    }
    if (stability.permutation_p_value != null) lines.push(`- 置换检验 p 值: ${fmt(stability.permutation_p_value, 4)} (n=${stability.permutation_n || '?'})`);
    if (stability.cv_ate_mean != null) lines.push(`- K-fold CV ATE 均值: ${fmt(stability.cv_ate_mean)} (std=${stability.cv_ate_std != null ? fmt(stability.cv_ate_std) : 'N/A'})`);
    lines.push('');
  }

  // 10. 数据诊断
  if (diag && Object.keys(diag).length > 0) {
    lines.push('## 10. 数据诊断');
    if (diag.raw_tokens != null) lines.push(`- 原始 token 数: ${diag.raw_tokens}`);
    if (diag.valid_concept_tokens != null) lines.push(`- 有效概念 token 数: ${diag.valid_concept_tokens}`);
    if (diag.concept_coverage != null) lines.push(`- 概念覆盖率: ${(diag.concept_coverage * 100).toFixed(1)}%`);
    if (diag.unk_rate != null) lines.push(`- 未知词比例 (unk_rate): ${diag.unk_rate}`);
    if (diag.condition_number != null) lines.push(`- 条件数: ${diag.condition_number}`);
    if (diag.max_correlation != null) lines.push(`- 最大相关系数: ${diag.max_correlation}`);
    lines.push('');
  }

  // 11. 执行时间
  if (execProfile && Object.keys(execProfile).length > 0) {
    lines.push('## 11. 执行时间');
    const totalMs = execProfile.total_ms != null ? execProfile.total_ms : (execProfile.total || 0);
    if (totalMs > 0) lines.push(`- 总耗时: ${(totalMs / 1000).toFixed(2)}s (${totalMs}ms)`);
    if (Array.isArray(execProfile.stages) && execProfile.stages.length > 0) {
      lines.push('');
      lines.push('| 阶段 | 耗时 (ms) |');
      lines.push('|------|----------|');
      execProfile.stages.forEach(s => {
        lines.push(`| ${s.stage || s.name || '?'} | ${s.ms || 0} |`);
      });
    }
    lines.push('');
  }

  lines.push('---');
  lines.push(`_报告由 trace-engine-web SUPER 模式自动生成 · 模型: ${payload.model || 'shehui-llama'} · 模板对齐 counterfactual_bridge.report()_`);

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

    // P0 硬修复 (2026-07-29): Windows Python 子进程 stdin 编码问题，
    // 与 runPythonAnalysisStream 保持一致：文本写入 UTF-8 文件后通过参数传入。
    const inputFilePath = path.join(INPUTS_DIR, `${outputId}.txt`);
    fs.writeFileSync(inputFilePath, text, 'utf-8');

    const args = [pyScript, skillDir, outDir, mode];
    const cfg = bridgeConfig || CONFIG.bridgeConfig || '';
    args.push(cfg || '{}');
    args.push(inputFilePath);

    const py = spawn(CONFIG.pythonCmd, args, {
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });

    // 深度复审修复：sync 路径也需注册 activeJobs，否则绕过并发限制且无法取消
    activeJobs.set(outputId, py);

    let stdout = '';
    let stderr = '';
    let finished = false;

    // P1-1 修复 (Round 27 审计): sync 路径缺少超时，Python 子进程挂起会永久阻塞 Promise。
    // 与 runPythonAnalysisStream 对齐：按 mode 选取超时，超时后 killProcessWithFallback。
    const jobTimeout = mode === 'deep' ? CONFIG.deepJobTimeoutMs : CONFIG.jobTimeoutMs;
    const timeoutId = setTimeout(() => {
      if (finished) return;
      finished = true;
      try { killProcessWithFallback(py); } catch (_) {}
      activeJobs.delete(outputId);
      recordJob(outputId, mode, 'timeout');
      reject(new Error(`分析超时（>${jobTimeout}ms）`));
    }, jobTimeout);
    // 兜底：超时定时器不应阻止进程退出
    if (typeof timeoutId.unref === 'function') timeoutId.unref();

    py.stdout.on('data', (data) => { stdout += data.toString('utf-8'); });
    py.stderr.on('data', (data) => { stderr += data.toString('utf-8'); });

    py.on('close', (code) => {
      if (finished) return;
      finished = true;
      clearTimeout(timeoutId);
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
      clearTimeout(timeoutId);
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
