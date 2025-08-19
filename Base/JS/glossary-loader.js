// js/glossary-loader.js
document.addEventListener('DOMContentLoaded', () => {
    const glossaryContainer = document.getElementById('glossary-container');
    const insightsContainer = document.getElementById('insights-container');
    const secretOverlay = document.getElementById('secret-overlay');
    const secretKey = document.querySelector('.secret-key');

    // 1. 加载“太易词典”
    if (glossaryContainer && typeof glossaryData !== 'undefined') {
        const dl = document.createElement('dl');
        glossaryData.forEach(item => {
            const dt = document.createElement('dt');
            dt.textContent = item.term;
            const dd = document.createElement('dd');
            dd.textContent = item.definition;
            dl.appendChild(dt);
            dl.appendChild(dd);
        });
        glossaryContainer.appendChild(dl);
    }

    // 2. 加载“心得札记”
    if (insightsContainer && typeof insightsData !== 'undefined') {
        insightsData.forEach(item => {
            const card = document.createElement('div');
            card.className = 'insight-card';
            
            const title = document.createElement('h3');
            title.className = 'insight-title';
            title.textContent = item.title;
            
            const content = document.createElement('p');
            content.className = 'insight-content';
            content.innerHTML = item.content; // 使用 innerHTML 来解析彩蛋的 <span> 标签
            
            card.appendChild(title);
            card.appendChild(content);
            insightsContainer.appendChild(card);
        });
    }

    // 3. 彩蛋交互逻辑
    // 我们需要重新在DOM渲染后获取secretKey元素
    const renderedSecretKey = document.querySelector('.secret-key'); 
    if (renderedSecretKey && secretOverlay) {
        renderedSecretKey.addEventListener('click', () => {
            secretOverlay.classList.add('visible');
        });

        secretOverlay.addEventListener('click', () => {
            secretOverlay.classList.remove('visible');
        });
    }
});