"""
Latency Tracking Modülü - STT/LLM/TTS performans ölçümü
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SegmentLatency:
    segment_id: str
    
    # Filter stage
    filter_ms: float = 0.0              # actual processing time
    audio_chunk_duration_ms: float = 0.0 # length of audio chunk filtered
    
    # STT stage
    stt_first_audio_ts: Optional[float] = None  # when first chunk of audio entered STT
    stt_arrival_ts: Optional[float] = None       # when TranscriptionFrame arrived at translator
    
    # LLM stage
    llm_start_ts: Optional[float] = None
    llm_first_token_ts: Optional[float] = None
    llm_end_ts: Optional[float] = None
    llm_token_count: int = 0
    
    # TTS stage
    tts_start_ts: Optional[float] = None       # TTSStartedFrame
    tts_end_ts: Optional[float] = None         # TTSStoppedFrame
    tts_audio_bytes: int = 0                   # Total raw bytes generated
    tts_sample_rate: int = 24000               # Default sample rate
    
    @property
    def stt_processing_ms(self) -> float:
        if self.stt_first_audio_ts is not None and self.stt_arrival_ts is not None:
            return (self.stt_arrival_ts - self.stt_first_audio_ts) * 1000
        return 0.0

    @property
    def llm_ms(self) -> float:
        if self.llm_start_ts is not None and self.llm_end_ts is not None:
            return (self.llm_end_ts - self.llm_start_ts) * 1000
        return 0.0

    @property
    def llm_first_token_ms(self) -> float:
        if self.llm_start_ts is not None and self.llm_first_token_ts is not None:
            return (self.llm_first_token_ts - self.llm_start_ts) * 1000
        return 0.0

    @property
    def tts_synthesis_ms(self) -> float:
        if self.tts_start_ts is not None and self.tts_end_ts is not None:
            return (self.tts_end_ts - self.tts_start_ts) * 1000
        return 0.0

    @property
    def tts_audio_duration_ms(self) -> float:
        # Assumes 16-bit mono: bytes / (sample_rate * 2) * 1000
        if self.tts_audio_bytes > 0:
            return (self.tts_audio_bytes / (self.tts_sample_rate * 2)) * 1000
        return 0.0

    @property
    def total_ms(self) -> float:
        """End-to-end total (from first audio in to TTS done)."""
        if self.stt_first_audio_ts is not None and self.tts_end_ts is not None:
            return (self.tts_end_ts - self.stt_first_audio_ts) * 1000
        return 0.0

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "filter_ms": round(self.filter_ms, 1),
            "audio_chunk_duration_ms": round(self.audio_chunk_duration_ms, 1),
            "stt_processing_ms": round(self.stt_processing_ms, 1),
            "llm_ms": round(self.llm_ms, 1),
            "llm_first_token_ms": round(self.llm_first_token_ms, 1),
            "llm_token_count": self.llm_token_count,
            "tts_synthesis_ms": round(self.tts_synthesis_ms, 1),
            "tts_audio_duration_ms": round(self.tts_audio_duration_ms, 1),
            "total_ms": round(self.total_ms, 1)
        }
