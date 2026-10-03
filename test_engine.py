"""
Testes rudimentares do LightingEngine: K-Means, Submasters HTP e sequência com fade.
Roda sem hardware: usa o ArtNetController sem iniciar o loop de transmissão
e faz stub do AudioSyncAnalyzer (pyaudio pode não existir na máquina de CI).

Uso: python test_engine.py
"""
import os
import sys
import time
import types

# Stub do módulo audio ANTES de importar o engine (evita dependência de pyaudio)
fake_audio = types.ModuleType("audio")

class _FakeAnalyzer:
    def __init__(self, on_beat_callback=None):
        self.on_beat_callback = on_beat_callback
    def start(self): pass
    def stop(self): pass

fake_audio.AudioSyncAnalyzer = _FakeAnalyzer
sys.modules["audio"] = fake_audio

from controller import ArtNetController
from models import Stage
from engine import LightingEngine, kmeans_cluster

BASE = os.path.dirname(os.path.abspath(__file__))
PASSED = 0
FAILED = 0

def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [OK]   {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")


def build_engine():
    ctrl = ArtNetController(ip="127.0.0.1", port=6454)  # loop NÃO iniciado: nada sai na rede
    stage = Stage(os.path.join(BASE, "palco.json"), os.path.join(BASE, "fixtures.json"), ctrl)
    return LightingEngine(ctrl, stage)


def test_kmeans():
    print("\n== K-Means ==")
    pts = [(0, 0, 0), (0.1, 0, 0), (5, 5, 3), (5.1, 5, 3), (0.05, 0.1, 0)]
    labels, centroids = kmeans_cluster(pts, 2)
    check("2 clusters retornados", len(centroids) == 2)
    check("pontos próximos no mesmo cluster", labels[0] == labels[1] == labels[4])
    check("clusters distintos separados", labels[0] != labels[2])
    check("k > n não explode", len(kmeans_cluster([(1, 1, 1)], 5)[1]) == 1)
    check("lista vazia ok", kmeans_cluster([], 3) == ([], []))


def test_auto_group(eng):
    print("\n== Auto-Grouping ==")
    mapping = eng.auto_group(2)
    check("todas as fixtures mapeadas", len(mapping) == len(eng.stage.fixtures))
    check("nomes auto_* atribuídos", all(g.startswith("auto_") for g in mapping.values()))
    f0 = eng.stage.fixtures[0]
    check("grupo auto adicionado à fixture", any(g.startswith("auto_") for g in f0.groups))
    # Reagrupar não acumula grupos auto antigos
    eng.auto_group(2)
    check("sem acúmulo de grupos auto", sum(1 for g in f0.groups if g.startswith("auto_")) == 1)


def test_submasters_htp(eng):
    print("\n== Submasters HTP ==")
    ctrl = eng.controller
    f = eng.stage.fixtures[0]  # MEGA_PAR: dimmer no canal dmx_start
    dim_addr = f.dmx_start + f.channels_map["dimmer"] - 1

    eng.running_effect = False
    f.set_dimmer(200)
    check("dimmer sem submaster = valor cheio", ctrl.get_channel(dim_addr) == 200)

    eng.set_submaster("chao", 0.5)
    check("submaster 50% escala o dimmer", ctrl.get_channel(dim_addr) == 100,
          f"(got {ctrl.get_channel(dim_addr)})")

    # HTP: outro submaster com nível MAIOR vence
    eng.set_submaster("mega_par", 1.0)
    check("HTP: maior nível vence", ctrl.get_channel(dim_addr) == 200,
          f"(got {ctrl.get_channel(dim_addr)})")

    # Baixando o maior, volta a valer o de 0.5
    eng.set_submaster("mega_par", 0.25)
    check("HTP recalcula ao baixar", ctrl.get_channel(dim_addr) == 100,
          f"(got {ctrl.get_channel(dim_addr)})")

    # Grand master multiplica
    eng.set_grand_master(0.5)
    check("grand master multiplica", ctrl.get_channel(dim_addr) == 50,
          f"(got {ctrl.get_channel(dim_addr)})")
    eng.set_grand_master(1.0)
    eng.submasters.clear()
    eng._reapply_dimmers(None)


def test_sequence_fade(eng):
    print("\n== Sequência com Fade ==")
    ctrl = eng.controller
    f = eng.stage.fixtures[0]
    red_addr = f.dmx_start + f.channels_map["red"] - 1

    f._set_channel_value("red", 0)
    steps = [{"time_ms": 150, "fade_ms": 200,
              "state": [{"id": f.id, "channels": {"red": 250}}]}]
    eng.run_sequence(steps, loop=False)
    time.sleep(0.12)
    mid = ctrl.get_channel(red_addr)
    check("fade em progresso (valor intermediário)", 0 < mid <= 250, f"(got {mid})")
    time.sleep(0.5)
    eng.stop_effect()
    check("fade atinge o alvo", ctrl.get_channel(red_addr) == 250,
          f"(got {ctrl.get_channel(red_addr)})")


def test_audio_bands(eng):
    print("\n== Sound-to-Light ==")
    eng.set_sound_to_light(True)
    eng.stop_effect()
    eng.handle_audio_band("bass", 1.0)
    pars = [f for f in eng.stage.fixtures if "pan" not in f.channels_map]
    f = pars[0]
    dim_addr = f.dmx_start + f.channels_map["dimmer"] - 1
    check("bass acende os pars", eng.controller.get_channel(dim_addr) == 255,
          f"(got {eng.controller.get_channel(dim_addr)})")
    # rate-limit: segundo trigger imediato é ignorado sem erro
    eng.handle_audio_band("bass", 1.0)
    check("rate-limit não explode", True)
    eng.set_sound_to_light(False)


def test_events(eng):
    print("\n== Eventos (broadcast) ==")
    received = []
    eng.on_event = lambda ev: received.append(ev)
    eng.set_submaster("teto", 0.7)
    check("evento submaster emitido", any(e.get("type") == "submaster" for e in received))
    eng.set_all_colors(10, 20, 30)
    check("evento color emitido", any(e.get("type") == "color" for e in received))
    eng.on_event = None
    eng.submasters.clear()


if __name__ == "__main__":
    eng = build_engine()
    test_kmeans()
    test_auto_group(eng)
    test_submasters_htp(eng)
    test_sequence_fade(eng)
    test_audio_bands(eng)
    test_events(eng)
    print(f"\nRESULTADO: {PASSED} passed, {FAILED} failed")
    sys.exit(1 if FAILED else 0)
