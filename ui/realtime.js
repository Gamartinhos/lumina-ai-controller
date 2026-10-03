// ==========================================
// REALTIME.JS — Cliente WebSocket (sincronização instantânea)
// Substitui o polling: se o DJ muda algo no celular, o PC do VJ vê na hora.
// ==========================================

const Lumina = window.Lumina || {};
window.Lumina = Lumina;

Lumina.ws = null;
Lumina.wsReady = false;
let wsReconnectDelay = 1000;

function connectLuminaWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    try {
        Lumina.ws = new WebSocket(`${proto}://${location.host}/ws`);
    } catch (e) {
        scheduleWSReconnect();
        return;
    }

    Lumina.ws.onopen = () => {
        Lumina.wsReady = true;
        wsReconnectDelay = 1000;
        const led = document.getElementById('ledWs');
        if (led) { led.classList.add('online'); led.classList.remove('offline'); }
        console.log('[Lumina WS] Conectado');
    };

    Lumina.ws.onclose = () => {
        Lumina.wsReady = false;
        const led = document.getElementById('ledWs');
        if (led) { led.classList.remove('online'); led.classList.add('offline'); }
        scheduleWSReconnect();
    };

    Lumina.ws.onerror = () => { try { Lumina.ws.close(); } catch (e) {} };

    Lumina.ws.onmessage = (msg) => {
        let ev;
        try { ev = JSON.parse(msg.data); } catch (e) { return; }
        handleRealtimeEvent(ev);
    };
}

function scheduleWSReconnect() {
    setTimeout(connectLuminaWS, wsReconnectDelay);
    wsReconnectDelay = Math.min(wsReconnectDelay * 2, 10000);
}

Lumina.sendWS = function (obj) {
    if (Lumina.wsReady && Lumina.ws && Lumina.ws.readyState === WebSocket.OPEN) {
        Lumina.ws.send(JSON.stringify(obj));
        return true;
    }
    return false;
};

// --- Reação a eventos vindos do servidor (outros clientes / engine) ---
function handleRealtimeEvent(ev) {
    switch (ev.type) {
        case 'beat':
        case 'audio_trigger': {
            const dot = document.getElementById('beatDot');
            if (dot) {
                dot.classList.add('pulse');
                setTimeout(() => dot.classList.remove('pulse'), 120);
            }
            break;
        }
        case 'buttons_changed':
            if (typeof loadAiButtons === 'function') loadAiButtons();
            break;
        case 'submaster': {
            // Sincroniza o fader do submaster em todas as telas abertas
            const slider = document.querySelector(`input[data-submaster="${ev.group}"]`);
            if (slider && Math.abs(parseFloat(slider.value) - ev.level * 100) > 1) {
                slider.value = Math.round(ev.level * 100);
                const lbl = document.getElementById(`subVal_${ev.group}`);
                if (lbl) lbl.innerText = Math.round(ev.level * 100) + '%';
            }
            break;
        }
        case 'color': {
            // Feedback visual sutil de que outro cliente mudou a cor
            const wrapper = document.getElementById('colorWheelWrapper');
            if (wrapper) {
                wrapper.style.boxShadow = `0 0 18px rgb(${ev.r},${ev.g},${ev.b})`;
                setTimeout(() => { wrapper.style.boxShadow = ''; }, 600);
            }
            if (Lumina.viz3d) Lumina.viz3d.setAllColor(ev.r, ev.g, ev.b);
            break;
        }
        case 'pantilt':
            // Move a cabeça no visualizador 3D e sincroniza o XY Pad de outras telas
            if (Lumina.viz3d) Lumina.viz3d.setPanTilt(ev.id, ev.pan, ev.tilt);
            {
                const sel = document.getElementById('manualFixtureSelect');
                const dragging = (typeof isDraggingXY !== 'undefined') && isDraggingXY;
                if (sel && sel.value === ev.id && typeof setXYVisual === 'function' && !dragging) {
                    setXYVisual(ev.pan, ev.tilt);
                }
            }
            break;
        case 'fixture_color':
            if (Lumina.viz3d) Lumina.viz3d.setColor(ev.id, ev.r, ev.g, ev.b, ev.dimmer);
            break;
        case 'chase_step':
            if (Lumina.viz3d) Lumina.viz3d.setChaseStep(ev.ids, ev.active_id, ev.r, ev.g, ev.b);
            break;
        case 'group_color':
            if (Lumina.viz3d) Lumina.viz3d.setAllColor(ev.r, ev.g, ev.b);
            break;
        case 'dimmer':
            if (Lumina.viz3d) Lumina.viz3d.setAllDimmer(ev.intensity);
            break;
        case 'blackout':
            if (Lumina.viz3d) Lumina.viz3d.blackout();
            break;
        case 'auto_group':
            if (typeof showToast === 'function') showToast('Luzes reagrupadas automaticamente (K-Means).', 'success');
            if (typeof loadSubmasters === 'function') loadSubmasters();
            break;
        case 'sequence_step':
            if (typeof highlightTimelineStep === 'function') highlightTimelineStep(ev.index, ev.total);
            break;
        case 'sequence_done':
        case 'sequence_stopped':
            if (typeof onSequenceStopped === 'function') onSequenceStopped();
            break;
    }
}

document.addEventListener('DOMContentLoaded', connectLuminaWS);
