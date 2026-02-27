import time
from typing import Callable, Optional

from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

class TTSTimingObserver(FrameProcessor):
    """
    Observes TTS frames to measure synthesis time and audio duration.
    Calls a callback when the speech segment is complete.
    """
    def __init__(self, on_tts_complete: Callable[[float, float, int, int], None], **kwargs):
        super().__init__(**kwargs)
        self._on_tts_complete = on_tts_complete
        
        # Current segment state
        self._start_ts: Optional[float] = None
        self._audio_bytes: int = 0
        self._sample_rate: int = 24000

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        if isinstance(frame, TTSStartedFrame):
            self._start_ts = time.time()
            self._audio_bytes = 0
            
        elif isinstance(frame, TTSAudioRawFrame):
            self._audio_bytes += len(frame.audio)
            self._sample_rate = frame.sample_rate
            
        elif isinstance(frame, TTSStoppedFrame):
            end_ts = time.time()
            if self._start_ts:
                self._on_tts_complete(
                    self._start_ts,
                    end_ts,
                    self._audio_bytes,
                    self._sample_rate
                )
            # Reset for next segment
            self._start_ts = None
            self._audio_bytes = 0

        await self.push_frame(frame, direction)
