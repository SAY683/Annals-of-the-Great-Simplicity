/* pathways.js v2 — typography scale + label wrap + collision + zoom */
document.addEventListener('DOMContentLoaded', () => {

  // ===== Data =====
  const nodes = [
    {id:'n1', title:'太易序列 · [名为天国的钥匙].rar', short:'站点起点：整卷打包（总览）',
      desc:'下载/参阅打包文档（总体序列）。建议先快速浏览形成整体印象。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity', tags:['总览','仓库'], x:12,y:18, lvl:3},
    {id:'n2', title:'太上洞庭自然经.pdf', short:'主文档（核心文本）',
      desc:'阅读此 PDF 序言与目录，作为理解整体语境的关键文本。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/blob/main/%E5%A4%AA%E4%B8%8A%E6%B4%9E%E5%AE%BF%E8%87%AA%E7%84%B6%E7%BB%8F.pdf', tags:['核心','PDF'], x:36,y:18, lvl:3},
    {id:'n3', title:'进入 · 现代模式（Miscellanies）', short:'现代/项目化 → Miscellanies',
      desc:'现代模式聚焦项目实操、案例与流程化产出。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Miscellanies', tags:['现代','项目'], x:64,y:32, lvl:2},
    {id:'n4', title:'进入 · 炼金术模式（Remarks）', short:'隐秘/炼金/象征 → Remarks',
      desc:'炼金术模式偏重注释、隐喻与文本注解。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Remarks', tags:['炼金','注释'], x:84,y:46, lvl:2},
    {id:'n5', title:'项目·Miscellanies（实践入口）', short:'现代实践样本',
      desc:'挑一项做微案例并上传 PDF，形成可引用证据。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Miscellanies', tags:['实践','案例'], x:52,y:70, lvl:1},
    {id:'n6', title:'注释·Remarks（炼金术深读）', short:'炼金注释与笔记',
      desc:'按章节做“解读—注释—写作”循环，生成独立摘要。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Remarks', tags:['注释','深读'], x:26,y:86, lvl:1},
    {id:'n7', title:'回归 · 打包与支点页', short:'把产物打包为思想包',
      desc:'把 PDF、注释、案例整理并建立支点页（Pillar Page）。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity', tags:['打包','沉淀'], x:50,y:48, lvl:2}
  ];
  const edges = [['n1','n2'],['n2','n3'],['n3','n4'],['n3','n5'],['n4','n6'],['n5','n7']];

  // ===== State =====
  const STORAGE_KEY = 'sayhelp_pathways_v2';
  let state = { read: {} };
  try { const raw = localStorage.getItem(STORAGE_KEY); if(raw) state = JSON.parse(raw); } catch(e){}

  // ===== DOM =====
  const wrap = document.querySelector('.pathway-wrap');
  const nodesList = document.getElementById('nodesList');
  const svgMap = document.getElementById('svgMap');
  const detailTitle = document.getElementById('detailTitle');
  const detailDesc  = document.getElementById('detailDesc');
  const detailTags  = document.getElementById('detailTags');
  const progressFill= document.getElementById('progressFill');
  const progressLabel=document.getElementById('progressLabel');

  // ===== Theme detect (light/dark) =====
  detectLightMode();

  // ===== Render list =====
  renderList();

  // ===== Render map =====
  renderMap();

  // ===== Hash open =====
  if(location.hash){
    const id = location.hash.slice(1);
    if(nodes.some(n=>n.id===id)) selectNode(id);
  }

  // ===== Bind Toolbar =====
  bindToolbar();

  // ================== Functions ==================

  function saveState(){ localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }

  function renderList(){
    nodesList.innerHTML = '';
    nodes.forEach(n=>{
      const el = document.createElement('div');
      el.className = 'node' + (state.read[n.id] ? ' read' : '');
      el.dataset.id = n.id;
      el.innerHTML = `<h3><span>${n.title}</span><span class="small">${n.short}</span></h3><p>${n.short}</p>`;
      el.onclick = ()=>selectNode(n.id);
      if(state.read[n.id]) el.style.opacity = 0.8;
      nodesList.appendChild(el);
    });
    updateProgress();
  }

  function detectLightMode(){
    const manual = wrap.getAttribute('data-theme');
    if(manual === 'light'){ wrap.classList.add('light-mode'); return; }
    if(manual === 'dark'){  wrap.classList.remove('light-mode'); return; }
    // auto
    let el = wrap, c = null;
    while(el && el !== document.documentElement){
      const cs = getComputedStyle(el);
      const m = (cs.backgroundColor||'').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      if(m){ c = {r:+m[1],g:+m[2],b:+m[3]}; break; }
      el = el.parentElement;
    }
    const lum = c ? (0.2126*c.r + 0.7152*c.g + 0.0722*c.b)/255 : 1;
    if(lum > 0.65) wrap.classList.add('light-mode'); else wrap.classList.remove('light-mode');
  }

  function updateProgress(){
    const total = nodes.length;
    const readCount = Object.keys(state.read).filter(k=>state.read[k]).length;
    const pct = Math.round(readCount/total*100);
    progressFill.style.width = pct + '%';
    progressLabel.textContent = `已读 ${readCount} / ${total}`;
  }

  function bindToolbar(){
    const zi = document.getElementById('zoomIn');
    const zo = document.getElementById('zoomOut');
    const zr = document.getElementById('zoomReset');
    if(!zi || !zo || !zr) return;
    zi.onclick = ()=> setZoom(zoom*1.12);
    zo.onclick = ()=> setZoom(zoom/1.12);
    zr.onclick = ()=> setZoom(1);
    window.addEventListener('resize', ()=> { renderMap(); });
  }

  // ===== SVG render with wrapping, collision, zoom =====
  const VIEW_W = 100, VIEW_H = 60;
  let zoom = 1;

  function setZoom(z){
    zoom = Math.max(0.8, Math.min(1.8, z));
    // 重新渲染（字体/布局跟随）
    renderMap();
  }

  function currentFontVU(){
    const w = svgMap.clientWidth || 800;
    // 小屏更大字号，大屏适中
    if(w < 420) return 4.2;
    if(w < 768) return 3.6;
    if(w < 1200) return 3.0;
    return 2.8;
  }

  function renderMap(){
    const ns = 'http://www.w3.org/2000/svg';
    svgMap.innerHTML = '';
    const svg = document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox',`0 0 ${VIEW_W} ${VIEW_H}`);
    svg.style.width='100%'; svg.style.height='100%';

    // defs: soft radial fill
    const defs = document.createElementNS(ns,'defs');
    const grad = document.createElementNS(ns,'radialGradient');
    grad.setAttribute('id','nodeRad');
    grad.innerHTML = `
      <stop offset="0%"  stop-color="#9fd1f0"/>
      <stop offset="70%" stop-color="#5a9bc1"/>
      <stop offset="100%" stop-color="#1e6f9a"/>
    `;
    defs.appendChild(grad);
    svg.appendChild(defs);

    const vp = document.createElementNS(ns,'g');
    vp.setAttribute('id','vp');
    vp.setAttribute('transform', `translate(${(VIEW_W - VIEW_W*zoom)/2} ${(VIEW_H - VIEW_H*zoom)/2}) scale(${zoom})`);
    svg.appendChild(vp);

    // edges
    edges.forEach(([aId,bId])=>{
      const a = nodes.find(x=>x.id===aId), b = nodes.find(x=>x.id===bId);
      if(!a||!b) return;
      const line = document.createElementNS(ns,'line');
      line.setAttribute('x1', a.x); line.setAttribute('y1', a.y/1.2);
      line.setAttribute('x2', b.x); line.setAttribute('y2', b.y/1.2);
      line.setAttribute('stroke', 'rgba(110,161,200,0.18)');
      line.setAttribute('stroke-width', '0.7');
      vp.appendChild(line);
    });

    // nodes + labels
    const placed = []; // label bboxes in view units
    const fontVU = currentFontVU();
    const maxLabelWidthVU = 36; // 允许的最大标签宽度（视图单位）
    const pxPerVU = (svg.clientWidth || 800) / VIEW_W;

    nodes.forEach(n=>{
      const g = document.createElementNS(ns,'g');
      g.setAttribute('data-id', n.id);
      const cx = n.x, cy = n.y/1.2;

      // circle
      const circle = document.createElementNS(ns,'circle');
      const r = n.lvl >= 3 ? 3.8 : (n.lvl === 2 ? 3.2 : 2.8);
      circle.setAttribute('cx', cx);
      circle.setAttribute('cy', cy);
      circle.setAttribute('r', r);
      circle.setAttribute('fill', state.read[n.id] ? 'url(#nodeRad)' : '#1e6f9a');
      circle.style.cursor='pointer';
      circle.onclick = ()=>selectNode(n.id);
      g.appendChild(circle);

      // text + bg
      const text = document.createElementNS(ns,'text');
      text.setAttribute('font-size', String(fontVU));
      text.setAttribute('x', cx + r + 1.8);
      text.setAttribute('y', cy + 0.6);
      text.style.pointerEvents = 'none';
      wrapText(svg, text, n.title, maxLabelWidthVU, pxPerVU, 2);

      const rect = document.createElementNS(ns,'rect');
      rect.setAttribute('class','label-bg');
      g.insertBefore(rect, text);

      // place group first
      vp.appendChild(g);

      // collision resolve (candidate positions)
      const POS = [
        {dx:r+1.8, dy: 0.6},   // E
        {dx:r+1.6, dy:-1.2},   // NE
        {dx:r+1.6, dy: 2.4},   // SE
        {dx:-r-1.8, dy: 0.6, align:'end'}, // W
        {dx:-r-1.6, dy:-1.2, align:'end'}, // NW
        {dx:-r-1.6, dy: 2.4, align:'end'}, // SW
        {dx:0, dy:-r-3.0, align:'middle'}, // N
        {dx:0, dy:r+4.0,  align:'middle'}  // S
      ];

      let bbox = getTextBBox(text);
      function applyRect(){
        const b = getTextBBox(text);
        const pad = 0.8;
        rect.setAttribute('x', (b.x - pad)); rect.setAttribute('y', (b.y - pad));
        rect.setAttribute('width', (b.width + pad*2)); rect.setAttribute('height', (b.height + pad*2));
      }

      let placedOK = false;
      for(const p of POS){
        setTextPos(text, cx + p.dx, cy + p.dy, p.align);
        bbox = getTextBBox(text);
        if(!overlaps(bbox, placed)){ placed.push(bbox); placedOK = true; break; }
      }
      if(!placedOK){
        // gentle push down
        let tries=0;
        while(overlaps(bbox, placed) && tries<16){
          shiftText(text, 0, bbox.height*0.6);
          bbox = getTextBBox(text); tries++;
        }
        placed.push(bbox);
      }
      applyRect();
    });

    svgMap.appendChild(svg);

    // ensure fill equals container color (某些浏览器对 currentColor 继承不一致)
    const color = getComputedStyle(wrap || document.body).color;
    svg.querySelectorAll('text').forEach(t=> t.setAttribute('fill', color));
  }

  function wrapText(svg, textEl, fullText, maxVU, pxPerVU, lines=2){
    // 按中英文分别处理；中文按字切，英文按词切。
    const ns = 'http://www.w3.org/2000/svg';
    textEl.textContent = '';
    const isCJK = /[\u4e00-\u9fff]/.test(fullText);
    const tokens = isCJK ? fullText.split('') : fullText.split(/(\s+)/);
    let line = '';
    let lineCount = 0;

    const anchorX = parseFloat(textEl.getAttribute('x')) || 0;
    const anchorY = parseFloat(textEl.getAttribute('y')) || 0;

    function newTspan(dyEm){
      const t = document.createElementNS(ns,'tspan');
      t.setAttribute('x', String(anchorX));
      if(lineCount===0) t.setAttribute('dy', '0');
      else t.setAttribute('dy', `${dyEm}em`);
      textEl.appendChild(t);
      return t;
    }

    let tspan = newTspan(1.2);
    for(let i=0;i<tokens.length;i++){
      const next = line + tokens[i];
      tspan.textContent = next;
      const px = tspan.getComputedTextLength();
      const maxPx = maxVU * pxPerVU;

      if(px > maxPx){
        if(lineCount === lines-1){
          // 最后一行，做省略
          let base = tspan.textContent || '';
          // 退回到适配省略号
          while(base && tspan.getComputedTextLength() > maxPx - 10) {
            base = base.slice(0, -1);
            tspan.textContent = base;
          }
        tspan.textContent = (tspan.textContent || '') + '…';
          return;
        } else {
          // 换行
          line = isCJK ? tokens[i] : tokens[i].trimStart();
          tspan.textContent = (tspan.textContent || '').trim();
          lineCount++;
          tspan = newTspan(1.25);
          tspan.textContent = line;
        }
      } else {
        line = next;
      }
    }
  }

  function getTextBBox(text){ const b = text.getBBox(); return {x:b.x,y:b.y,width:b.width,height:b.height}; }
  function overlaps(box, list){
    return list.some(p => !( (box.x+box.width) < p.x || box.x > (p.x+p.width) || (box.y+box.height) < p.y || box.y > (p.y+p.height) ));
  }
  function setTextPos(text, x, y, align){
    text.setAttribute('x', String(x));
    text.setAttribute('y', String(y));
    if(align === 'end') text.setAttribute('text-anchor','end');
    else if(align === 'middle') text.setAttribute('text-anchor','middle');
    else text.removeAttribute('text-anchor');
    // 让所有 tspan 的 x 对齐
    text.querySelectorAll('tspan').forEach(t=> t.setAttribute('x', String(x)));
  }
  function shiftText(text, dx, dy){
    const x = parseFloat(text.getAttribute('x')) || 0;
    const y = parseFloat(text.getAttribute('y')) || 0;
    setTextPos(text, x+dx, y+dy);
  }

  // ===== Selection & actions =====
  let currentId = null;
  function selectNode(id){
    const n = nodes.find(x=>x.id===id); if(!n) return;
    currentId = id;
    document.querySelectorAll('.node').forEach(el=> el.classList.toggle('active', el.dataset.id === id));
    document.querySelectorAll('#svgMap svg g').forEach(g=>{
      const gid = g.getAttribute('data-id');
      const circle = g.querySelector('circle');
      if(!circle) return;
      if(gid === id) { circle.setAttribute('fill','#8fc1e6'); circle.setAttribute('r', parseFloat(circle.getAttribute('r')) + 0.8); }
      else {
        const base = nodes.find(nn=>nn.id===gid)?.lvl || 2;
        const r = base >=3 ? 3.8 : (base===2?3.2:2.8);
        circle.setAttribute('fill', (state.read[gid] ? 'url(#nodeRad)' : '#1e6f9a'));
        circle.setAttribute('r', r);
      }
    });
    detailTitle.textContent = n.title;
    detailDesc.textContent  = n.desc;
    detailTags.innerHTML = '';
    n.tags.forEach(t=>{ const s=document.createElement('span'); s.className='tag'; s.textContent=t; detailTags.appendChild(s); });

    document.getElementById('openLink').onclick = ()=> window.open(n.link,'_blank');
    document.getElementById('markRead').onclick = ()=>{ state.read[n.id]=true; saveState(); renderList(); renderMap(); selectNode(n.id); };
    document.getElementById('nextBtn').onclick  = ()=> goNext(n.id);
  }

  function goNext(id){
    const idx = nodes.findIndex(n=>n.id===id);
    if(idx>=0 && idx<nodes.length-1){
      selectNode(nodes[idx+1].id);
      const el = document.querySelector(`.node[data-id="${nodes[idx+1].id}"]`);
      if(el) el.scrollIntoView({behavior:'smooth', block:'center'});
    } else { alert('已达路径末端。'); }
  }

  // ===== Top controls =====
  document.getElementById('markAll').onclick = ()=>{ nodes.forEach(n=> state.read[n.id]=true); saveState(); renderList(); renderMap(); };
  document.getElementById('resetAll').onclick = ()=>{ state.read = {}; saveState(); renderList(); renderMap(); };
  document.getElementById('exportProgress').onclick = ()=>{
    const data = JSON.stringify(state, null, 2);
    const blob = new Blob([data], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'pathways-progress.json'; a.click();
    URL.revokeObjectURL(url);
  };

  // expose debug
  window._pathways = {
    theme(mode){ if(mode==='light'){ wrap.setAttribute('data-theme','light'); wrap.classList.add('light-mode'); }
                 else if(mode==='dark'){ wrap.setAttribute('data-theme','dark'); wrap.classList.remove('light-mode'); }
                 else { wrap.removeAttribute('data-theme'); detectLightMode(); }
                 renderMap(); },
    zoomIn(){ setZoom(zoom*1.12); }, zoomOut(){ setZoom(zoom/1.12); }, zoomReset(){ setZoom(1); }
  };
});
