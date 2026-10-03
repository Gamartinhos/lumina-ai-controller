import time
from controller import ArtNetController
from models import Stage
from engine import LightingEngine
import os

base_dir = os.path.dirname(os.path.abspath(__file__))
ctrl = ArtNetController()
stage = Stage(os.path.join(base_dir, "palco.json"), os.path.join(base_dir, "fixtures.json"), ctrl)
engine = LightingEngine(ctrl, stage)

print("Iniciando DMX via QLC+...")
engine.start()

print("Fazendo um chase (corre-luz) verde de teste!")
engine.run_chase(0, 255, 0, 150) # Verde, 150ms

time.sleep(3) # Deixa o chase rodar por 3 segundos

print("Mudando para tudo azul com fade!")
engine.run_fade(0, 0, 255, 2.0)

time.sleep(3)

print("Blackout.")
engine.set_blackout()
engine.stop()
print("Teste finalizado com sucesso.")
