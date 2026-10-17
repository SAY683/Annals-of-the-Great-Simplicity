module.exports = function mount(app, ctx) {
const { fs, path, spawn, crypto, ROOT, PROJECTS_DIR, TRAJECTORY_CSV, PYTHON_CMD, BRIDGE_SCRIPT, PACKAGE_VERSION, serverLog, reqLog, getActiveTrajectoryCSV, pyCall, pyScript, errorResponse, activeJobs, jobHistory, createJobId, emitSSE, streamBridgeProcess, readTrajectoryCSV, buildTrajectoryReport, buildTrajectoryReportHTML, getCached, setCached, invalidateCache, pyDS, getDatasetExports, markDatasetProcessed, pipelineState } = ctx;

app.get('/api/health', async (_req, res) => {
  const checks = {};
  let overall = 'healthy';

  // 1. Python 可用性 (bridge.py 依赖)
  try {
    const { execFileSync } = require('child_process');
    const pyOut = execFileSync(PYTHON_CMD, ['--version'], {
      encoding: 'utf-8',
      timeout: 3000,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    }).trim();
    checks['python'] = pyOut;
  } catch (e) {
    checks['python'] = `fail: ${e.message}`;
    overall = 'unhealthy'; // 无 Python 则 bridge.py 全部失效
  }

  // 2. data/inputs 目录存在
  const inputsDir = path.join(ROOT, 'data', 'inputs');
  try {
    if (fs.existsSync(inputsDir) && fs.statSync(inputsDir).isDirectory()) {
      checks['data_inputs_dir'] = 'ok';
    } else {
      checks['data_inputs_dir'] = 'missing';
      overall = 'degraded';
    }
  } catch (e) {
    checks['data_inputs_dir'] = `error: ${e.message}`;
    overall = 'degraded';
  }

  // 3. projects 目录存在 (任务产物存储)
  try {
    if (fs.existsSync(PROJECTS_DIR) && fs.statSync(PROJECTS_DIR).isDirectory()) {
      checks['projects_dir'] = 'ok';
    } else {
      checks['projects_dir'] = 'missing';
      overall = 'degraded';
    }
  } catch (e) {
    checks['projects_dir'] = `error: ${e.message}`;
    overall = 'degraded';
  }

  // 4. bridge.py 脚本可访问 (核心桥接逻辑)
  try {
    if (fs.existsSync(BRIDGE_SCRIPT) && fs.statSync(BRIDGE_SCRIPT).isFile()) {
      checks['bridge_py'] = 'ok';
    } else {
      checks['bridge_py'] = 'missing';
      overall = 'unhealthy'; // 无 bridge.py 则所有 Python 调用失效
    }
  } catch (e) {
    checks['bridge_py'] = `error: ${e.message}`;
    overall = 'unhealthy';
  }

  // 5. 活跃任务数 (便于监控)
  try {
    checks['active_jobs'] = activeJobs.size;
  } catch (e) {
    checks['active_jobs'] = 'unknown';
  }

  res.json({
    status: overall,
    service: 'trace-to-edm',
    version: PACKAGE_VERSION,
    time: new Date().toISOString(),
    checks,
  });
});

// debt-12.13: 暴露 /api/version 端点，版本号从 package.json 读取
// 与 trace-engine-web /api/version 契约对齐，便于便携式 verify 与运维监控
app.get('/api/version', (_req, res) => {
  res.json({
    success: true,
    service: 'trace-to-edm',
    version: PACKAGE_VERSION,
    node: process.version,
    time: new Date().toISOString(),
  });
});

// ── API: 状态查询 ─────────────────────────────────────────

// ROUND28 P0-04/P1-04: EDM 分级 confidence_level (与 edm_trigger.py 阈值对齐)
// 15-30 行 = exploratory (探索性), ≥30 行 = formal (正式), <15 = insufficient
// 阈值常量与 edm_trigger.EDM_FORMAL_THRESHOLD / config.EDM_MIN_ROWS_FOR_ANALYSIS 保持同步
const EDM_MIN_ROWS = 15;
const EDM_FORMAL_THRESHOLD = 30;
function computeEDMConfidence(nRows) {
  if (nRows < EDM_MIN_ROWS) {
    return {
      confidence_level: 'insufficient',
      confidence_disclaimer: `数据不足 (${nRows} < ${EDM_MIN_ROWS}), 无法触发 EDM 分析。`,
    };
  }
  if (nRows < EDM_FORMAL_THRESHOLD) {
    return {
      confidence_level: 'exploratory',
      confidence_disclaimer:
        `探索性分析 (${nRows} 行, < ${EDM_FORMAL_THRESHOLD}): ` +
        'EDM 动力学预测在小样本下不稳定, 可能产生伪相变信号。' +
        '结果仅供探索, 不得用于投资决策。建议积累 ≥30 行后再做正式分析。',
    };
  }
  return {
    confidence_level: 'formal',
    confidence_disclaimer:
      `正式分析 (${nRows} 行 ≥ ${EDM_FORMAL_THRESHOLD}): ` +
      '结果可用于报告, 但仍需注意 EDM-TAKENS 的 IAAFT/BH 统计保证边界。',
  };
}

app.get('/api/status', (_req, res) => {
  const traj = readTrajectoryCSV();
  const active = Array.from(activeJobs.keys());

  // EDM 就绪度 + 分级置信度 (ROUND28 P0-04)
  const edmReady = traj.total >= EDM_MIN_ROWS;
  const { confidence_level, confidence_disclaimer } = computeEDMConfidence(traj.total);

  // ROUND28 P1-04/05: L3 目标标注 interpretive + methodology_tag
  // 与 layer3_sacred.METHODOLOGY_TAG / METHODOLOGY_DISCLAIMER 对齐
  const L3_TAG = 'interpretive_zero_shot';
  const L3_DISCLAIMER =
    'Layer 3 是诠释性框架 (Interpretive Framework), 非统计推断。' +
    'z_* 值由八本私域经书的零样本余弦相似度确定, 不具备 Layer 1 那样的 ' +
    'refutation/p-value 统计保证。投资决策需与 L1 统计量交叉验证。';
  const mkL1 = (col, desc) => ({ col, desc, layer: 'L1', interpretive: false, methodology_tag: 'statistical' });
  const mkL2 = (col, desc) => ({ col, desc, layer: 'L2', interpretive: false, methodology_tag: 'statistical_pca' });
  const mkL3 = (col, desc) => ({ col, desc, layer: 'L3', interpretive: true, methodology_tag: L3_TAG, methodology_disclaimer: L3_DISCLAIMER });

  const edmTargets = edmReady ? [
    // Layer 1: 元SCM (科学层)
    mkL1('ate', '因果效应强度'),
    mkL1('adj_density', '因果图密度 — 系统纠缠度'),
    mkL1('max_delta_nll', '最强因果信号'),
    mkL1('ci_width', '因果不确定性 — 时代噪音'),
    mkL1('edge_count', '显著因果边数'),
    mkL1('ccm_coverage_pct', 'CCM非线性验证覆盖率'),
    // Layer 2: 世俗语义 PCA (科学层)
    mkL2('z_pca_1', '世俗PCA第1主轴'),
    mkL2('z_pca_2', '世俗PCA第2主轴'),
    mkL2('z_pca_3', '世俗PCA第3主轴'),
    mkL2('secular_entropy', '世俗熵'),
    // Layer 3: 八正道全轴 (诠释层 · 非统计推断)
    mkL3('z_福音', '福音(祂志书) 投影'),
    mkL3('z_吉祥', '吉祥(赐福书) 投影'),
    mkL3('z_奥美', '奥美(圣源书) 投影'),
    mkL3('z_存在', '存在(真实书) 投影 — 本体论距离'),
    mkL3('z_自孕', '自孕(胜育书) 投影'),
    mkL3('z_弥赛亚', '弥赛亚(至意书) 投影'),
    mkL3('z_Alice', 'Alice(慧辩书) 投影'),
    mkL3('z_觉爱', '觉爱(智识书) 投影 — 智慧维度'),
    // Layer 3: 一阶差分 (诠释层 · 关键动力学信号)
    mkL3('dz_存在', '存在轴一阶差分 Δz/Δt'),
    mkL3('dz_觉爱', '觉爱轴一阶差分 Δz/Δt'),
  ] : [];

  res.json({
    success: true,
    trajectory: {
      path: getActiveTrajectoryCSV(),
      rows: traj.total,
      columns: traj.columns.length,
      edm_ready: edmReady,
      edm_targets: edmTargets,
      // ROUND28 P0-04: 分级置信度披露
      confidence_level,
      confidence_disclaimer,
      formal_threshold: EDM_FORMAL_THRESHOLD,
      min_required: EDM_MIN_ROWS,
    },
    jobs: { active: active.length, active_ids: active },
    layers: {
      l1: traj.columns.filter(c => ['ate','adj_density','edge_count','ccm_coverage_pct'].includes(c)).length > 0,
      l2: traj.columns.includes('z_pca_1'),
      l3: traj.columns.includes('z_存在'),
    },
  });
});

// ── API: 八正道正交性报告 ─────────────────────────────────

app.get('/api/orthogonality', async (_req, res) => {
  try {
    // Q9 P1-11: 暴露 Frobenius 距离等元审计数据
    const script = `
import sys, json; sys.path.insert(0, '.')
from layer3_sacred import SacredProjector
sp = SacredProjector()
loaded = sp.load_sacred_texts()
if not loaded:
    print(json.dumps({"available": False, "error": "sacred texts not loaded"}))
else:
    report = sp.get_orthogonality_report()
    print(json.dumps(report, ensure_ascii=False, default=str))
    `.trim();
    const { out } = await pyScript(script, 30000);
    try { res.json(JSON.parse(out)); }
    catch { res.status(500).json({ error: 'invalid response', raw: out.slice(0, 500) }); }
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

// ── API: 轨迹数据 ─────────────────────────────────────────


};
