// ==========================================
// MIDI.JS — Web MIDI API (controladores físicos, ex: AKAI APC Mini)
// Modo "MIDI Learn": clique em Learn numa ação, aperte o botão/fader físico.
// Mapeamentos persistidos em localStorage.
// ==========================================

let midiAccess = null;
let midiLearnAction = null; // ação aguardando aprendizado
const MIDI_MAP_KEY = 'lumina_midi_map';

// Ações mapeáveis. CC (faders) usam handler com valor 0-127; notas disparam trigger.
const MIDI_ACTIONS = {
    'blackout':   { label: 'Blackout',           trigger: () => sendAction('/api/blackout') },
    'flash_on':   { label: 'Flash / Blinder',    trigger: () => { startFlash(); setTimeout(stopFlash, 250); } },
    'autodj':     { label: 'Auto-DJ Toggle',     trigger: () => { const b = document.querySelector('.btn-primary'); if (b) toggleAutoDJ(b); } },
    'soundlight': { label: 'Sound-to-Light',     trigger: () => toggleSoundToLight() },
    'scene_1':    { label: 'Cena 1',             trigger: () => clickScene(0) },
    'scene_2':    { label: 'Cena 2',             trigger: () => clickScene(1) },
    'scene_3':    { label: 'Cena 3',             trigger: () => clickScene(2) },
    'scene_4':    { label: 'Cena 4',             trigger: () => clickScene(3) },
    'scene_5':    { label: 'Cena 5',             trigger: () => clickScene(4) },
    'dimmer':     { label: 'Dimmer Geral (CC)',  cc: (v) => sendDimmer(Math.round(v / 127 * 255)) },
    'strobe':     { label: 'Strobe Geral (CC)',  cc: (v) => sendStrobe(Math.round(v / 127 * 255)) },
    'speed':      { label: 'Master Speed (CC)',  cc: (v) => sendMasterSpeed(Math.round(10 + (v / 127) * 290)) },
};

// Submasters entram dinamicamente: midi action id = 'sub_<grupo>'
function registerSubmasterMidiActions(groups) {
    groups.forEach(g => {
        MIDI_ACTIONS[`sub_${g}`] = {
            label: `Submaster ${g} (CC)`,
            cc: (v) => setSubmasterLevel(g, v / 127)
        };
    });
}

function clickScene(idx) {
    const buttons = document.querySelectorAll('#aiButtonsContainer .btn-vibe');
    if (buttons[idx]) buttons[idx].click();
}

function getMidiMap() {
    try { return JSON.parse(localStorage.getItem(MIDI_MAP_KEY)) || {}; }
    catch (e) { return {}; }
}

function saveMidiMap(map) {
    localStorage.setItem(MIDI_MAP_KEY, JSON.stringify(map));
}

async function initMidi() {
    if (!navigator.requestMIDIAccess) {
        showToast('Web MIDI não suportado neste navegador (use Chrome/Edge).', 'error');
        return false;
    }
    try {
        midiAccess = await navigator.requestMIDIAccess();
    } catch (e) {
        showToast('Permissão MIDI negada.', 'error');
        return false;
    }

    const attach = () => {
        midiAccess.inputs.forEach(input => { input.onmidimessage = onMidiMessage; });
    };
    attach();
    midiAccess.onstatechange = attach; // replug do controlador

    const count = midiAccess.inputs.size;
    showToast(`MIDI ativo: ${count} dispositivo(s) de entrada.`, count > 0 ? 'success' : 'info');
    return true;
}

function onMidiMessage(msg) {
    const [status, data1, data2] = msg.data;
    const cmd = status & 0xF0;

    let key = null, isCC = false, value = data2;
    if (cmd === 0x90 && data2 > 0) {           // Note On
        key = `note:${data1}`;
    } else if (cmd === 0xB0) {                  // Control Change (faders/knobs)
        key = `cc:${data1}`;
        isCC = true;
    } else {
        return;
    }

    // Modo Learn: associa a próxima mensagem à ação pendente
    if (midiLearnAction) {
        const map = getMidiMap();
        // remove associações antigas dessa ação
        for (const k of Object.keys(map)) {
            if (map[k] === midiLearnAction) delete map[k];
        }
        map[key] = midiLearnAction;
        saveMidiMap(map);
        showToast(`MIDI ${key} mapeado para "${MIDI_ACTIONS[midiLearnAction].label}"`, 'success');
        midiLearnAction = null;
        renderMidiModal();
        return;
    }

    const map = getMidiMap();
    const actionId = map[key];
    if (!actionId || !MIDI_ACTIONS[actionId]) return;

    const action = MIDI_ACTIONS[actionId];
    if (isCC && action.cc) {
        action.cc(value);
    } else if (!isCC && action.trigger) {
        action.trigger();
    }
}

// --- UI do modal MIDI ---
async function openMidiModal() {
    const ok = midiAccess || await initMidi();
    document.getElementById('midiModal').style.display = 'flex';
    renderMidiModal();
}

function closeMidiModal() {
    document.getElementById('midiModal').style.display = 'none';
    midiLearnAction = null;
}

function renderMidiModal() {
    const list = document.getElementById('midiActionsList');
    if (!list) return;
    const map = getMidiMap();
    const bound = {};
    for (const [k, a] of Object.entries(map)) bound[a] = k;

    list.innerHTML = '';
    for (const [id, action] of Object.entries(MIDI_ACTIONS)) {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex; align-items:center; gap:8px; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.06);';

        const learning = midiLearnAction === id;
        row.innerHTML = `
            <span style="flex:1; font-size:0.9em;">${action.label}</span>
            <span style="font-size:0.75em; color: var(--text-muted); min-width: 70px;">${bound[id] || '—'}</span>
        `;
        const btn = document.createElement('button');
        btn.className = 'btn';
        btn.style.cssText = `padding: 2px 10px; font-size: 0.75em; ${learning ? 'background: var(--accent); color:#000;' : 'background: rgba(255,255,255,0.08);'}`;
        btn.innerText = learning ? 'Aperte no controlador...' : 'Learn';
        btn.onclick = () => {
            midiLearnAction = learning ? null : id;
            renderMidiModal();
        };
        row.appendChild(btn);

        if (bound[id]) {
            const del = document.createElement('button');
            del.className = 'btn';
            del.style.cssText = 'padding:2px 8px; font-size:0.75em; background: rgba(255,0,0,0.2); color:#ff6b6b;';
            del.innerText = 'X';
            del.onclick = () => {
                const m = getMidiMap();
                delete m[bound[id]];
                saveMidiMap(m);
                renderMidiModal();
            };
            row.appendChild(del);
        }
        list.appendChild(row);
    }
}

// Auto-inicializa MIDI silenciosamente se já houver mapeamentos salvos
document.addEventListener('DOMContentLoaded', () => {
    if (Object.keys(getMidiMap()).length > 0 && navigator.requestMIDIAccess) {
        initMidi();
    }
});
