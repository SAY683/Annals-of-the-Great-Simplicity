const fs = require('fs');
const path = require('path');
const { PROJECTS_DIR, TRAJECTORY_CSV } = require('../config');
const { activeJobs, jobHistory } = require('./job-service');

function getActiveTrajectoryCSV() {
  try {
    const indexPath = path.join(PROJECTS_DIR, '_index.json');
    if (fs.existsSync(indexPath)) {
      const idx = JSON.parse(fs.readFileSync(indexPath, 'utf-8'));
      const active = idx.active || 'default';
      return path.join(PROJECTS_DIR, active, 'narrative_meta_trajectories.csv');
    }
  } catch (e) { /* fall through */ }
  return TRAJECTORY_CSV;
}



function readTrajectoryCSV() {
  try {
    const csvPath = getActiveTrajectoryCSV();
    if (!fs.existsSync(csvPath)) return { columns: [], rows: [], total: 0 };

    // 使用简单的 CSV 解析 (处理引号内的逗号)
    const content = fs.readFileSync(csvPath, 'utf-8');
    // ENG-10 修复: 用 /\r?\n/ 分割以兼容 Windows(\r\n) 与 Unix(\n) 行尾
    // 原实现 content.trim().split('\n') 在 Windows CSV 下会保留每行末尾的 \r,
    // 导致最后一列 (d2z_觉爱_zscore) 实际变为 "d2z_觉爱_zscore\r",
    // colLayer 的 endsWith('_zscore') 匹配失败，字段被误分类为 (其他)。
    const lines = content.trim().split(/\r?\n/);
    if (lines.length < 2) return { columns: [], rows: [], total: 0 };

    const parseCSVLine = (line) => {
      const result = [];
      let current = '', inQuotes = false;
      // ENG-10 防御: 兜底剥离行尾 \r (Windows 行尾残留)
      const sanitized = line.replace(/\r$/, '');
      for (const ch of sanitized) {
        if (ch === '"') { inQuotes = !inQuotes; continue; }
        if (ch === ',' && !inQuotes) { result.push(current); current = ''; continue; }
        current += ch;
      }
      result.push(current);
      return result;
    };

    const columns = parseCSVLine(lines[0]);
    const rows = lines.slice(1).map(line => {
      const vals = parseCSVLine(line);
      const obj = {};
      columns.forEach((col, i) => { obj[col] = (vals[i] || '').replace(/^"|"$/g, ''); });
      return obj;
    });
    return { columns, rows, total: rows.length, path: csvPath };
  } catch (e) {
    return { columns: [], rows: [], total: 0, error: e.message };
  }
}

// ── P2 (§20.12): 生成人话版 Markdown 报告 ─────────────────
// 抽离为独立函数, 供 /api/trajectory/export/md 与 /api/trajectory/report 复用,
// 保证浏览器查看报告时总是拿到最新数据, 避免 stale latest.md.
function buildTrajectoryReport() {
  const traj = readTrajectoryCSV();
  const active = Array.from(activeJobs.entries()).map(([id, j]) => ({
    id, mode: j.mode, status: j.status, startTime: j.startTime,
  }));
  const history = jobHistory.slice(0, 20);

  // 当前项目名
  let projectName = 'default';
  try {
    const idxPath = path.join(PROJECTS_DIR, '_index.json');
    if (fs.existsSync(idxPath)) {
      const idx = JSON.parse(fs.readFileSync(idxPath, 'utf-8'));
      projectName = idx.active || 'default';
    }
  } catch (_) { /* ignore */ }

  const edmReady = traj.total >= 15;
  const fmtTs = (iso) => {
    if (!iso) return 'N/A';
    try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }); } catch (_) { return String(iso); }
  };

  // 列分层映射: 为全部 89 列提供层级, 不再出现 '(其他)'
  const colLayer = {
    time_step: 'L0 元信息', text_hash: 'L0 元信息', source_label: 'L0 元信息',
    trace_status: 'L0 元信息', trace_mode: 'L0 元信息', trace_error: 'L0 元信息',
    ate: 'L1 元SCM', adj_density: 'L1 元SCM', max_delta_nll: 'L1 元SCM',
    ci_width: 'L1 元SCM', edge_count: 'L1 元SCM', refuted_count: 'L1 元SCM',
    ccm_coverage_pct: 'L1 元SCM',
    ate_ci_lower: 'L1 元SCM', ate_ci_upper: 'L1 元SCM',
    identifiable: 'L1 元SCM', concept_count: 'L1 元SCM',
    signal_type: 'L1 元SCM', max_delta_nll_concept_level: 'L1 元SCM',
    concept_level_edge_count: 'L1 元SCM', concept_coverage: 'L1 元SCM',
    condition_number: 'L1 元SCM', unk_rate: 'L1 元SCM',
    ccm_verdict: 'L1 元SCM', refutations_attempted: 'L1 元SCM',
    ccm_algorithm_run: 'L1 元SCM',
    edm_rho_high: 'L2 EDM', edm_rho_mid: 'L2 EDM',
    havok_status: 'L2 HAVOK', havok_linear_pct: 'L2 HAVOK',
    causallearn_consensus: 'L2 因果学习', edge_stability_mean: 'L2 稳定性',
    permutation_p_value: 'L2 稳定性', total_ms: 'L0 元信息',
    consensus_score: 'L2 共识', consensus_direction: 'L2 共识',
    z_pca_1: 'L2 PCA', z_pca_2: 'L2 PCA', z_pca_3: 'L2 PCA', secular_entropy: 'L2 PCA',
    z_福音: 'L3 八正道', z_吉祥: 'L3 八正道', z_奥美: 'L3 八正道', z_存在: 'L3 八正道',
    z_自孕: 'L3 八正道', z_弥赛亚: 'L3 八正道', z_Alice: 'L3 八正道', z_觉爱: 'L3 八正道',
    dz_福音: 'L3 一阶差分', dz_吉祥: 'L3 一阶差分', dz_奥美: 'L3 一阶差分',
    dz_存在: 'L3 一阶差分', dz_自孕: 'L3 一阶差分', dz_弥赛亚: 'L3 一阶差分',
    dz_Alice: 'L3 一阶差分', dz_觉爱: 'L3 一阶差分',
    d2z_福音: 'L3 二阶差分', d2z_吉祥: 'L3 二阶差分', d2z_奥美: 'L3 二阶差分',
    d2z_存在: 'L3 二阶差分', d2z_自孕: 'L3 二阶差分', d2z_弥赛亚: 'L3 二阶差分',
    d2z_Alice: 'L3 二阶差分', d2z_觉爱: 'L3 二阶差分',
  };
  // 辅助: 为 zscore 列批量生成层级
  const allColumns = traj.columns || [];
  allColumns.forEach(col => {
    if (col.endsWith('_zscore') && !colLayer[col]) colLayer[col] = 'L3 标准化';
  });

  // 列含义: 为全部 89 列提供人话解释
  const colDesc = {
    time_step: '原始时间戳 — 轨迹行对应的文本事件时间',
    text_hash: '文本哈希 — 输入文本的短指纹, 用于去重与追踪',
    source_label: '来源标签 — 新闻/文本来源标识',
    trace_status: '轨迹状态 — OK/ERROR 表示该条文本是否成功完成因果推断',
    trace_mode: '分析模式 — light/deep/super, 决定计算深度',
    trace_error: '错误信息 — 若处理失败, 记录失败原因',
    ate: '因果效应强度 — ATE 数值, 反映处理→结果的因果关联大小; 负值 = 抑制, 零 = 无线性因果',
    adj_density: '因果图密度 — 系统纠缠度, 越高概念间因果链越密',
    max_delta_nll: '最强因果信号 — ΔNLL 最大值; 值越大非线性因果信号越强',
    ci_width: '因果不确定性 — 置信区间宽度, CI 越宽噪音越大',
    edge_count: '显著因果边数 — 通过统计显著性检验的边',
    refuted_count: '反驳测试被反驳数 — 0 在 light 模式为正常(未运行反驳)',
    ccm_coverage_pct: 'CCM 非线性验证覆盖率 — light 模式为 0(未运行 CCM)',
    ate_ci_lower: 'ATE 置信区间下限 — 因果效应的保守估计',
    ate_ci_upper: 'ATE 置信区间上限 — 因果效应的乐观估计',
    identifiable: '因果效应可识别性 — 1 表示估计量可被识别, 0 表示不可识别',
    concept_count: '识别出的概念数 — 文本中提取的语义概念数量',
    signal_type: '信号类型 — 当前最强因果信号的来源标记',
    max_delta_nll_concept_level: '概念级最强 ΔNLL — 概念粒度下的最强非线性信号',
    concept_level_edge_count: '概念级显著边数 — 概念聚合后的显著因果边',
    concept_coverage: '概念覆盖率 — 文本中被概念词典覆盖的比例',
    condition_number: '设计矩阵条件数 — 数值越大共线性越严重, 估计越不稳定',
    unk_rate: '未知词比例 — 文本中未识别词汇的占比',
    ccm_verdict: 'CCM 裁决 — 非线性验证的定性结论',
    refutations_attempted: '尝试的反驳测试数 — 0 表示 light 模式未运行',
    ccm_algorithm_run: 'CCM 算法是否执行 — 1 表示运行, 0 表示未运行',
    edm_rho_high: 'EDM 高嵌入维 ρ — 高维下的预测相关系数',
    edm_rho_mid: 'EDM 中嵌入维 ρ — 中等维度的预测相关系数',
    havok_status: 'HAVOK 分析状态 — 线性动力学分解是否成功',
    havok_linear_pct: 'HAVOK 线性占比 — 系统动力学中可线性解释的比例',
    causallearn_consensus: 'CausalLearn 共识 — 多种算法对因果方向的一致性投票',
    edge_stability_mean: '因果边稳定性均值 — 自助法下边强度的稳定程度',
    permutation_p_value: '置换检验 p 值 — 因果结构的统计显著性',
    total_ms: '总耗时(毫秒) — 该条文本的处理时间',
    consensus_score: '因果方向共识分 — 方向一致性的定量分数',
    consensus_direction: '共识方向 — positive/negative/ambiguous',
    z_pca_1: '世俗 PCA 第 1 主轴 — 经济/物质维度投影',
    z_pca_2: '世俗 PCA 第 2 主轴 — 社会/权力维度投影',
    z_pca_3: '世俗 PCA 第 3 主轴 — 技术/工具维度投影',
    secular_entropy: '世俗熵 — 话语多样性, 越高词汇/主题越分散',
    z_福音: '福音 (祂志书) 投影 — 信仰维度',
    z_吉祥: '吉祥 (赐福书) 投影 — 祝福维度',
    z_奥美: '奥美 (圣源书) 投影 — 美学维度',
    z_存在: '存在 (真实书) 投影 — 本体论距离, 越大越"超验"',
    z_自孕: '自孕 (胜育书) 投影 — 生命维度',
    z_弥赛亚: '弥赛亚 (至意书) 投影 — 救赎维度',
    z_Alice: 'Alice (慧辩书) 投影 — 逻辑维度',
    z_觉爱: '觉爱 (智识书) 投影 — 智慧维度',
    dz_福音: '福音轴一阶差分 Δz/Δt — 首行为空(因差分需至少2个点)',
    dz_吉祥: '吉祥轴一阶差分 Δz/Δt — 突变速率; 正 = 上升, 负 = 下降',
    dz_奥美: '奥美轴一阶差分 Δz/Δt',
    dz_存在: '存在轴一阶差分 Δz/Δt — 突变速率; 正 = 上升, 负 = 下降',
    dz_自孕: '自孕轴一阶差分 Δz/Δt',
    dz_弥赛亚: '弥赛亚轴一阶差分 Δz/Δt',
    dz_Alice: 'Alice轴一阶差分 Δz/Δt',
    dz_觉爱: '觉爱轴一阶差分 Δz/Δt — 智慧突变速率',
    d2z_福音: '福音轴二阶差分 Δ²z/Δt² — 首两行空(二阶差分需至少3个点)',
    d2z_吉祥: '吉祥轴二阶差分 Δ²z/Δt² — 加速度; 正 = 加速上升, 负 = 减速/转向',
    d2z_奥美: '奥美轴二阶差分 Δ²z/Δt²',
    d2z_存在: '存在轴二阶差分 Δ²z/Δt²',
    d2z_自孕: '自孕轴二阶差分 Δ²z/Δt²',
    d2z_弥赛亚: '弥赛亚轴二阶差分 Δ²z/Δt²',
    d2z_Alice: 'Alice轴二阶差分 Δ²z/Δt²',
    d2z_觉爱: '觉爱轴二阶差分 Δ²z/Δt²',
  };
  // 辅助: 为 zscore 列批量生成含义
  allColumns.forEach(col => {
    if (col.endsWith('_zscore') && !colDesc[col]) {
      const base = col.slice(0, -7);
      colDesc[col] = `${base} 的标准分数 — 该时刻值偏离其历史均值的标准差倍数`;
    }
  });

  const lines = [];
  lines.push(`# TRACE-TO-EDM 桥接报告: 项目 \`${projectName}\`\n`);
  lines.push(`> 自动生成 — 面向非技术读者的人话版解读. 报告基于轨迹 CSV + 任务历史.\n`);
  lines.push('');

  // 1. 概览
  lines.push('## 1. 概览\n');
  lines.push(`- **当前项目**: \`${projectName}\``);
  lines.push(`- **轨迹文件**: \`${traj.path || 'N/A'}\``);
  lines.push(`- **轨迹行数**: ${traj.total}`);
  lines.push(`- **轨迹列数**: ${traj.columns.length}`);
  lines.push(`- **EDM 就绪**: ${edmReady ? '✓ 是 (≥15 行, 可触发 EDM 分析)' : '✗ 否 (<15 行, 需更多数据)'}`);
  lines.push(`- **生成时间**: ${fmtTs(new Date().toISOString())}`);
  lines.push(`- **活动任务**: ${active.length}`);
  lines.push(`- **历史任务**: ${history.length} 条 (最近)`);
  lines.push('');

  // 2. 关键指标统计
  const numericStats = {};
  if (traj.rows.length > 0) {
    traj.columns.forEach(col => {
      const vals = traj.rows.map(r => parseFloat(r[col])).filter(v => !isNaN(v));
      if (vals.length === 0) return;
      const min = Math.min(...vals);
      const max = Math.max(...vals);
      const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
      const half = Math.floor(vals.length / 2);
      const firstHalf = vals.slice(0, half).reduce((a, b) => a + b, 0) / Math.max(half, 1);
      const secondHalf = vals.slice(half).reduce((a, b) => a + b, 0) / Math.max(vals.length - half, 1);
      const delta = secondHalf - firstHalf;
      const trend = Math.abs(delta) < Math.abs(mean) * 0.05
        ? '→ 平稳'
        : (delta > 0 ? '↗ 上升' : '↘ 下降');
      numericStats[col] = { min, max, mean, trend };
    });
  }

  lines.push('## 2. 指标详解 + 统计 + 趋势\n');
  if (traj.columns.length > 0) {
    lines.push('| 列名 | 层级 | 含义 | 最小 | 最大 | 均值 | 趋势 |');
    lines.push('|------|------|------|------|------|------|------|');
    const fmt = (v) => (Math.abs(v) >= 1000 ? v.toFixed(1) : v.toFixed(3));
    traj.columns.forEach(col => {
      const layer = colLayer[col] || '(其他)';
      const desc = colDesc[col] || '—';
      const st = numericStats[col];
      if (st) {
        lines.push(`| \`${col}\` | ${layer} | ${desc} | ${fmt(st.min)} | ${fmt(st.max)} | ${fmt(st.mean)} | ${st.trend} |`);
      } else {
        lines.push(`| \`${col}\` | ${layer} | ${desc} | — | — | — | — |`);
      }
    });
    lines.push('');
    lines.push('> **解读**: 趋势 = 后半段均值 vs 前半段均值. '
      + '↗/↘ 幅度 > 5% 均值才算"上升/下降", 否则视为"平稳". '
      + '空值 — 表示该列无非数值内容(如 trace_error).\n');
  } else {
    lines.push('- 轨迹文件为空或不存在.\n');
  }

  // 3. 数学正确性说明: 解释零值与负数
  lines.push('## 3. 关于零值与负数的数学说明\n');
  lines.push('- **ATE 为 0**: 在 LIGHT 模式下, 若文本过短或无可识别因果结构, OLS 估计会退化为 0. 这不代表算法错误, 而是"无显著线性因果"的统计结果.');
  lines.push('- **ATE 为负**: 表示"处理变量增加 → 结果变量减少"的抑制关系, 是因果效应的正常取值范围.');
  lines.push('- **refuted_count = 0**: LIGHT 模式不运行反驳测试, 故恒为 0; DEEP/SUPER 模式才会产生非零值.');
  lines.push('- **ccm_coverage_pct = 0**: LIGHT 模式不运行 CCM 非线性验证, 故恒为 0.');
  lines.push('- **dz_/d2z_ 首行空**: 一阶差分需要至少 2 个连续点, 二阶差分需要至少 3 个连续点, 因此首行/首两行无定义(显示为 —).');
  lines.push('- **z_pca / z_八正道 为负**: 投影以均值为 0 进行标准化, 负值表示"低于该维度的平均水平", 完全正常.');
  lines.push('- **zscore 为负/正**: 标准分数, 0 为均值, ±1 为一个标准差, 负值表示低于历史均值.');
  lines.push('');

  // 4. 轨迹数据预览
  lines.push('## 4. 轨迹数据预览 (Top 15)\n');
  if (traj.rows.length > 0) {
    const previewCols = traj.columns.slice(0, 8);  // 限制前 8 列
    lines.push('| # | ' + previewCols.map(c => `\`${c}\``).join(' | ') + ' |');
    lines.push('|---|' + previewCols.map(() => '------').join('|') + '|');
    traj.rows.slice(0, 15).forEach((row, i) => {
      const vals = previewCols.map(c => {
        const v = row[c] || '';
        const num = parseFloat(v);
        if (!isNaN(num) && v !== '') {
          return Math.abs(num) >= 1000 ? num.toFixed(1) : num.toFixed(3);
        }
        return String(v).slice(0, 20);
      });
      lines.push(`| ${i + 1} | ${vals.join(' | ')} |`);
    });
    if (traj.rows.length > 15) {
      lines.push('');
      lines.push(`_...共 ${traj.total} 行, 此处仅展示前 15 行._`);
    }
    lines.push('');
  } else {
    lines.push('- 轨迹为空.\n');
  }

  // 5. 任务历史
  lines.push('## 5. 任务历史 (最近 20 条)\n');
  if (history.length > 0) {
    lines.push('| # | 任务 ID | 模式 | 状态 | 开始时间 |');
    lines.push('|---|---------|------|------|----------|');
    history.forEach((j, i) => {
      const status = j.status === 'completed' ? '✓ 完成' : (j.status === 'failed' ? '✗ 失败' : j.status);
      lines.push(`| ${i + 1} | \`${j.id}\` | ${j.mode || '?'} | ${status} | ${fmtTs(j.startTime)} |`);
    });
    lines.push('');
  } else {
    lines.push('- 无任务历史.\n');
  }

  // 6. 总结
  lines.push('## 6. 一句话总结\n');
  const parts = [];
  if (traj.total > 0) parts.push(`已采集 ${traj.total} 条轨迹`);
  if (edmReady) parts.push('EDM 可触发');
  else parts.push(`需 ${Math.max(0, 15 - traj.total)} 条更多数据才能触发 EDM`);
  if (history.length > 0) {
    const completed = history.filter(j => j.status === 'completed').length;
    parts.push(`历史任务 ${completed}/${history.length} 完成`);
  }
  lines.push('**' + parts.join('; ') + '.**');
  lines.push('');
  lines.push('---');
  lines.push(`_报告由 trace-to-edm Web 自动生成于 ${fmtTs(new Date().toISOString())}._`);

  const mdContent = lines.join('\n');

  // 写入项目 reports/ 目录, 方便用户在文件系统中直接查阅
  const reportsDir = path.join(PROJECTS_DIR, projectName, 'reports');
  fs.mkdirSync(reportsDir, { recursive: true });
  fs.writeFileSync(path.join(reportsDir, 'latest.md'), mdContent, 'utf-8');

  return {
    mdContent,
    htmlContent: null, // 由 buildTrajectoryReportHTML() 按需生成
    projectName,
    generated: new Date().toISOString(),
    traj,
    numericStats,
    colLayer,
    colDesc,
    edmReady,
    active,
    history,
  };
}

// ── P2 (§20.12): 生成人话版 HTML 报告 ─────────────────────
// 暗色主题、可折叠卡片、按层级分组，减少 89 列大表的压迫感。
function buildTrajectoryReportHTML(baseReport) {
  const {
    projectName, generated, traj, numericStats, colLayer, colDesc, edmReady, active, history,
  } = baseReport;
  const fmtTs = (iso) => {
    if (!iso) return 'N/A';
    try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }); } catch (_) { return String(iso); }
  };
  const fmt = (v) => {
    if (v === undefined || v === null || Number.isNaN(v)) return '—';
    return Math.abs(v) >= 1000 ? v.toFixed(1) : v.toFixed(3);
  };

  // 按层级分组列
  const layers = {};
  traj.columns.forEach((col) => {
    const layer = colLayer[col] || '其他';
    if (!layers[layer]) layers[layer] = [];
    layers[layer].push(col);
  });
  const layerOrder = [
    'L0 元信息',
    'L1 元SCM',
    'L2 EDM',
    'L2 HAVOK',
    'L2 因果学习',
    'L2 稳定性',
    'L2 共识',
    'L2 PCA',
    'L3 八正道',
    'L3 一阶差分',
    'L3 二阶差分',
    'L3 标准化',
    '其他',
  ];

  // 内联数学/语义说明
  function inlineNote(col, st) {
    const notes = [];
    if (col === 'ate' && st) {
      if (Math.abs(st.mean) < 0.001) notes.push('均值接近 0：可能为 LIGHT 模式无线性因果或文本过短。');
      if (st.min < 0) notes.push('负值 = 抑制关系，属正常取值范围。');
    }
    if (col === 'refuted_count' || col === 'refutations_attempted') {
      notes.push('LIGHT 模式不运行反驳测试，0 为正常。');
    }
    if (col === 'ccm_coverage_pct' || col === 'ccm_algorithm_run') {
      notes.push('LIGHT 模式不运行 CCM 非线性验证，0 为正常。');
    }
    if (col.startsWith('dz_')) {
      notes.push('首行空：一阶差分需至少 2 个连续点。');
    }
    if (col.startsWith('d2z_')) {
      notes.push('首两行空：二阶差分需至少 3 个连续点。');
    }
    if ((col.startsWith('z_pca_') || col.startsWith('z_') || col.endsWith('_zscore')) && st && st.min < 0) {
      notes.push('负值表示低于该维度历史/平均水平，完全正常。');
    }
    if (!notes.length) return '';
    return `<span class="metric-note">${notes.join(' ')}</span>`;
  }

  function renderLayerCard(layerName, cols) {
    const rows = cols.map((col) => {
      const st = numericStats[col];
      const desc = colDesc[col] || '—';
      const trendBadge = st
        ? `<span class="trend ${st.trend.includes('上升') ? 'up' : (st.trend.includes('下降') ? 'down' : 'flat')}">${st.trend}</span>`
        : '<span class="trend flat">—</span>';
      const stats = st
        ? `<span class="stat">最小 ${fmt(st.min)}</span><span class="stat">最大 ${fmt(st.max)}</span><span class="stat">均值 ${fmt(st.mean)}</span>`
        : '<span class="stat dim">非数值列</span>';
      return `<div class="metric-row">
        <div class="metric-head">
          <code class="metric-name">${col}</code>
          <span class="metric-desc">${desc}</span>
          ${trendBadge}
        </div>
        <div class="metric-body">
          ${stats}
          ${inlineNote(col, st)}
        </div>
      </div>`;
    }).join('');
    const open = layerName.startsWith('L0') || layerName.startsWith('L1') ? 'open' : '';
    return `<details class="layer-card" ${open}>
      <summary><span class="layer-name">${layerName}</span><span class="layer-count">${cols.length} 项</span></summary>
      <div class="layer-body">${rows}</div>
    </details>`;
  }

  const layerCards = layerOrder
    .filter((l) => layers[l] && layers[l].length)
    .map((l) => renderLayerCard(l, layers[l]))
    .join('');

  // 数据预览（前 8 列，前 15 行）
  let previewTable = '<p class="dim">轨迹为空。</p>';
  if (traj.rows.length > 0) {
    const previewCols = traj.columns.slice(0, 8);
    const head = previewCols.map((c) => `<th><code>${c}</code></th>`).join('');
    const body = traj.rows.slice(0, 15).map((row, i) => {
      const cells = previewCols.map((c) => {
        const v = row[c] || '';
        const num = parseFloat(v);
        const display = (!isNaN(num) && v !== '') ? fmt(num) : String(v).slice(0, 20);
        return `<td>${display}</td>`;
      }).join('');
      return `<tr><td class="row-idx">${i + 1}</td>${cells}</tr>`;
    }).join('');
    const more = traj.rows.length > 15 ? `<p class="dim">…共 ${traj.total} 行，仅展示前 15 行</p>` : '';
    previewTable = `<div class="table-wrap"><table class="preview-table"><thead><tr><th>#</th>${head}</tr></thead><tbody>${body}</tbody></table></div>${more}`;
  }

  // 任务历史
  let historyHtml = '<p class="dim">无任务历史。</p>';
  if (history.length > 0) {
    historyHtml = `<div class="table-wrap"><table class="history-table">
      <thead><tr><th>#</th><th>任务 ID</th><th>模式</th><th>状态</th><th>开始时间</th></tr></thead>
      <tbody>${history.map((j, i) => {
    const statusClass = j.status === 'completed' ? 'ok' : (j.status === 'failed' ? 'err' : 'warn');
    const statusText = j.status === 'completed' ? '✓ 完成' : (j.status === 'failed' ? '✗ 失败' : j.status);
    return `<tr><td class="row-idx">${i + 1}</td><td><code>${j.id}</code></td><td>${j.mode || '?'}</td><td class="${statusClass}">${statusText}</td><td>${fmtTs(j.startTime)}</td></tr>`;
  }).join('')}</tbody>
    </table></div>`;
  }

  // 总结
  const parts = [];
  if (traj.total > 0) parts.push(`已采集 ${traj.total} 条轨迹`);
  if (edmReady) parts.push('EDM 可触发');
  else parts.push(`需 ${Math.max(0, 15 - traj.total)} 条更多数据才能触发 EDM`);
  if (history.length > 0) {
    const completed = history.filter((j) => j.status === 'completed').length;
    parts.push(`历史任务 ${completed}/${history.length} 完成`);
  }
  const summary = parts.join('；') + '。';

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TRACE-TO-EDM 桥接报告 — ${projectName}</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #020408;
      --bg-elevated: #05080f;
      --panel: rgba(8, 12, 20, 0.92);
      --panel-solid: #080c14;
      --panel-2: #0c1220;
      --accent: #66fcf1;
      --accent-dim: #45a29e;
      --accent2: #4da6ff;
      --warn: #f2c94c;
      --fail: #ff4d4d;
      --success: #03c988;
      --text: #d8dce6;
      --text-bright: #f0f2f7;
      --muted: #5e6a7d;
      --border: rgba(58, 68, 88, 0.85);
      --border-bright: #5a6678;
      --font-mono: "JetBrains Mono", "Fira Code", "Consolas", monospace;
      --font-ui: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: clamp(14px, 2vw, 28px);
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-ui);
      line-height: 1.6;
    }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .report-header {
      background: linear-gradient(180deg, rgba(10,14,24,0.95) 0%, rgba(8,12,20,0.92) 100%);
      border: 1px solid var(--border);
      border-left: 4px solid var(--accent);
      border-radius: 6px;
      padding: clamp(14px, 2vw, 22px);
      margin-bottom: 22px;
    }
    .report-header h1 {
      margin: 0 0 8px;
      font-size: clamp(1.15rem, 2.4vw, 1.6rem);
      color: var(--text-bright);
      font-family: var(--font-mono);
    }
    .report-header .subtitle { color: var(--muted); font-size: 0.85rem; margin: 0 0 14px; }
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      font-size: 0.82rem;
    }
    .meta-item { display: flex; gap: 8px; }
    .meta-item .label { color: var(--muted); white-space: nowrap; }
    .meta-item .value { color: var(--accent); font-family: var(--font-mono); }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 3px;
      font-size: 0.75rem;
      border: 1px solid var(--border-bright);
    }
    .badge.ok { color: var(--success); border-color: rgba(3, 201, 136, 0.5); background: rgba(3, 201, 136, 0.08); }
    .badge.warn { color: var(--warn); border-color: rgba(242, 201, 76, 0.5); background: rgba(242, 201, 76, 0.08); }
    .section-title {
      font-size: 0.9rem;
      color: var(--accent);
      margin: 28px 0 12px;
      font-family: var(--font-mono);
      border-bottom: 1px solid var(--border);
      padding-bottom: 6px;
    }
    .layer-card {
      background: var(--panel-solid);
      border: 1px solid var(--border);
      border-radius: 5px;
      margin-bottom: 12px;
      overflow: hidden;
    }
    .layer-card summary {
      cursor: pointer;
      padding: 12px 14px;
      background: var(--panel-2);
      display: flex;
      align-items: center;
      gap: 12px;
      user-select: none;
      list-style: none;
    }
    .layer-card summary::-webkit-details-marker { display: none; }
    .layer-card summary::before {
      content: "▶";
      color: var(--accent);
      font-size: 0.7rem;
      transition: transform 0.15s;
    }
    .layer-card[open] summary::before { transform: rotate(90deg); }
    .layer-name { color: var(--text-bright); font-weight: 600; font-family: var(--font-mono); }
    .layer-count { color: var(--muted); font-size: 0.72rem; margin-left: auto; }
    .layer-body { padding: 10px 14px 14px; }
    .metric-row {
      border-bottom: 1px solid rgba(58, 68, 88, 0.45);
      padding: 10px 0;
    }
    .metric-row:last-child { border-bottom: none; padding-bottom: 0; }
    .metric-head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 12px;
      margin-bottom: 6px;
    }
    .metric-name {
      background: rgba(102, 252, 241, 0.08);
      color: var(--accent);
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 0.78rem;
    }
    .metric-desc { color: var(--text); font-size: 0.82rem; flex: 1 1 auto; }
    .metric-body {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 14px;
      font-size: 0.78rem;
    }
    .stat {
      color: var(--text-bright);
      font-family: var(--font-mono);
      background: rgba(90, 102, 120, 0.18);
      padding: 2px 7px;
      border-radius: 3px;
    }
    .stat.dim { color: var(--muted); background: transparent; padding: 0; }
    .trend {
      font-family: var(--font-mono);
      font-size: 0.72rem;
      padding: 1px 6px;
      border-radius: 3px;
      border: 1px solid var(--border-bright);
    }
    .trend.up { color: var(--success); border-color: rgba(3, 201, 136, 0.45); background: rgba(3, 201, 136, 0.08); }
    .trend.down { color: var(--fail); border-color: rgba(255, 77, 77, 0.45); background: rgba(255, 77, 77, 0.08); }
    .trend.flat { color: var(--muted); border-color: var(--border); background: rgba(58, 68, 88, 0.15); }
    .metric-note {
      color: var(--warn);
      font-size: 0.74rem;
      border-left: 2px solid var(--warn);
      padding-left: 8px;
      max-width: 100%;
    }
    .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 4px; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.76rem;
      font-family: var(--font-mono);
    }
    th, td {
      padding: 6px 9px;
      text-align: left;
      border-bottom: 1px solid rgba(58, 68, 88, 0.45);
      white-space: nowrap;
    }
    th {
      background: var(--panel-2);
      color: var(--accent);
      font-weight: 600;
    }
    tr:last-child td { border-bottom: none; }
    .row-idx { color: var(--muted); }
    .ok { color: var(--success); }
    .err { color: var(--fail); }
    .warn { color: var(--warn); }
    .dim { color: var(--muted); }
    .summary-box {
      background: rgba(102, 252, 241, 0.06);
      border: 1px solid rgba(102, 252, 241, 0.25);
      border-radius: 5px;
      padding: 14px;
      font-size: 0.9rem;
      color: var(--text-bright);
    }
    .footer {
      margin-top: 28px;
      padding-top: 14px;
      border-top: 1px solid var(--border);
      color: var(--muted);
      font-size: 0.75rem;
      text-align: right;
    }
    @media (max-width: 640px) {
      .meta-grid { grid-template-columns: 1fr; }
      .metric-head { flex-direction: column; align-items: flex-start; }
    }
  </style>
</head>
<body>
  <div class="report-header">
    <h1>TRACE-TO-EDM 桥接报告</h1>
    <p class="subtitle">面向非技术读者的人话版解读 · 基于轨迹 CSV + 任务历史自动生成</p>
    <div class="meta-grid">
      <div class="meta-item"><span class="label">当前项目</span><span class="value">${projectName}</span></div>
      <div class="meta-item"><span class="label">轨迹文件</span><span class="value">${traj.path || 'N/A'}</span></div>
      <div class="meta-item"><span class="label">轨迹行数</span><span class="value">${traj.total}</span></div>
      <div class="meta-item"><span class="label">轨迹列数</span><span class="value">${traj.columns.length}</span></div>
      <div class="meta-item"><span class="label">EDM 就绪</span>${edmReady ? '<span class="badge ok">✓ 是（≥15 行）</span>' : '<span class="badge warn">✗ 否（<15 行）</span>'}</div>
      <div class="meta-item"><span class="label">活动任务</span><span class="value">${active.length}</span></div>
      <div class="meta-item"><span class="label">历史任务</span><span class="value">${history.length} 条（最近）</span></div>
      <div class="meta-item"><span class="label">生成时间</span><span class="value">${fmtTs(generated)}</span></div>
    </div>
  </div>

  <div class="section-title">◈ 指标层级卡片</div>
  <p class="dim" style="font-size:0.78rem;margin:-8px 0 14px;">趋势 = 后半段均值 vs 前半段均值；↗/↘ 幅度 &gt; 5% 均值才算“上升/下降”，否则为“平稳”。</p>
  ${layerCards}

  <div class="section-title">◈ 轨迹数据预览（Top 15）</div>
  ${previewTable}

  <div class="section-title">◈ 任务历史（最近 20 条）</div>
  ${historyHtml}

  <div class="section-title">◈ 一句话总结</div>
  <div class="summary-box">${summary}</div>

  <div class="footer">报告由 trace-to-edm Web 自动生成于 ${fmtTs(generated)} · <a href="/api/trajectory/report">Markdown 版</a></div>
</body>
</html>`;
}


module.exports = {
  getActiveTrajectoryCSV,
  readTrajectoryCSV,
  buildTrajectoryReport,
  buildTrajectoryReportHTML,
};
