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

// P0-3 修复 (ROUND27 12维度核对): async 路由无 try/catch, 任一 reject 触发
// unhandledRejection → gracefulShutdown 整服关闭. asyncHandler 将 reject 转交
// Express error handler (middleware/index.js errorHandler), 仅返回 500 而不下线.
const asyncHandler = (fn) => (req, res, next) =>
  Promise.resolve(fn(req, res, next)).catch(next);

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
  // P4 修复 (Round 29 §11.4): 范围校验 — 限制单次批量删除上限, 防止 DoS.
  // 100 条/次已覆盖正常使用场景 (用户清理历史), 超过返回 400 避免服务阻塞.
  const MAX_BATCH_DELETE = 100;
  if (ids.length > MAX_BATCH_DELETE) {
    return res.status(400).json({
      success: false,
      error: `单次批量删除上限 ${MAX_BATCH_DELETE} 条, 当前 ${ids.length} 条`,
      code: 'BATCH_TOO_LARGE',
    });
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
router.get('/:id/detail', asyncHandler(async (req, res) => {
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
    jobEndedAt: job && job.completedAt ? job.completedAt : null,
  };

  res.json({
    success: true,
    job,
    inputText: inputRes.data,
    result: resultRes.data,
    report: reportRes.data,
    diagnostics,
  });
}));

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
router.get('/:id/export/md', asyncHandler(async (req, res) => {
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

  // P0 修复 (2026-07-29): 当 result.json 已被 TTL 清理或读取失败时,
  // 必须明确告知用户"原始数据不可用", 不能生成全是"未指定/0概念"的虚假报告.
  // 这是用户反馈"粗制滥造"的核心根因之一.
  if (!resultRes.exists || !r || Object.keys(r).length === 0 || (r.treatment == null && r.outcome == null && r.ate == null && (!r.concepts || (Array.isArray(r.concepts) ? r.concepts.length === 0 : true)))) {
    const reason = !resultRes.exists
      ? `result.json 不存在 (任务输出已被 TTL 清理或从未生成)`
      : resultRes.reason
        ? `result.json 读取失败: ${resultRes.reason}`
        : `result.json 为空对象 (任务异常退出, 未写入有效结果)`;
    const ttlHint = (CONFIG && CONFIG.outputTtlMs) ? `TTL=${Math.round(CONFIG.outputTtlMs / 3600000)}h` : 'TTL=?';
    const html = [
      `# 任务 ${id.slice(0, 8)}… 数据不可用`,
      ``,
      `> **状态**: 原始分析结果已过期或损坏, 无法生成论证报告.`,
      `> **原因**: ${reason}`,
      `> **任务元数据**: mode=${job.mode || '?'}, status=${job.status || '?'}, 创建=${job.createdAt ? new Date(job.createdAt).toLocaleString('zh-CN', { hour12: false }) : '?'}, 结束=${job.completedAt ? new Date(job.completedAt).toLocaleString('zh-CN', { hour12: false }) : '?'}`,
      `> **输出 TTL**: ${ttlHint}`,
      ``,
      `## 修复建议`,
      ``,
      `1. **重新运行分析**: 该任务的输出文件已被自动清理, 请重新提交输入文本触发一次新的分析.`,
      `2. **延长 TTL**: 如需长期保留结果, 请在服务端配置中增大 \`outputTtlMs\`.`,
      `3. **检查任务状态**: 如 status 不是 \`completed\`, 说明任务当时异常退出, 需排查日志.`,
      ``,
      `---`,
      `_本提示由 TRACE Engine Web 数据可用性守护生成. 不生成虚假报告是数据可信度的底线._`,
    ].join('\n');
    res.setHeader('Content-Type', 'text/markdown; charset=utf-8');
    res.setHeader('X-Data-Unavailable', 'true');
    return res.send(html);
  }

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
  // ── 论文生成器: 从字段转译升级为论证文章 (P3 修缮 2026-07-29) ──
  // 设计意图: 人话版不是 API 字段的 Markdown 包装, 而是基于数据的多维论证报告.
  // 核心转变:
  //   旧: 字段表格罗列 + "解读"注释 → 粗制滥造的转译
  //   新: 论点驱动叙事 + 多云指数置信度 + 分级结论 → 论文基座

  // ── six_warriors 兼容访问 (dict 或 array) ──
  const _sw = r.six_warriors || {};
  const _getWarrior = (id) => {
    if (Array.isArray(_sw)) return _sw.find(w => w && w.warrior_id === id) || null;
    if (typeof _sw === 'object') {
      const key = id.toLowerCase().replace(/_/g, '');
      for (const k of Object.keys(_sw)) {
        if (k.toLowerCase().replace(/_/g, '') === key) return _sw[k];
      }
    }
    return null;
  };
  const ccmWarrior = _getWarrior('CCM');

  // ── 多维置信度评分 (论文基座的核心) ──
  const scoring = {
    // 维度1: 算法正确性 (基于 CCM 收敛 + 反驳通过率)
    algoCorrectness: (() => {
      let score = 5.0; // 基线
      if (ccmWarrior && ccmWarrior.verdict === 'VERIFIABLE') score += 2.0;
      if (ccmWarrior && ccmWarrior.verdict === 'ELIGIBLE_BUT_NOT_RUN') score += 0.5;
      if (refutations.length > 0) {
        const passRate = robustCount / refutations.length;
        score += passRate * 2.0;
      }
      if (r.n_samples && r.n_samples < 30) score -= 1.5; // 小样本惩罚
      return Math.max(0, Math.min(10, score));
    })(),
    // 维度2: 工程可用性 (基于条件数 + 执行时间)
    engUsability: (() => {
      let score = 7.0;
      const condNum = r.execution_profile?.condition_number ?? r.condition_number;
      if (condNum != null && isFinite(condNum)) {
        const cv = typeof condNum === 'number' ? condNum : parseFloat(condNum);
        if (isFinite(cv)) {
          if (cv > 1e10) score -= 4.0;
          else if (cv > 1e6) score -= 2.0;
          else if (cv > 1e3) score -= 0.5;
        }
      }
      if (job.durationMs > 300000) score -= 1.5; // >5min 惩罚
      if (r.mode && (r.mode.includes('模拟') || r.mode.includes('SEM'))) score -= 2.0;
      return Math.max(0, Math.min(10, score));
    })(),
    // 维度3: 统计严谨性 (基于样本量 + CI + 反驳)
    statRigor: (() => {
      let score = 5.0;
      const n = r.n_samples || 0;
      if (n >= 200) score += 3.0;
      else if (n >= 100) score += 2.0;
      else if (n >= 50) score += 1.0;
      else if (n >= 30) score += 0.3;
      else score -= 1.0;
      if (ci.length === 2 && ate != null) {
        const ciWidth = Math.abs(ci[1] - ci[0]);
        const ateAbs = Math.abs(ate);
        if (ateAbs > 0 && ciWidth / ateAbs < 2) score += 1.5; // CI 相对窄
        else if (ciWidth > ateAbs * 5) score -= 1.5; // CI 过宽
      }
      if (!identifiable) score -= 2.0; // 不可识别严重降级
      return Math.max(0, Math.min(10, score));
    })(),
    // 维度4: 数据管道完整性 (基于概念数 + 边数 + CCM 覆盖)
    dataPipeline: (() => {
      let score = 5.0;
      if (concepts.length >= 10) score += 2.0;
      else if (concepts.length >= 5) score += 1.0;
      else score -= 1.0;
      if (topEdges.length >= 5) score += 1.5;
      else if (topEdges.length === 0) score -= 2.0;
      if (ccmWarrior?.metrics?.CCM_coverage) {
        const cov = parseFloat(ccmWarrior.metrics.CCM_coverage);
        if (!isNaN(cov) && cov > 0.15) score += 1.5;
      }
      return Math.max(0, Math.min(10, score));
    })(),
  };
  const overallScore = (scoring.algoCorrectness + scoring.engUsability + scoring.statRigor + scoring.dataPipeline) / 4;
  const confidenceGrade = overallScore >= 8.0 ? 'A (投资级)'
    : overallScore >= 6.5 ? 'B (可行性验证级)'
    : overallScore >= 4.5 ? 'C (探索性级)'
    : 'D (不可下结论)';

  // ── 论点推导 (Thesis Generation) ──
  const treatment = r.treatment || '(未指定)';
  const outcome = r.outcome || '(未指定)';
  const ateSign = ate != null ? (ate > 0 ? '正向' : ate < 0 ? '负向' : '零') : '未知';
  const ateMag = ate != null ? Math.abs(ate) : 0;
  const effectStrength = ateMag > 0.5 ? '强' : ateMag > 0.1 ? '中等' : ateMag > 0.01 ? '弱' : '微弱';
  const thesis = identifiable
    ? `本研究在 ${mode} 模式下, 基于 ${r.n_samples || '?'} 个样本, 识别出 ${treatment} 对 ${outcome} 存在${ateSign}${effectStrength}因果效应 (ATE=${fmt(ate)}).`
    : `本研究在 ${mode} 模式下检测到 ${treatment} 与 ${outcome} 之间的关联信号 (ATE=${fmt(ate)}), 但因存在未观测混淆, 因果效应不可识别, 该数值仅为关联性而非因果性.`;

  // ── 论文标题 ──
  lines.push(`# ${treatment} → ${outcome}: 因果推断论证报告\n`);
  lines.push(`> **置信度分级**: ${confidenceGrade} (综合评分 ${overallScore.toFixed(2)}/10)`);
  lines.push(`> **生成时间**: ${fmtTs(new Date().toISOString())} | **任务ID**: \`${id}\` | **模式**: ${mode}`);
  if (modeNote) lines.push(`> ${modeNote}`);
  lines.push('');

  // ── 摘要 ──
  lines.push('## 摘要\n');
  lines.push(thesis);
  lines.push('');
  lines.push(`多维度置信度评估显示: 算法正确性 ${scoring.algoCorrectness.toFixed(1)}/10, 工程可用性 ${scoring.engUsability.toFixed(1)}/10, 统计严谨性 ${scoring.statRigor.toFixed(1)}/10, 数据管道完整性 ${scoring.dataPipeline.toFixed(1)}/10. 综合评定为 **${confidenceGrade}**.\n`);
  if (ccmWarrior) {
    lines.push(`六战士诊断中, CCM 判定为 \`${ccmWarrior.verdict || 'N/A'}\`, ` +
      (ccmWarrior.metrics?.ccm_rho ? `交叉映射 ρ=${ccmWarrior.metrics.ccm_rho} (方向: ${ccmWarrior.metrics.ccm_direction || 'N/A'}, E=${ccmWarrior.metrics.ccm_E || 'N/A'}).` : '未运行交叉映射.'));
    lines.push('');
  }

  // ── 1. 研究问题 ──
  lines.push('## 1. 研究问题与因果假设\n');
  lines.push(`**因果问题**: 干预 ${treatment} 是否会因果地改变 ${outcome} 的取值?\n`);
  lines.push(`**研究语境**: 基于 ${concepts.length} 个概念词汇的分析, 输入文本经 TRACE 引擎提取因果图, ` +
    `识别出 ${topEdges.length} 条显著因果边, 概念图谱密度反映文本的因果结构复杂度.\n`);
  if (inputText) {
    const preview = inputText.slice(0, 300) + (inputText.length > 300 ? '...' : '');
    lines.push(`**输入文本摘要**: ${preview.replace(/\n/g, ' ')}\n`);
  }

  // ── 2. 方法论 ──
  lines.push('## 2. 方法论\n');
  lines.push(`**分析模式**: ${mode} — ` +
    (mode === 'LIGHT' ? '快速简化流程, 跳过 DoWhy 反驳和 CCM 真算法.'
    : mode === 'DEEP' ? '完整六战士分析, 包含稳定性检查和 DoWhy 反驳.'
    : mode === 'SUPER' ? '使用 LLaMA 模型进行 TRACE 提取, 最深度分析.'
    : '未知模式.'));
  lines.push(`**算法栈**: TRACE (ΔNLL 掩码干预) → DoWhy (Pearl 三步反事实) → CCM (收敛交叉映射) → HAVOK (Hankel SVD) → causallearn (PC/GES)\n`);
  lines.push(`**样本量**: ${r.n_samples || 'N/A'} ${r.n_samples == null ? '⚠️ 未记录' : r.n_samples < 30 ? '⚠️ 小样本 (n<30), 假阳性风险显著' : r.n_samples < 100 ? '⚠ 中等样本, 方向判定需谨慎' : '✓ 样本量充足'}\n`);

  // ── 3. 核心发现 ──
  lines.push('## 3. 核心发现\n');
  lines.push('### 3.1 因果效应估计\n');
  lines.push(`**ATE (平均因果效应)**: ${fmt(ate)} (${ateSign}${effectStrength}效应)\n`);
  if (ci.length === 2) {
    const ciWidth = Math.abs(ci[1] - ci[0]);
    const ciContainsZero = (ci[0] < 0 && ci[1] > 0) || (ci[0] > 0 && ci[1] < 0);
    lines.push(`**95% 置信区间**: [${fmt(ci[0])}, ${fmt(ci[1])}] (宽度 ${ciWidth.toFixed(4)})`);
    lines.push(ciContainsZero ? '> ⚠️ 置信区间包含 0, 因果效应不显著.\n' : '> ✓ 置信区间不包含 0, 因果效应统计显著.\n');
  }
  lines.push(`**可识别性**: ${identifiable ? '✓ 可识别 — 可基于观测数据无偏估计 ATE' : '✗ 不可识别 — 存在未观测混淆, ATE 估计有偏'}\n`);
  const condNum = r.execution_profile?.condition_number ?? r.condition_number;
  if (condNum != null && isFinite(condNum)) {
    const cv = typeof condNum === 'number' ? condNum : parseFloat(condNum);
    if (isFinite(cv)) {
      const condStr = cv.toExponential(2);
      if (cv > 1e10) {
        lines.push(`**设计矩阵条件数**: ${condStr} ⚠️ **严重病态** — OLS 估计方差无穷大, CI 不可信, ATE 数值不可靠.\n`);
      } else if (cv > 1e6) {
        lines.push(`**设计矩阵条件数**: ${condStr} ⚠️ 接近病态, CI 应谨慎解读.\n`);
      } else {
        lines.push(`**设计矩阵条件数**: ${condStr} ✓ 良好.\n`);
      }
    }
  }

  lines.push('### 3.2 因果结构发现\n');
  if (topEdges.length > 0) {
    lines.push(`识别出 ${topEdges.length} 条显著因果边 (展示前 10):\n`);
    lines.push('| 排名 | 源 → 目标 | 强度 (ΔNLL) | 方向 |');
    lines.push('|------|-----------|-------------|------|');
    topEdges.slice(0, 10).forEach((e, i) => {
      lines.push(`| ${i + 1} | \`${e.source}\` → \`${e.target}\` | ${fmt(e.strength, 3)} | ${e.direction || '→'} |`);
    });
    lines.push('');
    // 因果结构叙事
    const strongest = topEdges[0];
    lines.push(`> **结构洞察**: 最强因果边为 \`${strongest.source}\` → \`${strongest.target}\` (ΔNLL=${fmt(strongest.strength, 3)}), ` +
      `表明在当前文本语境中, "${strongest.source}" 概念的出现对 "${strongest.target}" 概念的预测信息量贡献最大.\n`);
  } else {
    lines.push('未识别出显著因果边. 这可能表明: (1) 输入文本缺乏明确因果结构; (2) 概念频次不足; (3) 阈值设置过高.\n');
  }

  lines.push('### 3.3 稳健性验证\n');
  if (refutations.length > 0) {
    lines.push(`反驳测试 ${robustCount}/${refutations.length} 项稳健, ${refutedCount} 项被反驳:\n`);
    lines.push('| 方法 | 原 ATE | 新 ATE | 偏差 | 判定 |');
    lines.push('|------|--------|--------|------|------|');
    refutations.forEach(ref => {
      const verdict = ref.refuted ? '✗ 被反驳' : '✓ 稳健';
      lines.push(`| ${ref.method || '?'} | ${fmt(ate)} | ${fmt(ref.new_effect)} | ${fmt(ref.display_metric, 3)} | ${verdict} |`);
    });
    lines.push('');
    const passRate = robustCount / refutations.length;
    lines.push(`> **稳健性评估**: 通过率 ${(passRate * 100).toFixed(0)}%. ` +
      (passRate >= 0.8 ? '✓ 结论可信度高.' : passRate >= 0.5 ? '⚠ 结论中等可信, 部分反驳提示 ATE 可能存在偏倚.' : '✗ 结论可信度低, 多项反驳表明 ATE 可能是统计假象.') + '\n');
  } else {
    lines.push('未运行反驳测试 (LIGHT 模式或样本量不足). 稳健性无法评估.\n');
  }

  if (cfScan.length > 0) {
    lines.push('### 3.4 反事实扫描\n');
    lines.push(`对 ${cfScan.length} 条因果边执行反事实干预 (展示前 5):\n`);
    lines.push('| 边 | ΔNLL | ITE | 观测值 | 反事实值 |');
    lines.push('|----|------|-----|--------|----------|');
    cfScan.slice(0, 5).forEach(c => {
      lines.push(`| \`${c.source}\`→\`${c.target}\` | ${fmt(c.trace_dnl, 3)} | ${fmt(c.ite, 2)} | ${fmt(c.observed, 1)} | ${fmt(c.counterfactual, 1)} |`);
    });
    lines.push('');
  }

  // ── 4. 多维置信度评估 ──
  lines.push('## 4. 多维置信度评估\n');
  lines.push('| 维度 | 评分 | 评级 | 关键依据 |');
  lines.push('|------|------|------|----------|');
  const gradeStr = (s) => s >= 8 ? 'A' : s >= 6.5 ? 'B' : s >= 4.5 ? 'C' : 'D';
  lines.push(`| 算法正确性 | ${scoring.algoCorrectness.toFixed(1)}/10 | ${gradeStr(scoring.algoCorrectness)} | ${ccmWarrior?.verdict === 'VERIFIABLE' ? 'CCM 收敛验证通过' : 'CCM 未验证'} + 反驳通过率 ${refutations.length > 0 ? `${Math.round(robustCount / refutations.length * 100)}%` : 'N/A'} |`);
  lines.push(`| 工程可用性 | ${scoring.engUsability.toFixed(1)}/10 | ${gradeStr(scoring.engUsability)} | 条件数 ${condNum != null && isFinite(condNum) ? '(' + (typeof condNum === 'number' ? condNum : parseFloat(condNum)).toExponential(1) + ')' : 'N/A'} + 耗时 ${(job.durationMs / 1000).toFixed(1)}s |`);
  lines.push(`| 统计严谨性 | ${scoring.statRigor.toFixed(1)}/10 | ${gradeStr(scoring.statRigor)} | n=${r.n_samples || '?'} + ${identifiable ? '可识别' : '不可识别'} + CI宽度 ${ci.length === 2 ? Math.abs(ci[1] - ci[0]).toFixed(3) : 'N/A'} |`);
  lines.push(`| 数据管道完整性 | ${scoring.dataPipeline.toFixed(1)}/10 | ${gradeStr(scoring.dataPipeline)} | ${concepts.length} 概念 + ${topEdges.length} 边 + CCM覆盖 ${ccmWarrior?.metrics?.CCM_coverage || 'N/A'} |`);
  lines.push(`| **综合** | **${overallScore.toFixed(2)}/10** | **${confidenceGrade}** | — |\n`);

  // ── 5. 局限性声明 ──
  lines.push('## 5. 局限性声明\n');
  const limitations = [];
  if (r.n_samples && r.n_samples < 30) {
    limitations.push(`**小样本风险**: n=${r.n_samples} < 30, CCM 假阳性率可达 10-40% (基于负控制实验基线), 方向判定不可靠. 建议标注"小样本假阳性风险".`);
  }
  if (r.n_samples && r.n_samples < 100 && r.n_samples >= 30) {
    limitations.push(`**中等样本**: n=${r.n_samples}, CCM 方向判定需谨慎, 建议仅报告"检测到因果耦合"而非方向.`);
  }
  if (!identifiable) {
    limitations.push('**不可识别性**: 存在未观测混淆路径, ATE 估计有偏, 数值仅为关联性而非因果性.');
  }
  if (condNum != null && isFinite(condNum)) {
    const cv = typeof condNum === 'number' ? condNum : parseFloat(condNum);
    if (isFinite(cv) && cv > 1e6) {
      limitations.push(`**设计矩阵病态**: 条件数 ${cv.toExponential(2)} > 1e6, OLS 估计方差膨胀, CI 不可信.`);
    }
  }
  if (r.mode && (r.mode.includes('模拟') || r.mode.includes('SEM'))) {
    limitations.push('**SEM 模拟模式**: 本次分析使用结构方程模型生成合成数据, ATE 为模拟估计, 不可识别, 仅用于算法管道完整性验证.');
  }
  if (mode === 'LIGHT') {
    limitations.push('**LIGHT 模式限制**: 跳过 DoWhy 反驳和 CCM 真算法, 稳健性和方向验证缺失.');
  }
  if (mode === 'SUPER') {
    limitations.push('**SUPER 模式声明**: 相关结论基于 LLaMA 模型推理, 未做运行时验证 (L1 代码阅读层级).');
  }
  limitations.push('**共同驱动不可区分**: CCM 无法区分真实因果与共同驱动 (Z→X, Z→Y), 这是 Sugihara 原论文已承认的根本不可识别性限制.');
  if (limitations.length > 0) {
    limitations.forEach(l => lines.push(`- ${l}`));
    lines.push('');
  }

  // ── 6. 分级结论 ──
  lines.push('## 6. 结论\n');
  let conclusionStrength;
  if (overallScore >= 8.0) {
    conclusionStrength = '**强结论** (投资级置信度)';
  } else if (overallScore >= 6.5) {
    conclusionStrength = '**中等结论** (可行性验证级)';
  } else if (overallScore >= 4.5) {
    conclusionStrength = '**弱结论** (探索性级)';
  } else {
    conclusionStrength = '**不可下结论** (证据不足)';
  }
  lines.push(`### ${conclusionStrength}\n`);
  lines.push(`基于 ${r.n_samples || '?'} 个样本的 ${mode} 模式分析, ` +
    `${identifiable ? `可以` : '不能'}从观测数据中无偏估计 ${treatment} 对 ${outcome} 的因果效应. ` +
    `ATE=${fmt(ate)} ${ci.length === 2 ? `(95% CI: [${fmt(ci[0])}, ${fmt(ci[1])}])` : ''}, ` +
    `综合置信度 ${overallScore.toFixed(2)}/10 (${confidenceGrade}).\n`);
  lines.push(`> **数据基座**: 本结论由 ${concepts.length} 概念 / ${topEdges.length} 因果边 / ${refutations.length} 反驳测试 / ${cfScan.length} 反事实扫描 / 六战士诊断 共同支撑, ` +
    `并非单一指标判定, 而是多云指数标签的参数化论证基座.\n`);

  // ── 附录 ──
  lines.push('---\n');
  lines.push('## 附录 A: 概念词汇 (Top 15)\n');
  if (concepts.length > 0) {
    lines.push('| 概念 | 频次 | CCM 可用 |');
    lines.push('|------|------|----------|');
    concepts.slice(0, 15).forEach(c => {
      const freq = conceptFreq[c] ?? 0;
      const eligible = ccmEligible.includes(c) ? '✓' : '—';
      lines.push(`| \`${c}\` | ${freq} | ${eligible} |`);
    });
    lines.push('');
  }

  lines.push('## 附录 B: 执行画像\n');
  if (execProfile && Object.keys(execProfile).length > 0) {
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

  if (inputText) {
    lines.push('## 附录 C: 输入文本\n');
    lines.push('```text');
    lines.push(inputText.slice(0, 2000) + (inputText.length > 2000 ? '\n... (已截断)' : ''));
    lines.push('```\n');
  }

  // 原 report.md 附在末尾
  if (reportMd) {
    lines.push('## 附录 D: 原始 report.md\n');
    lines.push(reportMd);
    lines.push('');
  }

  lines.push('---');
  lines.push(`_本论证报告由 TRACE Engine Web 论文生成器自动生成于 ${fmtTs(new Date().toISOString())}. ` +
    `基于多维置信度评分模型, 非简单字段转译. 报告遵循"分级结论 + 局限披露"原则._`);

  const mdContent = lines.join('\n');

  // P1 fix (Round 25 §2): 人话版报告落盘到任务输出目录, 方便文件系统查阅.
  // 用户要求: "应当等同于我们的日志在项目的文件夹中，进行生成"
  try {
    const humanReportPath = path.join(OUTPUT_DIR, id, 'human_report.md');
    await fs.promises.writeFile(humanReportPath, mdContent, 'utf-8');
  } catch (e) {
    // 落盘失败不影响浏览器展示
  }

  // P2 fix (Round 24 §10): 改为直接展示 (text/markdown), 不触发浏览器下载.
  res.setHeader('Content-Type', 'text/markdown; charset=utf-8');
  res.send(mdContent);
}));


module.exports = router;
