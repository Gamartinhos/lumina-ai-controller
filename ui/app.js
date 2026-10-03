const API_BASE = '/api';

// --- TOAST NOTIFICATIONS (substitui alert()) ---
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) { console.log(message); return; }
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerText = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 250);
    }, 3500);
}

// --- MODO BLIND (Programação Cega) ---
let blindMode = false;
let blindPending = { r: null, g: null, b: null, intensity: null };

function toggleBlindMode(btn) {
    blindMode = !blindMode;
    btn.innerText = blindMode ? '🙈 MODO BLIND: ON' : '🙈 MODO BLIND: OFF';
    btn.style.background = blindMode ? 'var(--accent)' : 'rgba(255,255,255,0.05)';
    btn.style.color = blindMode ? '#000' : '';
    if (!blindMode && (blindPending.r !== null || blindPending.intensity !== null)) {
        applyBlindPending();
    }
    showToast(blindMode ? 'Modo Blind ativado: as próximas cores não vão pro palco até você desativar.' : 'Modo Blind desativado.', 'info');
}

async function applyBlindPending() {
    if (blindPending.r !== null) {
        await fetch(`${API_BASE}/color`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ r: blindPending.r, g: blindPending.g, b: blindPending.b }) });
    }
    if (blindPending.intensity !== null) {
        await fetch(`${API_BASE}/dimmer`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intensity: blindPending.intensity }) });
    }
    blindPending = { r: null, g: null, b: null, intensity: null };
    showToast('Cena aplicada ao palco!', 'success');
}

async function sendAction(endpoint) {
    try {
        await fetch(`${API_BASE}${endpoint.replace('/api', '')}`, {
            method: 'POST'
        });
    } catch (e) {
        console.error("Erro de conexão", e);
        showToast('Erro de conexão com o servidor.', 'error');
    }
}

async function sendColor(r, g, b) {
    if (blindMode) {
        blindPending.r = r; blindPending.g = g; blindPending.b = b;
        showToast('Cor armazenada (Modo Blind). Desative o Blind para aplicar.', 'info');
        return;
    }
    try {
        await fetch(`${API_BASE}/color`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ r, g, b })
        });
    } catch (e) {
        console.error(e);
        showToast('Erro ao enviar cor.', 'error');
    }
}

async function sendDimmer(val) {
    document.getElementById('dimmerVal').innerText = Math.round((val/255)*100) + '%';
    if (blindMode) {
        blindPending.intensity = parseInt(val);
        return;
    }
    await fetch(`${API_BASE}/dimmer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intensity: parseInt(val) })
    });
}

async function sendStrobe(val) {
    document.getElementById('strobeVal').innerText = val;
    await fetch(`${API_BASE}/strobe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ speed: parseInt(val) })
    });
}

// --- MASTER SPEED ---
async function sendMasterSpeed(val) {
    const factor = (parseInt(val) / 100).toFixed(2);
    document.getElementById('masterSpeedVal').innerText = factor + 'x';
    try {
        await fetch(`${API_BASE}/master_speed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ factor: parseFloat(factor) })
        });
    } catch (e) { console.error(e); }
}

// --- FLASH / OVERRIDE (Blinder momentâneo) ---
let flashActive = false;
async function startFlash() {
    if (flashActive) return;
    flashActive = true;
    try {
        await fetch(`${API_BASE}/flash`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on: true }) });
    } catch (e) { console.error(e); }
}
async function stopFlash() {
    if (!flashActive) return;
    flashActive = false;
    try {
        await fetch(`${API_BASE}/flash`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on: false }) });
    } catch (e) { console.error(e); }
}

// --- SHAPE GENERATOR (Pan/Tilt) ---
async function sendShape(shape) {
    try {
        await fetch(`${API_BASE}/shape`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ shape, speed: 1.0, size: 1.0 })
        });
        showToast(`Forma "${shape}" ativada nos moving heads.`, 'success');
    } catch (e) {
        console.error(e);
        showToast('Erro ao ativar forma.', 'error');
    }
}

// --- UNDO ("OOPS") ---
async function undoLastAiAction() {
    try {
        const res = await fetch(`${API_BASE}/undo`, { method: 'POST' });
        const data = await res.json();
        showToast(data.message, data.status === 'ok' ? 'success' : 'error');
    } catch (e) {
        showToast('Erro de conexão ao desfazer.', 'error');
    }
}

// --- STATUS LEDs (LLM Local / Art-Net) ---
async function pollStatus() {
    try {
        const res = await fetch(`${API_BASE}/status`);
        const data = await res.json();
        const ledLlm = document.getElementById('ledLlm');
        const ledArtnet = document.getElementById('ledArtnet');
        if (ledLlm) {
            ledLlm.classList.toggle('online', !!data.llm);
            ledLlm.classList.toggle('offline', !data.llm);
        }
        if (ledArtnet) {
            ledArtnet.classList.toggle('online', !!data.artnet);
            ledArtnet.classList.toggle('offline', !data.artnet);
        }
    } catch (e) {
        // silencioso, tenta de novo no próximo ciclo
    }
}
setInterval(pollStatus, 5000);
document.addEventListener('DOMContentLoaded', pollStatus);

// --- HOTKEYS (Barra de espaço = Blackout, 1-9 = cenas salvas) ---
document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

    if (e.code === 'Space') {
        e.preventDefault();
        sendAction('/api/blackout');
        showToast('Blackout (atalho de teclado)', 'info');
        return;
    }
    const num = parseInt(e.key);
    if (!isNaN(num) && num >= 1 && num <= 9) {
        const buttons = document.querySelectorAll('#aiButtonsContainer .btn-vibe');
        const target = buttons[num - 1];
        if (target) target.click();
    }
});

// --- COLOR WHEEL ---
function initColorWheel() {
    const canvas = document.getElementById('colorWheel');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const cx = w / 2, cy = h / 2, radius = w / 2;

    const image = ctx.createImageData(w, h);
    for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
            const dx = x - cx, dy = y - cy;
            const dist = Math.sqrt(dx * dx + dy * dy);
            const idx = (y * w + x) * 4;
            if (dist <= radius) {
                const angle = Math.atan2(dy, dx) * 180 / Math.PI;
                const hue = (angle + 360) % 360;
                const sat = Math.min(1, dist / radius);
                const [r, g, b] = hsvToRgb(hue, sat, 1);
                image.data[idx] = r;
                image.data[idx + 1] = g;
                image.data[idx + 2] = b;
                image.data[idx + 3] = 255;
            }
        }
    }
    ctx.putImageData(image, 0, 0);

    canvas.onclick = (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const dx = x - cx, dy = y - cy;
        if (Math.sqrt(dx * dx + dy * dy) > radius) return;
        const pixel = ctx.getImageData(x, y, 1, 1).data;
        sendColor(pixel[0], pixel[1], pixel[2]);
    };
}

function hsvToRgb(h, s, v) {
    const c = v * s;
    const x = c * (1 - Math.abs((h / 60) % 2 - 1));
    const m = v - c;
    let r = 0, g = 0, b = 0;
    if (h < 60) { r = c; g = x; }
    else if (h < 120) { r = x; g = c; }
    else if (h < 180) { g = c; b = x; }
    else if (h < 240) { g = x; b = c; }
    else if (h < 300) { r = x; b = c; }
    else { r = c; b = x; }
    return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
}

document.addEventListener('DOMContentLoaded', initColorWheel);

let autoDjActive = false;
async function toggleAutoDJ(btn) {
    autoDjActive = !autoDjActive;
    if (autoDjActive) {
        btn.style.background = 'var(--accent)';
        btn.style.color = '#000';
        btn.innerText = 'AUTO-DJ: ON';
    } else {
        btn.style.background = '';
        btn.style.color = '';
        btn.innerText = 'AUTO-DJ: OFF';
    }
    
    try {
        await fetch(`${API_BASE}/autodj`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: autoDjActive })
        });
    } catch (e) {
        console.error(e);
    }
}

// --- CHAT IA LOCAL ---
function handleChatEnter(event) {
    if (event.key === 'Enter') {
        sendChatMessage();
    }
}

async function sendChatMessage() {
    const input = document.getElementById('chatInput');
    const msg = input.value.trim();
    if (!msg) return;

    appendMessage(msg, 'user-msg');
    input.value = '';

    const thinkingEl = appendThinking();

    try {
        const response = await fetch(`${API_BASE}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg })
        });
        const data = await response.json();
        thinkingEl.remove();

        if (data.status === 'ok') {
            appendMessage(data.reply || 'Comando executado pela IA.', 'ai-msg');
            loadAiButtons();
        } else {
            appendMessage('Erro: ' + data.reply, 'ai-msg');
        }
    } catch (e) {
        thinkingEl.remove();
        appendMessage('Erro de conexão com o servidor local.', 'ai-msg');
    }
}

function appendThinking() {
    const box = document.getElementById('chatBox');
    const div = document.createElement('div');
    div.className = 'message ai-msg thinking-msg';
    div.innerHTML = '<span class="thinking-dot"></span><span class="thinking-dot"></span><span class="thinking-dot"></span>';
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    return div;
}

function appendMessage(text, className) {
    const box = document.getElementById('chatBox');
    const div = document.createElement('div');
    div.className = `message ${className}`;
    div.innerText = text;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
}

// --- MAPA DO PALCO 2D (FABRIC.JS) ---
let mapFixtures = [];
let canvas = null;

// Acesso estruturado ao palco virtual (usado pela IA e pelo futuro visualizador 3D).
// Lumina.stage.fixtures = snapshot das fixtures com posição real (x: -3..3, y: 0..5).
// Lumina.stage.capture() = valores DMX atuais de cada canal, direto do engine.
window.Lumina = window.Lumina || {};
Lumina.stage = {
    fixtures: [],
    async refresh() {
        const res = await fetch(`${API_BASE}/fixtures`);
        const data = await res.json();
        if (data.status === 'ok') this.fixtures = data.fixtures;
        return this.fixtures;
    },
    async capture() {
        const res = await fetch(`${API_BASE}/state/capture`);
        const data = await res.json();
        return data.status === 'ok' ? data.state : [];
    }
};

async function loadStageMap() {
    try {
        mapFixtures = await Lumina.stage.refresh();
        initFabricMap();
    } catch (e) {
        console.error('Erro ao carregar fixtures', e);
    }
}

function initFabricMap() {
    const mapDiv = document.getElementById('stageMap');
    const canvasElement = document.getElementById('stageMapCanvas');
    
    // Set internal canvas resolution to match the container
    const width = mapDiv.clientWidth || 300;
    const height = mapDiv.clientHeight || 300;
    canvasElement.width = width;
    canvasElement.height = height;

    if (canvas) {
        canvas.dispose();
    }

    canvas = new fabric.Canvas('stageMapCanvas', {
        selection: false, // desabilita seleção múltipla pra não bugar no mobile
        preserveObjectStacking: true
    });

    // Coordenadas reais simuladas: x = -4 a 4, y = 0 a 5
    mapFixtures.forEach(f => {
        const isMegaPar = f.type === 'MEGA_PAR_54';
        const percentX = (f.position.x + 3) / 6; 
        const percentY = f.position.y / 5;
        
        const pxX = percentX * width;
        const pxY = height - (percentY * height);

        let shape;
        if (isMegaPar) {
            shape = new fabric.Circle({
                radius: 12,
                fill: '#00f0ff',
                stroke: 'white',
                strokeWidth: 2,
                shadow: new fabric.Shadow({ color: 'rgba(255,255,255,0.5)', blur: 10 }),
                originX: 'center',
                originY: 'center',
                hasControls: false, // Só pode arrastar, não redimensionar
                hasBorders: false,
                fixtureId: f.id
            });
        } else {
            shape = new fabric.Rect({
                width: 24,
                height: 24,
                fill: '#ff003c',
                stroke: 'white',
                strokeWidth: 2,
                shadow: new fabric.Shadow({ color: 'rgba(255,255,255,0.5)', blur: 10 }),
                originX: 'center',
                originY: 'center',
                rx: 4,
                ry: 4,
                hasControls: false,
                hasBorders: false,
                fixtureId: f.id
            });
        }

        // Tooltip rudimentar desenhado no canvas
        const text = new fabric.Text(f.label, {
            fontSize: 10,
            fill: 'white',
            originX: 'center',
            originY: 'center',
            top: -20,
            backgroundColor: 'rgba(0,0,0,0.8)'
        });

        const group = new fabric.Group([shape, text], {
            left: pxX,
            top: pxY,
            originX: 'center',
            originY: 'center',
            hasControls: false,
            hasBorders: false,
            fixtureData: f // Salva a fixture para o drop
        });

        canvas.add(group);
    });

    // Clique simples para abrir modal individual da luz (ignora se foi um arrasto)
    let clickStartPoint = null;
    canvas.on('mouse:down', function(options) {
        clickStartPoint = options.pointer ? { x: options.pointer.x, y: options.pointer.y } : null;
    });
    canvas.on('mouse:up', function(options) {
        if (!options.target || !options.target.fixtureData || !clickStartPoint || !options.pointer) return;
        const dx = options.pointer.x - clickStartPoint.x;
        const dy = options.pointer.y - clickStartPoint.y;
        const movedDistance = Math.sqrt(dx * dx + dy * dy);
        if (movedDistance < 4) {
            openFixtureModal(options.target.fixtureData);
        }
    });

    // Evento de drop (ao soltar o mouse)
    canvas.on('object:modified', async function(options) {
        const target = options.target;
        if (!target || !target.fixtureData) return;

        const f = target.fixtureData;
        const pX = target.left / width;
        const pY = 1.0 - (target.top / height); 

        const realX = (pX * 6) - 3;
        const realY = pY * 5;

        f.position.x = realX;
        f.position.y = realY;

        await fetch(`${API_BASE}/update_position`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: f.id, x: realX, y: realY, z: f.position.z })
        });
    });
}

document.addEventListener('DOMContentLoaded', loadStageMap);
window.addEventListener('resize', () => {
    if (mapFixtures.length > 0) initFabricMap();
});

async function uploadBackground(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const formData = new FormData();
    formData.append("file", file);
    
    try {
        const response = await fetch(`${API_BASE}/upload_bg`, {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        if (data.status === 'ok') {
            const mapDiv = document.getElementById('stageMap');
            mapDiv.style.backgroundImage = `url('bg.jpg?t=${new Date().getTime()}')`;
        } else {
            showToast('Erro ao subir a planta.', 'error');
        }
    } catch (e) {
        console.error(e);
        showToast('Erro de conexão ao enviar a planta.', 'error');
    }
}

// --- BOTÕES INTELIGENTES (IA) ---
async function loadAiButtons() {
    try {
        const response = await fetch(`${API_BASE}/buttons`);
        const data = await response.json();
        const container = document.getElementById('aiButtonsContainer');
        if (!container) return;
        
        container.innerHTML = '';
        if (data.buttons && data.buttons.length > 0) {
            data.buttons.forEach((b, index) => {
                const wrapper = document.createElement('div');
                wrapper.style.display = 'flex';
                wrapper.style.gap = '4px';

                const btn = document.createElement('button');
                btn.className = 'btn btn-vibe';
                btn.style.flex = '1';
                btn.style.background = 'rgba(0, 240, 255, 0.1)';
                btn.style.border = '1px solid rgba(0, 240, 255, 0.3)';
                if (b.is_sequence) {
                    btn.innerHTML = `<span>${b.name}</span><small>Sequência · right-click p/ editar</small>`;
                    btn.onclick = () => executeAiButton(b);
                    // Right-click: abre a cena na Timeline para edição/overwrite
                    btn.oncontextmenu = (e) => {
                        e.preventDefault();
                        if (typeof editSceneInTimeline === 'function') editSceneInTimeline(index, b);
                    };
                } else {
                    btn.innerHTML = `<span>${b.name}</span><small>Efeito IA</small>`;
                    btn.onclick = () => executeAiButton(b);
                }

                const delBtn = document.createElement('button');
                delBtn.className = 'btn';
                delBtn.style.padding = '0 8px';
                delBtn.style.background = 'rgba(255, 0, 0, 0.2)';
                delBtn.style.border = '1px solid rgba(255, 0, 0, 0.4)';
                delBtn.style.color = '#ff6b6b';
                delBtn.innerText = 'X';
                delBtn.title = 'Excluir efeito';
                delBtn.onclick = (e) => { e.stopPropagation(); deleteAiButton(index); };

                wrapper.appendChild(btn);
                wrapper.appendChild(delBtn);
                container.appendChild(wrapper);
            });
        } else {
            container.innerHTML = '<small style="color: var(--text-muted);">Peça para a IA criar um botão de efeito no chat!</small>';
        }
    } catch (e) {
        console.error("Erro ao carregar botões:", e);
    }
}

async function deleteAiButton(index) {
    try {
        const response = await fetch(`${API_BASE}/buttons/${index}`, { method: 'DELETE' });
        const data = await response.json();
        if (data.status === 'ok') {
            loadAiButtons();
        } else {
            showToast('Erro ao excluir efeito.', 'error');
        }
    } catch (e) {
        console.error('Erro ao excluir botão:', e);
    }
}

async function executeAiButton(btnData) {
    if (btnData.is_sequence) {
        appendMessage(`Rodando Sequência: ${btnData.name}`, 'user-msg');
        try {
            await fetch(`${API_BASE}/sequences/play`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ steps: btnData.steps })
            });
        } catch (e) { console.error(e); }
        return;
    }

    appendMessage(`Executando: ${btnData.prompt}`, 'user-msg');
    try {
        const response = await fetch(`${API_BASE}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: btnData.prompt })
        });
        const data = await response.json();
        if (data.status === 'ok') {
            appendMessage(data.reply || 'Comando executado.', 'ai-msg');
        }
    } catch (e) {
        console.error(e);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadAiButtons();
});

// --- PATCH FIXTURES (FREESTYLER STYLE) ---
let libraryFixtures = [];

async function openPatchModal() {
    document.getElementById('patchModal').style.display = 'flex';
    const select = document.getElementById('fxtSelect');
    select.innerHTML = '<option>Carregando...</option>';
    
    try {
        const response = await fetch(`${API_BASE}/fixtures/library`);
        const data = await response.json();
        
        if (data.status === 'ok') {
            libraryFixtures = data.library;
            select.innerHTML = '';
            if (libraryFixtures.length === 0) {
                select.innerHTML = '<option>Nenhum .fxt encontrado na pasta</option>';
            } else {
                libraryFixtures.forEach(f => {
                    const opt = document.createElement('option');
                    opt.value = f.id;
                    opt.innerText = `${f.filename} (${f.total_channels} canais)`;
                    select.appendChild(opt);
                });
            }
        }
    } catch (e) {
        select.innerHTML = '<option>Erro ao carregar</option>';
    }
}

function closePatchModal() {
    document.getElementById('patchModal').style.display = 'none';
}

async function submitPatch() {
    const select = document.getElementById('fxtSelect');
    const fxtId = select.value;
    const qty = parseInt(document.getElementById('fxtQuantity').value) || 1;
    
    if (!fxtId || fxtId.startsWith('Nenhum') || fxtId.startsWith('Erro')) return;
    
    const fxt = libraryFixtures.find(f => f.id === fxtId);
    if (!fxt) return;
    
    try {
        const response = await fetch(`${API_BASE}/patch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: fxt.filename,
                quantity: qty,
                total_channels: fxt.total_channels,
                fxt_name: fxt.name,
                fxt_id: fxt.id
            })
        });
        const data = await response.json();
        if (data.status === 'ok') {
            showToast(`Patch de ${qty}x ${fxt.name} realizado com sucesso!`, 'success');
            closePatchModal();
            loadStageMap(); // Recarrega as posições na tela principal
        } else {
            showToast('Erro no Patch: ' + data.message, 'error');
        }
    } catch (e) {
        showToast('Erro de conexão ao realizar o patch.', 'error');
    }
}

// --- CONTROLE INDIVIDUAL DO FIXTURE ---
let currentFixtureId = null;

function openFixtureModal(fixture) {
    currentFixtureId = fixture.id;
    document.getElementById('fixtureModalTitle').innerText = `${fixture.label} (${fixture.type})`;
    document.getElementById('fixtureModal').style.display = 'flex';
}

function closeFixtureModal() {
    document.getElementById('fixtureModal').style.display = 'none';
    currentFixtureId = null;
}

async function submitFixtureColor() {
    if (!currentFixtureId) return;
    const dimmer = parseInt(document.getElementById('fixDimmer').value);
    const r = parseInt(document.getElementById('fixR').value);
    const g = parseInt(document.getElementById('fixG').value);
    const b = parseInt(document.getElementById('fixB').value);
    
    try {
        const response = await fetch(`${API_BASE}/fixture_color`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: currentFixtureId, r, g, b, dimmer })
        });
        const data = await response.json();
        if (data.status === 'ok') {
            closeFixtureModal();
        } else {
            showToast('Erro ao atualizar luz.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão.', 'error');
    }
}

// --- MAPA / MANUAL TOGGLE ---
function toggleMainArea() {
    const manual = document.getElementById('manualControlArea');
    const btnToggle = document.getElementById('btnToggleMain');

    if (manual.style.display !== 'flex') {
        manual.style.display = 'flex';
        btnToggle.innerText = '🔽 Fechar Sequencer & XY Pad';
        populateManualFixtures();
    } else {
        manual.style.display = 'none';
        btnToggle.innerText = '▶ Abrir Sequencer & XY Pad';
    }
}

// --- XY PAD (PAN / TILT) ---
let isDraggingXY = false;
let xyTimeout = null;
let currentPan = 127;
let currentTilt = 127;

function populateManualFixtures() {
    const select = document.getElementById('manualFixtureSelect');
    select.innerHTML = '<option value="">(Selecione um aparelho)</option>';
    mapFixtures.forEach(f => {
        const opt = document.createElement('option');
        opt.value = f.id;
        opt.innerText = `${f.label} (${f.type})`;
        select.appendChild(opt);
    });
}

function updateXYFromFixture() {
    // Placeholder: futuramente lê o Pan/Tilt atual da fixture via Lumina.stage.capture()
}

function startPanTiltDrag(e) {
    isDraggingXY = true;
    doPanTiltDrag(e);
}

function stopPanTiltDrag(e) {
    isDraggingXY = false;
}

function doPanTiltDrag(e) {
    if (!isDraggingXY) return;
    const container = document.getElementById('xyPadContainer');
    const cursor = document.getElementById('xyCursor');
    const rect = container.getBoundingClientRect();
    
    let x = e.clientX - rect.left;
    let y = e.clientY - rect.top;
    
    x = Math.max(0, Math.min(rect.width, x));
    y = Math.max(0, Math.min(rect.height, y));
    
    const pan = Math.round((x / rect.width) * 255);
    const tilt = Math.round((1 - (y / rect.height)) * 255); // y=0 é tilt=255

    setXYVisual(pan, tilt);

    if (xyTimeout) clearTimeout(xyTimeout);
    xyTimeout = setTimeout(() => {
        sendPanTilt(pan, tilt);
    }, 40); // 40ms debounce
}

// Atualiza cursor, crosshairs, label e o preview 3D a partir de valores DMX (0-255)
function setXYVisual(pan, tilt) {
    currentPan = Math.max(0, Math.min(255, Math.round(pan)));
    currentTilt = Math.max(0, Math.min(255, Math.round(tilt)));

    const container = document.getElementById('xyPadContainer');
    const cursor = document.getElementById('xyCursor');
    const crossX = document.getElementById('xyCrosshairX');
    const crossY = document.getElementById('xyCrosshairY');

    const px = (currentPan / 255) * 100;
    const py = (1 - currentTilt / 255) * 100;
    if (cursor) { cursor.style.left = px + '%'; cursor.style.top = py + '%'; }
    if (crossX) crossX.style.top = py + '%';
    if (crossY) crossY.style.left = px + '%';

    const lbl = document.getElementById('xyVal');
    if (lbl) lbl.innerText = `Pan: ${currentPan} | Tilt: ${currentTilt}`;

    // Preview instantâneo no visualizador 3D (sem esperar o round-trip do servidor)
    const fId = document.getElementById('manualFixtureSelect')?.value;
    if (fId && window.Lumina && Lumina.viz3d) Lumina.viz3d.setPanTilt(fId, currentPan, currentTilt);
}

// Botão Home/Center: volta a mira para o centro (127/127)
function centerPanTilt() {
    setXYVisual(127, 127);
    sendPanTilt(127, 127);
}

// Ajuste fino: dPan/dTilt em passos de ±1 DMX
function nudgePanTilt(dPan, dTilt) {
    setXYVisual(currentPan + dPan, currentTilt + dTilt);
    if (xyTimeout) clearTimeout(xyTimeout);
    xyTimeout = setTimeout(() => sendPanTilt(currentPan, currentTilt), 40);
}

async function sendPanTilt(pan, tilt) {
    const fId = document.getElementById('manualFixtureSelect').value;
    if (!fId) return;
    
    try {
        await fetch(`${API_BASE}/fixture_pantilt`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: fId, pan, tilt })
        });
    } catch (e) {
        console.error("Erro no XY Pad", e);
    }
}

// ==========================================
// SUBMASTERS (Faders de Grupo com HTP)
// ==========================================

async function loadSubmasters() {
    try {
        const res = await fetch(`${API_BASE}/submasters`);
        const data = await res.json();
        if (data.status !== 'ok') return;

        const container = document.getElementById('submastersContainer');
        if (!container) return;
        container.innerHTML = '';

        // Grupos relevantes (ignora 'todos' que já tem o dimmer geral)
        const groups = (data.groups || []).filter(g => g !== 'todos');
        if (typeof registerSubmasterMidiActions === 'function') registerSubmasterMidiActions(groups);

        groups.forEach(g => {
            const level = (data.submasters && data.submasters[g] !== undefined) ? data.submasters[g] : 1.0;
            const col = document.createElement('div');
            col.className = 'submaster-col';
            col.innerHTML = `
                <span class="submaster-val" id="subVal_${g}">${Math.round(level * 100)}%</span>
                <input type="range" min="0" max="100" value="${Math.round(level * 100)}"
                    class="submaster-fader" data-submaster="${g}"
                    oninput="onSubmasterInput('${g}', this.value)">
                <span class="submaster-name">${g.replace('auto_', '')}</span>
            `;
            container.appendChild(col);
        });
    } catch (e) {
        console.error('Erro ao carregar submasters', e);
    }
}

function onSubmasterInput(group, val) {
    const level = parseInt(val) / 100;
    const lbl = document.getElementById(`subVal_${group}`);
    if (lbl) lbl.innerText = Math.round(level * 100) + '%';
    setSubmasterLevel(group, level);
}

let subThrottle = {};
function setSubmasterLevel(group, level) {
    // Preferência: WebSocket (latência mínima). Fallback: POST com throttle.
    if (window.Lumina && Lumina.sendWS({ type: 'submaster', group, level })) return;

    if (subThrottle[group]) clearTimeout(subThrottle[group]);
    subThrottle[group] = setTimeout(() => {
        fetch(`${API_BASE}/submaster`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group, level })
        }).catch(() => {});
    }, 60);
}

async function runAutoGroup() {
    try {
        const res = await fetch(`${API_BASE}/auto_group`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ k: 3 })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast('Auto-grouping K-Means aplicado! Novos submasters criados.', 'success');
            loadSubmasters();
        }
    } catch (e) {
        showToast('Erro no auto-grouping.', 'error');
    }
}

document.addEventListener('DOMContentLoaded', loadSubmasters);

// ==========================================
// FIXTURE BUILDER (criar aparelho DMX do zero, drag-and-drop de canais)
// ==========================================

const BUILDER_CHANNEL_TYPES = ['dimmer', 'red', 'green', 'blue', 'amber', 'white', 'strobe', 'pan', 'pan_fine', 'tilt', 'tilt_fine', 'color', 'gobo', 'speed', 'effects', 'auto', 'reset'];
let builderChannels = []; // [{name, offset}]

function openBuilderModal() {
    document.getElementById('builderModal').style.display = 'flex';
    builderChannels = [];
    renderBuilderPalette();
    renderBuilderSlots();
}

function closeBuilderModal() {
    document.getElementById('builderModal').style.display = 'none';
}

function renderBuilderPalette() {
    const palette = document.getElementById('builderPalette');
    palette.innerHTML = '';
    BUILDER_CHANNEL_TYPES.forEach(name => {
        if (builderChannels.some(c => c.name === name)) return; // já usado
        const chip = document.createElement('div');
        chip.className = 'builder-chip';
        chip.draggable = true;
        chip.innerText = name;
        chip.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('text/plain', name);
            e.dataTransfer.effectAllowed = 'copy';
        });
        chip.onclick = () => addBuilderChannel(name); // fallback mobile: toque adiciona
        palette.appendChild(chip);
    });
}

function addBuilderChannel(name) {
    if (builderChannels.some(c => c.name === name)) return;
    builderChannels.push({ name, offset: builderChannels.length + 1 });
    renderBuilderPalette();
    renderBuilderSlots();
}

function renderBuilderSlots() {
    const slots = document.getElementById('builderSlots');
    slots.innerHTML = '';

    if (builderChannels.length === 0) {
        slots.innerHTML = '<div style="color:#666; font-size:0.85em; text-align:center; padding: 16px;">Arraste os canais da paleta para cá.<br>Ordem = canal DMX.</div>';
    }

    builderChannels.forEach((c, idx) => {
        const row = document.createElement('div');
        row.className = 'builder-slot';
        row.innerHTML = `
            <span class="builder-slot-num">CH ${c.offset}</span>
            <span style="flex:1;">${c.name}</span>
        `;
        const del = document.createElement('button');
        del.className = 'btn';
        del.style.cssText = 'padding:0 8px; font-size:0.75em; background: rgba(255,0,0,0.2); color:#ff6b6b;';
        del.innerText = 'X';
        del.onclick = () => {
            builderChannels.splice(idx, 1);
            builderChannels.forEach((cc, i) => cc.offset = i + 1); // re-endereça
            renderBuilderPalette();
            renderBuilderSlots();
        };
        row.appendChild(del);
        slots.appendChild(row);
    });

    // Zona de drop
    slots.ondragover = (e) => { e.preventDefault(); slots.classList.add('drop-hover'); };
    slots.ondragleave = () => slots.classList.remove('drop-hover');
    slots.ondrop = (e) => {
        e.preventDefault();
        slots.classList.remove('drop-hover');
        const name = e.dataTransfer.getData('text/plain');
        if (name) addBuilderChannel(name);
    };
    document.getElementById('builderTotal').innerText = builderChannels.length;
}

async function submitBuilder() {
    const id = document.getElementById('builderId').value.trim();
    const name = document.getElementById('builderName').value.trim();
    if (!id || !name) { showToast('Preencha ID e nome do aparelho.', 'error'); return; }
    if (builderChannels.length === 0) { showToast('Adicione pelo menos um canal.', 'error'); return; }

    const channels = {};
    builderChannels.forEach(c => channels[c.name] = c.offset);

    try {
        const res = await fetch(`${API_BASE}/fixtures/builder`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fxt_id: id, name, channels, total_channels: builderChannels.length })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(`Fixture "${name}" criada no fixtures.json (${builderChannels.length} canais)!`, 'success');
            closeBuilderModal();
        } else {
            showToast('Erro: ' + data.message, 'error');
        }
    } catch (e) {
        showToast('Erro de conexão ao criar fixture.', 'error');
    }
}
