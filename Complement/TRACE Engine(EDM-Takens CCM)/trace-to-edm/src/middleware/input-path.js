const fs = require('fs');
const path = require('path');
const util = require('util');
const { ROOT } = require('../config');
const { reqLog } = require('../services/logger');

const realpathAsync = util.promisify(fs.realpath);

async function resolveInputPath(csv_path) {
  // 未指定时使用默认示例文件
  if (!csv_path) {
    return path.join(ROOT, 'data', 'inputs', 'example_input.csv');
  }
  // 拒绝包含 .. 或空字符的可疑路径（第一道防线）
  if (csv_path.includes('..') || csv_path.includes('\0')) {
    throw new Error('invalid path: traversal detected');
  }
  // 解析并真实化路径，防御符号链接绕过
  const resolved = await realpathAsync(path.resolve(ROOT, csv_path)).catch(() => {
    // 文件不存在时回退到逻辑解析路径（用于后续错误提示）
    return path.resolve(ROOT, csv_path);
  });
  // 仅允许 data/inputs/ 或 projects/<name>/inputs/ 下的文件
  const allowedRoots = [
    path.join(ROOT, 'data', 'inputs'),
    path.join(ROOT, 'projects'),
  ];
  const inside = allowedRoots.some(ar => resolved === ar || resolved.startsWith(ar + path.sep));
  if (!inside) {
    throw new Error('invalid path: outside allowed input directories');
  }
  return resolved;
}

// 通用输入路径校验中间件（适用于 req.body.csv_path / req.query.path 等）
function validateInputPathMiddleware(req, res, next) {
  const csvPath = req.body && req.body.csv_path;
  if (csvPath === undefined) return next();
  resolveInputPath(csvPath)
    .then(resolved => { req.resolvedInputPath = resolved; next(); })
    .catch(err => {
      reqLog(req, 'warn', `路径校验失败: ${csvPath} -> ${err.message}`);
      res.status(400).json({ error: err.message });
    });
}


module.exports = { resolveInputPath, validateInputPathMiddleware };
