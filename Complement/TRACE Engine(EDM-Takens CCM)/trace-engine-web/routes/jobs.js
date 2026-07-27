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
const { OUTPUT_DIR, INPUTS_DIR, CONFIG, activeJobs, jobHistory, resultCache } = state;
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

// ── 批量删除任务历史（P1-c：批量工具栏后端支持） ───────────────────
router.post('/batch-delete', (req, res) => {
  const { ids } = req.body;
  if (!Array.isArray(ids) || ids.length === 0) {
    return res.status(400).json({ success: false, error: 'ids 数组不能为空' });
  }
  // 安全校验：过滤非法 ID，防止注入
  const validIds = ids.filter(id => isValidId(id));
  if (validIds.length === 0) {
    return res.status(400).json({ success: false, error: '无有效任务 ID' });
  }
  // 不允许删除正在运行的任务
  const runningIds = validIds.filter(id => activeJobs.has(id));
  const deletableIds = validIds.filter(id => !activeJobs.has(id));
  let removed = 0;
  for (let i = jobHistory.length - 1; i >= 0; i--) {
    if (deletableIds.includes(jobHistory[i].id)) {
      jobHistory.splice(i, 1);
      removed++;
    }
  }
  persistJobHistory();
  res.json({
    success: true,
    removed,
    skipped: runningIds.length > 0 ? `${runningIds.length} 个任务正在运行，已跳过` : null,
  });
});

// ── 删除单条任务历史（P1-c：批量工具栏后端支持） ─────────────────────
router.delete('/:id', (req, res) => {
  const id = req.params.id;
  if (!isValidId(id)) {
    return res.status(400).json({ success: false, error: '非法的任务 ID' });
  }
  if (activeJobs.has(id)) {
    return res.status(409).json({ success: false, error: '任务正在运行，无法删除' });
  }
  const idx = jobHistory.findIndex(j => j.id === id);
  if (idx < 0) {
    return res.status(404).json({ success: false, error: '任务不存在' });
  }
  jobHistory.splice(idx, 1);
  persistJobHistory();
  res.json({ success: true, removed: 1 });
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

// ── 单任务详情聚合（历史任务详情查看：聚合 job 元数据 + 输入文本 + result.json + report.md） ─
// 注意：路径必须放在 GET /:id 之后；Express 会按定义顺序匹配，此处 /:id/detail 不会被 /:id 抢先。
router.get('/:id/detail', async (req, res) => {
  const id = req.params.id;
  // 校验 UUID，防止 path.join 拼接出路径遍历
  if (!isValidId(id)) {
    return res.status(400).json({ success: false, error: '非法的任务 ID' });
  }
  // 从历史中查找任务元数据
  const job = jobHistory.find(j => j.id === id);
  if (!job) {
    return res.status(404).json({ success: false, error: 'job not found' });
  }

  // P0 修缮：safeReadFile 返回 { data, exists, reason } 三元组
  // 让前端能区分"未落盘/已被清理"vs"读取出错"vs"JSON 解析失败"，
  // 不再把所有 null 误判为"已过 TTL 清理"
  const safeReadFile = async (filePath, isJson = false) => {
    let exists = false;
    try {
      await fs.promises.access(filePath, fs.constants.R_OK);
      exists = true;
    } catch (_) {
      return { data: null, exists: false, reason: 'not_found' };
    }
    try {
      const raw = await fs.promises.readFile(filePath, 'utf-8');
      if (!isJson) return { data: raw, exists: true, reason: null };
      try {
        return { data: JSON.parse(raw), exists: true, reason: null };
      } catch (parseErr) {
        return { data: null, exists: true, reason: `json_parse_failed: ${parseErr.message}` };
      }
    } catch (readErr) {
      return { data: null, exists: true, reason: `read_error: ${readErr.code || readErr.message}` };
    }
  };

  const [inputRes, resultRes, reportRes] = await Promise.all([
    safeReadFile(path.join(INPUTS_DIR, `${id}.txt`), false),
    safeReadFile(path.join(OUTPUT_DIR, id, 'result.json'), true),
    safeReadFile(path.join(OUTPUT_DIR, id, 'report.md'), false),
  ]);

  // 同时返回结构化诊断字段，前端可据此给出准确提示
  // diagnostics 中包含 TTL 配置与路径，便于运维排查
  const diagnostics = {
    inputExists: inputRes.exists,
    inputReason: inputRes.reason,
    resultExists: resultRes.exists,
    resultReason: resultRes.reason,
    reportExists: reportRes.exists,
    reportReason: reportRes.reason,
    inputsTtlMs: CONFIG && CONFIG.inputsTtlMs ? CONFIG.inputsTtlMs : null,
    outputTtlMs: CONFIG && CONFIG.outputTtlMs ? CONFIG.outputTtlMs : null,
    inputsDir: INPUTS_DIR,
    outputDir: path.join(OUTPUT_DIR, id),
    jobCreatedAt: job && job.createdAt ? job.createdAt : null,
    jobEndedAt: job && job.endedAt ? job.endedAt : null,
  };

  res.json({
    success: true,
    job,
    inputText: inputRes.data,
    result: resultRes.data,
    report: reportRes.data,
    diagnostics,
  });
});

module.exports = router;
