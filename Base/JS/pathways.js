/* js/pathways.js (revised)
   - 背景亮度鲁棒探测（支持 linear-gradient / 逐级祖先）
   - 支持 data-theme="light|dark" 手动覆盖
   - 标签加半透明底板 rect，任意底色都清晰
   - 8 方位候选 + 碰撞规避，减少重叠
   - 边界收敛 + 兜底描边/配色
*/

document.addEventListener('DOMContentLoaded', function () {
  const nodes = [
    {id:'n1', title:'太易序列 · [名为天国的钥匙].rar', short:'站点起点：整卷打包（总览）',
      desc:'下载/参阅打包文档（总体序列）。建议先快速浏览形成整体印象。', link:'https://github.com/SAY683/Annals-of-the-Great-Simplicity', tags:['总览','仓库'], x:12,y:18},
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

  const STORAGE_KEY = 'sayhelp_pathways_v2';
  let state = { read: {} };

  // ——状态读写——
  const loadState = () => {
    try { const raw = localStorage.getItem(STORAGE_KEY); if(raw) state = JSON.parse(raw); }
    catch(e){ state = { read: {} }; }
  };
  const saveState = () => localStorage.setItem(STORAGE_KEY, JSON.stringify(state));

  // ——DOM 引用——
  const wrap = document.querySelector('.pathway-wrap');
  const nodesList = document.getElementById('nodesList');
  const svgMap = document.getElementById('svgMap');
  const detailTitle = document.getElementById('detailTitle');
  const detailDesc = document.getElementById('detailDesc');
  const detailTags = document.getElementById('detailTags');
  const progressFill = document.getElementById('progressFill');
  const progressLabel = document.getElementById('progressLabel');

  // ——渲染列表——
  function renderList(){
    nodesList.innerHTML = '';
    nodes.forEach(n=>{
      const el = document.createElement('div');
      el.className = 'node' + (state.read[n.id] ? ' read' : '');
      el.setAttribute('data-id', n.id);
      el.innerHTML = `<h3><span>${n.title}</span><span class="small">${n.short}</span></h3><p>${n.short}</p>`;
      el.onclick = ()=>selectNode(n.id);
      if(state.read[n.id]) el.style.opacity = 0.75;
      nodesList.appendChild(el);
    });
    updateProgress();
  }

  // ——颜色工具：解析 rgb/rgba/hex —— 
  function parseColor(str){
    if(!str || str === 'transparent') return null;
    let m;
    if((m = str.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i))) {
      return {r:+m[1], g:+m[2], b:+m[3]};
    }
    if((m = str.match(/#([0-9a-f]{3,8})/i))) {
      let hex = m[1];
      if(hex.length===3){ return {
        r:parseInt(hex[0]+hex[0],16),
        g:parseInt(hex[1]+hex[1],16),
        b:parseInt(hex[2]+hex[2],16)}; }
      if(hex.length>=6){ return {
        r:parseInt(hex.slice(0,2),16),
        g:parseInt(hex.slice(2,4),16),
        b:parseInt(hex.slice(4,6),16)}; }
    }
    return null;
  }
  const luminance = ({r,g,b}) => (0.2126*r + 0.7152*g + 0.0722*b)/255;

  // ——从祖先链探测有效背景（含 linear-gradient 简析）——
  function detectLightMode(){
    if(!wrap) return;
    // 手动覆盖优先
    const manual = wrap.getAttribute('data-theme');
    if(manual === 'light'){ wrap.classList.add('light-mode'); return; }
    if(manual === 'dark'){  wrap.classList.remove('light-mode'); return; }

    let el = wrap, found = null;
    while(el && el !== document.documentElement){
      const cs = getComputedStyle(el);
      // 1) 直接 color 也作为参考（fallback）
      // 2) 解析 backgroundColor
      let c = parseColor(cs.backgroundColor);
      // 3) 解析 linear-gradient(...) 中的首/尾色
      if(!c && cs.backgroundImage && cs.backgroundImage.includes('linear-gradient')){
        const rgbMatches = cs.backgroundImage.match(/rgba?\(\d+,\s*\d+,\s*\d+(?:,\s*[\d.]+)?\)/g);
        if(rgbMatches && rgbMatches.length){
          // 取首尾平均
          const first = parseColor(rgbMatches[0]);
          const last  = parseColor(rgbMatches[rgbMatches.length-1]);
          if(first && last){
            c = { r: Math.round((first.r+last.r)/2),
                  g: Math.round((first.g+last.g)/2),
                  b: Math.round((first.b+last.b)/2) };
          } else if(first) c = first;
        }
      }
      if(c){ found = c; break; }
      el = el.parentElement;
    }
    const lum = found ? luminance(found) : 1; // 默认白
    if(lum > 0.65) wrap.classList.add('light-mode');
    else wrap.classList.remove('light-mode');
  }

  // ——渲染 SVG 地图——
  function renderMap(){
    const ns = 'http://www.w3.org/2000/svg';
    svgMap.innerHTML = '';
    const svg = document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 100 60');
    svg.setAttribute('preserveAspectRatio','xMidYMid meet');
    svg.style.width='100%'; svg.style.height='100%';

    // 边
    const edges = [['n1','n2'],['n2','n3'],['n3','n4'],['n3','n5'],['n4','n6'],['n5','n7']];
    edges.forEach(e=>{
      const a = nodes.find(x=>x.id===e[0]); const b = nodes.find(x=>x.id===e[1]);
      if(!a||!b) return;
      const line = document.createElementNS(ns,'line');
      line.setAttribute('x1', a.x); line.setAttribute('y1', a.y/1.2);
      line.setAttribute('x2', b.x); line.setAttribute('y2', b.y/1.2);
      line.setAttribute('stroke', 'rgba(110,161,200,0.16)');
      line.setAttribute('stroke-width', '0.7');
      svg.appendChild(line);
    });

    // 节点 + 标签
    const placed = []; // 已放置标签的 bbox 列表
    const groups = [];

    // 候选位置（相对圆心）
    const POS = [
      {dx: 3.4, dy:  0.6},  // E
      {dx: 3.2, dy: -1.2},  // NE
      {dx: 3.2, dy:  2.4},  // SE
      {dx:-3.4, dy:  0.6},  // W
      {dx:-3.2, dy: -1.2},  // NW
      {dx:-3.2, dy:  2.4},  // SW
      {dx: 0.0, dy: -3.4},  // N
      {dx: 0.0, dy:  4.2},  // S
    ];

    nodes.forEach(n=>{
      const g = document.createElementNS(ns,'g');
      g.setAttribute('data-id', n.id);
      const cx = n.x, cy = n.y/1.2;

      // 圆点
      const circle = document.createElementNS(ns,'circle');
      circle.setAttribute('cx', cx);
      circle.setAttribute('cy', cy);
      circle.setAttribute('r', 2.8);
      circle.setAttribute('fill', state.read[n.id] ? '#6ea1c8' : '#1e6f9a');
      circle.style.cursor='pointer';
      circle.onclick = ()=>selectNode(n.id);
      g.appendChild(circle);

      // 先放一个文本用于测量，再决定最终位置
      const text = document.createElementNS(ns,'text');
      text.textContent = n.title;
      text.setAttribute('x', cx + 3.4);
      text.setAttribute('y', cy + 0.6);
      g.appendChild(text);

      // 背板（在 text 之前插入）
      const rect = document.createElementNS(ns,'rect');
      rect.setAttribute('class','label-bg');
      g.insertBefore(rect, text);

      svg.appendChild(g);
      groups.push({g, text, rect, cx, cy, id:n.id});
    });

    svgMap.appendChild(svg);

    // 等一帧让浏览器计算 BBox
    setTimeout(()=>{
      groups.forEach(item=>{
        // 选择一个不重叠的候选位置
        let chosen = null, bbox = null;
        for(const p of POS){
          positionLabel(item, p.dx, p.dy);
          const b = getLabelBBox(item);
          if(!overlaps(b, placed)) { chosen = p; bbox = b; break; }
        }
        if(!chosen){
          // 全重叠则在 E 方向基础上小步下移直到相对不重叠或到达上限
          positionLabel(item, POS[0].dx, POS[0].dy);
          bbox = getLabelBBox(item);
          let attempts = 0;
          while(overlaps(bbox, placed) && attempts < 18){
            shiftLabel(item, 0, (bbox.height + 0.8));
            bbox = getLabelBBox(item);
            attempts++;
          }
        }
        // 边界收敛：若超出 viewBox，向里收回 1.5
        const vb = svg.viewBox.baseVal;
        let moved = false;
        if(bbox.x + bbox.width > vb.width - 1.5) { shiftLabel(item, -((bbox.x + bbox.width) - (vb.width - 1.5)), 0); moved=true; }
        if(bbox.x < 1.5)                           { shiftLabel(item,  (1.5 - bbox.x), 0); moved=true; }
        if(moved) bbox = getLabelBBox(item);

        // 更新背板尺寸（四周留白 0.8）
        const pad = 0.8;
        bbox = getLabelBBox(item); // 最新 bbox
        item.rect.setAttribute('x', (bbox.x - pad).toString());
        item.rect.setAttribute('y', (bbox.y - pad).toString());
        item.rect.setAttribute('width',  (bbox.width + pad*2).toString());
        item.rect.setAttribute('height', (bbox.height + pad*2).toString());

        placed.push(bbox);
      });

      // 兜底：把当前容器 color 实际取值赋给 <text> 的 fill，避免某些浏览器对 currentColor 继承不一致
      const color = getComputedStyle(wrap || document.body).color;
      svg.querySelectorAll('text').forEach(t=> t.setAttribute('fill', color));
    }, 40);
  }

  function positionLabel(item, dx, dy){
    item.text.setAttribute('x', (item.cx + dx).toString());
    item.text.setAttribute('y', (item.cy + dy).toString());
  }
  function shiftLabel(item, dx, dy){
    item.text.setAttribute('x', (parseFloat(item.text.getAttribute('x')) + dx).toString());
    item.text.setAttribute('y', (parseFloat(item.text.getAttribute('y')) + dy).toString());
  }
  function getLabelBBox(item){
    const b = item.text.getBBox();
    return { x:b.x, y:b.y, width:b.width, height:b.height };
  }
  function overlaps(box, list){
    return list.some(p => !( (box.x+box.width) < p.x || box.x > (p.x+p.width) || (box.y+box.height) < p.y || box.y > (p.y+p.height) ));
  }

  // ——交互逻辑——
  let currentId = null;
  function selectNode(id){
    const n = nodes.find(x=>x.id===id); if(!n) return;
    currentId = id;
    document.querySelectorAll('.node').forEach(el=> el.classList.toggle('active', el.dataset.id === id));
    document.querySelectorAll('#svgMap svg g').forEach(g=>{
      const gid = g.getAttribute('data-id');
      const circle = g.querySelector('circle');
      if(!circle) return;
      if(gid === id) {
        circle.setAttribute('fill','#8fc1e6'); circle.setAttribute('r',3.6);
      } else {
        circle.setAttribute('fill', (state.read[gid] ? '#6ea1c8' : '#1e6f9a'));
        circle.setAttribute('r',2.8);
      }
    });
    detailTitle.textContent = n.title;
    detailDesc.textContent = n.desc;
    detailTags.innerHTML = '';
    n.tags.forEach(t=>{ const s=document.createElement('span'); s.className='tag'; s.textContent=t; detailTags.appendChild(s); });

    document.getElementById('openLink').onclick = ()=> window.open(n.link,'_blank');
    document.getElementById('markRead').onclick = ()=>{ state.read[n.id]=true; saveState(); renderList(); renderMap(); selectNode(n.id); };
    document.getElementById('nextBtn').onclick = ()=> goNext(n.id);
  }

  function goNext(id){
    const idx = nodes.findIndex(n=>n.id===id);
    if(idx >= 0 && idx < nodes.length-1){
      selectNode(nodes[idx+1].id);
      const el = document.querySelector(`.node[data-id="${nodes[idx+1].id}"]`);
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

  // 顶部控制
  document.getElementById('markAll').onclick = ()=>{ nodes.forEach(n=> state.read[n.id]=true); saveState(); renderList(); renderMap(); };
  document.getElementById('resetAll').onclick = ()=>{ state.read = {}; saveState(); renderList(); renderMap(); };
  document.getElementById('exportProgress').onclick = ()=>{
    const data = JSON.stringify(state, null, 2);
    const blob = new Blob([data], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'pathways-progress.json'; a.click();
    URL.revokeObjectURL(url);
  };

  // ——初始化——
  loadState();
  detectLightMode();
  renderList();
  renderMap();
  if(location.hash){
    const id = location.hash.replace('#','');
    if(nodes.some(n=>n.id===id)) selectNode(id);
  }

  // 支持在 HTML 上手动切换：<div class="pathway-wrap" data-theme="light">...</div>
  // 也可在控制台调用：_pathways.theme('light'|'dark'|'auto')
  function theme(mode){
    if(!wrap) return;
    if(mode === 'light'){ wrap.setAttribute('data-theme','light'); wrap.classList.add('light-mode'); }
    else if(mode === 'dark'){ wrap.setAttribute('data-theme','dark'); wrap.classList.remove('light-mode'); }
    else { wrap.removeAttribute('data-theme'); detectLightMode(); }
    // 重绘以应用文字/底板对比色
    renderMap();
  }

  window._pathways = { nodes, state, saveState, selectNode, theme };
});
