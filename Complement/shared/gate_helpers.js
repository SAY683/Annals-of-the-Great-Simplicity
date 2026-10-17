'use strict';

function safeNextPath(value, fallback = '/') {
  const raw = String(value || '');
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\') || /[\r\n]/.test(raw)) {
    return fallback;
  }
  return raw;
}

function parseCookies(header) {
  const out = {};
  String(header || '').split(';').forEach(part => {
    const idx = part.indexOf('=');
    if (idx <= 0) return;
    const key = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    try {
      out[key] = decodeURIComponent(value);
    } catch {
      // Ignore malformed cookies instead of letting one bad header crash the gate.
    }
  });
  return out;
}

module.exports = { safeNextPath, parseCookies };