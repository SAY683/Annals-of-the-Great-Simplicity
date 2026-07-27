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
    batchToolbar.style.cssText = 'display:flex;align-items:center;gap:8px;padding:4px 8px;border-bottom:1px solid var(--border,rgba(255,255,255,0.1));margin-bottom:4px;font-size:clamp(0.64rem,0.85vw,0.72rem);';

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
        const deleteBtn = ` <a href="#" class="delete-link" data-id="${j.id}" style="color:var(--danger,#ff4444);text-decoration:none;margin-left:6px;">[DEL]</a>`;
        // 显式"详情"链接：提供独立可点击目标，避免与 checkbox/链接的点击区域冲突
        const detailBtn = ` <a href="#" class="detail-link" data-id="${j.id}" style="color:var(--accent-tokusatsu,#ff9f43);text-decoration:none;margin-left:6px;font-weight:600;">[详情]</a>`;
        // 截断 textPreview 至 200 字符作为摘要（任务详情模态框入口提示）
        const previewRaw = j.textPreview || '';
        const preview = previewRaw.length > 200 ? previewRaw.slice(0, 200) + '…' : previewRaw;
        const previewHtml = preview
          ? `<div class="job-preview" style="color:var(--muted);font-size:clamp(0.68rem,0.92vw,0.78rem);margin-top:0.2rem;opacity:0.75;line-height:1.45;">${escapeHtml(preview)}</div>`
          : '';

        const row = addLine(
          `<input type="checkbox" class="job-cb" data-id="${j.id}" style="accent-color:var(--accent,#00ff88);margin-right:4px;">` +
          `<span class="job-meta" style="flex:1;min-width:0;">[${ts}] ${j.id.slice(0, 8)}… ${mode} ${j.status}${dur}${errMark}</span>` +
          `<span class="job-actions" style="flex-shrink:0;">${retryBtn}${deleteBtn}${detailBtn}</span>` +
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
    exportMdBtn.title = '导出人话版 Markdown 报告';
    const closeBtn = document.getElementById('jobDetailClose');
    if (closeBtn && closeBtn.parentNode) {
      closeBtn.parentNode.insertBefore(exportMdBtn, closeBtn);
    }
    exportMdBtn.addEventListener('click', () => {
      const tid = exportMdBtn.dataset.taskId;
      if (!tid) return;
      // 直接触发下载
      const a = document.createElement('a');
      a.href = `/api/jobs/${tid}/export/md`;
      a.download = `${tid}_report.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      if (typeof log === 'function') log('info', `已请求导出人话版报告: ${tid.slice(0, 8)}…`);
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
  const modeVal = (r.analysis_mode || 'light').toUpperCase();
  const durationVal = r.execution_profile && r.execution_profile.total_ms != null
    ? `${safeFmt(r.execution_profile.total_ms / 1000, 2)}s`
    : '-';

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
