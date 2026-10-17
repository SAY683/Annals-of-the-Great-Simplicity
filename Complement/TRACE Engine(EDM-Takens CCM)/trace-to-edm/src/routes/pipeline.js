module.exports = function mount(app, ctx) {
const { fs, path, spawn, crypto, ROOT, PROJECTS_DIR, TRAJECTORY_CSV, PYTHON_CMD, BRIDGE_SCRIPT, PACKAGE_VERSION, serverLog, reqLog, getActiveTrajectoryCSV, pyCall, pyScript, errorResponse, activeJobs, jobHistory, createJobId, emitSSE, streamBridgeProcess, readTrajectoryCSV, buildTrajectoryReport, buildTrajectoryReportHTML, getCached, setCached, invalidateCache, pyDS, getDatasetExports, markDatasetProcessed, pipelineState } = ctx;

app.post('/api/run', (req, res) => {
  const { mode, text, source, ts } = req.body;
  const jobId = createJobId();
  // P1 修复: 白名单校验 mode 参数，防止注入 SUPER 等未授权模式
  const traceMode = ['light', 'deep'].includes(mode) ? mode : 'light';

  // P1 修复：/api/run 原先忽略 text 参数，总是跑示例 CSV；现在支持单条文本。
  const args = [BRIDGE_SCRIPT];
  if (text && typeof text === 'string') {
    args.push('--text', text);
    if (source) args.push('--source', String(source));
    if (ts) args.push('--ts', String(ts));
  } else {
    const inputPath = req.resolvedInputPath || path.join(ROOT, 'data', 'inputs', 'example_input.csv');
    args.push('--input', inputPath);
  }
  args.push('--mode', traceMode, '--verbose');

  const proc = spawn(PYTHON_CMD, args, {
    cwd: ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });

  const job = {
    id: jobId,
    mode: 'text-pipeline',
    traceMode,
    startTime: new Date().toISOString(),
    logs: [],
    status: 'running',
  };

  activeJobs.set(jobId, { ...job, process: proc });

  // 接受 SSE 流
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
  });

  // P0 修复: 客户端断连时清理子进程，防止孤儿进程泄漏
  let clientDisconnected = false;
  req.on('close', () => {
    if (clientDisconnected) return;
    clientDisconnected = true;
    try { proc.kill('SIGTERM'); } catch (_) {}
    activeJobs.delete(jobId);
  });

  // P1 修复 (ROUND32 三视角评审-算法工程师): 启动阶段首字节超时
  // 病灶: /api/run 仅依赖客户端断连清理, 若 Python 启动卡死 (torch/transformers
  // 导入失败但未崩溃), SSE 连接会无限挂起, 浏览器侧表现为"loading 永不结束".
  // 修复: 60s 首字节 timeout — Python 应在 60s 内输出任意 stdout/stderr,
  // 否则判定为启动卡死, kill 进程并返回 SPAWN_TIMEOUT 错误.
  let firstByteReceived = false;
  const SPAWN_TIMEOUT_MS = 60000;
  const spawnTimer = setTimeout(() => {
    if (firstByteReceived || clientDisconnected) return;
    try { proc.kill('SIGKILL'); } catch (_) {}
    job.status = 'timeout';
    activeJobs.delete(jobId);
    emitSSE(res, 'error', {
      message: `spawn timeout (${SPAWN_TIMEOUT_MS / 1000}s 无首字节输出, Python 启动卡死)`,
      code: 'SPAWN_TIMEOUT',
    });
    res.end();
  }, SPAWN_TIMEOUT_MS);

  const _markFirstByte = () => {
    if (!firstByteReceived) {
      firstByteReceived = true;
      clearTimeout(spawnTimer);
    }
  };

  emitSSE(res, 'start', { job_id: jobId, mode: traceMode });

  proc.stdout.on('data', (data) => {
    _markFirstByte();
    if (clientDisconnected) return;
    const chunk = data.toString();
    job.logs.push({ time: new Date().toISOString(), text: chunk.trim() });
    const lines = chunk.trim().split('\n');
    for (const line of lines) {
      if (line.includes('✓ 完成') || line.includes('批量处理完成')) {
        // 提取进度
        emitSSE(res, 'progress', { message: line.trim() });
      } else if (line.includes('⚠') || line.includes('❌')) {
        emitSSE(res, 'warn', { message: line.trim() });
      } else if (line.trim()) {
        emitSSE(res, 'log', { message: line.trim() });
      }
    }
  });

  proc.stderr.on('data', (data) => {
    _markFirstByte();
    if (clientDisconnected) return;
    const stderrText = data.toString().trim();
    if (stderrText) {
      job.logs.push({ time: new Date().toISOString(), text: stderrText });
      emitSSE(res, 'log', { message: stderrText });
    }
  });

  proc.on('close', (code) => {
    clearTimeout(spawnTimer);
    if (clientDisconnected) return;
    job.status = code === 0 ? 'completed' : 'failed';
    job.endTime = new Date().toISOString();
    activeJobs.delete(jobId);
    jobHistory.unshift({ id: jobId, status: job.status, mode: job.mode, startTime: job.startTime });
    if (jobHistory.length > 50) jobHistory.pop();

    const traj = readTrajectoryCSV();
    emitSSE(res, 'done', {
      job_id: jobId,
      success: code === 0,
      trajectory_rows: traj.total,
      edm_ready: traj.total >= 15,
    });
    res.end();
  });

  proc.on('error', (err) => {
    clearTimeout(spawnTimer);
    if (clientDisconnected) return;
    job.status = 'error';
    activeJobs.delete(jobId);
    emitSSE(res, 'error', { message: err.message });
    res.end();
  });
});

// ── API: 提交回填任务 (Mode B) ────────────────────────────

app.post('/api/replay', (req, res) => {
  const { replay_all } = req.body;
  const jobId = createJobId();

  // validateInputPathMiddleware 已将 csv_path 解析为 req.resolvedInputPath
  const resolvedReplayPath = replay_all ? null : (req.resolvedInputPath || null);

  const args = [BRIDGE_SCRIPT, '--verbose'];
  if (replay_all) {
    args.push('--replay-all');
  } else if (resolvedReplayPath) {
    args.push('--replay', resolvedReplayPath);
  } else {
    args.push('--replay-all'); // 默认全部回填
  }

  const proc = spawn(PYTHON_CMD, args, {
    cwd: ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });

  const job = {
    id: jobId,
    mode: replay_all ? 'replay-all' : 'replay',
    startTime: new Date().toISOString(),
    logs: [],
    status: 'running',
  };

  activeJobs.set(jobId, { ...job, process: proc });

  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
  });

  // P0 修复 (ROUND32 三视角评审-算法工程师): /api/replay 缺失客户端断连清理
  // 与 /api/run 不一致, 长时间回填若客户端断开会留下孤儿进程.
  let clientDisconnected = false;
  req.on('close', () => {
    if (clientDisconnected) return;
    clientDisconnected = true;
    try { proc.kill('SIGTERM'); } catch (_) {}
    activeJobs.delete(jobId);
  });

  // P1 修复: 启动阶段首字节超时 (与 /api/run 对齐, 60s)
  let firstByteReceived = false;
  const SPAWN_TIMEOUT_MS = 60000;
  const spawnTimer = setTimeout(() => {
    if (firstByteReceived || clientDisconnected) return;
    try { proc.kill('SIGKILL'); } catch (_) {}
    job.status = 'timeout';
    activeJobs.delete(jobId);
    emitSSE(res, 'error', {
      message: `spawn timeout (${SPAWN_TIMEOUT_MS / 1000}s 无首字节输出, Python 启动卡死)`,
      code: 'SPAWN_TIMEOUT',
    });
    res.end();
  }, SPAWN_TIMEOUT_MS);

  const _markFirstByte = () => {
    if (!firstByteReceived) {
      firstByteReceived = true;
      clearTimeout(spawnTimer);
    }
  };

  emitSSE(res, 'start', { job_id: jobId, mode: job.mode });

  proc.stdout.on('data', (data) => {
    _markFirstByte();
    if (clientDisconnected) return;
    const text = data.toString();
    job.logs.push({ time: new Date().toISOString(), text: text.trim() });
    const lines = text.trim().split('\n');
    for (const line of lines) {
      if (line.includes('✓ 回填完成') || line.includes('回填完成:')) {
        emitSSE(res, 'progress', { message: line.trim() });
      } else if (line.includes('⚠') || line.includes('❌')) {
        emitSSE(res, 'warn', { message: line.trim() });
      } else if (line.trim()) {
        emitSSE(res, 'log', { message: line.trim() });
      }
    }
  });

  proc.stderr.on('data', (data) => {
    _markFirstByte();
    if (clientDisconnected) return;
    const text = data.toString().trim();
    if (text) {
      job.logs.push({ time: new Date().toISOString(), text });
      emitSSE(res, 'log', { message: text });
    }
  });

  proc.on('close', (code) => {
    clearTimeout(spawnTimer);
    if (clientDisconnected) return;
    job.status = code === 0 ? 'completed' : 'failed';
    job.endTime = new Date().toISOString();
    activeJobs.delete(jobId);
    jobHistory.unshift({ id: jobId, status: job.status, mode: job.mode, startTime: job.startTime });
    if (jobHistory.length > 50) jobHistory.pop();

    const traj = readTrajectoryCSV();
    emitSSE(res, 'done', {
      job_id: jobId,
      success: code === 0,
      trajectory_rows: traj.total,
      edm_ready: traj.total >= 15,
    });
    res.end();
  });

  proc.on('error', (err) => {
    clearTimeout(spawnTimer);
    if (clientDisconnected) return;
    job.status = 'error';
    activeJobs.delete(jobId);
    emitSSE(res, 'error', { message: err.message });
    res.end();
  });
});

app.get('/api/jobs', (_req, res) => {
  const active = Array.from(activeJobs.entries()).map(([id, j]) => ({
    id,
    mode: j.mode,
    status: j.status,
    startTime: j.startTime,
  }));
  res.json({ active, history: jobHistory.slice(0, 50) });
});

// ── API: 数据集管理 ───────────────────────────────────────

app.post('/api/pipeline/run', async (req, res) => {
  // 防重入: 管线已在运行中
  if (pipelineState.running) {
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
    emitSSE(res, 'warn', { message: '管线正在运行中, 请等待完成后再试' });
    emitSSE(res, 'done', { job_id: 'rejected', success: false });
    return res.end();
  }
  pipelineState.running = true;

  // P2 修缮：从前端读取 trace_mode（默认 light），允许 LIGHT/DEEP 切换
  // SUPER 模式不在此处支持（需经 trace-engine-web 的 LLaMA Worker）
  const body = req.body || {};
  const requestedMode = (typeof body.trace_mode === 'string' ? body.trace_mode : (req.query && req.query.trace_mode) || 'light').toLowerCase();
  const traceMode = ['light', 'deep'].includes(requestedMode) ? requestedMode : 'light';

  const jobId = createJobId();
  const job = { id: jobId, mode: `pipeline:${traceMode}`, startTime: new Date().toISOString(), status: 'running' };
  activeJobs.set(jobId, job);

  res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive' });
  emitSSE(res, 'start', { job_id: jobId, trace_mode: traceMode });

  try {
    // 1. 获取数据集导出
      emitSSE(res, 'log', { message: '准备数据集...' });
      const exports = await getDatasetExports();

      if (exports.error || exports.pending_replay === undefined || exports.pending_text === undefined) {
        const reason = exports.error || exports || '数据集导出异常';
        emitSSE(res, 'warn', { message: String(reason) || 'no pending entries' });
        emitSSE(res, 'done', { job_id: jobId, success: true, message: 'no pending entries' });
        return;
      }

      emitSSE(res, 'log', { message: `待处理: ${exports.pending_replay} 回填 + ${exports.pending_text} 文本 | TRACE 模式: ${traceMode.toUpperCase()}` });

      // P2 修缮：状态聚合改为 ok/partial/failed 三态
      let worstStatus = 'ok';  // ok > partial > failed

      // 2. 处理回填条目 (实时流式)
      if (exports.replay_csv) {
        emitSSE(res, 'progress', { message: `--- 回填管线 (${exports.pending_replay}条) ---` });
        const status = await streamBridgeProcess(res, ['--replay', exports.replay_csv], `Mode B: 回填 ${exports.pending_replay} 条`);
        if (status === 'failed') { emitSSE(res, 'warn', { message: '回填管线失败' }); worstStatus = 'failed'; }
        else if (status === 'partial' && worstStatus === 'ok') { worstStatus = 'partial'; }
        emitSSE(res, 'progress', { message: '回填管线完成 ✓' });
      }

      // 3. 处理文本条目 (实时流式)
      if (exports.text_csv) {
        emitSSE(res, 'progress', { message: `--- 文本管线 (${exports.pending_text}条, ${traceMode.toUpperCase()}模式) ---` });
        const status = await streamBridgeProcess(res, ['--input', exports.text_csv, '--mode', traceMode], `Mode A: 文本分析 ${exports.pending_text} 条 [${traceMode.toUpperCase()}]`);
        if (status === 'failed') { emitSSE(res, 'warn', { message: '文本管线失败' }); worstStatus = 'failed'; }
        else if (status === 'partial' && worstStatus === 'ok') { worstStatus = 'partial'; }
        emitSSE(res, 'progress', { message: '文本管线完成 ✓' });
      }

      // 4. 标记已处理 + 更新统计
      emitSSE(res, 'log', { message: '更新数据集状态...' });
      const stats = await markDatasetProcessed(exports.pending_ids);

      // P2：partial 也算"完成但有警告"，failed 才算失败
      job.status = worstStatus === 'failed' ? 'failed' : 'completed';
      job.endTime = new Date().toISOString();

      // P2：如果 partial，在 done 事件中显式提示
      if (worstStatus === 'partial') {
        emitSSE(res, 'warn', { message: '部分 TRACE 分析失败：轨迹 CSV 中 trace_status=FAILED 的行 L1 字段为 0，请检查 server.log 或前端 error 事件' });
      }

      emitSSE(res, 'done', {
        job_id: jobId,
        success: worstStatus !== 'failed',
        partial: worstStatus === 'partial',
        trajectory_rows: stats.rows || 0,
        edm_ready: stats.edm_ready || false,
      });

  } catch (e) {
    job.status = 'error';
    emitSSE(res, 'error', { message: e.message });
  } finally {
    pipelineState.running = false;
    activeJobs.delete(jobId);
    res.end();
  }
});

};
