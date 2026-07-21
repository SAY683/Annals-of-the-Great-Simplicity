/**
 * TRACE Engine Web — 任务历史路由（debt-08）
 * =====================================
 * 包含：/api/jobs、/api/jobs/export、/api/jobs/clear、/api/jobs/:id
 */
const express = require('express');
const path = require('path');
const fs = require('fs');

const router = express.Router();

const state = require('../lib/state');
const utils = require('../lib/utils');
const { OUTPUT_DIR, activeJobs, jobHistory, resultCache } = state;
const { persistJobHistory, isValidId } = utils;

// ── 任务历史列表 ────────────────────────────────────────────────────
router.get('/', (_req, res) => {
  res.json({
    success: true,
    active: Array.from(activeJobs.keys()),
    history: jobHistory.slice(-50),
    cacheSize: resultCache.size,
  });
});

// ── 导出任务历史（必须在 /api/jobs/:id 之前定义） ─────────────────
router.get('/export', (_req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Content-Disposition', 'attachment; filename="trace_jobs.json"');
  res.json({ success: true, exportedAt: new Date().toISOString(), jobs: jobHistory });
});

// ── 清空任务历史（debt-12：管理员路径，由 auth 中间件保护） ─────────
router.post('/clear', (_req, res) => {
  jobHistory.length = 0;
  persistJobHistory();
  res.json({ success: true, message: '任务历史已清空' });
});

// ── 单任务查询 ──────────────────────────────────────────────────────
router.get('/:id', (req, res) => {
  const id = req.params.id;
  // Q9 P0-3 修复：校验 UUID 格式，防止 path.join(OUTPUT_DIR, id, ...) 路径遍历
  if (!isValidId(id)) {
    return res.status(400).json({ success: false, error: '非法的任务 ID', code: 'ERROR' });
  }
  const active = activeJobs.has(id);
  const history = jobHistory.find((j) => j.id === id);
  const outputExists = fs.existsSync(path.join(OUTPUT_DIR, id, 'result.json'));
  if (!active && !history && !outputExists) {
    return res.status(404).json({ success: false, error: '任务不存在' });
  }
  res.json({
    success: true,
    id,
    active,
    history: history || null,
    resultPath: outputExists ? `/api/result/${id}` : null,
    reportPath: fs.existsSync(path.join(OUTPUT_DIR, id, 'report.md')) ? `/api/report/${id}` : null,
  });
});

module.exports = router;
