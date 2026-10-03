import os
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import urllib.request
import urllib.error

from controller import FreestylerController
from engine import LightingEngine
from models import Stage

# Você pode definir a sua chave aqui ou no arquivo .env
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Se estiver usando LM Studio ou LocalAI, deixe a chave vazia e use a URL local:
LOCAL_API_URL = "http://localhost:1234/v1/chat/completions"

class AIClient:
    """Cliente simples para falar com Claude (Anthropic) ou um modelo local."""
    
    def __init__(self, engine: LightingEngine, palco_data, fixtures_data):
        self.engine = engine
        self.system_prompt = self._build_system_prompt(palco_data, fixtures_data)

    def _build_system_prompt(self, palco_data, fixtures_data):
        return f"""Você é o Lumina-AI, um assistente inteligente de iluminação.
O usuário vai pedir coisas em linguagem natural. Você deve responder APENAS com um JSON válido listando as funções que devem ser executadas.
As funções disponíveis são:
- set_mood_color(r, g, b)
- set_blackout(active_boolean)
- start_sequence(seq_num)
- stop_sequence(seq_num)
- set_all_strobe(speed_0_to_255)
- set_fixture_color(fixture_id, r, g, b)
- set_fixture_dimmer(fixture_id, intensity)

Dados do palco: {json.dumps(palco_data)}
Livraria de Fixtures: {json.dumps(fixtures_data)}

Exemplo de resposta:
{{
  "acoes": [
    {{"funcao": "set_fixture_color", "args": ["par_esq", 255, 0, 0]}},
    {{"funcao": "set_all_strobe", "args": [255]}}
  ],
  "mensagem_usuario": "Coloquei o par esquerdo vermelho e ativei o strobo."
}}
Responda SOMENTE o JSON.
"""

    def send_prompt(self, user_text):
        if ANTHROPIC_API_KEY:
            return self._call_anthropic(user_text)
        else:
            return self._call_local(user_text)

    def _call_local(self, user_text):
        data = {
            "model": "local-model",
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_text}
            ],
            "temperature": 0.1
        }
        req = urllib.request.Request(LOCAL_API_URL, json.dumps(data).encode('utf-8'), 
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read())
                content = result['choices'][0]['message']['content']
                return self._parse_and_execute(content)
        except Exception as e:
            return f"Erro ao conectar na IA local: {e}. Verifique se o LM Studio/Ollama está rodando."

    def _call_anthropic(self, user_text):
        data = {
            "model": "claude-3-haiku-20240307",
            "system": self.system_prompt,
            "messages": [{"role": "user", "content": user_text}],
            "max_tokens": 1024,
            "temperature": 0.1
        }
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", json.dumps(data).encode('utf-8'), 
                                     headers={'x-api-key': ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read())
                content = result['content'][0]['text']
                return self._parse_and_execute(content)
        except Exception as e:
            return f"Erro ao conectar no Claude: {e}"

    def _parse_and_execute(self, ai_text):
        try:
            # Tentar achar os limites do JSON se a IA mandou Markdown
            start = ai_text.find('{')
            end = ai_text.rfind('}') + 1
            if start != -1 and end != -1:
                clean_json = ai_text[start:end]
            else:
                clean_json = ai_text

            data = json.loads(clean_json)
            
            for acao in data.get("acoes", []):
                func_name = acao.get("funcao")
                args = acao.get("args", [])
                
                # Executa dinamicamente a função no Engine
                func = getattr(self.engine, func_name, None)
                if func:
                    func(*args)
                    
            return data.get("mensagem_usuario", "Comando executado com sucesso.")
        except Exception as e:
            return f"Erro ao interpretar resposta da IA: {e}\nResposta original: {ai_text}"


class LuminaGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Lumina-AI - Controle de Iluminação")
        self.root.geometry("900x600")
        self.root.resizable(True, True)

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.fixtures_path = os.path.join(base_dir, "fixtures.json")
        self.palco_path = os.path.join(base_dir, "palco.json")

        with open(self.palco_path, 'r', encoding='utf-8') as f:
            palco_data = json.load(f)
        with open(self.fixtures_path, 'r', encoding='utf-8') as f:
            fixtures_data = json.load(f)

        self.ctrl = FreestylerController(ip="127.0.0.1", tcp_port=3332, artnet_port=6454)
        self.stage = Stage(self.palco_path, self.fixtures_path, self.ctrl)
        self.engine = LightingEngine(self.ctrl, self.stage)
        
        self.ai = AIClient(self.engine, palco_data, fixtures_data)

        self.create_widgets()

    def create_widgets(self):
        self.paned_window = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- PAINEL ESQUERDO ---
        left_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(left_frame, weight=1)

        conn_frame = ttk.LabelFrame(left_frame, text="Conexão com FreeStyler", padding="10")
        conn_frame.pack(fill=tk.X, pady=5)

        self.lbl_status = ttk.Label(conn_frame, text="Status: Desconectado", foreground="red")
        self.lbl_status.pack(side=tk.LEFT, padx=5)

        self.btn_connect = ttk.Button(conn_frame, text="Conectar", command=self.toggle_connection)
        self.btn_connect.pack(side=tk.RIGHT, padx=5)

        global_frame = ttk.LabelFrame(left_frame, text="Controles Globais", padding="10")
        global_frame.pack(fill=tk.X, pady=5)

        self.btn_blackout = ttk.Button(global_frame, text="Ativar Blackout", command=self.toggle_blackout)
        self.btn_blackout.pack(side=tk.LEFT, padx=5)
        self.blackout_active = False

        ttk.Label(global_frame, text="Master Intensity:").pack(side=tk.LEFT, padx=5)
        self.scale_master = ttk.Scale(global_frame, from_=0, to=255, orient=tk.HORIZONTAL, command=self.update_master)
        self.scale_master.set(255)
        self.scale_master.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        color_frame = ttk.LabelFrame(left_frame, text="Cor do Palco (RGB)", padding="10")
        color_frame.pack(fill=tk.X, pady=5)

        ttk.Label(color_frame, text="R:").grid(row=0, column=0, padx=5)
        self.scale_r = ttk.Scale(color_frame, from_=0, to=255, orient=tk.HORIZONTAL)
        self.scale_r.grid(row=0, column=1, sticky="ew", padx=5)

        ttk.Label(color_frame, text="G:").grid(row=1, column=0, padx=5)
        self.scale_g = ttk.Scale(color_frame, from_=0, to=255, orient=tk.HORIZONTAL)
        self.scale_g.grid(row=1, column=1, sticky="ew", padx=5)

        ttk.Label(color_frame, text="B:").grid(row=2, column=0, padx=5)
        self.scale_b = ttk.Scale(color_frame, from_=0, to=255, orient=tk.HORIZONTAL)
        self.scale_b.grid(row=2, column=1, sticky="ew", padx=5)
        color_frame.columnconfigure(1, weight=1)

        btn_apply_color = ttk.Button(color_frame, text="Aplicar Cor", command=self.apply_color)
        btn_apply_color.grid(row=0, column=2, rowspan=3, padx=10, sticky="ns")

        macro_frame = ttk.LabelFrame(left_frame, text="Macros e Sequências", padding="10")
        macro_frame.pack(fill=tk.X, pady=5)

        btn_seq1_start = ttk.Button(macro_frame, text="Iniciar Seq 1", command=lambda: self.engine.start_sequence(1))
        btn_seq1_start.pack(side=tk.LEFT, padx=5)
        btn_seq1_stop = ttk.Button(macro_frame, text="Parar Seq 1", command=lambda: self.engine.stop_sequence(1))
        btn_seq1_stop.pack(side=tk.LEFT, padx=5)

        log_frame = ttk.LabelFrame(left_frame, text="Log", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = tk.Text(log_frame, height=8, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # --- PAINEL DIREITO ---
        right_frame = ttk.LabelFrame(self.paned_window, text="Comandos IA (IA Real)", padding="10")
        self.paned_window.add(right_frame, weight=1)

        self.chat_history = tk.Text(right_frame, state=tk.DISABLED, wrap=tk.WORD)
        self.chat_history.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        input_frame = ttk.Frame(right_frame)
        input_frame.pack(fill=tk.X)

        self.entry_ai = ttk.Entry(input_frame, font=("Arial", 11))
        self.entry_ai.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.entry_ai.bind("<Return>", lambda e: self.send_ai_command())

        self.btn_send_ai = ttk.Button(input_frame, text="Enviar", command=self.send_ai_command)
        self.btn_send_ai.pack(side=tk.RIGHT)

        self.log(f"Sistema iniciado. {len(self.stage.fixtures)} refletores carregados.")
        self.log_ai("Olá! Agora estou conectado com o Motor de IA Real.\nO controle via Art-Net também está pronto para as luzes individuais!")

    def log(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def log_ai(self, message, sender="IA"):
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.insert(tk.END, f"{sender}: {message}\n\n")
        self.chat_history.see(tk.END)
        self.chat_history.config(state=tk.DISABLED)

    def toggle_connection(self):
        if not self.ctrl.connected:
            if self.ctrl.connect():
                self.lbl_status.config(text="Status: Conectado", foreground="green")
                self.btn_connect.config(text="Desconectar")
                self.log("Conectado ao FreeStyler com sucesso!")
            else:
                messagebox.showerror("Erro de Conexão", "Não foi possível conectar.")
                self.log("Falha ao conectar.")
        else:
            self.ctrl.disconnect()
            self.lbl_status.config(text="Status: Desconectado", foreground="red")
            self.btn_connect.config(text="Conectar")
            self.log("Desconectado.")

    def toggle_blackout(self):
        self.blackout_active = not self.blackout_active
        self.engine.set_blackout(self.blackout_active)
        if self.blackout_active:
            self.btn_blackout.config(text="Desativar Blackout")
            self.log("Blackout ATIVADO.")
        else:
            self.btn_blackout.config(text="Ativar Blackout")
            self.log("Blackout DESATIVADO.")

    def update_master(self, event=None):
        val = int(self.scale_master.get())
        if self.ctrl.connected:
            self.engine.set_master_intensity(val)

    def apply_color(self):
        r = int(self.scale_r.get())
        g = int(self.scale_g.get())
        b = int(self.scale_b.get())
        self.engine.set_mood_color(r, g, b)
        self.log(f"Cor do palco alterada via Art-Net para RGB({r}, {g}, {b})")

    def send_ai_command(self):
        command = self.entry_ai.get().strip()
        if not command:
            return
        
        self.entry_ai.delete(0, tk.END)
        self.log_ai(command, sender="Você")
        self.btn_send_ai.config(state=tk.DISABLED)
        
        # Roda a requisição web em uma thread separada para não travar a GUI
        threading.Thread(target=self._ai_worker, args=(command,), daemon=True).start()
        
    def _ai_worker(self, command):
        response = self.ai.send_prompt(command)
        
        # Atualiza a GUI de volta na thread principal
        self.root.after(0, self._ai_response_callback, response)
        
    def _ai_response_callback(self, response):
        self.log_ai(response, sender="IA")
        self.btn_send_ai.config(state=tk.NORMAL)

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    app = LuminaGUI(root)
    root.mainloop()
