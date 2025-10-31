// START OF FILE JS/daopan.js (FINAL VERSION WITH TOOLTIP)

document.addEventListener('DOMContentLoaded', () => {
    // 1. DOM ELEMENT REFERENCES
    const elements = {
        gridContainer: document.querySelector('.daopan-grid'),
        edictBank: document.getElementById('edict-bank'),
        toggleAcupointsBtn: document.getElementById('toggle-acupoints-btn'),
        resetBtn: document.getElementById('reset-daopan-btn'),
        phaseDisplay: document.querySelector('#current-phase-display p'),
        rulingSelector: document.getElementById('ruling-selector'),
        tooltip: document.getElementById('daopan-tooltip'),
        modal: {
            overlay: document.getElementById('selection-modal'),
            title: document.getElementById('modal-title'),
            optionsContainer: document.getElementById('modal-options-container'),
            closeBtn: document.getElementById('modal-close-btn')
        }
    };

    // 2. STATE MANAGEMENT
    let gameState = {};
    const phaseInstructions = {
        PLACE_EDICTS: '请拖拽“四令”至“本宫”',
        PLACE_GATES: '请点击“太宫”以布列八门',
        PLACE_GENERALS: '请点击“局宫”或“仪宫”以布列神将',
        PLACE_DIVISIONS: '请点击“重宫”或“义宫”以布列神部',
        COMPLETE: '道盘已成，请静观其变'
    };

    function initializeGameState() {
        gameState = {
            phase: 'PLACE_EDICTS',
            draggedElement: null,
            placedEdicts: 0,
            ruling: elements.rulingSelector.value
        };
    }

    // 3. RENDERING FUNCTIONS
    function renderDaopanGrid() {
        elements.gridContainer.innerHTML = '';
        daopanData.layout.forEach((row, r) => {
            row.forEach((type, c) => {
                const cell = document.createElement('div');
                cell.className = `cell cell-${type}`;
                cell.dataset.cellType = type;
                cell.dataset.row = r;
                cell.dataset.col = c;
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
            card.className = 'edict-card';
            card.textContent = edict.name;
            card.dataset.id = edict.id;
            card.draggable = true;
            elements.edictBank.appendChild(card);
        });
    }

    // 4. CORE LOGIC & STATE TRANSITIONS
    function clearAllInteractivity() {
        document.querySelectorAll('.cell').forEach(cell => {
            cell.classList.remove('clickable', 'droppable');
        });
    }

    function updateInteractivity() {
        elements.phaseDisplay.textContent = phaseInstructions[gameState.phase];
        clearAllInteractivity();

        const phaseConfig = {
            PLACE_EDICTS: { types: ['ben'], class: 'droppable', condition: (cell) => !cell.querySelector('.edict-card') },
            PLACE_GATES: { types: ['tai'], class: 'clickable' },
            PLACE_GENERALS: { types: ['ju', 'hole'], class: 'clickable' },
            PLACE_DIVISIONS: { types: ['zhong', 'yi'], class: 'clickable' }
        };

        const config = phaseConfig[gameState.phase];
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
        const phaseOrder = ['PLACE_EDICTS', 'PLACE_GATES', 'PLACE_GENERALS', 'PLACE_DIVISIONS', 'COMPLETE'];
        const currentIndex = phaseOrder.indexOf(gameState.phase);
        if (currentIndex < phaseOrder.length - 1) {
            gameState.phase = phaseOrder[currentIndex + 1];
        }
        updateInteractivity();
    }

    function resetBoard() {
        elements.gridContainer.classList.remove('show-acupoints');
        elements.toggleAcupointsBtn.textContent = '查看穴位';
        elements.rulingSelector.value = 'moon';
        initializeGameState();
        renderDaopanGrid();
        renderEdictBank();
        updateInteractivity();
    }

    // 5. DRAG & DROP LOGIC
    function handleDragStart(e) {
        if (e.target.classList.contains('edict-card')) {
            gameState.draggedElement = e.target;
            setTimeout(() => e.target.classList.add('dragging'), 0);
        }
    }

    function handleDragEnd(e) {
        if (e.target.classList.contains('edict-card')) {
            e.target.classList.remove('dragging');
        }
        gameState.draggedElement = null;
    }

    function handleDragOver(e) {
        e.preventDefault();
    }

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

    // 6. AUTO-PLACEMENT LOGIC & TOOLTIP
    function openSelectionModal(title, options, callback) {
        elements.modal.title.textContent = title;
        elements.modal.optionsContainer.innerHTML = '';
        options.forEach((option, index) => {
            const button = document.createElement('div');
            button.className = 'modal-option';
            button.textContent = typeof option === 'string' ? option : option.name;
            button.onclick = () => {
                callback(index);
                closeModal();
            };
            elements.modal.optionsContainer.appendChild(button);
        });
        elements.modal.overlay.classList.add('visible');
    }

    function closeModal() {
        elements.modal.overlay.classList.remove('visible');
    }

    function performAutoPlacement(clickedCell, pathKey, dataArray) {
        const path = daopanData.paths[pathKey];
        if (!path) { console.error(`路径未定义: ${pathKey}`); return; }

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

    function handleCellClick(e) {
        const cell = e.target.closest('.cell.clickable');
        if (!cell) return;
        
        const actions = {
            'PLACE_GATES': () => performAutoPlacement(cell, 'gates', daopanData.eightGates),
            'PLACE_GENERALS': () => {
                const generalsData = daopanData.divineGenerals[gameState.ruling];
                performAutoPlacement(cell, 'generals', generalsData);
            },
            'PLACE_DIVISIONS': () => performAutoPlacement(cell, 'divisions', daopanData.divineDivisions)
        };
        
        if (actions[gameState.phase]) {
            actions[gameState.phase]();
        }
    }

    function handleMouseOver(e) {
        const cell = e.target.closest('.cell');
        if (cell && cell._placedData) {
            const data = cell._placedData;
            let content = '';

            if (data.subName) {
                content = `<strong>${data.name} (${data.subName})</strong><br>属性: ${data.type} · ${data.star}`;
            } else if (data.scripture) {
                content = `<strong>${data.name}</strong><br><small>${data.scripture}</small>`;
            } else if (data.description) {
                content = `<strong>${data.name}</strong><br><small>${data.description}</small>`;
            } else if (typeof data === 'string') {
                content = `<strong>${data}</strong>`;
            }

            if (content) {
                elements.tooltip.innerHTML = content;
                elements.tooltip.classList.add('visible');
            }
        }
    }

    function handleMouseOut() {
        elements.tooltip.classList.remove('visible');
    }

    function handleMouseMove(e) {
        if (elements.tooltip.classList.contains('visible')) {
            elements.tooltip.style.left = `${e.clientX + 15}px`;
            elements.tooltip.style.top = `${e.clientY + 15}px`;
        }
    }

    // 7. INITIALIZATION & EVENT LISTENERS
    function initialize() {
        initializeGameState();
        renderDaopanGrid();
        renderEdictBank();
        updateInteractivity();

        elements.toggleAcupointsBtn.addEventListener('click', () => {
            elements.gridContainer.classList.toggle('show-acupoints');
            elements.toggleAcupointsBtn.textContent = elements.gridContainer.classList.contains('show-acupoints') ? '返回道盘' : '查看穴位';
        });

        elements.resetBtn.addEventListener('click', resetBoard);
        elements.rulingSelector.addEventListener('change', (e) => { gameState.ruling = e.target.value; });

        const interactiveArea = document.getElementById('daopan-interactive-area');
        interactiveArea.addEventListener('dragstart', handleDragStart);
        interactiveArea.addEventListener('dragend', handleDragEnd);
        interactiveArea.addEventListener('dragover', handleDragOver);
        interactiveArea.addEventListener('drop', handleDrop);

        elements.gridContainer.addEventListener('click', handleCellClick);
        elements.gridContainer.addEventListener('mouseover', handleMouseOver);
        elements.gridContainer.addEventListener('mouseout', handleMouseOut);
        document.addEventListener('mousemove', handleMouseMove);

        elements.modal.closeBtn.addEventListener('click', closeModal);
        elements.modal.overlay.addEventListener('click', (e) => { if (e.target === elements.modal.overlay) closeModal(); });
    }

    initialize();
});

// END OF FILE JS/daopan.js (FINAL VERSION WITH TOOLTIP)