/* TRACE Engine Web — 主入口逻辑（debt-09）
 * ===========================================
 * 抽取自原 index.html 内联 <script>。
 * 本文件最后加载，负责：
 *   1. 声明所有 DOM 元素引用与共享状态（供其他 js 文件运行时引用）
 *   2. 附加所有事件监听器
 *   3. 提供核心控制函数（startAnalysis / cancelAnalysis / applyScale / 等）
 *   4. 页面初始化（loadBridgeSchema / loadJobHistory）
 *
 * debt-11：startAnalysis 在重连时通过 Last-Event-ID 头携带 lastSseEventId。
 *
 * 依赖（由先加载的 js 文件提供）：
 *   - schema.js:  loadBridgeSchema / applyPreset / getConfig / getCurrentSchema
 *   - sse.js:     readSSEStream / lastSseEventId
 *   - render.js:  log / escapeHtml / safeFmt / showToast / applyLogFilters / updateLogFilterButtons / setLogPaused / renderResult
 *   - jobs.js:    loadJobHistory / exportJobs / clearJobs
 */

// ── DOM 元素引用（跨脚本共享） ────────────────────────────────────────
const sampleText = `算法推荐系统通过持续分析用户行为数据，精准推送用户感兴趣的内容。然而，这种个性化推送机制会在长期运行中导致信息茧房效应的形成。信息茧房使得用户长期只接触单一观点，从而加剧了观点极化的趋势。观点极化进一步侵蚀了社会共识的基础。当社会共识瓦解后，公共讨论空间也随之萎缩。公共讨论空间的萎缩又会削弱社会监督功能，社会监督功能的弱化反过来降低算法平台的问责压力。算法平台问责压力的降低，使得算法透明度改革难以推进。算法透明度改革的迟滞进一步固化信息茧房，从而形成一条完整的因果反馈回路。与此同时，用户行为数据的过度采集也引发了隐私风险，隐私风险的上升会削弱用户对平台的信任。用户信任的下降减少了数据共享意愿，数据共享意愿的降低又反过来损害推荐算法的精准度。推荐精准度的下降导致平台广告收入减少，广告收入的减少进一步压缩内容审核投入，内容审核投入的下降助长了虚假信息的传播，虚假信息的传播加剧了观点极化。`;

const analyzeBtn = document.getElementById('analyzeBtn');
const cancelBtn = document.getElementById('cancelBtn');
const loadSampleBtn = document.getElementById('loadSampleBtn');
const textInput = document.getElementById('textInput');
const fileInput = document.getElementById('fileInput');
const terminal = document.getElementById('terminal');
const logStageBadge = document.getElementById('logStageBadge');
const pauseLogBtn = document.getElementById('pauseLogBtn');
const clearLogBtn = document.getElementById('clearLogBtn');
const logFilters = document.querySelectorAll('.log-filter');
const progressWrap = document.getElementById('progressWrap');
const progressFill = document.getElementById('progressFill');
const stageName = document.getElementById('stageName');
const stagePercent = document.getElementById('stagePercent');
const stageElapsed = document.getElementById('stageElapsed');
const superStats = document.getElementById('superStats');
const statsRate = document.getElementById('statsRate');
const statsProcessed = document.getElementById('statsProcessed');
const statsTotal = document.getElementById('statsTotal');
const statsEta = document.getElementById('statsEta');
const toast = document.getElementById('toast');
const resultPanel = document.getElementById('resultPanel');
const inputPanel = document.getElementById('inputPanel');
const sbMode = document.getElementById('sbMode');
const sbCore = document.getElementById('sbCore');
const missionClock = document.getElementById('missionClock');
const modeRadios = document.querySelectorAll('input[name="mode"]');
const modeNote = document.getElementById('modeNote');
const uiScale = document.getElementById('uiScale');
const uiScaleVal = document.getElementById('uiScaleVal');
const resetScaleBtn = document.getElementById('resetScaleBtn');
const clearBtn = document.getElementById('clearBtn');
const refreshJobsBtn = document.getElementById('refreshJobsBtn');
const exportJobsBtn = document.getElementById('exportJobsBtn');
const clearJobsBtn = document.getElementById('clearJobsBtn');
const jobHistoryTerminal = document.getElementById('jobHistoryTerminal');
const dynamicParams = document.getElementById('dynamicParams');
const dropZone = document.getElementById('dropZone');
const dropText = document.getElementById('dropText');
const fileName = document.getElementById('fileName');
const modelBadge = document.getElementById('modelBadge');
const superModelSelect = document.getElementById('superModelSelect');
const DEFAULT_SCALE = 105;

// ── 共享状态（跨脚本共享） ────────────────────────────────────────────
let currentJobId = null;
let streamAbort = null;
let lastConfig = null;
let elapsedInterval = null;

// ── UI 缩放控制 ───────────────────────────────────────────────────────
function applyScale(pct) {
  document.documentElement.style.setProperty('--ui-scale', pct / 100);
  uiScaleVal.textContent = pct + '%';
  uiScale.value = pct;
  try { localStorage.setItem('trace-ui-scale', String(pct)); } catch (_) {}
}

function updateModelBadge() {
  if (!modelBadge || !superModelSelect) return;
  const v = superModelSelect.value;
  if (v === 'shenji-llama') {
    modelBadge.textContent = '469M / SLOW';
    modelBadge.className = 'model-badge egg';
  } else if (v === 'shehui-llama-v4-archive') {
    modelBadge.textContent = '470M / ARCHIVE';
    modelBadge.className = 'model-badge egg';
  } else {
    modelBadge.textContent = '27M / FAST';
    modelBadge.className = 'model-badge speed';
  }
}

// 模式说明联动 + 状态看板 + 特摄警戒边框
function updateStatusBoard() {
  const mode = getMode();
  sbMode.textContent = mode.toUpperCase();
  if (mode === 'super') {
    sbCore.textContent = superModelSelect.value.toUpperCase().replace('-', ' ');
    inputPanel.classList.add('alert');
  } else {
    sbCore.textContent = 'JIEBA / RULE';
    inputPanel.classList.remove('alert');
  }
}

function getMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function resetUI() {
  terminal.innerHTML = '';
  logStageBadge.textContent = 'IDLE';
  resultPanel.classList.add('hidden');
  progressWrap.style.display = 'block';
  updateProgress('INIT', 0);
  showToast('', '');
}

function setRunning(running) {
  analyzeBtn.disabled = running;
  cancelBtn.style.display = running ? 'inline-block' : 'none';
  modeRadios.forEach(r => r.disabled = running);
  if (running) startElapsedTimer();
  else stopElapsedTimer();
}

function updateProgress(stage, progress) {
  const s = stage.toUpperCase();
  stageName.textContent = s;
  logStageBadge.textContent = s;
  const pct = progress !== null ? Math.round(progress * 100) : 0;
  progressFill.style.width = pct + '%';
  stagePercent.textContent = pct + '%';
}

function startElapsedTimer() {
  const start = Date.now();
  stageElapsed.textContent = '00:00';
  elapsedInterval = setInterval(() => {
    const s = Math.floor((Date.now() - start) / 1000);
    const mm = String(Math.floor(s / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    stageElapsed.textContent = `${mm}:${ss}`;
  }, 1000);
}

function stopElapsedTimer() {
  if (elapsedInterval) {
    clearInterval(elapsedInterval);
    elapsedInterval = null;
  }
}

function validateClientInput(text) {
  if (!text || text.trim().length === 0) return { ok: false, error: '文本不能为空' };
  if (text.length > 500000) return { ok: false, error: '文本长度超过 500000 字符限制' };
  return { ok: true };
}

function updateFileName() {
  const f = fileInput.files[0];
  if (f) {
    dropText.textContent = '文件已选择';
    fileName.textContent = f.name;
    fileName.style.display = 'block';
  } else {
    dropText.textContent = '点击选择或拖拽文本文件到此处';
    fileName.textContent = '';
    fileName.style.display = 'none';
  }
}

// ── 分析启动（debt-11：重连时发送 Last-Event-ID 头） ──────────────────
async function startAnalysis() {
  const text = textInput.value.trim();
  const file = fileInput.files[0];

  if (!text && !file) {
    showToast('请输入文本或上传文件', 'error');
    return;
  }

  let payloadText = text;
  if (file) {
    try {
      payloadText = await file.text();
    } catch (err) {
      showToast('读取文件失败: ' + err.message, 'error');
      return;
    }
  }

  const validation = validateClientInput(payloadText);
  if (!validation.ok) {
    showToast(validation.error, 'error');
    return;
  }

  resetUI();
  currentJobId = crypto.randomUUID();
  const mode = getMode();
  lastConfig = getConfig();
  if (mode === 'super') {
    lastConfig.model = document.getElementById('superModelSelect').value;
  }
  setRunning(true);

  // 前置警告：SUPER 模式大模型处理长文本极易超时，给用户明确预期
  if (mode === 'super' && lastConfig.model && payloadText.length > 200) {
    const m = lastConfig.model.toLowerCase();
    const isArchive = m.includes('archive');
    const isShenji = m.includes('shenji');
    const isLightShehui = m.includes('shehui') && !isArchive;
    if (isShenji || isArchive) {
      const modelLabel = isShenji ? 'Shenji-LLaMA' : 'Shehui-LLaMA V4 [ARCHIVE]';
      const msg = `${modelLabel} 为 470M/1.88GB 级大模型，当前文本 ${payloadText.length} 字符。SUPER 模式不再设置固定超时，界面会实时显示处理速率与预计剩余时间；如无法接受等待时长，可随时点击 > ABORT 主动停止。系统会自动限制 window_size≤128 / max_segments≤3。若预估时间过长，也可缩短文本、切换到轻量 Shehui-LLaMA (27M) 或 DEEP 模式。`;
      log('warn', msg);
      showToast(msg, 'warn');
    } else if (isLightShehui) {
      // 27M 轻量模型速率极快，仅在超长文本时提示
      if (payloadText.length > 5000) {
        const msg = `Shehui-LLaMA (27M) 当前文本 ${payloadText.length} 字符，因果视野 256 tokens，长文本将分段处理。轻量模型推理速度极快，但仍可随时点击 > ABORT 主动停止。`;
        log('info', msg);
        showToast(msg, 'info');
      }
    }
  }

  log('stage', `任务启动 [${currentJobId.slice(0, 8)}] 模式=${mode.toUpperCase()}`);
  const cfgSummary = Object.entries(lastConfig).map(([k, v]) => `${k}=${v}`).join(' ');
  log('info', `桥接参数: ${cfgSummary}`);

  // 使用 POST + fetch + ReadableStream 消费 SSE，避免长文本 URL 超限
  streamAbort = new AbortController();
  // debt-11：构建请求头，重连时携带 Last-Event-ID（lastSseEventId 由 sse.js 维护）
  // P0 修缮：把 fetch 封装为 doFetch，首次与重连共用；重连时重新构建 headers 以携带最新 lastSseEventId
  const doFetch = async () => {
    const reqHeaders = { 'Content-Type': 'application/json' };
    if (lastSseEventId != null) {
      reqHeaders['Last-Event-ID'] = String(lastSseEventId);
    }
    const resp = await fetch('/api/analyze-stream', {
      method: 'POST',
      headers: reqHeaders,
      body: JSON.stringify({ id: currentJobId, text: payloadText, mode, config: lastConfig }),
      signal: streamAbort.signal,
    });
    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      const code = errData.code ? `[${errData.code}] ` : '';
      throw new Error(code + (errData.error || `HTTP ${resp.status}`));
    }
    return resp;
  };
  try {
    const response = await doFetch();
    // P0 修缮：传入 reconnectFactory + signal，readSSEStream 在网络中断时自动重连 3 次（1s/2s/4s）
    await readSSEStream(response.body, {
      reconnectFactory: doFetch,
      signal: streamAbort.signal,
    });
  } catch (err) {
    if (err.name !== 'AbortError') {
      log('error', err.message || '分析请求失败');
      showToast(err.message || '分析请求失败', 'error');
      setRunning(false);
      loadJobHistory();
    }
  }
}

async function cancelAnalysis() {
  if (!currentJobId) return;
  if (streamAbort) streamAbort.abort();
  try {
    const res = await fetch(`/api/cancel/${currentJobId}`, { method: 'POST' });
    const data = await res.json();
    // S11：统一错误响应访问方式——失败读 data.error，成功读 data.message/data.reason
    const msg = data.success
      ? (data.message || `已取消（${data.reason || 'process_terminated'}）`)
      : (data.error || '取消失败');
    log('warn', msg);
    showToast(msg, data.success ? 'info' : 'error');
  } catch (err) {
    showToast(err.message, 'error');
  }
  setRunning(false);
}

// ── 事件监听器附加 ────────────────────────────────────────────────────
uiScale.addEventListener('input', () => applyScale(parseInt(uiScale.value, 10)));
resetScaleBtn.addEventListener('click', () => applyScale(DEFAULT_SCALE));
(function restoreScale() {
  try {
    const saved = localStorage.getItem('trace-ui-scale');
    if (saved) {
      applyScale(parseInt(saved, 10));
    } else {
      applyScale(DEFAULT_SCALE);
    }
  } catch (_) { applyScale(DEFAULT_SCALE); }
})();

superModelSelect.addEventListener('change', updateModelBadge);
superModelSelect.addEventListener('change', updateStatusBoard);

modeRadios.forEach(r => r.addEventListener('change', () => {
  const mode = getMode();
  const superWrap = document.getElementById('superModelWrap');
  if (mode === 'deep') {
    modeNote.innerHTML = '<strong>DEEP 模式：</strong>执行完整六战士深度诊断（TRACE、CCM、EDM、HAVOK、DoWhy+CF、causallearn PC/GES）。概念图由 jieba 构建，预计耗时 10–60 秒或更长。';
    superWrap.style.display = 'none';
  } else if (mode === 'super') {
    modeNote.innerHTML = '<strong>SUPER 模式 // 特装型：</strong>启动 LLaMA 核心驱动，执行真正的 token-level TRACE 因果发现，再走完整六合一诊断。可在下方选择三个模型之一：Shehui-LLaMA（27M 轻量，~800 pps，显存 ≥1.5GB）、Shenji-LLaMA（469M，~10-40 pps，显存 ≥3.0GB）、Shehui-LLaMA V4 [ARCHIVE]（470M 旧版归档）。大模型首次加载较慢，分析耗时数分钟至数十分钟。界面会实时显示处理速率（pairs/s）与预计剩余时间；如无法接受等待时长，可随时点击 <strong>> ABORT</strong> 主动停止。470M 级模型会自动限制 window_size≤128 / max_segments≤3。';
    superWrap.style.display = 'flex';
    updateModelBadge();
  } else {
    modeNote.innerHTML = '<strong>LIGHT 模式：</strong>仅执行 TRACE + DoWhy 核心因果推断（识别、估计、反驳、反事实扫描），约 1–3 秒完成。此模式跳过 causallearn、完整 CCM/EDM/HAVOK 深度诊断，因此“快”是设计行为，不是缺陷。';
    superWrap.style.display = 'none';
  }
  updateStatusBoard();
}));

// 任务时钟
setInterval(() => {
  const now = new Date();
  missionClock.textContent = now.toLocaleTimeString('zh-CN', { hour12: false });
}, 1000);

loadSampleBtn.addEventListener('click', () => {
  textInput.value = sampleText;
  log('info', '示例文本已加载');
});

clearBtn.addEventListener('click', () => {
  textInput.value = '';
  fileInput.value = '';
  updateFileName();
  resultPanel.classList.add('hidden');
  terminal.innerHTML = '';
  showToast('', '');
  log('info', '输入与结果已清空');
});

refreshJobsBtn.addEventListener('click', loadJobHistory);
exportJobsBtn.addEventListener('click', exportJobs);
clearJobsBtn.addEventListener('click', clearJobs);

// debt-16：参数预设按钮改为调用 applyPreset（从 /api/presets 动态加载）
document.querySelectorAll('.preset-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    applyPreset(btn.dataset.preset);
  });
});

// 拖拽上传
dropZone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => updateFileName());
dropZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});
dropZone.addEventListener('dragleave', () => {
  dropZone.classList.remove('drag-over');
});
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const files = e.dataTransfer.files;
  if (files.length > 0) {
    fileInput.files = files;
    updateFileName();
    log('info', `已选择文件: ${files[0].name}`);
  }
});

// 键盘快捷键：Ctrl+Enter 运行分析
textInput.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key === 'Enter') {
    e.preventDefault();
    startAnalysis();
  }
});

analyzeBtn.addEventListener('click', startAnalysis);
cancelBtn.addEventListener('click', cancelAnalysis);

// 日志过滤
for (const btn of logFilters) {
  btn.addEventListener('click', () => {
    const lvl = btn.dataset.level;
    if (lvl === 'all') {
      const allActive = LOG_LEVELS.every(l => activeLogLevels.has(l));
      if (allActive) activeLogLevels.clear();
      else LOG_LEVELS.forEach(l => activeLogLevels.add(l));
    } else {
      if (activeLogLevels.has(lvl)) activeLogLevels.delete(lvl);
      else activeLogLevels.add(lvl);
    }
    updateLogFilterButtons();
    applyLogFilters();
  });
}

// 手动暂停 / 恢复自动滚动
pauseLogBtn.addEventListener('click', () => setLogPaused(logAutoScroll));

// 用户向上滚动时自动暂停；滚到底部恢复
terminal.addEventListener('scroll', () => {
  const nearBottom = terminal.scrollTop + terminal.clientHeight >= terminal.scrollHeight - 50;
  if (nearBottom && !logAutoScroll) setLogPaused(false);
  else if (!nearBottom && logAutoScroll) setLogPaused(true);
});

clearLogBtn.addEventListener('click', () => {
  terminal.innerHTML = '';
  logStageBadge.textContent = 'IDLE';
});

// ── 页面初始化 ────────────────────────────────────────────────────────
// 页面加载时拉取参数 Schema 与任务历史
loadBridgeSchema();
loadJobHistory();
