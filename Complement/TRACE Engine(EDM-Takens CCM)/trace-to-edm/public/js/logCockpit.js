/**
 * trace-to-edm 日志 cockpit 纯函数工具
 * 从 app.js 抽离，便于 Node 单元测试与前端共享。
 *
 * 注意：所有声明封装在 IIFE 内，避免污染浏览器全局作用域，
 * 防止与 app.js 顶层 const 解构（如 LOG_MAX_LINES）冲突导致 SyntaxError。
 */
(function () {
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
    progress: 'stage',
    info: 'info',
    warn: 'warn',
    error: 'error',
    done: 'info',
    log: 'info',
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));
  }

  function formatLogEntry(entry, filters) {
    const level = entry.level || 'log';
    if (filters && !filters.has(level)) return null;
    // 过滤无意义行：空行、纯分隔符行（ASCII #### ==== ---- **** 或 Unicode 制表符 ─━│┃═║ 等）
    const trimmed = String(entry.message).trim();
    if (!trimmed) return null;
    // 去除空格后检测纯分隔符（如 "── ── ──" → "────────"）
    const noSpaces = trimmed.replace(/\s+/g, '');
    if (/^[#=\-*+_~─━│┃═║╔╗╚╝╠╣╦╩╬]+$/.test(noSpaces)) return null;
    // 过滤单字符重复 4 次以上的纯分隔行（如 ────── 或 ======）
    if (/^(.)\1{4,}$/.test(noSpaces)) return null;
    // 过滤纯图标行（单个符号无实际内容）
    if (/^[◉▶▲✖✓✦○●◇◆□■△▽☆★]+$/.test(noSpaces)) return null;
    const icon = LOG_ICONS[level] || '◉ INFO';
    const cls = LOG_CLASSES[level] || 'info';
    const ts = entry.time instanceof Date
      ? entry.time.toLocaleTimeString('zh-CN', { hour12: false })
      : '00:00:00';
    const iconChar = icon.split(' ')[0];
    const levelText = icon.split(' ')[1] || '';
    return `<div class="terminal-line ${cls}" data-level="${level}"><span class="log-icon">${iconChar}</span><span class="log-level">${levelText}</span><span class="log-ts">[${ts}]</span><span class="log-msg">${escapeHtml(entry.message)}</span></div>`;
  }

  function countByLevel(buffer) {
    const counts = { progress: 0, info: 0, warn: 0, error: 0, done: 0, log: 0 };
    buffer.forEach(e => { if (counts[e.level] !== undefined) counts[e.level]++; });
    return counts;
  }

  function trimBuffer(buffer, maxLines) {
    const max = (typeof maxLines === 'number' && maxLines > 0) ? maxLines : LOG_MAX_LINES;
    if (buffer.length > max) {
      return buffer.slice(buffer.length - max);
    }
    return buffer;
  }

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
})();
