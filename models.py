import json
from typing import Dict, List, Optional
from controller import ArtNetController

class Fixture:
    """
    Representa um aparelho físico no palco (Mega Par, Moving Head, etc).
    Conhece seus canais DMX locais e calcula os absolutos.
    """
    def __init__(self, f_id: str, label: str, f_type: str, dmx_start: int, position: Dict[str, float], groups: List[str], channels_map: Dict[str, int], total_channels: int, controller: ArtNetController):
        self.id = f_id
        self.label = label
        self.type = f_type
        self.dmx_start = dmx_start
        self.position = position
        self.groups = groups
        self.channels_map = channels_map
        self.total_channels = total_channels
        self.controller = controller

        # HTP / Submasters: valor "programado" do dimmer (antes da escala).
        # O engine injeta dimmer_scaler para aplicar submasters proporcionais.
        self.base_dimmer = 0
        self.dimmer_scaler = None

    def _set_channel_value(self, channel_name: str, value: int):
        """Método auxiliar para calcular endereço DMX real e enviar."""
        if channel_name not in self.channels_map:
            # Fixture não suporta este canal, ignorar silenciosamente
            return False
            
        # Calcula endereço absoluto DMX (offset 1-based, então dmx_start + offset - 1)
        offset = self.channels_map[channel_name]
        abs_address = self.dmx_start + offset - 1
        
        # Garante o limite do DMX (0-255)
        safe_value = max(0, min(255, value))
        return self.controller.set_channel(abs_address, safe_value)

    # --- Métodos Semânticos Genéricos ---

    def set_dimmer(self, intensity: int):
        """Guarda o valor programado e escreve o valor escalado (HTP/submasters)."""
        self.base_dimmer = max(0, min(255, int(intensity)))
        scale = 1.0
        if self.dimmer_scaler:
            try:
                scale = self.dimmer_scaler(self)
            except Exception:
                scale = 1.0
        return self._set_channel_value("dimmer", int(self.base_dimmer * scale))
        
    def set_strobe(self, speed: int):
        success = self._set_channel_value("strobe", speed)
        # MEGA PAR BUG FIX: Se o strobo for zero (desligado), forçar o canal de macro/efeitos para 0
        if speed == 0 and "effects" in self.channels_map:
            self._set_channel_value("effects", 0)
        return success

    # --- Métodos Específicos para Cores (Ex: Pars) ---

    def set_color(self, r: int, g: int, b: int, amber: int = 0):
        """Define cores RGB(A). Ignora canais se não existirem na fixture."""
        success = True
        if "red" in self.channels_map: success &= self._set_channel_value("red", r)
        if "green" in self.channels_map: success &= self._set_channel_value("green", g)
        if "blue" in self.channels_map: success &= self._set_channel_value("blue", b)
        if "amber" in self.channels_map: success &= self._set_channel_value("amber", amber)
        return success

    # --- Métodos Específicos para Moving Heads ---

    def set_pan_tilt(self, pan: int, tilt: int):
        success = True
        if "pan" in self.channels_map: success &= self._set_channel_value("pan", pan)
        if "tilt" in self.channels_map: success &= self._set_channel_value("tilt", tilt)
        return success


class Stage:
    """
    Gerencia todas as fixtures no palco e expõe operações em grupo.
    """
    def __init__(self, palco_json_path: str, fixtures_json_path: str, controller: ArtNetController):
        self.controller = controller
        self.fixtures: List[Fixture] = []
        
        with open(fixtures_json_path, 'r', encoding='utf-8') as f:
            self.fixtures_lib = json.load(f)
            
        with open(palco_json_path, 'r', encoding='utf-8') as f:
            palco_data = json.load(f)
            
        for fix_data in palco_data.get("fixtures", []):
            f_type = fix_data["type"]
            lib_data = self.fixtures_lib.get(f_type)
            if not lib_data:
                print(f"[Stage] Tipo de fixture '{f_type}' desconhecido. Ignorando {fix_data['id']}.")
                continue
                
            fixture = Fixture(
                f_id=fix_data["id"],
                label=fix_data["label"],
                f_type=f_type,
                dmx_start=fix_data["dmx_start"],
                position=fix_data["position"],
                groups=fix_data.get("groups", []),
                channels_map=lib_data["channels"],
                total_channels=lib_data["total_channels"],
                controller=self.controller
            )
            self.fixtures.append(fixture)
            
    def get_fixture(self, f_id: str) -> Optional[Fixture]:
        for f in self.fixtures:
            if f.id == f_id:
                return f
        return None
        
    def get_by_type(self, f_type: str) -> List[Fixture]:
        return [f for f in self.fixtures if f.type == f_type]

    def get_all_fixtures(self) -> List[Dict]:
        """Retorna uma lista serializável das fixtures para a UI"""
        res = []
        for f in self.fixtures:
            res.append({
                "id": f.id,
                "label": f.label,
                "type": f.type,
                "position": f.position,
                "groups": getattr(f, "groups", [])
            })
        return res

    def update_position(self, f_id: str, x: float, y: float, z: float, palco_json_path: str):
        """Atualiza a posição de uma fixture e salva no arquivo palco.json"""
        f = self.get_fixture(f_id)
        if f:
            f.position = {"x": x, "y": y, "z": z}
            
            # Atualiza no arquivo JSON original
            try:
                with open(palco_json_path, 'r', encoding='utf-8') as file:
                    data = json.load(file)
                
                for item in data.get("fixtures", []):
                    if item["id"] == f_id:
                        item["position"] = f.position
                        break
                        
                with open(palco_json_path, 'w', encoding='utf-8') as file:
                    json.dump(data, file, indent=2, ensure_ascii=False)
                return True
            except Exception as e:
                print(f"[Stage] Erro ao salvar palco.json: {e}")
        return False

    def save_groups(self, palco_json_path: str):
        """Persiste os grupos atuais das fixtures no palco.json (usado pelo auto-grouping)."""
        try:
            with open(palco_json_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
            by_id = {f.id: f for f in self.fixtures}
            for item in data.get("fixtures", []):
                f = by_id.get(item.get("id"))
                if f:
                    item["groups"] = list(f.groups)
            with open(palco_json_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[Stage] Erro ao salvar grupos: {e}")
            return False

    # --- Operações de Grupo (Semânticas para IA) ---
    
    def set_all_colors(self, r: int, g: int, b: int):
        """Muda a cor de todos os refletores que suportam RGB."""
        for f in self.fixtures:
            f.set_color(r, g, b)
            
    def set_all_dimmer(self, intensity: int):
        """Define o dimmer de todas as fixtures que têm esse canal."""
        for f in self.fixtures:
            f.set_dimmer(intensity)
