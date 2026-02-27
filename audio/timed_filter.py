import time
from pipecat.audio.filters.base_audio_filter import BaseAudioFilter

class TimedFilterWrapper(BaseAudioFilter):
    """
    Wraps any BaseAudioFilter and measures the latency of the filter() call.
    Values are stored in public attributes for the translator to pick up.
    """
    def __init__(self, inner_filter: BaseAudioFilter, sample_rate: int = 16000):
        self._inner = inner_filter
        self._sample_rate = sample_rate
        self.last_filter_ms: float = 0.0
        self.last_chunk_duration_ms: float = 0.0

    async def start(self, sample_rate: int):
        self._sample_rate = sample_rate
        await self._inner.start(sample_rate)

    async def stop(self):
        await self._inner.stop()

    async def filter(self, audio: bytes) -> bytes:
        t0 = time.time()
        result = await self._inner.filter(audio)
        self.last_filter_ms = (time.time() - t0) * 1000

        # 16-bit mono: bytes / (sample_rate * 2) * 1000
        # Use output size, not input — AIC may return different-sized blocks (buffering).
        self.last_chunk_duration_ms = (len(result) / (self._sample_rate * 2)) * 1000 if result else 0.0

        return result

    async def process_frame(self, frame):
        await self._inner.process_frame(frame)
