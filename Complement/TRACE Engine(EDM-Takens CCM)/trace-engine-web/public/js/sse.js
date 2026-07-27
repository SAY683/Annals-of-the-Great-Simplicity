/* TRACE Engine Web — SSE 流处理（debt-09 + debt-11）
 * ==================================================
 * 抽取自原 index.html 内联 <script>。
 *
 * debt-11：SSE 重连支持
 *   - parseSSEBlock 解析 `id:` 行，更新 lastSseEventId
 *   - 重连时通过 Last-Event-ID 请求头携带最后接收的事件 ID
 *   - 服务端 sendSSE 已为每个事件写入递增 id + retry:30000（30 秒重连间隔，跨项目契约对齐 trace-to-edm/server.js）
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
 *
 * P0 修缮（跨项目 SSE 一致性）：支持 3 次手动重连 + 指数退避 1s/2s/4s。
 * 参考实现：trace-to-edm/public/js/app.js streamJob。
 *
 * 向后兼容：第二个参数 options 可省略，省略时与原行为一致（仅消费 body，不重连）。
 *
 * @param {ReadableStream} body fetch response body
 * @param {object} [options] 可选参数
 * @param {function} [options.reconnectFactory] 重连时重新发起 fetch 的工厂函数，返回 Response；
 *                                              未提供则不重连（保持向后兼容）
 * @param {AbortSignal} [options.signal] AbortSignal，触发时立即停止重连（保持 AbortError 语义）
 */
async function readSSEStream(body, options = {}) {
  const { reconnectFactory, signal, onEvent } = options;
  const maxRetries = 3;
  let attempt = 0;
  let currentBody = body;

  while (true) {
    try {
      await consumeSSEBody(currentBody, onEvent);
      return;
    } catch (err) {
      // 用户主动 abort：直接抛出（保持原 AbortError 语义，由 app.js catch 跳过提示）
      if (signal && signal.aborted) throw err;
      // 未提供 reconnectFactory：保持向后兼容，直接抛出
      if (!reconnectFactory) throw err;
      // 已达最大重试次数：抛出明确错误
      if (attempt >= maxRetries) {
        const exhausted = new Error(`SSE 连接中断，已重连 ${maxRetries} 次仍失败: ${err.message || err}`);
        throw exhausted;
      }
      attempt++;
      // 指数退避：1000ms → 2000ms → 4000ms
      const delayMs = 1000 * Math.pow(2, attempt - 1);
      try { log('warn', `⟲ 连接中断，第 ${attempt}/${maxRetries} 次重连（${delayMs}ms 后）...`); } catch (_) {}
      await sleepCancellable(delayMs, signal);
      // 退避期间用户可能 abort，再次检查
      if (signal && signal.aborted) throw err;
      const response = await reconnectFactory();
      if (!response.ok || !response.body) {
        throw new Error(`重连失败: HTTP ${response.status}`);
      }
      currentBody = response.body;
    }
  }
}

/**
 * 消费单个 SSE body 流（原 readSSEStream 主体逻辑）。
 * body 正常结束（done=true）时返回；读取过程中抛错则向上传播给 readSSEStream 触发重连。
 */
async function consumeSSEBody(body, onEvent) {
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
      if (typeof onEvent === 'function') onEvent(event);
      dispatchSSEEvent(event);
    }
  }
  if (buffer.trim()) {
    const event = parseSSEBlock(buffer);
    if (event) {
      if (typeof onEvent === 'function') onEvent(event);
      dispatchSSEEvent(event);
    }
  }
}

/**
 * 可取消的 sleep。signal 触发时立即 reject(AbortError)。
 * 用于重连退避期间响应用户主动取消。
 */
function sleepCancellable(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal && signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(resolve, ms);
    if (signal) {
      signal.addEventListener('abort', () => {
        clearTimeout(timer);
        reject(new DOMException('Aborted', 'AbortError'));
      }, { once: true });
    }
  });
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
  const lbl = document.getElementById('statsLabel');
  if (lbl) lbl.textContent = stats.label || '处理中';
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
      log('done', '✓ 任务完成');
      setRunning(false);
      loadJobHistory();
    }
  } catch (err) {
    log('raw', data);
  }
}
