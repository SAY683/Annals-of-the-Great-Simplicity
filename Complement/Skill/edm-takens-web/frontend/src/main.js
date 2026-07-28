import '../shared/themes/tokusatsu.css'
import './style.css'

const API_PREFIX = '/api'

const $ = (sel) => document.querySelector(sel)

// Escape dynamic text before injecting into innerHTML to prevent XSS.
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

let lastQualityData = null

async function apiJson(url, opts = {}) {
  const res = await fetch(API_PREFIX + url, opts)
  if (!res.ok) {
    const txt = await res.text()
    throw new Error(`${res.status}: ${txt}`)
  }
  return res.json()
}

async function refreshDatasets() {
  try {
    const { datasets } = await apiJson('/datasets')
    const sel = $('#datasetSelect')
    sel.innerHTML = '<option value="">-- 选择数据集 --</option>'
    if (!datasets || datasets.length === 0) {
      console.warn('No datasets found')
      const status = $('#uploadStatus')
      if (status) status.textContent = '暂无已上传数据集，请上传 CSV 文件。'
      return
    }
    datasets.forEach((name) => {
      const opt = document.createElement('option')
      opt.value = name
      opt.textContent = name || '(未命名)'
      sel.appendChild(opt)
    })
    const status = $('#uploadStatus')
    if (status && status.textContent.includes('暂无已上传')) {
      status.textContent = ''
    }
  } catch (e) {
    console.error('refreshDatasets:', e)
    const sel = $('#datasetSelect')
    if (sel) sel.innerHTML = '<option value="">加载失败</option>'
    const status = $('#uploadStatus')
    if (status) status.textContent = `数据集列表加载失败: ${e.message}`
  }
}

function setStatusValue(id, value) {
  const el = document.getElementById(id)
  if (!el) return
  if (value == null || value === '') {
    el.textContent = ''
    el.dataset.empty = 'true'
  } else {
    el.textContent = value
    el.dataset.empty = 'false'
  }
}

function updateStatusWall(options = {}) {
  const wall = $('#statusWall')
  if (!wall) return
  // P1-f 修缮：数据集就绪 或 有分析历史时都显示状态墙
  if (options.dataset || (options.analyses && options.analyses > 0)) {
    wall.classList.remove('awaiting-data')
  }
  if (options.dataset != null) setStatusValue('statusDataset', options.dataset)
  if (options.target != null) setStatusValue('statusTarget', options.target)
  if (options.rows != null) setStatusValue('statusRows', options.rows)
  if (options.q != null) setStatusValue('statusQ', options.q)
  if (options.analyses != null) setStatusValue('statusAnalyses', options.analyses)
  // P1-f 修缮：MODE 字段动态更新（之前硬编码为 OBS，从不变化）
  if (options.mode != null) setStatusValue('statusMode', options.mode)
}

// P1-f 修缮：分析强度 → MODE 显示名映射
const INTENSITY_TO_MODE = {
  auto: 'AUTO',
  light: 'LIGHT',
  medium: 'DEEP',
  heavy: 'SUPER',
}

// P1-f 修缮：监听分析强度变化，实时更新状态墙 MODE 字段
document.addEventListener('DOMContentLoaded', () => {
  const intensitySel = $('#intensitySelect')
  if (intensitySel) {
    // 初始化时设置当前 MODE
    updateStatusWall({ mode: INTENSITY_TO_MODE[intensitySel.value] || 'OBS' })
    intensitySel.addEventListener('change', (e) => {
      updateStatusWall({ mode: INTENSITY_TO_MODE[e.target.value] || 'OBS' })
    })
  }
})

// P1-f 修缮：真实健康检查 — 定期轮询后端 /api/health，更新状态点
async function checkBackendHealth() {
  const statusDot = document.querySelector('.status-dot')
  if (!statusDot) return
  try {
    const res = await fetch('/api/health', { timeout: 5000 })
    if (res.ok) {
      statusDot.classList.remove('offline')
      statusDot.classList.add('online')
      statusDot.innerHTML = '<span></span>SYSTEM ONLINE'
    } else {
      throw new Error(`HTTP ${res.status}`)
    }
  } catch {
    statusDot.classList.remove('online')
    statusDot.classList.add('offline')
    statusDot.innerHTML = '<span></span>BACKEND OFFLINE'
  }
}

// P1-f 修缮：跨项目导航点健康检查 — 轮询其他项目的 /api/health
// debt-12.15 隧道模式适配: 隧道下 (https://xxx.trycloudflare.com) 不能 fetch
// 本地 http://127.0.0.1:xxxx（混合内容拦截），改为跳过健康检查，避免误显示离线
const NAV_TARGETS = [
  { port: 3000, selector: '.base-nav a[href*=":3000"]' },
  { port: 3100, selector: '.base-nav a[href*=":3100"]' },
]

function _isTunnelMode() {
  try {
    const host = window.location.hostname;
    return host.includes('trycloudflare.com') || (window.location.protocol === 'https:' && !host.match(/^(localhost|127\.0\.0\.1)$/));
  } catch { return false; }
}

async function checkNavHealth() {
  // 隧道模式下跳过跨项目健康检查（混合内容拦截，会误显示离线）
  if (_isTunnelMode()) {
    for (const target of NAV_TARGETS) {
      const link = document.querySelector(target.selector)
      const dot = link?.querySelector('.nav-dot')
      if (dot) {
        dot.style.opacity = '0.6'
        dot.title = '隧道模式（不检测本地服务）'
      }
    }
    return
  }
  for (const target of NAV_TARGETS) {
    const link = document.querySelector(target.selector)
    if (!link) continue
    const dot = link.querySelector('.nav-dot')
    if (!dot) continue
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 3000)
      const res = await fetch(`http://127.0.0.1:${target.port}/api/health`, {
        signal: controller.signal,
      })
      clearTimeout(timeout)
      if (res.ok) {
        dot.style.opacity = '1'
        dot.title = '在线'
      } else {
        dot.style.opacity = '0.3'
        dot.title = '离线'
      }
    } catch {
      dot.style.opacity = '0.3'
      dot.title = '离线'
    }
  }
}

async function loadDatasetColumns(filename) {
  try {
    const info = await apiJson(`/datasets/${encodeURIComponent(filename)}/columns`)
    // P1 修复 (Round 24 §2): 配置列信息使用分行布局, 避免长串列名撑出长条.
    // 数值列名以 chip 形式独立换行, 不再是一行长文本.
    const numericCols = info.numeric_columns || []
    const colsChips = numericCols.map((c) => `<span class="col-chip">${escapeHtml(c)}</span>`).join('')
    $('#columnInfo').innerHTML = `
      <div class="col-info-line"><strong>${escapeHtml(filename)}</strong></div>
      <div class="col-info-line">行数: ${info.rows} &nbsp;|&nbsp; 数值列: ${numericCols.length} 个</div>
      ${colsChips ? `<div class="col-info-chips">${colsChips}</div>` : ''}
    `
    const targetSel = $('#targetSelect')
    targetSel.innerHTML = ''
    info.numeric_columns.forEach((col) => {
      const opt = document.createElement('option')
      opt.value = col
      opt.textContent = col
      targetSel.appendChild(opt)
    })
    // Default to the backend's recommended target (avoids ID columns like game/id)
    if (info.recommended_target) {
      targetSel.value = info.recommended_target
    }
    await loadRecommendation(filename)
    await loadQuality(filename)
    $('#runBtn').disabled = false
    // 状态墙：数据集就绪后显示并回填基础信息
    updateStatusWall({
      dataset: filename,
      rows: info.rows,
      target: targetSel.value,
      q: $('#qInput').value || '自动',
      analyses: 0
    })
    // UX: 数据集就绪后将运行按钮滚动到可视区域，避免长页面中按钮被淹没
    setTimeout(() => $('#runBtn').scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100)
  } catch (e) {
    $('#columnInfo').innerHTML = `<span style="color:red">加载失败: ${escapeHtml(e.message)}</span>`
    $('#runBtn').disabled = true
  }
}

async function loadRecommendation(filename) {
  const target_col = $('#targetSelect').value
  const variables = $('#variablesInput').value
  const params = new URLSearchParams()
  if (target_col) params.set('target_col', target_col)
  if (variables) params.set('variables', variables)
  try {
    const profile = await apiJson(`/datasets/${encodeURIComponent(filename)}/recommend?${params}`)
    const intensitySel = $('#intensitySelect')
    if (profile.level && Array.from(intensitySel.options).some((o) => o.value === profile.level)) {
      intensitySel.value = profile.level
    }
    const box = $('#intensityRecommendation')
    if (profile.notes && profile.notes.length) {
      box.style.display = 'block'
      const paramsText = profile.params
        ? `q=${profile.params.q ?? '自动'}, max_e=${profile.params.max_e}, auto_fix=${profile.params.auto_fix}`
        : ''
      box.innerHTML = `
        <strong>推荐强度: ${escapeHtml(profile.level)}</strong> ${paramsText ? `(${escapeHtml(paramsText)})` : ''}
        <ul>${profile.notes.map((n) => `<li>${escapeHtml(n)}</li>`).join('')}</ul>
      `
    } else {
      box.style.display = 'none'
      box.innerHTML = ''
    }
  } catch (e) {
    $('#intensityRecommendation').style.display = 'none'
  }
}

async function loadQuality(filename) {
  const target_col = $('#targetSelect').value
  const variables = $('#variablesInput').value
  const params = new URLSearchParams()
  if (target_col) params.set('target_col', target_col)
  if (variables) params.set('variables', variables)
  const container = $('#qualityList')
  try {
    const data = await apiJson(`/datasets/${encodeURIComponent(filename)}/quality?${params}`)
    lastQualityData = data
    const ds = data.columns._dataset || {}
    const cols = Object.entries(data.columns).filter(([k]) => !k.startsWith('_'))
    if (!cols.length) {
      container.innerHTML = '无可评估列。'
      return
    }
    const dupRows = ds.duplicate_rows || {}
    const dupTs = ds.duplicate_timestamps || {}
    const datasetNote = []
    if (ds.n_numeric != null) {
      datasetNote.push(`数值列: ${ds.n_numeric} | 已选: ${ds.n_selected} | 二值: ${ds.n_binary}`)
    }
    if (dupRows.n_duplicate_rows) {
      datasetNote.push(`重复行: ${dupRows.n_duplicate_rows} (${(dupRows.fraction * 100).toFixed(1)}%)`)
    }
    if (dupTs.n_duplicate_timestamps) {
      datasetNote.push(`重复时间戳(${dupTs.time_column || '?'}): ${dupTs.n_duplicate_timestamps}`)
    }
    const datasetWarnings = ds.dataset_warnings || []
    const rows = cols.map(([name, q]) => {
      const statusClass = q.usable_for_edm ? 'ok' : 'bad'
      const statusText = q.usable_for_edm ? '可用' : '不建议'
      const badges = []
      if (q.is_target) badges.push('<span class="badge target">目标</span>')
      if (q.selected && !q.is_target) badges.push('<span class="badge selected">已选</span>')
      if (!q.selected) badges.push('<span class="badge muted">未选</span>')
      const warnText = q.warnings.length
        ? q.warnings.map((w) => escapeHtml(w)).join('；')
        : ''
      const warnings = warnText
        ? `<span class="warn-cell" data-warn="${warnText}">${q.warnings.length} 条警告</span>`
        : '<span class="ok">无</span>'
      return `
        <tr class="${q.selected ? 'selected-row' : ''}">
          <td><strong>${escapeHtml(name)}</strong> ${badges.join(' ')}</td>
          <td class="${statusClass}">${statusText}</td>
          <td>${q.n}</td>
          <td>${(q.missing_ratio * 100).toFixed(1)}%</td>
          <td>${q.unique_count}</td>
          <td>${q.std != null ? q.std.toExponential(2) : '-'}</td>
          <td>${q.lag1_autocorr != null ? q.lag1_autocorr.toFixed(2) : '-'}</td>
          <td>${q.trend_score != null ? q.trend_score.toFixed(2) : '-'}</td>
          <td>${warnings}</td>
        </tr>
      `
    }).join('')
    container.innerHTML = `
      ${datasetWarnings.length ? `<div class="dataset-warn"><strong>数据集级提示：</strong><ul>${datasetWarnings.map((w) => `<li>${escapeHtml(w)}</li>`).join('')}</ul></div>` : ''}
      ${datasetNote.length ? `<p class="dim">${datasetNote.join(' | ')}</p>` : ''}
      <div class="quality-table-wrap">
        <table class="quality-table">
          <thead>
            <tr>
              <th>列名</th>
              <th>EDM 可用</th>
              <th>N</th>
              <th>缺失</th>
              <th>唯一值</th>
              <th>标准差</th>
              <th>lag1 自相关</th>
              <th>趋势分</th>
              <th>警告</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `
  } catch (e) {
    container.innerHTML = `<p class="error">加载数据质量失败: ${escapeHtml(e.message)}</p>`
  }
}

async function uploadFile() {
  const input = $('#csvInput')
  if (!input.files.length) return
  const file = input.files[0]
  const form = new FormData()
  form.append('file', file)
  $('#uploadStatus').textContent = '上传中...'
  try {
    const res = await apiJson('/upload', { method: 'POST', body: form })
    $('#uploadStatus').textContent = `已上传: ${res.filename}`
    // 等待后端文件系统刷新后重新拉取列表
    await new Promise((resolve) => setTimeout(resolve, 200))
    await refreshDatasets()
    // Ensure the newly uploaded file is selectable before forcing selection.
    const sel = $('#datasetSelect')
    let found = Array.from(sel.options).some((o) => o.value === res.filename)
    if (!found) {
      await new Promise((resolve) => setTimeout(resolve, 300))
      await refreshDatasets()
      found = Array.from(sel.options).some((o) => o.value === res.filename)
    }
    if (found) {
      sel.value = res.filename
      await loadDatasetColumns(res.filename)
    } else {
      $('#uploadStatus').textContent += ' （刷新后未找到该文件，请手动选择）'
    }
  } catch (e) {
    $('#uploadStatus').textContent = `上传失败: ${e.message}`
  }
}

function clearTerminal() {
  const term = $('#terminal')
  term.innerHTML = ''
  return term
}

function appendTerminal(text, type = 'info') {
  const term = $('#terminal')
  // 过滤无意义行：空行、纯分隔符行（ASCII #### ==== ---- **** 或 Unicode 制表符 ─━│┃═║ 等）
  const trimmed = String(text).trim()
  if (!trimmed) return
  // 去除空格后检测纯分隔符（如 "── ── ──" → "────────"）
  const noSpaces = trimmed.replace(/\s+/g, '')
  if (/^[#=\-*+_~─━│┃═║╔╗╚╝╠╣╦╩╬]+$/.test(noSpaces)) return
  // 过滤单字符重复 4 次以上的纯分隔行（如 ────── 或 ======）
  if (/^(.)\1{4,}$/.test(noSpaces)) return
  // 过滤纯图标行（单个符号无实际内容）
  if (/^[◉▶▲✖✓✦○●◇◆□■△▽☆★]+$/.test(noSpaces)) return

  const line = document.createElement('div')
  const typeMap = { cmd: 'stage', success: 'stage', dim: 'info' }
  const themeType = typeMap[type] || type || 'info'
  line.className = `terminal-line ${themeType}`

  const iconMap = { stage: '▶', info: '◉', warn: '▲', error: '✖' }
  const icon = iconMap[themeType] || '◉'

  const iconSpan = document.createElement('span')
  iconSpan.className = 'log-icon'
  iconSpan.textContent = icon

  const msgSpan = document.createElement('span')
  msgSpan.className = 'log-msg'
  msgSpan.textContent = text

  line.appendChild(iconSpan)
  line.appendChild(msgSpan)
  term.appendChild(line)
  term.scrollTop = term.scrollHeight
}

function setTerminalStatus(status) {
  const el = $('#terminalStatus')
  el.textContent = status
  el.className = 'terminal-status ' + status
}

function setTerminalJobId(jobId) {
  const el = $('#terminalJobId')
  el.textContent = jobId ? `job: ${jobId}` : ''
}

async function pollJobStatus(jobId, onStatus) {
  try {
    const data = await apiJson(`/analyze/jobs/${encodeURIComponent(jobId)}`)
    onStatus(data)
    return data
  } catch (e) {
    appendTerminal(`[poll] ${e.message}`, 'error')
    return null
  }
}

async function runAnalysis() {
  const filename = $('#datasetSelect').value
  if (!filename) {
    alert('请先选择一个数据集')
    return
  }
  const target_col = $('#targetSelect').value
  const variables = $('#variablesInput').value
  const q = $('#qInput').value
  // q 范围校验：允许留空（自动检测），填则必须是 2-64 之间的整数。
  if (q !== '') {
    const qNum = Number(q)
    if (!Number.isInteger(qNum) || qNum < 2 || qNum > 64) {
      alert('嵌入维度 q 必须是 2 到 64 之间的整数（留空则自动检测）')
      return
    }
  }
  const project_name = $('#projectNameInput').value.trim()
  const intensity = $('#intensitySelect').value
  const auto_fix = $('#autoFixCheckbox').checked

  // Pre-run quality guard: warn if the selected target column is flagged unusable.
  if (lastQualityData && lastQualityData.columns && lastQualityData.columns[target_col]) {
    const qcol = lastQualityData.columns[target_col]
    if (!qcol.usable_for_edm) {
      const warningLines = qcol.warnings.length ? qcol.warnings.join('\n') : '目标列当前不可用，可能导致分析失败或结果不可靠。'
      const proceed = confirm(`目标列 "${target_col}" 当前不建议用于 EDM：\n\n${warningLines}\n\n仍要继续运行吗？`)
      if (!proceed) return
    }
  }

  // P1 fix (Round 22 §5): 添加进度条, 让用户在长时间运行中看到实时进度
  $('#summary').innerHTML = '<p>初始化分析任务...</p><div id="jobProgressLabel">准备中...</div><progress id="jobProgress" max="100" value="0"></progress>'
  $('#images').innerHTML = ''
  $('#runBtn').disabled = true
  clearTerminal()
  setTerminalStatus('running')
  setTerminalJobId('')
  appendTerminal(`> 创建任务: ${filename} | target=${target_col} | auto_fix=${auto_fix}`, 'cmd')

  const form = new FormData()
  form.append('filename', filename)
  form.append('target_col', target_col)
  if (variables) form.append('variables', variables)
  if (q) form.append('q', q)
  if (project_name) form.append('project_name', project_name)
  form.append('intensity', intensity)
  form.append('auto_fix', auto_fix ? 'true' : 'false')

  let jobId = null
  try {
    const job = await apiJson('/analyze/jobs', { method: 'POST', body: form })
    jobId = job.job_id
    setTerminalJobId(jobId)
    appendTerminal(`> job_id: ${jobId} | status: ${job.status}`, 'cmd')
  } catch (e) {
    appendTerminal(`ERROR: ${e.message}`, 'error')
    $('#summary').innerHTML = `<p class="error">创建任务失败: ${e.message}</p>`
    setTerminalStatus('error')
    $('#runBtn').disabled = false
    return
  }

  // Poll status every 2s so the UI shows pending/running/done even if the
  // stream briefly disconnects.
  let finalData = null
  let streamError = null
  // P1 修复 (Round 24 §3): 重写进度条逻辑 — 通过解析日志中的 STAGE 标记
  // 区分 EDM 流水线的三个阶段 (Pipeline / Cross-Validation / Interpretation),
  // 在各阶段内根据子阶段标记更新进度, 不再恒卡 90%.
  // 阶段映射:
  //   pending            → 5%
  //   Stage 1: Pipeline  → 10-40% (env/audit/HAVOK/CCM)
  //   Stage 2: Cross-Val → 40-70% (3 safeguards)
  //   Stage 3: Interp    → 70-95% (EDM/HAVOK/CCM interpretation)
  //   done               → 100%
  //   error              → 100%
  const STAGE_PATTERNS = [
    { re: /STAGE\s*1\s*\/\s*3.*Pipeline/i, min: 10, max: 40, label: 'Stage 1: 流水线 (环境+审计+HAVOK+CCM)' },
    { re: /STAGE\s*2\s*\/\s*3.*Cross.?Validation/i, min: 40, max: 70, label: 'Stage 2: 交叉验证 (3 重保险)' },
    { re: /STAGE\s*3\s*\/\s*3.*Interpretation/i, min: 70, max: 95, label: 'Stage 3: 动力学解释' },
  ]
  // 子阶段标记 (用于在主阶段内细分进度)
  const SUBSTAGE_PATTERNS = [
    { re: /PHASE\s*1.*Individual Variable Dynamics/i, bump: 5 },
    { re: /PHASE\s*2.*Causal Structure/i, bump: 5 },
    { re: /AUDIT|审计/i, bump: 3 },
    { re: /HAVOK|SovereignHAVOK/i, bump: 3 },
    { re: /CCM|Convergent Cross Mapping/i, bump: 3 },
    { re: /Visualization saved|图已保存/i, bump: 5 },
    { re: /Config saved|配置已保存/i, bump: 2 },
    { re: /Interpretation complete/i, bump: 5 },
  ]
  const updateProgress = (status, logs) => {
    const bar = $('#jobProgress')
    const label = $('#jobProgressLabel')
    if (!bar || !label) return
    let pct = 0
    let text = '准备中...'
    if (status === 'pending') {
      pct = 5
      text = '排队中...'
    } else if (status === 'running') {
      const lines = logs || []
      // 1. 找到当前所处的最高阶段
      let currentStageIdx = -1
      for (let i = 0; i < STAGE_PATTERNS.length; i++) {
        const hasStage = lines.some((l) => STAGE_PATTERNS[i].re.test(l))
        if (hasStage) currentStageIdx = i
      }
      if (currentStageIdx === -1) {
        // 还没进入 Stage 1, 仍在准备阶段
        pct = 8
        text = '运行中: 初始化环境...'
      } else {
        const stage = STAGE_PATTERNS[currentStageIdx]
        // 2. 在当前阶段内, 通过子阶段标记细分
        let bumpTotal = 0
        for (const sp of SUBSTAGE_PATTERNS) {
          if (lines.some((l) => sp.re.test(l))) bumpTotal += sp.bump
        }
        // 3. 用日志行数微调 (在阶段区间内插值, 避免恒卡)
        const logProgress = Math.min(1, lines.length / 200)
        const stageRange = stage.max - stage.min
        // 子阶段 bump 不超过阶段范围的 60%, 剩余 40% 给日志微调
        const bumpCapped = Math.min(stageRange * 0.6, bumpTotal)
        pct = Math.min(stage.max - 1, stage.min + bumpCapped + logProgress * (stageRange * 0.4))
        pct = Math.round(pct)
        text = `运行中: ${stage.label} (${pct}%)`
      }
    } else if (status === 'done') {
      pct = 100
      text = '完成 ✓'
    } else if (status === 'error') {
      pct = 100
      text = '失败 ✗'
    } else if (status === 'interrupted') {
      // ROB-03: 后端重启导致任务被中断，视为终态停止轮询
      pct = 100
      text = '已中断 ⚠'
    }
    bar.value = pct
    label.textContent = text
  }
  const pollInterval = setInterval(async () => {
    const data = await pollJobStatus(jobId, (data) => {
      setTerminalStatus(data.status)
      updateProgress(data.status, data.logs)
    })
    // ROB-03: "interrupted" 也是终态，需停止轮询，否则会无限轮询被中断的任务
    if (data && (data.status === 'done' || data.status === 'error' || data.status === 'interrupted')) {
      clearInterval(pollInterval)
      updateProgress(data.status, data.logs)
    }
  }, 2000)

  try {
    const response = await fetch(`${API_PREFIX}/analyze/jobs/${encodeURIComponent(jobId)}/stream`)
    if (!response.ok) {
      const text = await response.text()
      throw new Error(`${response.status}: ${text}`)
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const msg = JSON.parse(line)
          if (msg.type === 'log') {
            appendTerminal(msg.data)
          } else if (msg.type === 'result') {
            finalData = msg.data
            appendTerminal('> 分析完成。', 'success')
          } else if (msg.type === 'error') {
            streamError = msg.data.detail
            appendTerminal(`ERROR: ${msg.data.detail}`, 'error')
            $('#summary').innerHTML = `<p class="error">运行失败: ${msg.data.detail}</p>`
          }
        } catch (e) {
          appendTerminal(line)
        }
      }
    }

    // If the stream ended without a clear result/error, do a final status poll.
    if (!finalData && !streamError) {
      const data = await pollJobStatus(jobId, () => {})
      if (data) {
        setTerminalStatus(data.status)
        if (data.status === 'done' && data.result) {
          finalData = data.result
        } else if (data.status === 'error' && data.error) {
          streamError = data.error
          appendTerminal(`ERROR: ${data.error}`, 'error')
          $('#summary').innerHTML = `<p class="error">运行失败: ${data.error}</p>`
        } else if (data.status === 'interrupted') {
          // ROB-03: 后端重启导致任务被中断
          streamError = data.error || '任务因后端重启而被中断'
          appendTerminal(`INTERRUPTED: ${streamError}`, 'error')
          $('#summary').innerHTML = `<p class="error">任务被中断: ${escapeHtml(streamError)}</p>`
        }
      }
    }

    if (finalData) {
      renderSummary(finalData.summary)
      renderImages(finalData.images, finalData.task_id)
      const nameText = finalData.summary && finalData.summary.project_name
        ? `项目: ${finalData.summary.project_name}`
        : `task ${finalData.task_id}`
      $('#summary').insertAdjacentHTML('afterbegin', `<p class="success">分析成功: ${finalData.filename} <span class="dim">(${nameText})</span></p>`)
      // P1 fix (Round 26 §8): 人话版默认内联卡片渲染，保留原文链接
      const exportBar = document.createElement('div')
      exportBar.style.cssText = 'display:flex;gap:8px;justify-content:center;margin:8px 0;flex-wrap:wrap;'
      const btnMd = document.createElement('button')
      btnMd.className = 'small export-md-btn'
      btnMd.title = '在结果面板下方内联渲染人话版卡片'
      btnMd.textContent = '📝 人话版'
      btnMd.addEventListener('click', () => renderHumanReportInline(finalData.task_id))
      const btnJson = document.createElement('button')
      btnJson.className = 'small'
      btnJson.textContent = '⬇ JSON'
      btnJson.addEventListener('click', () => downloadExport(finalData.task_id, 'json'))
      const btnCsv = document.createElement('button')
      btnCsv.className = 'small'
      btnCsv.textContent = '⬇ CSV'
      btnCsv.addEventListener('click', () => downloadExport(finalData.task_id, 'csv'))
      exportBar.appendChild(btnMd)
      exportBar.appendChild(btnJson)
      exportBar.appendChild(btnCsv)
      $('#summary').insertBefore(exportBar, $('#summary').firstChild)
      setTerminalStatus('done')
      loadHistory()
    } else if (streamError) {
      setTerminalStatus('error')
    } else {
      setTerminalStatus('done')
      appendTerminal('> 流已结束，未收到结果。', 'dim')
    }
  } catch (e) {
    appendTerminal(`ERROR: ${e.message}`, 'error')
    $('#summary').innerHTML = `<p class="error">运行失败: ${escapeHtml(e.message)}</p>`
    setTerminalStatus('error')
  } finally {
    clearInterval(pollInterval)
    $('#runBtn').disabled = false
  }
}

function renderSummary(summary) {
  const rows = []

  // 审计裁决面板
  const verdict = summary.post_audit_verdict
  if (verdict) {
    const normalized = String(verdict).toUpperCase()
    let vClass = 'warn'
    let vText = 'WARN'
    let vStamp = '▲'
    if (normalized === 'PASS' || normalized === 'PASS_WITH_NOTES') {
      vClass = 'pass'
      vText = 'PASS'
      vStamp = '✓'
    } else if (normalized === 'FAIL' || normalized === 'BLOCKED') {
      vClass = 'fail'
      vText = 'FAIL'
      vStamp = '✖'
    } else if (normalized === 'INCONCLUSIVE') {
      vClass = 'warn'
      vText = 'INCONCLUSIVE'
      vStamp = '▲'
    }
    rows.push(`<div class="audit-verdict ${vClass}"><span class="verdict-stamp">${vStamp}</span><span>${vText}</span></div>`)
  }

  if (summary.project_name) {
    rows.push(`<p><strong>项目名称:</strong> ${escapeHtml(summary.project_name)}</p>`)
  }
  if (summary.intensity) {
    rows.push(`<p><strong>分析强度:</strong> ${escapeHtml(summary.intensity)}`)
    if (summary.intensity_params) {
      const p = summary.intensity_params
      rows.push(` (q=${p.q ?? '自动'}, max_e=${p.max_e}, auto_fix=${p.auto_fix})`)
    }
    rows.push('</p>')
  }
  rows.push(`<p><strong>Pipeline:</strong> ${escapeHtml(summary.pipeline ?? '-')}</p>`)
  rows.push(`<p><strong>Cross-validation:</strong> ${escapeHtml(summary.cross_validation ?? '-')}</p>`)
  rows.push(`<p><strong>Interpretation:</strong> ${escapeHtml(summary.interpretation ?? '-')}</p>`)
  if (summary.havok) {
    const h = summary.havok
    // 空值保护：后端某些字段可能缺失，使用可选链 + 默认值兜底，
    // 避免对 undefined/NaN 调用 .toFixed() 抛错导致渲染中断。
    const explainedVar = h?.explained_variance
    const regR2 = h?.regression_r2
    const kurt = h?.kurtosis
    const maxEig = h?.max_eigenvalue
    rows.push(`
      <h4>HAVOK 诊断</h4>
      <ul>
        <li>Rank r: ${h?.rank ?? '-'}</li>
        <li>解释方差: ${(typeof explainedVar === 'number' && !isNaN(explainedVar))
          ? (explainedVar * 100).toFixed(1) + '%'
          : '-'}</li>
        <li>回归 R²: ${(typeof regR2 === 'number' && !isNaN(regR2))
          ? regR2.toFixed(4)
          : '-'}</li>
        <li>强迫项峰度: ${(typeof kurt === 'number' && !isNaN(kurt))
          ? kurt.toFixed(3)
          : '-'}</li>
        <li>最大离散特征值: ${(typeof maxEig === 'number' && !isNaN(maxEig))
          ? maxEig.toFixed(4)
          : '-'}</li>
      </ul>
    `)
  }
  if (summary.stability_tier) {
    rows.push(`<p><strong>稳定性层级:</strong> ${escapeHtml(summary.stability_tier)}</p>`)
  }
  if (summary.heavy_tailed_variables) {
    rows.push(`<p><strong>重尾变量:</strong> ${escapeHtml(summary.heavy_tailed_variables.join(', ') || '无')}</p>`)
  }
  if (typeof summary.n_ccm_significant === 'number') {
    rows.push(`<p><strong>显著 CCM 因果对:</strong> ${summary.n_ccm_significant}</p>`)
  }
  $('#summary').innerHTML = rows.join('')
}

function renderImages(images, taskId) {
  const container = $('#images')
  container.innerHTML = ''
  if (!images.length) {
    container.innerHTML = '<p>未生成图片。</p>'
    return
  }
  const prefix = taskId ? `${encodeURIComponent(taskId)}/` : ''
  images.forEach((name) => {
    const wrapper = document.createElement('div')
    wrapper.className = 'image-card'
    const title = document.createElement('h4')
    title.textContent = name
    const img = document.createElement('img')
    img.src = `${API_PREFIX}/results/${prefix}${encodeURIComponent(name)}?t=${Date.now()}`
    img.alt = name
    wrapper.appendChild(title)
    wrapper.appendChild(img)
    container.appendChild(wrapper)
  })
}

async function loadHistory() {
  const container = $('#historyList')
  try {
    const tasks = await apiJson('/history')
    updateStatusWall({ analyses: tasks.length })
    if (!tasks.length) {
      container.innerHTML = '暂无历史数据。'
      $('#historyBatchToolbar').style.display = 'none'
      return
    }
    $('#historyBatchToolbar').style.display = 'flex'
    updateBatchToolbar()

    container.innerHTML = tasks.map((task) => {
      const date = new Date(task.updated_at * 1000).toLocaleString('zh-CN')
      const tid = escapeHtml(task.task_id)
      const thumbs = task.images.map((img) => {
        const src = `${API_PREFIX}/results/${encodeURIComponent(task.task_id)}/${encodeURIComponent(img)}`
        const eimg = escapeHtml(img)
        return `<img src="${src}" alt="${eimg}" title="${eimg}" data-full="${src}" />`
      }).join('')
      return `
        <div class="history-item" data-task-id="${tid}">
          <label class="history-checkbox">
            <input type="checkbox" value="${tid}" />
            <span>选择</span>
          </label>
          <h4>${tid}</h4>
          <div class="meta">更新时间: ${escapeHtml(date)} | 图片: ${task.images.length} 张 ${task.has_config ? '| 含配置' : ''}</div>
          <div class="actions">
            <button class="small view-btn" data-task="${tid}">查看</button>
            <button class="small download-btn" data-task="${tid}">下载 zip</button>
            <button class="small archive-btn" data-task="${tid}">归档</button>
            <button class="small compare-select-btn" data-task="${tid}">对比</button>
            <button class="small export-json-btn" data-task="${tid}">JSON</button>
            <button class="small export-csv-btn" data-task="${tid}">CSV</button>
            <button class="small export-md-btn" data-task="${tid}" title="导出人话版 Markdown 报告">📝人话版</button>
            <button class="small danger delete-btn" data-task="${tid}">删除</button>
          </div>
          <div class="thumbs">${thumbs || '<span class="dim">无图片</span>'}</div>
        </div>
      `
    }).join('')

    // Click thumbnail to open full image
    container.querySelectorAll('.thumbs img').forEach((img) => {
      img.addEventListener('click', () => window.open(img.dataset.full, '_blank'))
    })

    // Checkboxes
    container.querySelectorAll('.history-checkbox input').forEach((cb) => {
      cb.addEventListener('change', () => {
        updateBatchToolbar()
        updateCompareSelectionState()
      })
    })

    // Download / archive / delete / compare-select buttons
    container.querySelectorAll('.view-btn').forEach((btn) => {
      btn.addEventListener('click', () => viewHistoryTask(btn.dataset.task))
    })
    container.querySelectorAll('.download-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.task
        downloadFile(`${API_PREFIX}/history/${encodeURIComponent(id)}/download`, `${id}.zip`)
      })
    })
    container.querySelectorAll('.archive-btn').forEach((btn) => {
      btn.addEventListener('click', () => archiveHistoryTask(btn.dataset.task))
    })
    container.querySelectorAll('.delete-btn').forEach((btn) => {
      btn.addEventListener('click', () => deleteHistoryTask(btn.dataset.task))
    })
    container.querySelectorAll('.compare-select-btn').forEach((btn) => {
      btn.addEventListener('click', () => toggleCompareSelection(btn.dataset.task))
    })
    container.querySelectorAll('.export-json-btn').forEach((btn) => {
      btn.addEventListener('click', () => downloadExport(btn.dataset.task, 'json'))
    })
    container.querySelectorAll('.export-csv-btn').forEach((btn) => {
      btn.addEventListener('click', () => downloadExport(btn.dataset.task, 'csv'))
    })
    // P2 (§20.12): 一键导出人话版 Markdown 报告 — 默认内联卡片渲染
    container.querySelectorAll('.export-md-btn').forEach((btn) => {
      btn.addEventListener('click', () => renderHumanReportInline(btn.dataset.task))
    })
  } catch (e) {
    container.innerHTML = `<p class="error">加载历史失败: ${e.message}</p>`
    $('#historyBatchToolbar').style.display = 'none'
  }
}

// 历史回看：调用 /api/history/:task_id 拉取完整数据，复用 renderSummary /
// renderImages 把摘要和图片重新渲染到结果面板，并在摘要顶部插入回看标识。
async function viewHistoryTask(taskId) {
  try {
    const r = await fetch(`${API_PREFIX}/history/${encodeURIComponent(taskId)}`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const d = await r.json()
    if (!d.success) throw new Error(d.error || 'unknown')

    // 重渲染摘要面板（复用 renderSummary）
    if (d.summary && typeof renderSummary === 'function') {
      renderSummary(d.summary)
    }
    // 重渲染图片区（复用 renderImages）
    if (d.images && typeof renderImages === 'function') {
      renderImages(d.images, taskId)
    }
    // 在摘要顶部插入 task_id 标识
    const summaryEl = document.getElementById('summary')
    if (summaryEl) {
      let badge = document.getElementById('historyViewBadge')
      if (!badge) {
        badge = document.createElement('div')
        badge.id = 'historyViewBadge'
        badge.style.cssText = 'padding:8px 12px;background:var(--accent-dim,rgba(0,255,200,0.1));border-left:3px solid var(--accent);margin-bottom:8px;font-size:0.8rem;'
        summaryEl.prepend(badge)
      }
      // task_updated 是 Unix 秒；缺失时退回当前时间
      const updatedSec = d.task_updated || (Date.now() / 1000)
      badge.textContent = `◉ 历史回看: ${taskId.slice(0, 16)}... | 更新于 ${new Date(updatedSec * 1000).toLocaleString('zh-CN')}`
    }
    // 滚动到结果面板
    summaryEl?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    // 日志提示
    appendTerminal(`◉ 已加载历史任务 ${taskId.slice(0, 8)}... 的数据`, 'info')
  } catch (e) {
    appendTerminal(`✗ 加载历史失败: ${e.message}`, 'error')
  }
}

async function downloadFile(url, fallbackFilename) {
  try {
    const res = await fetch(url)
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
    const blob = await res.blob()
    let filename = fallbackFilename
    try {
      const cd = res.headers.get('content-disposition') || ''
      const match = cd.match(/filename\*?=UTF-8''([^;]+)|filename="?([^"]+)"?/)
      if (match) {
        filename = decodeURIComponent(match[1] || match[2] || fallbackFilename)
      }
    } catch (_) {
      // If Content-Disposition is not exposed by CORS, keep fallback name.
    }
    const urlObj = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = urlObj
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(urlObj)
  } catch (e) {
    appendTerminal(`下载失败: ${e.message}`, 'error')
  }
}

async function downloadExport(taskId, format) {
  await downloadFile(
    `${API_PREFIX}/history/${encodeURIComponent(taskId)}/export/${format}`,
    `${taskId}_summary.${format}`
  )
}

// P1 fix (Round 26 §8): 人话版在新标签页直接查看
function openHumanReport(taskId) {
  window.open(`${API_PREFIX}/history/${encodeURIComponent(taskId)}/export/md`, '_blank')
}

// P1 fix (Round 26 §8): Markdown → 卡片式 HTML 内联渲染, 避免黑色白字文字墙
async function renderHumanReportInline(taskId) {
  try {
    const res = await fetch(`${API_PREFIX}/history/${encodeURIComponent(taskId)}/export/md`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const md = await res.text()
    const html = markdownToCards(md, taskId)
    const host = document.getElementById('summary')
    if (host) {
      // 移除已存在的人话版卡片，避免重复渲染
      const existing = host.querySelector('.human-report-cards')
      if (existing) existing.remove()
      const wrapper = document.createElement('div')
      wrapper.className = 'human-report-cards'
      wrapper.innerHTML = `
        <div class="human-report-header">
          <h3>// 人话版解读</h3>
          <div class="human-report-meta">
            <a href="${API_PREFIX}/history/${encodeURIComponent(taskId)}/export/md" target="_blank" rel="noopener">新标签页查看原文</a>
            <button class="small" onclick="this.closest('.human-report-cards').remove()">收起</button>
          </div>
        </div>
        ${html}
      `
      host.appendChild(wrapper)
      wrapper.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  } catch (e) {
    appendTerminal(`人话版加载失败: ${e.message}`, 'error')
  }
}

const HUMAN_CARD_ICONS = {
  '概览': '◎',
  '稳定性诊断': '◈',
  '稳定性诊断 (HAVOK)': '◈',
  '各变量 EDM 预测技能': '◉',
  'CCM 因果链': '⇄',
  'CCM 因果链 (Sugihara 因果关系)': '⇄',
  '图谱解析': '▣',
  '图谱解析 (dynamics_interpretation.png)': '▣',
  '八正道审计': '✓',
  '八正道审计 (Eightfold Path Audit)': '✓',
  '数据质量与采样充分性': '◆',
  '配置参数附录': '⚙',
  '一句话总结': '★',
}

function markdownToCards(md, taskId) {
  // 按 H2 切分章节, 每个 H2 渲染为一张卡片
  const lines = md.split('\n')
  const sections = []
  let current = { title: '概览', body: [] }
  lines.forEach((line) => {
    const h2 = line.match(/^##\s+(.*)/)
    const h1 = line.match(/^#\s+(.*)/)
    if (h1) {
      if (current.body.length) sections.push(current)
      current = { title: h1[1].replace(/^EDM-Takens\s+分析报告:\s*/, '').trim() || '概览', body: [] }
    } else if (h2) {
      if (current.body.length) sections.push(current)
      current = { title: h2[1].trim(), body: [] }
    } else {
      current.body.push(line)
    }
  })
  if (current.body.length) sections.push(current)

  const escape = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
  const renderInline = (s) => {
    return escape(s)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/_([^_]+)_/g, '<em>$1</em>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
  }

  const parseTable = (rows) => {
    // rows: array of raw markdown lines forming a table
    if (rows.length < 2) return null
    const header = rows[0].split('|').map((c) => c.trim()).filter((c) => c !== '')
    const bodyRows = rows.slice(2).filter((r) => r.trim().startsWith('|'))
    if (!header.length || !bodyRows.length) return null
    const cells = bodyRows.map((r) => r.split('|').map((c) => c.trim()).filter((c) => c !== ''))
    return { header, cells }
  }

  let out = '<div class="human-cards-grid">'
  sections.forEach((sec) => {
    const bodyHtml = []
    const bodyLines = sec.body
    let i = 0
    while (i < bodyLines.length) {
      const line = bodyLines[i]
      const trimmed = line.trim()
      if (trimmed === '') {
        i += 1
        continue
      }
      // 表格：|...|
      if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
        const tableLines = []
        while (i < bodyLines.length && bodyLines[i].trim().startsWith('|')) {
          tableLines.push(bodyLines[i].trim())
          i += 1
        }
        const table = parseTable(tableLines)
        if (table) {
          const th = table.header.map((h) => `<th>${renderInline(h)}</th>`).join('')
          const tr = table.cells.map((row) => `<tr>${row.map((c) => `<td>${renderInline(c)}</td>`).join('')}</tr>`).join('')
          bodyHtml.push(`<table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`)
        } else {
          bodyHtml.push(`<p>${renderInline(trimmed)}</p>`)
        }
        continue
      }
      // 无序列表
      if (/^[-*]\s+/.test(trimmed)) {
        const listItems = []
        while (i < bodyLines.length && (/^[-*]\s+/.test(bodyLines[i].trim()) || (/^\s{2,}/.test(bodyLines[i]) && bodyLines[i].trim() !== ''))) {
          const raw = bodyLines[i].trim()
          if (/^[-*]\s+/.test(raw)) {
            listItems.push(raw.replace(/^[-*]\s+/, ''))
          } else {
            listItems.push(raw)
          }
          i += 1
        }
        bodyHtml.push('<ul>' + listItems.map((li) => `<li>${renderInline(li)}</li>`).join('') + '</ul>')
        continue
      }
      // 引用块
      const quote = trimmed.match(/^>\s*(.*)/)
      if (quote) {
        bodyHtml.push(`<blockquote>${renderInline(quote[1])}</blockquote>`)
        i += 1
        continue
      }
      // 普通段落
      bodyHtml.push(`<p>${renderInline(trimmed)}</p>`)
      i += 1
    }

    const icon = HUMAN_CARD_ICONS[sec.title] || '▸'
    const titleHtml = `<span class="card-icon">${icon}</span><span>${escape(sec.title)}</span>`
    out += `<div class="human-card"><h4 class="human-card-title">${titleHtml}</h4><div class="human-card-body">${bodyHtml.join('')}</div></div>`
  })
  out += '</div>'
  return out
}

function getSelectedHistoryIds() {
  return Array.from($('#historyList').querySelectorAll('.history-checkbox input:checked')).map((cb) => cb.value)
}

function updateBatchToolbar() {
  const ids = getSelectedHistoryIds()
  $('#historyBatchCount').textContent = `已选 ${ids.length} 项`
  const compareBtn = $('#compareSelectedBtn')
  // P1 修复 (Round 24 §3): 允许 2-8 个任务对比, 不再要求恰好 2 个
  compareBtn.disabled = ids.length < 2 || ids.length > 8
  // 同步全选复选框状态
  const allCbs = $('#historyList').querySelectorAll('.history-checkbox input[type="checkbox"]')
  const selectAllCb = $('#selectAllHistory')
  if (selectAllCb) {
    if (allCbs.length === 0) {
      selectAllCb.checked = false
      selectAllCb.indeterminate = false
    } else if (ids.length === allCbs.length) {
      selectAllCb.checked = true
      selectAllCb.indeterminate = false
    } else if (ids.length > 0) {
      selectAllCb.checked = false
      selectAllCb.indeterminate = true
    } else {
      selectAllCb.checked = false
      selectAllCb.indeterminate = false
    }
  }
}

function updateCompareSelectionState() {
  const ids = getSelectedHistoryIds()
  const buttons = $('#historyList').querySelectorAll('.compare-select-btn')
  buttons.forEach((btn) => {
    const selected = ids.includes(btn.dataset.task)
    btn.classList.toggle('selected', selected)
    btn.textContent = selected ? '已选' : '对比'
  })
}

function toggleCompareSelection(taskId) {
  const ids = getSelectedHistoryIds()
  const cb = $(`.history-item[data-task-id="${CSS.escape(taskId)}"] .history-checkbox input`)
  if (cb) cb.checked = !cb.checked
  updateBatchToolbar()
  updateCompareSelectionState()
}

async function runBatchAction(action) {
  const task_ids = getSelectedHistoryIds()
  if (!task_ids.length) {
    alert('请先在历史记录中选择至少一项')
    return
  }
  const actionLabels = { archive: '归档', delete: '删除', download: '下载' }
  if (action !== 'download' && !confirm(`确定要批量${actionLabels[action]}选中的 ${task_ids.length} 项任务吗？`)) return

  try {
    const res = await fetch(API_PREFIX + '/history/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_ids, action }),
    })
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)

    if (action === 'download') {
      const blob = await res.blob()
      let filename = `batch_${Date.now()}.zip`
      try {
        const cd = res.headers.get('content-disposition') || ''
        const match = cd.match(/filename\*?=UTF-8''([^;]+)|filename="?([^"]+)"?/)
        if (match) filename = decodeURIComponent(match[1] || match[2] || filename)
      } catch (_) {}
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } else {
      const data = await res.json()
      const okCount = (data.results || []).filter((r) => r.success).length
      appendTerminal(`> 批量${actionLabels[action]}完成: ${okCount}/${task_ids.length} 项`, 'success')
      loadHistory()
      loadArchives()
    }
  } catch (e) {
    appendTerminal(`批量${actionLabels[action]}失败: ${e.message}`, 'error')
  }
}

async function openCompareModal() {
  const ids = getSelectedHistoryIds()
  // P1 修复 (Round 24 §3): 支持 2-8 个任务对比, 不再要求恰好 2 个
  if (ids.length < 2) {
    alert('请至少选择两项任务进行对比')
    return
  }
  if (ids.length > 8) {
    alert('最多支持 8 个任务同时对比, 请取消部分选择')
    return
  }
  $('#compareModal').style.display = 'flex'
  $('#compareBody').innerHTML = '正在加载对比数据...'
  try {
    const data = await apiJson('/history/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_ids: ids }),
    })
    renderCompare(data)
  } catch (e) {
    $('#compareBody').innerHTML = `<p class="error">对比加载失败: ${e.message}</p>`
  }
}

function closeCompareModal() {
  $('#compareModal').style.display = 'none'
}

function renderCompare(data) {
  // P1 修复 (Round 24 §3): 重写对比渲染, 支持任意数量 (2-8) 任务的对比.
  // 后端返回 summaries 数组, 同时保留 left_task/right_task 兼容旧前端.
  const summaries = data.summaries || []
  // 兼容回退: 若 summaries 为空, 尝试从 left_task/right_task 构建
  if (summaries.length === 0) {
    const left = data.left || data.left_task
    const right = data.right || data.right_task
    if (left) summaries.push(left)
    if (right) summaries.push(right)
  }
  const count = summaries.length
  if (count === 0) {
    $('#compareBody').innerHTML = '<p class="error">无可对比的任务数据</p>'
    return
  }
  // 任务编号 A/B/C/D... 用于标题
  const labelOf = (idx) => String.fromCharCode(65 + idx) // A, B, C, ...
  const renderSide = (task, idx) => {
    const title = `任务 ${labelOf(idx)}`
    const etitle = escapeHtml(title)
    if (!task) return `<div class="compare-side"><h4>${etitle}</h4><p class="dim">无数据</p></div>`
    const config = task.config || {}
    const params = task.params || {}
    const images = (task.images || []).map((img) => {
      const src = `${API_PREFIX}/results/${encodeURIComponent(task.task_id)}/${encodeURIComponent(img)}`
      const eimg = escapeHtml(img)
      return `<img src="${src}" alt="${eimg}" title="${eimg}" />`
    }).join('')
    // 配置信息 (紧凑显示)
    const configEntries = Object.entries(config)
    const configHtml = configEntries.length
      ? configEntries.map(([k, v]) => {
          const ek = escapeHtml(k)
          const ev = typeof v === 'object'
            ? escapeHtml(JSON.stringify(v))
            : escapeHtml(String(v))
          return `<li><strong>${ek}</strong>: <span class="dim">${ev}</span></li>`
        }).join('')
      : '<li class="dim">无配置信息</li>'
    // 任务输入参数
    const paramEntries = Object.entries(params)
    const paramsHtml = paramEntries.length
      ? paramEntries.map(([k, v]) => {
          const ek = escapeHtml(k)
          const ev = typeof v === 'object'
            ? escapeHtml(JSON.stringify(v))
            : escapeHtml(String(v))
          return `<li><strong>${ek}</strong>: <span class="dim">${ev}</span></li>`
        }).join('')
      : ''
    // 更新时间
    const updated = task.updated_at
      ? new Date(task.updated_at * 1000).toLocaleString('zh-CN')
      : '-'
    return `
      <div class="compare-side">
        <h4>${etitle}: <code>${escapeHtml(task.task_id)}</code></h4>
        <div class="compare-meta">更新: ${escapeHtml(updated)} | 图片: ${(task.images || []).length} 张</div>
        <div class="compare-section">
          <strong>任务参数</strong>
          <ul>${paramsHtml || '<li class="dim">无</li>'}</ul>
        </div>
        <div class="compare-section">
          <strong>运行配置</strong>
          <ul>${configHtml}</ul>
        </div>
        <div class="compare-images">${images || '<span class="dim">无图片</span>'}</div>
      </div>
    `
  }
  const sidesHtml = summaries.map((task, idx) => renderSide(task, idx)).join('')
  // 横向对比表 (关键参数对照)
  const compareTable = (() => {
    // 收集所有任务的 config+params 字段并集
    const allKeys = new Set()
    summaries.forEach((task) => {
      const config = task.config || {}
      const params = task.params || {}
      Object.keys(config).forEach((k) => allKeys.add(k))
      Object.keys(params).forEach((k) => allKeys.add(k))
    })
    if (allKeys.size === 0) return ''
    const rows = Array.from(allKeys).sort().map((key) => {
      const cells = summaries.map((task) => {
        const config = task.config || {}
        const params = task.params || {}
        const v = (key in config) ? config[key] : (key in params ? params[key] : null)
        if (v === null || v === undefined) return '<td class="dim">-</td>'
        const ev = typeof v === 'object'
          ? escapeHtml(JSON.stringify(v))
          : escapeHtml(String(v))
        return `<td>${ev}</td>`
      }).join('')
      return `<tr><td class="key">${escapeHtml(key)}</td>${cells}</tr>`
    }).join('')
    const headerCells = summaries
      .map((_, idx) => `<th>任务 ${labelOf(idx)}</th>`)
      .join('')
    return `
      <div class="compare-table-wrap">
        <h4>参数横向对照</h4>
        <table class="compare-table">
          <thead><tr><th>参数</th>${headerCells}</tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `
  })()
  $('#compareBody').innerHTML = `
    <div class="compare-header-info">共 ${count} 个任务对比</div>
    <div class="compare-grid compare-grid-${count}">
      ${sidesHtml}
    </div>
    ${compareTable}
  `
}

async function archiveHistoryTask(taskId) {
  if (!confirm(`确定归档任务 "${taskId}"？\n归档后会打包为 zip 并从活跃历史列表中移除。`)) return
  try {
    await apiJson(`/history/${encodeURIComponent(taskId)}/archive`, { method: 'POST' })
    appendTerminal(`> 已归档: ${taskId}`, 'success')
    loadHistory()
  } catch (e) {
    appendTerminal(`归档失败: ${e.message}`, 'error')
  }
}

async function deleteHistoryTask(taskId) {
  if (!confirm(`确定删除任务 "${taskId}"？\n删除后无法恢复。`)) return
  try {
    await apiJson(`/history/${encodeURIComponent(taskId)}`, { method: 'DELETE' })
    appendTerminal(`> 已删除: ${taskId}`, 'success')
    loadHistory()
  } catch (e) {
    appendTerminal(`删除失败: ${e.message}`, 'error')
  }
}

async function cleanupHistory() {
  const days = prompt('清理多少天以前的历史数据？（默认 30）', '30')
  if (days === null) return
  const n = parseInt(days, 10)
  if (!n || n < 1) {
    alert('请输入大于 0 的整数天数')
    return
  }
  if (!confirm(`确定清理 ${n} 天以前的历史数据？此操作不可恢复。`)) return
  try {
    const res = await apiJson(`/history/cleanup?days=${n}`, { method: 'POST' })
    appendTerminal(`> 已清理 ${res.removed_count} 项历史数据`, 'success')
    loadHistory()
    loadArchives()
  } catch (e) {
    appendTerminal(`清理失败: ${e.message}`, 'error')
  }
}

async function loadArchives() {
  const container = $('#archiveList')
  try {
    const data = await apiJson('/archives')
    const archives = Array.isArray(data) ? data : (data.archives || [])
    if (!archives.length) {
      container.innerHTML = '暂无归档数据。'
      return
    }
    container.innerHTML = archives.map((a) => {
      const date = a.updated_at ? new Date(a.updated_at * 1000).toLocaleString('zh-CN') : '-'
      const size = a.size_bytes != null ? `(${(a.size_bytes / 1024 / 1024).toFixed(2)} MB)` : ''
      const label = a.filename || a.task_id
      return `
        <div class="archive-item" data-archive-id="${a.task_id}">
          <h4>${label}</h4>
          <div class="meta">归档时间: ${date} ${size}</div>
          <div class="actions">
            <button class="small view-archive-btn" data-id="${a.task_id}">查看</button>
            <button class="small restore-archive-btn" data-id="${a.task_id}">恢复</button>
            <button class="small danger delete-archive-btn" data-id="${a.task_id}">删除</button>
          </div>
        </div>
      `
    }).join('')

    container.querySelectorAll('.view-archive-btn').forEach((btn) => {
      btn.addEventListener('click', () => viewArchiveTask(btn.dataset.id))
    })
    container.querySelectorAll('.restore-archive-btn').forEach((btn) => {
      btn.addEventListener('click', () => restoreArchive(btn.dataset.id))
    })
    container.querySelectorAll('.delete-archive-btn').forEach((btn) => {
      btn.addEventListener('click', () => deleteArchive(btn.dataset.id))
    })
  } catch (e) {
    container.innerHTML = `<p class="error">加载归档失败: ${e.message}</p>`
  }
}

// 归档回看：调用 /api/archives/:task_id/preview 临时解压 zip 拉取元数据，
// 复用 renderSummary / renderImages 把摘要和图片渲染到结果面板。
// 注意：归档预览端点只返回 config/params/images 元数据，不返回图片二进制；
// 图片渲染仍走 /api/results/<task_id>/<img> 静态路由，因此若任务目录尚未
// 恢复到 results/ 下，图片会 404。摘要和参数回看不依赖图片可达性。
async function viewArchiveTask(taskId) {
  try {
    const r = await fetch(`${API_PREFIX}/archives/${encodeURIComponent(taskId)}/preview`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const d = await r.json()
    if (!d.success) throw new Error(d.error || 'unknown')

    // 重渲染摘要面板（复用 renderSummary）
    if (d.summary && typeof renderSummary === 'function') {
      renderSummary(d.summary)
    }
    // 归档预览模式：图片渲染依赖 results/ 静态服务，若任务目录尚未恢复
    // 则图片不可达。这里仍尝试渲染（若用户已恢复过同名任务，图片可见）。
    if (d.images && typeof renderImages === 'function') {
      renderImages(d.images, taskId)
    }
    // 在摘要顶部插入归档回看标识
    const summaryEl = document.getElementById('summary')
    if (summaryEl) {
      let badge = document.getElementById('historyViewBadge')
      if (!badge) {
        badge = document.createElement('div')
        badge.id = 'historyViewBadge'
        badge.style.cssText = 'padding:8px 12px;background:var(--accent-dim,rgba(0,255,200,0.1));border-left:3px solid var(--accent);margin-bottom:8px;font-size:0.8rem;'
        summaryEl.prepend(badge)
      }
      const updatedSec = d.task_updated || (Date.now() / 1000)
      badge.textContent = `◉ 归档回看: ${taskId.slice(0, 16)}... | 归档于 ${new Date(updatedSec * 1000).toLocaleString('zh-CN')}`
    }
    summaryEl?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    appendTerminal(`◉ 已加载归档 ${taskId.slice(0, 8)}... 的预览数据`, 'info')
  } catch (e) {
    appendTerminal(`✗ 加载归档预览失败: ${e.message}`, 'error')
  }
}

async function restoreArchive(id) {
  if (!confirm(`确定恢复归档 "${id}"？`)) return
  try {
    await apiJson(`/archives/${encodeURIComponent(id)}/restore`, { method: 'POST' })
    appendTerminal(`> 已恢复归档: ${id}`, 'success')
    loadArchives()
    loadHistory()
  } catch (e) {
    appendTerminal(`恢复归档失败: ${e.message}`, 'error')
  }
}

async function deleteArchive(id) {
  if (!confirm(`确定删除归档 "${id}"？删除后无法恢复。`)) return
  try {
    await apiJson(`/archives/${encodeURIComponent(id)}`, { method: 'DELETE' })
    appendTerminal(`> 已删除归档: ${id}`, 'success')
    loadArchives()
  } catch (e) {
    appendTerminal(`删除归档失败: ${e.message}`, 'error')
  }
}

async function loadEmbedCurve() {
  const filename = $('#datasetSelect').value
  if (!filename) {
    alert('请先选择一个数据集')
    return
  }
  const wrap = $('#embedCurveWrap')
  const canvas = $('#embedCurveCanvas')
  const optimalDiv = $('#embedCurveOptimal')
  wrap.style.display = 'block'
  optimalDiv.textContent = '加载中...'
  try {
    const data = await apiJson(`/datasets/${encodeURIComponent(filename)}/embed_curve`)
    const E = data.E_values || []
    const rho = data.rho_values || []
    const optimalE = data.optimal_E
    if (!E.length || !rho.length || E.length !== rho.length) {
      optimalDiv.textContent = '暂无足够数据绘制嵌入维度曲线。'
      return
    }
    drawLineChart(canvas, E, rho, 'E', 'rho')
    optimalDiv.textContent = `最优嵌入维度 E: ${optimalE ?? '未知'}`
  } catch (e) {
    optimalDiv.textContent = `加载失败: ${e.message}`
  }
}

function drawLineChart(canvas, x, y, xLabel, yLabel) {
  const ctx = canvas.getContext('2d')
  const dpr = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  canvas.width = Math.max(rect.width, 300) * dpr
  canvas.height = Math.max(rect.height, 240) * dpr
  ctx.scale(dpr, dpr)
  const width = canvas.width / dpr
  const height = canvas.height / dpr
  const pad = { top: 30, right: 30, bottom: 50, left: 60 }
  const chartW = width - pad.left - pad.right
  const chartH = height - pad.top - pad.bottom

  ctx.clearRect(0, 0, width, height)

  const minX = Math.min(...x)
  const maxX = Math.max(...x)
  const minY = Math.min(...y)
  const maxY = Math.max(...y)
  const rangeY = maxY - minY || 1
  const rangeX = maxX - minX || 1

  const sx = (v) => pad.left + ((v - minX) / rangeX) * chartW
  const sy = (v) => pad.top + chartH - ((v - minY) / rangeY) * chartH

  // Grid
  ctx.strokeStyle = '#1f2a36'
  ctx.lineWidth = 1
  ctx.beginPath()
  for (let i = 0; i <= 4; i++) {
    const gy = pad.top + (chartH / 4) * i
    ctx.moveTo(pad.left, gy)
    ctx.lineTo(pad.left + chartW, gy)
  }
  for (let i = 0; i <= 4; i++) {
    const gx = pad.left + (chartW / 4) * i
    ctx.moveTo(gx, pad.top)
    ctx.lineTo(gx, pad.top + chartH)
  }
  ctx.stroke()

  // Line
  ctx.strokeStyle = '#00d9a3'
  ctx.lineWidth = 2
  ctx.beginPath()
  x.forEach((xi, i) => {
    if (i === 0) ctx.moveTo(sx(xi), sy(y[i]))
    else ctx.lineTo(sx(xi), sy(y[i]))
  })
  ctx.stroke()

  // Points
  ctx.fillStyle = '#00ff9d'
  x.forEach((xi, i) => {
    ctx.beginPath()
    ctx.arc(sx(xi), sy(y[i]), 3, 0, Math.PI * 2)
    ctx.fill()
  })

  // Axes labels
  ctx.fillStyle = '#94a3b8'
  ctx.font = '12px JetBrains Mono, Consolas, monospace'
  ctx.textAlign = 'center'
  ctx.fillText(xLabel, pad.left + chartW / 2, height - 14)

  ctx.save()
  ctx.translate(18, pad.top + chartH / 2)
  ctx.rotate(-Math.PI / 2)
  ctx.fillText(yLabel, 0, 0)
  ctx.restore()

  // Tick labels
  ctx.textAlign = 'right'
  ctx.textBaseline = 'middle'
  for (let i = 0; i <= 4; i++) {
    const val = minY + (rangeY / 4) * i
    const gy = pad.top + chartH - (chartH / 4) * i
    ctx.fillText(val.toFixed(2), pad.left - 8, gy)
  }

  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  for (let i = 0; i <= 4; i++) {
    const val = minX + (rangeX / 4) * i
    const gx = pad.left + (chartW / 4) * i
    ctx.fillText(val.toFixed(0), gx, pad.top + chartH + 8)
  }
}

// Event bindings
$('#uploadBtn').addEventListener('click', uploadFile)

// Drop zone drag-and-drop
const dropZone = $('#dropZone')
if (dropZone) {
  ;['dragenter', 'dragover', 'dragleave', 'drop'].forEach((evt) => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault()
      e.stopPropagation()
    })
  })
  ;['dragenter', 'dragover'].forEach((evt) => {
    dropZone.addEventListener(evt, () => dropZone.classList.add('drag-over'))
  })
  ;['dragleave', 'drop'].forEach((evt) => {
    dropZone.addEventListener(evt, () => dropZone.classList.remove('drag-over'))
  })
  dropZone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files
    if (files.length) {
      $('#csvInput').files = files
      uploadFile()
    }
  })
}

$('#refreshDatasetsBtn').addEventListener('click', refreshDatasets)
$('#refreshHistoryBtn').addEventListener('click', loadHistory)
$('#refreshQualityBtn').addEventListener('click', () => {
  const filename = $('#datasetSelect').value
  if (filename) loadQuality(filename)
})
$('#embedCurveBtn').addEventListener('click', loadEmbedCurve)
$('#cleanupHistoryBtn').addEventListener('click', cleanupHistory)
$('#refreshArchivesBtn').addEventListener('click', loadArchives)
$('#batchArchiveBtn').addEventListener('click', () => runBatchAction('archive'))
$('#batchDeleteBtn').addEventListener('click', () => runBatchAction('delete'))
$('#batchDownloadBtn').addEventListener('click', () => runBatchAction('download'))
$('#compareSelectedBtn').addEventListener('click', openCompareModal)
$('#closeCompareModal').addEventListener('click', closeCompareModal)
$('#compareModal .modal-backdrop').addEventListener('click', closeCompareModal)
$('#datasetSelect').addEventListener('change', (e) => {
  if (e.target.value) loadDatasetColumns(e.target.value)
})
$('#targetSelect').addEventListener('change', () => {
  const filename = $('#datasetSelect').value
  if (filename) {
    updateStatusWall({ target: $('#targetSelect').value })
    loadRecommendation(filename)
    loadQuality(filename)
  }
})
$('#variablesInput').addEventListener('input', () => {
  const filename = $('#datasetSelect').value
  if (filename) {
    loadRecommendation(filename)
    loadQuality(filename)
  }
})
$('#runBtn').addEventListener('click', runAnalysis)
$('#qInput').addEventListener('input', () => {
  const filename = $('#datasetSelect').value
  if (filename) updateStatusWall({ q: $('#qInput').value || '自动' })
})

// 全选/取消全选历史记录
$('#selectAllHistory').addEventListener('change', (e) => {
  const cbs = $('#historyList').querySelectorAll('.history-checkbox input[type="checkbox"]')
  cbs.forEach((cb) => { cb.checked = e.target.checked })
  updateBatchToolbar()
  updateCompareSelectionState()
})

// UX: 全局快捷键 Ctrl+Enter 触发分析（方便长页面中快速运行）
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !$('#runBtn').disabled) {
    e.preventDefault()
    runAnalysis()
  }
})

// 特摄防卫队氛围: 任务时钟
function startMissionClock() {
  const update = () => {
    const now = new Date()
    const timeStr = now.toLocaleTimeString('zh-CN', { hour12: false })
    const clockEl = document.querySelector('#missionClock .clock-value')
    if (clockEl) clockEl.textContent = timeStr
  }
  update()
  setInterval(update, 1000)
}

// 点击质量表格中的警告单元格，弹出该行完整质量报告
$('#qualityList').addEventListener('click', (e) => {
  const cell = e.target.closest('.warn-cell')
  if (!cell || !cell.dataset.warn) return
  const name = cell.closest('tr')?.querySelector('td strong')?.textContent || '未知列'
  const lines = cell.dataset.warn.split('；')
  const detailHtml = lines.map((w) => `<li>${w}</li>`).join('')
  const panel = document.createElement('div')
  panel.className = 'quality-detail-modal'
  panel.innerHTML = `
    <div class="quality-detail-backdrop"></div>
    <div class="quality-detail-content">
      <div class="quality-detail-header">
        <h4>◉ ${escapeHtml(name)} — 数据质量详情</h4>
        <button class="close-detail" aria-label="关闭">✕</button>
      </div>
      <ul class="quality-detail-list">${detailHtml}</ul>
    </div>
  `
  document.body.appendChild(panel)
  panel.querySelector('.close-detail').addEventListener('click', () => panel.remove())
  panel.querySelector('.quality-detail-backdrop').addEventListener('click', () => panel.remove())
})

// Init
refreshDatasets()
loadHistory()
loadArchives()
startMissionClock()
// P1-f 修缮：启动健康检查（本机后端 + 跨项目导航点）
checkBackendHealth()
checkNavHealth()
setInterval(checkBackendHealth, 30000)  // 每 30s 检查本机后端
setInterval(checkNavHealth, 60000)      // 每 60s 检查跨项目导航点
