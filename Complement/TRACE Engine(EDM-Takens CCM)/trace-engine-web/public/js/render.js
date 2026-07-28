/* TRACE Engine Web — 结果渲染与日志工具（debt-09 + debt-10）
 * ==========================================================
 * 抽取自原 index.html 内联 <script>。
 *
 * debt-10：renderResult 利用 RESULT_SCHEMA（由 schema.js 从 /api/schema 加载）
 *          驱动动态渲染——校验 required 字段是否齐全，缺失时显示空态提示。
 *
 * 本文件还提供跨脚本共享的纯工具函数：escapeHtml / safeFmt / showToast / log。
 *
 * 依赖（运行时由 app.js 提供 DOM 引用）：
 *   - terminal / logStageBadge / logFilters / pauseLogBtn / clearLogBtn / toast / resultPanel
 */

// ── 日志状态与配置 ────────────────────────────────────────────────────
const LOG_LEVELS = ['stage', 'info', 'warn', 'error', 'done', 'stderr'];
const LOG_ICONS = { stage: '▶', info: '◉', warn: '▲', error: '✖', done: '✓', stderr: '⚠' };
const MAX_LOG_LINES = 400;
let activeLogLevels = new Set(LOG_LEVELS);
let logAutoScroll = true;

// ── 共享纯工具函数 ────────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (m) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[m]));
}

// 安全数值格式化：null/undefined/NaN 等非数值返回 'N/A'，避免 toFixed 崩溃
const safeFmt = (v, n = 4) => (v != null && typeof v === 'number' && !isNaN(v)) ? v.toFixed(n) : 'N/A';

let _toastTimer = null;
function showToast(msg, type) {
  if (!toast) return;
  toast.textContent = msg;
  toast.className = 'toast ' + (type || 'hidden');
  toast.style.display = type ? 'block' : 'none';
  // Round 17 修缮：error 类型停留 6s，其他 4s 后自动消失
  if (_toastTimer) clearTimeout(_toastTimer);
  if (type && type !== 'hidden') {
    const ms = type === 'error' ? 6000 : 4000;
    _toastTimer = setTimeout(() => {
      toast.style.display = 'none';
      toast.className = 'toast';
    }, ms);
  }
}

// ── 日志渲染（cockpit 风格） ──────────────────────────────────────────
function applyLogFilters() {
  if (!terminal) return;
  for (const line of terminal.children) {
    if (line.classList.contains('log-paused-hint')) continue;
    const lvl = line.getAttribute('data-level') || 'info';
    line.classList.toggle('hidden', !activeLogLevels.has(lvl));
  }
  if (logAutoScroll) terminal.scrollTop = terminal.scrollHeight;
}

function updateLogFilterButtons() {
  const allActive = LOG_LEVELS.every(l => activeLogLevels.has(l));
  for (const btn of logFilters) {
    const lvl = btn.dataset.level;
    if (lvl === 'all') {
      btn.classList.toggle('active', allActive);
    } else {
      btn.classList.toggle('active', activeLogLevels.has(lvl));
    }
  }
}

function log(level, message) {
  if (!terminal) return;
  // 过滤无意义行：空行、纯分隔符行（ASCII #### ==== ---- **** 或 Unicode 制表符 ─━│┃═║ 等）
  const trimmed = String(message).trim();
  if (!trimmed) return;
  // 去除空格后检测纯分隔符（如 "── ── ──" → "────────"）
  const noSpaces = trimmed.replace(/\s+/g, '');
  if (/^[#=\-*+_~─━│┃═║╔╗╚╝╠╣╦╩╬]+$/.test(noSpaces)) return;
  // 过滤单字符重复 4 次以上的纯分隔行（如 ────── 或 ======）
  if (/^(.)\1{4,}$/.test(noSpaces)) return;
  // 过滤纯图标行（单个符号无实际内容）
  if (/^[◉▶▲✖✓✦○●◇◆□■△▽☆★]+$/.test(noSpaces)) return;

  const normalized = LOG_LEVELS.includes(level) ? level : 'info';
  const line = document.createElement('div');
  line.className = `terminal-line ${normalized}`;
  line.setAttribute('data-level', normalized);
  const ts = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const icon = LOG_ICONS[normalized] || LOG_ICONS.info;
  let msgHtml = escapeHtml(message);
  // 对关键系统信息做视觉强化
  if (/(耗时预估|超时阈值|研报级)/.test(message)) {
    line.classList.add('highlight');
    msgHtml = msgHtml.replace(/(\d+[\d\s]*)/g, '<strong>$1</strong>');
  }
  line.innerHTML = `<span class="log-icon">${icon}</span><span class="log-meta"><span class="log-ts">${ts}</span><span class="log-level">${normalized}</span></span><span class="log-msg">${msgHtml}</span>`;
  terminal.appendChild(line);

  // 限制 DOM 行数，避免超大日志卡顿
  while (terminal.children.length > MAX_LOG_LINES) {
    terminal.removeChild(terminal.firstChild);
  }

  if (!activeLogLevels.has(normalized)) {
    line.classList.add('hidden');
  }
  if (logAutoScroll) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

function setLogPaused(paused) {
  logAutoScroll = !paused;
  if (pauseLogBtn) {
    pauseLogBtn.textContent = paused ? 'RESUME' : 'PAUSE';
    pauseLogBtn.classList.toggle('active', paused);
  }
  if (!paused && terminal) terminal.scrollTop = terminal.scrollHeight;
}

// ── 结果渲染（debt-10：基于 RESULT_SCHEMA 动态校验字段） ──────────────
/**
 * 渲染分析结果。debt-10：若 RESULT_SCHEMA 可用，先校验 required 字段是否齐全，
 * 缺失字段在对应区段显示空态提示，而非抛出异常。
 */
function renderResult(data) {
  const r = data.result;
  if (!r) return;
  if (resultPanel) resultPanel.classList.remove('hidden');

  // 有结果后显示顶部状态墙
  const statusWall = document.getElementById('statusWall');
  if (statusWall) statusWall.classList.remove('awaiting-data');

  // debt-10：基于 resultSchema 校验必需字段（仅记录缺失，不阻断渲染）
  const missingFields = [];
  if (RESULT_SCHEMA && RESULT_SCHEMA.required) {
    for (const field of RESULT_SCHEMA.required) {
      if (r[field] === undefined || r[field] === null) {
        missingFields.push(field);
      }
    }
    if (missingFields.length > 0) {
      log('warn', `结果缺少 Schema 必需字段: ${missingFields.join(', ')}（已用空态占位）`);
    }
  }

  // 状态墙（顶部）+ 结果面板（详情）双更新；使用独立 ID 避免冲突
  function setMetric(id, value, styleFn) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
    if (styleFn) styleFn(el);
  }

  const conceptsVal = r.concepts ? r.concepts.length : '-';
  const edgesVal = r.n_significant_edges ?? '-';
  const ateVal = safeFmt(r.ate, 4);
  const ciVal = r.confidence_interval
    ? `[${safeFmt(r.confidence_interval[0], 2)}, ${safeFmt(r.confidence_interval[1], 2)}]`
    : '-';
  const identifiableVal = r.identifiable ? 'YES' : 'NO';
  const refutedVal = r.refutations
    ? `${r.refutations.filter(x => x.refuted).length}/${r.refutations.length}`
    : '-';
  // P1 修缮 (Round 23 §审计前端消费): 区分 LIGHT(0/0 未测试) 与 DEEP/SUPER(0/3 全通过)
  const refutationsAttempted = r.refutations ? r.refutations.length : 0;
  const refutedSemantic = refutationsAttempted === 0
    ? '<span class="badge warn" title="LIGHT模式跳过反驳测试">未测试</span>'
    : (r.refutations.filter(x => x.refuted).length === 0
        ? '<span class="badge pass" title="3次反驳测试全部通过">3/3 通过</span>'
        : `<span class="badge fail">${r.refutations.filter(x => x.refuted).length}/3 被反驳</span>`);
  const modeVal = (r.analysis_mode || 'light').toUpperCase();
  const durationVal = r.execution_profile && r.execution_profile.total_ms != null
    ? `${safeFmt(r.execution_profile.total_ms / 1000, 2)}s`
    : '-';

  setMetric('mConcepts', conceptsVal);
  setMetric('rConcepts', conceptsVal);
  setMetric('mEdges', edgesVal);
  setMetric('rEdges', edgesVal);
  setMetric('mATE', ateVal);
  setMetric('rATE', ateVal);
  setMetric('rCI', ciVal);
  setMetric('mIdentifiable', identifiableVal, el => { el.style.color = r.identifiable ? 'var(--success)' : 'var(--fail)'; });
  setMetric('rIdentifiable', identifiableVal, el => { el.style.color = r.identifiable ? 'var(--success)' : 'var(--fail)'; });
  setMetric('mRefuted', refutedVal);
  setMetric('rRefuted', refutedVal);
  setMetric('mMode', modeVal);
  setMetric('rMode', modeVal);
  setMetric('rDuration', durationVal);

  // Parameters — 质谱级参数网格
  const paramGrid = document.getElementById('paramGrid');
  paramGrid.innerHTML = '';
  const params = [
    { k: 'Treatment', v: r.treatment },
    { k: 'Outcome', v: r.outcome },
    { k: 'Threshold', v: r.threshold ?? 0.03 },
    { k: 'Window Size', v: r.window_size ?? 8 },
    { k: 'Concept Min Freq', v: r.concept_min_freq ?? 1 },
    { k: 'Max Concepts', v: r.max_concepts ?? 12 },
    { k: 'Analysis Mode', v: (r.analysis_mode || 'light').toUpperCase() },
    { k: 'LLaMA Model', v: r.model ? r.model : 'N/A' },
    { k: 'Backend', v: r.backend ?? 'DoWhy' },
    { k: 'Simulation', v: r.simulation ? 'YES' : 'NO' },
    { k: 'Estimand Type', v: r.estimand_type ?? 'N/A' },
    { k: 'N Samples', v: r.n_samples ?? '-' },
    { k: 'Confidence Method', v: r.confidence_method ?? 'bootstrap' },
  ];
  params.forEach(p => {
    const div = document.createElement('div');
    div.className = 'param';
    div.innerHTML = `<span class="k">${p.k}</span><span class="v">${escapeHtml(String(p.v))}</span>`;
    paramGrid.appendChild(div);
  });

  // Execution profile
  const execProfile = document.getElementById('execProfile');
  execProfile.innerHTML = '';
  if (r.execution_profile && r.execution_profile.stages) {
    const table = document.createElement('table');
    table.innerHTML = '<thead><tr><th>STAGE</th><th>MS</th><th>%</th></tr></thead>';
    const tbody = document.createElement('tbody');
    const total = r.execution_profile.total_ms || 1;
    r.execution_profile.stages.forEach(s => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${s.stage}</td><td>${s.ms}</td><td>${total > 0 ? safeFmt((s.ms / total) * 100, 1) : 'N/A'}%</td>`;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    execProfile.appendChild(table);
  } else {
    execProfile.innerHTML = '<div style="color:var(--muted)">无执行时间数据</div>';
  }

  // Environment & bridge health
  const envDiagnostics = document.getElementById('envDiagnostics');
  envDiagnostics.innerHTML = '';
  const env = r.environment_diagnostics || {};
  const envParams = [
    { k: 'Python', v: env.python_version },
    { k: 'PyTorch', v: env.torch_version },
    { k: 'CUDA', v: env.cuda_available ? (env.cuda_device || 'YES') : 'NO' },
    { k: 'VRAM Free', v: env.vram_free_mb != null ? `${env.vram_free_mb} MB` : 'N/A' },
    { k: 'Model Dir Exists', v: env.model_dir_exists ? 'YES' : 'NO' },
    { k: 'Bridge Modules', v: env.bridge_modules_ok ? 'OK' : 'FAIL' },
    { k: 'Trace Root', v: env.trace_root },
  ];
  const envGrid = document.createElement('div');
  envGrid.className = 'param-grid';
  envParams.forEach(p => {
    const div = document.createElement('div');
    div.className = 'param';
    div.innerHTML = `<span class="k">${p.k}</span><span class="v">${escapeHtml(String(p.v ?? 'N/A'))}</span>`;
    envGrid.appendChild(div);
  });
  envDiagnostics.appendChild(envGrid);

  // Data & model diagnostics
  const dataDiagnostics = document.getElementById('dataDiagnostics');
  dataDiagnostics.innerHTML = '';
  const diag = r.data_diagnostics || {};
  // P1 修缮 (Round 23 §审计前端消费): signal_type 特殊标注, 区分共现计数 vs 真实ΔNLL
  const kpiHtml = Object.entries(diag).map(([k, v]) => {
    let display = v;
    if (typeof v === 'number') display = Number.isInteger(v) ? v : v.toFixed(4);
    // signal_type 字段特殊高亮
    if (k === 'signal_type') {
      const stype = String(v);
      const cls = stype === 'delta_nll' ? 'pass' : (stype === 'co_occurrence' ? 'warn' : '');
      const label = stype === 'delta_nll' ? '真实ΔNLL' : (stype === 'co_occurrence' ? '共现计数' : stype);
      return `<span class="kpi-pill"><span class="k">${k}:</span><span class="badge ${cls}" title="信号语义类型">${escapeHtml(label)}</span></span>`;
    }
    return `<span class="kpi-pill"><span class="k">${k}:</span>${escapeHtml(String(display))}</span>`;
  }).join('');
  // 附加反驳语义徽章
  const refutedBadgeHtml = `<span class="kpi-pill"><span class="k">refutations:</span>${refutedSemantic}</span>`;
  dataDiagnostics.innerHTML = `<div class="kpi-row">${kpiHtml}${refutedBadgeHtml || ''}</div>` + (kpiHtml ? '' : '<span class="kpi-pill">无诊断数据</span>');

  // Algorithm sufficiency
  const sufficiencyPanel = document.getElementById('sufficiencyPanel');
  sufficiencyPanel.innerHTML = '';
  const suff = r.algorithm_sufficiency || {};
  const suffOk = suff.sufficient;
  const suffBadge = suffOk
    ? '<span class="badge pass">SUFFICIENT</span>'
    : '<span class="badge warn">ADVISORY</span>';
  const suffRecs = (suff.recommendations || []).map(rec => `<div class="warrior-finding">→ ${escapeHtml(rec)}</div>`).join('');
  sufficiencyPanel.innerHTML = `
    <div style="display:flex;align-items:center;gap:0.8rem;margin-bottom:0.5rem;flex-wrap:wrap;">
      <span style="font-family:var(--font-mono);color:var(--muted);">ALGORITHM SUFFICIENCY:</span>
      ${suffBadge}
      <span class="kpi-pill"><span class="k">tokens:</span>${suff.n_tokens ?? '-'}</span>
      <span class="kpi-pill"><span class="k">concepts:</span>${suff.n_concepts ?? '-'}</span>
      <span class="kpi-pill"><span class="k">edges:</span>${suff.n_edges ?? '-'}</span>
    </div>
    ${suffRecs}
  `;

  // Identifiability & backend
  const identPanel = document.getElementById('identifiabilityPanel');
  identPanel.innerHTML = '';
  const ident = r.identifiability || {};
  const identParams = [
    { k: 'Identifiable', v: ident.identifiable ?? r.identifiable },
    { k: 'Estimand Type', v: ident.estimand_type ?? r.estimand_type ?? 'N/A' },
    { k: 'Backdoor Paths', v: ident.backdoor_paths ?? 'N/A' },
    { k: 'Adjustment Set', v: ident.adjustment_set ? ident.adjustment_set.join(', ') : 'N/A' },
    { k: 'Backend Engine', v: r.backend ?? 'DoWhy' },
    { k: 'DoWhy Available', v: r.dowhy_available ? 'YES' : 'NO' },
    { k: 'CausalLearn Available', v: r.causallearn_available ? 'YES' : 'NO' },
  ];
  const identGrid = document.createElement('div');
  identGrid.className = 'param-grid';
  identParams.forEach(p => {
    const div = document.createElement('div');
    div.className = 'param';
    div.innerHTML = `<span class="k">${p.k}</span><span class="v">${escapeHtml(String(p.v))}</span>`;
    identGrid.appendChild(div);
  });
  identPanel.appendChild(identGrid);

  // Concept vocabulary & frequency
  const conceptFreqBody = document.getElementById('conceptFreqBody');
  conceptFreqBody.innerHTML = '';
  const freqMap = r.concept_frequencies || {};
  const sortedConcepts = Object.entries(freqMap).sort((a, b) => b[1] - a[1]);
  if (sortedConcepts.length === 0) {
    conceptFreqBody.innerHTML = '<tr><td colspan="4" class="empty-state">无概念频率数据</td></tr>';
  } else {
    sortedConcepts.forEach(([concept, freq], idx) => {
      const eligible = (r.ccm_eligible_concepts || []).includes(concept) ? 'YES' : 'NO';
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${escapeHtml(concept)}</td><td>${freq}</td><td>${idx + 1}</td><td>${eligible}</td>`;
      conceptFreqBody.appendChild(tr);
    });
  }

  // Adjacency matrix heatmap (default) + 3D topology toggle
  const adjMatrixWrap = document.getElementById('adjMatrixWrap');
  if (adjMatrixWrap) adjMatrixWrap.innerHTML = buildAdjacencyMatrixHTML(r);

  // 3D topology is hidden by default; toggle button swaps between 2D matrix and 3D view
  const mainMatrixView = document.getElementById('mainMatrixView');
  const mainTopologyView = document.getElementById('mainTopologyView');
  if (mainMatrixView && mainTopologyView) {
    mainMatrixView.classList.remove('hidden');
    mainTopologyView.classList.add('hidden');
  }
  const mainTopoToggle = document.getElementById('mainTopoToggle');
  if (mainTopoToggle && typeof setupTopologyToggle === 'function') {
    setupTopologyToggle(r, {
      matrixView: mainMatrixView,
      topologyView: mainTopologyView,
      wrap: document.getElementById('topologyWrap'),
      canvas: document.getElementById('topologyCanvas'),
      pauseBtn: document.getElementById('topoPauseBtn'),
      resetBtn: document.getElementById('topoResetBtn'),
      toggleBtn: mainTopoToggle
    });
  }

  // Stability & robustness
  const stabilityPanel = document.getElementById('stabilityPanel');
  stabilityPanel.innerHTML = '';
  const stability = r.stability_analysis || {};
  if (Object.keys(stability).length === 0) {
    const mode = r.analysis_mode || r.mode || 'light';
    const stabilityEmptyMsg = mode === 'light'
      ? 'LIGHT 模式未执行稳定性/排列检验。切换 DEEP 或 SUPER 模式可获得 bootstrap 边稳定性、置换 p-value 等质谱级指标。'
      : `${mode.toUpperCase()} 模式稳定性分析未返回数据（可能因数据量不足或分析失败）。请检查日志或增大文本长度。`;
    stabilityPanel.innerHTML = `<div class="empty-state">${stabilityEmptyMsg}</div>`;
  } else {
    const stabParams = [
      { k: 'Edge Stability Mean', v: stability.edge_stability_mean != null ? stability.edge_stability_mean.toFixed(4) : 'N/A' },
      { k: 'Edge Stability Std', v: stability.edge_stability_std != null ? stability.edge_stability_std.toFixed(4) : 'N/A' },
      { k: 'ATE Bootstrap Std', v: stability.ate_bootstrap_std != null ? stability.ate_bootstrap_std.toFixed(4) : 'N/A' },
      { k: 'Permutation p-value', v: stability.permutation_p_value != null ? stability.permutation_p_value.toFixed(4) : 'N/A' },
      { k: 'CV Folds', v: stability.cv_folds ?? 'N/A' },
      { k: 'CV ATE Mean', v: stability.cv_ate_mean != null ? stability.cv_ate_mean.toFixed(4) : 'N/A' },
      { k: 'CV ATE Std', v: stability.cv_ate_std != null ? stability.cv_ate_std.toFixed(4) : 'N/A' },
    ];
    const stabGrid = document.createElement('div');
    stabGrid.className = 'param-grid';
    stabParams.forEach(p => {
      const div = document.createElement('div');
      div.className = 'param';
      div.innerHTML = `<span class="k">${p.k}</span><span class="v">${escapeHtml(String(p.v))}</span>`;
      stabGrid.appendChild(div);
    });
    stabilityPanel.appendChild(stabGrid);
    if (stability.edge_stability_per_edge) {
      const t = document.createElement('table');
      t.className = 'stability-table';
      t.innerHTML = '<thead><tr><th>EDGE</th><th>STABILITY</th><th>VERDICT</th></tr></thead>';
      const tb = document.createElement('tbody');
      Object.entries(stability.edge_stability_per_edge).forEach(([edge, s]) => {
        const verdict = s > 0.7 ? 'STABLE' : (s > 0.4 ? 'MODERATE' : 'FRAGILE');
        const cls = s > 0.7 ? 'pass' : (s > 0.4 ? 'warn' : 'fail');
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${escapeHtml(edge)}</td><td>${safeFmt(s, 3)}</td><td><span class="badge ${cls}">${verdict}</span></td>`;
        tb.appendChild(tr);
      });
      t.appendChild(tb);
      stabilityPanel.appendChild(t);
    }
  }

  // Top edges
  const edgesBody = document.getElementById('edgesBody');
  edgesBody.innerHTML = '';
  (r.top_edges || []).forEach(e => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${escapeHtml(e.source)}</td><td>${escapeHtml(e.target)}</td><td>${safeFmt(e.strength, 3)}</td><td>${escapeHtml(e.direction || '→')}</td>`;
    edgesBody.appendChild(tr);
  });

  // Counterfactual scan
  const scanBody = document.getElementById('scanBody');
  scanBody.innerHTML = '';
  (r.counterfactual_scan || []).forEach(s => {
    const tr = document.createElement('tr');
    const iteNum = typeof s.ite === 'number' ? s.ite : 0;
    const cls = iteNum > 0 ? 'pass' : (iteNum < 0 ? 'fail' : 'warn');
    const iteStr = (typeof s.ite === 'number' && s.ite >= 0) ? '+' : '';
    tr.innerHTML = `<td>${escapeHtml(s.source)} → ${escapeHtml(s.target)}</td><td>${safeFmt(s.trace_dnl, 3)}</td><td><span class="badge ${cls}">${iteStr}${safeFmt(s.ite, 4)}</span></td><td>${safeFmt(s.observed, 4)}</td><td>${safeFmt(s.counterfactual, 4)}</td>`;
    scanBody.appendChild(tr);
  });

  // Refutations
  const refuteBody = document.getElementById('refuteBody');
  refuteBody.innerHTML = '';
  if (!r.refutations || r.refutations.length === 0) {
    refuteBody.innerHTML = '<tr><td colspan="5" class="empty-state">LIGHT 模式跳过反驳测试。切换 DEEP 模式可获得随机共因 / 安慰剂处理 / 数据子集三套反驳检验。</td></tr>';
  } else {
  (r.refutations || []).forEach(ref => {
    const tr = document.createElement('tr');
    const cls = ref.refuted ? 'fail' : 'pass';
    const metricStr = ref.display_metric != null
      ? `${escapeHtml(ref.display_label)}=${ref.display_metric < 0.001 ? '&lt;0.01%' : safeFmt(ref.display_metric * 100, 2) + '%'}`
      : '-';
    tr.innerHTML = `<td>${escapeHtml(ref.method)}</td><td>${safeFmt(r.ate, 4)}</td><td>${safeFmt(ref.new_effect, 4)}</td><td>${metricStr}</td><td><span class="badge ${cls}">${ref.refuted ? 'REFUTED' : 'ROBUST'}</span></td>`;
    refuteBody.appendChild(tr);
  });
  }

  // Six warriors
  const warriorGrid = document.getElementById('warriorGrid');
  warriorGrid.innerHTML = '';
  const warriors = r.six_warriors || {};
  if (Object.keys(warriors).length === 0) {
    const mode = r.analysis_mode || r.mode || 'light';
    const warriorEmptyMsg = mode === 'light'
      ? 'LIGHT 模式未执行六战士深度诊断。切换 DEEP 或 SUPER 模式可获得 TRACE / CCM / EDM / HAVOK / DoWhy+CF / causallearn 的完整诊断。'
      : `${mode.toUpperCase()} 模式六战士诊断未返回数据（可能因分析失败）。请检查日志。`;
    warriorGrid.innerHTML = `<div class="empty-state">${warriorEmptyMsg}</div>`;
  } else {
  Object.entries(warriors).forEach(([key, card]) => {
    const div = document.createElement('div');
    div.className = `warrior-card ${card.status}`;
    const metrics = Object.entries(card.metrics || {}).map(([k, v]) => `${k}: ${v}`).join(' · ');
    const findings = (card.findings || []).map(f => `<div class="warrior-finding">→ ${escapeHtml(f)}</div>`).join('');
    const rawDetails = card.raw ? `<details><summary>raw metrics</summary><div style="font-family:var(--font-mono);font-size:0.72rem;color:var(--muted);white-space:pre-wrap;">${escapeHtml(JSON.stringify(card.raw, null, 2))}</div></details>` : '';
    // P2-10：warrior_id / name / status 来自后端结果，插入 innerHTML 前必须转义，防止 XSS
    // Round 17 P2 修缮：渲染 Tier-A/B 等级标签，让"四真算法 + 二启发式诊断"在前端显式化
    const safeWarriorId = escapeHtml(card.warrior_id);
    const safeName = escapeHtml(card.name);
    const safeStatus = escapeHtml(card.status);
    const safeTier = escapeHtml(card.tier || '');
    // Tier-A=真算法层(可追溯因果证据)，Tier-B=启发式诊断层(文本特征启发式)
    // 标签弱化显示，避免抢占主信息；hover/focus 时亮起，与 SECTOR 标签风格一致
    const tierTag = safeTier
      ? `<span class="warrior-tier tier-${safeTier}" title="Tier-${safeTier === 'A' ? 'A 真算法层' : 'B 启发式诊断层'}">T${safeTier}</span>`
      : '';
    // P1 修缮 (Round 23 §审计前端消费): CCM verdict 语义徽章
    // ELIGIBLE_BUT_NOT_RUN / HEURISTIC_FALLBACK / NARRATIVE_TEXT → 启发式/未运行
    // VERIFIABLE → 真算法已运行 (当前代码中不会出现, 保留为未来扩展)
    const verdictText = card.verdict || 'N/A';
    let ccmBadge = '';
    if (key === 'ccm') {
      if (verdictText === 'VERIFIABLE') {
        ccmBadge = '<span class="badge pass" title="真实CCM算法已运行并验证">真CCM已验证</span>';
      } else if (verdictText === 'ELIGIBLE_BUT_NOT_RUN') {
        ccmBadge = '<span class="badge warn" title="真算法可导入但未实际调用ccm_with_convergence">启发式覆盖率</span>';
      } else if (verdictText === 'HEURISTIC_FALLBACK') {
        ccmBadge = '<span class="badge warn" title="启发式回退, 非真实CCM">启发式回退</span>';
      } else if (verdictText === 'NARRATIVE_TEXT') {
        ccmBadge = '<span class="badge warn" title="概念稀疏, 不符合CCM条件">概念稀疏</span>';
      }
    }
    div.innerHTML = `
      <div class="warrior-title">${safeWarriorId} · ${safeName} ${tierTag}<span class="warrior-status ${safeStatus}">${safeStatus}</span> ${ccmBadge}</div>
      <div class="warrior-metrics">${escapeHtml(metrics)}</div>
      ${findings}
      <div class="warrior-verdict">// ${escapeHtml(verdictText)}</div>
      ${rawDetails}
    `;
    warriorGrid.appendChild(div);
  });
  }

  document.getElementById('reportLink').href = data.reportPath || '#';
  document.getElementById('jsonLink').href = data.resultPath || '#';

  // 自动滚动到结果区
  resultPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── 共享热力词矩阵 HTML 生成器 ─────────────────────────────────────────
function buildAdjacencyMatrixHTML(r) {
  const concepts = r.concepts || [];
  const matrix = r.adjacency_matrix;
  if (!matrix || matrix.length === 0 || concepts.length === 0) {
    return '<div class="empty-state">无邻接矩阵数据</div>';
  }
  const n = concepts.length;
  const maxVal = Math.max(...matrix.flat().map(v => Math.abs(v)), 1e-9);
  let html = `<div class="adj-matrix" style="grid-template-columns:repeat(${n + 1}, minmax(28px, 1fr));">`;
  html += '<div></div>';
  concepts.forEach(c => {
    const lbl = c.length > 4 ? c.slice(0, 3) + '…' : c;
    html += `<div class="adj-label" title="${escapeHtml(c)}">${escapeHtml(lbl)}</div>`;
  });
  matrix.forEach((row, i) => {
    const lbl = concepts[i].length > 4 ? concepts[i].slice(0, 3) + '…' : concepts[i];
    html += `<div class="adj-label" title="${escapeHtml(concepts[i])}">${escapeHtml(lbl)}</div>`;
    row.forEach((v, j) => {
      const intensity = Math.min(Math.abs(v) / maxVal, 1);
      const bg = i === j ? 'var(--panel-3)' : `rgba(102,252,241,${0.08 + intensity * 0.72})`;
      const color = intensity > 0.5 ? '#000' : 'var(--text)';
      const val = v !== 0 ? safeFmt(Number(v), 1) : '';
      html += `<div class="adj-cell" style="background:${bg};color:${color};" title="${escapeHtml(concepts[i])} → ${escapeHtml(concepts[j])}: ${safeFmt(Number(v), 2)}">${val}</div>`;
    });
  });
  html += '</div>';
  html += `<div class="adj-legend"><span>0</span><div class="adj-legend-bar"></div><span>${maxVal.toFixed(1)}</span></div>`;
  return html;
}
window.buildAdjacencyMatrixHTML = buildAdjacencyMatrixHTML;

// P1 fix (Round 26 §5): 3D 因果拓扑网络图渲染器
// 用 Canvas 2D 模拟 3D 力导向 + 透视投影，支持拖拽旋转、滚轮缩放、自动旋转。
const topologyStates = new Map();

function project(p, rotX, rotY, zoom, W, H) {
  // 绕 Y 轴旋转
  let x = p.x * Math.cos(rotY) - p.z * Math.sin(rotY);
  let z = p.x * Math.sin(rotY) + p.z * Math.cos(rotY);
  // 绕 X 轴旋转
  let y = p.y * Math.cos(rotX) - z * Math.sin(rotX);
  z = p.y * Math.sin(rotX) + z * Math.cos(rotX);
  const fov = 800;
  const scale = (fov * zoom) / (fov + z + 400);
  return { x: W / 2 + x * scale, y: H / 2 + y * scale, z, scale };
}

function initPositions(nodes, edges) {
  const n = nodes.length;
  const radius = Math.max(120, n * 18);
  nodes.forEach((node, i) => {
    const theta = (i / n) * Math.PI * 2;
    const phi = Math.acos(2 * (i + 0.5) / n - 1);
    node.x = radius * Math.sin(phi) * Math.cos(theta);
    node.y = radius * Math.sin(phi) * Math.sin(theta);
    node.z = radius * Math.cos(phi);
    // 节点大小基于出现频次
    node.radius = 4 + Math.sqrt(node.freq || 1) * 1.8;
  });
  // 简单力导向迭代几次让边长度均匀
  for (let iter = 0; iter < 40; iter++) {
    // 斥力
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
        let dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
        const force = 2000 / (dist * dist + 100);
        const fx = (dx / dist) * force, fy = (dy / dist) * force, fz = (dz / dist) * force;
        a.x += fx; a.y += fy; a.z += fz;
        b.x -= fx; b.y -= fy; b.z -= fz;
      }
    }
    // 引力(边)
    edges.forEach(e => {
      const a = e.source, b = e.target;
      let dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
      let dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
      const force = (dist - 90) * 0.015;
      const fx = (dx / dist) * force, fy = (dy / dist) * force, fz = (dz / dist) * force;
      a.x += fx; a.y += fy; a.z += fz;
      b.x -= fx; b.y -= fy; b.z -= fz;
    });
    // 向中心引力防止飞散
    nodes.forEach(node => {
      node.x *= 0.96; node.y *= 0.96; node.z *= 0.96;
    });
  }
}

function renderTopology3D(r, wrap, canvas, pauseBtn, resetBtn) {
  if (!wrap || !canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;

  function resize() {
    const rect = wrap.getBoundingClientRect();
    const W = Math.max(1, rect.width);
    const H = Math.max(1, rect.height);
    canvas.width = Math.floor(W * dpr);
    canvas.height = Math.floor(H * dpr);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { W, H };
  }

  let { W, H } = resize();

  // DES-01 修复: 节点数 > 32 时显示提示，避免静默丢弃
  const allConcepts = r.concepts || [];
  const TRUNCATED = allConcepts.length > 32;
  const concepts = allConcepts.slice(0, 32); // 限制节点数保证性能
  const freq = r.concept_frequencies || {};
  if (concepts.length < 2) {
    ctx.fillStyle = '#94a3b8';
    ctx.font = '13px monospace';
    ctx.fillText('概念数不足 (需≥2)', 12, H / 2);
    return;
  }

  const nodes = concepts.map((c, i) => ({ id: c, index: i, freq: freq[c] || 1 }));
  const edges = [];
  const matrix = r.adjacency_matrix;
  if (matrix && matrix.length === concepts.length) {
    for (let i = 0; i < concepts.length; i++) {
      for (let j = 0; j < concepts.length; j++) {
        if (i === j) continue;
        const v = Number(matrix[i][j]);
        if (!isNaN(v) && Math.abs(v) > 0.01) {
          edges.push({ source: nodes[i], target: nodes[j], strength: v });
        }
      }
    }
  }
  // 如果没有矩阵，用 top_edges 兜底
  if (edges.length === 0 && r.top_edges) {
    r.top_edges.forEach(e => {
      const s = nodes.find(n => n.id === e.source);
      const t = nodes.find(n => n.id === e.target);
      if (s && t) edges.push({ source: s, target: t, strength: e.strength });
    });
  }

  initPositions(nodes, edges);

  const existing = topologyStates.get(canvas);
  if (existing && existing.rafId) cancelAnimationFrame(existing.rafId);

  const state = {
    rafId: null, nodes, edges, rotX: 0.35, rotY: 0.45, zoom: 1.0,
    dragging: false, lastX: 0, lastY: 0, paused: false, W, H, wrap, canvas, ctx, dpr,
    truncated: TRUNCATED, totalConcepts: allConcepts.length
  };
  topologyStates.set(canvas, state);

  function draw() {
    const s = topologyStates.get(canvas);
    if (!s) return;
    const { W: w, H: h } = s;
    ctx.fillStyle = '#05070a';
    ctx.fillRect(0, 0, w, h);

    // 投影所有节点并排序(远到近)
    const projected = s.nodes.map(n => ({ node: n, ...project(n, s.rotX, s.rotY, s.zoom, w, h) })).sort((a, b) => a.z - b.z);

    // 画边
    const maxStr = Math.max(...s.edges.map(x => Math.abs(x.strength)), 1e-6);
    s.edges.forEach(e => {
      const pa = projected[e.source.index];
      const pb = projected[e.target.index];
      if (!pa || !pb) return;
      const intensity = Math.min(Math.abs(e.strength) / maxStr, 1);
      ctx.strokeStyle = e.strength > 0
        ? `rgba(102, 252, 241, ${0.12 + intensity * 0.55})`
        : `rgba(255, 100, 100, ${0.12 + intensity * 0.55})`;
      ctx.lineWidth = 0.8 + intensity * 2.2;
      ctx.beginPath();
      ctx.moveTo(pa.x, pa.y);
      ctx.lineTo(pb.x, pb.y);
      ctx.stroke();
    });

    // 画节点
    projected.forEach(p => {
      const radius = p.node.radius * Math.max(0.4, p.scale * 0.012);
      const alpha = Math.max(0.35, Math.min(1, (p.z + 300) / 500));
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0, 217, 163, ${alpha})`;
      ctx.fill();
      ctx.strokeStyle = `rgba(255, 255, 255, ${alpha * 0.4})`;
      ctx.lineWidth = 0.8;
      ctx.stroke();
      // 标签只给较近节点
      if (alpha > 0.7) {
        ctx.fillStyle = `rgba(200, 220, 235, ${alpha})`;
        ctx.font = `${Math.max(9, 10 * p.scale * 0.012)}px monospace`;
        ctx.fillText(p.node.id.slice(0, 6), p.x + radius + 3, p.y + 3);
      }
    });

    // 坐标轴提示
    ctx.fillStyle = 'rgba(148,163,184,0.5)';
    ctx.font = '10px monospace';
    ctx.fillText(`3D TOPO · nodes=${s.nodes.length} edges=${s.edges.length}`, 8, h - 8);
    // DES-01: 节点截断提示
    if (s.truncated) {
      ctx.fillStyle = 'rgba(251,191,36,0.85)';
      ctx.font = '11px monospace';
      ctx.fillText(`⚠ 已显示前 32 个节点 (共 ${s.totalConcepts} 个)`, 8, h - 22);
    }
  }

  function animate() {
    const s = topologyStates.get(canvas);
    if (!s) return;
    if (!s.paused && !s.dragging) s.rotY += 0.003;
    draw();
    s.rafId = requestAnimationFrame(animate);
  }

  // 事件绑定(每个 canvas 只绑定一次)
  if (!canvas._topoBound) {
    canvas._topoBound = true;
    canvas.addEventListener('mousedown', e => {
      const s = topologyStates.get(canvas);
      if (!s) return;
      s.dragging = true;
      s.lastX = e.clientX;
      s.lastY = e.clientY;
    });
    window.addEventListener('mousemove', e => {
      for (const s of topologyStates.values()) {
        if (!s.dragging) continue;
        const dx = e.clientX - s.lastX;
        const dy = e.clientY - s.lastY;
        s.rotY += dx * 0.008;
        s.rotX += dy * 0.008;
        s.lastX = e.clientX;
        s.lastY = e.clientY;
      }
    });
    window.addEventListener('mouseup', () => {
      for (const s of topologyStates.values()) s.dragging = false;
    });
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const s = topologyStates.get(canvas);
      if (!s) return;
      s.zoom *= e.deltaY > 0 ? 0.9 : 1.1;
      s.zoom = Math.max(0.3, Math.min(3.0, s.zoom));
    }, { passive: false });
  }

  pauseBtn = pauseBtn || wrap.querySelector('.topo-pause-btn');
  if (pauseBtn && !pauseBtn._topoBound) {
    pauseBtn._topoBound = true;
    pauseBtn.addEventListener('click', () => {
      const s = topologyStates.get(canvas);
      if (!s) return;
      s.paused = !s.paused;
      pauseBtn.textContent = s.paused ? '▶' : '⏸';
    });
  }
  resetBtn = resetBtn || wrap.querySelector('.topo-reset-btn');
  if (resetBtn && !resetBtn._topoBound) {
    resetBtn._topoBound = true;
    resetBtn.addEventListener('click', () => {
      const s = topologyStates.get(canvas);
      if (!s) return;
      s.rotX = 0.35; s.rotY = 0.45; s.zoom = 1.0;
    });
  }

  if (!wrap._topoResizeObs) {
    const ro = new ResizeObserver(() => {
      const s = topologyStates.get(canvas);
      if (!s) return;
      const rect = wrap.getBoundingClientRect();
      s.W = Math.max(1, rect.width);
      s.H = Math.max(1, rect.height);
      canvas.width = Math.floor(s.W * dpr);
      canvas.height = Math.floor(s.H * dpr);
      canvas.style.width = s.W + 'px';
      canvas.style.height = s.H + 'px';
      s.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    });
    ro.observe(wrap);
    wrap._topoResizeObs = ro;
  }

  animate();
}
window.renderTopology3D = renderTopology3D;

function setupTopologyToggle(r, opts) {
  const { matrixView, topologyView, wrap, canvas, toggleBtn, pauseBtn, resetBtn } = opts;
  if (!toggleBtn || !matrixView || !topologyView) return;
  topologyView.classList.add('hidden');
  matrixView.classList.remove('hidden');
  toggleBtn.textContent = '3D 拓扑';
  if (toggleBtn._topoToggleBound) return;
  toggleBtn._topoToggleBound = true;
  toggleBtn.addEventListener('click', () => {
    const hidden = topologyView.classList.contains('hidden');
    if (hidden) {
      topologyView.classList.remove('hidden');
      matrixView.classList.add('hidden');
      toggleBtn.textContent = '2D 矩阵';
      const s = topologyStates.get(canvas);
      if (!s) {
        renderTopology3D(r, wrap, canvas, pauseBtn, resetBtn);
      } else {
        s.paused = false;
        const rect = wrap.getBoundingClientRect();
        s.W = Math.max(1, rect.width);
        s.H = Math.max(1, rect.height);
        canvas.width = Math.floor(s.W * s.dpr);
        canvas.height = Math.floor(s.H * s.dpr);
        canvas.style.width = s.W + 'px';
        canvas.style.height = s.H + 'px';
        s.ctx.setTransform(s.dpr, 0, 0, s.dpr, 0, 0);
      }
    } else {
      topologyView.classList.add('hidden');
      matrixView.classList.remove('hidden');
      toggleBtn.textContent = '3D 拓扑';
      const s = topologyStates.get(canvas);
      if (s) s.paused = true;
    }
  });
}
window.setupTopologyToggle = setupTopologyToggle;
