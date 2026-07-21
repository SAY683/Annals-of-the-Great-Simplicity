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
      return
    }
    datasets.forEach((name) => {
      const opt = document.createElement('option')
      opt.value = name
      opt.textContent = name
      sel.appendChild(opt)
    })
  } catch (e) {
    console.error('refreshDatasets:', e)
    const sel = $('#datasetSelect')
    if (sel) sel.innerHTML = '<option value="">加载失败</option>'
  }
}

async function loadDatasetColumns(filename) {
  try {
    const info = await apiJson(`/datasets/${encodeURIComponent(filename)}/columns`)
    $('#columnInfo').innerHTML = `
      <strong>${escapeHtml(filename)}</strong><br/>
      行数: ${info.rows} &nbsp;|&nbsp; 数值列: ${escapeHtml(info.numeric_columns.join(', '))}
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
      const warnings = q.warnings.length
        ? `<ul>${q.warnings.map((w) => `<li class="warn">${escapeHtml(w)}</li>`).join('')}</ul>`
        : '<span class="ok">无警告</span>'
      return `
        <tr class="${q.selected ? 'selected-row' : ''}">
          <td><strong>${escapeHtml(name)}</strong> ${badges.join(' ')}</td>
          <td class="${statusClass}">${statusText}</td>
          <td>${q.n}</td>
          <td>${(q.missing_ratio * 100).toFixed(1)}%</td>
          <td>${q.unique_count}</td>
          <td>${q.std.toExponential(2)}</td>
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
    await refreshDatasets()
    // Ensure the newly uploaded file is selectable before forcing selection.
    const sel = $('#datasetSelect')
    if (!Array.from(sel.options).some((o) => o.value === res.filename)) {
      // If the backend sanitized the filename, fall back to a manual refresh.
      await refreshDatasets()
    }
    sel.value = res.filename
    if (sel.value === res.filename) {
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
  const line = document.createElement('div')
  line.className = `terminal-line ${type}`
  line.textContent = text
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

  $('#summary').innerHTML = '<p>初始化分析任务...</p>'
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
  const pollInterval = setInterval(async () => {
    const data = await pollJobStatus(jobId, (data) => {
      setTerminalStatus(data.status)
    })
    if (data && (data.status === 'done' || data.status === 'error')) {
      clearInterval(pollInterval)
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
            <button class="small download-btn" data-task="${tid}">下载 zip</button>
            <button class="small archive-btn" data-task="${tid}">归档</button>
            <button class="small compare-select-btn" data-task="${tid}">对比</button>
            <button class="small export-json-btn" data-task="${tid}">JSON</button>
            <button class="small export-csv-btn" data-task="${tid}">CSV</button>
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
  } catch (e) {
    container.innerHTML = `<p class="error">加载历史失败: ${e.message}</p>`
    $('#historyBatchToolbar').style.display = 'none'
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

function getSelectedHistoryIds() {
  return Array.from($('#historyList').querySelectorAll('.history-checkbox input:checked')).map((cb) => cb.value)
}

function updateBatchToolbar() {
  const ids = getSelectedHistoryIds()
  $('#historyBatchCount').textContent = `已选 ${ids.length} 项`
  const compareBtn = $('#compareSelectedBtn')
  compareBtn.disabled = ids.length !== 2
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
  if (ids.length !== 2) {
    alert('请恰好选择两项任务进行对比')
    return
  }
  const [leftId, rightId] = ids
  $('#compareModal').style.display = 'flex'
  $('#compareBody').innerHTML = '正在加载对比数据...'
  try {
    const data = await apiJson('/history/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ left_id: leftId, right_id: rightId }),
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
  const renderSide = (task, title) => {
    const etitle = escapeHtml(title)
    if (!task) return `<div class="compare-side"><h4>${etitle}</h4><p class="dim">无数据</p></div>`
    // 后端 _task_summary() 返回 {task_id, updated_at, images, config}，无 summary 字段；
    // 这里展示任务配置信息（config），为空时给出提示。
    const config = task.config || {}
    const images = (task.images || []).map((img) => {
      const src = `${API_PREFIX}/results/${encodeURIComponent(task.task_id)}/${encodeURIComponent(img)}`
      const eimg = escapeHtml(img)
      return `<img src="${src}" alt="${eimg}" title="${eimg}" />`
    }).join('')
    const configHtml = Object.entries(config).map(([k, v]) => {
      const ek = escapeHtml(k)
      if (typeof v === 'object') return `<li><strong>${ek}:</strong> <pre>${escapeHtml(JSON.stringify(v, null, 2))}</pre></li>`
      return `<li><strong>${ek}:</strong> ${escapeHtml(v)}</li>`
    }).join('')
    return `
      <div class="compare-side">
        <h4>${etitle}: ${escapeHtml(task.task_id)}</h4>
        <div class="compare-summary"><ul>${configHtml || '<li class="dim">无配置信息</li>'}</ul></div>
        <div class="compare-images">${images || '<span class="dim">无图片</span>'}</div>
      </div>
    `
  }
  const left = data.left || data.left_task
  const right = data.right || data.right_task
  $('#compareBody').innerHTML = `
    <div class="compare-grid">
      ${renderSide(left, '任务 A')}
      ${renderSide(right, '任务 B')}
    </div>
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
            <button class="small restore-archive-btn" data-id="${a.task_id}">恢复</button>
            <button class="small danger delete-archive-btn" data-id="${a.task_id}">删除</button>
          </div>
        </div>
      `
    }).join('')

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

// UX: 全局快捷键 Ctrl+Enter 触发分析（方便长页面中快速运行）
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !$('#runBtn').disabled) {
    e.preventDefault()
    runAnalysis()
  }
})

// 特摄防卫队氛围: 任务时钟与状态看板
function startMissionClock() {
  const update = () => {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('zh-CN', { hour12: false });
    const clockEl = document.getElementById('clockValue');
    if (clockEl) clockEl.textContent = timeStr;
  };
  update();
  setInterval(update, 1000);
}

function updateStatusBoard() {
  const intensity = $('#intensitySelect')?.value?.toUpperCase() || 'AUTO';
  const modeEl = document.getElementById('sbMode');
  if (modeEl) modeEl.textContent = intensity;
}

// Init
refreshDatasets()
loadHistory()
loadArchives()
startMissionClock()
updateStatusBoard()
$('#intensitySelect')?.addEventListener('change', updateStatusBoard)
