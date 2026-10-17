function setupTopologyToggle(r, opts) {
  const {
    matrixView, topologyView, topology2DView,
    wrap, canvas, wrap2D, canvas2D,
    toggleBtn, toggle2DBtn,
    pauseBtn, resetBtn, reset2DBtn
  } = opts;
  if (!toggleBtn || !matrixView || !topologyView) return;

  // 视图状态: 'matrix' | '3d' | '2d'
  let viewState = 'matrix';
  topologyView.classList.add('hidden');
  if (topology2DView) topology2DView.classList.add('hidden');
  matrixView.classList.remove('hidden');
  toggleBtn.textContent = '3D 拓扑';
  if (toggle2DBtn) {
    toggle2DBtn.classList.remove('hidden');
    toggle2DBtn.textContent = '2D 网络';
  }

  function showView(state, focusedNodeId = null) {
    viewState = state;
    if (state === 'matrix') {
      matrixView.classList.remove('hidden');
      topologyView.classList.add('hidden');
      if (topology2DView) topology2DView.classList.add('hidden');
      toggleBtn.textContent = '3D 拓扑';
      if (toggle2DBtn) toggle2DBtn.textContent = '2D 网络';
      const s = topologyStates.get(canvas);
      if (s) s.paused = true;
      const s2 = topology2DStates.get(canvas2D);
      if (s2 && s2.rafId) { cancelAnimationFrame(s2.rafId); s2.rafId = null; }
    } else if (state === '3d') {
      matrixView.classList.add('hidden');
      topologyView.classList.remove('hidden');
      if (topology2DView) topology2DView.classList.add('hidden');
      toggleBtn.textContent = '2D 矩阵';
      if (toggle2DBtn) toggle2DBtn.textContent = '2D 网络';
      const s = topologyStates.get(canvas);
      const s2 = topology2DStates.get(canvas2D);
      if (s2 && s2.rafId) { cancelAnimationFrame(s2.rafId); s2.rafId = null; }
      if (!s) {
        renderTopology3D(r, wrap, canvas, pauseBtn, resetBtn);
      } else {
        s.paused = false;
        const rect = wrap.getBoundingClientRect();
        s.W = Math.max(1, rect.width);
        s.H = Math.max(1, rect.height);
        canvas.width = Math.floor(s.W * s.dpr);
        canvas.height = Math.floor(s.H * s.dpr);
        canvas.style.width = s.W + 'px';
        canvas.style.height = s.H + 'px';
        s.ctx.setTransform(s.dpr, 0, 0, s.dpr, 0, 0);
      }
    } else if (state === '2d') {
      matrixView.classList.add('hidden');
      topologyView.classList.add('hidden');
      if (topology2DView) topology2DView.classList.remove('hidden');
      toggleBtn.textContent = '3D 拓扑';
      if (toggle2DBtn) toggle2DBtn.textContent = '2D 矩阵';
      const s = topologyStates.get(canvas);
      if (s) s.paused = true;
      renderTopology2D(r, wrap2D, canvas2D, focusedNodeId);
    }
  }

  if (!toggleBtn._topoToggleBound) {
    toggleBtn._topoToggleBound = true;
    toggleBtn.addEventListener('click', () => {
      if (viewState === 'matrix') showView('3d');
      else if (viewState === '3d') showView('matrix');
      else if (viewState === '2d') showView('3d');
    });
  }
  if (toggle2DBtn && !toggle2DBtn._topo2DToggleBound) {
    toggle2DBtn._topo2DToggleBound = true;
    toggle2DBtn.addEventListener('click', () => {
      if (viewState === 'matrix') showView('2d');
      else if (viewState === '2d') showView('matrix');
      else if (viewState === '3d') showView('2d');
    });
  }
  if (reset2DBtn && !reset2DBtn._topo2DResetBound) {
    reset2DBtn._topo2DResetBound = true;
    reset2DBtn.addEventListener('click', () => {
      const s2 = topology2DStates.get(canvas2D);
      if (s2) {
        s2.scale = 1.0; s2.panX = 0; s2.panY = 0; s2.focusedNodeId = null;
        initPositions2D(s2.nodes, s2.edges, s2.W, s2.H);
      }
    });
  }

  // P0 升级: 3D 拓扑点击节点 → 坍缩到 2D 网络并聚焦该节点
  if (canvas && !canvas._topo3DClickBound) {
    canvas._topo3DClickBound = true;
    canvas.addEventListener('click', e => {
      const s = topologyStates.get(canvas);
      if (!s || viewState !== '3d') return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const dpr = s.dpr;
      // 找到投影后离鼠标最近的节点
      // P2 修复：z 越小表示节点越靠近观察者（project 中 scale = fov*zoom/(fov+z+400)，z 小则 scale 大）。
      // 原代码 minZ=-Infinity + p.z>minZ 选的是 z 最大（最远）的节点，方向反了。
      // 改为 minZ=Infinity + p.z<minZ，选 z 最小（最近、最前）的节点。
      let nearest = null, minZ = Infinity, minD = Infinity;
      const projected = s.nodes.map(n => ({ node: n, ...project(n, s.rotX, s.rotY, s.zoom, s.W, s.H) }));
      projected.forEach(p => {
        const dx = p.x - mx, dy = p.y - my;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < Math.max(12, p.node.radius * Math.max(0.4, p.scale * 0.012)) + 6) {
          // 优先选 z 更近（z 更小 = 更靠前）的节点
          if (nearest === null || p.z < minZ || (p.z === minZ && d < minD)) {
            nearest = p.node; minZ = p.z; minD = d;
          }
        }
      });
      if (nearest) {
        showView('2d', nearest.id);
      }
    });
  }
}
window.setupTopologyToggle = setupTopologyToggle;
