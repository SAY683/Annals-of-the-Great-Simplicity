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
const MAX_LOG_LINES = 300;
const MAX_LOG_MSG_LENGTH = 2000;
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
  // 截断超长消息，防止单行 DOM 节点过大导致渲染/内存爆炸
  let displayMessage = String(message);
  let truncated = false;
  if (displayMessage.length > MAX_LOG_MSG_LENGTH) {
    displayMessage = displayMessage.slice(0, MAX_LOG_MSG_LENGTH) + '…';
    truncated = true;
  }
  let msgHtml = escapeHtml(displayMessage);
  if (truncated) {
    msgHtml += ` <span style="color:var(--muted);font-size:0.6rem;">(截断, 原长 ${String(message).length})</span>`;
  }
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
      topology2DView: document.getElementById('mainTopology2DView'),
      wrap: document.getElementById('topologyWrap'),
      canvas: document.getElementById('topologyCanvas'),
      wrap2D: document.getElementById('topology2DWrap'),
      canvas2D: document.getElementById('topology2DCanvas'),
      toggleBtn: mainTopoToggle,
      toggle2DBtn: document.getElementById('mainTopo2DToggle'),
      pauseBtn: document.getElementById('topoPauseBtn'),
      resetBtn: document.getElementById('topoResetBtn'),
      reset2DBtn: document.getElementById('topo2DResetBtn')
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
  // P0 修复 (2026-07-29): 矩阵标签差位问题——改用 "auto + repeat(n, 32px)" 网格,
  // 行标签不旋转, 列标签在独立表头中旋转, 避免单元格内旋转导致的差位.
  let html = `<div class="adj-matrix-wrap">`;
  // P0 修复 (2026-07-29): 行标签列必须给一个最小宽度, 避免中文多字概念被压缩成单字.
  html += `<div class="adj-matrix" style="grid-template-columns:minmax(84px, auto) repeat(${n}, minmax(28px, 32px));">`;
  // 顶部列标签行
  html += '<div class="adj-corner"></div>';
  concepts.forEach(c => {
    html += `<div class="adj-col-header" title="${escapeHtml(c)}"><span>${escapeHtml(c)}</span></div>`;
  });
  // 数据行
  matrix.forEach((row, i) => {
    html += `<div class="adj-row-header" title="${escapeHtml(concepts[i])}">${escapeHtml(concepts[i])}</div>`;
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
  html += '</div>';
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

    // ── 氛围背景: 径向渐变 + 网格 + 星点 ──────────────────────
    const bgGrad = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.7);
    bgGrad.addColorStop(0, '#0a1018');
    bgGrad.addColorStop(0.5, '#070b12');
    bgGrad.addColorStop(1, '#030508');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, w, h);

    // 细网格 (透视感)
    ctx.strokeStyle = 'rgba(102,252,241,0.04)';
    ctx.lineWidth = 1;
    const gridStep = 40;
    for (let x = 0; x < w; x += gridStep) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }
    for (let y = 0; y < h; y += gridStep) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }
    // 星点 (固定 seed 避免闪烁)
    if (!s._stars) {
      s._stars = [];
      for (let i = 0; i < 60; i++) {
        s._stars.push({ x: Math.random() * w, y: Math.random() * h, r: Math.random() * 1.2 + 0.3, a: Math.random() * 0.3 + 0.1 });
      }
    }
    s._stars.forEach(st => {
      ctx.fillStyle = `rgba(180,200,220,${st.a})`;
      ctx.beginPath(); ctx.arc(st.x, st.y, st.r, 0, Math.PI * 2); ctx.fill();
    });

    // ── 投影所有节点并排序(远到近) ──────────────────────────
    const projected = s.nodes.map(n => ({ node: n, ...project(n, s.rotX, s.rotY, s.zoom, w, h) })).sort((a, b) => a.z - b.z);
    const maxStr = Math.max(...s.edges.map(x => Math.abs(x.strength)), 1e-6);

    // ── 画边: 渐变 + 箭头 + strength 标签 ────────────────────
    s.edges.forEach(e => {
      const pa = projected[e.source.index];
      const pb = projected[e.target.index];
      if (!pa || !pb) return;
      const intensity = Math.min(Math.abs(e.strength) / maxStr, 1);
      const avgAlpha = (Math.max(0.35, Math.min(1, (pa.z + 300) / 500)) + Math.max(0.35, Math.min(1, (pb.z + 300) / 500))) / 2;

      // 渐变线条
      const lineGrad = ctx.createLinearGradient(pa.x, pa.y, pb.x, pb.y);
      const colorPos = e.strength > 0 ? '102,252,241' : '255,100,100';
      lineGrad.addColorStop(0, `rgba(${colorPos},${(0.15 + intensity * 0.5) * avgAlpha})`);
      lineGrad.addColorStop(1, `rgba(${colorPos},${(0.08 + intensity * 0.35) * avgAlpha})`);
      ctx.strokeStyle = lineGrad;
      ctx.lineWidth = 0.8 + intensity * 2.5;

      // 发光效果 (强边)
      if (intensity > 0.5) {
        ctx.shadowBlur = 6 + intensity * 8;
        ctx.shadowColor = `rgba(${colorPos},0.6)`;
      } else {
        ctx.shadowBlur = 0;
      }
      ctx.beginPath();
      ctx.moveTo(pa.x, pa.y);
      ctx.lineTo(pb.x, pb.y);
      ctx.stroke();
      ctx.shadowBlur = 0;

      // 方向箭头 (70% 位置, 仅强边)
      if (intensity > 0.25 && avgAlpha > 0.5) {
        const arrowPos = 0.62;
        const ax = pa.x + (pb.x - pa.x) * arrowPos;
        const ay = pa.y + (pb.y - pa.y) * arrowPos;
        const angle = Math.atan2(pb.y - pa.y, pb.x - pa.x);
        const arrowSize = 4 + intensity * 5;
        ctx.fillStyle = `rgba(${colorPos},${0.6 + intensity * 0.3})`;
        ctx.beginPath();
        ctx.moveTo(ax + Math.cos(angle) * arrowSize, ay + Math.sin(angle) * arrowSize);
        ctx.lineTo(ax + Math.cos(angle + 2.5) * arrowSize * 0.7, ay + Math.sin(angle + 2.5) * arrowSize * 0.7);
        ctx.lineTo(ax + Math.cos(angle - 2.5) * arrowSize * 0.7, ay + Math.sin(angle - 2.5) * arrowSize * 0.7);
        ctx.closePath();
        ctx.fill();
      }

      // strength 数值标签 (中点, 仅强边且近)
      if (intensity > 0.35 && avgAlpha > 0.6) {
        const mx = (pa.x + pb.x) / 2;
        const my = (pa.y + pb.y) / 2;
        const label = e.strength.toFixed(2);
        ctx.font = '9px monospace';
        const tw = ctx.measureText(label).width;
        // 背景药丸
        ctx.fillStyle = `rgba(10,16,24,${0.7 * avgAlpha})`;
        ctx.fillRect(mx - tw / 2 - 3, my - 7, tw + 6, 12);
        ctx.fillStyle = `rgba(${colorPos},${0.85 * avgAlpha})`;
        ctx.fillText(label, mx - tw / 2, my + 2);
      }
    });

    // ── 画节点: 径向渐变 + 发光 + 完整标签 ───────────────────
    projected.forEach(p => {
      const radius = p.node.radius * Math.max(0.4, p.scale * 0.012);
      const alpha = Math.max(0.35, Math.min(1, (p.z + 300) / 500));

      // 外发光
      if (alpha > 0.5) {
        ctx.shadowBlur = 8 + radius;
        ctx.shadowColor = `rgba(0,217,163,${alpha * 0.5})`;
      }
      // 径向渐变填充
      const nodeGrad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, radius);
      nodeGrad.addColorStop(0, `rgba(120,255,200,${alpha})`);
      nodeGrad.addColorStop(0.6, `rgba(0,217,163,${alpha * 0.8})`);
      nodeGrad.addColorStop(1, `rgba(0,180,135,${alpha * 0.3})`);
      ctx.fillStyle = nodeGrad;
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      // 边框
      ctx.strokeStyle = `rgba(255,255,255,${alpha * 0.45})`;
      ctx.lineWidth = 0.8;
      ctx.stroke();

      // 完整概念名标签 (带背景药丸, 近节点)
      if (alpha > 0.55) {
        const label = p.node.id;
        const fontSize = Math.max(10, Math.min(13, 11 * p.scale * 0.012));
        ctx.font = `${fontSize}px var(--font-mono, monospace)`;
        const tw = ctx.measureText(label).width;
        const labelX = p.x + radius + 4;
        const labelY = p.y - fontSize / 2;
        // 背景药丸
        ctx.fillStyle = `rgba(10,16,24,${0.65 * alpha})`;
        ctx.fillRect(labelX - 2, labelY - 1, tw + 6, fontSize + 4);
        ctx.strokeStyle = `rgba(102,252,241,${0.2 * alpha})`;
        ctx.lineWidth = 0.5;
        ctx.strokeRect(labelX - 2, labelY - 1, tw + 6, fontSize + 4);
        // 文字
        ctx.fillStyle = `rgba(210,230,245,${alpha})`;
        ctx.fillText(label, labelX + 1, labelY + fontSize);
      }
    });

    // ── HUD: 信息看板 ────────────────────────────────────────
    // 半透明背景条
    ctx.fillStyle = 'rgba(5,10,16,0.75)';
    ctx.fillRect(0, h - 24, w, 24);
    ctx.fillStyle = 'rgba(148,163,184,0.7)';
    ctx.font = '10px monospace';
    ctx.fillText(`◈ 3D CAUSAL TOPOLOGY · nodes=${s.nodes.length} edges=${s.edges.length} · drag=rotate · wheel=zoom`, 8, h - 8);
    // 节点截断提示
    if (s.truncated) {
      ctx.fillStyle = 'rgba(251,191,36,0.9)';
      ctx.font = '10px monospace';
      ctx.fillText(`⚠ 已显示前 32 个节点 (共 ${s.totalConcepts} 个)`, 8, h - 36);
    }
    // 图例
    const legendX = w - 130;
    const legendY = 12;
    ctx.fillStyle = 'rgba(5,10,16,0.6)';
    ctx.fillRect(legendX - 6, legendY - 4, 125, 38);
    ctx.font = '9px monospace';
    ctx.fillStyle = 'rgba(102,252,241,0.8)';
    ctx.fillText('━━ 正因果 (ΔNLL>0)', legendX, legendY + 8);
    ctx.fillStyle = 'rgba(255,100,100,0.8)';
    ctx.fillText('━━ 负因果 (ΔNLL<0)', legendX, legendY + 20);
    ctx.fillStyle = 'rgba(0,217,163,0.8)';
    ctx.fillText('● 概念节点 (大小=频次)', legendX, legendY + 32);
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

// P0 升级 (2026-07-29): 3D 拓扑点击节点后坍缩为 2D 力导向网络图谱
// 支持：力导向布局、节点拖拽、滚轮缩放、空白处拖拽平移、点击高亮邻居。
const topology2DStates = new Map();

function initPositions2D(nodes, edges, W, H) {
  const n = nodes.length;
  W = Math.max(1, Number(W) || 1);
  H = Math.max(1, Number(H) || 1);
  const radius = Math.min(W, H) * 0.35;
  nodes.forEach((node, i) => {
    const angle = (i / Math.max(n, 1)) * Math.PI * 2 + Math.random() * 0.2;
    node.x = W / 2 + radius * Math.cos(angle);
    node.y = H / 2 + radius * Math.sin(angle);
    node.vx = 0; node.vy = 0;
    node.radius = 5 + Math.sqrt(node.freq || 1) * 2.2;
  });
  // 力导向稳定化（使用与 step() 一致的温和系数，避免数值爆炸）
  const k = Math.sqrt((W * H) / Math.max(n, 1)) * 0.9;
  const maxCoord = Math.max(W, H) * 4; // 软边界，防止溢出
  for (let iter = 0; iter < 300; iter++) {
    // 斥力
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let dist = Math.sqrt(dx * dx + dy * dy);
        if (!Number.isFinite(dist) || dist < 0.5) dist = 0.5;
        const force = (k * k) / (dist * dist + 10) * 0.02;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
    }
    // 引力（边）
    edges.forEach(e => {
      const a = e.source, b = e.target;
      let dx = b.x - a.x, dy = b.y - a.y;
      let dist = Math.sqrt(dx * dx + dy * dy);
      if (!Number.isFinite(dist) || dist < 0.5) dist = 0.5;
      const targetLen = 70 + 80 / (Math.abs(e.strength) + 0.5);
      const force = (dist - targetLen) * 0.0008;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    });
    // 中心引力 + 速度阻尼 + 软边界
    nodes.forEach(node => {
      node.vx += (W / 2 - node.x) * 0.0005;
      node.vy += (H / 2 - node.y) * 0.0005;
      node.vx *= 0.92;
      node.vy *= 0.92;
      node.x += node.vx;
      node.y += node.vy;
      if (!Number.isFinite(node.x) || Math.abs(node.x) > maxCoord) node.x = W / 2;
      if (!Number.isFinite(node.y) || Math.abs(node.y) > maxCoord) node.y = H / 2;
    });
  }
  nodes.forEach(node => { node.vx = 0; node.vy = 0; });
}

function renderTopology2D(r, wrap, canvas, focusedNodeId = null) {
  if (!wrap || !canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;

  function resize() {
    const rect = wrap.getBoundingClientRect();
    const W = Math.max(1, Math.floor(rect.width));
    const H = Math.max(1, Math.floor(rect.height));
    canvas.width = Math.floor(W * dpr);
    canvas.height = Math.floor(H * dpr);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { W, H };
  }

  function init2D(W, H) {
  const allConcepts = (r.concepts || []).slice(0, 64);
  const freq = r.concept_frequencies || {};
  if (allConcepts.length < 2) {
    ctx.fillStyle = '#94a3b8';
    ctx.font = '13px monospace';
    ctx.fillText('概念数不足 (需≥2)', 12, H / 2);
    return;
  }

  const nodes = allConcepts.map((c, i) => ({ id: c, index: i, freq: freq[c] || 1 }));
  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const edges = [];
  const matrix = r.adjacency_matrix;
  if (matrix && matrix.length === allConcepts.length) {
    for (let i = 0; i < allConcepts.length; i++) {
      for (let j = 0; j < allConcepts.length; j++) {
        if (i === j) continue;
        const v = Number(matrix[i][j]);
        if (!isNaN(v) && Math.abs(v) > 0.01) {
          edges.push({ source: nodes[i], target: nodes[j], strength: v });
        }
      }
    }
  }
  if (edges.length === 0 && r.top_edges) {
    r.top_edges.forEach(e => {
      const s = nodeMap.get(e.source);
      const t = nodeMap.get(e.target);
      if (s && t) edges.push({ source: s, target: t, strength: e.strength });
    });
  }

  initPositions2D(nodes, edges, W, H);

  const existing = topology2DStates.get(canvas);
  if (existing && existing.rafId) cancelAnimationFrame(existing.rafId);

  const state = {
    rafId: null, nodes, edges, nodeMap, W, H, wrap, canvas, ctx, dpr,
    scale: 1.0, panX: 0, panY: 0,
    draggingNode: null, draggingCanvas: false, lastX: 0, lastY: 0,
    focusedNodeId,
    hoveredNode: null,
    alpha: 0 // 用于入场动画
  };
  topology2DStates.set(canvas, state);

  function step() {
    const s = topology2DStates.get(canvas);
    if (!s) return;
    // 温和力导向持续运行，保持动态稳定
    const k = Math.sqrt((s.W * s.H) / Math.max(s.nodes.length, 1)) * 0.9;
    for (let i = 0; i < s.nodes.length; i++) {
      for (let j = i + 1; j < s.nodes.length; j++) {
        const a = s.nodes[i], b = s.nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let dist = Math.sqrt(dx * dx + dy * dy);
        if (!Number.isFinite(dist) || dist < 0.5) dist = 0.5;
        const force = (k * k) / (dist * dist + 10) * 0.02;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
    }
    s.edges.forEach(e => {
      const a = e.source, b = e.target;
      let dx = b.x - a.x, dy = b.y - a.y;
      let dist = Math.sqrt(dx * dx + dy * dy);
      if (!Number.isFinite(dist) || dist < 0.5) dist = 0.5;
      const targetLen = 70 + 80 / (Math.abs(e.strength) + 0.5);
      const force = (dist - targetLen) * 0.0008;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    });
    s.nodes.forEach(node => {
      if (node === s.draggingNode) return;
      node.vx += (s.W / 2 - node.x) * 0.0005;
      node.vy += (s.H / 2 - node.y) * 0.0005;
      node.vx *= 0.92;
      node.vy *= 0.92;
      node.x += node.vx;
      node.y += node.vy;
    });
  }

  function toScreen(x, y) {
    const s = topology2DStates.get(canvas);
    return { x: s.W / 2 + (x - s.W / 2 + s.panX) * s.scale, y: s.H / 2 + (y - s.H / 2 + s.panY) * s.scale };
  }
  function fromScreen(sx, sy) {
    const s = topology2DStates.get(canvas);
    return { x: (sx - s.W / 2) / s.scale + s.W / 2 - s.panX, y: (sy - s.H / 2) / s.scale + s.H / 2 - s.panY };
  }

  function draw() {
    const s = topology2DStates.get(canvas);
    if (!s) return;
    const { W: w, H: h } = s;
    ctx.fillStyle = '#05070a';
    ctx.fillRect(0, 0, w, h);

    // 背景网格
    ctx.strokeStyle = 'rgba(102,252,241,0.04)';
    ctx.lineWidth = 1;
    for (let x = 0; x < w; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
    for (let y = 0; y < h; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }

    const maxStr = Math.max(...s.edges.map(x => Math.abs(x.strength)), 1e-6);
    const focused = (s.focusedNodeId && s.nodeMap) ? s.nodeMap.get(s.focusedNodeId) : null;
    const neighborSet = new Set();
    if (focused) {
      neighborSet.add(focused.id);
      s.edges.forEach(e => {
        if (e.source === focused) neighborSet.add(e.target.id);
        if (e.target === focused) neighborSet.add(e.source.id);
      });
    }

    // 边
    s.edges.forEach(e => {
      const a = toScreen(e.source.x, e.source.y);
      const b = toScreen(e.target.x, e.target.y);
      const intensity = Math.min(Math.abs(e.strength) / maxStr, 1);
      const isDimmed = focused && !(neighborSet.has(e.source.id) && neighborSet.has(e.target.id));
      const colorPos = e.strength > 0 ? '102,252,241' : '255,100,100';
      ctx.strokeStyle = `rgba(${colorPos},${isDimmed ? 0.1 : (0.25 + intensity * 0.55)})`;
      ctx.lineWidth = (0.8 + intensity * 2.5) * s.scale;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      // 箭头
      if (!isDimmed && intensity > 0.15) {
        const angle = Math.atan2(b.y - a.y, b.x - a.x);
        const arrowSize = (4 + intensity * 5) * s.scale;
        const t = 0.55;
        const ax = a.x + (b.x - a.x) * t;
        const ay = a.y + (b.y - a.y) * t;
        ctx.fillStyle = `rgba(${colorPos},${0.6 + intensity * 0.3})`;
        ctx.beginPath();
        ctx.moveTo(ax + Math.cos(angle) * arrowSize, ay + Math.sin(angle) * arrowSize);
        ctx.lineTo(ax + Math.cos(angle + 2.5) * arrowSize * 0.7, ay + Math.sin(angle + 2.5) * arrowSize * 0.7);
        ctx.lineTo(ax + Math.cos(angle - 2.5) * arrowSize * 0.7, ay + Math.sin(angle - 2.5) * arrowSize * 0.7);
        ctx.closePath(); ctx.fill();
      }
    });

    // 节点
    s.nodes.forEach(node => {
      const p = toScreen(node.x, node.y);
      const isFocused = focused && focused.id === node.id;
      const isNeighbor = focused && neighborSet.has(node.id) && focused.id !== node.id;
      const isDimmed = focused && !neighborSet.has(node.id);
      const baseRadius = Number(node.radius) || 6;
      const radius = baseRadius * s.scale * (isFocused ? 1.3 : 1.0);

      // 防御性检查：避免 NaN/Infinity 导致 createRadialGradient 报错
      if (!Number.isFinite(p.x) || !Number.isFinite(p.y) || !Number.isFinite(radius) || radius <= 0) return;

      ctx.shadowBlur = isFocused ? 20 : (isNeighbor ? 12 : 6);
      ctx.shadowColor = isFocused ? 'rgba(255,159,67,0.7)' : (isNeighbor ? 'rgba(0,217,163,0.5)' : 'rgba(0,217,163,0.3)');
      const nodeGrad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, radius);
      nodeGrad.addColorStop(0, isFocused ? 'rgba(255,200,120,1)' : (isNeighbor ? 'rgba(120,255,200,0.95)' : 'rgba(120,255,200,0.8)'));
      nodeGrad.addColorStop(1, isFocused ? 'rgba(255,159,67,0.5)' : (isNeighbor ? 'rgba(0,217,163,0.55)' : 'rgba(0,180,135,0.25)'));
      ctx.globalAlpha = isDimmed ? 0.25 : 1.0;
      ctx.fillStyle = nodeGrad;
      ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = isFocused ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,0.4)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.shadowBlur = 0;

      // 标签
      ctx.font = `${Math.max(10, 11 * s.scale)}px var(--font-mono, monospace)`;
      const tw = ctx.measureText(node.id).width;
      const labelBg = isFocused ? 'rgba(255,159,67,0.15)' : 'rgba(10,16,24,0.7)';
      ctx.fillStyle = labelBg;
      ctx.fillRect(p.x + radius + 3, p.y - 7, tw + 5, 14);
      ctx.fillStyle = isFocused ? 'rgba(255,220,160,1)' : 'rgba(210,230,245,0.9)';
      ctx.fillText(node.id, p.x + radius + 5, p.y + 3);
      ctx.globalAlpha = 1.0;
    });

    // HUD
    ctx.fillStyle = 'rgba(5,10,16,0.75)';
    ctx.fillRect(0, h - 24, w, 24);
    ctx.fillStyle = 'rgba(148,163,184,0.7)';
    ctx.font = '10px monospace';
    const focusText = focused ? ` · 聚焦: ${focused.id}` : '';
    ctx.fillText(`◈ 2D CAUSAL NETWORK · nodes=${s.nodes.length} edges=${s.edges.length}${focusText} · drag=移动节点 · wheel=缩放`, 8, h - 8);
  }

  function animate() {
    const s = topology2DStates.get(canvas);
    if (!s) return;
    step();
    if (s.alpha < 1) s.alpha += 0.05;
    draw();
    s.rafId = requestAnimationFrame(animate);
  }

  // 事件绑定
  if (!canvas._topo2DBound) {
    canvas._topo2DBound = true;
    canvas.addEventListener('mousedown', e => {
      const s = topology2DStates.get(canvas);
      if (!s) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const world = fromScreen(mx, my);
      // 查找最近节点
      let nearest = null, minD = Infinity;
      s.nodes.forEach(node => {
        const dx = node.x - world.x, dy = node.y - world.y;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < node.radius + 8 && d < minD) { minD = d; nearest = node; }
      });
      if (nearest) {
        s.draggingNode = nearest;
      } else {
        s.draggingCanvas = true;
        s.lastX = mx; s.lastY = my;
      }
    });
    canvas.addEventListener('mousemove', e => {
      const s = topology2DStates.get(canvas);
      if (!s) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const world = fromScreen(mx, my);
      if (s.draggingNode) {
        s.draggingNode.x = world.x;
        s.draggingNode.y = world.y;
        s.draggingNode.vx = 0; s.draggingNode.vy = 0;
      } else if (s.draggingCanvas) {
        s.panX += (mx - s.lastX) / s.scale;
        s.panY += (my - s.lastY) / s.scale;
        s.lastX = mx; s.lastY = my;
      }
      // hover
      let nearest = null, minD = Infinity;
      s.nodes.forEach(node => {
        const dx = node.x - world.x, dy = node.y - world.y;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < node.radius + 8 && d < minD) { minD = d; nearest = node; }
      });
      s.hoveredNode = nearest;
      canvas.style.cursor = nearest ? 'pointer' : (s.draggingCanvas ? 'grabbing' : 'default');
    });
    window.addEventListener('mouseup', () => {
      const s = topology2DStates.get(canvas);
      if (s) { s.draggingNode = null; s.draggingCanvas = false; }
    });
    canvas.addEventListener('click', e => {
      const s = topology2DStates.get(canvas);
      if (!s) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const world = fromScreen(mx, my);
      let nearest = null, minD = Infinity;
      s.nodes.forEach(node => {
        const dx = node.x - world.x, dy = node.y - world.y;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < node.radius + 8 && d < minD) { minD = d; nearest = node; }
      });
      if (nearest) {
        s.focusedNodeId = s.focusedNodeId === nearest.id ? null : nearest.id;
      }
    });
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const s = topology2DStates.get(canvas);
      if (!s) return;
      const factor = e.deltaY > 0 ? 0.9 : 1.1;
      s.scale *= factor;
      s.scale = Math.max(0.2, Math.min(5.0, s.scale));
    }, { passive: false });
  }

  if (!wrap._topo2DResizeObs) {
    const ro = new ResizeObserver(() => {
      const s = topology2DStates.get(canvas);
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
    wrap._topo2DResizeObs = ro;
  }

    animate();
  } // end init2D

  let { W, H } = resize();
  if (W < 50 || H < 50) {
    // 容器尚未完成布局，延迟一帧重试
    requestAnimationFrame(() => {
      const { W: W2, H: H2 } = resize();
      if (W2 >= 50 && H2 >= 50) init2D(W2, H2);
    });
  } else {
    init2D(W, H);
  }
}
window.renderTopology2D = renderTopology2D;

function setupTopologyToggle(r, opts) {
  const {
    matrixView, topologyView, topology2DView,
    wrap, canvas, wrap2D, canvas2D,
    toggleBtn, toggle2DBtn,
    pauseBtn, resetBtn, reset2DBtn
  } = opts;
  if (!toggleBtn || !matrixView || !topologyView) return;

  // 视图状态: 'matrix' | '3d' | '2d'
  let viewState = 'matrix';
  topologyView.classList.add('hidden');
  if (topology2DView) topology2DView.classList.add('hidden');
  matrixView.classList.remove('hidden');
  toggleBtn.textContent = '3D 拓扑';
  if (toggle2DBtn) {
    toggle2DBtn.classList.remove('hidden');
    toggle2DBtn.textContent = '2D 网络';
  }

  function showView(state, focusedNodeId = null) {
    viewState = state;
    if (state === 'matrix') {
      matrixView.classList.remove('hidden');
      topologyView.classList.add('hidden');
      if (topology2DView) topology2DView.classList.add('hidden');
      toggleBtn.textContent = '3D 拓扑';
      if (toggle2DBtn) toggle2DBtn.textContent = '2D 网络';
      const s = topologyStates.get(canvas);
      if (s) s.paused = true;
      const s2 = topology2DStates.get(canvas2D);
      if (s2 && s2.rafId) { cancelAnimationFrame(s2.rafId); s2.rafId = null; }
    } else if (state === '3d') {
      matrixView.classList.add('hidden');
      topologyView.classList.remove('hidden');
      if (topology2DView) topology2DView.classList.add('hidden');
      toggleBtn.textContent = '2D 矩阵';
      if (toggle2DBtn) toggle2DBtn.textContent = '2D 网络';
      const s = topologyStates.get(canvas);
      const s2 = topology2DStates.get(canvas2D);
      if (s2 && s2.rafId) { cancelAnimationFrame(s2.rafId); s2.rafId = null; }
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
    } else if (state === '2d') {
      matrixView.classList.add('hidden');
      topologyView.classList.add('hidden');
      if (topology2DView) topology2DView.classList.remove('hidden');
      toggleBtn.textContent = '3D 拓扑';
      if (toggle2DBtn) toggle2DBtn.textContent = '2D 矩阵';
      const s = topologyStates.get(canvas);
      if (s) s.paused = true;
      renderTopology2D(r, wrap2D, canvas2D, focusedNodeId);
    }
  }

  if (!toggleBtn._topoToggleBound) {
    toggleBtn._topoToggleBound = true;
    toggleBtn.addEventListener('click', () => {
      if (viewState === 'matrix') showView('3d');
      else if (viewState === '3d') showView('matrix');
      else if (viewState === '2d') showView('3d');
    });
  }
  if (toggle2DBtn && !toggle2DBtn._topo2DToggleBound) {
    toggle2DBtn._topo2DToggleBound = true;
    toggle2DBtn.addEventListener('click', () => {
      if (viewState === 'matrix') showView('2d');
      else if (viewState === '2d') showView('matrix');
      else if (viewState === '3d') showView('2d');
    });
  }
  if (reset2DBtn && !reset2DBtn._topo2DResetBound) {
    reset2DBtn._topo2DResetBound = true;
    reset2DBtn.addEventListener('click', () => {
      const s2 = topology2DStates.get(canvas2D);
      if (s2) {
        s2.scale = 1.0; s2.panX = 0; s2.panY = 0; s2.focusedNodeId = null;
        initPositions2D(s2.nodes, s2.edges, s2.W, s2.H);
      }
    });
  }

  // P0 升级: 3D 拓扑点击节点 → 坍缩到 2D 网络并聚焦该节点
  if (canvas && !canvas._topo3DClickBound) {
    canvas._topo3DClickBound = true;
    canvas.addEventListener('click', e => {
      const s = topologyStates.get(canvas);
      if (!s || viewState !== '3d') return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const dpr = s.dpr;
      // 找到投影后离鼠标最近的节点
      let nearest = null, minZ = -Infinity, minD = Infinity;
      const projected = s.nodes.map(n => ({ node: n, ...project(n, s.rotX, s.rotY, s.zoom, s.W, s.H) }));
      projected.forEach(p => {
        const dx = p.x - mx, dy = p.y - my;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < Math.max(12, p.node.radius * Math.max(0.4, p.scale * 0.012)) + 6) {
          // 优先选 z 更近（排序后更前面）的节点
          if (nearest === null || p.z > minZ || (p.z === minZ && d < minD)) {
            nearest = p.node; minZ = p.z; minD = d;
          }
        }
      });
      if (nearest) {
        showView('2d', nearest.id);
      }
    });
  }
}
window.setupTopologyToggle = setupTopologyToggle;
