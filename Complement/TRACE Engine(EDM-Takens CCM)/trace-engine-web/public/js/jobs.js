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
    const addLine = (html) => {
      const div = document.createElement('div');
      div.className = 'terminal-line';
      div.innerHTML = html;
      jobHistoryTerminal.appendChild(div);
    };
    if (data.active && data.active.length > 0) {
      addLine(`ACTIVE: ${data.active.length} job(s)`);
      data.active.forEach(id => addLine(`  ${id.slice(0, 8)}... running`));
    }
    if (data.history && data.history.length > 0) {
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
        addLine(`  [${ts}] ${j.id.slice(0, 8)}… ${mode} ${j.status}${dur}${errMark}${retryBtn}`);
      });
      jobHistoryTerminal.querySelectorAll('.retry-link').forEach(link => {
        link.addEventListener('click', (e) => {
          e.preventDefault();
          retryJob(link.dataset.id);
        });
      });
    } else {
      addLine('NO HISTORY');
    }
    jobHistoryTerminal.scrollTop = jobHistoryTerminal.scrollHeight;
  } catch (err) {
    jobHistoryTerminal.innerHTML = `<div class="terminal-line">加载任务历史失败: ${escapeHtml(err.message)}</div>`;
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
