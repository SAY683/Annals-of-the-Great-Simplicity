/* js/pathways.js
   Robust pathways script:
   - Renders nodes list and SVG map with foreignObject labels
   - Heuristic placement (right if x<60 else left; avoid top if near top)
   - Click list item opens detail and map click opens link
   - Zoom controls + localStorage progress
*/

document.addEventListener('DOMContentLoaded', () => {
  // ---------- data (customize as needed) ----------
  const nodes = [
    {id:'n1', title:'太易序列 · [名为天国的钥匙].rar', short:'总览包：先浏览全体', desc:'快速浏览压缩包以建立整体印象。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity', tags:['总览'], x:12,y:18},
    {id:'n2', title:'太上洞庭自然经.pdf', short:'核心文本 PDF', desc:'阅读序言与目录，确定章节深入路径。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/blob/main/%E5%A4%AA%E4%B8%8A%E6%B4%9E%E5%AE%BF%E8%87%AA%E7%84%B6%E7%BB%8F.pdf', tags:['核心','PDF'], x:36,y:18},
    {id:'n3', title:'进入 · 现代模式（Miscellanies）', short:'项目化路径', desc:'现代实践、案例、流程化产出。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Miscellanies', tags:['现代','项目'], x:64,y:32},
    {id:'n4', title:'进入 · 炼金术模式（Remarks）', short:'注释/象征路径', desc:'炼金注解与隐喻深读。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Remarks', tags:['炼金','注释'], x:84,y:46},
    {id:'n5', title:'项目 · Miscellanies（实践入口）', short:'现代实践样本', desc:'做微案例并上传 PDF，形成证据。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Miscellanies', tags:['实践'], x:52,y:70},
    {id:'n6', title:'注释 · Remarks（炼金术深读）', short:'炼金注释', desc:'逐章注释并生成独立摘要。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Remarks', tags:['注释','深读'], x:26,y:86},
    {id:'n7', title:'回归 · 打包与支点页', short:'思想包整理', desc:'整理产物并建立支点页以便沉淀引用。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity', tags:['打包'], x:50,y:48}
  ];
  const edges = [['n1','n2'],['n2','n3'],['n3','n4'],['n3','n5'],['n4','n6'],['n5','n7']];

  // ---------- state ----------
  const KEY = 'sayhelp_pathways_v_final';
  let state = { read: {} };
  try { const raw = localStorage.getItem(KEY); if(raw) state = JSON.parse(raw); } catch(e){ state={read:{}}; }

  // ---------- DOM refs ----------
  const wrap = document.getElementById('pathways-root');
  const nodesList = document.getElementById('nodesList');
  const svgMap = document.getElementById('svgMap');
  const detailTitle = document.getElementById('detailTitle');
  const detailDesc  = document.getElementById('detailDesc');
  const detailTags  = document.getElementById('detailTags');
  const progressFill = document.getElementById('progressFill');
  const progressLabel = document.getElementById('progressLabel');

  // ---------- helpers ----------
  function save(){ localStorage.setItem(KEY, JSON.stringify(state)); }
  function pct(){ const t=nodes.length, r=Object.keys(state.read).filter(k=>state.read[k]).length; return {r,t,pc: Math.round((r/t)*100)}; }

  // ---------- render list ----------
  function renderList(){
    nodesList.innerHTML = '';
    nodes.forEach(n=>{
      const a = document.createElement('a');
      a.className = 'node';
      a.href = '#';
      a.dataset.id = n.id;
      a.innerHTML = `<h3><span>${n.title}</span><span class="small">${n.short}</span></h3><p>${n.desc}</p>`;
      if(state.read[n.id]) a.classList.add('read');
      // click selects
      a.addEventListener('click', (e)=>{ e.preventDefault(); selectNode(n.id); });
      // external mini link appended
      const ext = document.createElement('a');
      ext.textContent = '↗';
      ext.className = 'ext';
      ext.href = n.link;
      ext.target = '_blank';
      ext.rel = 'noopener noreferrer';
      ext.title = '在新标签打开';
      a.querySelector('h3').appendChild(ext);
      nodesList.appendChild(a);
    });
    updateProgress();
  }

  // ---------- render svg map with foreignObject labels ----------
  let zoom = 1;
  function renderMap(){
    svgMap.innerHTML = '';
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 100 60');
    svg.style.width = '100%';
    svg.style.height = '100%';
    svg.setAttribute('preserveAspectRatio','xMidYMid meet');

    // draw edges
    edges.forEach(pair=>{
      const a = nodes.find(n=>n.id===pair[0]); const b = nodes.find(n=>n.id===pair[1]);
      if(!a||!b) return;
      const line = document.createElementNS(ns,'line');
      line.setAttribute('x1', a.x); line.setAttribute('y1', a.y/1.2);
      line.setAttribute('x2', b.x); line.setAttribute('y2', b.y/1.2);
      line.setAttribute('stroke','rgba(110,161,200,0.14)');
      line.setAttribute('stroke-width','0.7');
      svg.appendChild(line);
    });

    // group for nodes
    nodes.forEach(n=>{
      const g = document.createElementNS(ns,'g');
      g.setAttribute('data-id', n.id);

      // circle
      const circle = document.createElementNS(ns,'circle');
      const r = 2.8;
      circle.setAttribute('cx', n.x);
      circle.setAttribute('cy', n.y/1.2);
      circle.setAttribute('r', r);
      circle.setAttribute('fill', state.read[n.id] ? '#6ea1c8' : '#1e6f9a');
      circle.style.cursor = 'pointer';
      circle.onclick = ()=> { window.open(n.link, '_blank'); };
      g.appendChild(circle);

      // label via foreignObject
      const fo = document.createElementNS(ns,'foreignObject');
      const labelWidth = 30; // viewBox units
      // decide side: right if x<55 else left
      const side = (n.x < 55) ? 'right' : 'left';
      const foX = side === 'right' ? n.x + r + 1.4 : n.x - labelWidth - r - 1.4;
      const foY = n.y/1.2 - 2.2; // baseline
      fo.setAttribute('x', foX);
      fo.setAttribute('y', foY);
      fo.setAttribute('width', String(labelWidth));
      fo.setAttribute('height', '8'); // enough to contain two lines
      fo.setAttribute('class', 'label-outer');

      // inner HTML (div.labelbox)
      const div = document.createElement('div');
      div.setAttribute('xmlns','http://www.w3.org/1999/xhtml');
      div.className = 'labelbox';
      div.style.maxWidth = '100%';
      div.style.overflow = 'hidden';
      div.style.display = 'inline-block';
      div.innerHTML = `<div style="font-weight:600;">${escapeHtml(n.title)}</div>
                       <div style="font-size:13px;margin-top:4px;opacity:0.95;">${escapeHtml(n.short)}</div>`;

      fo.appendChild(div);
      g.appendChild(fo);
      svg.appendChild(g);
    });

    svgMap.appendChild(svg);

    // after appended, do a light overlap reduction: if labels overlap vertically for same side, nudge down
    reduceOverlaps(svg);
    // ensure labels' text color matches container color
    const color = getComputedStyle(wrap || document.body).color;
    svg.querySelectorAll('.labelbox').forEach(d=> d.style.color = color);
  }

  function escapeHtml(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  // simple post-process to nudge overlapping foreignObjects down slightly
  function reduceOverlaps(svg){
    const boxes = [];
    // collect all fo bounding rects in SVG coordinate space using getBoundingClientRect mapping back
    const svgbcr = svg.getBoundingClientRect();
    svg.querySelectorAll('foreignObject').forEach(fo=>{
      const rect = fo.getBoundingClientRect();
      // compute relative to svg viewBox units
      const x = (rect.left - svgbcr.left)/svgbcr.width * 100;
      const y = (rect.top - svgbcr.top)/svgbcr.height * 60;
      const w = rect.width / svgbcr.width * 100;
      const h = rect.height / svgbcr.height * 60;
      boxes.push({fo, x, y, w, h});
    });

    // naive pairwise nudge
    for(let i=0;i<boxes.length;i++){
      for(let j=i+1;j<boxes.length;j++){
        const a = boxes[i], b = boxes[j];
        if(rectsOverlap(a,b)){
          // nudge the lower one downward a little (in viewBox units)
          if(a.y <= b.y) {
            b.y += (a.h*0.6);
            b.fo.setAttribute('y', String(parseFloat(b.fo.getAttribute('y')) + (b.h/60*svgbcr.height*0.6)/svgbcr.height*60)); // best-effort adjust
          } else {
            a.y += (b.h*0.6);
            a.fo.setAttribute('y', String(parseFloat(a.fo.getAttribute('y')) + (a.h/60*svgbcr.height*0.6)/svgbcr.height*60));
          }
        }
      }
    }
    // note: this is a gentle nudge heuristic for most common crowding
  }

  function rectsOverlap(a,b){
    return !( (a.x + a.w) < b.x || a.x > (b.x + b.w) || (a.y + a.h) < b.y || a.y > (b.y + b.h) );
  }

  // ---------- select node (detail) ----------
  let current = null;
  function selectNode(id){
    current = id;
    document.querySelectorAll('#nodesList .node').forEach(el=> el.classList.toggle('active', el.dataset.id === id));
    const n = nodes.find(x=>x.id===id);
    if(!n) return;
    detailTitle.textContent = n.title;
    detailDesc.textContent = n.desc;
    detailTags.innerHTML = '';
    n.tags.forEach(t=>{
      const s = document.createElement('span'); s.className='tag'; s.textContent = t; detailTags.appendChild(s);
    });
    document.getElementById('openLink').onclick = ()=> window.open(n.link, '_blank');
    document.getElementById('markRead').onclick = ()=>{ state.read[n.id]=true; save(); renderList(); renderMap(); selectNode(n.id); };
    document.getElementById('nextBtn').onclick = ()=> { const idx = nodes.findIndex(x=>x.id===id); if(idx < nodes.length-1) selectNode(nodes[idx+1].id); else alert('已达末端'); };
  }

  // ---------- controls ----------
  document.getElementById('markAll').addEventListener('click', ()=>{
    nodes.forEach(n=> state.read[n.id]=true); save(); renderList(); renderMap();
  });
  document.getElementById('resetAll').addEventListener('click', ()=>{
    state.read = {}; save(); renderList(); renderMap();
  });
  document.getElementById('exportProgress').addEventListener('click', ()=>{
    const blob = new Blob([JSON.stringify(state, null, 2)], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href=url; a.download='pathways-progress.json'; a.click(); URL.revokeObjectURL(url);
  });

  // zoom toolbar
  const zoomIn = document.getElementById('zoomIn'), zoomOut = document.getElementById('zoomOut'), zoomReset = document.getElementById('zoomReset');
  if(zoomIn) zoomIn.addEventListener('click', ()=>{ zoom = Math.min(1.6, zoom*1.12); renderMap(); });
  if(zoomOut) zoomOut.addEventListener('click', ()=>{ zoom = Math.max(0.8, zoom/1.12); renderMap(); });
  if(zoomReset) zoomReset.addEventListener('click', ()=>{ zoom = 1; renderMap(); });

  // ---------- initial render ----------
  renderList();
  renderMap();
  // select first as default
  if(nodes.length) selectNode(nodes[0].id);
  // update progress area
  (function upd(){ const p=pct(); progressFill.style.width = p.pc + '%'; progressLabel.textContent = `已读 ${p.r} / ${p.t}`; })();

  // reflow on resize
  window.addEventListener('resize', ()=> { renderMap(); });

});
