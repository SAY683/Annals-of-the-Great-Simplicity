function edgeTempColor(strength, intensity, alpha) {
  const t = Math.max(0, Math.min(1, intensity));
  let h, s, l;
  if (strength > 0) {
    // 正因果：深蓝青 -> 青 -> 绿青 -> 暖黄
    if (t < 0.33) { h = 200 - t * 75; s = 65; l = 32 + t * 25; }
    else if (t < 0.66) { h = 175 - (t - 0.33) * 45; s = 80; l = 52 + (t - 0.33) * 15; }
    else { h = 160 - (t - 0.66) * 155; s = 90; l = 67 + (t - 0.66) * 18; }
  } else {
    // 负因果：深蓝 -> 紫 -> 玫红 -> 红
    if (t < 0.33) { h = 235 + t * 120; s = 60; l = 32 + t * 25; }
    else if (t < 0.66) { h = 275 + (t - 0.33) * 120; s = 80; l = 52 + (t - 0.33) * 15; }
    else { h = 315 + (t - 0.66) * 75; s = 90; l = 67 + (t - 0.66) * 18; }
  }
  return `hsla(${h.toFixed(1)}, ${s}%, ${l.toFixed(1)}%, ${alpha})`;
}

// ── 共享热力词矩阵 HTML 生成器 ─────────────────────────────────────────
function buildAdjacencyMatrixHTML(r) {
  const concepts = r.concepts || [];
  const matrix = r.adjacency_matrix;
  if (!matrix || matrix.length === 0 || concepts.length === 0) {
    return '<div class="empty-state">无邻接矩阵数据</div>';
  }
  // P0 修复: SUPER 模式输出 token 级矩阵(442×442)，与 concepts(12) 维度不匹配
  // 需要维度守卫：如果矩阵维度 ≠ concepts 数量，降级为概念级聚合或提示
  if (matrix.length !== concepts.length) {
    // 尝试从 top_edges 构建概念级矩阵
    const n = concepts.length;
    const idx = new Map(concepts.map((c, i) => [c, i]));
    const agg = Array.from({length: n}, () => new Array(n).fill(0));
    const edges = r.top_edges || [];
    edges.forEach(e => {
      const si = idx.get(e.source);
      const ti = idx.get(e.target);
      if (si != null && ti != null) agg[si][ti] = Math.abs(e.strength);
    });
    // 用聚合矩阵替代
    return buildAdjacencyMatrixHTMLFromAgg(concepts, agg);
  }
  const n = concepts.length;
  // P0 修复: 用 reduce 替代 Math.max(...spread)，防止大矩阵爆栈
  const maxVal = matrix.reduce((mx, row) => {
    return row.reduce((rmx, v) => {
      const a = Math.abs(v);
      return a > rmx ? a : rmx;
    }, mx);
  }, 1e-9);
  // P0 修复 (2026-07-29): 矩阵标签差位问题——改用 "auto + repeat(n, 32px)" 网格,
  // 行标签不旋转, 列标签在独立表头中旋转, 避免单元格内旋转导致的差位.
  // P0+ 修复 (2026-07-29): 行标签列不能用 auto，否则会在宽屏下被拉得很远。
  // 改用 minmax(60px, 120px)，让第一列宽度由内容决定但上限 120px，紧贴矩阵单元格。
  // P1 修缮: 单元格根据容器自适应放大，同时设置上限避免大屏过度拉伸；
  // 行标签列固定宽度区间，保证短文本时矩阵仍保持视觉重量与居中感。
  const cellMax = 'min(6vw, 72px)';
  let html = `<div class="adj-matrix-wrap">`;
  html += `<div class="adj-matrix" style="grid-template-columns:minmax(80px, 120px) repeat(${n}, minmax(40px, ${cellMax}));">`;
  // 顶部列标签行
  html += '<div class="adj-corner"></div>';
  concepts.forEach(c => {
    html += `<div class="adj-col-header" title="${escapeHtml(c)}"><span>${escapeHtml(c)}</span></div>`;
  });
  // 数据行
  matrix.forEach((row, i) => {
    html += `<div class="adj-row-header" title="${escapeHtml(concepts[i])}">${escapeHtml(concepts[i])}</div>`;
    row.forEach((v, j) => {
      const intensity = Math.min(Math.abs(v) / maxVal, 1);
      const bg = i === j ? 'var(--panel-3)' : `rgba(102,252,241,${0.08 + intensity * 0.72})`;
      const color = intensity > 0.5 ? '#000' : 'var(--text)';
      const val = v !== 0 ? safeFmt(Number(v), 1) : '';
      html += `<div class="adj-cell" style="background:${bg};color:${color};" title="${escapeHtml(concepts[i])} → ${escapeHtml(concepts[j])}: ${safeFmt(Number(v), 2)}">${val}</div>`;
    });
  });
  html += '</div>';
  html += `<div class="adj-legend"><span>0</span><div class="adj-legend-bar"></div><span>${maxVal.toFixed(1)}</span></div>`;
  html += '</div>';
  return html;
}

// P0 修复: SUPER 模式 token 级矩阵降级为概念级聚合矩阵
function buildAdjacencyMatrixHTMLFromAgg(concepts, agg) {
  const n = concepts.length;
  const maxVal = agg.reduce((mx, row) => {
    return row.reduce((rmx, v) => {
      const a = Math.abs(v);
      return a > rmx ? a : rmx;
    }, mx);
  }, 1e-9);
  const cellMax = 'min(6vw, 72px)';
  let html = `<div class="adj-matrix-wrap">`;
  html += `<div class="adj-matrix" style="grid-template-columns:minmax(80px, 120px) repeat(${n}, minmax(40px, ${cellMax}));">`;
  html += '<div class="adj-corner"></div>';
  concepts.forEach(c => {
    html += `<div class="adj-col-header" title="${escapeHtml(c)}"><span>${escapeHtml(c)}</span></div>`;
  });
  agg.forEach((row, i) => {
    html += `<div class="adj-row-header" title="${escapeHtml(concepts[i])}">${escapeHtml(concepts[i])}</div>`;
    row.forEach((v, j) => {
      const intensity = Math.min(Math.abs(v) / maxVal, 1);
      const bg = i === j ? 'var(--panel-3)' : `rgba(102,252,241,${0.08 + intensity * 0.72})`;
      const color = intensity > 0.5 ? '#000' : 'var(--text)';
      const val = v !== 0 ? safeFmt(Number(v), 1) : '';
      html += `<div class="adj-cell" style="background:${bg};color:${color};" title="${escapeHtml(concepts[i])} → ${escapeHtml(concepts[j])}: ${safeFmt(Number(v), 2)}">${val}</div>`;
    });
  });
  html += '</div>';
  html += `<div class="adj-legend"><span>0</span><div class="adj-legend-bar"></div><span>${maxVal.toFixed(1)}</span></div>`;
  html += '</div>';
  return html;
}
window.buildAdjacencyMatrixHTML = buildAdjacencyMatrixHTML;

// P1 fix (Round 26 §5): 3D 因果拓扑网络图渲染器
// 用 Canvas 2D 模拟 3D 力导向 + 透视投影，支持拖拽旋转、滚轮缩放、自动旋转。
