from controller import ArtNetController
from models import Stage
from audio import AudioSyncAnalyzer
import time
import math
import threading
import random


# ==========================================
# K-MEANS (clusterização espacial pura, sem numpy)
# ==========================================

def kmeans_cluster(points, k, iterations=25, seed=42):
    """
    K-Means simples sobre pontos 3D [(x, y, z), ...].
    Retorna (labels, centroids). Determinístico via seed para
    que o auto-grouping seja reprodutível.
    """
    n = len(points)
    if n == 0:
        return [], []
    k = max(1, min(k, n))

    rng = random.Random(seed)

    # Inicialização k-means++ simplificada: primeiro ponto aleatório,
    # os demais escolhidos proporcionalmente à distância ao mais próximo.
    centroids = [points[rng.randrange(n)]]
    while len(centroids) < k:
        dists = []
        for p in points:
            d = min(_sqdist(p, c) for c in centroids)
            dists.append(d)
        total = sum(dists)
        if total == 0:
            centroids.append(points[rng.randrange(n)])
            continue
        r = rng.uniform(0, total)
        acc = 0.0
        for i, d in enumerate(dists):
            acc += d
            if acc >= r:
                centroids.append(points[i])
                break

    labels = [0] * n
    for _ in range(iterations):
        changed = False
        for i, p in enumerate(points):
            best = min(range(len(centroids)), key=lambda ci: _sqdist(p, centroids[ci]))
            if best != labels[i]:
                labels[i] = best
                changed = True
        # Recalcula centróides
        for ci in range(len(centroids)):
            members = [points[i] for i in range(n) if labels[i] == ci]
            if members:
                centroids[ci] = tuple(sum(m[d] for m in members) / len(members) for d in range(3))
        if not changed:
            break
    return labels, centroids


def _sqdist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3))


class LightingEngine:
    """
    Motor de luzes que gerencia o ArtNetController e roda efeitos dinâmicos
    (fades, chases, sequências com fade por step) em threads separadas.

    Novidades desta versão:
    - Submasters com merge HTP (Highest Takes Precedence) por grupo
    - Grand Master global
    - Auto-grouping espacial via K-Means
    - Sound-to-Light: triggers de bandas (graves/médios/agudos) vindos do
      front-end (Web Audio FFT) via WebSocket
    - Callback on_event para sincronização real-time (WebSockets)
    """
    def __init__(self, controller: ArtNetController, stage: Stage):
        self.controller = controller
        # Efeitos dinâmicos rodam em threads independentes por "chave" (chase/shape/
        # fade/sequence), assim uma cena que encadeia várias tool calls (ex: cor
        # estática + chase nos pars + shape nos movers) pode rodar tudo em paralelo,
        # em vez da chamada seguinte matar o efeito anterior via stop_effect() global.
        self.effect_threads = {}
        self.effect_flags = {}
        # Mantidos por compatibilidade (testes antigos e leitura externa de estado);
        # não controlam mais o loop dos efeitos.
        self.current_effect_thread = None
        self.running_effect = False

        # Módulo de Áudio (Auto-DJ via microfone do servidor)
        self.audio_analyzer = AudioSyncAnalyzer(on_beat_callback=self._on_music_beat)
        self.auto_dj_enabled = False
        self.current_dj_color = (255, 0, 0)

        # Master Speed: fator global que escala a velocidade de sequências/formas
        self.master_speed = 1.0

        # Undo ("Oops")
        self._last_snapshot = None
        self.blind_mode = False

        # --- SUBMASTERS (HTP) ---
        # grupo -> nível 0.0..1.0. Fixtures fora de qualquer submaster ficam a 1.0.
        self.submasters = {}
        self.grand_master = 1.0

        # --- Sound-to-Light (FFT do front-end) ---
        self.sound_to_light_enabled = False
        self._band_last_trigger = {"bass": 0.0, "mid": 0.0, "high": 0.0}
        self._bass_color_idx = 0
        self._bass_palette = [(255, 0, 0), (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 120, 0)]

        # Callback de eventos p/ broadcast (setado pela API)
        self.on_event = None

        self.attach_stage(stage)

    # ------------------------------------------
    # STAGE / HTP WIRING
    # ------------------------------------------

    def attach_stage(self, stage: Stage):
        """Liga (ou re-liga, após patch) o palco ao motor, injetando o scaler HTP."""
        self.stage = stage
        for f in stage.fixtures:
            f.dimmer_scaler = self._htp_scale

    def _htp_scale(self, fixture):
        """
        Merge HTP: entre todos os submasters que afetam a fixture,
        vence o de MAIOR nível. Sem submaster aplicável => 1.0.
        O Grand Master multiplica tudo no final.
        """
        levels = [lvl for grp, lvl in self.submasters.items() if grp in getattr(fixture, "groups", [])]
        scale = max(levels) if levels else 1.0
        return scale * self.grand_master

    def set_submaster(self, group: str, level: float):
        """Define o nível (0..1) de um submaster e reaplica os dimmers do grupo."""
        level = max(0.0, min(1.0, level))
        self.submasters[group] = level
        self._reapply_dimmers(group)
        self._emit({"type": "submaster", "group": group, "level": level})

    def set_grand_master(self, level: float):
        self.grand_master = max(0.0, min(1.0, level))
        self._reapply_dimmers(None)
        self._emit({"type": "grand_master", "level": self.grand_master})

    def _reapply_dimmers(self, group):
        """Re-escreve o canal dimmer das fixtures afetadas usando o base_dimmer salvo."""
        for f in self.stage.fixtures:
            if group is None or group in getattr(f, "groups", []):
                f.set_dimmer(f.base_dimmer)

    def get_submasters(self):
        return {"submasters": dict(self.submasters), "grand_master": self.grand_master}

    # ------------------------------------------
    # EVENTOS (WebSocket broadcast)
    # ------------------------------------------

    def _emit(self, event: dict):
        if self.on_event:
            try:
                self.on_event(event)
            except Exception as e:
                print(f"[Engine] Erro no on_event: {e}")

    # ------------------------------------------
    # AUTO-GROUPING (K-MEANS)
    # ------------------------------------------

    def auto_group(self, k: int = 3):
        """
        Clusteriza as fixtures pelas posições (x, y, z) e atribui grupos
        automáticos. Nomeia semanticamente: clusters altos (z alto) viram
        'aereo_N', baixos viram 'pista_N'. Remove grupos auto_* anteriores.
        Retorna o mapeamento {fixture_id: group_name}.
        """
        fixtures = self.stage.fixtures
        if not fixtures:
            return {}
        points = [(f.position["x"] if isinstance(f.position, dict) else f.position.x,
                   f.position["y"] if isinstance(f.position, dict) else f.position.y,
                   f.position["z"] if isinstance(f.position, dict) else f.position.z)
                  for f in fixtures]
        labels, centroids = kmeans_cluster(points, k)

        # Nomeia cada cluster pela altura do centróide
        names = {}
        counters = {"aereo": 0, "pista": 0}
        # ordena clusters por z para nomes estáveis
        order = sorted(range(len(centroids)), key=lambda ci: (centroids[ci][2], centroids[ci][1]))
        for ci in order:
            base = "aereo" if centroids[ci][2] >= 1.5 else "pista"
            counters[base] += 1
            names[ci] = f"auto_{base}_{counters[base]}"

        mapping = {}
        for f, lbl in zip(fixtures, labels):
            # remove grupos automáticos antigos e adiciona o novo
            f.groups = [g for g in f.groups if not g.startswith("auto_")]
            f.groups.append(names[lbl])
            mapping[f.id] = names[lbl]

        self._emit({"type": "auto_group", "mapping": mapping})
        return mapping

    # ------------------------------------------
    # CICLO DE VIDA / AUTO-DJ
    # ------------------------------------------

    def start(self):
        self.controller.start_loop()

    def enable_auto_dj(self):
        self.auto_dj_enabled = True
        self.audio_analyzer.start()
        self._emit({"type": "autodj", "enabled": True})

    def disable_auto_dj(self):
        self.auto_dj_enabled = False
        self.audio_analyzer.stop()
        self._emit({"type": "autodj", "enabled": False})

    def _on_music_beat(self):
        if not self.auto_dj_enabled:
            return
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 0)]
        self.current_dj_color = random.choice(colors)

        self.stop_effect()
        for f in self.stage.fixtures:
            f.set_color(*self.current_dj_color)
            f.set_dimmer(255)
            f.set_strobe(255)
        threading.Timer(0.1, lambda: self.set_all_strobe(0)).start()
        self._emit({"type": "beat"})

    def stop(self):
        self.controller.stop_loop()
        self.stop_effect()
        self.disable_auto_dj()

    def stop_effect(self, key: str = None):
        """
        Para um efeito dinâmico específico (key='chase'|'shape'|'fade'|'sequence')
        ou TODOS os efeitos em andamento quando key=None (usado por blackout,
        cores estáticas, undo, stop_effects, etc.).
        """
        keys = [key] if key is not None else list(self.effect_threads.keys())
        for k in keys:
            self.effect_flags[k] = False
            thread = self.effect_threads.get(k)
            if thread:
                thread.join()
            self.effect_threads.pop(k, None)
            self.effect_flags.pop(k, None)

        self.running_effect = False
        self.current_effect_thread = None

    def _start_effect(self, key: str, target, args: tuple):
        """Para qualquer efeito anterior com a MESMA chave e inicia um novo em thread própria."""
        self.stop_effect(key)
        self.effect_flags[key] = True
        thread = threading.Thread(target=target, args=args, daemon=True)
        self.effect_threads[key] = thread
        self.current_effect_thread = thread  # compat: reflete o último efeito iniciado
        self.running_effect = True
        thread.start()

    # ------------------------------------------
    # SOUND-TO-LIGHT (FFT vinda do navegador)
    # ------------------------------------------

    def set_sound_to_light(self, enabled: bool):
        self.sound_to_light_enabled = enabled
        self._emit({"type": "sound_to_light", "enabled": enabled})

    def handle_audio_band(self, band: str, energy: float):
        """
        Trigger de banda vindo do front-end via WebSocket.
        - bass  : flash colorido nos pars (grupos chao/parede/mega_par/pista)
        - mid   : onda de dimmer nos pars de parede
        - high  : rajada de strobo nos moving heads
        Rate-limit por banda para não saturar o DMX.
        """
        if not self.sound_to_light_enabled:
            return
        now = time.time()
        min_interval = {"bass": 0.12, "mid": 0.15, "high": 0.10}.get(band, 0.15)
        if now - self._band_last_trigger.get(band, 0.0) < min_interval:
            return
        self._band_last_trigger[band] = now

        if band == "bass":
            self._bass_color_idx = (self._bass_color_idx + 1) % len(self._bass_palette)
            color = self._bass_palette[self._bass_color_idx]
            targets = [f for f in self.stage.fixtures
                       if "pan" not in f.channels_map]  # pars (não-movings)
            for f in targets:
                f.set_color(*color)
                f.set_dimmer(int(255 * min(1.0, energy)))
        elif band == "mid":
            targets = [f for f in self.stage.fixtures
                       if "parede" in getattr(f, "groups", []) or "teto" in getattr(f, "groups", [])]
            for f in targets:
                f.set_dimmer(int(120 + 135 * min(1.0, energy)))
        elif band == "high":
            movers = [f for f in self.stage.fixtures if "pan" in f.channels_map]
            for f in movers:
                f.set_strobe(220)
                f.set_dimmer(255)
            threading.Timer(0.12, lambda: [f.set_strobe(0) for f in movers]).start()

        self._emit({"type": "audio_trigger", "band": band, "energy": round(float(energy), 3)})

    # ==========================================
    # COMANDOS DIRETOS
    # ==========================================

    def set_blackout(self):
        self.stop_effect()
        self.disable_auto_dj()
        for f in self.stage.fixtures:
            f.set_dimmer(0)
            f.set_color(0, 0, 0)
            f.set_strobe(0)
        self._emit({"type": "blackout"})

    def set_all_colors(self, r: int, g: int, b: int):
        self.stop_effect()
        for f in self.stage.fixtures:
            f.set_color(r, g, b)
            f.set_dimmer(255)
        self._emit({"type": "color", "r": r, "g": g, "b": b})

    def set_all_dimmer(self, intensity: int):
        self.stop_effect()
        for f in self.stage.fixtures:
            f.set_dimmer(intensity)
        self._emit({"type": "dimmer", "intensity": intensity})

    def set_group_color(self, group_name: str, r: int, g: int, b: int):
        self.stop_effect()
        found = False
        for f in self.stage.fixtures:
            if group_name in getattr(f, "groups", []) or group_name == "todos":
                f.set_color(r, g, b)
                f.set_dimmer(255)
                found = True
        if found:
            self._emit({"type": "group_color", "group": group_name, "r": r, "g": g, "b": b})
        return found

    def set_fixture_color(self, fixture_id: str, r: int, g: int, b: int):
        self.stop_effect()
        f = self.stage.get_fixture(fixture_id)
        if f:
            f.set_color(r, g, b)
            f.set_dimmer(255)
            return True
        return False

    def set_all_strobe(self, speed: int):
        for f in self.stage.fixtures:
            f.set_strobe(speed)

    # ==========================================
    # SNAPSHOT / UNDO ("OOPS")
    # ==========================================

    def snapshot(self):
        state = []
        for f in self.stage.fixtures:
            channels = {}
            for ch_name, offset in f.channels_map.items():
                channels[ch_name] = self.controller.get_channel(f.dmx_start + offset - 1)
            state.append({"id": f.id, "channels": channels})
        return state

    def save_undo_point(self):
        self._last_snapshot = self.snapshot()

    def undo_last(self):
        if not self._last_snapshot:
            return False
        self.stop_effect()
        for f_state in self._last_snapshot:
            f = self.stage.get_fixture(f_state["id"])
            if f:
                for ch_name, val in f_state["channels"].items():
                    f._set_channel_value(ch_name, val)
        self._last_snapshot = None
        return True

    # ==========================================
    # OVERRIDE / FLASH (Blinder momentâneo)
    # ==========================================

    def set_blinder(self, on: bool):
        for f in self.stage.fixtures:
            if on:
                f.set_color(255, 255, 255)
                f.set_dimmer(255)
            f.set_strobe(0)

    def set_master_speed(self, factor: float):
        self.master_speed = max(0.1, min(4.0, factor))
        self._emit({"type": "master_speed", "factor": self.master_speed})

    # ==========================================
    # EFEITOS DINÂMICOS
    # ==========================================

    def run_chase(self, r: int, g: int, b: int, speed_ms: int):
        self._start_effect("chase", self._chase_loop, (r, g, b, speed_ms / 1000.0))

    def _chase_loop(self, r, g, b, delay):
        # Só afeta pars/fixas: movers (pan/tilt) têm dimmer controlado por run_shape,
        # senão os dois efeitos brigam pelo mesmo canal e o mover pisca/apaga.
        fixtures = [f for f in self.stage.fixtures if "pan" not in f.channels_map]
        if not fixtures:
            self.effect_flags["chase"] = False
            return
        while self.effect_flags.get("chase"):
            for i in range(len(fixtures)):
                if not self.effect_flags.get("chase"):
                    break
                for f in fixtures:
                    f.set_dimmer(0)
                fixtures[i].set_color(r, g, b)
                fixtures[i].set_dimmer(255)
                # Um único evento por passo (em vez de N+1) evita inundar o WebSocket
                # quando há muitas fixtures; o front-end aplica o "apagar tudo" localmente.
                self._emit({
                    "type": "chase_step",
                    "ids": [f.id for f in fixtures],
                    "active_id": fixtures[i].id,
                    "r": r, "g": g, "b": b,
                })
                time.sleep(delay / self.master_speed)
    def set_position(self, position: str):
        """
        Aponta os Moving Heads para locais específicos do bar/venue.
        Pan: 0=esquerda total, 127=centro, 255=direita total (curso 540°)
        Tilt: 0=teto/cima, 127=horizontal/meio, 180=plateia/frente, 220=chão/baixo
        
        Layout do bar (movings pendurados no fundo do palco, Y≈5, Z≈3m):
        - Palco/palco (Y≈0 a 2, atrás dos movings ou ao lado) -> Tilt apontando pra baixo-frente
        - Pista de dança (Y≈0 a 3, em frente) -> Tilt ≈ 160-180
        - Bar balcão (Y≈-4, fundo) -> Tilt bem apontado pra frente/baixo
        - Mesanino (Z≈4-5m, acima) -> Tilt ≈ 60-80 (para cima)
        - Colunas (laterais, X≈±5) -> Pan 0 ou 255 + Tilt ≈ 120
        - Mesa de sinuca -> Tilt ≈ 150, Pan levemente lateral
        - Banheiro -> Tilt ≈ 170, Pan extremo
        """
        # Defaults: centro horizontal
        pan, tilt = 127, 127
        p = position.lower().replace("ç", "c").replace("ã", "a").replace("é", "e").replace("á", "a")

        # ── POSIÇÕES ESPECÍFICAS DO BAR ─────────────────────────────────────
        if any(x in p for x in ["palco", "stage"]):
            pan, tilt = 127, 200   # Apontado pra baixo-frente do palco (movings ficam atrás)
        elif any(x in p for x in ["pista", "dance", "danca", "floor"]):
            pan, tilt = 127, 175   # Pista de dança: tilt quase horizontal pra baixo
        elif any(x in p for x in ["bar", "balcao", "balcão", "drinks"]):
            pan, tilt = 127, 210   # Bar: mais longe, mais inclinado
        elif any(x in p for x in ["mesanino", "camarote", "galeria", "segundo andar", "cima", "acima", "alto"]):
            pan, tilt = 127, 60    # Aponta para o alto (mesanino)
        elif any(x in p for x in ["sinuca", "bilhar", "mesa de sinuca", "pool"]):
            pan, tilt = 60, 180    # Levemente à esquerda, baixo
        elif any(x in p for x in ["banheiro", "toalete", "wc", "sanitario"]):
            pan, tilt = 20, 190    # Canto extremo
        elif any(x in p for x in ["coluna", "pilar", "parede", "columns"]):
            pan, tilt = 0, 130     # Lateral extremo, quase horizontal
        elif any(x in p for x in ["coluna dir", "coluna d", "pilar dir"]):
            pan, tilt = 255, 130   # Coluna direita
        elif any(x in p for x in ["plateia", "publico", "público", "audiencia", "frente", "front"]):
            pan, tilt = 127, 165   # Plateia/público na frente
        elif any(x in p for x in ["esquerda", "esq", "left"]):
            pan, tilt = 20, 150
        elif any(x in p for x in ["direita", "dir", "right"]):
            pan, tilt = 235, 150
        # ── POSIÇÕES GENÉRICAS ───────────────────────────────────────────────
        elif any(x in p for x in ["teto", "ceu", "ceiling", "topo"]):
            pan, tilt = 127, 0     # Aponta pro teto acima
        elif any(x in p for x in ["chao", "floor", "ground", "baixo"]):
            pan, tilt = 127, 220   # Aponta pro chão
        elif any(x in p for x in ["meio", "centro", "center", "middle"]):
            pan, tilt = 127, 127   # Centro neutro
        elif any(x in p for x in ["entrada", "porta", "door"]):
            pan, tilt = 127, 195   # Entrada do local

        movers = [f for f in self.stage.fixtures if "pan" in f.channels_map]
        for f in movers:
            f.set_pan_tilt(pan, tilt)
            if f.base_dimmer <= 0:
                f.set_dimmer(255)
            self._emit({"type": "pantilt", "id": f.id, "pan": pan, "tilt": tilt})
        
        return {"pan": pan, "tilt": tilt, "location": position}


    # ==========================================
    # GERADOR DE FORMAS (Pan/Tilt Shapes)
    # ==========================================

    def run_shape(self, shape: str, speed: float = 1.0, size: float = 1.0, fixture_ids=None):
        self._start_effect("shape", self._shape_loop, (shape, speed, size, fixture_ids))

    def _shape_loop(self, shape, speed, size, fixture_ids):
        movers = [f for f in self.stage.fixtures if "pan" in f.channels_map and "tilt" in f.channels_map]
        if fixture_ids:
            movers = [f for f in movers if f.id in fixture_ids]
        if not movers:
            self.effect_flags["shape"] = False
            return

        # Movers ficam escuros por padrão (dimmer=0): sem isso o pan/tilt roda mas
        # nada aparece visualmente. run_shape acende os movers que vai controlar.
        for f in movers:
            if f.base_dimmer <= 0:
                f.set_dimmer(255)

        center = 127
        radius = max(1, min(127, int(127 * size)))
        step = 0.0
        step_delay = 0.02
        tick_count = 0

        while self.effect_flags.get("shape"):
            angle = step * speed
            tick_count += 1
            emit_now = (tick_count % 3 == 0) # Emit websocket every ~16fps to avoid spam

            for idx, f in enumerate(movers):
                phase = angle + (idx * (math.pi / 4))
                if shape == "circle":
                    pan = center + int(radius * math.cos(phase))
                    tilt = center + int(radius * math.sin(phase))
                elif shape == "figure8":
                    pan = center + int(radius * math.sin(phase))
                    tilt = center + int(radius * math.sin(phase) * math.cos(phase))
                elif shape == "sweep":
                    pan = center + int(radius * math.sin(phase))
                    tilt = center
                else:
                    pan, tilt = center, center
                
                f.set_pan_tilt(max(0, min(255, pan)), max(0, min(255, tilt)))
                
                if emit_now:
                    self._emit({"type": "pantilt", "id": f.id, "pan": max(0, min(255, pan)), "tilt": max(0, min(255, tilt))})
                    
            step += step_delay * self.master_speed
            time.sleep(step_delay)

    # ==========================================
    # SEQUÊNCIAS (Timeline com Fade por Step)
    # ==========================================

    def run_sequence(self, steps: list, loop: bool = True):
        self._start_effect("sequence", self._sequence_loop, (steps, loop))

    def _sequence_loop(self, steps, loop=True):
        """
        Cada step suporta:
          - fade_ms: interpolação suave do estado atual para o alvo (0 = snap)
          - time_ms: tempo de espera (hold) após atingir o alvo
          - state:   [{id, channels: {nome: valor}}]
        """
        first_pass = True
        while self.effect_flags.get("sequence") and (loop or first_pass):
            first_pass = False
            for step_idx, step in enumerate(steps):
                if not self.effect_flags.get("sequence"):
                    break

                hold = step.get('time_ms', 500) / 1000.0
                fade = step.get('fade_ms', 0) / 1000.0
                state = step.get('state', [])

                # Aplica fade ou snap ANTES de anunciar o step
                if fade > 0.01:
                    self._fade_to_state(state, fade / self.master_speed)
                else:
                    self._apply_state(state)

                # Só destaca o bloco depois de chegar lá
                self._emit({"type": "sequence_step", "index": step_idx, "total": len(steps)})

                # hold em pequenos incrementos para reagir rápido ao stop
                remaining = hold / self.master_speed
                while remaining > 0 and self.effect_flags.get("sequence"):
                    dt = min(0.05, remaining)
                    time.sleep(dt)
                    remaining -= dt

        self.effect_flags["sequence"] = False
        self._emit({"type": "sequence_done"})


    def _apply_state(self, state):
        for f_state in state:
            f = self.stage.get_fixture(f_state.get('id'))
            if f:
                for ch_name, val in f_state.get('channels', {}).items():
                    f._set_channel_value(ch_name, val)

    def _fade_to_state(self, state, duration):
        """Interpola linearmente todos os canais do estado atual até o alvo."""
        # Captura pontos de partida
        plan = []  # (fixture, ch_name, start, target)
        for f_state in state:
            f = self.stage.get_fixture(f_state.get('id'))
            if not f:
                continue
            for ch_name, target in f_state.get('channels', {}).items():
                if ch_name not in f.channels_map:
                    continue
                start = self.controller.get_channel(f.dmx_start + f.channels_map[ch_name] - 1)
                plan.append((f, ch_name, start, target))

        steps = max(1, int(duration * 30))
        for s in range(1, steps + 1):
            if not self.effect_flags.get("sequence"):
                return
            t = s / steps
            for f, ch_name, start, target in plan:
                f._set_channel_value(ch_name, int(start + (target - start) * t))
            time.sleep(duration / steps)

    def run_fade(self, r: int, g: int, b: int, duration_sec: float):
        self._start_effect("fade", self._fade_loop, (r, g, b, duration_sec))

    def _fade_loop(self, r_target, g_target, b_target, duration):
        if not self.stage.fixtures:
            return
        f0 = self.stage.fixtures[0]
        r_start = self.controller.get_channel(f0.dmx_start + f0.channels_map.get("red", 1) - 1)
        g_start = self.controller.get_channel(f0.dmx_start + f0.channels_map.get("green", 2) - 1)
        b_start = self.controller.get_channel(f0.dmx_start + f0.channels_map.get("blue", 3) - 1)

        steps = int(duration * 30)
        if steps == 0:
            steps = 1

        for step in range(steps):
            if not self.effect_flags.get("fade"):
                break

            r = int(r_start + (r_target - r_start) * (step / steps))
            g = int(g_start + (g_target - g_start) * (step / steps))
            b = int(b_start + (b_target - b_start) * (step / steps))

            # Só afeta pars/fixas: preserva o dimmer dos movers para não brigar com
            # um run_shape em paralelo (movers não têm canais red/green/blue mesmo).
            for f in self.stage.fixtures:
                if "pan" in f.channels_map:
                    continue
                f.set_color(r, g, b)
                f.set_dimmer(255)

            time.sleep(1 / 30.0)
        self._emit({"type": "color", "r": r_target, "g": g_target, "b": b_target})
