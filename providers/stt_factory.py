"""
STT Provider Factory - Creates the appropriate STT service based on config.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _parse_vocab_lines(vocab_str: str) -> list:
    """Parse vocabulary string into (word, sounds_like) tuples.

    Format: one entry per line, optionally "word|sound1,sound2"
    """
    parsed = []
    for line in vocab_str.split("\n"):
        line = line.strip().strip(",")
        if not line:
            continue
        parts = line.split("|")
        word = parts[0].strip()
        if not word:
            continue
        sounds_like = [s.strip() for s in parts[1].split(",")] if len(parts) > 1 else []
        sounds_like = [s for s in sounds_like if s]
        parsed.append((word, sounds_like))
    return parsed


def _truncate_vocab(entries: list, limit: int, provider: str) -> list:
    """Truncate vocabulary list to provider limit with a warning log."""
    if len(entries) > limit:
        logger.warning(
            f"{provider} STT custom vocabulary limit is {limit}. "
            f"Truncating {len(entries)} entries to {limit}."
        )
        return entries[:limit]
    return entries


def create_stt_service(config, session=None) -> Any:
    """Create STT service based on config.stt.provider.

    Supported providers:
    - elevenlabs: ElevenLabsRealtimeSTTService (default)
    - deepgram: DeepgramSTTService
    - gladia: GladiaSTTService
    - speechmatics: SpeechmaticsSTTService
    - gemini_live: GeminiLiveSTTService (Gemini Live WebSocket API)

    Returns a Pipecat FrameProcessor-compatible STT service.
    """
    provider = getattr(config.stt, "provider", "elevenlabs")
    logger.info(f"Creating STT service: provider={provider}")

    _CREATORS = {
        "elevenlabs": _create_elevenlabs_stt,
        "deepgram": _create_deepgram_stt,
        "gladia": _create_gladia_stt,
        "speechmatics": _create_speechmatics_stt,
        "gemini_live": _create_gemini_live_stt,
    }
    creator = _CREATORS.get(provider)
    if creator is None:
        raise ValueError(
            f"Unknown STT provider: {provider}. "
            f"Supported: {', '.join(_CREATORS)}"
        )
    return creator(config)


def _create_elevenlabs_stt(config):
    """Create ElevenLabs Realtime STT service."""
    from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService, CommitStrategy

    api_key = getattr(config.stt, "api_key", "")
    if not api_key:
        raise ValueError("ElevenLabs API key is required for STT. Set ELEVENLABS_API_KEY in .env or admin panel.")

    # ElevenLabs Scribe v2 requires ISO 639-3 or language name
    lang = config.stt.language.lower()
    mapping = {
        "tr": "tur",
        "en": "eng",
        "es": "spa",
        "fr": "fra",
        "de": "deu",
        "it": "ita",
        "ru": "rus",
        "ar": "ara"
    }
    elevenlabs_lang = mapping.get(lang, lang)
    stt = ElevenLabsRealtimeSTTService(
        api_key=api_key,
        model=getattr(config.stt, "model", "scribe_v2_realtime"),
        sample_rate=config.audio.sample_rate,
        params=ElevenLabsRealtimeSTTService.InputParams(
            language_code=elevenlabs_lang,
            commit_strategy=CommitStrategy.VAD,
            # Removed invalid kwargs (vad_silence_threshold_secs, vad_threshold, etc.) 
            # because Pipecat's ElevenLabs service defines its own VAD internally.
        ),
    )
    logger.info(f"ElevenLabs STT created: model={config.stt.model}, lang={elevenlabs_lang}")
    return stt


def _create_deepgram_stt(config):
    """Create Deepgram STT service."""
    from deepgram import LiveOptions
    from pipecat.services.deepgram.stt import DeepgramSTTService

    api_key = getattr(config.stt, "deepgram_api_key", "")
    model = getattr(config.stt, "deepgram_model", "nova-3")

    if not api_key:
        raise ValueError("Deepgram API key is required. Set DEEPGRAM_API_KEY in .env or admin panel.")

    # Parse custom vocabulary if enabled
    keywords = None
    if getattr(config.stt, "enable_custom_vocabulary", False):
        vocab_str = getattr(config.stt, "stt_deepgram_vocabulary", "")
        seen = set()
        parsed = []
        for word, _ in _parse_vocab_lines(vocab_str):
            if word not in seen:
                seen.add(word)
                parsed.append(word)
        parsed = _truncate_vocab(parsed, 100, "Deepgram")
        if parsed:
            keywords = parsed

    # utterance_end_ms expects str (Deepgram SDK type: Optional[str])
    utterance_end_ms = str(getattr(config.stt, "deepgram_utterance_end_ms", "1000"))

    # nova-2 and nova-3 use `keyterm` (newer, more accurate).
    # Older models use legacy `keywords` parameter.
    use_keyterm = model.startswith(("nova-2", "nova-3"))

    live_options = LiveOptions(
        model=model,
        language=config.stt.language,
        encoding="linear16",
        channels=1,
        sample_rate=config.audio.sample_rate,
        interim_results=True,
        smart_format=getattr(config.stt, "deepgram_smart_format", True),
        punctuate=getattr(config.stt, "deepgram_punctuate", True),
        no_delay=getattr(config.stt, "deepgram_no_delay", True),
        utterance_end_ms=utterance_end_ms,
        keyterm=keywords if use_keyterm else None,
        keywords=None if use_keyterm else keywords,
    )

    stt = DeepgramSTTService(
        api_key=api_key,
        sample_rate=config.audio.sample_rate,
        live_options=live_options,
    )
    logger.info(f"Deepgram STT created: model={model}, lang={config.stt.language}")
    return stt


def _create_gladia_stt(config):
    """Create Gladia STT service."""
    from pipecat.services.gladia.config import (
        GladiaInputParams,
        LanguageConfig,
        PreProcessingConfig,
    )
    from pipecat.services.gladia.stt import GladiaSTTService

    api_key = getattr(config.stt, "gladia_api_key", "")
    model = getattr(config.stt, "gladia_model", "solaria-1")

    if not api_key:
        raise ValueError("Gladia API key is required. Set GLADIA_API_KEY in .env or admin panel.")

    code_switching = getattr(config.stt, "gladia_code_switching", False)
    audio_enhancer = getattr(config.stt, "gladia_audio_enhancer", False)
    endpointing = getattr(config.stt, "gladia_endpointing", 0.5)
    max_duration = getattr(config.stt, "gladia_max_duration", 5)

    language_config = LanguageConfig(
        languages=[config.stt.language],
        code_switching=code_switching,
    )

    params_kwargs = {
        "language_config": language_config,
        "endpointing": endpointing,
        "maximum_duration_without_endpointing": max_duration,
    }

    if getattr(config.stt, "enable_custom_vocabulary", False):
        vocab_str = getattr(config.stt, "stt_gladia_vocabulary", "")
        intensity = max(0.0, min(1.0, float(getattr(config.stt, "gladia_vocab_intensity", 0.5))))
        parsed = []
        for word, sounds_like in _parse_vocab_lines(vocab_str):
            if sounds_like:
                from pipecat.services.gladia.config import CustomVocabularyItem
                parsed.append(CustomVocabularyItem(value=word, intensity=intensity, pronunciations=sounds_like))
            else:
                parsed.append(word)

        parsed = _truncate_vocab(parsed, 250, "Gladia")

        if parsed:
            from pipecat.services.gladia.config import RealtimeProcessingConfig, CustomVocabularyConfig
            rt_config = RealtimeProcessingConfig(
                custom_vocabulary=True,
                custom_vocabulary_config=CustomVocabularyConfig(vocabulary=parsed)
            )
            params_kwargs["realtime_processing"] = rt_config

    if audio_enhancer:
        params_kwargs["pre_processing"] = PreProcessingConfig(audio_enhancer=True)

    stt = GladiaSTTService(
        api_key=api_key,
        model=model,
        sample_rate=config.audio.sample_rate,
        params=GladiaInputParams(**params_kwargs),
    )
    logger.info(f"Gladia STT created: model={model}, lang={config.stt.language}")
    return stt


def _create_speechmatics_stt(config):
    """Create Speechmatics STT service.

    TurnDetectionMode:
      - EXTERNAL (default): Pipecat'in VAD'ı endpointing'i kontrol eder.
        Mevcut pipeline mimarisiyle (InputBuffer + Silero VAD) güvenli entegrasyon.
      - SMART_TURN: Speechmatics'in ML tabanlı VAD'ı — dil bağlamını anlıyor,
        Türkçe gibi diller için daha iyi cümle sınırı tespiti.
      - ADAPTIVE: Speechmatics'in sessizlik tabanlı VAD'ı.
    """
    from pipecat.services.speechmatics.stt import SpeechmaticsSTTService

    api_key = getattr(config.stt, "speechmatics_api_key", "")
    language = getattr(config.stt, "speechmatics_language", "") or config.stt.language or "en"
    enable_partials = getattr(config.stt, "speechmatics_enable_partials", True)
    max_delay = getattr(config.stt, "speechmatics_max_delay", 1.0)
    mode_str = getattr(config.stt, "speechmatics_turn_detection", "external").lower()

    if not api_key:
        raise ValueError("Speechmatics API key required. Set SPEECHMATICS_API_KEY in .env or admin panel.")

    # Map config string → TurnDetectionMode enum
    _mode_map = {
        "external": SpeechmaticsSTTService.TurnDetectionMode.EXTERNAL,
        "smart_turn": SpeechmaticsSTTService.TurnDetectionMode.SMART_TURN,
        "adaptive": SpeechmaticsSTTService.TurnDetectionMode.ADAPTIVE,
    }
    if mode_str not in _mode_map:
        logger.warning(f"Invalid Speechmatics turn_detection mode '{mode_str}', falling back to EXTERNAL")
    turn_mode = _mode_map.get(mode_str, SpeechmaticsSTTService.TurnDetectionMode.EXTERNAL)

    params = SpeechmaticsSTTService.InputParams(
        language=language,
        turn_detection_mode=turn_mode,
        include_partials=enable_partials,
        max_delay=max_delay,
    )
    
    if getattr(config.stt, "enable_custom_vocabulary", False):
        vocab_str = getattr(config.stt, "stt_speechmatics_vocabulary", "")
        parsed = []
        for word, sounds_like in _parse_vocab_lines(vocab_str):
            if sounds_like:
                parsed.append(SpeechmaticsSTTService.AdditionalVocabEntry(content=word, sounds_like=sounds_like))
            else:
                parsed.append(SpeechmaticsSTTService.AdditionalVocabEntry(content=word))

        parsed = _truncate_vocab(parsed, 1000, "Speechmatics")

        if parsed:
            params.additional_vocab = parsed

    stt = SpeechmaticsSTTService(
        api_key=api_key,
        sample_rate=config.audio.sample_rate,
        params=params,
    )
    logger.info(
        f"Speechmatics STT created: lang={language}, mode={mode_str}, "
        f"partials={enable_partials}, max_delay={max_delay}"
    )
    return stt


def _create_gemini_live_stt(config):
    """Create Gemini Live STT service (WebSocket real-time transcription)."""
    from providers.gemini_stt_service import GeminiLiveSTTService

    api_key = getattr(config.stt, "gemini_api_key", "")
    model = getattr(config.stt, "gemini_stt_model", "gemini-2.5-flash-native-audio-preview-12-2025")
    silence_ms = getattr(config.stt, "gemini_stt_silence_duration_ms", 400)
    end_sensitivity = getattr(config.stt, "gemini_stt_end_sensitivity", "HIGH")
    start_sensitivity = getattr(config.stt, "gemini_stt_start_sensitivity", "HIGH")
    prefix_padding_ms = getattr(config.stt, "gemini_stt_prefix_padding_ms", 0) or 0
    custom_instruction = getattr(config.stt, "gemini_stt_system_instruction", "")
    context_compression = getattr(config.stt, "gemini_stt_context_compression", True)
    domain_vocabulary = getattr(config.stt, "gemini_stt_domain_vocabulary", "")
    punctuation_mode = getattr(config.stt, "gemini_stt_punctuation_mode", True)

    if not api_key:
        raise ValueError("Google API key required for Gemini Live STT. Set GOOGLE_API_KEY in .env or admin panel.")

    return GeminiLiveSTTService(
        api_key=api_key,
        model=model,
        language=config.stt.language,
        sample_rate=config.audio.sample_rate,
        silence_duration_ms=silence_ms,
        end_sensitivity=end_sensitivity,
        start_sensitivity=start_sensitivity,
        prefix_padding_ms=prefix_padding_ms,
        custom_system_instruction=custom_instruction,
        context_compression=context_compression,
        domain_vocabulary=domain_vocabulary,
        punctuation_mode=punctuation_mode,
    )
