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

        const row = addLine(
          `  <input type="checkbox" class="job-cb" data-id="${j.id}" style="accent-color:var(--accent,#00ff88);margin-right:4px;">` +
          `[${ts}] ${j.id.slice(0, 8)}… ${mode} ${j.status}${dur}${errMark}${retryBtn}${deleteBtn}`
        );
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
