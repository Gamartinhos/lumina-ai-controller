import json
import urllib.request
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Lumina-AI-DMX")

API_URL = "http://localhost:8000/api/execute_tool"

def send_tool_call(tool_name: str, kwargs: dict) -> str:
    payload = {
        "tool_name": tool_name,
        "kwargs": kwargs
    }
    try:
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if res_data.get("status") == "ok":
                return res_data.get("reply", "Executado com sucesso!")
            else:
                return f"Erro retornado pelo servidor: {res_data.get('reply', 'Desconhecido')}"
    except Exception as e:
        return f"Falha ao conectar com o Lumina-AI. Certifique-se de que o aplicativo (app.bat) está aberto. Erro: {e}"


@mcp.tool()
def set_blackout() -> str:
    """
    Apaga todas as luzes imediatamente e para qualquer efeito rodando.
    """
    return send_tool_call("set_blackout", {})

@mcp.tool()
def stop_effects() -> str:
    """
    Para todos os movimentos e efeitos piscantes em andamento, sem necessariamente apagar as luzes.
    """
    return send_tool_call("stop_effects", {})

@mcp.tool()
def set_color(r: int, g: int, b: int) -> str:
    """
    Define uma cor estática (RGB 0-255) para todos os refletores do palco simultaneamente.
    """
    return send_tool_call("set_color", {"r": r, "g": g, "b": b})

@mcp.tool()
def set_group_color(group_name: str, r: int, g: int, b: int) -> str:
    """
    Define a cor (RGB 0-255) de apenas um grupo específico.
    """
    return send_tool_call("set_group_color", {"group_name": group_name, "r": r, "g": g, "b": b})

@mcp.tool()
def set_position(position: str) -> str:
    """
    Aponta os moving heads estaticamente para uma posição fixa (teto, chao, meio, frente, esquerda, direita).
    """
    return send_tool_call("set_position", {"position": position})

@mcp.tool()
def run_fade(r: int, g: int, b: int, duration_sec: float) -> str:
    """
    Faz uma transição de fade suave da cor atual para a nova cor RGB.
    Duração em segundos (ex: 2.5).
    """
    return send_tool_call("run_fade", {"r": r, "g": g, "b": b, "duration": duration_sec})

@mcp.tool()
def run_chase(r: int, g: int, b: int, speed_ms: int) -> str:
    """
    Cria um efeito sequencial (corre-luz) onde os refletores piscam na cor informada.
    speed_ms é a velocidade entre os pulos em milissegundos.
    """
    return send_tool_call("run_chase", {"r": r, "g": g, "b": b, "speed_ms": speed_ms})

@mcp.tool()
def run_shape(shape: str, speed: float, size: float) -> str:
    """
    Faz os moving heads desenharem um formato/movimento contínuo.
    shape: 'circle', 'figure8' ou 'sweep'.
    speed: velocidade (ex: 1.0).
    size: tamanho do movimento (ex: 1.0).
    """
    return send_tool_call("run_shape", {"shape": shape, "speed": speed, "size": size})

@mcp.tool()
def ask_lumina_ai(prompt: str) -> str:
    """
    Envia um comando em linguagem natural para a IA local do Lumina (Qwen) resolver.
    Use essa ferramenta quando o usuário pedir "peça para a IA do lumina fazer X".
    A IA do Lumina analisará o prompt e acionará as luzes de acordo com as regras internas dela.
    """
    payload = {"message": prompt}
    try:
        req = urllib.request.Request(
            "http://localhost:8000/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if res_data.get("status") == "ok":
                return f"A IA local respondeu e executou: {res_data.get('reply', 'ok')}"
            else:
                return f"Erro retornado pela IA local: {res_data.get('reply', 'Desconhecido')}"
    except Exception as e:
        return f"Falha ao conectar com o Lumina-AI (O uvicorn está rodando?). Erro: {e}"

if __name__ == "__main__":
    mcp.run()
