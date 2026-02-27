"""
Configuration Manager - CRUD operations for runtime config with .env persistence.
"""

import os
import re
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("config_manager")

# .env file path
_ENV_PATH = Path(__file__).parent / ".env"


def mask_key(value: str) -> str:
    """Mask API key for display: 'sk-proj-abc...xyz' -> 'sk-pr****xyz'"""
    if not value or len(value) < 10:
        return "****" if value else ""
    return value[:4] + "****" + value[-3:]


def _is_sensitive_field(field_name: str) -> bool:
    """Check if a field contains sensitive data."""
    sensitive_keywords = ("api_key", "secret", "password", "license_key", "token")
    return any(kw in field_name.lower() for kw in sensitive_keywords)


def get_all_config() -> dict:
    """Get all configuration sections with masked sensitive values."""
    from config import get_config
    cfg = get_config()

    def _section_to_dict(section_obj) -> dict:
        result = {}
        for field_name in vars(section_obj):
            if field_name.startswith("_"):
                continue
            value = getattr(section_obj, field_name)
            if _is_sensitive_field(field_name):
                result[field_name] = mask_key(str(value))
                result[f"_{field_name}_set"] = bool(value)  # flag: key var mı?
            else:
                result[field_name] = value
        return result

    audio_dict = _section_to_dict(cfg.audio)
    audio_dict["debug_audio"] = os.getenv("DEBUG_AUDIO", "false").lower() == "true"

    return {
        "stt": _section_to_dict(cfg.stt),
        "tts": _section_to_dict(cfg.tts),
        "llm": _section_to_dict(cfg.llm),
        "audio": audio_dict,
        "general": {
            "source_language": cfg.source_language,
            "target_language": cfg.target_language,
            "log_level": cfg.log_level,
            "target_latency_ms": cfg.target_latency_ms,
        },
        "verifier": _section_to_dict(cfg.verifier),

        "buffer": _get_buffer_config(),
    }


# Mapping: config field -> .env variable name
_ENV_MAP = {
    # STT
    "stt.provider": "STT_PROVIDER",
    "stt.api_key": "ELEVENLABS_API_KEY",
    "stt.language": "SOURCE_LANGUAGE",
    "stt.model": "STT_MODEL",
    "stt.vad_silence_threshold": "VAD_SILENCE_THRESHOLD",
    "stt.vad_threshold": "VAD_THRESHOLD",
    "stt.min_speech_duration_ms": "MIN_SPEECH_DURATION_MS",
    "stt.min_silence_duration_ms": "MIN_SILENCE_DURATION_MS",
    "stt.deepgram_api_key": "DEEPGRAM_API_KEY",
    "stt.deepgram_model": "DEEPGRAM_MODEL",
    "stt.gladia_api_key": "GLADIA_API_KEY",
    "stt.gladia_model": "GLADIA_MODEL",
    # Özel Sözlükler (Vocab)
    "stt.enable_custom_vocabulary": "STT_ENABLE_CUSTOM_VOCABULARY",
    "stt.stt_deepgram_vocabulary": "STT_DEEPGRAM_VOCABULARY",
    "stt.stt_gladia_vocabulary": "STT_GLADIA_VOCABULARY",
    "stt.stt_speechmatics_vocabulary": "STT_SPEECHMATICS_VOCABULARY",
    "stt.gladia_vocab_intensity": "STT_GLADIA_VOCAB_INTENSITY",
    # STT Deepgram-specific
    "stt.deepgram_smart_format": "DEEPGRAM_SMART_FORMAT",
    "stt.deepgram_punctuate": "DEEPGRAM_PUNCTUATE",
    "stt.deepgram_no_delay": "DEEPGRAM_NO_DELAY",
    "stt.deepgram_utterance_end_ms": "DEEPGRAM_UTTERANCE_END_MS",
    "stt.deepgram_keywords": "DEEPGRAM_KEYWORDS",
    # STT Gladia-specific
    "stt.gladia_endpointing": "GLADIA_ENDPOINTING",
    "stt.gladia_max_duration": "GLADIA_MAX_DURATION",
    "stt.gladia_audio_enhancer": "GLADIA_AUDIO_ENHANCER",
    "stt.gladia_code_switching": "GLADIA_CODE_SWITCHING",
    # STT Speechmatics-specific
    "stt.speechmatics_api_key": "SPEECHMATICS_API_KEY",
    "stt.speechmatics_language": "SPEECHMATICS_LANGUAGE",
    "stt.speechmatics_enable_partials": "SPEECHMATICS_PARTIALS",
    "stt.speechmatics_max_delay": "SPEECHMATICS_MAX_DELAY",
    "stt.speechmatics_turn_detection": "SPEECHMATICS_TURN_DETECTION",
    # STT Gemini Live-specific
    # GOOGLE_STT_API_KEY olarak kaydedilir; runtime config.py GOOGLE_API_KEY'e fall back eder.
    "stt.gemini_api_key": "GOOGLE_STT_API_KEY",
    "stt.gemini_stt_model": "GEMINI_STT_MODEL",
    "stt.gemini_stt_silence_duration_ms": "GEMINI_STT_SILENCE_MS",
    "stt.gemini_stt_end_sensitivity": "GEMINI_STT_END_SENSITIVITY",
    "stt.gemini_stt_start_sensitivity": "GEMINI_STT_START_SENSITIVITY",
    "stt.gemini_stt_system_instruction": "GEMINI_STT_SYSTEM_INSTRUCTION",
    "stt.gemini_stt_context_compression": "GEMINI_STT_CONTEXT_COMPRESSION",
    "stt.gemini_stt_domain_vocabulary": "GEMINI_STT_DOMAIN_VOCABULARY",
    "stt.gemini_stt_punctuation_mode": "GEMINI_STT_PUNCTUATION_MODE",
    # TTS
    "tts.provider": "TTS_PROVIDER",
    "tts.api_key": "ELEVENLABS_API_KEY",
    "tts.voice_id": "ELEVENLABS_VOICE_ID",
    "tts.voice_id_male": "ELEVENLABS_VOICE_ID_MALE",
    "tts.voice_id_female": "ELEVENLABS_VOICE_ID_FEMALE",
    "tts.model": "TTS_MODEL",
    "tts.speed": "TTS_SPEED",
    "tts.stability": "TTS_STABILITY",
    "tts.similarity_boost": "TTS_SIMILARITY_BOOST",
    "tts.optimize_streaming_latency": "TTS_OPTIMIZE_LATENCY",
    "tts.deepgram_api_key": "DEEPGRAM_API_KEY",
    "tts.deepgram_model": "DEEPGRAM_TTS_MODEL",
    # TTS ElevenLabs-specific
    "tts.style": "TTS_STYLE",
    "tts.use_speaker_boost": "TTS_USE_SPEAKER_BOOST",
    "tts.apply_text_normalization": "TTS_TEXT_NORMALIZATION",
    # TTS Deepgram-specific
    "tts.deepgram_encoding": "DEEPGRAM_TTS_ENCODING",
    # LLM
    "llm.provider": "LLM_PROVIDER",
    "llm.api_key": "OPENAI_API_KEY",
    "llm.model": "LLM_MODEL",
    "llm.gemini_api_key": "GOOGLE_API_KEY",
    "llm.groq_api_key": "GROQ_API_KEY",
    # Audio
    "audio.sample_rate": "AUDIO_SAMPLE_RATE",
    "audio.output_sample_rate": "AUDIO_OUTPUT_SAMPLE_RATE",
    "audio.channels": "AUDIO_CHANNELS",
    "audio.chunk_size_ms": "AUDIO_CHUNK_SIZE_MS",
    "audio.aic_enabled": "AIC_ENABLED",
    "audio.aic_license_key": "AIC_LICENSE_KEY",
    "audio.aic_model_id": "AIC_MODEL_ID",
    "audio.aic_gain_compensation": "AIC_GAIN_COMPENSATION",
    "audio.debug_audio": "DEBUG_AUDIO",
    # General
    "general.source_language": "SOURCE_LANGUAGE",
    "general.target_language": "TARGET_LANGUAGE",
    "general.log_level": "LOG_LEVEL",
    "general.target_latency_ms": "TARGET_LATENCY_MS",

    # Buffer (translator)
    "buffer.flush_timeout_secs": "BUFFER_FLUSH_TIMEOUT",
    "buffer.min_words_long": "BUFFER_MIN_WORDS_LONG",
    "buffer.min_words_with_punct": "BUFFER_MIN_WORDS_PUNCT",
    "buffer.min_sentences": "BUFFER_MIN_SENTENCES",
    "buffer.min_words_timeout": "BUFFER_MIN_WORDS_TIMEOUT",
    "buffer.max_buffer_words": "BUFFER_MAX_WORDS",
    
    # Verifier
    "verifier.enabled": "VERIFIER_ENABLED",
    "verifier.provider": "VERIFIER_PROVIDER",
    "verifier.model": "VERIFIER_MODEL",
    "verifier.timeout": "VERIFIER_TIMEOUT",
    "verifier.prompt": "VERIFIER_PROMPT",
}


def update_env_var(key: str, value: str) -> None:
    """Update a single variable in .env file. Creates the key if not present."""
    if not _ENV_PATH.exists():
        logger.warning(f".env file not found at {_ENV_PATH}")
        return

    content = _ENV_PATH.read_text(encoding="utf-8")
    pattern = re.compile(rf'^{re.escape(key)}=.*$', re.MULTILINE)

    # Newline karakterlerini escape'le — .env dosya format injection koruması
    safe_value = value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")

    if pattern.search(content):
        new_content = pattern.sub(lambda m: f"{key}={safe_value}", content)
    else:
        new_content = content.rstrip("\n") + f"\n{key}={safe_value}\n"

    _ENV_PATH.write_text(new_content, encoding="utf-8")
    # Update os.environ so runtime picks up the change
    os.environ[key] = value
    logger.info(f"Updated .env: {key}={'****' if _is_sensitive_field(key) else value}")


def update_config_section(section: str, data: dict) -> dict:
    """Update a config section. Persists changes to .env.
    
    Returns dict with updated fields list.
    """
    updated_fields = []

    for field_name, value in data.items():
        # Skip internal flags
        if field_name.startswith("_"):
            continue
        # Skip system_prompt (handled separately via file)
        if field_name == "system_prompt":
            _update_system_prompt(value)
            updated_fields.append(field_name)
            continue

        # Don't update masked key values (user didn't change it)
        if _is_sensitive_field(field_name) and "****" in str(value):
            continue

        env_key_name = f"{section}.{field_name}"
        env_var = _ENV_MAP.get(env_key_name)

        if env_var:
            # Convert booleans to string
            if isinstance(value, bool):
                value = "true" if value else "false"
            update_env_var(env_var, str(value))
            updated_fields.append(field_name)
        else:
            logger.debug(f"No .env mapping for {env_key_name}, skipping persist")

    _apply_runtime_config(section, data, updated_fields)
    return {"status": "ok", "updated_fields": updated_fields}


def _update_system_prompt(content: str) -> None:
    """Update llm_prompt.txt file."""
    prompt_path = Path(__file__).parent / "llm_prompt.txt"
    prompt_path.write_text(content, encoding="utf-8")
    logger.info("Updated llm_prompt.txt")


def _apply_runtime_config(section: str, data: dict, updated_fields: list[str]) -> None:
    if not updated_fields:
        return
    from config import get_config
    cfg = get_config()
    if section in ("stt", "tts", "llm", "audio", "verifier"):
        target = getattr(cfg, section, None)
    else:
        target = cfg
    if not target:
        return
    for field in updated_fields:
        if section == "llm" and field == "system_prompt":
            cfg.llm.system_prompt = data.get("system_prompt", "")
            continue
        if not hasattr(target, field):
            continue
        current = getattr(target, field)
        value = data.get(field)
        coerced = _coerce_value(current, value)
        setattr(target, field, coerced)
    if section == "stt" and "language" in updated_fields:
        cfg.source_language = data.get("language", cfg.source_language)
    if section == "general" and "source_language" in updated_fields:
        if getattr(cfg, "stt", None) and hasattr(cfg.stt, "language"):
            cfg.stt.language = data.get("source_language", cfg.stt.language)


def _coerce_value(current, value):
    if isinstance(current, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
        return bool(value)
    if isinstance(current, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return current
    if isinstance(current, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return current
    return value

def _get_buffer_config() -> dict:
    """Get translator InputBufferConfig values."""
    return {
        "flush_timeout_secs": float(os.getenv("BUFFER_FLUSH_TIMEOUT", "3.0")),
        "min_words_long": int(os.getenv("BUFFER_MIN_WORDS_LONG", "7")),
        "min_words_with_punct": int(os.getenv("BUFFER_MIN_WORDS_PUNCT", "5")),
        "min_sentences": int(os.getenv("BUFFER_MIN_SENTENCES", "2")),
        "min_words_timeout": int(os.getenv("BUFFER_MIN_WORDS_TIMEOUT", "4")),
        "max_buffer_words": int(os.getenv("BUFFER_MAX_WORDS", "30")),
    }


def reset_to_defaults() -> dict:
    """Reset configuration to factory defaults (excluding API Keys)."""
    try:
        from config import _default_system_prompt
        default_prompt = _default_system_prompt("tr", "en")
    except Exception:
        default_prompt = ""

    defaults = {
        "stt": {
            "provider": "elevenlabs",
            "language": "tr",
            "model": "scribe_v2_realtime",
            "deepgram_model": "nova-3",
            "gladia_model": "solaria-1",
            "vad_silence_threshold": 0.6,
            "vad_threshold": 0.5,
            "min_speech_duration_ms": 250,
            "min_silence_duration_ms": 200,
            "deepgram_smart_format": True,
            "deepgram_punctuate": True,
            "deepgram_no_delay": True,
            "deepgram_utterance_end_ms": 1000,
            "gladia_endpointing": 0.5,
            "gladia_max_duration": 5,
            "gladia_audio_enhancer": False,
            "gladia_code_switching": False,
            "gladia_vocab_intensity": 0.5,
            "speechmatics_language": "tr",
            "speechmatics_enable_partials": True,
            "speechmatics_max_delay": 1.0,
            "speechmatics_turn_detection": "external",
            # Vocabulary — reset to disabled/empty
            "enable_custom_vocabulary": False,
            "stt_deepgram_vocabulary": "",
            "stt_gladia_vocabulary": "",
            "stt_speechmatics_vocabulary": "",
            # Gemini Live STT defaults
            "gemini_stt_model": "gemini-2.5-flash-native-audio-preview-12-2025",
            "gemini_stt_silence_duration_ms": 400,
            "gemini_stt_end_sensitivity": "HIGH",
            "gemini_stt_start_sensitivity": "HIGH",
            "gemini_stt_system_instruction": "",
            "gemini_stt_context_compression": True,
            "gemini_stt_domain_vocabulary": "",
            "gemini_stt_punctuation_mode": True,
        },
        "tts": {
            "provider": "elevenlabs",
            "voice_id": "nPczCjzI2devNBz1zQrb",
            "voice_id_male": "pNInz6obpgDQGcFmaJgB",
            "voice_id_female": "Xb7hH8MSUJpSbSDYk0k2",
            "model": "eleven_flash_v2_5",
            "speed": 0.95,
            "stability": 0.75,
            "similarity_boost": 0.3,
            "optimize_streaming_latency": 4,
            "deepgram_model": "aura-asteria-en",
            "style": 0.0,
            "use_speaker_boost": True,
            "apply_text_normalization": "auto",
            "deepgram_encoding": "linear16"
        },
        "llm": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "system_prompt": default_prompt
        },
        "audio": {
            "sample_rate": 16000,
            "output_sample_rate": 24000,
            "channels": 1,
            "chunk_size_ms": 100,
            "aic_enabled": True,
            "aic_model_id": "quail-vf-l-16khz",
            "aic_gain_compensation": True,
            "debug_audio": False
        },
        "buffer": {
            "flush_timeout_secs": 3.0,
            "min_words_long": 7,
            "min_words_with_punct": 5,
            "min_sentences": 2,
            "min_words_timeout": 4,
            "max_buffer_words": 30
        },
        "general": {
            "source_language": "tr",
            "target_language": "en",
            "log_level": "DEBUG",
            "target_latency_ms": 5000
        },
        "verifier": {
            "enabled": False,
            "provider": "groq",
            "model": "llama3-8b-8192",
            "timeout": 3.0,
            "prompt": "You are a fast speech-to-text verifier. Your job is to read transcriptions and fix minor errors or drop garbage transcriptions (like background noise transcribed as 'you', 'so', 'right', 'uh'). If the text is garbage or incomplete meaningless fragment, respond exactly with 'DROP'. Otherwise, respond with 'KEEP|' followed by the corrected text. Example: 'KEEP|This is the corrected text.'"
        }
    }

    results = {}
    for section, data in defaults.items():
        res = update_config_section(section, data)
        results[section] = res["updated_fields"]

    return {"status": "ok", "reset_sections": results}

