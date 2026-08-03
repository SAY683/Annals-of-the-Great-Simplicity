/**
 * TRACE Engine Web — 管理员路由（debt-08）
 * =====================================
 * 包含：/api/admin/cleanup（debt-12：管理员路径，由 auth 中间件保护）
 */
const express = require('express');

const router = express.Router();

const state = require('../lib/state');
const utils = require('../lib/utils');
const { CONFIG, OUTPUT_DIR, INPUTS_DIR } = state;
const { logToFile } = utils;

// ── 输出 + 输入目录 TTL 清理（debt-14：work/inputs 也纳入清理） ─────
function cleanupOldOutputs() {
  const now = Date.now();
  let totalCleaned = 0;

  // 1. outputs/ 目录清理（原有行为）
  try {
    const dirs = require('fs').readdirSync(OUTPUT_DIR);
    let cleaned = 0;
    for (const dir of dirs) {
      const full = require('path').join(OUTPUT_DIR, dir);
      try {
        // P1-1 修复 (ROUND27 12维度核对): 用 lstatSync 不跟随符号链接,
        // 防止植入的 symlink 指向系统目录被 rmSync(recursive) 递归删除.
        // statSync 会跟随 symlink, lstatSync 返回符号链接本身的信息.
        const lstat = require('fs').lstatSync(full);
        if (lstat.isSymbolicLink()) {
          console.warn(`[cleanup] 跳过符号链接: ${dir} (潜在安全风险)`);
          continue;
        }
        const stat = require('fs').statSync(full);
        if (now - stat.mtimeMs > CONFIG.outputTtlMs) {
          require('fs').rmSync(full, { recursive: true, force: true });
          cleaned += 1;
        }
      } catch (_) { /* ignore */ }
    }
    if (cleaned > 0) {
      console.log(`[cleanup] 已清理 ${cleaned} 个过期输出目录`);
      totalCleaned += cleaned;
    }
  } catch (err) {
    console.error('[cleanup] 清理 outputs 失败:', err.message);
  }

  // 2. inputs/ 目录清理（debt-14：新增）
  try {
    const path = require('path');
    const fs = require('fs');
    if (fs.existsSync(INPUTS_DIR)) {
      const files = fs.readdirSync(INPUTS_DIR);
      let cleaned = 0;
      for (const file of files) {
        if (!file.endsWith('.txt')) continue;
        const full = path.join(INPUTS_DIR, file);
        try {
          const stat = fs.statSync(full);
          if (now - stat.mtimeMs > CONFIG.inputsTtlMs) {
            fs.rmSync(full, { force: true });
            cleaned += 1;
          }
        } catch (_) { /* ignore */ }
      }
      if (cleaned > 0) {
        console.log(`[cleanup] 已清理 ${cleaned} 个过期输入文件`);
        totalCleaned += cleaned;
      }
    }
  } catch (err) {
    console.error('[cleanup] 清理 inputs 失败:', err.message);
  }

  return totalCleaned;
}

// ── 手动触发清理 ────────────────────────────────────────────────────
router.post('/cleanup', (_req, res) => {
  const cleaned = cleanupOldOutputs();
  logToFile('info', `手动清理完成：移除 ${cleaned} 个条目`);
  res.json({ success: true, message: '输出目录清理完成', cleaned });
});

module.exports = {
  router,
  cleanupOldOutputs,
};
