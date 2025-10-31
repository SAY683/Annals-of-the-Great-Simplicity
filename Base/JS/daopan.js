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
        quadrantTitles: document.querySelectorAll('.quadrant-title'),
        quadrantDisplays: document.querySelectorAll('.gods-eye-display'),
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
            layout: [
                { symbol: 'VV', type: 'zhong' }, { symbol: 'TT', type: 'ju' }, 
                { symbol: 'TS', type: 'ju' }, { symbol: 'ST', type: 'yi' }, 
                { symbol: 'SV', type: 'ben' }, { symbol: 'SS', type: 'yi' }, 
                { symbol: 'VT', type: 'tai' }, { symbol: 'VS', type: 'tai' }, 
                { symbol: 'TV', type: 'hole' }
            ],
            grid: [
                { s: 'VV', r: 1, c: 3 }, { s: '/', r: 2, c: 2 }, { s: '\\', r: 2, c: 4 },
                { s: 'TT', r: 3, c: 2 }, { s: 'TS', r: 3, c: 4 }, 
                { s: '/', r: 4, c: 1 }, { s: '\\', r: 4, c: 3 }, { s: '/', r: 4, c: 3 }, { s: '\\', r: 4, c: 5 },
                { s: 'ST', r: 5, c: 1 }, { s: 'SV', r: 5, c: 3 }, { s: 'SS', r: 5, c: 5 }, 
                { s: '\\', r: 6, c: 2 }, { s: '/', r: 6, c: 4 },
                { s: 'VT', r: 7, c: 2 }, { s: 'VS', r: 7, c: 4 }, 
                { s: '\\', r: 8, c: 3 }, { s: '/', r: 8, c: 3 }, // Special case for combined slash
                { s: 'TV', r: 9, c: 3 }
            ]
        },
        moon: {
             layout: [
                { symbol: 'VV', type: 'hole' }, { symbol: 'TT', type: 'tai' }, 
                { symbol: 'TS', type: 'tai' }, { symbol: 'ST', type: 'yi' }, 
                { symbol: 'SV', type: 'ben' }, { symbol: 'SS', type: 'yi' }, 
                { symbol: 'VT', type: 'ju' }, { symbol: 'VS', type: 'ju' }, 
                { symbol: 'TV', type: 'zhong' }
            ],
            grid: [ // The visual grid layout is the same for both
                { s: 'VV', r: 1, c: 3 }, { s: '/', r: 2, c: 2 }, { s: '\\', r: 2, c: 4 },
                { s: 'TT', r: 3, c: 2 }, { s: 'TS', r: 3, c: 4 }, 
                { s: '/', r: 4, c: 1 }, { s: '\\', r: 4, c: 3 }, { s: '/', r: 4, c: 3 }, { s: '\\', r: 4, c: 5 },
                { s: 'ST', r: 5, c: 1 }, { s: 'SV', r: 5, c: 3 }, { s: 'SS', r: 5, c: 5 }, 
                { s: '\\', r: 6, c: 2 }, { s: '/', r: 6, c: 4 },
                { s: 'VT', r: 7, c: 2 }, { s: 'VS', r: 7, c: 4 }, 
                { s: '\\', r: 8, c: 3 }, { s: '/', r: 8, c: 3 },
                { s: 'TV', r: 9, c: 3 }
            ]
        }
    };

    const quadrantConfig = {
        ne: { start: [0, 5], r_inc: 1, c_inc: -1, titleAcupoint: '土穴' },
        se: { start: [5, 5], r_inc: -1, c_inc: -1, titleAcupoint: '水穴' },
        sw: { start: [5, 0], r_inc: -1, c_inc: 1, titleAcupoint: '风穴' },
        nw: { start: [0, 0], r_inc: 1, c_inc: 1, titleAcupoint: '火穴' }
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
            hasJumped: false
        };
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
            const afterJumpButton = elements.godsEyeToggleButtons.querySelector('[data-view="after"]');
            afterJumpButton.classList.add('hidden');
            const beforeJumpButton = elements.godsEyeToggleButtons.querySelector('[data-view="before"]');
            elements.godsEyeToggleButtons.querySelectorAll('button').forEach(btn => btn.classList.remove('active'));
            beforeJumpButton.classList.add('active');
            elements.advancedPlayArea.classList.remove('hidden');
            gameState.panStateBeforeJump = capturePanState();
            renderGodsEyeView('before');
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

    function findBenGongJumpPartner(cellA) {
        const typeA = cellA.dataset.cellType;
        if (typeA !== 'ben' || !cellA._placedData) return null;
        
        const edictTypeA = cellA._placedData.type;
        const ruling = gameState.ruling;
        let targetEdictType;
        if (ruling === 'moon') targetEdictType = (edictTypeA === 'A') ? 'B' : 'A';
        if (ruling === 'sun') targetEdictType = edictTypeA;
        
        const allBenGong = Array.from(document.querySelectorAll('.cell[data-cell-type="ben"]'));
        return allBenGong.find(cellB => cellB !== cellA && cellB._placedData && cellB._placedData.type === targetEdictType);
    }
    
    function performAllJumps(cellA, cellB) {
        let tempPanState = capturePanState();
        const allBenGong = Array.from(document.querySelectorAll('.cell[data-cell-type="ben"]'));
        const remainingBenGong = allBenGong.filter(c => c !== cellA && c !== cellB);
        const pairs = [[cellA, cellB]];
        if(remainingBenGong.length === 2 && findBenGongJumpPartner(remainingBenGong[0]) === remainingBenGong[1]) {
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
        const afterJumpButton = elements.godsEyeToggleButtons.querySelector('[data-view="after"]');
        afterJumpButton.classList.remove('hidden');
        elements.godsEyeToggleButtons.querySelectorAll('button').forEach(btn => btn.classList.remove('active'));
        afterJumpButton.classList.add('active');
        gameState.currentGodsEyeView = 'after';
        renderGodsEyeView('after');
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

    function generateGodsEyeData(panState) {
        const symbolLayout = godsEyeMap[gameState.ruling].layout;
        const quadrants = {};
        
        for (const [qKey, config] of Object.entries(quadrantConfig)) {
            quadrants[qKey] = {};
            const qCells = [];
            for (let i = 0; i < 3; i++) { for (let j = 0; j < 3; j++) {
                const r = config.start[0] + (i * config.r_inc);
                const c = config.start[1] + (j * config.c_inc);
                if (r >= 0 && r <= 5 && c >= 0 && c <= 5) qCells.push({r, c});
            }}
            
            const filledPositions = new Set();
            symbolLayout.forEach(({ symbol, type }) => {
                const foundCell = qCells.find(cell => {
                    const key = `${cell.r}-${cell.c}`;
                    return daopanData.layout[cell.r][cell.c] === type && !filledPositions.has(key);
                });

                if (foundCell) {
                    const key = `${foundCell.r}-${foundCell.c}`;
                    const cellData = panState[key];
                    quadrants[qKey][symbol] = cellData ? (cellData.subName || cellData.name || cellData) : '----';
                    filledPositions.add(key);
                } else {
                    quadrants[qKey][symbol] = '----';
                }
            });
        }
        return quadrants;
    }

    function renderGodsEyeView(viewType) {
        const panState = viewType === 'before' ? gameState.panStateBeforeJump : gameState.panStateAfterJump;
        if (!panState) return;

        const godsEyeData = generateGodsEyeData(panState);
        const gridLayout = godsEyeMap[gameState.ruling].grid;

        elements.quadrantDisplays.forEach((display, index) => {
            const qKey = Object.keys(quadrantConfig)[index];
            const qData = godsEyeData[qKey];
            const titleAcupoint = quadrantConfig[qKey].titleAcupoint;
            elements.quadrantTitles[index].textContent = `${gameState.ruling === 'sun' ? '遁局 (偶遁-' : '遁局 (奇遁-'}${titleAcupoint})`;
            
            display.innerHTML = '';
            
            const createSpan = (text, className, gridArea) => {
                const el = document.createElement('span');
                if (className) el.className = className;
                el.textContent = text;
                el.style.gridArea = gridArea;
                display.appendChild(el);
            };

            const symbols = ['VV','TT','TS','ST','SV','SS','VT','VS','TV'];
            const gridPositions = {
                'VV': '1 / 3', 'TT': '3 / 2', 'TS': '3 / 4', 'ST': '5 / 1', 'SV': '5 / 3',
                'SS': '5 / 5', 'VT': '7 / 2', 'VS': '7 / 4', 'TV': '9 / 3'
            };
            const slashes = [
                {p: '2 / 2', c: '/'}, {p: '2 / 4', c: '\\'}, {p: '4 / 1', c: '/'}, 
                {p: '4 / 2', c: '\\'}, {p: '4 / 4', c: '/'}, {p: '4 / 5', c: '\\'},
                {p: '6 / 2', c: '\\'}, {p: '6 / 4', c: '/'}, {p: '8 / 3', c: '\\ /'}
            ];
            
            symbols.forEach(s => {
                const content = qData[s] || '----';
                createSpan(`[${content}]`, `symbol-${s.toLowerCase()}`, gridPositions[s]);
            });

            slashes.forEach(slash => {
                 createSpan(slash.c, 'slash', slash.p);
            });
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
        const partner = findBenGongJumpPartner(cell);
        if (partner) {
            document.querySelectorAll('.selected-for-jump').forEach(c => c.classList.remove('selected-for-jump'));
            elements.jumpPanInfo.textContent = `确认将“${cell.textContent}”与“${partner.textContent}”联动交换？点击任一高亮处确认。`;
            cell.classList.add('selected-for-jump');
            partner.classList.add('selected-for-jump');
            
            const confirmationHandler = (e) => {
                const confirmCell = e.target.closest('.selected-for-jump');
                document.querySelectorAll('.selected-for-jump').forEach(c => c.classList.remove('selected-for-jump'));
                elements.jumpPanInfo.textContent = '';
                if (confirmCell) {
                    performAllJumps(cell, partner);
                }
                document.body.removeEventListener('click', bodyClickHandler, { capture: true });
            };
            const bodyClickHandler = (e) => {
                if (!e.target.closest('.selected-for-jump')) {
                    confirmationHandler({}); // Simulate a cancel click
                }
            };
            
            setTimeout(() => {
                elements.gridContainer.addEventListener('click', confirmationHandler, { once: true });
                document.body.addEventListener('click', bodyClickHandler, { capture: true, once: true });
            }, 0);

        } else {
            elements.jumpPanInfo.textContent = '此令无合法交换对象。';
            setTimeout(() => { elements.jumpPanInfo.textContent = ''; }, 2000);
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
                renderGodsEyeView(gameState.currentGodsEyeView);
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
            renderGodsEyeView(gameState.currentGodsEyeView);
        });
    }

    initialize();
});

// END OF FILE JS/daopan.js (FINAL AND TRULY COMPLETE VERSION)