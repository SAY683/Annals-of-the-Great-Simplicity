// START OF FILE JS/vts-wheel.js
document.addEventListener('DOMContentLoaded', () => {

    // 1. 数据定义
    const archetypesData = [
        { id: 'arc1', name: "智者", subName: "鉴渊", group: 'left' },
        { id: 'arc2', name: "照顾者", subName: "润荄", group: 'left' },
        { id: 'arc3', name: "英雄", subName: "振锋", group: 'left' },
        { id: 'arc4', name: "凡人", subName: "守昭", group: 'left' },
        { id: 'arc5', name: "统治者", subName: "纲曜", group: 'left' },
        { id: 'arc6', name: "革新者", subName: "破曜", group: 'left' },
        { id: 'arc7', name: "情人", subName: "合漪", group: 'right' },
        { id: 'arc8', name: "魔法师", subName: "玄圜", group: 'right' },
        { id: 'arc9', name: "小丑", subName: "谑枢", group: 'right' },
        { id: 'arc10', name: "创造者", subName: "形曦", group: 'right' },
        { id: 'arc11', name: "孤儿", subName: "孤曜", group: 'right' },
        { id: 'arc12', name: "探索者", subName: "越垠", group: 'right' }
    ];

    // 2. 获取 DOM 元素
    const bankLeft = document.getElementById('bank-left');
    const bankRight = document.getElementById('bank-right');
    const dropZones = document.querySelectorAll('.drop-zone');
    const downloadBtn = document.getElementById('download-btn');
    const layoutNameInput = document.getElementById('layout-name');

    // 3. 初始化原型库
    function populateBanks() {
        archetypesData.forEach(arc => {
            const item = document.createElement('div');
            item.className = 'archetype-item';
            item.draggable = true;
            item.dataset.id = arc.id;
            item.innerHTML = `${arc.name}<span class="sub-name">${arc.subName}</span>`;

            if (arc.group === 'left') {
                bankLeft.appendChild(item);
            } else {
                bankRight.appendChild(item);
            }
        });
    }

    populateBanks();

    // 4. 实现拖放逻辑
    const archetypeItems = document.querySelectorAll('.archetype-item');

    archetypeItems.forEach(item => {
        item.addEventListener('dragstart', (e) => {
            e.target.classList.add('dragging');
            e.dataTransfer.setData('text/plain', e.target.dataset.id);
        });

        item.addEventListener('dragend', (e) => {
            e.target.classList.remove('dragging');
        });
    });

    dropZones.forEach(zone => {
        zone.addEventListener('dragover', (e) => {
            e.preventDefault(); // 必须阻止默认行为才能触发 drop
            zone.classList.add('drag-over');
        });

        zone.addEventListener('dragleave', () => {
            zone.classList.remove('drag-over');
        });

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('drag-over');

            const id = e.dataTransfer.getData('text/plain');
            const draggedItem = document.querySelector(`.archetype-item[data-id='${id}']`);
            
            if (!draggedItem) return;

            // 如果插槽中已有卡片，将其移回原来的库
            if (zone.children.length > 1) { // 忽略 .slot-label
                const existingItem = zone.querySelector('.archetype-item');
                const existingItemData = archetypesData.find(a => a.id === existingItem.dataset.id);
                if(existingItemData.group === 'left') {
                    bankLeft.appendChild(existingItem);
                } else {
                    bankRight.appendChild(existingItem);
                }
            }
            
            // 将新卡片放入插槽
            zone.appendChild(draggedItem);
        });
    });

    // 5. 实现下载 JSON 功能
    downloadBtn.addEventListener('click', () => {
        const layoutName = layoutNameInput.value.trim() || '未命名排盘';
        
        const result = {
            name: layoutName,
            timestamp: new Date().toISOString(),
            layout: {
                V: null,
                T: null,
                S: null
            }
        };

        dropZones.forEach(zone => {
            const slot = zone.dataset.slot;
            const item = zone.querySelector('.archetype-item');
            if (item) {
                const itemData = archetypesData.find(a => a.id === item.dataset.id);
                result.layout[slot] = {
                    id: itemData.id,
                    name: itemData.name,
                    subName: itemData.subName
                };
            }
        });

        // 创建并触发下载
        const jsonString = JSON.stringify(result, null, 2);
        const blob = new Blob([jsonString], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `${layoutName}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });

});
// END OF FILE JS/vts-wheel.js