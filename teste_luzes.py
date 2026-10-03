import time
import os
from controller import FreestylerController
from engine import LightingEngine
from models import Stage

def rodar_teste():
    print("=" * 60)
    print("      LUMINA-AI - TESTE ORIENTADO A OBJETOS (IA READY)      ")
    print("=" * 60)
    
    # Caminhos para os JSONs
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fixtures_path = os.path.join(base_dir, "fixtures.json")
    palco_path = os.path.join(base_dir, "palco.json")
    
    # 1. Inicializa o Controlador (Transporte)
    ctrl = FreestylerController(ip="127.0.0.1", port=3332)
    
    # 2. Inicializa o Stage (Mundo Físico)
    stage = Stage(palco_path, fixtures_path, ctrl)
    print(f"[Sistema] {len(stage.fixtures)} refletores carregados no palco.")
    
    # 3. Inicializa a Engine (Lógica de Alto Nível / Macros)
    engine = LightingEngine(ctrl, stage)
    
    if not ctrl.connect():
        print("\n[ERRO] Não foi possível conectar ao FreeStyler.")
        return

    try:
        # Teste de Macro
        print("\n--- TESTE DE MACROS (ENGINE) ---")
        print("Removendo Blackout e definindo Master para 100%...")
        engine.set_blackout(False)
        engine.set_master_intensity(255)
        time.sleep(1.0)
        
        print("Disparando Sequência 1 (Macro)...")
        engine.start_sequence(1)
        time.sleep(3.0)
        engine.stop_sequence(1)

        # Teste Físico (Orientado a Objeto)
        print("\n--- TESTE FÍSICO (STAGE / FIXTURES) ---")
        print("Definindo todas as luzes para Vermelho...")
        stage.set_all_colors(255, 0, 0)
        time.sleep(2.0)
        
        print("Definindo todas as luzes para Azul...")
        stage.set_all_colors(0, 0, 255)
        time.sleep(2.0)
        
        # Testando buscar um reflector específico
        esq = stage.get_fixture("par_chao_esq")
        if esq:
            print(f"Mudando cor apenas do '{esq.label}' para Verde...")
            esq.set_color(0, 255, 0)
            time.sleep(2.0)

        # 6. Finalizando
        print("\nFinalizando e ativando Blackout...")
        engine.set_blackout(True)
        print("Teste concluído com sucesso!")
        
    except KeyboardInterrupt:
        print("\nTeste interrompido pelo usuário.")
    finally:
        ctrl.disconnect()
        print("=" * 60)

if __name__ == "__main__":
    rodar_teste()
