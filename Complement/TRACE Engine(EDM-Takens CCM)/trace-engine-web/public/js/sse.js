/* TRACE Engine Web — SSE 流处理（debt-09 + debt-11）
 * ==================================================
 * 抽取自原 index.html 内联 <script>。
 *
 * debt-11：SSE 重连支持
 *   - parseSSEBlock 解析 `id:` 行，更新 lastSseEventId
 *   - 重连时通过 Last-Event-ID 请求头携带最后接收的事件 ID
 *   - 服务端 sendSSE 已为每个事件写入递增 id + retry:5000
 *
 * 依赖（运行时由 app.js / render.js 提供）：
 *   - log(level, message)         由 render.js 提供
 *   - updateProgress(stage, p)    由 app.js 提供
 *   - renderResult(obj)           由 render.js 提供
 *   - showToast(msg, type)        由 render.js 提供
 *   - setRunning(bool)            由 app.js 提供
 *   - loadJobHistory()            由 jobs.js 提供
 *   - superStats/statsRate/...    由 app.js 提供（DOM 引用）
 */

// debt-11：最后接收的 SSE 事件 ID（用于重连续传）
let lastSseEventId = null;

/**
 * 读取 SSE 流。debt-11：解析 id: 行并更新 lastSseEventId。
 * @param {ReadableStream} body fetch response body
 */
async function readSSEStream(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop();
    for (const block of blocks) {
      const event = parseSSEBlock(block);
      if (!event) continue;
      dispatchSSEEvent(event);
    }
  }
  if (buffer.trim()) {
    const event = parseSSEBlock(buffer);
    if (event) dispatchSSEEvent(event);
  }
}

/**
 * 解析单个 SSE 事件块。debt-11：同时解析 `id:` 行以更新 lastSseEventId。
 * 支持的行类型：id / event / data / 注释（:heartbeat）
 */
function parseSSEBlock(block) {
  const lines = block.split('\n');
  let event = 'message';
  let data = '';
  let id = null;
  for (const line of lines) {
    if (line.startsWith('id:')) {
      id = line.slice(3).trim();
    } else if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      data += (data ? '\n' : '') + line.slice(5).trim();
    }
    // :heartbeat 等注释行被忽略
  }
  // debt-11：更新最后接收的事件 ID，供重连时发送 Last-Event-ID 头
  if (id !== null) {
    lastSseEventId = id;
  }
  return data ? { event, data, id } : null;
}

function formatDuration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m${s % 60}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h${m}m`;
}

function updateStats(stats) {
  if (!stats || !superStats) return;
  superStats.style.display = 'block';
  statsRate.textContent = stats.rate != null ? stats.rate.toFixed(1) : '--';
  statsProcessed.textContent = stats.processed_pairs != null ? stats.processed_pairs.toLocaleString() : '--';
  statsTotal.textContent = stats.total_pairs != null ? stats.total_pairs.toLocaleString() : '--';
  statsEta.textContent = stats.remaining_seconds != null ? formatDuration(stats.remaining_seconds) : '--';
}

function hideStats() {
  if (superStats) superStats.style.display = 'none';
}

function dispatchSSEEvent({ event, data }) {
  try {
    const obj = JSON.parse(data);
    if (event === 'stage') {
      updateProgress(obj.stage, obj.progress ?? null);
    } else if (event === 'log') {
      log(obj.level, obj.message);
    } else if (event === 'stats') {
      updateStats(obj);
    } else if (event === 'result') {
      hideStats();
      renderResult(obj);
      showToast('分析完成', 'success');
      setRunning(false);
      loadJobHistory();
    } else if (event === 'error') {
      hideStats();
      log('error', obj.message || 'SSE 错误');
      showToast(obj.message || '分析失败', 'error');
      setRunning(false);
      loadJobHistory();
    } else if (event === 'done') {
      hideStats();
      setRunning(false);
      loadJobHistory();
    }
  } catch (err) {
    log('raw', data);
  }
}
