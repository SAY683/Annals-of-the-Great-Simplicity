// START OF FILE JS/vts-wheel.js (FINAL VERSION - REFINED JSON OUTPUT)

document.addEventListener('DOMContentLoaded', () => {

    // =========================================================================
    // 1. 数据定义 (DATA DEFINITIONS)
    // -------------------------------------------------------------------------
    // VTS模型和十二原型的核心数据，是应用的基石。
    // =========================================================================

    const vtsData = {
        V: { name: "Vision / 愿景", concepts: "朴明 · 元亨 · 萨埵", entropy: "低熵 (Low Entropy)", description: "代表了系统的核心驱动力与终极理想。它是一种纯粹的、高度有序的精神形态，是所有行动的源初之光与最终归宿。" },
        T: { name: "Tactic / 战术", concepts: "权德 · 态式 · 刺阇", entropy: "中熵 (Medium Entropy)", description: "代表了将愿景转化为现实的具体方法与权变之道。它是在动态环境中，平衡内外、调度资源、执行操作的实际能力与表现形态。" },
        S: { name: "Strategy / 战略", concepts: "质性 · 流理 · 答摩", entropy: "高熵 (High Entropy)", description: "代表了系统的根基与物质基础。它是系统得以存在的底层逻辑、资源流与限制性条件，是构成现实世界的最基本质料与规律。" }
    };

    const archetypesData = [
        {
            id: 'arc1', name: "智者", subName: "鉴渊", englishName: "The Sage", group: 'left',
            quote: "真理值得追寻，哪怕代价高昂。",
            core: { desire: "理解世界真相，获得智慧并传授他人。", fear: "无知、被欺骗、浅薄；真理不可知。" },
            manifestation: { behavior: "学习与研究、分析问题、传授知识、追求客观、反思内省。", shadow: "冷漠疏离、知识傲慢、脱离实践、用理性压抑情感、故步自封。" }
        },
        {
            id: 'arc2', name: "照顾者", subName: "润荄", englishName: "The Caregiver", group: 'left',
            quote: "我愿付出，只为他人安康。",
            core: { desire: "帮助与滋养他人，创造安全与温暖的环境。", fear: "自私、无能为力、所爱之人受伤或受苦。" },
            manifestation: { behavior: "给予支持、倾听共情、牺牲自我、提供资源、维护关系。", shadow: "情感勒索、过度干预、控制欲伪装成关爱、自我耗竭、怨恨未被感激。" }
        },
        {
            id: 'arc3', name: "英雄", subName: "振锋", englishName: "The Hero", group: 'left',
            quote: "我必战胜障碍，证明我的价值。",
            core: { desire: "证明自身价值，战胜障碍，带来积极改变。", fear: "软弱、失败、无助；被看作无能或懦弱。" },
            manifestation: { behavior: "勇敢行动、承担责任、保护弱者、设定目标、坚持到底。", shadow: "好斗逞强、救世主情结、忽视合作、将他人工具化、无法示弱。" }
        },
        {
            id: 'arc4', name: "天真者", subName: "守昭", englishName: "The Innocent", group: 'left',
            quote: "愿世界美好，愿我安全。",
            core: { desire: "获得幸福、安全与归属；保持纯真，相信善终胜恶。", fear: "惩罚、失败、被抛弃；世界充满危险与背叛。" },
            manifestation: { behavior: "信任他人、保持乐观、寻求保护、避免冲突、向往简单生活。", shadow: "否认现实、幼稚逃避、依赖权威、压抑负面情绪、拒绝成长。" }
        },
        {
            id: 'arc5', name: "统治者", subName: "纲曜", englishName: "The Ruler", group: 'left',
            quote: "秩序带来繁荣，责任成就权威。",
            core: { desire: "建立并维持秩序、安全与繁荣；承担责任，引领集体成功。", fear: "混乱、失控、无政府状态；被推翻或失去合法性。" },
            manifestation: { behavior: "领导团队、制定规则与制度、分配资源、维护公平、建立可持续结构。", shadow: "专制独裁、滥用权力、控制欲过强、压抑异见、僵化守旧。" }
        },
        {
            id: 'arc6', name: "革新者", subName: "破曜", englishName: "The Rebel", group: 'left',
            quote: "打破旧世界，才能建新家园。",
            core: { desire: "颠覆压迫性结构，创造真实与自由的新秩序。", fear: "无力、被压迫、平庸；变革无法发生。" },
            manifestation: { behavior: "挑战权威、揭露虚伪、制造颠覆性改变、坚持真实、反抗不公。", shadow: "无目的破坏、愤世嫉俗、自我毁灭、以反叛为身份、拒绝建设。" }
        },
        {
            id: 'arc7', name: "情人", subName: "合漪", englishName: "The Lover", group: 'right',
            quote: "渴望亲密、融合、体验美与爱；与他人或世界深度连接。",
            core: { desire: "亲密、融合、体验美与爱；与他人或世界深度连接。", fear: "孤独、不被爱、关系破裂；爱被拒绝或背叛。" },
            manifestation: { behavior: "吸引与融合、创造美感、表达热情、培养亲密、重视感官体验。", shadow: "情感依赖、嫉妒控制、为爱迷失自我、物化他人、沉溺激情。" }
        },
        {
            id: 'arc8', name: "魔法师", subName: "玄圜", englishName: "The Magician", group: 'right',
            quote: "转化是可能的，现实可被重塑。",
            core: { desire: "转化现实，掌握深层法则，疗愈与整合对立。", fear: "无力、魔法失效、被表象迷惑；转化失败。" },
            manifestation: { behavior: "疗愈创伤、连接灵性与物质、促成质变、运用象征、整合矛盾。", shadow: "操控他人、神秘主义逃避、滥用影响力、制造幻觉、拒绝平凡。" }
        },
        {
            id: 'arc9', name: "小丑", subName: "谑枢", englishName: "The Jester", group: 'right',
            quote: "笑对荒诞，方得自由。",
            core: { desire: "享受当下、带来欢乐、解构严肃与权威。", fear: "无聊、被忽视、生活无趣或沉重。" },
            manifestation: { behavior: "幽默讽刺、游戏精神、打破僵局、揭示真相、活在当下。", shadow: "轻浮逃避、拒绝深度、用笑掩盖痛苦、破坏而不建设、情感疏离。" }
        },
        {
            id: 'arc10', name: "创造者", subName: "形曦", englishName: "The Creator", group: 'right',
            quote: "我要留下独一无二的印记。",
            core: { desire: "创造独特而持久的作品，实现内在愿景。", fear: "平庸、创意枯竭、作品被忽视或误解。" },
            manifestation: { behavior: "想象与设计、艺术或技术创新、表达个性、追求完美、赋予形式。", shadow: "完美主义瘫痪、自我怀疑、为创作牺牲生活、贬低他人作品、脱离现实。" }
        },
        {
            id: 'arc11', name: "孤儿", subName: "孤曜", englishName: "The Orphan", group: 'right',
            quote: "我不再幻想，只求真实地活着。",
            core: { desire: "归属、真实、平等；摆脱幻想，脚踏实地。", fear: "被排斥、孤立无援、沦为受害者；虚假的希望破灭。" },
            manifestation: { behavior: "务实处事、共情他人苦难、寻求社群支持、质疑权威、强调公平。", shadow: "怨恨不平、受害者心态、随波逐流、压抑个性、愤世嫉俗。" }
        },
        {
            id: 'arc12', name: "探索者", subName: "越垠", englishName: "The Explorer", group: 'right',
            quote: "真理在远方，自由在我心。",
            core: { desire: "自由、发现新世界、寻找真理与自我定义。", fear: "被困、平庸、失去自主；生活陷入重复与束缚。" },
            manifestation: { behavior: "旅行或精神漫游、质疑常规、突破边界、追求独特体验、保持独立。", shadow: "逃避责任、永不满足、孤独成瘾、拒绝承诺、将自由等同于疏离。" }
        }
    ];


    // =========================================================================
    // 2. 状态与元素管理 (STATE & ELEMENT MANAGEMENT)
    // =========================================================================
    let dragState = { sourceElement: null, originalParent: null };
    const elements = {
        interactiveArea: document.querySelector('.vts-interactive-area'),
        bankLeft: document.getElementById('bank-left'),
        bankRight: document.getElementById('bank-right'),
        dropZones: document.querySelectorAll('.drop-zone'),
        downloadBtn: document.getElementById('download-btn'),
        resetBtn: document.getElementById('reset-btn'),
        layoutNameInput: document.getElementById('layout-name'),
    };
    const allDropTargets = [elements.bankLeft, elements.bankRight, ...elements.dropZones];


    // =========================================================================
    // 3. 核心功能函数 (CORE FUNCTIONS)
    // =========================================================================

    /**
     * 根据原型数据创建一个可拖拽的DOM元素。
     */
    function createArchetypeElement(arcData) {
        const item = document.createElement('div');
        item.className = 'archetype-item';
        item.classList.add(arcData.group === 'left' ? 'group-left' : 'group-right');
        item.draggable = true;
        item.dataset.id = arcData.id;
        item.innerHTML = `${arcData.name}<span class="sub-name">${arcData.subName}</span>`;
        return item;
    }

    /**
     * 更新一个VTS插槽的视觉状态。
     */
    function updateDropZoneState(zone) {
        if (zone && zone.classList.contains('drop-zone')) {
            const hasItem = zone.querySelector('.archetype-item') !== null;
            zone.classList.toggle('has-item', hasItem);
        }
    }

    /**
     * 检查并更新下载按钮的可用状态。
     */
    function updateDownloadButtonState() {
        const allSlotsFilled = [...elements.dropZones].every(zone => zone.querySelector('.archetype-item'));
        elements.downloadBtn.disabled = !allSlotsFilled;
    }
    
    /**
     * 重置整个排盘界面到初始状态。
     */
    function resetChart() {
        elements.dropZones.forEach(zone => {
            const item = zone.querySelector('.archetype-item');
            if (item) {
                const itemData = archetypesData.find(a => a.id === item.dataset.id);
                const targetBank = itemData.group === 'left' ? elements.bankLeft : elements.bankRight;
                targetBank.appendChild(item);
            }
            updateDropZoneState(zone);
        });
        
        elements.layoutNameInput.value = '';
        updateDownloadButtonState();
    }
    
    /**
     * 【核心重构】生成并下载精炼后的排盘JSON文件。
     *  现在只包含与本次排盘直接相关的信息。
     */
    function generateAndDownloadJSON() {
        const layoutName = elements.layoutNameInput.value.trim() || '未命名排盘';
        
         // 1. 构建JSON的基础结构
        const result = {
            layout_name: layoutName,
            creation_timestamp: new Date().toISOString(),
            vts_model_definitions: vtsData,
            chart: {
                V: null,
                T: null,
                S: null
            }
        };

        // 2. 遍历插槽，填充排盘信息
        elements.dropZones.forEach(zone => {
            const slot = zone.dataset.slot;
            const item = zone.querySelector('.archetype-item');
            if (item) {
                const itemData = archetypesData.find(a => a.id === item.dataset.id);
                
                // 【核心修复】使用对象解构赋值，在创建副本时同时剔除 'id' 和 'group' 属性。
                // `...definition` 是剩余参数语法，它会将 itemData 中除了 id 和 group 之外的所有属性
                // 收集到一个名为 definition 的新对象中。
                const { id, group, ...definition } = itemData;
                
                // 将这份纯净的、不含内部ID的定义信息填入对应的槽位
                result.chart[slot] = definition;
            }
        });

        // 3. 将构建好的对象转换为JSON字符串并触发下载
        const jsonString = JSON.stringify(result, null, 4);
        const blob = new Blob([jsonString], { type: 'application/json;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${layoutName.replace(/ /g, '_')}_VTS_Chart.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    // =========================================================================
    // 4. 事件处理函数 (EVENT HANDLERS)
    // =========================================================================

    function handleDragStart(e) {
        if (e.target.classList.contains('archetype-item')) {
            dragState.sourceElement = e.target;
            dragState.originalParent = e.target.parentElement;
            
            const clone = e.target.cloneNode(true);
            clone.style.cssText = `position: absolute; top: -1000px; width: ${e.target.offsetWidth}px; opacity: 0.7;`;
            document.body.appendChild(clone);
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setDragImage(clone, e.target.offsetWidth / 2, e.target.offsetHeight / 2);
            
            setTimeout(() => {
                e.target.classList.add('dragging');
                document.body.removeChild(clone);
            }, 0);

            updateDropZoneState(dragState.originalParent);
        }
    }

    function handleDragEnd(e) {
        if (dragState.sourceElement) {
            dragState.sourceElement.classList.remove('dragging');
            if (dragState.sourceElement.parentElement === dragState.originalParent) {
                updateDropZoneState(dragState.originalParent);
            }
            dragState = { sourceElement: null, originalParent: null };
        }
    }

    function handleDragOver(e) {
        e.preventDefault();
        e.currentTarget.classList.add('drag-over');
    }

    function handleDragLeave(e) {
        e.currentTarget.classList.remove('drag-over');
    }

    function handleDrop(e) {
        e.preventDefault();
        const dropTarget = e.currentTarget;
        dropTarget.classList.remove('drag-over');
        if (!dragState.sourceElement) return;

        if (dropTarget.classList.contains('drop-zone')) {
            const existingItem = dropTarget.querySelector('.archetype-item');
            if (existingItem) {
                const itemData = archetypesData.find(a => a.id === existingItem.dataset.id);
                const targetBank = itemData.group === 'left' ? elements.bankLeft : elements.bankRight;
                targetBank.appendChild(existingItem);
            }
        }
        
        dropTarget.appendChild(dragState.sourceElement);
        
        updateDropZoneState(dropTarget);
        updateDownloadButtonState();
    }

    // =========================================================================
    // 5. 应用初始化 (APP INITIALIZATION)
    // =========================================================================
    
    function initializeApp() {
        archetypesData.sort((a, b) => parseInt(a.id.slice(3)) - parseInt(b.id.slice(3)));
        archetypesData.forEach(arc => {
            const item = createArchetypeElement(arc);
            const targetBank = arc.group === 'left' ? elements.bankLeft : elements.bankRight;
            targetBank.appendChild(item);
        });

        elements.interactiveArea.addEventListener('dragstart', handleDragStart);
        elements.interactiveArea.addEventListener('dragend', handleDragEnd);

        allDropTargets.forEach(target => {
            target.addEventListener('dragover', handleDragOver);
            target.addEventListener('dragleave', handleDragLeave);
            target.addEventListener('drop', handleDrop);
        });

        elements.downloadBtn.addEventListener('click', () => {
            const originalText = elements.downloadBtn.textContent;
            elements.downloadBtn.textContent = '已生成 ✓';
            generateAndDownloadJSON();
            setTimeout(() => { elements.downloadBtn.textContent = originalText; }, 2000);
        });
        
        elements.resetBtn.addEventListener('click', resetChart);

        updateDownloadButtonState();
    }

    initializeApp();

});

// END OF FILE JS/vts-wheel.js (FINAL VERSION - REFINED JSON OUTPUT)