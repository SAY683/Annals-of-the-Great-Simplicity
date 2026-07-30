/* TRACE Engine Web — 任务历史管理（debt-09）
 * ===========================================
 * 抽取自原 index.html 内联 <script>。
 *
 * 依赖（运行时由 app.js / render.js 提供）：
 *   - log(level, message)         由 render.js 提供
 *   - showToast(msg, type)        由 render.js 提供
 *   - escapeHtml(str)             由 render.js 提供
 *   - jobHistoryTerminal (DOM)    由 app.js 提供
 */

async function loadJobHistory() {
  try {
    const res = await fetch('/api/jobs');
    const data = await res.json();
    if (!data.success) return;
    jobHistoryTerminal.innerHTML = '';

    // P1-c：批量选择工具栏
    const batchToolbar = document.createElement('div');
    batchToolbar.className = 'batch-toolbar';
    batchToolbar.style.cssText = 'display:flex;align-items:center;gap:6px;padding:2px 6px;border-bottom:1px solid var(--border,rgba(255,255,255,0.1));margin-bottom:2px;font-size:clamp(0.6rem,0.82vw,0.7rem);';

    const selectAllCb = document.createElement('input');
    selectAllCb.type = 'checkbox';
    selectAllCb.id = 'selectAllJobs';
    selectAllCb.style.cssText = 'accent-color:var(--accent,#00ff88);';
    selectAllCb.title = '全选/取消全选';

    const selectAllLabel = document.createElement('label');
    selectAllLabel.htmlFor = 'selectAllJobs';
    selectAllLabel.textContent = '全选';
    selectAllLabel.style.cssText = 'cursor:pointer;opacity:0.7;';

    const batchDeleteBtn = document.createElement('button');
    batchDeleteBtn.className = 'btn-mini secondary';
    batchDeleteBtn.textContent = '批量删除';
    batchDeleteBtn.style.cssText = 'display:none;margin-left:auto;';
    batchDeleteBtn.onclick = batchDeleteJobs;

    const selectedCount = document.createElement('span');
    selectedCount.className = 'selected-count';
    selectedCount.style.cssText = 'margin-left:auto;opacity:0.6;display:none;';

    batchToolbar.appendChild(selectAllCb);
    batchToolbar.appendChild(selectAllLabel);
    batchToolbar.appendChild(selectedCount);
    batchToolbar.appendChild(batchDeleteBtn);

    const historyRows = [];  // 用于全选/批量操作

    const addLine = (html) => {
      const div = document.createElement('div');
      div.className = 'terminal-line';
      div.innerHTML = html;
      jobHistoryTerminal.appendChild(div);
      return div;
    };

    if (data.active && data.active.length > 0) {
      addLine(`ACTIVE: ${data.active.length} job(s)`);
      data.active.forEach(id => addLine(`  ${id.slice(0, 8)}... running`));
    }

    if (data.history && data.history.length > 0) {
      // 添加批量工具栏（仅在有历史记录时显示）
      jobHistoryTerminal.appendChild(batchToolbar);
      addLine(`HISTORY (last ${data.history.length}):`);

      [...data.history].reverse().forEach(j => {
        const ts = new Date(j.createdAt).toLocaleTimeString('zh-CN', { hour12: false });
        const mode = (j.mode || 'light').toUpperCase();
        const dur = j.durationMs != null ? ` ${(j.durationMs / 1000).toFixed(1)}s` : '';
        const errMark = j.error ? ' ⚠' : '';
        const retryable = ['error', 'timeout', 'cancelled'].includes(j.status) && j.mode !== 'super';
        const retryBtn = retryable
          ? ` <a href="#" class="retry-link" data-id="${j.id}" style="color:var(--accent);text-decoration:none;">[RETRY]</a>`
          : '';
        const deleteBtn = ` <a href="#" class="delete-link" data-id="${j.id}" style="color:var(--danger,#ff4444);text-decoration:none;margin-left:3px;">[DEL]</a>`;
        // 显式"详情"链接：提供独立可点击目标，避免与 checkbox/链接的点击区域冲突
        const detailBtn = ` <a href="#" class="detail-link" data-id="${j.id}" style="color:var(--accent-tokusatsu,#ff9f43);text-decoration:none;margin-left:3px;font-weight:600;">[详情]</a>`;
        // 截断 textPreview 至 200 字符作为摘要（任务详情模态框入口提示）
        const previewRaw = j.textPreview || '';
        const preview = previewRaw.length > 200 ? previewRaw.slice(0, 200) + '…' : previewRaw;
        // P0 修复 (2026-07-29): preview 不再使用内联样式，完全由 CSS 控制，
        // 避免 inline style 覆盖 .terminal-line.job-card .job-preview 的 flex/width/margin。
        const previewHtml = preview
          ? `<div class="job-preview">${escapeHtml(preview)}</div>`
          : '';

        const row = addLine(
          `<div class="job-card-row">` +
          `<input type="checkbox" class="job-cb" data-id="${j.id}">` +
          `<span class="job-meta">[${ts}] ${j.id.slice(0, 8)}… ${mode} ${j.status}${dur}${errMark}</span>` +
          `<span class="job-actions">${retryBtn}${deleteBtn}${detailBtn}</span>` +
          `</div>` +
          previewHtml
        );
        // 改造为可点击卡片：cursor:pointer + hover 高亮，点击触发详情模态框
        row.classList.add('job-card');
        row.style.cursor = 'pointer';
        row.addEventListener('click', (e) => {
          // 点击 checkbox / RETRY / DEL / 详情 链接时不触发卡片级详情（保留各自功能）
          if (e.target.closest('.job-cb, .retry-link, .delete-link, .detail-link')) return;
          viewJobDetail(j.id);
        });
        historyRows.push({ id: j.id, row });
      });

      jobHistoryTerminal.querySelectorAll('.retry-link').forEach(link => {
        link.addEventListener('click', (e) => {
          e.preventDefault();
          retryJob(link.dataset.id);
        });
      });
      jobHistoryTerminal.querySelectorAll('.delete-link').forEach(link => {
        link.addEventListener('click', (e) => {
          e.preventDefault();
          deleteSingleJob(link.dataset.id);
        });
      });
      jobHistoryTerminal.querySelectorAll('.detail-link').forEach(link => {
        link.addEventListener('click', (e) => {
          e.preventDefault();
          viewJobDetail(link.dataset.id);
        });
      });

      // 全选逻辑（三态）
      const jobCheckboxes = () => jobHistoryTerminal.querySelectorAll('.job-cb');
      selectAllCb.addEventListener('change', () => {
        const cbs = jobCheckboxes();
        cbs.forEach(cb => { cb.checked = selectAllCb.checked; });
        updateBatchUI();
      });
      jobHistoryTerminal.addEventListener('change', (e) => {
        if (e.target.classList.contains('job-cb')) {
          updateBatchUI();
        }
      });

      function updateBatchUI() {
        const cbs = Array.from(jobCheckboxes());
        const checked = cbs.filter(cb => cb.checked);
        if (cbs.length > 0) {
          selectAllCb.indeterminate = checked.length > 0 && checked.length < cbs.length;
          selectAllCb.checked = checked.length === cbs.length;
        }
        if (checked.length > 0) {
          batchDeleteBtn.style.display = 'inline-block';
          selectedCount.style.display = 'inline';
          selectedCount.textContent = `已选 ${checked.length} 项`;
        } else {
          batchDeleteBtn.style.display = 'none';
          selectedCount.style.display = 'none';
        }
      }
    } else {
      addLine('NO HISTORY');
    }
    jobHistoryTerminal.scrollTop = jobHistoryTerminal.scrollHeight;
  } catch (err) {
    jobHistoryTerminal.innerHTML = `<div class="terminal-line">加载任务历史失败: ${escapeHtml(err.message)}</div>`;
  }
}

// P1-c：批量删除任务
async function batchDeleteJobs() {
  const cbs = document.querySelectorAll('.job-cb:checked');
  const ids = Array.from(cbs).map(cb => cb.dataset.id);
  if (ids.length === 0) return;
  if (!confirm(`确定要删除选中的 ${ids.length} 条任务历史吗？`)) return;
  try {
    const res = await fetch('/api/jobs/batch-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    const data = await res.json();
    if (data.success) {
      log('info', `已删除 ${data.removed} 条任务历史${data.skipped ? '（' + data.skipped + '）' : ''}`);
      loadJobHistory();
    } else {
      showToast(data.error, 'error');
    }
  } catch (err) {
    showToast('批量删除失败: ' + err.message, 'error');
  }
}

// P1-c：删除单条任务
async function deleteSingleJob(id) {
  if (!confirm(`确定要删除任务 ${id.slice(0, 8)}… 的历史记录吗？`)) return;
  try {
    const res = await fetch(`/api/jobs/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      log('info', `已删除任务 ${id.slice(0, 8)}…`);
      loadJobHistory();
    } else {
      showToast(data.error, 'error');
    }
  } catch (err) {
    showToast('删除失败: ' + err.message, 'error');
  }
}

async function retryJob(id) {
  if (!confirm(`重试任务 ${id.slice(0, 8)}…？`)) return;
  try {
    log('info', `正在重试任务 ${id.slice(0, 8)}…`);
    const res = await fetch(`/api/retry/${id}`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      log('info', `重试成功，新任务 ID: ${data.newId.slice(0, 8)}…`);
      loadJobHistory();
    } else {
      showToast(data.error, 'error');
    }
  } catch (err) {
    showToast('重试失败: ' + err.message, 'error');
  }
}

async function exportJobs() {
  try {
    const res = await fetch('/api/jobs/export');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trace_jobs_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    log('info', '任务历史已导出');
  } catch (err) {
    showToast('导出失败: ' + err.message, 'error');
  }
}

async function clearJobs() {
  if (!confirm('确定要清空任务历史吗？此操作不可恢复。')) return;
  try {
    const res = await fetch('/api/jobs/clear', { method: 'POST' });
    const data = await res.json();
    log('info', data.message);
    loadJobHistory();
  } catch (err) {
    showToast('清空失败: ' + err.message, 'error');
  }
}

// ── 历史任务详情查看（点击 SECTOR-B2 历史项 → 弹出模态框） ────────────
// 调用 GET /api/jobs/:id/detail 聚合端点，一次性拉取 job 元数据 + 输入文本 + result.json + report.md
async function viewJobDetail(id) {
  const modal = document.getElementById('jobDetailModal');
  const title = document.getElementById('jobDetailTitle');
  const inputText = document.getElementById('jobDetailInputText');
  const resultData = document.getElementById('jobDetailResultData');
  const reportText = document.getElementById('jobDetailReportText');

  // 显示 loading 态
  title.textContent = `◉ 任务详情 ${id.slice(0, 8)}... (加载中)`;
  inputText.textContent = '加载中...';
  resultData.innerHTML = '<p class="detail-empty">加载中...</p>';
  reportText.textContent = '加载中...';
  modal.style.display = 'flex';

  // P2 (§20.12): 在标题区动态注入"📝人话版"导出按钮（每次打开时刷新 data-id）
  // 按钮固定在 modal-header 右侧（关闭按钮左侧），避免与原关闭按钮冲突
  let exportMdBtn = document.getElementById('jobDetailExportMd');
  if (!exportMdBtn) {
    exportMdBtn = document.createElement('button');
    exportMdBtn.id = 'jobDetailExportMd';
    exportMdBtn.className = 'btn-mini';
    exportMdBtn.style.cssText = 'margin-right:0.4rem;padding:0.25rem 0.6rem;font-size:0.72rem;background:rgba(0,255,136,0.08);border:1px solid var(--accent,#00ff88);color:var(--accent,#00ff88);';
    exportMdBtn.textContent = '📝 人话版';
    exportMdBtn.title = '在新标签页查看人话版 Markdown 报告';
    const closeBtn = document.getElementById('jobDetailClose');
    if (closeBtn && closeBtn.parentNode) {
      closeBtn.parentNode.insertBefore(exportMdBtn, closeBtn);
    }
    exportMdBtn.addEventListener('click', () => {
      const tid = exportMdBtn.dataset.taskId;
      if (!tid) return;
      // P2 fix (Round 24 §10): 改为新标签页直接查看, 不触发浏览器下载
      // report.md 已在 OUTPUT_DIR/<id>/report.md 落盘, export/md 端点返回 text/markdown
      window.open(`/api/jobs/${tid}/export/md`, '_blank');
      if (typeof log === 'function') log('info', `已在新标签页打开人话版报告: ${tid.slice(0, 8)}…`);
    });
  }
  exportMdBtn.dataset.taskId = id;

  try {
    const r = await fetch(`/api/jobs/${id}/detail`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    if (!d.success) throw new Error(d.error || 'unknown');

    const job = d.job || {};
    const diag = d.diagnostics || {};
    title.textContent = `◉ 任务 ${id.slice(0, 8)} | ${job.mode || '?'} | ${job.status || '?'}`;

    // P0 修缮：根据 diagnostics 区分"未落盘/读取出错/JSON 解析失败"
    // 不再把所有 null 误判为"已过 TTL 清理"
    // 输入文本
    if (d.inputText !== null && d.inputText !== undefined && d.inputText !== '') {
      inputText.textContent = d.inputText;
    } else if (diag.inputExists === false) {
      const ttlHint = diag.inputsTtlMs
        ? `TTL=${Math.round(diag.inputsTtlMs / 3600000)}h`
        : 'TTL=?';
      // R13-3 修缮：利用 job.inputPersisted 区分"写盘失败"vs"已被 TTL 清理"
      const persisted = job.inputPersisted;
      let cause;
      if (persisted === false) {
        cause = '写盘失败（recordJob 时 INPUTS_DIR 不可写或磁盘满）';
      } else if (persisted === true) {
        cause = `已被 TTL 清理 [${ttlHint}] 或手动删除`;
      } else {
        cause = `未落盘或已被清理 [${ttlHint}]（旧任务无 inputPersisted 标记）`;
      }
      inputText.textContent = `(输入文本不可用: ${cause})\n` +
        `  路径: ${diag.inputsDir || '?'}\\${id}.txt\n` +
        `  任务创建: ${diag.jobCreatedAt || '?'}  结束: ${diag.jobEndedAt || '?'}`;
    } else {
      inputText.textContent = `(输入文本读取失败: ${diag.inputReason || 'unknown'})\n  路径: ${diag.inputsDir || '?'}\\${id}.txt`;
    }

    // 结果数据
    if (d.result) {
      resultData.innerHTML = renderResultMetrics(d.result);
      // 绑定详情页 2D/3D 拓扑切换与 Canvas 渲染
      if (typeof setupTopologyToggle === 'function') {
        const detailMatrixView = document.getElementById('detailMatrixView');
        const detailTopologyView = document.getElementById('detailTopologyView');
        const detailTopologyWrap = document.getElementById('detailTopologyWrap');
        const detailTopologyCanvas = document.getElementById('detailTopologyCanvas');
        const detailTopology2DView = document.getElementById('detailTopology2DView');
        const detailTopology2DWrap = document.getElementById('detailTopology2DWrap');
        const detailTopology2DCanvas = document.getElementById('detailTopology2DCanvas');
        const detailTopoToggle = document.getElementById('detailTopoToggle');
        const detailTopo2DToggle = document.getElementById('detailTopo2DToggle');
        const detailTopoPauseBtn = document.getElementById('detailTopoPauseBtn');
        const detailTopoResetBtn = document.getElementById('detailTopoResetBtn');
        const detailTopo2DResetBtn = document.getElementById('detailTopo2DResetBtn');
        if (detailMatrixView && detailTopologyView) {
          setupTopologyToggle(d.result, {
            matrixView: detailMatrixView,
            topologyView: detailTopologyView,
            topology2DView: detailTopology2DView,
            wrap: detailTopologyWrap,
            canvas: detailTopologyCanvas,
            wrap2D: detailTopology2DWrap,
            canvas2D: detailTopology2DCanvas,
            toggleBtn: detailTopoToggle,
            toggle2DBtn: detailTopo2DToggle,
            pauseBtn: detailTopoPauseBtn,
            resetBtn: detailTopoResetBtn,
            reset2DBtn: detailTopo2DResetBtn
          });
        }
      }
    } else if (diag.resultExists === false) {
      const ttlHint = diag.outputTtlMs
        ? `TTL=${Math.round(diag.outputTtlMs / 3600000)}h`
        : 'TTL=?';
      resultData.innerHTML =
        `<p class="detail-empty">(result.json 未落盘或已被清理 [${ttlHint}])<br>` +
        `  路径: ${diag.outputDir || '?'}\\result.json<br>` +
        `  任务创建: ${diag.jobCreatedAt || '?'}  结束: ${diag.jobEndedAt || '?'}</p>`;
    } else if (diag.resultReason && diag.resultReason.startsWith('json_parse_failed')) {
      resultData.innerHTML =
        `<p class="detail-empty" style="color:var(--warn,#ffb000);">(result.json 存在但解析失败: ${diag.resultReason})<br>` +
        `  路径: ${diag.outputDir || '?'}\\result.json<br>` +
        `  建议: 检查 Python 写盘是否被中途截断</p>`;
    } else {
      resultData.innerHTML =
        `<p class="detail-empty">(result.json 读取失败: ${diag.resultReason || 'unknown'})<br>` +
        `  路径: ${diag.outputDir || '?'}\\result.json</p>`;
    }

    // 报告
    if (d.report !== null && d.report !== undefined && d.report !== '') {
      reportText.textContent = d.report;
    } else if (diag.reportExists === false) {
      const ttlHint = diag.outputTtlMs
        ? `TTL=${Math.round(diag.outputTtlMs / 3600000)}h`
        : 'TTL=?';
      reportText.textContent = `(report.md 未落盘或已被清理 [${ttlHint}])\n` +
        `  路径: ${diag.outputDir || '?'}\\report.md\n` +
        `  可能原因: Python 桥接未生成报告 / TTL 清理 / LIGHT 模式无报告`;
    } else {
      reportText.textContent = `(report.md 读取失败: ${diag.reportReason || 'unknown'})\n  路径: ${diag.outputDir || '?'}\\report.md`;
    }
  } catch (e) {
    title.textContent = `✗ 加载失败`;
    inputText.textContent = e.message;
    resultData.innerHTML = '';
    reportText.textContent = '';
  }
}

// 渲染 result.json 关键字段为 metric-grid 卡片 + 参数网格 + Top 边 + 反驳测试
// 复用 renderResult (render.js) 的字段映射逻辑，但返回 HTML 字符串而非直接操作 DOM
function renderResultMetrics(r) {
  if (!r) return '<p class="detail-empty">(无结果数据)</p>';

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
  // P2 修缮 (Round 23 §8): 历史任务也显示语义徽章, 与 render.js 保持一致
  // 区分 LIGHT(0/0 未测试) vs DEEP/SUPER(0/3 全通过)
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
  // P2 修缮 (Round 23 §8): signal_type 语义徽章 (区分共现计数 vs 真实ΔNLL)
  const diag = r.data_diagnostics || {};
  const signalType = diag.signal_type;
  let signalBadge = '';
  if (signalType === 'delta_nll') {
    signalBadge = '<span class="badge pass" title="SUPER模式真实ΔNLL">真实ΔNLL</span>';
  } else if (signalType === 'co_occurrence') {
    signalBadge = '<span class="badge warn" title="LIGHT/DEEP模式共现计数">共现计数</span>';
  }
  // P2 修缮 (Round 23 §8): CCM verdict 语义徽章
  const sixWarriors = r.six_warriors || {};
  const ccmCard = sixWarriors.ccm || {};
  const ccmVerdict = ccmCard.verdict;
  let ccmBadge = '';
  if (ccmVerdict === 'VERIFIABLE') {
    ccmBadge = '<span class="badge pass" title="真实CCM算法已运行">真CCM已验证</span>';
  } else if (ccmVerdict === 'ELIGIBLE_BUT_NOT_RUN') {
    ccmBadge = '<span class="badge warn" title="真算法可导入但未实际调用">启发式覆盖率</span>';
  } else if (ccmVerdict === 'HEURISTIC_FALLBACK') {
    ccmBadge = '<span class="badge warn" title="启发式回退, 非真实CCM">启发式回退</span>';
  } else if (ccmVerdict === 'NARRATIVE_TEXT') {
    ccmBadge = '<span class="badge warn" title="概念稀疏, 不符合CCM条件">概念稀疏</span>';
  }

  const metrics = [
    { label: 'CONCEPTS', value: conceptsVal },
    { label: 'EDGES', value: edgesVal },
    { label: 'ATE', value: ateVal },
    { label: '95% CI', value: ciVal },
    { label: 'IDENTIFIABLE', value: identifiableVal },
    { label: 'REFUTED', value: refutedVal },
    { label: 'MODE', value: modeVal },
    { label: 'DURATION', value: durationVal },
  ];
  const metricsHtml = metrics.map(m =>
    `<div class="metric"><div class="value">${escapeHtml(String(m.value))}</div><div class="label">${m.label}</div></div>`
  ).join('');
  let html = `<div class="metric-grid">${metricsHtml}</div>`;

  // P2 修缮 (Round 23 §8): 语义徽章行 (signal_type / refutations / CCM verdict)
  const badgesHtml = [signalBadge, refutedSemantic, ccmBadge].filter(Boolean).join(' ');
  if (badgesHtml) {
    html += `<div style="display:flex;flex-wrap:wrap;gap:0.4rem;align-items:center;margin:0.5rem 0;padding:0.4rem 0.6rem;border:1px solid var(--border,rgba(255,255,255,0.1));border-radius:4px;background:rgba(0,0,0,0.2);">
      <span style="font-family:var(--font-mono);color:var(--muted);font-size:clamp(0.64rem,0.85vw,0.72rem);">SEMANTICS:</span>${badgesHtml}
    </div>`;
  }

  // 关键参数网格
  const params = [
    { k: 'Treatment', v: r.treatment },
    { k: 'Outcome', v: r.outcome },
    { k: 'Threshold', v: r.threshold ?? 0.03 },
    { k: 'Window Size', v: r.window_size ?? 8 },
    { k: 'Backend', v: r.backend ?? 'DoWhy' },
    { k: 'Estimand Type', v: r.estimand_type ?? 'N/A' },
    { k: 'N Samples', v: r.n_samples ?? '-' },
    { k: 'Identifiable', v: r.identifiable ? 'YES' : 'NO' },
  ];
  const paramsHtml = params.map(p =>
    `<div class="param"><span class="k">${escapeHtml(p.k)}</span><span class="v">${escapeHtml(String(p.v ?? 'N/A'))}</span></div>`
  ).join('');
  html += `<h3 class="section-title" style="margin-top:0.6rem;">// KEY PARAMETERS</h3><div class="param-grid">${paramsHtml}</div>`;

  // Top causal edges（最多展示 10 条）
  if (r.top_edges && r.top_edges.length > 0) {
    const edgesRows = r.top_edges.slice(0, 10).map(e =>
      `<tr><td>${escapeHtml(e.source)}</td><td>${escapeHtml(e.target)}</td><td>${safeFmt(e.strength, 3)}</td><td>${escapeHtml(e.direction || '→')}</td></tr>`
    ).join('');
    html += `<h3 class="section-title">// TOP CAUSAL EDGES (top 10)</h3>` +
      `<table><thead><tr><th>SOURCE</th><th>TARGET</th><th>STRENGTH</th><th>DIRECTION</th></tr></thead><tbody>${edgesRows}</tbody></table>`;
  }

  // Refutation tests
  if (r.refutations && r.refutations.length > 0) {
    const refuteRows = r.refutations.map(ref => {
      const cls = ref.refuted ? 'fail' : 'pass';
      return `<tr><td>${escapeHtml(ref.method)}</td><td>${safeFmt(r.ate, 4)}</td><td>${safeFmt(ref.new_effect, 4)}</td><td><span class="badge ${cls}">${ref.refuted ? 'REFUTED' : 'ROBUST'}</span></td></tr>`;
    }).join('');
    html += `<h3 class="section-title">// REFUTATION TESTS</h3>` +
      `<table><thead><tr><th>METHOD</th><th>ORIGINAL</th><th>NEW EFFECT</th><th>VERDICT</th></tr></thead><tbody>${refuteRows}</tbody></table>`;
  }

  // P1 fix (Round 25 §1 + Round 27): 历史记录补全热力词矩阵图，并支持 2D/3D 切换
  // 用户反馈: "记录点击时，缺失热力词矩阵图（如同我们正常的运行的信息呈现）"
  const matrixHtml = (typeof buildAdjacencyMatrixHTML === 'function') ? buildAdjacencyMatrixHTML(r) : '';
  const hasConcepts = (r.concepts || []).length >= 2;
  if (matrixHtml || hasConcepts) {
    html += `<h3 class="section-title" style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;flex-wrap:wrap;">
      <span>// CONCEPT TOPOLOGY</span>
      <span style="display:flex;gap:6px;">
        <button class="btn-mini topo-toggle-btn" id="detailTopoToggle" title="切换到 3D 拓扑">3D 拓扑</button>
        <button class="btn-mini topo-toggle-btn hidden" id="detailTopo2DToggle" title="切换到 2D 网络图谱">2D 网络</button>
      </span>
    </h3>`;
    html += `<div id="detailMatrixView">${matrixHtml || '<div class="empty-state">无邻接矩阵数据</div>'}</div>`;
    html += `<div id="detailTopologyView" class="hidden">
      <h3 class="section-title">// 3D CAUSAL TOPOLOGY (高维空间拓扑)</h3>
      <div id="detailTopologyWrap" style="position:relative;width:100%;height:min(50vh,420px);border:1px solid var(--border);border-radius:6px;overflow:hidden;background:#05070a;">
        <canvas id="detailTopologyCanvas" style="width:100%;height:100%;display:block;"></canvas>
        <div style="position:absolute;top:6px;right:8px;display:flex;gap:6px;">
          <button id="detailTopoPauseBtn" class="btn-mini secondary topo-pause-btn" title="暂停/继续旋转">⏸</button>
          <button id="detailTopoResetBtn" class="btn-mini secondary topo-reset-btn" title="重置视角">⟲</button>
        </div>
        <div style="position:absolute;bottom:6px;left:8px;font-size:0.6rem;color:var(--muted);">拖拽旋转 · 滚轮缩放 · 点击节点坍缩为 2D 网络 · 节点大小=出现频次 · 边粗细=因果强度</div>
      </div>
    </div>`;
    html += `<div id="detailTopology2DView" class="hidden">
      <h3 class="section-title">// 2D CAUSAL NETWORK (坍缩网络图谱)</h3>
      <div id="detailTopology2DWrap" style="position:relative;width:100%;height:min(50vh,420px);border:1px solid var(--border);border-radius:6px;overflow:hidden;background:#05070a;">
        <canvas id="detailTopology2DCanvas" style="width:100%;height:100%;display:block;"></canvas>
        <div style="position:absolute;top:6px;right:8px;display:flex;gap:6px;">
          <button id="detailTopo2DResetBtn" class="btn-mini secondary topo-2d-reset-btn" title="重置布局">⟲</button>
        </div>
        <div style="position:absolute;bottom:6px;left:8px;font-size:0.6rem;color:var(--muted);">拖拽节点 · 滚轮缩放 · 点击高亮邻居 · 2D 力导向网络 · 边=因果链接</div>
      </div>
    </div>`;
  }

  // P1 fix (Round 25 §1): 补全反事实扫描 (SUPER 模式核心特征)
  if (r.counterfactual_scan && r.counterfactual_scan.length > 0) {
    const cfRows = r.counterfactual_scan.slice(0, 10).map(c =>
      `<tr><td>${escapeHtml(c.source || '?')}</td><td>${escapeHtml(c.target || '?')}</td><td>${safeFmt(c.trace_dnl, 3)}</td><td>${safeFmt(c.ite, 2)}</td><td>${safeFmt(c.observed, 1)}</td><td>${safeFmt(c.counterfactual, 1)}</td></tr>`
    ).join('');
    html += `<h3 class="section-title">// COUNTERFACTUAL SCAN (反事实扫描, top 10)</h3>` +
      `<table><thead><tr><th>EDGE</th><th>→</th><th>ΔNLL</th><th>ITE</th><th>OBSERVED</th><th>COUNTERFACT</th></tr></thead><tbody>${cfRows}</tbody></table>`;
  }

  // P1 fix (Round 25 §1): 补全六战士摘要 (SUPER 模式应比 LIGHT/DEEP 呈现更多信息)
  const sw = r.six_warriors || {};
  const swCards = [];
  if (sw.ccm) {
    const m = sw.ccm.metrics || {};
    swCards.push(`<div class="param"><span class="k">CCM Coverage</span><span class="v">${safeFmt(m.CCM_coverage, 1)}%</span></div>`);
    if (sw.ccm.verdict) swCards.push(`<div class="param"><span class="k">CCM Verdict</span><span class="v">${escapeHtml(sw.ccm.verdict)}</span></div>`);
  }
  if (sw.edm) {
    const m = sw.edm.metrics || {};
    swCards.push(`<div class="param"><span class="k">EDM ρ_high</span><span class="v">${safeFmt(m.rho_high, 3)}</span></div>`);
    swCards.push(`<div class="param"><span class="k">EDM ρ_mid</span><span class="v">${safeFmt(m.rho_mid, 3)}</span></div>`);
  }
  if (sw.havok) {
    const m = sw.havok.metrics || {};
    swCards.push(`<div class="param"><span class="k">HAVOK Linear%</span><span class="v">${safeFmt(m.linear_pct, 1)}%</span></div>`);
  }
  if (sw.causallearn) {
    const m = sw.causallearn.metrics || {};
    swCards.push(`<div class="param"><span class="k">CausalLearn Agree</span><span class="v">${safeFmt(m.Agree, 2)}</span></div>`);
  }
  if (swCards.length > 0) {
    html += `<h3 class="section-title">// SIX WARRIORS (六战士摘要)</h3><div class="param-grid">${swCards.join('')}</div>`;
  }

  // P1 fix (Round 25 §1): 补全稳定性分析
  const stab = r.stability_analysis || {};
  if (Object.keys(stab).length > 0) {
    const stabItems = [
      { k: 'Edge Stability', v: stab.edge_stability_mean },
      { k: 'Permutation p', v: stab.permutation_p_value },
      { k: 'ATE Bootstrap Std', v: stab.ate_bootstrap_std },
      { k: 'CV Folds', v: stab.cv_folds },
    ].filter(x => x.v != null);
    if (stabItems.length > 0) {
      const stabHtml = stabItems.map(x =>
        `<div class="param"><span class="k">${escapeHtml(x.k)}</span><span class="v">${typeof x.v === 'number' ? safeFmt(x.v, 4) : escapeHtml(String(x.v))}</span></div>`
      ).join('');
      html += `<h3 class="section-title">// STABILITY ANALYSIS</h3><div class="param-grid">${stabHtml}</div>`;
    }
  }

  return html;
}

// ── 详情模态框关闭绑定（脚本加载时立即附加，DOM 已就绪） ─────────────
// 关闭按钮
const _jobDetailCloseBtn = document.getElementById('jobDetailClose');
if (_jobDetailCloseBtn) {
  _jobDetailCloseBtn.addEventListener('click', () => {
    const m = document.getElementById('jobDetailModal');
    if (m) m.style.display = 'none';
  });
}
// 点击 overlay 外部关闭（仅当点击目标就是 overlay 本身时触发）
const _jobDetailOverlay = document.getElementById('jobDetailModal');
if (_jobDetailOverlay) {
  _jobDetailOverlay.addEventListener('click', (e) => {
    if (e.target.id === 'jobDetailModal') e.target.style.display = 'none';
  });
}
