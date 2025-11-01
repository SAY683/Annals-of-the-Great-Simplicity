// START OF FILE JS/daopan.js (FINAL AND TRULY COMPLETE VERSION)

document.addEventListener('DOMContentLoaded', () => {

    // =========================================================================
    // 1. DOM & STATE VARIABLES
    // =========================================================================
    const elements = {
        gridContainer: document.querySelector('.daopan-grid'),
        edictBank: document.getElementById('edict-bank'),
        toggleAcupointsBtn: document.getElementById('toggle-acupoints-btn'),
        resetBtn: document.getElementById('reset-daopan-btn'),
        phaseDisplay: document.querySelector('#current-phase-display p'),
        rulingSelector: document.getElementById('ruling-selector'),
        tooltip: document.getElementById('daopan-tooltip'),
        advancedPlayArea: document.getElementById('advanced-play-area'),
        jumpPanInfo: document.getElementById('jump-pan-info'),
        godsEyeToggleButtons: document.getElementById('gods-eye-toggle-buttons'),
        godsEyeContainer: document.getElementById('gods-eye-container'),
        downloadImageBtn: document.getElementById('download-image-btn'),
        modal: {
            overlay: document.getElementById('selection-modal'),
            title: document.getElementById('modal-title'),
            optionsContainer: document.getElementById('modal-options-container'),
            closeBtn: document.getElementById('modal-close-btn')
        }
    };

    let gameState = {};

    const phaseInstructions = {
        PLACE_EDICTS: '请拖拽“四令”至“本宫”',
        PLACE_GATES: '请点击“太宫”以布列八门',
        PLACE_GENERALS: '请点击“局宫”或“仪宫”以布列神将',
        PLACE_DIVISIONS: '请点击“重宫”或“义宫”以布列神部',
        COMPLETE: '推演完成，可进行高阶操作',
        JUMP_PAN: '请点击任意高亮“本宫”确认联动跳盘'
    };

    const godsEyeMap = {
        sun: {
            layout: [ { symbol: 'VV', type: 'zhong' }, { symbol: 'TT', type: 'ju' }, { symbol: 'TS', type: 'ju' }, { symbol: 'ST', type: 'yi' }, { symbol: 'SV', type: 'ben' }, { symbol: 'SS', type: 'yi' }, { symbol: 'VT', type: 'tai' }, { symbol: 'VS', type: 'tai' }, { symbol: 'TV', type: 'hole' } ]
        },
        moon: {
             layout: [ { symbol: 'VV', type: 'hole' }, { symbol: 'TT', type: 'tai' }, { symbol: 'TS', type: 'tai' }, { symbol: 'ST', type: 'yi' }, { symbol: 'SV', type: 'ben' }, { symbol: 'SS', type: 'yi' }, { symbol: 'VT', type: 'ju' }, { symbol: 'VS', type: 'ju' }, { symbol: 'TV', type: 'zhong' } ]
        }
    };
    
    const nodePositions = {
        'VV': {x: 50, y: 10}, 'TT': {x: 25, y: 30}, 'TS': {x: 75, y: 30},
        'ST': {x: 10, y: 50}, 'SV': {x: 50, y: 50}, 'SS': {x: 90, y: 50},
        'VT': {x: 25, y: 70}, 'VS': {x: 75, y: 70}, 'TV': {x: 50, y: 90}
    };
    const nodeConnections = [
        ['VV','TT'], ['VV','TS'], ['TT','ST'], ['TT','SV'], ['TS','SV'], ['TS','SS'],
        ['ST','VT'], ['SV','VT'], ['SV','VS'], ['SS','VS'], ['VT','TV'], ['VS','TV']
    ];

    const quadrantConfig = {
        ne: { start: [0, 5], r_inc: 1, c_inc: -1, titleAcupoint: '土穴', rotation: 0 },
        se: { start: [5, 5], r_inc: -1, c_inc: -1, titleAcupoint: '水穴', rotation: 1 },
        sw: { start: [5, 0], r_inc: -1, c_inc: 1, titleAcupoint: '风穴', rotation: 2 },
        nw: { start: [0, 0], r_inc: 1, c_inc: 1, titleAcupoint: '火穴', rotation: 3 }
    };

    // =========================================================================
    // 2. CORE FUNCTIONS
    // =========================================================================
    
    function initializeGameState() {
        gameState = {
            phase: 'PLACE_EDICTS', draggedElement: null, placedEdicts: 0,
            ruling: elements.rulingSelector.value, jumpSelection: null,
            panStateBeforeJump: null, panStateAfterJump: null,
            currentGodsEyeView: 'before',
            hasJumped: false,
            quadrantData: {}
        };
        elements.downloadImageBtn.disabled = true;
    }

    function renderDaopanGrid() {
        elements.gridContainer.innerHTML = '';
        daopanData.layout.forEach((row, r) => {
            row.forEach((type, c) => {
                const cell = document.createElement('div');
                cell.className = `cell cell-${type}`;
                cell.dataset.cellType = type; cell.dataset.row = r; cell.dataset.col = c;
                const cellText = document.createElement('span');
                cellText.textContent = daopanData.cellTypeNames[type] || '';
                cell.appendChild(cellText);
                if (r >= 1 && r <= 4 && c >= 1 && c <= 4) {
                    cell.dataset.acupointName = daopanData.acupointLayout[r - 1][c - 1];
                }
                elements.gridContainer.appendChild(cell);
            });
        });
    }

    function renderEdictBank() {
        elements.edictBank.innerHTML = '';
        daopanData.fourEdicts.forEach(edict => {
            const card = document.createElement('div');
            card.className = 'edict-card'; card.textContent = edict.name;
            card.dataset.id = edict.id; card.draggable = true;
            elements.edictBank.appendChild(card);
        });
    }

    function clearAllInteractivity() {
        document.querySelectorAll('.cell').forEach(cell => {
            cell.classList.remove('clickable', 'droppable', 'jumpable', 'selected-for-jump');
        });
    }

    function updateInteractivity() {
        elements.phaseDisplay.textContent = phaseInstructions[gameState.phase];
        clearAllInteractivity();
        const config = {
            PLACE_EDICTS: { types: ['ben'], class: 'droppable', condition: (cell) => !cell.querySelector('.edict-card') },
            PLACE_GATES: { types: ['tai'], class: 'clickable' },
            PLACE_GENERALS: { types: ['ju', 'hole'], class: 'clickable' },
            PLACE_DIVISIONS: { types: ['zhong', 'yi'], class: 'clickable' }
        }[gameState.phase];

        if (config) {
            document.querySelectorAll('.cell').forEach(cell => {
                const type = cell.dataset.cellType;
                if (config.types.includes(type) && (config.condition ? config.condition(cell) : true)) {
                    cell.classList.add(config.class);
                }
            });
        }
    }
    
    function advancePhase() {
        const phaseOrder = ['PLACE_EDICTS', 'PLACE_GATES', 'PLACE_GENERALS', 'PLACE_DIVISIONS'];
        const currentIndex = phaseOrder.indexOf(gameState.phase);
        if (currentIndex === phaseOrder.length - 1) {
            gameState.phase = 'COMPLETE';
            updateInteractivity();
            elements.downloadImageBtn.disabled = false;
            const afterJumpButton = elements.godsEyeToggleButtons.querySelector('[data-view="after"]');
            afterJumpButton.classList.add('hidden');
            const beforeJumpButton = elements.godsEyeToggleButtons.querySelector('[data-view="before"]');
            elements.godsEyeToggleButtons.querySelectorAll('button').forEach(btn => btn.classList.remove('active'));
            beforeJumpButton.classList.add('active');
            elements.advancedPlayArea.classList.remove('hidden');
            gameState.panStateBeforeJump = capturePanState();
            generateAndStoreGodsEyeData('before');
            renderAllQuadrants();
            gameState.phase = 'JUMP_PAN';
            elements.phaseDisplay.textContent = phaseInstructions[gameState.phase];
            activateJumpPan();
        } else if (currentIndex < phaseOrder.length - 1) {
            gameState.phase = phaseOrder[currentIndex + 1];
            updateInteractivity();
        }
    }

    function resetBoard() {
        elements.gridContainer.classList.remove('show-acupoints');
        elements.toggleAcupointsBtn.textContent = '查看穴位';
        elements.rulingSelector.value = 'moon';
        elements.advancedPlayArea.classList.add('hidden');
        initializeGameState();
        renderDaopanGrid();
        renderEdictBank();
        updateInteractivity();
    }

    function openSelectionModal(title, options, callback) {
        elements.modal.title.textContent = title;
        elements.modal.optionsContainer.innerHTML = '';
        options.forEach((option, index) => {
            const button = document.createElement('div');
            button.className = 'modal-option';
            button.textContent = typeof option === 'string' ? option : option.name;
            button.onclick = () => { callback(index); closeModal(); };
            elements.modal.optionsContainer.appendChild(button);
        });
        elements.modal.overlay.classList.add('visible');
    }

    function closeModal() { elements.modal.overlay.classList.remove('visible'); }

    function performAutoPlacement(clickedCell, pathKey, dataArray) {
        const path = daopanData.paths[pathKey];
        if (!path) { return; }
        const startCellIndex = path.findIndex(([r, c]) => r == clickedCell.dataset.row && c == clickedCell.dataset.col);
        if (startCellIndex === -1) { return; }
        openSelectionModal(`为起始宫选择`, dataArray, (startDataIndex) => {
            path.forEach((coords, i) => {
                const [r, c] = coords;
                const cellToUpdate = document.querySelector(`.cell[data-row='${r}'][data-col='${c}']`);
                const dataOffset = (i - startCellIndex + dataArray.length) % dataArray.length;
                const currentDataIndex = (startDataIndex + dataOffset) % dataArray.length;
                const dataItem = dataArray[currentDataIndex];
                if (cellToUpdate) {
                    cellToUpdate._placedData = dataItem;
                    cellToUpdate.innerHTML = '';
                    const textSpan = document.createElement('span');
                    textSpan.textContent = dataItem.subName || (typeof dataItem === 'string' ? dataItem : dataItem.name);
                    cellToUpdate.appendChild(textSpan);
                }
            });
            advancePhase();
        });
    }

    function activateJumpPan() {
        clearAllInteractivity();
        document.querySelectorAll('.cell[data-cell-type="ben"]').forEach(cell => {
             cell.classList.add('jumpable');
        });
    }
    
    function findBenGongJumpPartners(cellA) {
        const typeA = cellA.dataset.cellType;
        if (typeA !== 'ben' || !cellA._placedData) return [];
        const edictTypeA = cellA._placedData.type;
        const ruling = gameState.ruling;
        let targetEdictType;
        if (ruling === 'moon') targetEdictType = (edictTypeA === 'A') ? 'B' : 'A';
        if (ruling === 'sun') targetEdictType = edictTypeA;
        const allBenGong = Array.from(document.querySelectorAll('.cell[data-cell-type="ben"]'));
        return allBenGong.filter(cellB => cellB !== cellA && cellB._placedData && cellB._placedData.type === targetEdictType);
    }
    
    function performAllJumps(cellA, cellB) {
        let tempPanState = capturePanState();
        const allBenGong = Array.from(document.querySelectorAll('.cell[data-cell-type="ben"]'));
        const remainingBenGong = allBenGong.filter(c => c !== cellA && c !== cellB);
        const pairs = [[cellA, cellB]];
        if(remainingBenGong.length === 2 && findBenGongJumpPartners(remainingBenGong[0]).includes(remainingBenGong[1])) {
            pairs.push(remainingBenGong);
        }

        pairs.forEach(pair => {
            const key1 = `${pair[0].dataset.row}-${pair[0].dataset.col}`;
            const key2 = `${pair[1].dataset.row}-${pair[1].dataset.col}`;
            const tempEdict = tempPanState[key1];
            tempPanState[key1] = tempPanState[key2];
            tempPanState[key2] = tempEdict;
        });
        
        elements.jumpPanInfo.textContent = `本宫联动交换完成！正在自动执行八门跳盘...`;

        const jumpRules = daopanData.jumpRules[gameState.ruling]['日月仪'];
        const jumpedAcupoints = new Set();
        for (const startAcupoint in jumpRules) {
            if (jumpedAcupoints.has(startAcupoint)) continue;
            const endAcupoint = jumpRules[startAcupoint];
            const startCell = findCellByAcupoint(startAcupoint);
            const endCell = findCellByAcupoint(endAcupoint);
            if(startCell && endCell) {
                const keyStart = `${startCell.dataset.row}-${startCell.dataset.col}`;
                const keyEnd = `${endCell.dataset.row}-${endCell.dataset.col}`;
                const tempGate = tempPanState[keyStart];
                tempPanState[keyStart] = tempPanState[keyEnd];
                tempPanState[keyEnd] = tempGate;
                jumpedAcupoints.add(startAcupoint);
                jumpedAcupoints.add(endAcupoint);
            }
        }
        
        gameState.panStateAfterJump = tempPanState;
        redrawPanFromState(gameState.panStateAfterJump);

        gameState.phase = 'COMPLETE';
        gameState.hasJumped = true;
        clearAllInteractivity();
        elements.phaseDisplay.textContent = "跳盘完成！";
        setTimeout(() => { elements.jumpPanInfo.textContent = ''; }, 2000);
        
        generateAndStoreGodsEyeData('after');
        
        const afterJumpButton = elements.godsEyeToggleButtons.querySelector('[data-view="after"]');
        afterJumpButton.classList.remove('hidden');
        elements.godsEyeToggleButtons.querySelectorAll('button').forEach(btn => btn.classList.remove('active'));
        afterJumpButton.classList.add('active');
        gameState.currentGodsEyeView = 'after';
        renderAllQuadrants();
    }
    
    function getAcupointNameForCell(cell) {
        const r = parseInt(cell.dataset.row), c = parseInt(cell.dataset.col);
        return (r >= 1 && r <= 4 && c >= 1 && c <= 4) ? daopanData.acupointLayout[r-1][c-1] : null;
    }

    function findCellByAcupoint(acupointName) {
        return document.querySelector(`.cell[data-acupoint-name="${acupointName}"]`);
    }

    function redrawPanFromState(panState) {
        document.querySelectorAll('.cell').forEach(cell => {
            const key = `${cell.dataset.row}-${cell.dataset.col}`;
            const data = panState[key];
            cell._placedData = data;
            if (data) {
                if (cell.querySelector('.edict-card')) {
                    const card = cell.querySelector('.edict-card');
                    card.dataset.id = data.id;
                    card.textContent = data.name;
                } else {
                    cell.innerHTML = '';
                    const textSpan = document.createElement('span');
                    textSpan.textContent = data.subName || data.name || data;
                    cell.appendChild(textSpan);
                }
            }
        });
    }

    function capturePanState() {
        const panState = {};
        document.querySelectorAll('.cell').forEach(cell => {
            panState[`${cell.dataset.row}-${cell.dataset.col}`] = cell._placedData;
        });
        return panState;
    }

    function generateAndStoreGodsEyeData(viewType) {
        const panState = viewType === 'before' ? gameState.panStateBeforeJump : gameState.panStateAfterJump;
        if (!panState) return;
        
        gameState.quadrantData[viewType] = {};
        const symbolLayout = godsEyeMap[gameState.ruling].layout;

        for (const [qKey, config] of Object.entries(quadrantConfig)) {
            let quadrantMatrix = [[], [], []];
            for (let i = 0; i < 3; i++) { for (let j = 0; j < 3; j++) {
                const r = config.start[0] + (i * config.r_inc);
                const c = config.start[1] + (j * config.c_inc);
                quadrantMatrix[i][j] = { key: `${r}-${c}`, type: daopanData.layout[r][c] };
            }}

            for (let i = 0; i < config.rotation; i++) {
                quadrantMatrix = quadrantMatrix[0].map((_, colIndex) => quadrantMatrix.map(row => row[colIndex]).reverse());
            }

            const temp = quadrantMatrix[0][0]; quadrantMatrix[0][0] = quadrantMatrix[0][2]; quadrantMatrix[0][2] = temp;
            const temp2 = quadrantMatrix[1][0]; quadrantMatrix[1][0] = quadrantMatrix[1][2]; quadrantMatrix[1][2] = temp2;
            const temp3 = quadrantMatrix[2][0]; quadrantMatrix[2][0] = quadrantMatrix[2][2]; quadrantMatrix[2][2] = temp3;
            
            gameState.quadrantData[viewType][qKey] = {};
            const filledPositions = new Set();
            symbolLayout.forEach(({ symbol, type }) => {
                const foundCell = quadrantMatrix.flat().find(cell => cell.type === type && !filledPositions.has(cell.key));
                if (foundCell) {
                    const cellData = panState[foundCell.key];
                    gameState.quadrantData[viewType][qKey][symbol] = cellData ? (cellData.subName || cellData.name || cellData) : '----';
                    filledPositions.add(foundCell.key);
                } else {
                    gameState.quadrantData[viewType][qKey][symbol] = '----';
                }
            });
        }
    }

    function renderQuadrant(quadrantEl, qData) {
        const display = quadrantEl.querySelector('.gods-eye-display');
        display.innerHTML = '';
        const svgNS = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(svgNS, 'svg');

        Object.entries(qData).forEach(([symbol, value]) => {
            if (value !== '----') {
                const pos = nodePositions[symbol];
                const nodeEl = document.createElement('div');
                nodeEl.className = `gods-eye-node symbol-${symbol.toLowerCase()}`;
                nodeEl.textContent = `[${value}]`;
                nodeEl.style.left = `${pos.x}%`;
                nodeEl.style.top = `${pos.y}%`;
                display.appendChild(nodeEl);
            }
        });

        nodeConnections.forEach(([from, to]) => {
            if (qData[from] !== '----' && qData[to] !== '----') {
                const pos1 = nodePositions[from];
                const pos2 = nodePositions[to];
                const line = document.createElementNS(svgNS, 'line');
                line.setAttribute('x1', `${pos1.x}%`);
                line.setAttribute('y1', `${pos1.y}%`);
                line.setAttribute('x2', `${pos2.x}%`);
                line.setAttribute('y2', `${pos2.y}%`);
                svg.appendChild(line);
            }
        });
        display.appendChild(svg);
    }
    
    function renderAllQuadrants() {
        const viewType = gameState.currentGodsEyeView;
        const allQuadrantsData = gameState.quadrantData[viewType];
        if (!allQuadrantsData) return;

        elements.godsEyeContainer.querySelectorAll('.quadrant').forEach(quadrantEl => {
            const qKey = quadrantEl.id.split('-')[1];
            const qData = allQuadrantsData[qKey];
            const titleEl = quadrantEl.querySelector('.quadrant-title');
            const titleAcupoint = quadrantConfig[qKey].titleAcupoint;
            titleEl.textContent = `${gameState.ruling === 'sun' ? '遁局 (偶遁-' : '遁局 (奇遁-'}${titleAcupoint})`;
            renderQuadrant(quadrantEl, qData);
        });
    }

    function downloadPanAsImage() {
        if (!gameState.panStateBeforeJump) { return; }
        const btn = elements.downloadImageBtn;
        const originalText = btn.textContent;
        btn.textContent = '正在生成...';
        btn.disabled = true;

        const container = document.createElement('div');
        container.style.position = 'absolute';
        container.style.left = '-9999px';
        container.style.backgroundColor = getComputedStyle(document.body).backgroundColor;
        container.style.padding = '20px';
        container.style.display = 'grid';
        container.style.gridTemplateColumns = '1fr 1fr';
        container.style.gap = '20px';
        container.style.width = '800px';

        const beforeContainer = document.getElementById('gods-eye-container').cloneNode(true);
        if(gameState.hasJumped) {
             const afterContainer = beforeContainer.cloneNode(true);
             container.appendChild(beforeContainer);
             container.appendChild(afterContainer);
             document.body.appendChild(container);
             renderGodsEyeView('before', beforeContainer);
             renderGodsEyeView('after', afterContainer);
        } else {
             container.style.gridTemplateColumns = '1fr';
             container.appendChild(beforeContainer);
             document.body.appendChild(container);
             renderGodsEyeView('before', beforeContainer);
        }

        html2canvas(container, { scale: 2 }).then(canvas => {
            const link = document.createElement('a');
            link.download = `daopan_result_${gameState.ruling}_${Date.now()}.png`;
            link.href = canvas.toDataURL('image/png');
            link.click();
            btn.textContent = originalText;
            btn.disabled = false;
            document.body.removeChild(container);
        }).catch(err => {
            console.error('图片生成失败:', err);
            btn.textContent = originalText;
            btn.disabled = false;
            document.body.removeChild(container);
        });
    }

    // =========================================================================
    // 3. EVENT HANDLERS
    // =========================================================================

    function handleDragStart(e) { if (e.target.classList.contains('edict-card')) { gameState.draggedElement = e.target; setTimeout(() => e.target.classList.add('dragging'), 0); } }
    function handleDragEnd(e) { if (e.target.classList.contains('edict-card')) { e.target.classList.remove('dragging'); } gameState.draggedElement = null; }
    
    function handleDrop(e) {
        e.preventDefault();
        const targetCell = e.target.closest('.cell');
        if (targetCell && targetCell.classList.contains('droppable') && gameState.draggedElement) {
            const edictData = daopanData.fourEdicts.find(ed => ed.id === gameState.draggedElement.dataset.id);
            if (edictData) {
                targetCell._placedData = edictData;
            }
            targetCell.innerHTML = '';
            targetCell.appendChild(gameState.draggedElement);
            targetCell.classList.remove('droppable');
            gameState.placedEdicts++;
            if (gameState.placedEdicts === 4) {
                advancePhase();
            }
        }
    }

    function handleCellClick(e) {
        const cell = e.target.closest('.cell');
        if (!cell) return;
        if (cell.classList.contains('clickable')) {
            const actions = {
                'PLACE_GATES': () => performAutoPlacement(cell, 'gates', daopanData.eightGates),
                'PLACE_GENERALS': () => { const generalsData = daopanData.divineGenerals[gameState.ruling]; performAutoPlacement(cell, 'generals', generalsData); },
                'PLACE_DIVISIONS': () => performAutoPlacement(cell, 'divisions', daopanData.divineDivisions)
            };
            if (actions[gameState.phase]) { actions[gameState.phase](); }
        } else if (cell.classList.contains('jumpable')) {
            handleJumpSelection(cell);
        }
    }

    function handleJumpSelection(cell) {
        if (gameState.hasJumped) return;
        
        if (gameState.jumpSelection) {
            if (cell.classList.contains('selected-for-jump') && cell !== gameState.jumpSelection) {
                 performAllJumps(gameState.jumpSelection, cell);
            } else {
                 document.querySelectorAll('.selected-for-jump').forEach(c => c.classList.remove('selected-for-jump'));
                 gameState.jumpSelection = null;
                 elements.jumpPanInfo.textContent = '';
            }
        } else {
            const partners = findBenGongJumpPartners(cell);
            if (partners.length > 0) {
                gameState.jumpSelection = cell;
                cell.classList.add('selected-for-jump');
                partners.forEach(p => p.classList.add('selected-for-jump'));
                elements.jumpPanInfo.textContent = `已选择“${cell.textContent}”，请在其他高亮单元格中选择交换对象。`;
            } else {
                elements.jumpPanInfo.textContent = '此令无合法交换对象。';
                setTimeout(() => { elements.jumpPanInfo.textContent = ''; }, 2000);
            }
        }
    }

    function handleMouseOver(e) {
        const cell = e.target.closest('.cell');
        if (!cell) return;
        let content = '';
        if (elements.gridContainer.classList.contains('show-acupoints')) {
            const acupointName = cell.dataset.acupointName;
            if (acupointName && daopanData.acupointDetails[acupointName]) {
                const data = daopanData.acupointDetails[acupointName];
                content = `<strong>${data.name}</strong><br>${data.type}<br><small>${data.detail}</small>`;
            }
        } else if (cell._placedData) {
            const data = cell._placedData;
            if (data.subName) { content = `<strong>${data.name} (${data.subName})</strong><br>属性: ${data.type} · ${data.star}<br><small>渴望: ${data.desire}</small>`; } 
            else if (data.scripture) { content = `<strong>${data.name}</strong><br><small>${data.scripture}</small>`; } 
            else if (data.description) { content = `<strong>${data.name}</strong><br><small>${data.description}</small>`; } 
            else if (typeof data === 'string') { content = `<strong>${data}</strong>`; }
        }
        if (content) {
            elements.tooltip.innerHTML = content;
            elements.tooltip.classList.add('visible');
        }
    }

    function handleMouseOut() { elements.tooltip.classList.remove('visible'); }
    function handleMouseMove(e) { if (elements.tooltip.classList.contains('visible')) { elements.tooltip.style.left = `${e.clientX + 15}px`; elements.tooltip.style.top = `${e.clientY + 15}px`; } }
    
    // =========================================================================
    // 4. INITIALIZATION
    // =========================================================================
    function initialize() {
        initializeGameState();
        renderDaopanGrid();
        renderEdictBank();
        updateInteractivity();
        
        elements.resetBtn.addEventListener('click', resetBoard);
        elements.toggleAcupointsBtn.addEventListener('click', () => {
            elements.gridContainer.classList.toggle('show-acupoints');
            elements.toggleAcupointsBtn.textContent = elements.gridContainer.classList.contains('show-acupoints') ? '返回道盘' : '查看穴位';
        });
        elements.rulingSelector.addEventListener('change', (e) => { 
            gameState.ruling = e.target.value;
            if (gameState.phase === 'COMPLETE' || gameState.phase === 'JUMP_PAN' || gameState.hasJumped) {
                generateAndStoreGodsEyeData('before');
                if(gameState.hasJumped) generateAndStoreGodsEyeData('after');
                renderAllQuadrants();
            }
        });
        elements.downloadImageBtn.addEventListener('click', downloadPanAsImage);
        
        elements.godsEyeContainer.addEventListener('click', (e) => {
            const flipBtn = e.target.closest('.flip-btn');
            if(flipBtn && (gameState.phase === 'JUMP_PAN' || gameState.hasJumped)) {
                const quadrantEl = flipBtn.closest('.quadrant');
                const qKey = quadrantEl.id.split('-')[1];
                const viewType = gameState.currentGodsEyeView;
                const qData = gameState.quadrantData[viewType][qKey];
                
                const tempTT = qData['TT']; qData['TT'] = qData['TS']; qData['TS'] = tempTT;
                const tempST = qData['ST']; qData['ST'] = qData['SS']; qData['SS'] = tempST;
                const tempVT = qData['VT']; qData['VT'] = qData['VS']; qData['VS'] = tempVT;

                renderQuadrant(quadrantEl, qData);
            }
        });

        const interactiveArea = document.getElementById('daopan-interactive-area');
        interactiveArea.addEventListener('dragstart', handleDragStart);
        interactiveArea.addEventListener('dragend', handleDragEnd);
        interactiveArea.addEventListener('dragover', (e) => e.preventDefault());
        interactiveArea.addEventListener('drop', handleDrop);
        
        elements.gridContainer.addEventListener('click', handleCellClick);
        elements.gridContainer.addEventListener('mouseover', handleMouseOver);
        elements.gridContainer.addEventListener('mouseout', handleMouseOut);
        document.addEventListener('mousemove', handleMouseMove);
        
        elements.modal.closeBtn.addEventListener('click', closeModal);
        elements.modal.overlay.addEventListener('click', (e) => { if (e.target === elements.modal.overlay) closeModal(); });
        
        elements.godsEyeToggleButtons.addEventListener('click', (e) => {
            const button = e.target.closest('button');
            if (!button || button.classList.contains('active') || button.classList.contains('hidden')) return;
            elements.godsEyeToggleButtons.querySelectorAll('button').forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            gameState.currentGodsEyeView = button.dataset.view;
            renderAllQuadrants();
        });
    }

    initialize();
});

// END OF FILE JS/daopan.js (FINAL AND TRULY COMPLETE VERSION)