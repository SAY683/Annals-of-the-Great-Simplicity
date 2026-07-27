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

// ── P2 (§20.12): 一键导出人话版 Markdown 报告 ─────────────────────
// 将 result.json 转译为非技术读者可理解的中文报告.
// 设计目标: 用户读这份 .md 就能知道 "这次因果推断说了什么、可不可信、有哪些因果链".
//
// 报告结构:
//   1. 概览 (任务 ID, 模式, 处理 vs 结果, ATE + CI)
//   2. 可识别性诊断 (estimand 类型 + 是否可识别 + 解读)
//   3. 反驳测试 (Robust vs Refuted + 偏差)
//   4. 显著因果边 (Top 10)
//   5. 反事实扫描 (ITE + ΔNLL)
//   6. 概念词汇 (频次 + CCM 资格)
//   7. 配置与执行附录
router.get('/:id/export/md', async (req, res) => {
  const id = req.params.id;
  if (!isValidId(id)) {
    return res.status(400).json({ success: false, error: '非法的任务 ID' });
  }
  const job = jobHistory.find(j => j.id === id);
  if (!job) {
    return res.status(404).json({ success: false, error: 'job not found' });
  }

  // 复用 detail 端点的安全读取逻辑
  const safeReadFile = async (filePath, isJson = false) => {
    try {
      await fs.promises.access(filePath, fs.constants.R_OK);
    } catch (_) {
      return { data: null, exists: false };
    }
    try {
      const raw = await fs.promises.readFile(filePath, 'utf-8');
      if (!isJson) return { data: raw, exists: true };
      try {
        return { data: JSON.parse(raw), exists: true };
      } catch (parseErr) {
        return { data: null, exists: true, reason: `json_parse_failed: ${parseErr.message}` };
      }
    } catch (readErr) {
      return { data: null, exists: true, reason: `read_error: ${readErr.code || readErr.message}` };
    }
  };

  const [resultRes, reportRes] = await Promise.all([
    safeReadFile(path.join(OUTPUT_DIR, id, 'result.json'), true),
    safeReadFile(path.join(OUTPUT_DIR, id, 'report.md'), false),
  ]);

  const r = resultRes.data || {};
  const reportMd = reportRes.data || '';
  const inputTextPath = path.join(INPUTS_DIR, `${id}.txt`);
  let inputText = '';
  try {
    if (fs.existsSync(inputTextPath)) inputText = fs.readFileSync(inputTextPath, 'utf-8');
  } catch (_) { /* ignore */ }

  // 辅助函数
  const fmt = (v, d = 4) => (v == null ? 'N/A' : (typeof v === 'number' ? v.toFixed(d) : String(v)));
  const fmtTs = (iso) => {
    if (!iso) return 'N/A';
    try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }); } catch (_) { return String(iso); }
  };

  const mode = (r.analysis_mode || job.mode || 'light').toString().toUpperCase();
  const modeNote = (r.mode || '').includes('模拟') || (r.mode || '').includes('SEM')
    ? '⚠️ **模式提示**: 本次分析使用 SEM 模拟模式 (结构方程模型生成合成数据), ATE 为模拟估计, 不可识别, 仅用于算法管道完整性验证.'
    : '';
  const identifiable = r.identifiable === true;
  const ate = r.ate;
  const ci = r.confidence_interval || [];
  const refutations = r.refutations || [];
  const topEdges = r.top_edges || [];
  const cfScan = r.counterfactual_scan || [];
  const concepts = r.concepts || [];
  const conceptFreq = r.concept_frequencies || {};
  const ccmEligible = r.ccm_eligible_concepts || [];
  const identifiability = r.identifiability || {};
  const execProfile = r.execution_profile || {};
  const refutedCount = refutations.filter(x => x.refuted).length;
  const robustCount = refutations.length - refutedCount;

  const lines = [];
  lines.push(`# TRACE Engine 因果推断报告: ${id}\n`);
  lines.push(`> 自动生成 — 面向非技术读者的人话版解读. 报告基于任务 \`${id}\` 的 result.json + report.md 转译.\n`);
  lines.push('');

  // 1. 概览
  lines.push('## 1. 概览\n');
  lines.push(`- **任务 ID**: \`${id}\``);
  lines.push(`- **创建时间**: ${fmtTs(job.createdAt)}`);
  if (job.endedAt) lines.push(`- **结束时间**: ${fmtTs(job.endedAt)}`);
  if (job.durationMs != null) lines.push(`- **耗时**: ${(job.durationMs / 1000).toFixed(2)} 秒`);
  lines.push(`- **分析模式**: ${mode}`);
  lines.push(`- **处理变量 (Treatment)**: \`${r.treatment || 'N/A'}\``);
  lines.push(`- **结果变量 (Outcome)**: \`${r.outcome || 'N/A'}\``);
  lines.push(`- **ATE (平均因果效应)**: ${fmt(ate)}`);
  if (ci.length === 2) {
    lines.push(`- **95% 置信区间**: [${fmt(ci[0], 4)}, ${fmt(ci[1], 4)}]`);
    lines.push(`- **置信区间方法**: ${r.confidence_method || 'N/A'}`);
  }
  lines.push(`- **显著因果边数**: ${r.n_significant_edges ?? 'N/A'}`);
  // P0-1 修复 (Round 21 §P0-C): 暴露 condition_number 诊断, 论文已披露 5.5×10¹² 病态问题.
  // cond > 1e10 时 OLS 估计方差无穷大, CI 不可信, 必须在报告头部显著标注.
  const condNum = r.execution_profile?.condition_number ?? r.condition_number;
  if (condNum != null && isFinite(condNum)) {
    const condVal = typeof condNum === 'number' ? condNum : parseFloat(condNum);
    if (isFinite(condVal)) {
      const condStr = condVal.toExponential(2);
      if (condVal > 1e10) {
        lines.push(`- **设计矩阵条件数**: ${condStr} ⚠️ **病态** — CI 不可信, ATE 估计方差无穷大`);
      } else if (condVal > 1e6) {
        lines.push(`- **设计矩阵条件数**: ${condStr} ⚠️ 接近病态, CI 应谨慎解读`);
      } else {
        lines.push(`- **设计矩阵条件数**: ${condStr} ✓ 良好`);
      }
    }
  }
  if (modeNote) {
    lines.push('');
    lines.push(modeNote);
  }
  lines.push('');

  // 2. 可识别性诊断
  lines.push('## 2. 可识别性诊断\n');
  lines.push(`- **是否可识别**: ${identifiable ? '✓ 可识别 (可基于观测数据无偏估计 ATE)' : '✗ 不可识别 (存在未观测混淆, ATE 估计有偏)'}`);
  lines.push(`- **Estimand 类型**: ${identifiability.estimand_type || 'N/A'}`);
  lines.push(`- **后门路径**: ${identifiability.backdoor_paths || 'N/A'}`);
  const adjSet = identifiability.adjustment_set;
  if (Array.isArray(adjSet)) {
    lines.push(`- **调整集**: ${adjSet.length > 0 ? adjSet.map(s => `\`${s}\``).join(', ') : '(空)'}`);
  }
  if (r.n_samples != null) lines.push(`- **样本量**: ${r.n_samples}`);
  lines.push('');
  lines.push('> **解读**: "可识别" 表示在因果图 (DAG) 假设下, 我们能从观测数据中无偏估计出因果效应. '
    + '若不可识别, ATE 数值仅为关联性而非因果性, 需谨慎使用.\n');

  // 3. 反驳测试
  lines.push('## 3. 反驳测试 (稳健性)\n');
  if (refutations.length > 0) {
    lines.push(`- **稳健**: ${robustCount}/${refutations.length} 项`);
    lines.push(`- **被反驳**: ${refutedCount}/${refutations.length} 项`);
    lines.push('');
    lines.push('| 方法 | 原 ATE | 新 ATE | 偏差指标 | 判定 |');
    lines.push('|------|--------|--------|----------|------|');
    refutations.forEach(ref => {
      const verdict = ref.refuted ? '✗ 被反驳' : '✓ 稳健';
      const label = ref.display_label || '';
      lines.push(`| ${ref.method || '?'} | ${fmt(ate)} | ${fmt(ref.new_effect)} | ${fmt(ref.display_metric, 3)} ${label} | ${verdict} |`);
    });
    lines.push('');
    lines.push('> **解读**: 反驳测试用各种"找茬"方式 (随机共因/安慰剂/数据子集) 检验 ATE 是否站得住脚. '
      + '全部稳健 = 结论可信; 被反驳越多 = ATE 越可能是统计假象.\n');
  } else {
    lines.push('- 未运行反驳测试 (可能因 LIGHT 模式或样本量不足).\n');
  }

  // 4. 显著因果边
  lines.push('## 4. 显著因果边 (Top 10)\n');
  if (topEdges.length > 0) {
    lines.push('| 源 → 目标 | 强度 | 方向 |');
    lines.push('|-----------|------|------|');
    topEdges.slice(0, 10).forEach(e => {
      lines.push(`| \`${e.source}\` → \`${e.target}\` | ${fmt(e.strength, 3)} | ${e.direction || '→'} |`);
    });
    lines.push('');
    lines.push('> **解读**: 强度越高 = 该因果边的统计证据越强. 方向 "→" 表示源变量影响目标变量.\n');
  } else {
    lines.push('- 未识别出显著因果边.\n');
  }

  // 5. 反事实扫描
  lines.push('## 5. 反事实扫描 (ITE)\n');
  if (cfScan.length > 0) {
    lines.push('| 边 | ΔNLL | ITE | 观测值 | 反事实值 |');
    lines.push('|----|------|-----|--------|----------|');
    cfScan.slice(0, 10).forEach(c => {
      lines.push(`| \`${c.source}\`→\`${c.target}\` | ${fmt(c.trace_dnl, 3)} | ${fmt(c.ite, 2)} | ${fmt(c.observed, 1)} | ${fmt(c.counterfactual, 1)} |`);
    });
    lines.push('');
    lines.push('> **解读**: 反事实扫描回答"如果干预了源变量, 目标变量会变成多少". '
      + 'ITE (个体处理效应) 越大 = 干预对该个体的影响越大; ΔNLL = 因果信号强度.\n');
  } else {
    lines.push('- 未运行反事实扫描.\n');
  }

  // 6. 概念词汇
  lines.push('## 6. 概念词汇 (Top 15)\n');
  if (concepts.length > 0) {
    lines.push('| 概念 | 出现频次 | CCM 可用? |');
    lines.push('|------|----------|-----------|');
    concepts.slice(0, 15).forEach(c => {
      const freq = conceptFreq[c] ?? 0;
      const eligible = ccmEligible.includes(c) ? '✓' : '—';
      lines.push(`| \`${c}\` | ${freq} | ${eligible} |`);
    });
    lines.push('');
    lines.push('> **解读**: CCM 可用 = 该概念频次足够且为名词性, 适合做 CCM 因果方向验证.\n');
  } else {
    lines.push('- 未提取到概念词汇.\n');
  }

  // 7. 配置与执行附录
  lines.push('## 7. 配置与执行附录\n');
  lines.push('### 任务元数据\n');
  lines.push('| 字段 | 值 |');
  lines.push('|------|----|');
  lines.push(`| job ID | \`${id}\` |`);
  lines.push(`| 模式 | ${mode} |`);
  lines.push(`| 状态 | ${job.status || 'N/A'} |`);
  if (job.textPreview) {
    const preview = String(job.textPreview).slice(0, 200);
    lines.push(`| 输入预览 | ${preview.replace(/\|/g, '\\|')} |`);
  }
  lines.push('');

  if (execProfile && Object.keys(execProfile).length > 0) {
    lines.push('### 执行画像\n');
    lines.push('| 字段 | 值 |');
    lines.push('|------|----|');
    for (const [k, v] of Object.entries(execProfile)) {
      if (v == null) continue;
      let val = v;
      if (typeof v === 'number') val = (v > 1000 ? v.toLocaleString() : v);
      if (typeof v === 'object') val = JSON.stringify(v);
      lines.push(`| \`${k}\` | \`${val}\` |`);
    }
    lines.push('');
  }

  // 输入文本
  if (inputText) {
    lines.push('## 8. 输入文本 (附录)\n');
    lines.push('```text');
    lines.push(inputText.slice(0, 2000) + (inputText.length > 2000 ? '\n... (已截断)' : ''));
    lines.push('```\n');
  }

  // 原 report.md 附在末尾
  if (reportMd) {
    lines.push('## 9. 原始 report.md (附录)\n');
    lines.push(reportMd);
    lines.push('');
  }

  // 总结
  lines.push('---');
  lines.push(`_报告由 TRACE Engine Web 自动生成于 ${fmtTs(new Date().toISOString())}._`);

  const mdContent = lines.join('\n');
  res.setHeader('Content-Type', 'text/markdown; charset=utf-8');
  res.setHeader('Content-Disposition', `attachment; filename="${id}_report.md"`);
  res.send(mdContent);
});


module.exports = router;
