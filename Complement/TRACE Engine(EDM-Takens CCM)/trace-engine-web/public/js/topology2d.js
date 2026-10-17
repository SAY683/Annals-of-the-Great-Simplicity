const topology2DStates = new Map();

function initPositions2D(nodes, edges, W, H) {
  const n = nodes.length;
  W = Math.max(1, Number(W) || 1);
  H = Math.max(1, Number(H) || 1);
  const radius = Math.min(W, H) * 0.35;
  nodes.forEach((node, i) => {
    const angle = (i / Math.max(n, 1)) * Math.PI * 2 + Math.random() * 0.2;
    node.x = W / 2 + radius * Math.cos(angle);
    node.y = H / 2 + radius * Math.sin(angle);
    node.vx = 0; node.vy = 0;
    node.radius = 5 + Math.sqrt(node.freq || 1) * 2.2;
  });
  // 力导向稳定化（使用与 step() 一致的温和系数，避免数值爆炸）
  const k = Math.sqrt((W * H) / Math.max(n, 1)) * 0.9;
  const maxCoord = Math.max(W, H) * 4; // 软边界，防止溢出
  for (let iter = 0; iter < 300; iter++) {
    // 斥力
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let dist = Math.sqrt(dx * dx + dy * dy);
        if (!Number.isFinite(dist) || dist < 0.5) dist = 0.5;
        const force = (k * k) / (dist * dist + 10) * 0.02;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
    }
    // 引力（边）
    edges.forEach(e => {
      const a = e.source, b = e.target;
      let dx = b.x - a.x, dy = b.y - a.y;
      let dist = Math.sqrt(dx * dx + dy * dy);
      if (!Number.isFinite(dist) || dist < 0.5) dist = 0.5;
      const targetLen = 70 + 80 / (Math.abs(e.strength) + 0.5);
      const force = (dist - targetLen) * 0.0008;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    });
    // 中心引力 + 速度阻尼 + 软边界
    nodes.forEach(node => {
      node.vx += (W / 2 - node.x) * 0.0005;
      node.vy += (H / 2 - node.y) * 0.0005;
      node.vx *= 0.92;
      node.vy *= 0.92;
      node.x += node.vx;
      node.y += node.vy;
      if (!Number.isFinite(node.x) || Math.abs(node.x) > maxCoord) node.x = W / 2;
      if (!Number.isFinite(node.y) || Math.abs(node.y) > maxCoord) node.y = H / 2;
    });
  }
  nodes.forEach(node => { node.vx = 0; node.vy = 0; });
}

function renderTopology2D(r, wrap, canvas, focusedNodeId = null) {
  if (!wrap || !canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;

  function resize() {
    const rect = wrap.getBoundingClientRect();
    const W = Math.max(1, Math.floor(rect.width));
    const H = Math.max(1, Math.floor(rect.height));
    canvas.width = Math.floor(W * dpr);
    canvas.height = Math.floor(H * dpr);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { W, H };
  }

  function init2D(W, H) {
  const allConcepts = (r.concepts || []).slice(0, 64);
  const freq = r.concept_frequencies || {};
  if (allConcepts.length < 2) {
    ctx.fillStyle = '#94a3b8';
    ctx.font = '13px monospace';
    ctx.fillText('概念数不足 (需≥2)', 12, H / 2);
    return;
  }

  const nodes = allConcepts.map((c, i) => ({ id: c, index: i, freq: freq[c] || 1 }));
  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const edges = [];
  const matrix = r.adjacency_matrix;
  if (matrix && matrix.length === allConcepts.length) {
    for (let i = 0; i < allConcepts.length; i++) {
      for (let j = 0; j < allConcepts.length; j++) {
        if (i === j) continue;
        const v = Number(matrix[i][j]);
        if (!isNaN(v) && Math.abs(v) > 0.01) {
          edges.push({ source: nodes[i], target: nodes[j], strength: v });
        }
      }
    }
  }
  if (edges.length === 0 && r.top_edges) {
    r.top_edges.forEach(e => {
      const s = nodeMap.get(e.source);
      const t = nodeMap.get(e.target);
      if (s && t) edges.push({ source: s, target: t, strength: e.strength });
    });
  }

  // 为互惠边分配反向弯曲偏移，避免 A→B 与 B→A 完全重叠
  const pairKey = (i, j) => `${Math.min(i, j)}-${Math.max(i, j)}`;
  const pairSeen = new Set();
  edges.forEach(e => {
    const reciprocal = edges.some(other => other.source.index === e.target.index && other.target.index === e.source.index);
    if (reciprocal) {
      const key = pairKey(e.source.index, e.target.index);
      e.curve = pairSeen.has(key) ? -1 : 1;
      pairSeen.add(key);
    } else {
      e.curve = 0;
    }
  });

  initPositions2D(nodes, edges, W, H);

  const existing = topology2DStates.get(canvas);
  if (existing && existing.rafId) cancelAnimationFrame(existing.rafId);

  const state = {
    rafId: null, nodes, edges, nodeMap, W, H, wrap, canvas, ctx, dpr,
    scale: 1.0, panX: 0, panY: 0,
    draggingNode: null, draggingCanvas: false, lastX: 0, lastY: 0,
    focusedNodeId,
    hoveredNode: null,
    alpha: 0 // 用于入场动画
  };
  topology2DStates.set(canvas, state);

  function step() {
    const s = topology2DStates.get(canvas);
    if (!s) return;
    // 温和力导向持续运行，保持动态稳定
    const k = Math.sqrt((s.W * s.H) / Math.max(s.nodes.length, 1)) * 0.9;
    for (let i = 0; i < s.nodes.length; i++) {
      for (let j = i + 1; j < s.nodes.length; j++) {
        const a = s.nodes[i], b = s.nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let dist = Math.sqrt(dx * dx + dy * dy);
        if (!Number.isFinite(dist) || dist < 0.5) dist = 0.5;
        const force = (k * k) / (dist * dist + 10) * 0.02;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
    }
    s.edges.forEach(e => {
      const a = e.source, b = e.target;
      let dx = b.x - a.x, dy = b.y - a.y;
      let dist = Math.sqrt(dx * dx + dy * dy);
      if (!Number.isFinite(dist) || dist < 0.5) dist = 0.5;
      const targetLen = 70 + 80 / (Math.abs(e.strength) + 0.5);
      const force = (dist - targetLen) * 0.0008;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    });
    s.nodes.forEach(node => {
      if (node === s.draggingNode) return;
      node.vx += (s.W / 2 - node.x) * 0.0005;
      node.vy += (s.H / 2 - node.y) * 0.0005;
      node.vx *= 0.92;
      node.vy *= 0.92;
      node.x += node.vx;
      node.y += node.vy;
    });
  }

  function toScreen(x, y) {
    const s = topology2DStates.get(canvas);
    return { x: s.W / 2 + (x - s.W / 2 + s.panX) * s.scale, y: s.H / 2 + (y - s.H / 2 + s.panY) * s.scale };
  }
  function fromScreen(sx, sy) {
    const s = topology2DStates.get(canvas);
    return { x: (sx - s.W / 2) / s.scale + s.W / 2 - s.panX, y: (sy - s.H / 2) / s.scale + s.H / 2 - s.panY };
  }

  function draw() {
    const s = topology2DStates.get(canvas);
    if (!s) return;
    const { W: w, H: h } = s;
    ctx.fillStyle = '#05070a';
    ctx.fillRect(0, 0, w, h);

    // 背景网格
    ctx.strokeStyle = 'rgba(102,252,241,0.04)';
    ctx.lineWidth = 1;
    for (let x = 0; x < w; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
    for (let y = 0; y < h; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }

    const maxStr = s.edges.reduce((mx, x) => { const a = Math.abs(x.strength); return a > mx ? a : mx; }, 1e-6);
    const focused = (s.focusedNodeId && s.nodeMap) ? s.nodeMap.get(s.focusedNodeId) : null;
    const neighborSet = new Set();
    if (focused) {
      neighborSet.add(focused.id);
      s.edges.forEach(e => {
        if (e.source === focused) neighborSet.add(e.target.id);
        if (e.target === focused) neighborSet.add(e.source.id);
      });
    }

    // 边：按强度分三级可视化，避免"全是箭头"的杂乱感
    s.edges.forEach(e => {
      const a = toScreen(e.source.x, e.source.y);
      const b = toScreen(e.target.x, e.target.y);
      const intensity = Math.min(Math.abs(e.strength) / maxStr, 1);
      const isDimmed = focused && !(neighborSet.has(e.source.id) && neighborSet.has(e.target.id));
      const baseAlpha = isDimmed ? 0.12 : (0.28 + intensity * 0.52);

      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';

      // 弱边：虚线、无箭头；中边：实线+小箭头；强边：实线粗线+大箭头+发光
      // 粗细差异收束，避免过粗破坏氛围；颜色按温度渐变
      let lineWidth, arrowSize, arrowThreshold, glowBlur;
      if (intensity < 0.35) {
        ctx.setLineDash([3 * s.scale, 3 * s.scale]);
        lineWidth = (0.65 + intensity * 0.65) * s.scale;
        arrowSize = 0;
        arrowThreshold = -1;
        glowBlur = 0;
      } else if (intensity < 0.7) {
        ctx.setLineDash([]);
        lineWidth = (1.0 + intensity * 0.9) * s.scale;
        arrowSize = (2 + intensity * 2) * s.scale;
        arrowThreshold = 0.5;
        glowBlur = 0;
      } else {
        ctx.setLineDash([]);
        lineWidth = (1.4 + intensity * 1.1) * s.scale;
        arrowSize = (3 + intensity * 3) * s.scale;
        arrowThreshold = 0.5;
        glowBlur = isDimmed ? 0 : (3 + intensity * 5);
      }

      ctx.strokeStyle = edgeTempColor(e.strength, intensity, baseAlpha);
      ctx.lineWidth = lineWidth;
      if (glowBlur > 0) {
        ctx.shadowBlur = glowBlur;
        ctx.shadowColor = edgeTempColor(e.strength, intensity, 0.45);
      }

      // 曲线控制点：互惠边反向弯曲，减少重叠；弯曲度与距离成正比
      let cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
      if (e.curve !== 0) {
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const nx = -dy / dist, ny = dx / dist;
        const offset = Math.min(dist * 0.22, 60 * s.scale) * e.curve;
        cx += nx * offset;
        cy += ny * offset;
      }
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(cx, cy, b.x, b.y); ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.setLineDash([]);

      // 箭头：仅中强边且未被聚焦淡化时绘制；沿曲线切线方向
      if (!isDimmed && intensity > arrowThreshold && arrowSize > 0) {
        const t = 0.58;
        const ax = (1 - t) * (1 - t) * a.x + 2 * (1 - t) * t * cx + t * t * b.x;
        const ay = (1 - t) * (1 - t) * a.y + 2 * (1 - t) * t * cy + t * t * b.y;
        // 切线方向：对二次贝塞尔 Q(t) 求导 = 2(1-t)(P1-P0) + 2t(P2-P1)
        const tx = 2 * (1 - t) * (cx - a.x) + 2 * t * (b.x - cx);
        const ty = 2 * (1 - t) * (cy - a.y) + 2 * t * (b.y - cy);
        const angle = Math.atan2(ty, tx);
        ctx.fillStyle = edgeTempColor(e.strength, intensity, 0.75 + intensity * 0.2);
        ctx.beginPath();
        ctx.moveTo(ax + Math.cos(angle) * arrowSize, ay + Math.sin(angle) * arrowSize);
        ctx.lineTo(ax + Math.cos(angle + 2.5) * arrowSize * 0.75, ay + Math.sin(angle + 2.5) * arrowSize * 0.75);
        ctx.lineTo(ax + Math.cos(angle - 2.5) * arrowSize * 0.75, ay + Math.sin(angle - 2.5) * arrowSize * 0.75);
        ctx.closePath(); ctx.fill();
      }
    });

    // 节点
    s.nodes.forEach(node => {
      const p = toScreen(node.x, node.y);
      const isFocused = focused && focused.id === node.id;
      const isNeighbor = focused && neighborSet.has(node.id) && focused.id !== node.id;
      const isDimmed = focused && !neighborSet.has(node.id);
      const baseRadius = Number(node.radius) || 6;
      const radius = baseRadius * s.scale * (isFocused ? 1.3 : 1.0);

      // 防御性检查：避免 NaN/Infinity 导致 createRadialGradient 报错
      if (!Number.isFinite(p.x) || !Number.isFinite(p.y) || !Number.isFinite(radius) || radius <= 0) return;

      ctx.shadowBlur = isFocused ? 20 : (isNeighbor ? 12 : 6);
      ctx.shadowColor = isFocused ? 'rgba(255,159,67,0.7)' : (isNeighbor ? 'rgba(0,217,163,0.5)' : 'rgba(0,217,163,0.3)');
      const nodeGrad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, radius);
      nodeGrad.addColorStop(0, isFocused ? 'rgba(255,200,120,1)' : (isNeighbor ? 'rgba(120,255,200,0.95)' : 'rgba(120,255,200,0.8)'));
      nodeGrad.addColorStop(1, isFocused ? 'rgba(255,159,67,0.5)' : (isNeighbor ? 'rgba(0,217,163,0.55)' : 'rgba(0,180,135,0.25)'));
      ctx.globalAlpha = isDimmed ? 0.25 : 1.0;
      ctx.fillStyle = nodeGrad;
      ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = isFocused ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,0.4)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.shadowBlur = 0;

      // 标签
      // P2 修复：Canvas ctx.font 不解析 CSS 变量，需用实际字体名（取自 tokusatsu.css --font-mono）
      ctx.font = `${Math.max(10, 11 * s.scale)}px "JetBrains Mono", "Fira Code", "Consolas", "SF Mono", monospace`;
      const tw = ctx.measureText(node.id).width;
      const labelBg = isFocused ? 'rgba(255,159,67,0.15)' : 'rgba(10,16,24,0.7)';
      ctx.fillStyle = labelBg;
      ctx.fillRect(p.x + radius + 3, p.y - 7, tw + 5, 14);
      ctx.fillStyle = isFocused ? 'rgba(255,220,160,1)' : 'rgba(210,230,245,0.9)';
      ctx.fillText(node.id, p.x + radius + 5, p.y + 3);
      ctx.globalAlpha = 1.0;
    });

    // HUD（两行：操作提示 + 图例状态，避免单行过长重叠）
    const hudH = 40;
    ctx.fillStyle = 'rgba(5,10,16,0.75)';
    ctx.fillRect(0, h - hudH, w, hudH);
    ctx.font = '10px monospace';
    const focusText = focused ? ` · 聚焦: ${focused.id}` : '';
    ctx.fillStyle = 'rgba(148,163,184,0.85)';
    ctx.fillText(`◈ 2D NETWORK  n=${s.nodes.length} e=${s.edges.length}${focusText}  ·  拖拽节点 · 滚轮缩放 · 点击高亮邻居`, 8, h - 26);
    ctx.fillStyle = 'rgba(148,163,184,0.7)';
    ctx.fillText('─强边  - -弱边  →方向  色温=强度  ▲正因果  ▼负因果', 8, h - 10);
  }

  function animate() {
    const s = topology2DStates.get(canvas);
    if (!s) return;
    step();
    if (s.alpha < 1) s.alpha += 0.05;
    draw();
    s.rafId = requestAnimationFrame(animate);
  }

  // 事件绑定
  if (!canvas._topo2DBound) {
    canvas._topo2DBound = true;
    canvas.addEventListener('mousedown', e => {
      const s = topology2DStates.get(canvas);
      if (!s) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const world = fromScreen(mx, my);
      // 查找最近节点
      let nearest = null, minD = Infinity;
      s.nodes.forEach(node => {
        const dx = node.x - world.x, dy = node.y - world.y;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < node.radius + 8 && d < minD) { minD = d; nearest = node; }
      });
      if (nearest) {
        s.draggingNode = nearest;
      } else {
        s.draggingCanvas = true;
        s.lastX = mx; s.lastY = my;
      }
    });
    canvas.addEventListener('mousemove', e => {
      const s = topology2DStates.get(canvas);
      if (!s) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const world = fromScreen(mx, my);
      if (s.draggingNode) {
        s.draggingNode.x = world.x;
        s.draggingNode.y = world.y;
        s.draggingNode.vx = 0; s.draggingNode.vy = 0;
      } else if (s.draggingCanvas) {
        s.panX += (mx - s.lastX) / s.scale;
        s.panY += (my - s.lastY) / s.scale;
        s.lastX = mx; s.lastY = my;
      }
      // hover
      let nearest = null, minD = Infinity;
      s.nodes.forEach(node => {
        const dx = node.x - world.x, dy = node.y - world.y;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < node.radius + 8 && d < minD) { minD = d; nearest = node; }
      });
      s.hoveredNode = nearest;
      canvas.style.cursor = nearest ? 'pointer' : (s.draggingCanvas ? 'grabbing' : 'default');
    });
    window.addEventListener('mouseup', () => {
      const s = topology2DStates.get(canvas);
      if (s) { s.draggingNode = null; s.draggingCanvas = false; }
    });
    canvas.addEventListener('click', e => {
      const s = topology2DStates.get(canvas);
      if (!s) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const world = fromScreen(mx, my);
      let nearest = null, minD = Infinity;
      s.nodes.forEach(node => {
        const dx = node.x - world.x, dy = node.y - world.y;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < node.radius + 8 && d < minD) { minD = d; nearest = node; }
      });
      if (nearest) {
        s.focusedNodeId = s.focusedNodeId === nearest.id ? null : nearest.id;
      }
    });
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const s = topology2DStates.get(canvas);
      if (!s) return;
      const factor = e.deltaY > 0 ? 0.9 : 1.1;
      s.scale *= factor;
      s.scale = Math.max(0.2, Math.min(5.0, s.scale));
    }, { passive: false });
  }

  if (!wrap._topo2DResizeObs) {
    const ro = new ResizeObserver(() => {
      const s = topology2DStates.get(canvas);
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
    wrap._topo2DResizeObs = ro;
  }

    animate();
  } // end init2D

  let { W, H } = resize();
  if (W < 50 || H < 50) {
    // 容器尚未完成布局，延迟一帧重试
    requestAnimationFrame(() => {
      const { W: W2, H: H2 } = resize();
      if (W2 >= 50 && H2 >= 50) init2D(W2, H2);
    });
  } else {
    init2D(W, H);
  }
}
window.renderTopology2D = renderTopology2D;
