module.exports = function mount(app, ctx) {
const { fs, path, spawn, crypto, ROOT, PROJECTS_DIR, TRAJECTORY_CSV, PYTHON_CMD, BRIDGE_SCRIPT, PACKAGE_VERSION, serverLog, reqLog, getActiveTrajectoryCSV, pyCall, pyScript, errorResponse, activeJobs, jobHistory, createJobId, emitSSE, streamBridgeProcess, readTrajectoryCSV, buildTrajectoryReport, buildTrajectoryReportHTML, getCached, setCached, invalidateCache, pyDS, getDatasetExports, markDatasetProcessed, pipelineState } = ctx;

app.post('/api/edm/trigger', (req, res) => {
  const { target, q, time_start, time_end, predict_window } = req.body;

  // P0-4 (Round 21 §P0-A): 入参校验 — 防止恶意输入触发 Python 端异常或长时间运行
  // target: 白名单校验, 必须为轨迹 CSV 中实际存在的数值列
  // ROUND51 E2E 修复: 原白名单含 n_significant_edges (result.json 键名, 非 CSV 列,
  // CSV 列是 edge_count) 且缺少 L2/L3 有方差列 (z_pca_*, z_存在 等), 导致 LIGHT 模式
  // 下 ate 全 0 时无任何可用的 EDM 目标. 现对齐 edm_trigger.list_recommended_targets().
  const ALLOWED_TARGETS = new Set([
    // Layer 1: 元 SCM (ate 在 LIGHT 模式可能全 0, 保留兼容)
    'ate', 'ate_ci_lower', 'ate_ci_upper', 'ci_width', 'refuted_count',
    'identifiable', 'edge_count', 'concept_count', 'adj_density',
    'max_delta_nll', 'ccm_coverage_pct',
    // Layer 2: 世俗语义 PCA (LIGHT 模式保证有方差)
    'z_pca_1', 'z_pca_2', 'z_pca_3', 'secular_entropy',
    // 兼容旧调用方 (非 CSV 列, 由 EDM 侧回退)
    'n_significant_edges',
  ]);
  if (target != null && (typeof target !== 'string' || !ALLOWED_TARGETS.has(target))) {
    return res.status(400).json({ success: false, error: `target 必须为白名单值: ${Array.from(ALLOWED_TARGETS).join('/')}`, code: 'INVALID_TARGET' });
  }
  const qNum = Number(q);
  if (q != null && (!Number.isInteger(qNum) || qNum < 2 || qNum > 20)) {
    return res.status(400).json({ success: false, error: 'q 必须为 [2, 20] 之间的整数', code: 'INVALID_Q' });
  }
  for (const [k, v] of [['time_start', time_start], ['time_end', time_end]]) {
    if (v != null && (typeof v !== 'number' || !Number.isFinite(v) || v < 0)) {
      return res.status(400).json({ success: false, error: `${k} 必须为非负数字`, code: 'INVALID_TIME' });
    }
  }
  const pwNum = Number(predict_window);
  if (predict_window != null && (!Number.isInteger(pwNum) || pwNum < 0 || pwNum > 1000)) {
    return res.status(400).json({ success: false, error: 'predict_window 必须为 [0, 1000] 之间的整数', code: 'INVALID_PW' });
  }

  const args = [
    BRIDGE_SCRIPT,
    '--edm-only',
    '--target', target || 'ate',
    '--q', String(qNum || 3),
    '--no-wait',  // 不等待EDM完成, 立即返回job_id
    '--verbose',
  ];
  if (time_start != null) args.push('--time-start', String(time_start));
  if (time_end != null) args.push('--time-end', String(time_end));
  if (predict_window != null) args.push('--predict-window', String(pwNum));

  const proc = spawn(PYTHON_CMD, args, {
    cwd: ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });

  // P1-2 修复: 增加 spawn 超时，防止 Python 启动挂起导致响应永不返回
  let responded = false;
  const spawnTimer = setTimeout(() => {
    if (!responded) {
      try { proc.kill('SIGKILL'); } catch (_) {}
      responded = true;
      res.status(504).json({ success: false, error: 'edm trigger spawn timeout (30s)', code: 'SPAWN_TIMEOUT' });
    }
  }, 30000);

  let stdout = '';
  let stderr = '';

  proc.stdout.on('data', (data) => {
    stdout += data.toString();
  });

  proc.stderr.on('data', (data) => {
    stderr += data.toString();
  });

  proc.on('close', (code) => {
    clearTimeout(spawnTimer);
    if (responded) return;  // 超时已响应
    responded = true;
    try {
      // 从 stdout 提取 JSON 块 (从第一个 { 到最后一个 })
      const firstBrace = stdout.indexOf('{');
      const lastBrace = stdout.lastIndexOf('}');
      if (firstBrace >= 0 && lastBrace > firstBrace) {
        const jsonStr = stdout.slice(firstBrace, lastBrace + 1);
        const result = JSON.parse(jsonStr);
        res.json({ success: code === 0, ...result });
      } else {
        res.json({ success: code === 0, output: stdout.trim(), stderr: stderr.trim() });
      }
    } catch {
      res.json({ success: code === 0, output: stdout.trim(), stderr: stderr.trim() });
    }
  });

  proc.on('error', (err) => {
    clearTimeout(spawnTimer);
    if (responded) return;
    responded = true;
    res.status(500).json({ success: false, error: err.message });
  });
});

// ── API: EDM 轮询代理 (P2-fix: 避免浏览器 CORS) ──────────
// 前端不能直接从 localhost:3100 fetch 到 localhost:8000
// (不同端口 = 跨域，edm-takens-web 的 CORS 白名单不含 localhost:3100)。
// 此后端端点代理转发轮询请求，服务器端 HTTP 无 CORS 限制。

const EDM_POLL_URL = process.env.EDM_API_URL || 'http://127.0.0.1:8000';

app.get('/api/edm/poll/:jobId', (req, res) => {
  const { jobId } = req.params;
  // P2-1 修复: 校验 jobId 格式，防止 SSRF 或路径注入
  if (!/^[\w\-]{1,128}$/.test(jobId)) {
    return res.status(400).json({ error: 'invalid jobId format', code: 'INVALID_JOB_ID' });
  }
  const mod = EDM_POLL_URL.startsWith('https') ? require('https') : require('http');
  const url = `${EDM_POLL_URL}/api/analyze/jobs/${encodeURIComponent(jobId)}`;

  reqLog(req, 'info', `EDM poll proxy → ${url}`);

  // ROUND51 E2E 修复: 响应防重入守卫.
  // 病灶: 原实现 setTimeout(5s) 触发时 res.json(504), 随后 upstream.destroy()
  // 触发 'error' 事件 → error 处理器再次 res.json(502) → ERR_HTTP_HEADERS_SENT
  // 抛异常崩溃整个 trace-to-edm 进程, 使 EDM 轮询链路被杀死 (EDM 后端分析
  // 正常运行但前端永远等不到结果). 现用 responded 标志保证三种响应路径
  // (end / error / timeout) 只响应一次, 竞争安全.
  let responded = false;
  const respond = (fn) => {
    if (responded) return;
    responded = true;
    try { fn(); } catch (_) { /* res 可能已关闭, 静默 */ }
  };

  const upstream = mod.get(url, { timeout: 5000 }, (upRes) => {
    let body = '';
    upRes.on('data', chunk => body += chunk);
    upRes.on('end', () => {
      respond(() => {
        try {
          res.json(JSON.parse(body));
        } catch {
          res.status(502).json({ error: 'invalid upstream response', raw: body.slice(0, 200) });
        }
      });
    });
  });

  upstream.on('error', (err) => {
    reqLog(req, 'warn', `EDM poll failed: ${err.message}`);
    respond(() => {
      res.status(502).json({
        error: `edm-takens-web unreachable: ${err.message}`,
        hint: '请确保 edm-takens-web 后端已启动 (python run_backend.py, 端口 8000)'
      });
    });
  });

  upstream.setTimeout(5000, () => {
    respond(() => {
      res.status(504).json({ error: 'edm-takens-web timeout' });
    });
    try { upstream.destroy(); } catch (_) {}
  });
});

// ── API: 任务历史 ─────────────────────────────────────────

};
