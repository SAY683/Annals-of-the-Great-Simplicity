/* js/pathways.js (updated)
   - improves label placement (simple collision avoidance)
   - detects light background and toggles .light-mode on .pathway-wrap
   - groups circle+label together to avoid label orphaning
*/

document.addEventListener('DOMContentLoaded', function () {

  const nodes = [
    {id:'n1', title:'太易序列 · [名为天国的钥匙].rar', short:'站点起点：整卷打包（总览）',
      desc:'下载/参阅打包文档（总体序列）。建议：先快速浏览形成整体印象。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity', tags:['总览','仓库'], x:12,y:18},
    {id:'n2', title:'太上洞庭自然经.pdf', short:'主文档（核心文本）',
      desc:'阅读此 PDF 序言与目录，作为理解整体语境的关键文本。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/blob/main/%E5%A4%AA%E4%B8%8A%E6%B4%9E%E5%AE%BF%E8%87%AA%E7%84%B6%E7%BB%8F.pdf', tags:['核心','PDF'], x:36,y:18},
    {id:'n3', title:'进入 · 现代模式（Miscellanies）', short:'现代/项目化 → Miscellanies',
      desc:'现代模式聚焦项目实操、案例与流程化产出。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Miscellanies', tags:['现代','项目'], x:64,y:32},
    {id:'n4', title:'进入 · 炼金术模式（Remarks）', short:'隐秘/炼金/象征 → Remarks',
      desc:'炼金术模式偏重注释、隐喻与文本注解。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Remarks', tags:['炼金','注释'], x:84,y:46},
    {id:'n5', title:'项目·Miscellanies（实践入口）', short:'现代实践样本',
      desc:'挑一项做微案例并上传 PDF，形成可引用证据。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Miscellanies', tags:['实践','案例'], x:52,y:70},
    {id:'n6', title:'注释·Remarks（炼金术深读）', short:'炼金注释与笔记',
      desc:'按章节做“解读—注释—写作”循环，生成独立摘要。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Remarks', tags:['注释','深读'], x:26,y:86},
    {id:'n7', title:'回归 · 打包与支点页', short:'把产物打包为思想包',
      desc:'把 PDF、注释、案例整理并建立支点页（Pillar Page）。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity', tags:['打包','沉淀'], x:50,y:48}
  ];

  const STORAGE_KEY = 'sayhelp_pathways_v1';
  let state = { read: {} };

  function loadState(){
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if(raw) state = JSON.parse(raw);
    } catch(e){ state = { read: {} }; }
  }
  function saveState(){ localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }

  const nodesList = document.getElementById('nodesList');
  const svgMap = document.getElementById('svgMap');
  const detailTitle = document.getElementById('detailTitle');
  const detailDesc = document.getElementById('detailDesc');
  const detailTags = document.getElementById('detailTags');
  const progressFill = document.getElementById('progressFill');
  const progressLabel = document.getElementById('progressLabel');

  // render list
  function renderList(){
    nodesList.innerHTML = '';
    nodes.forEach(n=>{
      const el = document.createElement('div');
      el.className = 'node' + (state.read[n.id] ? ' read' : '');
      el.setAttribute('data-id', n.id);
      el.innerHTML = '<h3><span>'+ n.title +'</span><span class="small">'+ n.short +'</span></h3><p>'+ (n.short) +'</p>';
      el.onclick = ()=>selectNode(n.id);
      if(state.read[n.id]) el.style.opacity = 0.7;
      nodesList.appendChild(el);
    });
    updateProgress();
  }

  // helper: create svg with nodes and labels, then run simple collision avoidance
  function renderMap(){
    const ns = 'http://www.w3.org/2000/svg';
    svgMap.innerHTML = '';
    const svg = document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 100 60');
    svg.setAttribute('preserveAspectRatio','xMidYMid meet');
    svg.style.width='100%';
    svg.style.height='100%';

    // draw edges
    const edges = [['n1','n2'],['n2','n3'],['n3','n4'],['n3','n5'],['n4','n6'],['n5','n7']];
    edges.forEach(e=>{
      const a = nodes.find(x=>x.id===e[0]); const b = nodes.find(x=>x.id===e[1]);
      if(!a||!b) return;
      const line = document.createElementNS(ns,'line');
      line.setAttribute('x1', a.x); line.setAttribute('y1', a.y/1.2);
      line.setAttribute('x2', b.x); line.setAttribute('y2', b.y/1.2);
      line.setAttribute('stroke', 'rgba(110,161,200,0.14)');
      line.setAttribute('stroke-width', '0.7');
      svg.appendChild(line);
    });

    // create groups with circle+text (text initially placed, then we'll adjust to avoid overlap)
    const labelNodes = [];
    nodes.forEach(n=>{
      const g = document.createElementNS(ns,'g');
      g.setAttribute('data-id', n.id);
      // Circle
      const cx = n.x, cy = n.y/1.2;
      const circle = document.createElementNS(ns,'circle');
      circle.setAttribute('cx', cx);
      circle.setAttribute('cy', cy);
      circle.setAttribute('r', 2.6);
      circle.setAttribute('fill', state.read[n.id] ? '#6ea1c8' : '#1e6f9a');
      circle.setAttribute('stroke','rgba(255,255,255,0.04)');
      circle.style.cursor='pointer';
      circle.onclick = ()=>selectNode(n.id);
      g.appendChild(circle);

      // Text label (placed to the right initially)
      const text = document.createElementNS(ns,'text');
      const labelX = cx + 3.2;
      const labelY = cy + 0.8;
      text.setAttribute('x', labelX);
      text.setAttribute('y', labelY);
      text.setAttribute('font-size','2.2');
      text.setAttribute('fill','currentColor');
      text.textContent = n.title;
      text.style.pointerEvents = 'none';
      g.appendChild(text);

      svg.appendChild(g);
      labelNodes.push({el:text, cx:labelX, cy:labelY, g: g});
    });

    svgMap.appendChild(svg);

    // collision avoidance: if two labels overlap vertically or horizontally, shift the later one downwards
    // Note: need to wait a moment for browser to compute bbox
    setTimeout(()=>{
      const placed = [];
      labelNodes.forEach(item=>{
        const box = item.el.getBBox();
        // convert box to pixel relative to svg viewBox units (we're already in viewBox coords)
        let x0 = box.x, y0 = box.y, x1 = box.x + box.width, y1 = box.y + box.height;
        // try to nudge downward until no intersection with any placed label
        let attempts = 0;
        while(placed.some(p => !(x1 < p.x0 || x0 > p.x1 || y1 < p.y0 || y0 > p.y1)) && attempts < 12) {
          // move down by box.height + 0.8 (viewBox units)
          const dy = box.height + 0.9;
          const newY = parseFloat(item.el.getAttribute('y')) + dy;
          item.el.setAttribute('y', newY.toString());
          // update coordinates
          const nb = item.el.getBBox();
          x0 = nb.x; y0 = nb.y; x1 = nb.x + nb.width; y1 = nb.y + nb.height;
          attempts++;
        }
        placed.push({x0,y0,x1,y1, el:item.el});
      });
      // final style tweak: if label falls outside bottom, pull it up to fit
      const svgBox = svg.viewBox.baseVal;
      placed.forEach(p=>{
        if(p.y1 > svgBox.height - 2) {
          const shiftUp = p.y1 - (svgBox.height - 2);
          const currY = parseFloat(p.el.getAttribute('y'));
          p.el.setAttribute('y', (currY - shiftUp).toString());
        }
      });
    }, 40);
  }

  // selection logic similar to previous
  let currentId = null;
  function selectNode(id){
    const n = nodes.find(x=>x.id===id); if(!n) return;
    currentId = id;
    document.querySelectorAll('.node').forEach(el=> el.classList.toggle('active', el.dataset.id === id));
    // recolor svg circles and adjust radii
    document.querySelectorAll('#svgMap svg g').forEach(g=>{
      const gid = g.getAttribute('data-id');
      const circle = g.querySelector('circle');
      if(!circle) return;
      if(gid === id) {
        circle.setAttribute('fill','#8fc1e6'); circle.setAttribute('r',3.6);
      } else {
        circle.setAttribute('fill', (state.read[gid] ? '#6ea1c8' : '#1e6f9a'));
        circle.setAttribute('r',2.6);
      }
    });

    detailTitle.textContent = n.title;
    detailDesc.textContent = n.desc;
    detailTags.innerHTML = '';
    n.tags.forEach(t=>{ const s=document.createElement('span'); s.className='tag'; s.textContent=t; detailTags.appendChild(s); });

    document.getElementById('openLink').onclick = ()=>{ window.open(n.link,'_blank'); };
    document.getElementById('markRead').onclick = ()=>{ state.read[n.id]=true; saveState(); renderList(); renderMap(); selectNode(n.id); };
    document.getElementById('nextBtn').onclick = ()=>{ goNext(n.id); };
  }

  function goNext(id){
    const idx = nodes.findIndex(n=>n.id===id);
    if(idx >= 0 && idx < nodes.length-1){
      selectNode(nodes[idx+1].id);
      const el = document.querySelector('.node[data-id="'+nodes[idx+1].id+'"]');
      if(el) el.scrollIntoView({behavior:'smooth', block:'center'});
    } else {
      alert('已达路径末端。');
    }
  }

  function updateProgress(){
    const total = nodes.length;
    const readCount = Object.keys(state.read).filter(k=>state.read[k]).length;
    const pct = Math.round((readCount/total)*100);
    progressFill.style.width = pct + '%';
    progressLabel.textContent = `已读 ${readCount} / ${total}`;
  }

  document.getElementById('markAll').onclick = ()=>{ nodes.forEach(n=> state.read[n.id]=true); saveState(); renderList(); renderMap(); };
  document.getElementById('resetAll').onclick = ()=>{ state.read = {}; saveState(); renderList(); renderMap(); };
  document.getElementById('exportProgress').onclick = ()=>{
    const data = JSON.stringify(state, null, 2);
    const blob = new Blob([data], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'pathways-progress.json'; a.click();
    URL.revokeObjectURL(url);
  };

  // initial
  loadState();
  renderList();
  renderMap();

  // open hash
  if(location.hash){
    const id = location.hash.replace('#','');
    if(nodes.some(n=>n.id===id)) selectNode(id);
  }

  // --- detect background brightness and toggle light-mode if needed ---
  (function detectBackground(){
    try {
      const wrap = document.querySelector('.pathway-wrap');
      if(!wrap) return;
      const cs = getComputedStyle(wrap);
      const bg = cs.backgroundColor || cs.background;
      // parse rgb(a) like "rgb(255, 255, 255)" or "rgba(..." ; fallback to dark if can't parse
      const m = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      if(m){
        const r = +m[1], g = +m[2], b = +m[3];
        // luminance (0..1)
        const lum = (0.2126*r + 0.7152*g + 0.0722*b) / 255;
        if(lum > 0.7) {
          wrap.classList.add('light-mode');
        } else {
          wrap.classList.remove('light-mode');
        }
      }
    } catch(e){}
  })();

  // expose
  window._pathways = { nodes, state, saveState, selectNode };

});
