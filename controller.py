import socket
import struct
import time
import threading

class ArtNetController:
    """
    Controlador DMX 100% focado em Art-Net (UDP).
    O Lumina-AI agora atua como a 'mesa' principal, enviando os 512 canais DMX crus 
    para o QLC+ via rede local, que repassa pro cabo Enttec e pro Magic 3D.
    """
    def __init__(self, ip="127.0.0.1", port=6454):
        self.ip = ip
        self.port = port
        
        self.socket_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.dmx_buffer = bytearray(512)
        
        self.running = False
        self._thread = None

    def start_loop(self):
        """Inicia uma thread que envia o pacote Art-Net a ~30fps."""
        if not self.running:
            self.running = True
            self._thread = threading.Thread(target=self._artnet_loop, daemon=True)
            self._thread.start()
            print("[Lumina-AI] Transmissão Art-Net iniciada em background.")

    def stop_loop(self):
        """Para a transmissão Art-Net."""
        self.running = False
        if self._thread:
            self._thread.join()

    def set_channel(self, address: int, value: int):
        """Define o valor (0-255) de um canal DMX específico (1-512)."""
        if 1 <= address <= 512:
            self.dmx_buffer[address - 1] = max(0, min(255, int(value)))
            return True
        return False

    def get_channel(self, address: int):
        if 1 <= address <= 512:
            return self.dmx_buffer[address - 1]
        return 0

    def _artnet_loop(self):
        """Loop contínuo para manter os refletores atualizados."""
        # Cabeçalho Art-Net fixo
        header = b'Art-Net\x00'
        opcode = struct.pack('<H', 0x5000) # OpCode ArtDmx
        version = struct.pack('>H', 14)
        seq = b'\x00'
        physical = b'\x00'
        universe = struct.pack('<H', 0)
        length = struct.pack('>H', 512)
        
        while self.running:
            packet = header + opcode + version + seq + physical + universe + length + self.dmx_buffer
            try:
                self.socket_udp.sendto(packet, (self.ip, self.port))
            except Exception as e:
                print(f"[Art-Net Erro]: {e}")
            
            time.sleep(1/30.0) # ~30 quadros por segundo
