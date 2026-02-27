"""
Audio Writer - Çevrilmiş sesi dosyaya kaydet
"""

from pathlib import Path
from typing import List, Optional
import wave

from pydub import AudioSegment

from config import get_config

config = get_config()


class AudioWriter:
    """
    Audio Writer - TTS çıktısını dosyaya kaydet
    
    PCM audio frame'leri toplar ve WAV/MP3 olarak kaydeder.
    """
    
    def __init__(
        self,
        output_path: Optional[str] = None,
        sample_rate: int = None,
    ):
        self.output_path = Path(output_path) if output_path else None
        self.sample_rate = sample_rate or config.audio.output_sample_rate
        self._audio_chunks: List[bytes] = []
        self._total_bytes = 0
    
    def add_audio(self, audio_data: bytes):
        """Audio chunk ekle"""
        self._audio_chunks.append(audio_data)
        self._total_bytes += len(audio_data)
    
    def clear(self):
        """Buffer'ı temizle"""
        self._audio_chunks.clear()
        self._total_bytes = 0
    
    def save_wav(self, output_path: Optional[str] = None) -> Path:
        """WAV olarak kaydet"""
        path = Path(output_path) if output_path else self.output_path
        if not path:
            raise ValueError("No output path specified")
        
        # .wav uzantısını garantile
        if path.suffix.lower() != '.wav':
            path = path.with_suffix('.wav')
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Tüm audio'yu birleştir
        all_audio = b''.join(self._audio_chunks)
        
        # WAV dosyası yaz
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)  # 16-bit
            wav.setframerate(self.sample_rate)
            wav.writeframes(all_audio)
        
        duration = len(all_audio) / (self.sample_rate * 2)
        print(f"Saved WAV: {path} ({duration:.1f}s)")
        
        return path
    
    def save_mp3(self, output_path: Optional[str] = None, bitrate: str = "192k") -> Path:
        """MP3 olarak kaydet"""
        path = Path(output_path) if output_path else self.output_path
        if not path:
            raise ValueError("No output path specified")
        
        # .mp3 uzantısını garantile
        if path.suffix.lower() != '.mp3':
            path = path.with_suffix('.mp3')
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Önce WAV olarak kaydet, sonra MP3'e dönüştür
        all_audio = b''.join(self._audio_chunks)
        
        # AudioSegment oluştur
        audio = AudioSegment(
            data=all_audio,
            sample_width=2,  # 16-bit
            frame_rate=self.sample_rate,
            channels=1
        )
        
        # MP3 olarak kaydet
        audio.export(str(path), format="mp3", bitrate=bitrate)
        
        duration = len(audio) / 1000
        print(f"Saved MP3: {path} ({duration:.1f}s)")
        
        return path
    
    @property
    def total_duration_seconds(self) -> float:
        """Toplam süre (saniye)"""
        return self._total_bytes / (self.sample_rate * 2)  # 16-bit mono
    
    @property
    def buffer_size_bytes(self) -> int:
        """Buffer boyutu (bytes)"""
        return self._total_bytes
