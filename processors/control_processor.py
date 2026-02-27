"""
Control processor for handling client-side control messages.
"""

from typing import Optional, TYPE_CHECKING

from pipecat.frames.frames import Frame, TTSUpdateSettingsFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from utils.logger import get_logger

if TYPE_CHECKING:
    from processors.translator import TranslateToTTSSpeakProcessor

logger = get_logger("control_processor")


class ControlProcessor(FrameProcessor):
    """Processes client control messages."""

    def __init__(
        self,
        translator: Optional["TranslateToTTSSpeakProcessor"] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._translator = translator
        self._audio_filter = None  # Audio filter reference (AIC or RNNoise)
        self._tts_service = None
        self._current_speed = 1.0
        self._noise_filter_enabled = True


    def set_translator(self, translator: "TranslateToTTSSpeakProcessor") -> None:
        self._translator = translator

    def set_audio_filter(self, audio_filter) -> None:
        """Set audio filter reference for toggle operations."""
        self._audio_filter = audio_filter

    def set_tts_service(self, tts_service) -> None:
        self._tts_service = tts_service

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

    async def handle_client_message(self, msg_type: str, data: dict) -> dict:
        """Handle incoming client control message."""
        logger.info(f"Control message received: {msg_type}")

        if msg_type == "set_speed":
            return await self._handle_set_speed(data)
        elif msg_type == "clear_buffer":
            return await self._handle_clear_buffer()
        elif msg_type == "reset_all":
            return await self._handle_reset_all()
        elif msg_type == "set_noise_filter":
            return await self._handle_set_noise_filter(data)
        elif msg_type == "delete_last":
            return await self._handle_delete_last()
        elif msg_type == "get_translations":
            return await self._handle_get_translations()
        elif msg_type == "delete_translation":
            return await self._handle_delete_translation(data)
        elif msg_type == "get_status":
            return await self._handle_get_status()
        else:
            return {"status": "ok", "message": "Action ignored (feature disabled)"}

    async def _handle_set_speed(self, data: dict) -> dict:
        """Handle speed change request."""
        speed = data.get("speed", 1.0)

        # Validate speed range (ElevenLabs: 0.7-1.2)
        if not 0.7 <= speed <= 1.2:
            return {
                "status": "error",
                "message": f"Speed must be between 0.7 and 1.2, got {speed}"
            }

        self._current_speed = speed
        updated = False

        # Method 1: Push TTSUpdateSettingsFrame through pipeline (Pipecat-native)
        try:
            await self.push_frame(
                TTSUpdateSettingsFrame(settings={"speed": speed}),
                FrameDirection.DOWNSTREAM,
            )
            logger.bind(terminal=True).info(f"TTS speed changed to: {speed}")
            updated = True
            return {"status": "ok", "speed": speed}
        except Exception as e:
            logger.warning(f"TTSUpdateSettingsFrame failed: {e}, trying direct update")

        # Method 2: Direct settings modification (fallback)
        if not updated and self._tts_service:
            try:
                if hasattr(self._tts_service, '_settings') and self._tts_service._settings is not None:
                    settings = self._tts_service._settings
                    if isinstance(settings, dict):
                        settings['speed'] = speed
                    else:
                        settings.speed = speed
                    logger.bind(terminal=True).info(f"TTS speed changed to: {speed} (direct)")
                    updated = True
                else:
                    logger.warning("TTS service has no _settings attribute")
            except Exception as e:
                logger.error(f"Failed to update TTS speed: {e}")
                return {"status": "error", "message": str(e)}

        if not updated:
            logger.warning("Could not update TTS speed - no method available")

        return {"status": "ok", "speed": speed}

    async def _handle_clear_buffer(self) -> dict:
        if self._translator:
            await self._translator.clear_buffers()
            return {"status": "ok", "message": "Buffers cleared"}
        return {"status": "error", "message": "Translator not found"}

    async def _handle_reset_all(self) -> dict:
        if self._translator:
            await self._translator.reset_all()
            return {"status": "ok", "message": "Full reset completed"}
        else:
            return {"status": "error", "message": "Translator not configured"}

    async def _handle_delete_last(self) -> dict:
        """Handle delete last translation request."""
        if self._translator:
            result = await self._translator.delete_last_translation()
            logger.bind(terminal=True).info(f"Deleted last translation: {result.get('deleted_text', result.get('deleted', '?'))}")
            return result
        else:
            return {"status": "error", "message": "Translator not configured"}

    async def _handle_get_translations(self) -> dict:
        """Return the current translation list for the UI."""
        if self._translator:
            return {
                "status": "ok",
                "translations": self._translator.get_translations_list(),
            }
        return {"status": "ok", "translations": []}

    async def _handle_delete_translation(self, data: dict) -> dict:
        """Handle selective deletion of a translation by ID."""
        translation_id = data.get("id")
        if not translation_id:
            return {"status": "error", "message": "Missing translation ID"}
        if self._translator:
            result = await self._translator.delete_translation_by_id(translation_id)
            logger.bind(terminal=True).info(
                f"Deleted translation {translation_id}: {result.get('deleted_text', '?')}"
            )
            return result
        return {"status": "error", "message": "Translator not configured"}

    async def _handle_get_status(self) -> dict:
        """Return current control status."""
        result = {
            "status": "ok",
            "speed": self._current_speed,
            "noise_filter_enabled": self._noise_filter_enabled,
            "noise_filter_connected": self._audio_filter is not None,
            "translator_connected": self._translator is not None,
        }
        if self._translator:
            result["translations"] = self._translator.get_translations_list()
        return result

    async def _handle_set_noise_filter(self, data: dict) -> dict:
        """Handle noise filter toggle."""
        enabled = data.get("enabled", True)
        self._noise_filter_enabled = enabled

        # Toggle filter via FilterEnableFrame
        if self._audio_filter:
            try:
                from pipecat.frames.frames import FilterEnableFrame
                await self._audio_filter.process_frame(FilterEnableFrame(enable=enabled))
                state = "enabled" if enabled else "disabled"
                logger.bind(terminal=True).info(f"Noise filter {state}")
            except Exception as e:
                logger.error(f"Failed to toggle noise filter: {e}")
                return {"status": "error", "message": str(e)}
        else:
            state = "enabled" if enabled else "disabled"
            logger.bind(terminal=True).info(f"Noise filter {state} (no filter connected)")

        return {"status": "ok", "noise_filter_enabled": enabled}
