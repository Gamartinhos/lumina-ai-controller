import pyaudio
import numpy as np
import threading
import time

class AudioSyncAnalyzer:
    """
    Captura áudio em tempo real e detecta frequências graves (Kicks/BPM).
    Quando um grave forte é detectado, ele dispara um callback.
    """
    def __init__(self, on_beat_callback=None):
        self.CHUNK = 1024
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 44100
        
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.running = False
        self._thread = None
        self.on_beat_callback = on_beat_callback
        
        # Limiar de detecção (Ajustável dependendo do volume geral)
        self.threshold = 1.5 
        self.bass_history = []

    def start(self):
        try:
            # Tenta usar o Stereo Mix (Loopback) ou o microfone padrão
            # Num ambiente de produção, é ideal listar os dispositivos e escolher o Virtual Audio Cable
            self.stream = self.p.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                frames_per_buffer=self.CHUNK
            )
            self.running = True
            self._thread = threading.Thread(target=self._process_audio, daemon=True)
            self._thread.start()
            print("[Áudio] Captura de música iniciada.")
        except Exception as e:
            print(f"[Áudio] Erro ao iniciar captura: {e}")

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join()
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.p.terminate()

    def _process_audio(self):
        while self.running:
            try:
                data = np.frombuffer(self.stream.read(self.CHUNK, exception_on_overflow=False), dtype=np.int16)
                
                # Aplica a Transformada Rápida de Fourier (FFT) para pegar as frequências
                fft_data = np.abs(np.fft.rfft(data))
                
                # Pega a média da banda de graves (20Hz a 120Hz)
                # Índices simplificados baseados na taxa de amostragem
                bass_band = np.mean(fft_data[1:10]) 
                
                self.bass_history.append(bass_band)
                if len(self.bass_history) > 20:
                    self.bass_history.pop(0)
                    
                local_avg = np.mean(self.bass_history)
                
                # Se o grave atual é muito maior que a média recente (um "KICK")
                if bass_band > local_avg * self.threshold and local_avg > 10000:
                    if self.on_beat_callback:
                        self.on_beat_callback()
                    # Sleep curto pra não disparar o mesmo bumbo 2 vezes
                    time.sleep(0.1) 
                    
            except Exception as e:
                pass
            time.sleep(0.01)
