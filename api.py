import os
import json
import time
import shutil
import asyncio
import urllib.request
import urllib.error
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from controller import ArtNetController
from engine import LightingEngine
from models import Stage

app = FastAPI(title="Lumina-AI Bar Edition")

# --- Instâncias Globais do Motor DMX ---
ctrl = None
stage = None
engine = None

def get_engine():
    global ctrl, stage, engine
    if engine is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        fixtures_path = os.path.join(base_dir, "fixtures.json")
        palco_path = os.path.join(base_dir, "palco.json")
        
        ctrl = ArtNetController(ip="127.0.0.1", port=6454)
        stage = Stage(palco_path, fixtures_path, ctrl)
        engine = LightingEngine(ctrl, stage)
        engine.start()
    return engine

# ==========================================
# WEBSOCKETS (Sincronização Real-Time)
# ==========================================

class ConnectionManager:
    """Gerencia conexões WebSocket de múltiplos clientes (DJ no celular, VJ no PC)."""
    def __init__(self):
        self.active: list[WebSocket] = []
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_threadsafe(self, message: dict):
        """Chamado pelo engine (threads de efeito) para empurrar eventos ao loop asyncio."""
        if self.loop and self.active:
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)

ws_manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")
            if msg_type == "audio_band":
                # Sound-to-Light: trigger de FFT vindo do navegador
                get_engine().handle_audio_band(data.get("band", "bass"), float(data.get("energy", 1.0)))
            elif msg_type == "submaster":
                get_engine().set_submaster(data.get("group", "todos"), float(data.get("level", 1.0)))
            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception:
        ws_manager.disconnect(ws)

@app.on_event("startup")
async def startup_event():
    ws_manager.loop = asyncio.get_running_loop()
    eng = get_engine()
    eng.on_event = ws_manager.broadcast_threadsafe
    print("[API] Motor DMX iniciado via FastAPI (WebSockets ativos em /ws)")

@app.on_event("shutdown")
def shutdown_event():
    if engine:
        engine.stop()

# --- Modelos de Entrada ---
class ColorRequest(BaseModel):
    r: int
    g: int
    b: int

class StrobeRequest(BaseModel):
    speed: int

class FadeRequest(BaseModel):
    r: int
    g: int
    b: int
    duration: float

class ChaseRequest(BaseModel):
    r: int
    g: int
    b: int
    speed_ms: int

class AutoDjRequest(BaseModel):
    enabled: bool

class PositionUpdateRequest(BaseModel):
    id: str
    x: float
    y: float
    z: float

class McpToolRequest(BaseModel):
    tool_name: str
    kwargs: dict

# --- Rotas de Gerenciamento do Palco (Planta) ---
@app.get("/api/fixtures")
def get_fixtures():
    # Passamos o stage diretamente do motor
    eng = get_engine()
    if eng and eng.stage:
        return {"status": "ok", "fixtures": eng.stage.get_all_fixtures()}
    return {"status": "error", "message": "Motor não iniciado"}

@app.get("/api/fixtures/library")
def get_fixture_library():
    # Caminho onde os .fxt estão
    fixture_dir = r"C:\Users\Gabriel Martins\Desktop\Claude acesso\Fixture"
    library = []
    
    if os.path.exists(fixture_dir):
        for filename in os.listdir(fixture_dir):
            if filename.lower().endswith(".fxt"):
                filepath = os.path.join(fixture_dir, filename)
                try:
                    with open(filepath, 'r', encoding='latin1') as f:
                        lines = [l.strip() for l in f.readlines()]
                        
                    if len(lines) >= 5:
                        name = lines[3]
                        total_channels = int(lines[4])
                        # Cria um identificador limpo
                        f_id = filename.replace(".fxt", "").replace(" ", "_").upper()
                        library.append({
                            "id": f_id,
                            "filename": filename,
                            "name": name,
                            "total_channels": total_channels
                        })
                except Exception as e:
                    print(f"Erro lendo {filename}: {e}")
                    
    return {"status": "ok", "library": library}

class PatchRequest(BaseModel):
    filename: str
    quantity: int
    total_channels: int
    fxt_name: str
    fxt_id: str

@app.post("/api/patch")
def patch_fixtures(req: PatchRequest):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    palco_path = os.path.join(base_dir, "palco.json")
    fixtures_lib_path = os.path.join(base_dir, "fixtures.json")
    
    try:
        # Lê palco atual
        with open(palco_path, 'r', encoding='utf-8') as f:
            palco_data = json.load(f)
            
        # Calcula último DMX
        highest_dmx = 0
        for fx in palco_data.get("fixtures", []):
            start = fx.get("dmx_start", 1)
            # Para não quebrar caso não exista no palco, assumimos que total_channels está salvo no fixtures.json, 
            # mas podemos ter que procurar. Como não sabemos, usamos uma estimativa de 16 ou procuramos no lib.
            highest_dmx = max(highest_dmx, start + 30) # safe margin se não sabemos
            
        # Melhor: obter o highest exato consultando os totais:
        with open(fixtures_lib_path, 'r', encoding='utf-8') as f:
            lib_data = json.load(f)
            
        highest_dmx = 0
        for fx in palco_data.get("fixtures", []):
            start = fx.get("dmx_start", 1)
            t_id = fx.get("type", "")
            t_chan = 1
            if t_id in lib_data:
                t_chan = lib_data[t_id].get("total_channels", 1)
            highest_dmx = max(highest_dmx, start + t_chan - 1)
            
        next_dmx = highest_dmx + 1
        
        # Se for uma fixture nova, adiciona no fixtures.json
        if req.fxt_id not in lib_data:
            lib_data[req.fxt_id] = {
                "name": req.fxt_name,
                "total_channels": req.total_channels,
                "channels": {} # vazio, o usuario precisara mapear manualmente se for desconhecida
            }
            with open(fixtures_lib_path, 'w', encoding='utf-8') as f:
                json.dump(lib_data, f, indent=2, ensure_ascii=False)
                
        # Adiciona N fixtures no palco
        added = []
        for i in range(req.quantity):
            f_id = f"{req.fxt_id.lower()}_{int(time.time()*1000) + i}"
            new_fx = {
                "id": f_id,
                "label": f"{req.fxt_name} {i+1}",
                "type": req.fxt_id,
                "dmx_start": next_dmx,
                "position": {"x": 0.0 + (i*0.5), "y": 0.0, "z": 0.0},
                "groups": []
            }
            palco_data.setdefault("fixtures", []).append(new_fx)
            added.append(new_fx)
            next_dmx += req.total_channels
            
        with open(palco_path, 'w', encoding='utf-8') as f:
            json.dump(palco_data, f, indent=2, ensure_ascii=False)
            
        # Recarrega o stage no engine!
        eng = get_engine()
        if eng:
            import models
            # Recria a classe stage lendo do disco e re-injeta o scaler HTP
            eng.attach_stage(models.Stage(palco_path, fixtures_lib_path, eng.controller))
            
        return {"status": "ok", "added": added}
    except Exception as e:
        print("Erro no patch:", e)
        return {"status": "error", "message": str(e)}

@app.post("/api/update_position")
def update_position(req: PositionUpdateRequest):
    eng = get_engine()
    if eng and eng.stage:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        palco_path = os.path.join(base_dir, "palco.json")
        success = eng.stage.update_position(req.id, req.x, req.y, req.z, palco_path)
        return {"status": "ok" if success else "error"}
    return {"status": "error"}

@app.post("/api/upload_bg")
async def upload_bg(file: UploadFile = File(...)):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bg_path = os.path.join(base_dir, "ui", "bg.jpg")
    with open(bg_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "ok", "message": "Planta atualizada com sucesso"}

@app.get("/api/state/capture")
def capture_state():
    eng = get_engine()
    if eng and eng.stage:
        state = []
        for f in eng.stage.fixtures:
            channels = {}
            for ch_name, offset in f.channels_map.items():
                val = eng.controller.get_channel(f.dmx_start + offset - 1)
                channels[ch_name] = val
            state.append({"id": f.id, "channels": channels})
        return {"status": "ok", "state": state}
    return {"status": "error"}

# --- Rotas API para Luzes ---
@app.post("/api/blackout")
def set_blackout():
    get_engine().set_blackout()
    return {"status": "ok", "message": "Blackout ativado"}

@app.post("/api/autodj")
def toggle_auto_dj(req: AutoDjRequest):
    if req.enabled:
        get_engine().enable_auto_dj()
    else:
        get_engine().disable_auto_dj()
    return {"status": "ok"}

@app.post("/api/color")
def set_color(req: ColorRequest):
    get_engine().set_all_colors(req.r, req.g, req.b)
    return {"status": "ok"}

@app.post("/api/strobe")
def set_strobe(req: StrobeRequest):
    get_engine().set_all_strobe(req.speed)
    return {"status": "ok"}

@app.post("/api/fade")
def run_fade(req: FadeRequest):
    get_engine().run_fade(req.r, req.g, req.b, req.duration)
    return {"status": "ok"}

@app.post("/api/chase")
def run_chase(req: ChaseRequest):
    get_engine().run_chase(req.r, req.g, req.b, req.speed_ms)
    return {"status": "ok"}

class DimmerRequest(BaseModel):
    intensity: int

@app.post("/api/dimmer")
def set_dimmer(req: DimmerRequest):
    get_engine().set_all_dimmer(req.intensity)
    return {"status": "ok"}

@app.post("/api/stop_effects")
def api_stop_effects():
    eng = get_engine()
    eng.stop_effect()
    eng.set_all_strobe(0)
    eng.disable_auto_dj()
    return {"status": "ok", "message": "Efeitos interrompidos"}

class ShapeRequest(BaseModel):
    shape: str
    speed: float = 1.0
    size: float = 1.0
    fixture_ids: list | None = None

@app.post("/api/shape")
def run_shape(req: ShapeRequest):
    get_engine().run_shape(req.shape, req.speed, req.size, req.fixture_ids)
    return {"status": "ok"}

class MasterSpeedRequest(BaseModel):
    factor: float

@app.post("/api/master_speed")
def set_master_speed(req: MasterSpeedRequest):
    get_engine().set_master_speed(req.factor)
    return {"status": "ok"}

class FlashRequest(BaseModel):
    on: bool

@app.post("/api/flash")
def set_flash(req: FlashRequest):
    get_engine().set_blinder(req.on)
    return {"status": "ok"}

@app.post("/api/undo")
def undo_last():
    ok = get_engine().undo_last()
    return {"status": "ok" if ok else "error", "message": "Ação revertida" if ok else "Nada para desfazer"}

@app.get("/api/status")
def get_status():
    eng = get_engine()
    artnet_on = bool(eng and eng.controller and eng.controller.running)
    llm_online = False
    try:
        probe = urllib.request.Request("http://localhost:11434/v1/models")
        with urllib.request.urlopen(probe, timeout=1.5) as resp:
            llm_online = resp.status == 200
    except Exception:
        llm_online = False
    return {"status": "ok", "artnet": artnet_on, "llm": llm_online}

class PanTiltRequest(BaseModel):
    id: str
    pan: int
    tilt: int

@app.post("/api/fixture_pantilt")
def set_fixture_pantilt(req: PanTiltRequest):
    eng = get_engine()
    if eng and eng.stage:
        f = eng.stage.get_fixture(req.id)
        if f:
            f.set_pan_tilt(req.pan, req.tilt)
            ws_manager.broadcast_threadsafe({"type": "pantilt", "id": req.id, "pan": req.pan, "tilt": req.tilt})
            return {"status": "ok"}
    return {"status": "error"}

class SequenceRequest(BaseModel):
    name: str
    steps: list
    is_sequence: bool = True

@app.post("/api/sequences")
def save_sequence(req: SequenceRequest):
    try:
        btn_path = os.path.join(os.path.dirname(__file__), "buttons.json")
        buttons = []
        if os.path.exists(btn_path):
            with open(btn_path, 'r', encoding='utf-8') as f:
                buttons = json.load(f)
        
        buttons.append({
            "name": req.name,
            "is_sequence": True,
            "steps": req.steps
        })
        
        with open(btn_path, 'w', encoding='utf-8') as f:
            json.dump(buttons, f, indent=4)
        ws_manager.broadcast_threadsafe({"type": "buttons_changed"})
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

class PlaySequenceRequest(BaseModel):
    steps: list
    loop: bool = False

@app.post("/api/sequences/play")
def play_sequence(req: PlaySequenceRequest):
    get_engine().run_sequence(req.steps, loop=req.loop)
    return {"status": "ok"}

@app.post("/api/sequences/stop")
def stop_sequence():
    eng = get_engine()
    eng.effect_flags["sequence"] = False
    eng._emit({"type": "sequence_stopped"})
    return {"status": "ok"}

# ==========================================
# SUBMASTERS (HTP) / GRAND MASTER
# ==========================================

class SubmasterRequest(BaseModel):
    group: str
    level: float  # 0.0 - 1.0

@app.post("/api/submaster")
def set_submaster(req: SubmasterRequest):
    get_engine().set_submaster(req.group, req.level)
    return {"status": "ok"}

@app.get("/api/submasters")
def get_submasters():
    eng = get_engine()
    data = eng.get_submasters()
    # Lista todos os grupos existentes no palco para a UI montar os faders
    groups = set()
    for f in eng.stage.fixtures:
        groups.update(getattr(f, "groups", []))
    data["groups"] = sorted(groups)
    data["status"] = "ok"
    return data

class GrandMasterRequest(BaseModel):
    level: float

@app.post("/api/grand_master")
def set_grand_master(req: GrandMasterRequest):
    get_engine().set_grand_master(req.level)
    return {"status": "ok"}

# ==========================================
# SOUND-TO-LIGHT (FFT do navegador)
# ==========================================

class SoundToLightRequest(BaseModel):
    enabled: bool

@app.post("/api/sound_to_light")
def set_sound_to_light(req: SoundToLightRequest):
    get_engine().set_sound_to_light(req.enabled)
    return {"status": "ok"}

# ==========================================
# AUTO-GROUPING (K-MEANS)
# ==========================================

class AutoGroupRequest(BaseModel):
    k: int = 3

@app.post("/api/auto_group")
def auto_group(req: AutoGroupRequest):
    eng = get_engine()
    mapping = eng.auto_group(req.k)
    palco_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "palco.json")
    eng.stage.save_groups(palco_path)
    return {"status": "ok", "mapping": mapping}

# ==========================================
# FIXTURE BUILDER (cria aparelhos do zero)
# ==========================================

class FixtureBuilderRequest(BaseModel):
    fxt_id: str
    name: str
    channels: dict  # {"dimmer": 1, "red": 2, ...} offsets 1-based
    total_channels: int

@app.post("/api/fixtures/builder")
def build_fixture(req: FixtureBuilderRequest):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fixtures_lib_path = os.path.join(base_dir, "fixtures.json")
    try:
        with open(fixtures_lib_path, 'r', encoding='utf-8') as f:
            lib_data = json.load(f)

        fxt_id = req.fxt_id.strip().replace(" ", "_").upper()
        if not fxt_id:
            return {"status": "error", "message": "ID inválido"}

        # Valida offsets dentro do total de canais
        for ch_name, offset in req.channels.items():
            if not (1 <= int(offset) <= req.total_channels):
                return {"status": "error", "message": f"Canal '{ch_name}' fora do range (1-{req.total_channels})"}

        lib_data[fxt_id] = {
            "name": req.name,
            "total_channels": req.total_channels,
            "channels": {k: int(v) for k, v in req.channels.items()}
        }
        with open(fixtures_lib_path, 'w', encoding='utf-8') as f:
            json.dump(lib_data, f, indent=2, ensure_ascii=False)

        # Recarrega o stage para que fixtures existentes desse tipo peguem o novo mapa
        eng = get_engine()
        if eng:
            import models
            palco_path = os.path.join(base_dir, "palco.json")
            eng.attach_stage(models.Stage(palco_path, fixtures_lib_path, eng.controller))

        return {"status": "ok", "fxt_id": fxt_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}

class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
def chat_with_ai(req: ChatRequest):
    # Ferramentas expostas para a IA Local (LM Studio)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "set_blackout",
                "description": "Apaga todas as luzes imediatamente."
            }
        },
        {
            "type": "function",
            "function": {
                "name": "stop_effects",
                "description": "Para qualquer efeito dinâmico em andamento (chase, fade, strobo, auto-dj) mantendo as luzes acesas com as cores atuais. Use quando o usuário pedir para 'apagar os efeitos', 'parar o efeito', etc."
            }
        },
        {
            "type": "function",
            "function": {
                "name": "set_color",
                "description": "Muda a cor de todas as luzes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "r": {"type": "integer", "description": "Vermelho (0-255)"},
                        "g": {"type": "integer", "description": "Verde (0-255)"},
                        "b": {"type": "integer", "description": "Azul (0-255)"}
                    },
                    "required": ["r", "g", "b"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "set_group_color",
                "description": "Muda a cor apenas de um grupo específico de luzes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "group_name": {"type": "string", "enum": ["chao", "parede", "teto", "mega_par", "moving", "todos"], "description": "O nome do grupo de luzes (chao, parede, teto, mega_par, moving)."},
                        "r": {"type": "integer"},
                        "g": {"type": "integer"},
                        "b": {"type": "integer"}
                    },
                    "required": ["group_name", "r", "g", "b"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_fade",
                "description": "Faz um fade (transição suave) para uma nova cor.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "r": {"type": "integer"},
                        "g": {"type": "integer"},
                        "b": {"type": "integer"},
                        "duration": {"type": "number", "description": "Duração em segundos"}
                    },
                    "required": ["r", "g", "b", "duration"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_chase",
                "description": "Faz um efeito chase (corre-luz) rápido.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "r": {"type": "integer"},
                        "g": {"type": "integer"},
                        "b": {"type": "integer"},
                        "speed_ms": {"type": "integer", "description": "Velocidade em milissegundos (ex: 150)"}
                    },
                    "required": ["r", "g", "b", "speed_ms"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_button",
                "description": "Salva a sequência atual ou cria um botão customizado na interface que executa um comando.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Nome curto para o botão (ex: 'Rave' ou 'Polícia')"},
                        "prompt": {"type": "string", "description": "O comando de texto EXATO que reproduz esse efeito (ex: 'pisca vermelho e azul rápido')"}
                    },
                    "required": ["name", "prompt"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "undo_last_action",
                "description": "Desfaz ('oops') a última alteração de luz feita pela IA, voltando ao estado anterior."
            }
        },
        {
            "type": "function",
            "function": {
                "name": "auto_group_lights",
                "description": "Agrupa automaticamente as luzes por proximidade espacial (K-Means nas posições x,y,z). Use quando o usuário pedir para 'agrupar as luzes', 'separar por região', 'agrupar as luzes do fundo/palco'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "k": {"type": "integer", "description": "Número de grupos desejados (2 a 6). Padrão 3."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "set_submaster",
                "description": "Define a intensidade proporcional (0.0 a 1.0) de um submaster de grupo, com merge HTP. Ex: 'baixa as luzes do palco pra metade'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "group_name": {"type": "string", "description": "Nome do grupo (chao, parede, teto, moving, todos, ou auto_*)"},
                        "level": {"type": "number", "description": "Nível 0.0 (apagado) a 1.0 (total)"}
                    },
                    "required": ["group_name", "level"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_shape",
                "description": "Faz os moving heads desenharem uma forma com Pan/Tilt (movimento contínuo).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "shape": {"type": "string", "enum": ["circle", "figure8", "sweep"], "description": "Formato do movimento"},
                        "speed": {"type": "number", "description": "Velocidade do movimento (1.0 = normal)"},
                        "size": {"type": "number", "description": "Tamanho do movimento (1.0 = máximo)"}
                    },
                    "required": ["shape"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "set_position",
                "description": "Aponta os moving heads estaticamente para uma posição específica (NÃO é um movimento contínuo).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "position": {"type": "string", "enum": ["teto", "chao", "meio", "frente", "esquerda", "direita"], "description": "Lugar para apontar as luzes"}
                    },
                    "required": ["position"]
                }
            }
        }
    ]

    eng = get_engine()
    stage_info = " Layout do palco:\n"
    if eng and eng.stage:
        for f in eng.stage.fixtures:
            px = f.position["x"] if isinstance(f.position, dict) else f.position.x
            py = f.position["y"] if isinstance(f.position, dict) else f.position.y
            is_moving = "pan" in f.channels_map
            tipo = "Moving Head (Movimenta Pan/Tilt)" if is_moving else "Luz Fixa (Cores/Dimmer)"
            stage_info += f"- {f.id} ({f.label}) [{tipo}]: grupo {f.groups}, pos(x:{px:.1f}, y:{py:.1f})\n"

    sys_prompt = f"""Você é o Lumina-AI, um Lighting Designer profissional. Use as ferramentas fornecidas. Não invente ferramentas. Responda de forma curta em português.
REGRAS DE OPERAÇÃO - CONTROLE DE ILUMINAÇÃO DMX:

1. Movimentação de Moving Heads (CRÍTICO)
- Você possui DUAS ferramentas distintas para os Moving Heads:
  A) `set_position`: Use EXCLUSIVAMENTE para apontar, mirar ou colocar os aparelhos parados em um lugar fixo. Palavras-chave do usuário: "apontar para", "colocar no", "mirar no", "ficar no" (ex: "pro teto", "pro chao", "pro meio").
  B) `run_shape`: Use EXCLUSIVAMENTE para movimentos contínuos e animações. Palavras-chave: "girar", "varrer", "movimento", "circular" (Formas: "circle", "figure8", "sweep").
- NUNCA use `run_shape` quando o usuário pedir para colocar a luz parada em um local.
- `run_chase` NUNCA move os aparelhos, ele apenas faz as cores piscarem.

2. Efeitos Rodam em Paralelo (MUITO IMPORTANTE)
- `run_chase` (afeta pars fixos) e `run_shape` (afeta moving heads) usam canais de efeito independentes. Eles PODEM e DEVEM ser chamados JUNTOS na mesma coreografia.
- ATENÇÃO: As ferramentas estáticas (`set_group_color`, `set_position`, `stop_effects`) PARAM TODOS OS EFEITOS em andamento naqueles canais.

3. Ordem de Execução e Coreografias
Para pedidos compostos, chame as ferramentas nesta ORDEM:
1º Cor de fundo (`set_group_color` ou `set_color`)
2º Posição estática (`set_position`) OU Movimento contínuo (`run_shape`)
3º Corre-luz/Pisca (`run_chase` ou `run_fade`)

4. Limitações de Tempo e Sequências (EXTREMAMENTE IMPORTANTE)
- Você NÃO CONSEGUE agendar ações para o futuro, nem criar "passos" de uma cena complexa em uma única resposta.
- Se o usuário pedir algo como "vá para o meio e depois para o teto", VOCÊ SÓ PODE FAZER O ÚLTIMO PASSO (ir para o teto) ou ativar um EFEITO CONTÍNUO (`run_shape`). Avise o usuário que ele precisa usar a interface do "Timeline Sequencer" passo-a-passo.

5. Criação de Botões
- Quando o usuário pedir para "salvar essa cena" ou "criar um botão", use a ferramenta `create_button`.

{stage_info}"""

    payload = {
        "model": "qwen2.5:7b-instruct",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": req.message}
        ],
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.3
    }

    try:
        req_ai = urllib.request.Request(
            "http://localhost:11434/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_ai) as response:
            result = json.loads(response.read().decode("utf-8"))
            
        ai_message = result["choices"][0]["message"]
        tool_calls = ai_message.get("tool_calls", [])

        # Guarda um snapshot do estado atual antes de aplicar as mudanças, para permitir "Oops" (undo)
        if tool_calls:
            get_engine().save_undo_point()

        # Executa as ferramentas escolhidas pela IA local
        for tool_call in tool_calls:
            func_name = tool_call["function"]["name"]
            args = json.loads(tool_call["function"]["arguments"])
            
            if func_name == "set_blackout":
                get_engine().set_blackout()
            elif func_name == "stop_effects":
                get_engine().stop_effect()
                get_engine().set_all_strobe(0)
                get_engine().disable_auto_dj()
            elif func_name == "set_color":
                get_engine().set_all_colors(args["r"], args["g"], args["b"])
            elif func_name == "set_group_color":
                get_engine().set_group_color(args["group_name"], args["r"], args["g"], args["b"])
            elif func_name == "set_position":
                get_engine().set_position(args["position"])
            elif func_name == "run_fade":
                get_engine().run_fade(args["r"], args["g"], args["b"], args["duration"])
            elif func_name == "run_chase":
                get_engine().run_chase(args["r"], args["g"], args["b"], args["speed_ms"])
            elif func_name == "auto_group_lights":
                eng2 = get_engine()
                k = int(args.get("k", 3)) if args else 3
                eng2.auto_group(max(2, min(6, k)))
                palco_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "palco.json")
                eng2.stage.save_groups(palco_path)
            elif func_name == "set_submaster":
                get_engine().set_submaster(args["group_name"], float(args["level"]))
            elif func_name == "run_shape":
                get_engine().run_shape(args["shape"], args.get("speed", 1.0), args.get("size", 1.0))
            elif func_name == "undo_last_action":
                get_engine().undo_last()
            elif func_name == "create_button":
                try:
                    btn_path = os.path.join(os.path.dirname(__file__), "buttons.json")
                    buttons = []
                    if os.path.exists(btn_path):
                        with open(btn_path, 'r', encoding='utf-8') as f:
                            buttons = json.load(f)
                    buttons.append({"name": args["name"], "prompt": args["prompt"]})
                    with open(btn_path, 'w', encoding='utf-8') as f:
                        json.dump(buttons, f, indent=4)
                    ws_manager.broadcast_threadsafe({"type": "buttons_changed"})
                except Exception as e:
                    print("Erro ao salvar botão:", e)

        if tool_calls:
            # Ignora o texto livre do modelo quando ele chama ferramentas: o Qwen
            # ocasionalmente vaza pra outro idioma no content depois de gerar tool_calls.
            reply = "Efeito ativado com sucesso!"
        else:
            reply = ai_message.get("content") or "Não entendi o pedido, pode reformular?"

        return {"status": "ok", "reply": reply}
    except Exception as e:
        return {"status": "error", "reply": f"Erro de comunicação com a IA Local: {str(e)}"}

@app.post("/api/execute_tool")
def execute_tool(req: McpToolRequest):
    try:
        func_name = req.tool_name
        args = req.kwargs
        
        if func_name == "set_blackout":
            get_engine().set_blackout()
        elif func_name == "stop_effects":
            get_engine().stop_effect()
            get_engine().set_all_strobe(0)
            get_engine().disable_auto_dj()
        elif func_name == "set_color":
            get_engine().set_all_colors(args["r"], args["g"], args["b"])
        elif func_name == "set_group_color":
            get_engine().set_group_color(args["group_name"], args["r"], args["g"], args["b"])
        elif func_name == "set_position":
            get_engine().set_position(args["position"])
        elif func_name == "run_fade":
            get_engine().run_fade(args["r"], args["g"], args["b"], args.get("duration", 1.0))
        elif func_name == "run_chase":
            get_engine().run_chase(args["r"], args["g"], args["b"], args["speed_ms"])
        elif func_name == "run_shape":
            get_engine().run_shape(args["shape"], args.get("speed", 1.0), args.get("size", 1.0))
        else:
            return {"status": "error", "reply": f"Ferramenta {func_name} desconhecida."}
            
        return {"status": "ok", "reply": f"Comando {func_name} executado com sucesso."}
    except Exception as e:
        return {"status": "error", "reply": f"Erro interno: {str(e)}"}

@app.get("/api/buttons")
def get_buttons():
    try:
        btn_path = os.path.join(os.path.dirname(__file__), "buttons.json")
        if os.path.exists(btn_path):
            with open(btn_path, 'r', encoding='utf-8') as f:
                return {"status": "ok", "buttons": json.load(f)}
    except Exception:
        pass
    return {"status": "ok", "buttons": []}

class ButtonUpdateRequest(BaseModel):
    name: str
    steps: list | None = None
    prompt: str | None = None

@app.put("/api/buttons/{index}")
def update_button(index: int, req: ButtonUpdateRequest):
    """Sobrescreve uma cena/botão existente (edição via Timeline)."""
    try:
        btn_path = os.path.join(os.path.dirname(__file__), "buttons.json")
        if not os.path.exists(btn_path):
            return {"status": "error", "message": "buttons.json não existe"}
        with open(btn_path, 'r', encoding='utf-8') as f:
            buttons = json.load(f)
        if not (0 <= index < len(buttons)):
            return {"status": "error", "message": "Índice inválido"}

        btn = buttons[index]
        btn["name"] = req.name
        if req.steps is not None:
            btn["steps"] = req.steps
            btn["is_sequence"] = True
            btn.pop("prompt", None)
        if req.prompt is not None:
            btn["prompt"] = req.prompt

        with open(btn_path, 'w', encoding='utf-8') as f:
            json.dump(buttons, f, indent=4)
        ws_manager.broadcast_threadsafe({"type": "buttons_changed"})
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.delete("/api/buttons/{index}")
def delete_button(index: int):
    try:
        btn_path = os.path.join(os.path.dirname(__file__), "buttons.json")
        if os.path.exists(btn_path):
            with open(btn_path, 'r', encoding='utf-8') as f:
                buttons = json.load(f)
            if 0 <= index < len(buttons):
                buttons.pop(index)
                with open(btn_path, 'w', encoding='utf-8') as f:
                    json.dump(buttons, f, indent=4)
                ws_manager.broadcast_threadsafe({"type": "buttons_changed"})
                return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Botão não encontrado"}

class FixtureColorRequest(BaseModel):
    id: str
    r: int
    g: int
    b: int
    dimmer: int

@app.post("/api/fixture_color")
def set_fixture_color_route(req: FixtureColorRequest):
    eng = get_engine()
    if eng and eng.stage:
        f = eng.stage.get_fixture(req.id)
        if f:
            f.set_color(req.r, req.g, req.b)
            f.set_dimmer(req.dimmer)
            ws_manager.broadcast_threadsafe({"type": "fixture_color", "id": req.id, "r": req.r, "g": req.g, "b": req.b, "dimmer": req.dimmer})
            return {"status": "ok"}
    return {"status": "error"}

# --- Servir a Interface Gráfica (Frontend) ---
ui_dir = os.path.join(os.path.dirname(__file__), "ui")
os.makedirs(ui_dir, exist_ok=True) # Garante que a pasta existe

app.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")

if __name__ == "__main__":
    print("Iniciando Lumina-AI...")
    print("Acesse http://localhost:8000 no navegador para abrir a interface.")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
