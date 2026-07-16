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
const LOG_LEVELS = ['stage', 'info', 'warn', 'error', 'stderr'];
const LOG_ICONS = { stage: '▶', info: '◉', warn: '▲', error: '✖', stderr: '⚠' };
const MAX_LOG_LINES = 400;
let activeLogLevels = new Set(LOG_LEVELS);
let logAutoScroll = true;

// ── 共享纯工具函数 ────────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (m) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[m]));
}

// 安全数值格式化：null/undefined/NaN 等非数值返回 'N/A'，避免 toFixed 崩溃
const safeFmt = (v, n = 4) => (v != null && typeof v === 'number' && !isNaN(v)) ? v.toFixed(n) : 'N/A';

function showToast(msg, type) {
  if (!toast) return;
  toast.textContent = msg;
  toast.className = 'toast ' + (type || 'hidden');
  toast.style.display = type ? 'block' : 'none';
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

  document.getElementById('mConcepts').textContent = r.concepts ? r.concepts.length : '-';
  document.getElementById('mEdges').textContent = r.n_significant_edges ?? '-';
  document.getElementById('mATE').textContent = safeFmt(r.ate, 4);
  document.getElementById('mCI').textContent = r.confidence_interval
    ? `[${safeFmt(r.confidence_interval[0], 2)}, ${safeFmt(r.confidence_interval[1], 2)}]`
    : '-';
  document.getElementById('mIdentifiable').textContent = r.identifiable ? 'YES' : 'NO';
  document.getElementById('mIdentifiable').style.color = r.identifiable ? 'var(--success)' : 'var(--fail)';
  document.getElementById('mRefuted').textContent = r.refutations
    ? `${r.refutations.filter(x => x.refuted).length}/${r.refutations.length}`
    : '-';
  document.getElementById('mMode').textContent = (r.analysis_mode || 'light').toUpperCase();
  document.getElementById('mDuration').textContent = r.execution_profile && r.execution_profile.total_ms != null
    ? `${safeFmt(r.execution_profile.total_ms / 1000, 2)}s`
    : '-';

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
  const kpiHtml = Object.entries(diag).map(([k, v]) => {
    let display = v;
    if (typeof v === 'number') display = Number.isInteger(v) ? v : v.toFixed(4);
    return `<span class="kpi-pill"><span class="k">${k}:</span>${escapeHtml(String(display))}</span>`;
  }).join('');
  dataDiagnostics.innerHTML = `<div class="kpi-row">${kpiHtml || '<span class="kpi-pill">无诊断数据</span>'}</div>`;

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

  // Adjacency matrix heatmap
  const adjMatrixWrap = document.getElementById('adjMatrixWrap');
  adjMatrixWrap.innerHTML = '';
  const concepts = r.concepts || [];
  const matrix = r.adjacency_matrix;
  if (matrix && matrix.length > 0 && concepts.length > 0) {
    const n = concepts.length;
    const grid = document.createElement('div');
    grid.className = 'adj-matrix';
    grid.style.gridTemplateColumns = `repeat(${n + 1}, minmax(28px, 1fr))`;
    const maxVal = Math.max(...matrix.flat().map(v => Math.abs(v)), 1e-9);
    // header row
    grid.appendChild(document.createElement('div'));
    concepts.forEach(c => {
      const label = document.createElement('div');
      label.className = 'adj-label';
      label.textContent = c.length > 4 ? c.slice(0, 3) + '…' : c;
      label.title = c;
      grid.appendChild(label);
    });
    matrix.forEach((row, i) => {
      const rowLabel = document.createElement('div');
      rowLabel.className = 'adj-label';
      rowLabel.textContent = concepts[i].length > 4 ? concepts[i].slice(0, 3) + '…' : concepts[i];
      rowLabel.title = concepts[i];
      grid.appendChild(rowLabel);
      row.forEach((v, j) => {
        const cell = document.createElement('div');
        cell.className = 'adj-cell';
        const intensity = Math.min(Math.abs(v) / maxVal, 1);
        cell.style.background = i === j ? 'var(--panel-3)'
          : `rgba(102, 252, 241, ${0.08 + intensity * 0.72})`;
        cell.style.color = intensity > 0.5 ? '#000' : 'var(--text)';
        cell.title = `${concepts[i]} → ${concepts[j]}: ${safeFmt(Number(v), 2)}`;
        cell.textContent = v !== 0 ? safeFmt(Number(v), 1) : '';
        grid.appendChild(cell);
      });
    });
    adjMatrixWrap.appendChild(grid);
    const legend = document.createElement('div');
    legend.className = 'adj-legend';
    legend.innerHTML = `<span>0</span><div class="adj-legend-bar"></div><span>${maxVal.toFixed(1)}</span>`;
    adjMatrixWrap.appendChild(legend);
  } else {
    adjMatrixWrap.innerHTML = '<div class="empty-state">无邻接矩阵数据</div>';
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
    const safeWarriorId = escapeHtml(card.warrior_id);
    const safeName = escapeHtml(card.name);
    const safeStatus = escapeHtml(card.status);
    div.innerHTML = `
      <div class="warrior-title">${safeWarriorId} · ${safeName} <span class="warrior-status ${safeStatus}">${safeStatus}</span></div>
      <div class="warrior-metrics">${escapeHtml(metrics)}</div>
      ${findings}
      <div class="warrior-verdict">// ${escapeHtml(card.verdict || 'N/A')}</div>
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
