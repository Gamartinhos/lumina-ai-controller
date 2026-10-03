// ==========================================
// SOUNDLIGHT.JS — Sound-to-Light via Web Audio API (FFT no navegador)
// Capta o microfone, separa Graves/Médios/Agudos e envia triggers em
// tempo real pro backend via WebSocket (que aciona grupos diferentes).
// ==========================================

let slAudioCtx = null;
let slAnalyser = null;
let slStream = null;
let slActive = false;
let slRafId = null;

// Detecção de onset por banda: média móvel + fator de sensibilidade
const slBands = {
    bass: { lo: 20,   hi: 250,  avg: 0, lastTrigger: 0, factor: 1.45, minInterval: 120 },
    mid:  { lo: 250,  hi: 2000, avg: 0, lastTrigger: 0, factor: 1.60, minInterval: 160 },
    high: { lo: 2000, hi: 8000, avg: 0, lastTrigger: 0, factor: 1.70, minInterval: 110 },
};

async function toggleSoundToLight(btn) {
    btn = btn || document.getElementById('btnSoundLight');
    if (slActive) {
        stopSoundToLight(btn);
    } else {
        await startSoundToLight(btn);
    }
}

async function startSoundToLight(btn) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showToast('Microfone não disponível neste navegador.', 'error');
        return;
    }
    try {
        slStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false }
        });
    } catch (e) {
        showToast('Permissão de microfone negada.', 'error');
        return;
    }

    slAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source = slAudioCtx.createMediaStreamSource(slStream);
    slAnalyser = slAudioCtx.createAnalyser();
    slAnalyser.fftSize = 2048;
    slAnalyser.smoothingTimeConstant = 0.4;
    source.connect(slAnalyser);

    slActive = true;
    if (btn) {
        btn.innerText = '🎵 SOUND-TO-LIGHT: ON';
        btn.style.background = 'var(--accent)';
        btn.style.color = '#000';
    }

    // Avisa o backend para começar a reagir aos triggers
    await fetch('/api/sound_to_light', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: true })
    }).catch(() => {});

    slLoop();
    showToast('Sound-to-Light ativo: graves → pars, médios → parede, agudos → strobo dos movings.', 'success');
}

function stopSoundToLight(btn) {
    slActive = false;
    if (slRafId) cancelAnimationFrame(slRafId);
    if (slStream) slStream.getTracks().forEach(t => t.stop());
    if (slAudioCtx) slAudioCtx.close().catch(() => {});
    slAudioCtx = null; slAnalyser = null; slStream = null;

    if (btn) {
        btn.innerText = '🎵 SOUND-TO-LIGHT: OFF';
        btn.style.background = '';
        btn.style.color = '';
    }
    fetch('/api/sound_to_light', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: false })
    }).catch(() => {});
}

function slLoop() {
    if (!slActive || !slAnalyser) return;

    const binCount = slAnalyser.frequencyBinCount;
    const data = new Uint8Array(binCount);
    slAnalyser.getByteFrequencyData(data);

    const nyquist = slAudioCtx.sampleRate / 2;
    const binHz = nyquist / binCount;
    const now = performance.now();

    for (const [name, band] of Object.entries(slBands)) {
        const loBin = Math.max(0, Math.floor(band.lo / binHz));
        const hiBin = Math.min(binCount - 1, Math.ceil(band.hi / binHz));

        let sum = 0;
        for (let i = loBin; i <= hiBin; i++) sum += data[i];
        const energy = sum / (hiBin - loBin + 1) / 255; // 0..1

        // média móvel exponencial (baseline do ambiente)
        band.avg = band.avg * 0.95 + energy * 0.05;

        // Onset: energia estoura acima da média => trigger
        const threshold = Math.max(0.06, band.avg * band.factor);
        if (energy > threshold && (now - band.lastTrigger) > band.minInterval) {
            band.lastTrigger = now;
            Lumina.sendWS({ type: 'audio_band', band: name, energy: Math.min(1, energy * 1.5) });
            slPulseMeter(name, energy);
        }
        slUpdateMeter(name, energy);
    }

    slRafId = requestAnimationFrame(slLoop);
}

// --- Medidores visuais (barras de banda no painel) ---
function slUpdateMeter(band, energy) {
    const bar = document.getElementById(`meter_${band}`);
    if (bar) bar.style.height = Math.round(Math.min(1, energy * 1.6) * 100) + '%';
}

function slPulseMeter(band) {
    const bar = document.getElementById(`meter_${band}`);
    if (bar) {
        bar.classList.add('pulse');
        setTimeout(() => bar.classList.remove('pulse'), 100);
    }
}
