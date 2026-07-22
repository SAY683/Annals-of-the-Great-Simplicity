/**
 * trace-to-edm Web 操纵台 — 数据集中心化前端
 */

// ── 全局状态 ──────────────────────────────────────────────
let selectedUUIDs = new Set();
let currentProject = 'default';
let workScanData = null;

// ── 终端与日志 cockpit ────────────────────────────────────
const terminal = document.getElementById('terminal');
const { LOG_MAX_LINES, formatLogEntry, countByLevel, trimBuffer } = window.LogCockpit || {
  LOG_MAX_LINES: 400,
  formatLogEntry: () => '',
  countByLevel: () => ({}),
  trimBuffer: b => b,
};

let logState = {
  buffer: [],          // 原始日志对象 {time, level, message}
  filters: new Set(['progress', 'info', 'warn', 'error', 'done']),
  autoScroll: true,
  paused: false,
  lastLevel: 'info',
};

function t(msg, cls) {
  const level = cls || 'log';
  const entry = { time: new Date(), level, message: msg };
  logState.buffer.push(entry);
  logState.buffer = trimBuffer(logState.buffer, LOG_MAX_LINES);
  logState.lastLevel = level;
  renderLogs();
}
function tClear() { logState.buffer = []; renderLogs(); }

function renderLogs() {
  const visible = logState.buffer.filter(e => logState.filters.has(e.level));
  terminal.innerHTML = visible.map(e => formatLogEntry(e, logState.filters) || '').join('');
  if (logState.autoScroll && !logState.paused) {
    terminal.scrollTop = terminal.scrollHeight;
  }
  updateLogStats();
}

function updateLogStats() {
  const counts = countByLevel(logState.buffer);
  ['progress','info','warn','error','done'].forEach(l => {
    const el = document.getElementById(`logCount${l}`);
    if (el) el.textContent = counts[l] || 0;
  });
  const totalEl = document.getElementById('logCountTotal');
  if (totalEl) totalEl.textContent = logState.buffer.length;
}

function setLogFilter(level, enabled) {
  if (enabled) logState.filters.add(level); else logState.filters.delete(level);
  renderLogs();
}

function toggleLogPause() {
  logState.paused = !logState.paused;
  const btn = document.getElementById('btnLogPause');
  if (btn) btn.textContent = logState.paused ? '▶ 继续' : '⏸ 暂停';
  if (!logState.paused) renderLogs();
}

// ── SSE 流处理（支持手动重连） ─────────────────────────────
function streamJob(url, body, label) {
  tClear();
  t(`▶ ${label}`, 'progress');
  const maxRetries = 3;
  let attempt = 0;

  function connect() {
    return fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(response => {
      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      attempt = 0; // 连接成功重置计数
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      function process() {
        return reader.read().then(({ done, value }) => {
          if (done) return true;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data:')) continue;
            try {
              const data = JSON.parse(line.slice(5).trim());
              const ev = data._event || data.event || data.type;
              if (ev === 'start') t(`▶ 任务开始 ${data.job_id || ''}`, 'progress');
              else if (ev === 'progress') t(data.message || '', 'progress');
              else if (ev === 'warn') t(data.message || '', 'warn');
              else if (ev === 'error') t(data.message || '', 'error');
              else if (ev === 'log') t(data.message || '', 'info');
              else if (ev === 'done') {
                t(data.success ? '✓ 完成' : '✗ 失败', data.success ? 'done' : 'error');
                if (data.trajectory_rows !== undefined) t(`轨迹: ${data.trajectory_rows}行 | EDM: ${data.edm_ready ? '就绪' : '未就绪'}`, 'info');
                refreshAll(); refreshChart();
                return data.success;
              }
            } catch (e) { /* skip */ }
          }
          return process();
        }).catch(err => {
          throw err;
        });
      }
      return process();
    }).catch(err => {
      attempt++;
      if (attempt <= maxRetries) {
        t(`⟲ 连接中断，第 ${attempt}/${maxRetries} 次重连...`, 'warn');
        return new Promise(r => setTimeout(r, 1500 * attempt)).then(connect);
      }
      t(`✗ 连接失败: ${err.message}`, 'error');
      throw err;
    });
  }
  return connect();
}

// ── 状态刷新 ──────────────────────────────────────────────
async function refreshAll() {
  await Promise.all([refreshStatus(), refreshDataset(), refreshTable()]);
}
let _statusPending = false;
async function refreshStatus() {
  if (_statusPending) return;
  _statusPending = true;
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('statRows').textContent = d.trajectory.rows;
    const edmEl = document.getElementById('statEdm');
    edmEl.textContent = d.trajectory.edm_ready ? '✓ 就绪' : `${15 - d.trajectory.rows}行`;
    edmEl.style.color = d.trajectory.edm_ready ? 'var(--accent)' : 'var(--warn)';
    document.getElementById('statLayers').textContent =
      `${d.layers.l1?'L1✓':'L1✗'} ${d.layers.l2?'L2✓':'L2✗'} ${d.layers.l3?'L3✓':'L3✗'}`;
    const edmBtn = document.getElementById('btnEDM');
    edmBtn.disabled = !d.trajectory.edm_ready;
    document.getElementById('edmStatus').textContent = d.trajectory.edm_ready ? '✓ 就绪' : `需≥15行 (当前${d.trajectory.rows})`;
    document.getElementById('edmStatus').style.color = d.trajectory.edm_ready ? 'var(--accent)' : 'var(--warn)';

    if (d.trajectory.rows === 0) {
      document.getElementById('edmDataRange').textContent = '无数据 (需≥15行)';
    }

    if (d.trajectory.edm_targets && d.trajectory.edm_targets.length > 0) {
      const sel = document.getElementById('edmTarget');
      const cv = sel.value;
      sel.innerHTML = '';
      d.trajectory.edm_targets.forEach(t => {
        const o = document.createElement('option');
        o.value = t.col;
        o.textContent = `[${t.layer}] ${t.col} — ${t.desc}`;
        sel.appendChild(o);
      });
      if ([...sel.options].some(o => o.value === cv)) sel.value = cv;
    } else {
      // EDM未就绪时不清空已有选项, 保持占位符可见
      const sel = document.getElementById('edmTarget');
      if (sel.options.length === 0) {
        sel.innerHTML = '<option value="">(需≥15行轨迹数据)</option>';
      }
    }
  } catch (e) { console.error(e); }
  finally { _statusPending = false; }
}

// ── 项目管理 ──────────────────────────────────────────────
async function refreshProjects() {
  try {
    const r = await fetch('/api/projects');
    const projects = await r.json();
    const sel = document.getElementById('projectSelect');
    sel.innerHTML = '';
    if (Array.isArray(projects)) {
      projects.forEach(p => {
        const o = document.createElement('option');
        o.value = p.name;
        o.textContent = `${p.active ? '▸ ' : '  '}${p.name} [${p.rows}行]`;
        if (p.active) { o.selected = true; currentProject = p.name; }
        sel.appendChild(o);
      });
      const active = projects.find(p => p.active);
      if (active) {
        document.getElementById('statProject').textContent = active.name;
        document.getElementById('projectDetail').innerHTML =
          `CSV: projects/${active.name}/ | 创建: ${active.created}` +
          (active.name !== 'default' ? ` <button class="btn-mini" style="color:var(--danger)" onclick="deleteProject('${active.name}')">删除</button>` : '');
      }
    }
  } catch (e) { console.error(e); }
  _projectsInitialized = true;
}

// 初始化标志: 防止页面加载时 change 事件触发 spurious API 调用
let _projectsInitialized = false;

document.getElementById('projectSelect').addEventListener('change', async (e) => {
  if (!_projectsInitialized) return;  // 跳过初始化阶段的 change 事件
  await fetch('/api/projects/activate', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: e.target.value }),
  });
  currentProject = e.target.value;
  refreshInputs();
  refreshAll();
});

async function createProject() {
  const input = document.getElementById('newProjectName');
  const name = input.value.trim();
  if (!name) return;
  try {
    const r = await fetch('/api/projects', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    input.value = '';
    await refreshProjects();
    t(`✓ 项目 "${name}" 创建成功`, 'done');
  } catch (e) {
    console.error('create project:', e);
    t('✗ 创建项目失败: ' + (e.message || e), 'error');
  }
}

document.getElementById('btnCreateProject').addEventListener('click', createProject);
document.getElementById('newProjectName').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') createProject();
});

document.getElementById('btnRefreshProjects').addEventListener('click', refreshProjects);

async function refreshInputs() {
  const sel = document.getElementById('textCsvSelect');
  if (!sel) return;
  const current = sel.value;
  try {
    const r = await fetch('/api/inputs');
    const d = await r.json();
    sel.innerHTML = '<option value="">-- 项目 inputs/ 中的文件 --</option>';
    if (d.files && d.files.length) {
      d.files.forEach(f => {
        const o = document.createElement('option');
        o.value = f.path;
        o.textContent = `${f.name} (${(f.size/1024).toFixed(1)}KB)`;
        sel.appendChild(o);
      });
      if ([...sel.options].some(o => o.value === current)) sel.value = current;
    }
  } catch (e) { console.error('refresh inputs:', e); }
}

async function deleteProject(name) {
  if (!confirm(`删除项目 "${name}" 及全部数据？`)) return;
  await fetch(`/api/projects/${name}`, { method: 'DELETE' });
  refreshProjects(); refreshAll();
}

// ── 模型配置 ──────────────────────────────────────────────

async function refreshModels() {
  const sel = document.getElementById('modelSelect');
  const info = document.getElementById('modelInfo');
  try {
    const r = await fetch('/api/models');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    if (!sel) return;
    sel.innerHTML = '';
    if (d.models && d.models.length > 0) {
      // Q9 P1-16 优化: 将可用模型与仅展示模型分组，避免误选
      const usableOptGroup = document.createElement('optgroup');
      usableOptGroup.label = '可用模型';
      const displayOptGroup = document.createElement('optgroup');
      displayOptGroup.label = '仅展示（需使用 trace-engine-web SUPER 模式）';

      d.models.forEach(m => {
        const o = document.createElement('option');
        o.value = m.key;
        o.textContent = m.name + ' (' + m.description + ')';
        if (m.key === d.active) o.selected = true;
        if (m.trace_model) {
          o.disabled = true;
          o.dataset.traceOnly = 'true';
          o.textContent += ' [仅展示]';
          displayOptGroup.appendChild(o);
        } else {
          usableOptGroup.appendChild(o);
        }
      });

      sel.appendChild(usableOptGroup);
      if (displayOptGroup.children.length > 0) {
        sel.appendChild(displayOptGroup);
      }
      if (info) info.textContent = (d.active || '') + ' | 切换后首次编码需重载模型 (~60-90s)';
      const coreEl = document.getElementById('statCore');
      if (coreEl) {
        const coreMap = {
          'qwen2.5-3b': 'Qwen3B',
          'qwen2.5-1.5b': 'Qwen1.5B',
          'shehui-llama': 'Shehui-LLaMA',
          'shenji-llama': 'Shenji-LLaMA'
        };
        coreEl.textContent = coreMap[d.active] || d.active;
      }
    } else {
      sel.innerHTML = '<option value="">无可用模型</option>';
      if (info) info.textContent = '未找到模型，请检查 Models 目录';
    }
  } catch (e) {
    console.error('model list:', e);
    if (sel) sel.innerHTML = '<option value="">加载失败</option>';
    if (info) info.textContent = '加载失败: ' + (e.message || e) + ' (服务未启动?)';
  }
}

document.getElementById('modelSelect').addEventListener('change', async (e) => {
  const target = e.target.options[e.target.selectedIndex];
  const targetModelKey = target.value;
  const targetText = target.textContent;

  // Q9 P1-16 修复: 阻止选择仅展示模型，并给出明确提示
  if (target.dataset.traceOnly === 'true') {
    alert(`模型 "${targetText}" 为 TRACE LLaMA 展示模型，\n仅在 L3 显示，不可直接激活。\n如需使用 TRACE LLaMA，请切换至 trace-engine-web 的 SUPER 模式。`);
    refreshModels();
    return;
  }

  // Q9 P1-16 修复: 动态生成模型切换提示，避免所有模型都提示 4-bit 量化
  const descMatch = targetText.match(/\(([^)]+)\)/);
  const desc = descMatch ? descMatch[1] : '';
  const isQuantizeModel = desc.includes('4-bit');
  const quantNote = isQuantizeModel
    ? '注意: 此模型在 CUDA 环境将启用 4-bit 量化以节省显存；CPU 环境回退 FP32。'
    : '此模型不启用量化。';
  const msg = `切换模型将清除缓存并重新加载。\n\n目标模型: ${targetText}\n${quantNote}`;

  if (!confirm(msg)) {
    refreshModels(); return;
  }
  try {
    const r = await fetch('/api/models/activate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: targetModelKey }),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      t(`✗ 模型切换失败: ${d.error || r.statusText}`, 'error');
    } else {
      t(`✓ 已切换模型: ${targetModelKey}`, 'done');
    }
  } catch (e) {
    t(`✗ 模型切换请求失败: ${e.message}`, 'error');
  }
  refreshModels();
});

document.getElementById('btnRefreshModels').addEventListener('click', refreshModels);

// ── 工作目录扫描 ──────────────────────────────────────────
async function scanWork() {
  const wrap = document.getElementById('workScanResult');
  wrap.innerHTML = '<span class="dim">扫描中...</span>';
  selectedUUIDs.clear();
  document.getElementById('btnAddSelected').disabled = true;

  try {
    const r = await fetch('/api/work-scan');
    const d = await r.json();
    workScanData = d;

    let html = `<div style="margin-bottom:6px;font-size:0.6rem">`;
    html += `${d.total} UUID | ${d.disk_mb||'?'}MB | `;
    html += `<span class="badge-ok">完整:${d.counts.complete}</span> `;
    if (d.orphans) html += `<span class="badge-warn">孤儿:${d.orphans}</span>`;
    html += `</div>`;

    if (d.complete && d.complete.length) {
      html += `<div class="ws-row" style="font-weight:700;color:var(--muted)"><span style="width:20px"></span><span>UUID</span><span style="flex:1">预览</span><span>时间</span><span style="width:40px"></span></div>`;
      d.complete.forEach(e => {
        html += `<div class="ws-row">
          <input type="checkbox" value="${e.uuid}" onchange="toggleUUID('${e.uuid}', this.checked)" />
          <span style="font-size:0.5rem;color:var(--muted)">${e.uuid.slice(0,12)}</span>
          <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.preview||''}</span>
          <span style="white-space:nowrap;font-size:0.5rem;color:var(--muted)">${e.mtime||''}</span>
          <button class="btn-mini" onclick="deleteWorkUUID('${e.uuid}')" style="color:var(--danger);padding:1px 4px;font-size:0.5rem">✕</button>
        </div>`;
      });
      html += `<div style="margin-top:4px;display:flex;gap:6px">
        <button class="btn-mini" onclick="selectAllUUIDs()">全选</button>
        <button class="btn-mini" onclick="deselectAllUUIDs()">取消全选</button>
        <button class="btn-mini" onclick="deleteSelectedUUIDs()" style="color:var(--danger)">删除选中</button>
      </div>`;
    }
    if (d.incomplete && d.incomplete.length) {
      html += `<div style="margin-top:4px;color:var(--warn);font-size:0.55rem">⚠ ${d.incomplete.length} 个不完整</div>`;
    }
    wrap.innerHTML = html;
  } catch (e) {
    wrap.innerHTML = `<span class="badge-err">扫描失败: ${e.message}</span>`;
  }
}

function toggleUUID(uuid, checked) {
  if (checked) selectedUUIDs.add(uuid); else selectedUUIDs.delete(uuid);
  document.getElementById('btnAddSelected').disabled = selectedUUIDs.size === 0;
  document.getElementById('btnAddSelected').textContent = `+ 将选中项 (${selectedUUIDs.size}) 加入数据集`;
}
function selectAllUUIDs() {
  document.querySelectorAll('#workScanResult input[type=checkbox]').forEach(cb => { cb.checked = true; selectedUUIDs.add(cb.value); });
  document.getElementById('btnAddSelected').disabled = false;
  document.getElementById('btnAddSelected').textContent = `+ 将选中项 (${selectedUUIDs.size}) 加入数据集`;
}
function deselectAllUUIDs() {
  document.querySelectorAll('#workScanResult input[type=checkbox]').forEach(cb => cb.checked = false);
  selectedUUIDs.clear();
  document.getElementById('btnAddSelected').disabled = true;
  document.getElementById('btnAddSelected').textContent = '+ 将选中项加入数据集';
}

async function deleteWorkUUID(uuid) {
  if (!confirm(`永久删除此 UUID 及其关联文件？\n${uuid}\n\n此操作不可撤销。`)) return;
  try {
    const r = await fetch(`/api/work-uuid/${uuid}`, { method: 'DELETE' });
    const d = await r.json();
    t(`已删除: ${uuid.slice(0,12)}... (释放 ${(d.freed_bytes/1024).toFixed(1)} KB)`, 'warn');
    scanWork();
  } catch (e) { t(`删除失败: ${e.message}`, 'error'); }
}

async function deleteSelectedUUIDs() {
  if (!selectedUUIDs.size) return;
  if (!confirm(`永久删除选中的 ${selectedUUIDs.size} 个 UUID 及其关联文件？\n此操作不可撤销。`)) return;
  let count = 0;
  for (const uuid of selectedUUIDs) {
    try {
      await fetch(`/api/work-uuid/${uuid}`, { method: 'DELETE' });
      count++;
    } catch (e) { /* continue */ }
  }
  t(`已删除 ${count}/${selectedUUIDs.size} 个 UUID`, 'warn');
  selectedUUIDs.clear();
  document.getElementById('btnAddSelected').disabled = true;
  scanWork();
}

document.getElementById('btnScanWork').addEventListener('click', scanWork);

document.getElementById('btnAddSelected').addEventListener('click', async () => {
  if (!selectedUUIDs.size) return;
  const uuids = [...selectedUUIDs];
  tClear(); t(`添加 ${uuids.length} 个 UUID 到数据集...`, 'progress');
  try {
    const r = await fetch('/api/dataset/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uuids }),
    });
    const d = await r.json();
    t(`✓ 已添加 ${d.added} 个条目 (${d.skipped||0} 已跳过)`, 'done');
    refreshDataset();
    selectedUUIDs.clear();
    document.getElementById('btnAddSelected').disabled = true;
    scanWork();
    document.getElementById('btnRunPipeline').disabled = false;
  } catch (e) { t(`✗ 失败: ${e.message}`, 'error'); }
});

// 清理按钮
document.getElementById('btnCleanOrphans').addEventListener('click', async () => {
  if (!confirm('删除仅有 input.txt 无 result.json 的孤儿文件？')) return;
  await fetch('/api/work-clean', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dry_run: false, orphans_only: true }),
  });
  scanWork();
});
document.getElementById('btnCleanInvalid').addEventListener('click', async () => {
  if (!confirm('删除所有无效 TRACE 输出？(text_only + empty + JSON损坏)')) return;
  await fetch('/api/work-clean', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dry_run: false }),
  });
  scanWork();
});

// ── 文本输入 ──────────────────────────────────────────────
async function addDirectText() {
  const csvFile = document.getElementById('textCsvSelect').value;
  const directText = document.getElementById('textDirect').value.trim();

  if (!csvFile && !directText) { alert('请选择 CSV 或粘贴文本'); return; }

  tClear();
  if (csvFile) {
    t(`从 CSV 添加文本: ${csvFile}`, 'progress');
    try {
      const r = await fetch('/api/dataset/add-text', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_path: csvFile }),
      });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || `HTTP ${r.status}`);
      t(`✓ 已添加 ${d.added !== undefined ? d.added : d} 条文本`, 'done');
    } catch (e) { t(`✗ CSV 添加失败: ${e.message}`, 'error'); }
  }

  if (directText) {
    const segments = directText.split('---').filter(s => s.trim());
    t(`添加 ${segments.length} 段文本...`, 'progress');
    try {
      const r = await fetch('/api/dataset/add-text', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texts: segments.map(t => ({ text: t.trim(), timestamp: new Date().toISOString().slice(0,16), source: '手动输入' })) }),
      });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || `HTTP ${r.status}`);
      t(`✓ 已添加 ${d.added !== undefined ? d.added : d} 条文本`, 'done');
      document.getElementById('textDirect').value = '';
    } catch (e) { t(`✗ 文本添加失败: ${e.message}`, 'error'); }
  }

  refreshDataset();
  document.getElementById('btnRunPipeline').disabled = false;
}

document.getElementById('btnAddText').addEventListener('click', addDirectText);
document.getElementById('textDirect').addEventListener('keydown', (e) => {
  // UX: Enter 提交，Shift+Enter 换行（与即时通讯/表单一致）
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    addDirectText();
  }
});

// ── 数据集管理 ────────────────────────────────────────────
async function refreshDataset() {
  try {
    const r = await fetch('/api/dataset');
    const d = await r.json();
    document.getElementById('statDS').textContent = `${d.summary.pending||0}待处理/${d.summary.total||0}总计`;
    document.getElementById('dsSummary').textContent =
      `回填:${d.summary.by_type?.replay||0} 文本:${d.summary.by_type?.text||0} | 待处理:${d.summary.pending||0} 已完成:${d.summary.processed||0}`;

    const wrap = document.getElementById('datasetTable');
    if (!d.entries || !d.entries.length) {
      wrap.innerHTML = '<div class="dim">数据集为空。从左侧数据源添加条目。</div>';
      document.getElementById('btnRunPipeline').disabled = true;
      return;
    }

    let html = '';
    d.entries.forEach(e => {
      const typeClass = e.type === 'replay' ? 'replay' : 'text';
      const typeLabel = e.type === 'replay' ? '回填' : '文本';
      html += `<div class="ds-row" data-id="${e.id}">
        <span class="ds-type ${typeClass}">${typeLabel}</span>
        <span class="ds-status ${e.status}">${e.status==='pending'?'待处理':e.status==='processed'?'已完成':'跳过'}</span>
        <span class="ds-preview">${(e.source||'').slice(0,50)}</span>
        <span class="ds-ts" style="cursor:pointer" title="点击修改时间">${(e.timestamp||'').slice(0,16)}</span>
        <button class="btn-mini" onclick="removeFromDataset('${e.id}')" style="color:var(--danger)">✕</button>
      </div>`;
    });
    wrap.innerHTML = html;

    const hasPending = d.summary.pending > 0;
    document.getElementById('btnRunPipeline').disabled = !hasPending;
  } catch (e) { console.error(e); }
}

async function removeFromDataset(id) {
  await fetch('/api/dataset/remove', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  refreshDataset();
}

document.getElementById('btnRefreshDS').addEventListener('click', refreshDataset);
document.getElementById('btnClearProcessed').addEventListener('click', async () => {
  await fetch('/api/dataset/clear-processed', { method: 'POST' });
  refreshDataset();
});

// ── 数据集时间编辑 ──────────────────────────────────────

async function editTimestamp(id, currentTs) {
  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:9999';
  modal.innerHTML = '<div style="background:var(--panel);border:1px solid var(--accent);border-radius:8px;padding:24px;min-width:360px"><h3 style="color:var(--accent);margin-bottom:12px">修改时间戳</h3><input id="tsInput" value="' + currentTs + '" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;font-family:inherit;font-size:0.8rem;margin-bottom:12px" placeholder="YYYY-MM-DD HH:MM"><div style="display:flex;gap:8px;justify-content:flex-end"><button id="tsCancel" class="btn-mini">取消</button><button id="tsOK" class="btn btn-run" style="width:auto;margin:0;padding:4px 16px">确认</button></div></div>';
  document.body.appendChild(modal);
  document.getElementById('tsInput').focus();
  document.getElementById('tsInput').select();
  return new Promise(function(resolve) {
    document.getElementById('tsOK').onclick = function() { var v = document.getElementById('tsInput').value.trim(); document.body.removeChild(modal); resolve(v); };
    document.getElementById('tsCancel').onclick = function() { document.body.removeChild(modal); resolve(null); };
    modal.onclick = function(e) { if (e.target === modal) { document.body.removeChild(modal); resolve(null); } };
  }).then(async function(newTs) {
  if (!newTs || newTs === currentTs) return;
  try {
    await fetch('/api/dataset/update-ts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, timestamp: newTs }),
    });
    refreshDataset();
  } catch (e) { t('修改失败: ' + e.message, 'error'); }
  });
}

async function batchSpreadTimestamps() {
  // Custom modal for time distribution
  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:9999';
  modal.innerHTML = '<div style="background:var(--panel);border:1px solid var(--accent);border-radius:8px;padding:24px;min-width:420px">' +
    '<h3 style="color:var(--accent);margin-bottom:16px">时间分布设置</h3>' +
    '<div style="margin-bottom:8px;font-size:0.7rem;color:var(--muted)">起始时间:</div>' +
    '<input id="spStart" value="' + new Date(Date.now()-7*86400000).toISOString().slice(0,16).replace('T',' ') + '" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;font-family:inherit;font-size:0.7rem;margin-bottom:12px">' +
    '<div style="margin-bottom:8px;font-size:0.7rem;color:var(--muted)">结束时间:</div>' +
    '<input id="spEnd" value="' + new Date().toISOString().slice(0,16).replace('T',' ') + '" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;font-family:inherit;font-size:0.7rem;margin-bottom:12px">' +
    '<div style="margin-bottom:8px;font-size:0.7rem;color:var(--muted)">分布模式:</div>' +
    '<select id="spMode" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;font-family:inherit;font-size:0.7rem;margin-bottom:16px">' +
    '<option value="uniform">均匀分布 (等间隔)</option>' +
    '<option value="gaussian">高斯分布 (中间密集, 两端稀疏)</option>' +
    '<option value="cauchy">柯西分布 (长尾, 极端值保留)</option>' +
    '</select>' +
    '<div style="display:flex;gap:8px;justify-content:flex-end"><button id="spCancel" class="btn-mini">取消</button><button id="spOK" class="btn btn-run" style="width:auto;margin:0;padding:4px 16px">执行分布</button></div></div>';
  document.body.appendChild(modal);
  const result = await new Promise(function(resolve) {
    document.getElementById('spOK').onclick = function() {
      resolve({
        start: document.getElementById('spStart').value.trim(),
        end: document.getElementById('spEnd').value.trim(),
        mode: document.getElementById('spMode').value,
      });
      document.body.removeChild(modal);
    };
    document.getElementById('spCancel').onclick = function() { document.body.removeChild(modal); resolve(null); };
    modal.onclick = function(e) { if (e.target === modal) { document.body.removeChild(modal); resolve(null); } };
  });
  if (!result) return;
  try {
    const r = await fetch('/api/dataset');
    const d = await r.json();
    const pending = (d.entries || []).filter(e => e.status === 'pending');
    if (pending.length < 2) { t('需要至少2条待处理条目', 'warn'); return; }
    const n = pending.length;
    const t0 = new Date(result.start).getTime();
    const t1 = new Date(result.end).getTime();
    const range = t1 - t0;
    const updates = pending.map((e, i) => {
      let pos;
      if (result.mode === 'uniform') {
        pos = n > 1 ? i / (n - 1) : 0.5;
      } else if (result.mode === 'gaussian') {
        // Box-Muller approximation: use inverse CDF of normal
        const x = n > 1 ? (i + 0.5) / n : 0.5;
        const z = Math.sqrt(2) * (x < 0.5 ? -Math.sqrt(-2*Math.log(2*x)) : Math.sqrt(-2*Math.log(2*(1-x))));
        pos = Math.max(0, Math.min(1, 0.5 + z * 0.22));
      } else {
        // Cauchy: use inverse CDF
        const x = n > 1 ? (i + 0.5) / n : 0.5;
        pos = Math.max(0, Math.min(1, 0.5 + 0.15 * Math.tan(Math.PI * (x - 0.5))));
      }
      return {
        id: e.id,
        timestamp: new Date(t0 + pos * range).toISOString().slice(0, 16).replace('T', ' '),
      };
    });
    for (const u of updates) {
      await fetch('/api/dataset/update-ts', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(u),
      });
    }
    t('已分布 ' + updates.length + ' 条时间 (' + result.mode + ')', 'progress');
    refreshDataset();
  } catch (e) { t('失败: ' + e.message, 'error'); }
}

document.getElementById('btnSpreadTime').addEventListener('click', batchSpreadTimestamps);


document.getElementById('btnResetAll').addEventListener('click', async () => {
  await fetch('/api/dataset/reset', { method: 'POST' });
  refreshDataset();
});

document.getElementById('btnClearTrajectory').addEventListener('click', async () => {
  if (!confirm('确定要清空当前项目的轨迹 CSV 吗？\n\n这将删除所有已积累的分析数据。\n数据集条目不受影响。\n此操作不可撤销。')) return;
  try {
    const r = await fetch('/api/trajectory/clear', { method: 'POST' });
    const d = await r.json();
    t(`轨迹已清空`, 'warn');
    refreshStatus(); refreshTable();
  } catch (e) { t(`清空失败: ${e.message}`, 'error'); }
});

// ── 运行管线 ──────────────────────────────────────────────
document.getElementById('btnRunPipeline').addEventListener('click', () => {
  const btn = document.getElementById('btnRunPipeline');
  btn.disabled = true;
  btn.textContent = '⏳ 运行中...';
  streamJob('/api/pipeline/run', { project: currentProject }, '运行管线: 处理所有待处理条目')
    .finally(() => {
      btn.disabled = false;
      btn.textContent = '▶ 运行管线 (处理所有待处理条目)';
      refreshDataset();
      refreshStatus();
      refreshTable();
    });
});

// ── 趋势图 ──────────────────────────────────────────────

async function refreshChart() {
  const canvas = document.getElementById('trendChart');
  if (!canvas) return;
  // 高 DPI 渲染 — 消除模糊
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  canvas.style.width = rect.width + 'px';
  canvas.style.height = rect.height + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const W = rect.width, H = rect.height;

  // 边距
  const pad = { top: 20, right: 20, bottom: 30, left: 55 };
  const pw = W - pad.left - pad.right;
  const ph = H - pad.top - pad.bottom;

  // 清空
  ctx.fillStyle = '#0b0f14'; ctx.fillRect(0, 0, W, H);

  try {
    const r = await fetch('/api/trajectory');
    const d = await r.json();
    if (!d.rows || d.rows.length < 2) {
      ctx.fillStyle = '#64748b'; ctx.font = '11px monospace';
      ctx.fillText('数据不足 (需≥2行)', pad.left, H/2);
      return;
    }

    // 提取 7 列数据 (L1+L2+L3)
    const rows = d.rows;
    // 5个关键指标: L1因果+L1结构+L2话语+L3本体+L2熵 (互补而不冗余)
    const series = [
      { key: 'ate', data: [], color: '#00d9a3', label: 'ATE (因果强度)' },
      { key: 'adj_density', data: [], color: '#f0a000', label: 'adj_density (图密度)' },
      { key: 'z_pca_1', data: [], color: '#4da6ff', label: 'z_pca_1 (世俗主轴)' },
      { key: 'z_存在', data: [], color: '#c084fc', label: 'z_存在 (本体论距离)' },
      { key: 'secular_entropy', data: [], color: '#e0a0ff', label: 'entropy (话语多样性)' },
    ];
    const labels = [];

    for (const row of rows) {
      for (const s of series) {
        const v = parseFloat(row[s.key]);
        if (!isNaN(v)) s.data.push(v);
      }
      labels.push((row.time_step || '').slice(5, 16));
    }
    // 对齐长度: 用最长序列为准
    const maxLen = Math.max(...series.map(s => s.data.length));
    for (const s of series) {
      while (s.data.length < maxLen) s.data.push(NaN);
    }

    const allData = series.flatMap(s => s.data).filter(v => !isNaN(v));
    if (!allData.length) {
      ctx.fillStyle = '#64748b'; ctx.font = '11px monospace';
      ctx.fillText('无有效数据', pad.left, H/2); return;
    }

    const yMin = Math.min(...allData);
    const yMax = Math.max(...allData);
    const yRange = yMax - yMin || 1;

    const scaleX = i => pad.left + (i / Math.max(maxLen - 1, 1)) * pw;
    const scaleY = v => pad.top + ph - ((v - yMin) / yRange) * ph;

    // 网格
    ctx.strokeStyle = '#1f2a36'; ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (ph * i / 4);
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
      ctx.fillStyle = '#64748b'; ctx.font = '9px monospace';
      ctx.fillText((yMax - (yRange * i / 4)).toFixed(2), 2, y + 3);
    }
    // 底部时间标签
    ctx.fillStyle = '#64748b'; ctx.font = '8px monospace';
    for (let i = 0; i < labels.length; i += Math.max(1, Math.floor(labels.length / 8))) {
      ctx.fillText(labels[i], scaleX(i) - 15, H - 5);
    }

    // 画线函数
    function drawLine(data, color, dash) {
      if (!data.length) return;
      ctx.strokeStyle = color; ctx.lineWidth = 1.5;
      if (dash) ctx.setLineDash([4, 3]); else ctx.setLineDash([]);
      ctx.beginPath();
      for (let i = 0; i < data.length; i++) {
        const x = scaleX(i), y = scaleY(data[i]);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }

    series.forEach(s => drawLine(s.data, s.color, false));

    // Y轴标签
    ctx.fillStyle = '#64748b'; ctx.font = '9px monospace';
    ctx.fillText('ATE', 2, pad.top - 4);

  } catch (e) { console.error('Chart error:', e); }
}

document.getElementById('btnRefreshChart').addEventListener('click', refreshChart);

// ── EDM 触发 (带反馈检测) ────────────────────────────────

// 元审计 P0 修缮: 反馈环真正兑现
// 将检测到非线性突变的时间点文本加入数据集，并标记为 DEEP 模式待再分析
// 之前代码仅 confirm 后打印消息，未实际调用 /api/dataset/add-text
async function enqueueDeepReanalysis(edmResult) {
  try {
    // 1. 从 EDM 结果或当前轨迹提取异常时间点对应的文本行
    //    优先使用 EDM 结果中可能有 timestamp/text 字段；否则用最近一条轨迹行
    const trajRes = await fetch('/api/trajectory');
    const trajData = await trajRes.json();
    const rows = trajData.rows || [];
    if (!rows.length) {
      t('⚠ 反馈环: 当前轨迹为空，无法定位异常时间点文本', 'warn');
      return;
    }

    // 2. 选取最后 N 条作为"异常时间点"候选（简化策略）
    //    生产级可基于 EDM 的 Lyapunov/HAVOK forcing 时间点精确定位
    const lastN = Math.min(3, rows.length);
    const candidateRows = rows.slice(-lastN);
    const texts = candidateRows.map(r => ({
      timestamp: r.time_step || r.timestamp || '',
      text_preview: r.text_preview || '',
      source: 'edm_feedback_nonlinear',
      deep_mode_pending: true,
    }));

    // 3. 调用 /api/dataset/add-text 真实写入数据集
    const addRes = await fetch('/api/dataset/add-text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texts }),
    });
    const addData = await addRes.json();

    if (addRes.ok && !addData.error) {
      t(`✓ 反馈环: 已将 ${texts.length} 条异常时间点文本加入数据集`, 'done');
      t(`  → 标记为 DEEP 模式待再分析 (source=edm_feedback_nonlinear)`, 'progress');
      t(`  → 请手动切换 trace-engine-web 为 DEEP 模式后运行`, 'log');
      refreshStatus(); refreshTable();
    } else {
      t(`✗ 反馈环: 加入数据集失败 — ${addData.error || addRes.status}`, 'error');
    }
  } catch (e) {
    t(`✗ 反馈环异常: ${e.message}`, 'error');
  }
}

async function triggerEDMWithFeedback() {
  const target = document.getElementById('edmTarget').value;
  const predictWindow = parseInt(document.getElementById('edmPredictWindow').value) || 3;
  if (!target || target === '__placeholder__') return;

  tClear(); t(`▶ 触发 EDM: target=${target}, 预测窗口=${predictWindow}步`, 'progress');
  const edmBtn = document.getElementById('btnEDM');
  edmBtn.disabled = true; edmBtn.textContent = '⏳ EDM运行中...';

  try {
    // 1. 提交EDM任务
    const r = await fetch('/api/edm/trigger', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target, q: 3, predict_window: predictWindow }),
    });
    const d = await r.json();

    if (!d.success) {
      t(`✗ EDM失败: ${d.error || d.output || d.stderr || '请确认 edm-takens-web 已启动 (python run_backend.py)'}`, 'error');
      edmBtn.disabled = false; edmBtn.textContent = '▶ 触发 EDM 分析';
      return;
    }

    const jobId = d.job_id;
    t(`EDM任务已提交: ${jobId}`, 'progress');
    t('轮询结果中 (每3秒)...', 'log');

    // 2. 轮询直到完成
    let status = 'pending';
    let attempts = 0;
    while (status === 'pending' || status === 'running') {
      await new Promise(r => setTimeout(r, 3000));
      attempts++;
      try {
        // P2-fix: 通过 trace-to-edm 后端代理轮询 (避免浏览器 CORS)
        // 之前直接 fetch http://localhost:8000 → 跨域被浏览器阻拦 (CORS)
        const sr = await fetch(`/api/edm/poll/${jobId}`);
        const sd = await sr.json();
        status = sd.status || 'unknown';
        t(`  [${attempts}] status=${status}`, 'dim');
      } catch (e) {
        t(`  [${attempts}] 轮询失败: ${e.message}`, 'warn');
      }
      if (attempts > 60) { t('⏰ EDM超时', 'warn'); break; }
    }

    // 3. 检查结果 — 是否有非线性检测
    if (status === 'completed') {
      t('✓ EDM分析完成', 'done');

      // 尝试拉取结果摘要
      try {
        const rr = await fetch(`/api/edm/poll/${jobId}`);
        const rd = await rr.json();
        t(`结果: ${JSON.stringify(rd).slice(0, 200)}`, 'log');

        // 检测是否有显著非线性信号
        // (简化版: 检查输出文本中是否有 nonlinear/chaos 关键词)
        const resultText = JSON.stringify(rd).toLowerCase();
        const hasNonlinearSignal = resultText.includes('nonlinear')
          || resultText.includes('chaos')
          || resultText.includes('havok');

        if (hasNonlinearSignal) {
          t('⚠ 检测到非线性动力学信号!', 'warn');
          t('→ 建议对异常时间点运行DEEP模式TRACE再分析', 'warn');

          // 元审计 P0 修缮: 真正兑现反馈环承诺
          // 之前代码仅 confirm 后打印消息，未实际调用 /api/dataset/add-text
          if (confirm('EDM检测到非线性突变信号。\n\n是否自动将相关时间点的文本加入数据集 (DEEP模式) 以便深度再分析？')) {
            await enqueueDeepReanalysis(rd);
          }
        } else {
          t('未检测到显著非线性信号, 系统动力学稳定', 'log');
        }
      } catch (e) {
        t(`结果解析: ${e.message}`, 'log');
      }

      refreshStatus(); refreshTable(); refreshChart();
    } else {
      t(`EDM结束: ${status}`, status === 'failed' ? 'error' : 'warn');
    }
  } catch (e) {
    t(`✗ EDM请求失败: ${e.message}`, 'error');
    t(`  提示: 请确认 edm-takens-web 后端运行在 localhost:8000`, 'warn');
  } finally {
    edmBtn.disabled = false;
    edmBtn.textContent = '▶ 触发 EDM 分析 (含反馈检测)';
  }
}

// 元审计 P1 修缮: 移除无效的 removeEventListener 调用
// 之前代码 removeEventListener 传箭头函数，每次都是新引用，什么也没做
// 直接 addEventListener 即可（页面加载时只有一次绑定）
document.getElementById('btnEDM').addEventListener('click', triggerEDMWithFeedback);

// ── 轨迹表格 ──────────────────────────────────────────────
async function refreshTable() {
  try {
    const r = await fetch('/api/trajectory');
    const d = await r.json();
    if (!d.rows || !d.rows.length) {
      document.getElementById('tableWrap').innerHTML = '<p class="dim">暂无数据</p>';
      document.getElementById('edmDataRange').textContent = '无数据 (需≥15行)';
      return;
    }
    // 复用轨迹数据更新数据范围，避免 refreshStatus 再次请求 /api/trajectory
    const timestamps = d.rows.map(row => row.time_step || '').filter(t => t).sort();
    if (timestamps.length) {
      const first = timestamps[0].slice(0, 16);
      const last = timestamps[timestamps.length - 1].slice(0, 16);
      document.getElementById('edmDataRange').textContent =
        `${first} ~ ${last} (${timestamps.length}个时间点)`;
    }
    // 三层体系分组的列选择
    const preferredCols = [
      // Meta
      'time_step', 'source_label',
      // L1: 元SCM — 因果系统诊断
      'ate', 'ci_width', 'edge_count', 'adj_density', 'max_delta_nll',
      'refuted_count', 'ccm_coverage_pct',
      // L2: 世俗语义 — 话语流形坐标
      'z_pca_1', 'z_pca_2', 'z_pca_3', 'secular_entropy',
      // L3: 八正道 — 神圣轴投影 + 漂移
      'z_福音', 'z_存在', 'z_觉爱', 'z_奥美', 'z_自孕',
      'dz_福音', 'dz_存在', 'dz_觉爱', 'dz_奥美',
    ];
    const cols = preferredCols.filter(c => d.columns.includes(c));
    // 按层分组着色
    const layerMap = {
      time_step:'meta', source_label:'meta',
      ate:'l1', ci_width:'l1', edge_count:'l1', adj_density:'l1', max_delta_nll:'l1',
      refuted_count:'l1', ccm_coverage_pct:'l1',
      z_pca_1:'l2', z_pca_2:'l2', z_pca_3:'l2', secular_entropy:'l2',
    };
    const isL3 = c => c.startsWith('z_') || c.startsWith('dz_') || c.startsWith('d2z_');

    let h = '<table><thead><tr>';
    cols.forEach(c => {
      const layer = isL3(c) ? 'l3' : (layerMap[c] || '');
      h += `<th class="${layer}">${c}</th>`;
    });
    h += '</tr></thead><tbody>';
    d.rows.forEach(row => {
      h += '<tr>';
      cols.forEach(c => {
        const v = row[c]||'';
        const isNum = !isNaN(parseFloat(v)) && v !== '';
        // dz_/d2z_ 列: 第一行为空是正常的 (差分需两个点)
        const isDiffCol = c.startsWith('dz_') || c.startsWith('d2z_');
        const diffEmpty = isDiffCol && v === '';
        const display = isNum ? parseFloat(v).toFixed(4) : (v || (diffEmpty ? '—' : ''));
        h += `<td class="${isNum?'num':''} ${diffEmpty?'dim':''}">${display}</td>`;
      });
      h += '</tr>';
    });
    h += '</tbody></table>';
    // 表注: 层分布
    const l1c = cols.filter(c => layerMap[c]==='l1').length;
    const l2c = cols.filter(c => layerMap[c]==='l2').length;
    const l3c = cols.filter(c => isL3(c)).length;
    h += `<div style="font-size:0.5rem;color:var(--muted);margin-top:4px">
      <span style="color:var(--accent)">L1:${l1c}列</span>
      <span style="color:var(--accent2);margin-left:8px">L2:${l2c}列</span>
      <span style="color:#c084fc;margin-left:8px">L3:${l3c}列</span>
    </div>`;
    document.getElementById('tableWrap').innerHTML = h;
  } catch (e) { document.getElementById('tableWrap').innerHTML = `<p class="dim">错误: ${e.message}</p>`; }
}

// ── 杂项 ──────────────────────────────────────────────────
const btnClearTerm = document.getElementById('btnClearTerm');
if (btnClearTerm) btnClearTerm.addEventListener('click', tClear);
const btnRefreshTable = document.getElementById('btnRefreshTable');
if (btnRefreshTable) btnRefreshTable.addEventListener('click', refreshTable);

// 日志过滤工具栏事件绑定
['progress','info','warn','error','done'].forEach(l => {
  const cb = document.getElementById(`filter${l.charAt(0).toUpperCase() + l.slice(1)}`);
  if (cb) cb.addEventListener('change', (e) => setLogFilter(l, e.target.checked));
});
const btnLogPause = document.getElementById('btnLogPause');
if (btnLogPause) btnLogPause.addEventListener('click', toggleLogPause);

// 暴露内部函数供最小化单元测试
window.__traceToEdmTestHarness = {
  t, tClear, setLogFilter, toggleLogPause, renderLogs, logState,
  escapeHtml: window.LogCockpit ? window.LogCockpit.escapeHtml : (s => s),
};

// 任务时钟（右上角）
function updateMissionClock() {
  const el = document.getElementById('missionClock');
  if (!el) return;
  const now = new Date();
  el.textContent = now.toLocaleTimeString('zh-CN', { hour12: false });
}
setInterval(updateMissionClock, 1000);
updateMissionClock();

// ── 启动 ──────────────────────────────────────────────────
refreshModels();
refreshProjects();
refreshInputs();
refreshStatus();
refreshDataset();
refreshTable();
refreshChart();
// 降低状态轮询频率以减少隧道开销；数据范围由 refreshTable 复用轨迹数据更新
setInterval(refreshStatus, 30000);
