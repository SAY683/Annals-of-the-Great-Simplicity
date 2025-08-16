/* js/pathways.js
   交互路径页逻辑（供 /pathways.html 引用）
   保存到仓库： js/pathways.js
*/
document.addEventListener('DOMContentLoaded', function () {

  // ======= 数据：你的思想路径节点（按要求的序列与分支） =======
  const nodes = [
    {
      id: 'n1',
      title: '太易序列 · [名为天国的钥匙].rar',
      short: '站点起点：整卷打包（总览）',
      desc: '下载/参阅打包文档（总体序列）。建议：先做快速浏览，形成整体印象；若偏好慢读，跳到下一项的 PDF 深读。',
      link: 'https://github.com/SAY683/Annals-of-the-Great-Simplicity',
      tags: ['总览','下载包','仓库'],
      x: 12, y: 18
    },
    {
      id: 'n2',
      title: '太上洞庭自然经.pdf',
      short: '主文档（核心文本）',
      desc: '阅读顺序建议：先读此 PDF 的序言与目录，再选择章节深入。此文为理解整体语境的关键文本。',
      link: 'https://github.com/SAY683/Annals-of-the-Great-Simplicity/blob/main/%E5%A4%AA%E4%B8%8A%E6%B4%9E%E5%AE%BF%E8%87%AA%E7%84%B6%E7%BB%8F.pdf',
      tags: ['核心文本','PDF','元皇经'],
      x: 36, y: 18
    },

    // 分支说明结点（用户可通过这里选择路线）
    {
      id: 'n3',
      title: '进入 · 现代模式（Miscellanies）',
      short: '若你偏现代/项目化 → 进入 Miscellanies',
      desc: '现代模式聚焦项目实操、案例、小册子与流程化产出。进入后可看到项目内部的“Miscellanies”文件夹，包含碎片化、现代姿态的写作与产物。',
      link: 'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Miscellanies',
      tags: ['现代','项目','Miscellanies'],
      x: 64, y: 32
    },
    {
      id: 'n4',
      title: '进入 · 炼金术模式（Remarks）',
      short: '若你偏隐秘/炼金/象征 → 进入 Remarks',
      desc: '炼金术模式偏重注释、隐喻、炼金思想与文本注解；更适合要深入“秘传”或进行哲学化创作的人。',
      link: 'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Remarks',
      tags: ['炼金','注释','Remarks'],
      x: 84, y: 46
    },

    // 扩展阅读 / 实践
    {
      id: 'n5',
      title: '项目·Miscellanies（实践入口）',
      short: '项目内的现代实践样本',
      desc: '若你已经进入 Miscellanies，这里列出你能做的“现代实践”：流程优化、案例 PDF、微刊发布。建议：挑一项做一个微案例并上传 PDF。',
      link: 'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Miscellanies',
      tags: ['实践','案例','上传PDF'],
      x: 52, y: 70
    },
    {
      id: 'n6',
      title: '注释·Remarks（炼金术深读）',
      short: '炼金术模式的注释与笔记',
      desc: 'Remarks 内是对文本的炼金注解与隐喻性扩展。建议：按章节做“解读—注释—写作”循环，并把关键注释做成独立可下载摘要。',
      link: 'https://github.com/SAY683/Annals-of-the-Great-Simplicity/tree/main/Remarks',
      tags: ['注释','炼金','深读'],
      x: 26, y: 86
    },
    {
      id: 'n7',
      title: '回归 · 打包与支点页',
      short: '把读写产物打包成为“支点页/思想包”',
      desc: '最后一步：把你在各文件夹中产生的 PDF、注释、微案例整理并建立支点页（Pillar Page），便于长期沉淀与引用。',
      link: 'https://github.com/SAY683/Annals-of-the-Great-Simplicity',
      tags: ['打包','支点页','沉淀'],
      x: 50, y: 48
    }
  ];

  // ======= 状态管理（localStorage） =======
  const STORAGE_KEY = 'sayhelp_pathways_v1';
  let state = { read: {} };

  function loadState(){
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if(raw) state = JSON.parse(raw);
    } catch(e){ state = { read: {} }; }
  }
  function saveState(){ localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }

  // ======= 渲染列表与地图（依赖 DOM 元素） =======
  const nodesList = document.getElementById('nodesList');
  const svgMap = document.getElementById('svgMap');
  const detailTitle = document.getElementById('detailTitle');
  const detailDesc = document.getElementById('detailDesc');
  const detailTags = document.getElementById('detailTags');
  const progressFill = document.getElementById('progressFill');
  const progressLabel = document.getElementById('progressLabel');

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

  function renderMap(){
    // prepare SVG
    const w = svgMap.clientWidth, h = svgMap.clientHeight;
    const ns = 'http://www.w3.org/2000/svg';
    svgMap.innerHTML = '';
    const svg = document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox', '0 0 100 60');
    svg.setAttribute('preserveAspectRatio','xMidYMid meet');
    svg.style.width = '100%'; svg.style.height = '100%';

    const edges = [['n1','n2'],['n2','n3'],['n3','n4'],['n3','n5'],['n4','n6'],['n5','n7']];
    edges.forEach(e=>{
      const a = nodes.find(x=>x.id===e[0]); const b = nodes.find(x=>x.id===e[1]);
      if(!a||!b) return;
      const line = document.createElementNS(ns,'line');
      line.setAttribute('x1', a.x); line.setAttribute('y1', a.y/1.2);
      line.setAttribute('x2', b.x); line.setAttribute('y2', b.y/1.2);
      line.setAttribute('stroke', 'rgba(110,161,200,0.18)');
      line.setAttribute('stroke-width', '0.8');
      svg.appendChild(line);
    });

    nodes.forEach(n=>{
      const g = document.createElementNS(ns,'g');
      g.setAttribute('data-id', n.id);
      const cx = n.x, cy = n.y/1.2;
      const circle = document.createElementNS(ns,'circle');
      circle.setAttribute('cx', cx);
      circle.setAttribute('cy', cy);
      circle.setAttribute('r', 2.6);
      circle.setAttribute('fill', state.read[n.id] ? '#6ea1c8' : '#1e6f9a');
      circle.setAttribute('stroke','rgba(255,255,255,0.04)');
      circle.style.cursor = 'pointer';
      circle.onclick = ()=>selectNode(n.id);
      g.appendChild(circle);

      const label = document.createElementNS(ns,'text');
      label.setAttribute('x', cx + 3.2);
      label.setAttribute('y', cy + 0.8);
      label.setAttribute('font-size','2.2');
      label.setAttribute('fill','#cfe9fb');
      label.textContent = n.title;
      svg.appendChild(g);
      svg.appendChild(label);
    });

    svgMap.appendChild(svg);
  }

  // ======= 节点选择与详情显示 =======
  let currentId = null;

  function selectNode(id){
    const n = nodes.find(x=>x.id===id);
    if(!n) return;
    currentId = id;
    document.querySelectorAll('.node').forEach(el=> el.classList.toggle('active', el.dataset.id === id));
    document.querySelectorAll('#svgMap svg circle').forEach(c=>{
      const g = c.parentNode; 
      const gid = g.getAttribute('data-id');
      if(!gid) return;
      c.setAttribute('fill', (gid === id) ? '#8fc1e6' : (state.read[gid] ? '#6ea1c8':'#1e6f9a'));
      c.setAttribute('r', (gid === id) ? 3.6 : 2.6);
    });

    detailTitle.textContent = n.title;
    detailDesc.textContent = n.desc;
    detailTags.innerHTML = '';
    n.tags.forEach(t=>{
      const s = document.createElement('span'); s.className='tag'; s.textContent = t; detailTags.appendChild(s);
    });

    // Open link behavior: if it's a GitHub tree link that points to folder, open in new tab
    document.getElementById('openLink').onclick = ()=> { window.open(n.link, '_blank'); };
    document.getElementById('markRead').onclick = ()=> { state.read[n.id]=true; saveState(); renderList(); renderMap(); selectNode(n.id); };
    document.getElementById('nextBtn').onclick = ()=> { goNext(n.id); };
  }

  function goNext(id){
    // recommend next meaningful node (if branching chose node with two children, pick first by default)
    const idx = nodes.findIndex(n=>n.id===id);
    if(idx >= 0 && idx < nodes.length-1){
      selectNode(nodes[idx+1].id);
      const el = document.querySelector('.node[data-id="'+nodes[idx+1].id+'"]');
      if(el) el.scrollIntoView({behavior:'smooth', block:'center'});
    } else {
      alert('已达路径末端。可回到任一节点复读或标注新笔记。');
    }
  }

  function updateProgress(){
    const total = nodes.length;
    const readCount = Object.keys(state.read).filter(k=>state.read[k]).length;
    const pct = Math.round((readCount/total)*100);
    progressFill.style.width = pct + '%';
    progressLabel.textContent = `已读 ${readCount} / ${total}`;
  }

  document.getElementById('markAll').onclick = ()=>{
    nodes.forEach(n=> state.read[n.id]=true); saveState(); renderList(); renderMap();
  };
  document.getElementById('resetAll').onclick = ()=>{
    state.read = {}; saveState(); renderList(); renderMap();
  };
  document.getElementById('exportProgress').onclick = ()=>{
    const data = JSON.stringify(state, null, 2);
    const blob = new Blob([data], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'pathways-progress.json'; a.click();
    URL.revokeObjectURL(url);
  };

  // ======= 初始化 =======
  loadState();
  renderList();
  renderMap();

  if(location.hash){
    const id = location.hash.replace('#','');
    if(nodes.some(n=>n.id===id)) selectNode(id);
  }

  // 暴露调试对象
  window._pathways = { nodes, state, saveState, selectNode };

});
