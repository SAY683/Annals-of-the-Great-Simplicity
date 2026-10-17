const fs = require('fs');
const { LOG_FILE } = require('../config');

function serverLog(level, message, traceId = '') {
  const ts = new Date().toISOString();
  const trace = traceId ? ` [${traceId}]` : '';
  const line = `[${ts}]${trace} [${level}] ${message}\n`;
  fs.appendFile(LOG_FILE, line, () => {});
  if (process.env.TRACE_DEBUG_LOG) console.log(line.trim());
}

function reqLog(req, level, message) {
  serverLog(level, message, req.traceId);
}

module.exports = { serverLog, reqLog };
