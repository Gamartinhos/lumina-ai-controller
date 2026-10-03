import threading
import time
import uvicorn
import webview
import ctypes
import sys
from api import app

class DesktopAPI:
    def open_terminal(self):
        # Aloca um console no Windows para mostrar os logs
        if sys.platform == "win32":
            try:
                ctypes.windll.kernel32.AllocConsole()
                sys.stdout = open("CONOUT$", "w", encoding="utf-8")
                sys.stderr = open("CONOUT$", "w", encoding="utf-8")
                print("=== Terminal de Debug do Lumina-AI ===")
                print("Console ativado! Logs e erros do servidor aparecerão aqui.")
            except Exception as e:
                pass
        else:
            print("Visualização de terminal via botão não suportada nativamente no Linux.")
            print("Por favor, verifique a saída diretamente no terminal onde o script foi iniciado.")

def start_server():
    # Roda o FastAPI (Lumina) na porta 8000
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

if __name__ == '__main__':
    # 1. Inicia o servidor em background
    t = threading.Thread(target=start_server)
    t.daemon = True
    t.start()

    # Dá um tempinho pro servidor subir
    time.sleep(1)

    api = DesktopAPI()

    # 2. Cria a janela Desktop nativa (usa o WebView2 do Windows, super rápido pro 3D)
    window = webview.create_window(
        'Lumina-AI Desktop',
        'http://127.0.0.1:8000',
        width=1280,
        height=800,
        background_color='#0f172a',
        js_api=api
    )
    
    # 3. Inicia o app desktop
    webview.start()
