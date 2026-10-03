// ==========================================
// TIMELINE.JS — Sequenciador visual estilo editor de vídeo
// Blocos arrastáveis (HTML5 Drag-and-Drop) com Fade-In, Hold e Snap.
// Também suporta EDITAR cenas existentes (right-click no botão da cena).
// ==========================================

let timelineSteps = [];          // [{time_ms, fade_ms, state, _color}]
let editingButtonIndex = null;   // != null => sobrescreve buttons.json ao salvar
let selectedStepIndex = null;
let dragSrcIndex = null;

const TIMELINE_PX_PER_SEC = 80;  // escala horizontal
const TIMELINE_SNAP_MS = 100;    // snap de tempos

function snapMs(ms) {
    return Math.max(TIMELINE_SNAP_MS, Math.round(ms / TIMELINE_SNAP_MS) * TIMELINE_SNAP_MS);
}

// --- Captura o estado atual do palco como um novo bloco ---
function addTimelineStep() {
    const hold = snapMs(parseInt(document.getElementById('stepTime').value) || 500);

    fetch('/api/state/capture')
        .then(res => res.json())
        .then(data => {
            if (data.status === 'ok') {
                timelineSteps.push({
                    time_ms: hold,
                    fade_ms: parseInt(document.getElementById('stepFade').value) || 0,
                    state: data.state,
                    _color: stepDominantColor(data.state)
                });
                renderTimeline();
            } else {
                showToast('Erro ao capturar passo.', 'error');
            }
        })
        .catch(e => showToast('Erro ao capturar passo: ' + e, 'error'));
}

// Extrai uma cor representativa do estado (pro bloco na timeline)
function stepDominantColor(state) {
    let r = 0, g = 0, b = 0, n = 0;
    (state || []).forEach(f => {
        const ch = f.channels || {};
        if ('red' in ch || 'green' in ch || 'blue' in ch) {
            r += ch.red || 0; g += ch.green || 0; b += ch.blue || 0; n++;
        }
    });
    if (n === 0) return '#555';
    return `rgb(${Math.round(r / n)},${Math.round(g / n)},${Math.round(b / n)})`;
}

// --- Renderização da Timeline ---
function renderTimeline() {
    const track = document.getElementById('timelineTrack');
    if (!track) return;

    if (timelineSteps.length === 0) {
        track.innerHTML = '<div style="color:#666; font-size:0.85em; padding: 20px; text-align:center; width: 100%;">Timeline vazia. Monte uma cena no palco e clique "+ Capturar Passo".</div>';
        updateTimelineInfo();
        return;
    }

    track.innerHTML = '';
    timelineSteps.forEach((s, idx) => {
        const block = document.createElement('div');
        block.className = 'tl-block' + (idx === selectedStepIndex ? ' selected' : '');
        block.draggable = true;
        block.dataset.index = idx;

        const totalMs = (s.fade_ms || 0) + (s.time_ms || 500);
        const width = Math.max(48, (totalMs / 1000) * TIMELINE_PX_PER_SEC);
        block.style.width = width + 'px';

        const fadePct = Math.round(((s.fade_ms || 0) / totalMs) * 100);
        block.innerHTML = `
            <div class="tl-fade" style="width:${fadePct}%;"></div>
            <div class="tl-body" style="--step-color:${s._color || stepDominantColor(s.state)};">
                <span class="tl-label">${idx + 1}</span>
                <span class="tl-times">${s.fade_ms ? '⤳' + s.fade_ms + ' ' : ''}⏱${s.time_ms}ms</span>
            </div>
        `;

        // Drag-and-Drop nativo HTML5 (reordenar blocos)
        block.addEventListener('dragstart', (e) => {
            dragSrcIndex = idx;
            e.dataTransfer.effectAllowed = 'move';
            block.classList.add('dragging');
        });
        block.addEventListener('dragend', () => block.classList.remove('dragging'));
        block.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            block.classList.add('drop-target');
        });
        block.addEventListener('dragleave', () => block.classList.remove('drop-target'));
        block.addEventListener('drop', (e) => {
            e.preventDefault();
            block.classList.remove('drop-target');
            if (dragSrcIndex === null || dragSrcIndex === idx) return;
            const moved = timelineSteps.splice(dragSrcIndex, 1)[0];
            timelineSteps.splice(idx, 0, moved);
            if (selectedStepIndex === dragSrcIndex) selectedStepIndex = idx;
            dragSrcIndex = null;
            renderTimeline();
        });

        // Clique: seleciona bloco e abre o editor granular
        block.addEventListener('click', () => {
            selectedStepIndex = (selectedStepIndex === idx) ? null : idx;
            renderTimeline();
            renderStepEditor();
        });

        track.appendChild(block);
    });
    updateTimelineInfo();
    renderStepEditor();
}

function updateTimelineInfo() {
    const info = document.getElementById('timelineInfo');
    if (!info) return;
    const total = timelineSteps.reduce((acc, s) => acc + (s.fade_ms || 0) + (s.time_ms || 0), 0);
    const mode = editingButtonIndex !== null ? ` | ✏️ Editando cena #${editingButtonIndex + 1}` : '';
    info.innerText = `${timelineSteps.length} passos | ${(total / 1000).toFixed(1)}s${mode}`;
}

// --- Editor granular do bloco selecionado (Fade / Hold / cor / excluir) ---
function renderStepEditor() {
    const panel = document.getElementById('stepEditor');
    if (!panel) return;
    if (selectedStepIndex === null || !timelineSteps[selectedStepIndex]) {
        panel.style.display = 'none';
        return;
    }
    const s = timelineSteps[selectedStepIndex];
    panel.style.display = 'flex';
    document.getElementById('editFade').value = s.fade_ms || 0;
    document.getElementById('editHold').value = s.time_ms || 500;
}

function applyStepEdit() {
    if (selectedStepIndex === null) return;
    const s = timelineSteps[selectedStepIndex];
    s.fade_ms = Math.max(0, parseInt(document.getElementById('editFade').value) || 0);
    s.time_ms = snapMs(parseInt(document.getElementById('editHold').value) || 500);
    renderTimeline();
}

function applyColorToStep(r, g, b) {
    // Modifica a cor de todas as fixtures RGB dentro do step selecionado
    if (selectedStepIndex === null) return;
    const s = timelineSteps[selectedStepIndex];
    (s.state || []).forEach(f => {
        const ch = f.channels || {};
        if ('red' in ch) ch.red = r;
        if ('green' in ch) ch.green = g;
        if ('blue' in ch) ch.blue = b;
    });
    s._color = `rgb(${r},${g},${b})`;
    renderTimeline();
    showToast('Cor do passo alterada.', 'success');
}

function deleteSelectedStep() {
    if (selectedStepIndex === null) return;
    timelineSteps.splice(selectedStepIndex, 1);
    selectedStepIndex = null;
    renderTimeline();
}

function duplicateSelectedStep() {
    if (selectedStepIndex === null) return;
    const copy = JSON.parse(JSON.stringify(timelineSteps[selectedStepIndex]));
    timelineSteps.splice(selectedStepIndex + 1, 0, copy);
    renderTimeline();
}

// Destaque do passo em execução (evento sequence_step via WS)
function highlightTimelineStep(index, total) {
    document.querySelectorAll('#timelineTrack .tl-block').forEach((el, i) => {
        el.classList.toggle('playing', i === index);
    });
    // Scroll automático para o bloco ativo
    const active = document.querySelector('#timelineTrack .tl-block.playing');
    if (active) active.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
}

function onSequenceStopped() {
    // Limpa highlights
    document.querySelectorAll('#timelineTrack .tl-block').forEach(el => el.classList.remove('playing'));
    // Reseta botão play para estado parado
    _setPlayButtonState(false);
}

let _isPlayingTimeline = false;

function _setPlayButtonState(playing) {
    _isPlayingTimeline = playing;
    const btn = document.getElementById('tlPlayBtn');
    if (!btn) return;
    btn.textContent = playing ? '⏸' : '▶';
    btn.title = playing ? 'Parar' : 'Preview (uma passagem)';
    btn.style.background = playing ? 'rgba(255,60,60,0.25)' : 'rgba(255,255,255,0.08)';
}

// --- Preview / Play ---
async function previewTimeline() {
    if (timelineSteps.length === 0) { showToast('Timeline vazia.', 'error'); return; }

    if (_isPlayingTimeline) {
        // Segundo clique = PARAR
        await stopTimeline();
        return;
    }

    _setPlayButtonState(true);
    await fetch(`${API_BASE}/sequences/play`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ steps: timelineSteps, loop: false })
    });
    showToast('Reproduzindo timeline...', 'info');
}

async function stopTimeline() {
    await fetch(`${API_BASE}/sequences/stop`, { method: 'POST' });
    showToast('Sequência parada.', 'info');
    // onSequenceStopped será chamado pelo WS, mas garantimos UI limpa aqui também
    onSequenceStopped();
}

async function loopTimeline() {
    if (timelineSteps.length === 0) { showToast('Timeline vazia.', 'error'); return; }
    if (_isPlayingTimeline) { await stopTimeline(); return; }
    _setPlayButtonState(true);
    await fetch(`${API_BASE}/sequences/play`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ steps: timelineSteps, loop: true })
    });
    showToast('Loop ativado...', 'info');
}

// --- Salvar (nova cena OU sobrescrever cena em edição) ---
async function saveTimeline() {
    const name = document.getElementById('seqName').value.trim();
    if (!name) { showToast('Dê um nome para a sequência!', 'error'); return; }
    if (timelineSteps.length === 0) { showToast('Adicione pelo menos um passo!', 'error'); return; }

    // remove metadados internos (_color) antes de persistir
    const cleanSteps = timelineSteps.map(s => ({ time_ms: s.time_ms, fade_ms: s.fade_ms || 0, state: s.state }));

    try {
        let res;
        if (editingButtonIndex !== null) {
            res = await fetch(`${API_BASE}/buttons/${editingButtonIndex}`, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, steps: cleanSteps })
            });
        } else {
            res = await fetch(`${API_BASE}/sequences`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, steps: cleanSteps, is_sequence: true })
            });
        }
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(editingButtonIndex !== null ? 'Cena sobrescrita com sucesso!' : 'Sequência salva com sucesso!', 'success');
            clearTimeline();
            loadAiButtons();
        } else {
            showToast('Erro ao salvar: ' + (data.message || ''), 'error');
        }
    } catch (e) {
        showToast('Erro de conexão.', 'error');
    }
}

function clearTimeline() {
    timelineSteps = [];
    editingButtonIndex = null;
    selectedStepIndex = null;
    document.getElementById('seqName').value = '';
    renderTimeline();
}

// --- Edição de cena existente (chamado pelo right-click no botão) ---
function editSceneInTimeline(index, btnData) {
    if (!btnData.is_sequence || !Array.isArray(btnData.steps)) {
        showToast('Só cenas do tipo sequência podem ser editadas na timeline.', 'error');
        return;
    }
    timelineSteps = JSON.parse(JSON.stringify(btnData.steps));
    timelineSteps.forEach(s => { s._color = stepDominantColor(s.state); });
    editingButtonIndex = index;
    selectedStepIndex = null;
    document.getElementById('seqName').value = btnData.name || '';

    // Garante que a área do sequenciador esteja visível
    const manual = document.getElementById('manualControlArea');
    if (manual && manual.style.display !== 'flex' && typeof toggleMainArea === 'function') {
        toggleMainArea();
    }
    renderTimeline();
    showToast(`Editando cena "${btnData.name}" na timeline. Salve para sobrescrever.`, 'info');
}

document.addEventListener('DOMContentLoaded', renderTimeline);
