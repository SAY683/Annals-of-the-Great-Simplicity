/**
 * trace-to-edm 日志 cockpit 纯函数工具
 * 从 app.js 抽离，便于 Node 单元测试与前端共享。
 */

const LOG_MAX_LINES = 400;
const LOG_ICONS = {
  progress: '▶ STAGE',
  info: '◉ INFO',
  warn: '▲ WARN',
  error: '✖ ERROR',
  done: '✓ DONE',
  log: '◉ INFO',
};
const LOG_CLASSES = {
  progress: 'progress',
  info: 'info',
  warn: 'warn',
  error: 'error',
  done: 'done',
  log: 'log',
};

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));
}

function formatLogEntry(entry, filters) {
  const level = entry.level || 'log';
  if (filters && !filters.has(level)) return null;
  const icon = LOG_ICONS[level] || '◉ INFO';
  const cls = LOG_CLASSES[level] || 'log';
  const ts = entry.time instanceof Date
    ? entry.time.toLocaleTimeString('zh-CN', { hour12: false })
    : '00:00:00';
  return `<div class="terminal-line ${cls}" data-level="${level}"><span class="log-badge">${icon}</span><span class="log-ts">[${ts}]</span> ${escapeHtml(entry.message)}</div>`;
}

function countByLevel(buffer) {
  const counts = { progress: 0, info: 0, warn: 0, error: 0, done: 0, log: 0 };
  buffer.forEach(e => { if (counts[e.level] !== undefined) counts[e.level]++; });
  return counts;
}

function trimBuffer(buffer, maxLines = LOG_MAX_LINES) {
  if (buffer.length > maxLines) {
    return buffer.slice(buffer.length - maxLines);
  }
  return buffer;
}

// 浏览器与 Node 兼容导出
const LogCockpit = {
  LOG_MAX_LINES, LOG_ICONS, LOG_CLASSES,
  escapeHtml, formatLogEntry, countByLevel, trimBuffer,
};

if (typeof window !== 'undefined') {
  window.LogCockpit = LogCockpit;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = LogCockpit;
}
