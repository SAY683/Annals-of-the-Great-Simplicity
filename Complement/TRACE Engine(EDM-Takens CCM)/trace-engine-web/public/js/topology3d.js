const topologyStates = new Map();

function project(p, rotX, rotY, zoom, W, H) {
  // 绕 Y 轴旋转
  let x = p.x * Math.cos(rotY) - p.z * Math.sin(rotY);
  let z = p.x * Math.sin(rotY) + p.z * Math.cos(rotY);
  // 绕 X 轴旋转
  let y = p.y * Math.cos(rotX) - z * Math.sin(rotX);
  z = p.y * Math.sin(rotX) + z * Math.cos(rotX);
  const fov = 800;
  const scale = (fov * zoom) / (fov + z + 400);
  return { x: W / 2 + x * scale, y: H / 2 + y * scale, z, scale };
}

function initPositions(nodes, edges) {
  const n = nodes.length;
  const radius = Math.max(120, n * 18);
  nodes.forEach((node, i) => {
    const theta = (i / n) * Math.PI * 2;
    const phi = Math.acos(2 * (i + 0.5) / n - 1);
    node.x = radius * Math.sin(phi) * Math.cos(theta);
    node.y = radius * Math.sin(phi) * Math.sin(theta);
    node.z = radius * Math.cos(phi);
    // 节点大小基于出现频次
    node.radius = 4 + Math.sqrt(node.freq || 1) * 1.8;
  });
  // 简单力导向迭代几次让边长度均匀
  for (let iter = 0; iter < 40; iter++) {
    // 斥力
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
        let dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
        const force = 2000 / (dist * dist + 100);
        const fx = (dx / dist) * force, fy = (dy / dist) * force, fz = (dz / dist) * force;
        a.x += fx; a.y += fy; a.z += fz;
        b.x -= fx; b.y -= fy; b.z -= fz;
      }
    }
    // 引力(边)
    edges.forEach(e => {
      const a = e.source, b = e.target;
      let dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
      let dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
      const force = (dist - 90) * 0.015;
      const fx = (dx / dist) * force, fy = (dy / dist) * force, fz = (dz / dist) * force;
      a.x += fx; a.y += fy; a.z += fz;
      b.x -= fx; b.y -= fy; b.z -= fz;
    });
    // 向中心引力防止飞散
    nodes.forEach(node => {
      node.x *= 0.96; node.y *= 0.96; node.z *= 0.96;
    });
  }
}

function renderTopology3D(r, wrap, canvas, pauseBtn, resetBtn) {
  if (!wrap || !canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;

  function resize() {
    const rect = wrap.getBoundingClientRect();
    const W = Math.max(1, rect.width);
    const H = Math.max(1, rect.height);
    canvas.width = Math.floor(W * dpr);
    canvas.height = Math.floor(H * dpr);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { W, H };
  }

  let { W, H } = resize();

  // DES-01 修复: 节点数 > 32 时显示提示，避免静默丢弃
  const allConcepts = r.concepts || [];
  const TRUNCATED = allConcepts.length > 32;
  const concepts = allConcepts.slice(0, 32); // 限制节点数保证性能
  const freq = r.concept_frequencies || {};
  if (concepts.length < 2) {
    ctx.fillStyle = '#94a3b8';
    ctx.font = '13px monospace';
    ctx.fillText('概念数不足 (需≥2)', 12, H / 2);
    return;
  }

  const nodes = concepts.map((c, i) => ({ id: c, index: i, freq: freq[c] || 1 }));
  const edges = [];
  const matrix = r.adjacency_matrix;
  if (matrix && matrix.length === concepts.length) {
    for (let i = 0; i < concepts.length; i++) {
      for (let j = 0; j < concepts.length; j++) {
        if (i === j) continue;
        const v = Number(matrix[i][j]);
        if (!isNaN(v) && Math.abs(v) > 0.01) {
          edges.push({ source: nodes[i], target: nodes[j], strength: v });
        }
      }
    }
  }
  // 如果没有矩阵，用 top_edges 兜底
  if (edges.length === 0 && r.top_edges) {
    r.top_edges.forEach(e => {
      const s = nodes.find(n => n.id === e.source);
      const t = nodes.find(n => n.id === e.target);
      if (s && t) edges.push({ source: s, target: t, strength: e.strength });
    });
  }

  initPositions(nodes, edges);

  const existing = topologyStates.get(canvas);
  if (existing && existing.rafId) cancelAnimationFrame(existing.rafId);

  const state = {
    rafId: null, nodes, edges, rotX: 0.35, rotY: 0.45, zoom: 1.0,
    dragging: false, lastX: 0, lastY: 0, paused: false, W, H, wrap, canvas, ctx, dpr,
    truncated: TRUNCATED, totalConcepts: allConcepts.length
  };
  topologyStates.set(canvas, state);

  function draw() {
    const s = topologyStates.get(canvas);
    if (!s) return;
    const { W: w, H: h } = s;

    // ── 氛围背景: 径向渐变 + 网格 + 星点 ──────────────────────
    const bgGrad = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.7);
    bgGrad.addColorStop(0, '#0a1018');
    bgGrad.addColorStop(0.5, '#070b12');
    bgGrad.addColorStop(1, '#030508');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, w, h);

    // 细网格 (透视感)
    ctx.strokeStyle = 'rgba(102,252,241,0.04)';
    ctx.lineWidth = 1;
    const gridStep = 40;
    for (let x = 0; x < w; x += gridStep) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }
    for (let y = 0; y < h; y += gridStep) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }
    // 星点 (固定 seed 避免闪烁)
    if (!s._stars) {
      s._stars = [];
      for (let i = 0; i < 60; i++) {
        s._stars.push({ x: Math.random() * w, y: Math.random() * h, r: Math.random() * 1.2 + 0.3, a: Math.random() * 0.3 + 0.1 });
      }
    }
    s._stars.forEach(st => {
      ctx.fillStyle = `rgba(180,200,220,${st.a})`;
      ctx.beginPath(); ctx.arc(st.x, st.y, st.r, 0, Math.PI * 2); ctx.fill();
    });

    // ── 投影所有节点并排序(远到近) ──────────────────────────
    const projected = s.nodes.map(n => ({ node: n, ...project(n, s.rotX, s.rotY, s.zoom, w, h) })).sort((a, b) => a.z - b.z);
    const maxStr = s.edges.reduce((mx, x) => { const a = Math.abs(x.strength); return a > mx ? a : mx; }, 1e-6);

    // ── 画边: 渐变 + 箭头 + strength 标签 ────────────────────
    s.edges.forEach(e => {
      const pa = projected[e.source.index];
      const pb = projected[e.target.index];
      if (!pa || !pb) return;
      const intensity = Math.min(Math.abs(e.strength) / maxStr, 1);
      const avgAlpha = (Math.max(0.35, Math.min(1, (pa.z + 300) / 500)) + Math.max(0.35, Math.min(1, (pb.z + 300) / 500))) / 2;

      // 按强度分三级可视化：弱边虚线无箭头、中边实线小箭头、强边粗线发光大箭头
      // 颜色按温度渐变：正因果从冷青到暖黄，负因果从冷蓝到暖红
      let lineWidth, arrowSize, arrowThreshold, glowBlur, dashPattern;
      if (intensity < 0.35) {
        lineWidth = 0.55 + intensity * 0.55;
        arrowSize = 0;
        arrowThreshold = -1;
        glowBlur = 0;
        dashPattern = [2, 2];
      } else if (intensity < 0.7) {
        lineWidth = 0.85 + intensity * 0.85;
        arrowSize = 2 + intensity * 2;
        arrowThreshold = 0.35;
        glowBlur = 0;
        dashPattern = [];
      } else {
        lineWidth = 1.25 + intensity * 1.15;
        arrowSize = 3.5 + intensity * 2.5;
        arrowThreshold = 0.35;
        glowBlur = 3 + intensity * 5;
        dashPattern = [];
      }

      const lineGrad = ctx.createLinearGradient(pa.x, pa.y, pb.x, pb.y);
      lineGrad.addColorStop(0, edgeTempColor(e.strength, intensity, (0.25 + intensity * 0.55) * avgAlpha));
      lineGrad.addColorStop(1, edgeTempColor(e.strength, intensity, (0.12 + intensity * 0.35) * avgAlpha));
      ctx.strokeStyle = lineGrad;
      ctx.lineWidth = lineWidth;
      ctx.lineCap = 'round';
      ctx.setLineDash(dashPattern);

      if (glowBlur > 0) {
        ctx.shadowBlur = glowBlur;
        ctx.shadowColor = edgeTempColor(e.strength, intensity, 0.5);
      }
      ctx.beginPath();
      ctx.moveTo(pa.x, pa.y);
      ctx.lineTo(pb.x, pb.y);
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.setLineDash([]);

      // 方向箭头 (仅中强边)
      if (intensity > arrowThreshold && arrowSize > 0 && avgAlpha > 0.5) {
        const arrowPos = 0.62;
        const ax = pa.x + (pb.x - pa.x) * arrowPos;
        const ay = pa.y + (pb.y - pa.y) * arrowPos;
        const angle = Math.atan2(pb.y - pa.y, pb.x - pa.x);
        ctx.fillStyle = edgeTempColor(e.strength, intensity, (0.7 + intensity * 0.25) * avgAlpha);
        ctx.beginPath();
        ctx.moveTo(ax + Math.cos(angle) * arrowSize, ay + Math.sin(angle) * arrowSize);
        ctx.lineTo(ax + Math.cos(angle + 2.5) * arrowSize * 0.75, ay + Math.sin(angle + 2.5) * arrowSize * 0.75);
        ctx.lineTo(ax + Math.cos(angle - 2.5) * arrowSize * 0.75, ay + Math.sin(angle - 2.5) * arrowSize * 0.75);
        ctx.closePath();
        ctx.fill();
      }

      // strength 数值标签 (中点, 仅强边且近)
      if (intensity > 0.35 && avgAlpha > 0.6) {
        const mx = (pa.x + pb.x) / 2;
        const my = (pa.y + pb.y) / 2;
        const label = e.strength.toFixed(2);
        ctx.font = '9px monospace';
        const tw = ctx.measureText(label).width;
        // 背景药丸
        ctx.fillStyle = `rgba(10,16,24,${0.7 * avgAlpha})`;
        ctx.fillRect(mx - tw / 2 - 3, my - 7, tw + 6, 12);
        ctx.fillStyle = edgeTempColor(e.strength, intensity, 0.85 * avgAlpha);
        ctx.fillText(label, mx - tw / 2, my + 2);
      }
    });

    // ── 画节点: 径向渐变 + 发光 + 完整标签 ───────────────────
    projected.forEach(p => {
      const radius = p.node.radius * Math.max(0.4, p.scale * 0.012);
      const alpha = Math.max(0.35, Math.min(1, (p.z + 300) / 500));

      // 外发光
      if (alpha > 0.5) {
        ctx.shadowBlur = 8 + radius;
        ctx.shadowColor = `rgba(0,217,163,${alpha * 0.5})`;
      }
      // 径向渐变填充
      const nodeGrad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, radius);
      nodeGrad.addColorStop(0, `rgba(120,255,200,${alpha})`);
      nodeGrad.addColorStop(0.6, `rgba(0,217,163,${alpha * 0.8})`);
      nodeGrad.addColorStop(1, `rgba(0,180,135,${alpha * 0.3})`);
      ctx.fillStyle = nodeGrad;
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      // 边框
      ctx.strokeStyle = `rgba(255,255,255,${alpha * 0.45})`;
      ctx.lineWidth = 0.8;
      ctx.stroke();

      // 完整概念名标签 (带背景药丸, 近节点)
      if (alpha > 0.55) {
        const label = p.node.id;
        const fontSize = Math.max(10, Math.min(13, 11 * p.scale * 0.012));
        // P2 修复：Canvas ctx.font 不解析 CSS 变量，需用实际字体名（取自 tokusatsu.css --font-mono）
        ctx.font = `${fontSize}px "JetBrains Mono", "Fira Code", "Consolas", "SF Mono", monospace`;
        const tw = ctx.measureText(label).width;
        const labelX = p.x + radius + 4;
        const labelY = p.y - fontSize / 2;
        // 背景药丸
        ctx.fillStyle = `rgba(10,16,24,${0.65 * alpha})`;
        ctx.fillRect(labelX - 2, labelY - 1, tw + 6, fontSize + 4);
        ctx.strokeStyle = `rgba(102,252,241,${0.2 * alpha})`;
        ctx.lineWidth = 0.5;
        ctx.strokeRect(labelX - 2, labelY - 1, tw + 6, fontSize + 4);
        // 文字
        ctx.fillStyle = `rgba(210,230,245,${alpha})`;
        ctx.fillText(label, labelX + 1, labelY + fontSize);
      }
    });

    // ── HUD: 信息看板 ────────────────────────────────────────
    // 半透明背景条（两行：操作提示 + 图例状态，避免单行过长重叠）
    const hudH = 40;
    ctx.fillStyle = 'rgba(5,10,16,0.75)';
    ctx.fillRect(0, h - hudH, w, hudH);
    ctx.font = '10px monospace';
    ctx.fillStyle = 'rgba(148,163,184,0.85)';
    ctx.fillText(`◈ 3D CAUSAL TOPOLOGY  n=${s.nodes.length} e=${s.edges.length}${s.truncated ? ' (前32)' : ''}  ·  拖拽旋转 · 滚轮缩放 · 点击节点坍缩为 2D`, 8, h - 26);
    ctx.fillStyle = 'rgba(148,163,184,0.7)';
    ctx.fillText('─强边  - -弱边  →方向  色温=强度  ▲正因果  ▼负因果', 8, h - 10);
    // 节点截断提示
    if (s.truncated) {
      ctx.fillStyle = 'rgba(251,191,36,0.9)';
      ctx.font = '10px monospace';
      ctx.fillText(`⚠ 已显示前 32 个节点 (共 ${s.totalConcepts} 个)`, 8, h - 52);
    }
  }

  function animate() {
    const s = topologyStates.get(canvas);
    if (!s) return;
    if (!s.paused && !s.dragging) s.rotY += 0.003;
    draw();
    s.rafId = requestAnimationFrame(animate);
  }

  // 事件绑定(每个 canvas 只绑定一次)
  if (!canvas._topoBound) {
    canvas._topoBound = true;
    canvas.addEventListener('mousedown', e => {
      const s = topologyStates.get(canvas);
      if (!s) return;
      s.dragging = true;
      s.lastX = e.clientX;
      s.lastY = e.clientY;
    });
    window.addEventListener('mousemove', e => {
      for (const s of topologyStates.values()) {
        if (!s.dragging) continue;
        const dx = e.clientX - s.lastX;
        const dy = e.clientY - s.lastY;
        s.rotY += dx * 0.008;
        s.rotX += dy * 0.008;
        s.lastX = e.clientX;
        s.lastY = e.clientY;
      }
    });
    window.addEventListener('mouseup', () => {
      for (const s of topologyStates.values()) s.dragging = false;
    });
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const s = topologyStates.get(canvas);
      if (!s) return;
      s.zoom *= e.deltaY > 0 ? 0.9 : 1.1;
      s.zoom = Math.max(0.3, Math.min(3.0, s.zoom));
    }, { passive: false });
  }

  pauseBtn = pauseBtn || wrap.querySelector('.topo-pause-btn');
  if (pauseBtn && !pauseBtn._topoBound) {
    pauseBtn._topoBound = true;
    pauseBtn.addEventListener('click', () => {
      const s = topologyStates.get(canvas);
      if (!s) return;
      s.paused = !s.paused;
      pauseBtn.textContent = s.paused ? '▶' : '⏸';
    });
  }
  resetBtn = resetBtn || wrap.querySelector('.topo-reset-btn');
  if (resetBtn && !resetBtn._topoBound) {
    resetBtn._topoBound = true;
    resetBtn.addEventListener('click', () => {
      const s = topologyStates.get(canvas);
      if (!s) return;
      s.rotX = 0.35; s.rotY = 0.45; s.zoom = 1.0;
    });
  }

  if (!wrap._topoResizeObs) {
    const ro = new ResizeObserver(() => {
      const s = topologyStates.get(canvas);
      if (!s) return;
      const rect = wrap.getBoundingClientRect();
      s.W = Math.max(1, rect.width);
      s.H = Math.max(1, rect.height);
      canvas.width = Math.floor(s.W * dpr);
      canvas.height = Math.floor(s.H * dpr);
      canvas.style.width = s.W + 'px';
      canvas.style.height = s.H + 'px';
      s.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    });
    ro.observe(wrap);
    wrap._topoResizeObs = ro;
  }

  animate();
}
window.renderTopology3D = renderTopology3D;

// P0 升级 (2026-07-29): 3D 拓扑点击节点后坍缩为 2D 力导向网络图谱
// 支持：力导向布局、节点拖拽、滚轮缩放、空白处拖拽平移、点击高亮邻居。
