"""
TTS Provider Factory - Creates the appropriate TTS service based on config.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def create_tts_service(config) -> Any:
    """Create TTS service based on config.tts.provider.

    Supported providers:
    - elevenlabs: ElevenLabsTTSService (default)
    - deepgram: DeepgramTTSService

    Returns a Pipecat FrameProcessor-compatible TTS service.
    """
    provider = getattr(config.tts, "provider", "elevenlabs")
    logger.info(f"Creating TTS service: provider={provider}")

    if provider == "elevenlabs":
        return _create_elevenlabs_tts(config)
    elif provider == "deepgram":
        return _create_deepgram_tts(config)
    else:
        raise ValueError(f"Unknown TTS provider: {provider}. Supported: elevenlabs, deepgram")


def _create_elevenlabs_tts(config):
    """Create ElevenLabs TTS service."""
    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

    api_key = getattr(config.tts, "api_key", "") or ""
    if not api_key:
        raise ValueError("ElevenLabs API key is required for TTS. Set ELEVENLABS_API_KEY in .env or admin panel.")

    # Style: 0 means default (None to omit)
    style_val = getattr(config.tts, "style", 0)
    style = style_val if style_val and style_val > 0 else None

    use_speaker_boost = getattr(config.tts, "use_speaker_boost", True)

    # Text normalization: "auto" means default (None to omit)
    text_norm = getattr(config.tts, "apply_text_normalization", "auto")
    apply_text_normalization = text_norm if text_norm != "auto" else None

    input_params = {
        "stability": config.tts.stability,
        "similarity_boost": config.tts.similarity_boost,
        "speed": config.tts.speed,
        "use_speaker_boost": use_speaker_boost,
    }
    if style is not None:
        input_params["style"] = style
    if apply_text_normalization is not None:
        input_params["apply_text_normalization"] = apply_text_normalization

    tts = ElevenLabsTTSService(
        api_key=api_key,
        voice_id=config.tts.voice_id,
        model=config.tts.model,
        sample_rate=config.audio.output_sample_rate,
        params=ElevenLabsTTSService.InputParams(**input_params),
    )
    logger.info(f"ElevenLabs TTS created: model={config.tts.model}, voice={config.tts.voice_id[:8]}...")
    return tts


def _create_deepgram_tts(config):
    """Create Deepgram TTS service."""
    from pipecat.services.deepgram.tts import DeepgramTTSService

    api_key = getattr(config.tts, "deepgram_api_key", "") or ""
    model = getattr(config.tts, "deepgram_model", "aura-asteria-en")

    if not api_key:
        raise ValueError("Deepgram API key is required for TTS. Set DEEPGRAM_API_KEY in .env or admin panel.")

    encoding = getattr(config.tts, "deepgram_encoding", "linear16")

    tts = DeepgramTTSService(
        api_key=api_key,
        voice=model,
        sample_rate=config.audio.output_sample_rate,
        encoding=encoding,
    )
    logger.info(f"Deepgram TTS created: model={model}")
    return tts
