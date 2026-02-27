"""
Pipeline builder for constructing translation pipelines.
"""

from dataclasses import dataclass
from typing import Optional, List, Callable, Any

from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import InputAudioRawFrame, Frame
from routes import context as routes_ctx

import processors
from processors.translator import TranslateToTTSSpeakProcessor
from processors.tts_timing_observer import TTSTimingObserver


class MicMuteFilter(FrameProcessor):
    """
    Blocks microphone (InputAudioRawFrame) packets when an MP3 URL is playing
    so that the two audio streams do not overlap. MP3 frames are passed through
    if tagged with `_is_mp3_stream = True`.
    """
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            is_mp3 = getattr(frame, "_is_mp3_stream", False)
            if not is_mp3:
                if routes_ctx.get_pending_mp3_url() or routes_ctx.get_mp3_stream_task():
                    return  # Drop mic frame while MP3 is active

        await self.push_frame(frame, direction)


@dataclass
class PipelineComponents:
    """Container for pipeline components."""

    transport_input: Optional[FrameProcessor]
    transport_output: Optional[FrameProcessor]
    stt: FrameProcessor
    translator: FrameProcessor
    tts: FrameProcessor
    control_processor: Optional[FrameProcessor] = None
    tts_timing_observer: Optional[FrameProcessor] = None


class PipelineBuilder:
    """
    Builds translation pipelines based on mode and configuration.

    Supports two modes:
    - URL mode: Audio comes from server-side MP3 streaming
    - Microphone mode: Audio comes from WebRTC client
    """

    def __init__(
        self,
        components: PipelineComponents,
        url_mode: bool = False,
        monitor_source: bool = False,
    ):
        self.components = components
        self.url_mode = url_mode
        self.monitor_source = monitor_source

    @classmethod
    def create_components(
        cls,
        *,
        transport,
        stt,
        llm,
        tts,
        control_processor=None,
        url_mode: bool = False,
        audio_filter: Optional[Any] = None,
        on_translation: Optional[Callable[[str, str, float], None]] = None,
    ) -> PipelineComponents:
        """Create all pipeline components."""
        translator = TranslateToTTSSpeakProcessor(
            llm_service=llm,
            speak_enabled=True,
            on_translation=on_translation,
            audio_filter=audio_filter
        )

        tts_timing_observer = TTSTimingObserver(
            on_tts_complete=translator._on_tts_complete
        )

        return PipelineComponents(
            transport_input=transport.input() if not url_mode else None,
            transport_output=transport.output(),
            stt=stt,
            translator=translator,
            tts=tts,
            control_processor=control_processor,
            tts_timing_observer=tts_timing_observer,
        )

    def build(self) -> Pipeline:
        """Build and return the pipeline.

        Flow (mic mode):  Input → MicMuteFilter → STT → Translator → [control] → TTS → [timing] → Output
        Flow (URL mode):  STT → Translator → [control] → TTS → [timing] → [Output if not monitor]
        """
        procs: List[FrameProcessor] = []

        # WebRTC input (microphone mode only)
        if not self.url_mode and self.components.transport_input:
            procs.append(self.components.transport_input)
            procs.append(MicMuteFilter())

        # Core processing chain
        procs.extend([self.components.stt, self.components.translator])

        if self.components.control_processor:
            procs.append(self.components.control_processor)

        procs.append(self.components.tts)

        if self.components.tts_timing_observer:
            procs.append(self.components.tts_timing_observer)

        # Skip WebRTC output in URL+monitor_source mode (avoids audio mixing)
        if not (self.url_mode and self.monitor_source) and self.components.transport_output:
            procs.append(self.components.transport_output)

        return Pipeline(procs)
