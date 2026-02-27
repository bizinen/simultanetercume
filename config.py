"""
Pipecat Simultane Tercüman - Yapılandırma Modülü
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv(override=True)


def _env_bool(key: str, default: str = "false") -> bool:
    """Read an environment variable as a boolean (true/false string)."""
    return os.getenv(key, default).lower() == "true"


def _language_name(code: str) -> str:
    code = (code or "").lower()
    return {
        "tr": "Türkçe",
        "en": "İngilizce",
        "ru": "Rusça",
        "de": "Almanca",
        "fr": "Fransızca",
        "es": "İspanyolca",
        "it": "İtalyanca",
        "ar": "Arapça",
    }.get(code, code or "hedef dil")


def _default_system_prompt(source_language: str, target_language: str) -> str:
    """
    Generates a system prompt by loading a template from 'llm_prompt.txt'
    and populating language variables.
    """
    src_name = _language_name(source_language)
    tgt_name = _language_name(target_language)
    
    # Get the directory where the current script is located
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_dir, "llm_prompt.txt")
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            template = f.read()
            
        # Format the template with the language names
        return template.format(src_name=src_name, tgt_name=tgt_name)
    
    except FileNotFoundError:
        # Fallback logic or a descriptive error
        raise FileNotFoundError(f"Could not find llm_prompt.txt at {file_path}")
    except KeyError as e:
        # This happens if the .txt file has {braces} that aren't variables
        raise KeyError(f"Missing or extra placeholders in llm_prompt.txt: {e}")


@dataclass
class STTConfig:
    """STT yapılandırması - Multi-provider destekli"""
    provider: str = field(default_factory=lambda: os.getenv("STT_PROVIDER", "elevenlabs"))
    # ElevenLabs (default)
    api_key: str = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY", ""))
    language: str = field(default_factory=lambda: os.getenv("SOURCE_LANGUAGE", "tr"))
    model: str = field(default_factory=lambda: os.getenv("STT_MODEL", "scribe_v2_realtime"))
    # Deepgram
    deepgram_api_key: str = field(default_factory=lambda: os.getenv("DEEPGRAM_API_KEY", ""))
    deepgram_model: str = field(default_factory=lambda: os.getenv("DEEPGRAM_MODEL", "nova-3"))
    # Gladia
    gladia_api_key: str = field(default_factory=lambda: os.getenv("GLADIA_API_KEY", ""))
    gladia_model: str = field(default_factory=lambda: os.getenv("GLADIA_MODEL", "solaria-1"))
    # VAD ayarları - akıcı konuşma için optimize edildi
    vad_silence_threshold: float = field(default_factory=lambda: float(os.getenv("VAD_SILENCE_THRESHOLD", "0.6")))
    vad_threshold: float = field(default_factory=lambda: float(os.getenv("VAD_THRESHOLD", "0.5")))
    min_speech_duration_ms: int = field(default_factory=lambda: int(os.getenv("MIN_SPEECH_DURATION_MS", "250")))
    min_silence_duration_ms: int = field(default_factory=lambda: int(os.getenv("MIN_SILENCE_DURATION_MS", "200")))
    # Deepgram-specific
    deepgram_smart_format: bool = field(default_factory=lambda: _env_bool("DEEPGRAM_SMART_FORMAT", "true"))
    deepgram_punctuate: bool = field(default_factory=lambda: _env_bool("DEEPGRAM_PUNCTUATE", "true"))
    deepgram_no_delay: bool = field(default_factory=lambda: _env_bool("DEEPGRAM_NO_DELAY", "false"))
    deepgram_utterance_end_ms: str = field(default_factory=lambda: os.getenv("DEEPGRAM_UTTERANCE_END_MS", "1000"))
    
    # --- Özel Sözlükler (Custom Vocabularies) ---
    # Sözlük özelliği genel olarak aktif mi? (STT sekmesindeki tetikleyici)
    enable_custom_vocabulary: bool = field(default_factory=lambda: _env_bool("STT_ENABLE_CUSTOM_VOCABULARY", "false"))
    # Her sağlayıcı için birbirinden bağımsız sözlük listeleri
    stt_deepgram_vocabulary: str = field(default_factory=lambda: os.getenv("STT_DEEPGRAM_VOCABULARY", "") or os.getenv("DEEPGRAM_KEYWORDS", ""))
    stt_gladia_vocabulary: str = field(default_factory=lambda: os.getenv("STT_GLADIA_VOCABULARY", ""))
    stt_speechmatics_vocabulary: str = field(default_factory=lambda: os.getenv("STT_SPEECHMATICS_VOCABULARY", ""))
    # Gladia custom vocabulary intensity (0.0 = hafif, 1.0 = güçlü)
    gladia_vocab_intensity: float = field(default_factory=lambda: float(os.getenv("STT_GLADIA_VOCAB_INTENSITY", "0.5")))
    # Gladia-specific
    gladia_endpointing: float = field(default_factory=lambda: float(os.getenv("GLADIA_ENDPOINTING", "0.5")))
    gladia_max_duration: int = field(default_factory=lambda: int(os.getenv("GLADIA_MAX_DURATION", "5")))
    gladia_audio_enhancer: bool = field(default_factory=lambda: _env_bool("GLADIA_AUDIO_ENHANCER", "false"))
    gladia_code_switching: bool = field(default_factory=lambda: _env_bool("GLADIA_CODE_SWITCHING", "false"))
    # Speechmatics
    speechmatics_api_key: str = field(default_factory=lambda: os.getenv("SPEECHMATICS_API_KEY", ""))
    speechmatics_language: str = field(default_factory=lambda: os.getenv("SPEECHMATICS_LANGUAGE", "tr"))
    speechmatics_enable_partials: bool = field(default_factory=lambda: _env_bool("SPEECHMATICS_PARTIALS", "true"))
    speechmatics_max_delay: float = field(default_factory=lambda: float(os.getenv("SPEECHMATICS_MAX_DELAY", "1.0")))
    # external | smart_turn | adaptive
    speechmatics_turn_detection: str = field(default_factory=lambda: os.getenv("SPEECHMATICS_TURN_DETECTION", "external"))
    # Gemini Live STT
    # GOOGLE_STT_API_KEY varsa onu kullan, yoksa GOOGLE_API_KEY'e fall back et.
    # Bu sayede STT ve LLM Gemini için farklı API key kullanılabilir.
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_STT_API_KEY") or os.getenv("GOOGLE_API_KEY", ""))
    gemini_stt_model: str = field(default_factory=lambda: os.getenv("GEMINI_STT_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"))
    gemini_stt_silence_duration_ms: int = field(default_factory=lambda: int(os.getenv("GEMINI_STT_SILENCE_MS", "400")))
    gemini_stt_end_sensitivity: str = field(default_factory=lambda: os.getenv("GEMINI_STT_END_SENSITIVITY", "HIGH"))
    gemini_stt_start_sensitivity: str = field(default_factory=lambda: os.getenv("GEMINI_STT_START_SENSITIVITY", "HIGH"))
    gemini_stt_prefix_padding_ms: int = field(default_factory=lambda: int(os.getenv("GEMINI_STT_PREFIX_PADDING_MS", "0")))
    gemini_stt_system_instruction: str = field(default_factory=lambda: os.getenv("GEMINI_STT_SYSTEM_INSTRUCTION", ""))
    # Context Window Compression: uzun oturumlarda token taşmasını önler (true/false)
    gemini_stt_context_compression: bool = field(default_factory=lambda: _env_bool("GEMINI_STT_CONTEXT_COMPRESSION", "true"))
    # Domain kelime listesi — virgülle ayrılmış terimler system prompt'a enjekte edilir
    gemini_stt_domain_vocabulary: str = field(default_factory=lambda: os.getenv("GEMINI_STT_DOMAIN_VOCABULARY", ""))
    # Noktalama + büyük harf modu
    gemini_stt_punctuation_mode: bool = field(default_factory=lambda: _env_bool("GEMINI_STT_PUNCTUATION_MODE", "true"))


@dataclass
class LLMConfig:
    """LLM yapılandırması — Multi-provider destekli"""
    # Provider seçimi: openai | gemini | groq
    provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai"))

    # OpenAI (default) — standard ve fine-tuned modeller (ft:...) desteklenir
    api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    # LLM_MODEL: provider-agnostic model adı. Fallback: OPENAI_MODEL (geriye dönük uyumluluk)
    model: str = field(default_factory=lambda: (
        os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    ))

    # Google Gemini
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))

    # Groq — ultra-fast inference (console.groq.com)
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))

    # Çeviri prompt'u
    system_prompt: str = field(
        default_factory=lambda: os.getenv("SYSTEM_PROMPT")
        or _default_system_prompt(
            os.getenv("SOURCE_LANGUAGE", "tr"),
            os.getenv("TARGET_LANGUAGE", "en"),
        )
    )


@dataclass 
class TTSConfig:
    """TTS yapılandırması - Multi-provider destekli"""
    provider: str = field(default_factory=lambda: os.getenv("TTS_PROVIDER", "elevenlabs"))
    # ElevenLabs (default)
    api_key: str = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY", ""))
    voice_id: str = field(default_factory=lambda: os.getenv("ELEVENLABS_VOICE_ID", "nPczCjzI2devNBz1zQrb"))
    voice_id_male: str = field(default_factory=lambda: os.getenv("ELEVENLABS_VOICE_ID_MALE", "pNInz6obpgDQGcFmaJgB"))
    voice_id_female: str = field(default_factory=lambda: os.getenv("ELEVENLABS_VOICE_ID_FEMALE", "Xb7hH8MSUJpSbSDYk0k2"))
    model: str = field(default_factory=lambda: os.getenv("TTS_MODEL", "eleven_flash_v2_5"))
    speed: float = field(default_factory=lambda: float(os.getenv("TTS_SPEED", "0.95")))
    stability: float = field(default_factory=lambda: float(os.getenv("TTS_STABILITY", "0.75")))
    similarity_boost: float = field(default_factory=lambda: float(os.getenv("TTS_SIMILARITY_BOOST", "0.3")))
    output_format: str = "pcm_24000"  # 24kHz PCM
    # Streaming gecikme optimizasyonu (0-4 arası)
    optimize_streaming_latency: int = field(default_factory=lambda: int(os.getenv("TTS_OPTIMIZE_LATENCY", "4")))
    # Deepgram
    deepgram_api_key: str = field(default_factory=lambda: os.getenv("DEEPGRAM_API_KEY", ""))
    deepgram_model: str = field(default_factory=lambda: os.getenv("DEEPGRAM_TTS_MODEL", "aura-asteria-en"))
    # ElevenLabs-specific
    style: float = field(default_factory=lambda: float(os.getenv("TTS_STYLE", "0")))
    use_speaker_boost: bool = field(default_factory=lambda: _env_bool("TTS_USE_SPEAKER_BOOST", "true"))
    apply_text_normalization: str = field(default_factory=lambda: os.getenv("TTS_TEXT_NORMALIZATION", "auto"))
    # Deepgram-specific
    deepgram_encoding: str = field(default_factory=lambda: os.getenv("DEEPGRAM_TTS_ENCODING", "linear16"))


@dataclass
class AudioConfig:
    """Ses işleme yapılandırması"""
    sample_rate: int = field(default_factory=lambda: int(os.getenv("AUDIO_SAMPLE_RATE", "16000")))  # STT için
    output_sample_rate: int = field(default_factory=lambda: int(os.getenv("AUDIO_OUTPUT_SAMPLE_RATE", "24000")))  # TTS için
    channels: int = field(default_factory=lambda: int(os.getenv("AUDIO_CHANNELS", "1")))
    chunk_size_ms: int = field(default_factory=lambda: int(os.getenv("AUDIO_CHUNK_SIZE_MS", "100")))  # 100ms chunks
    # AIC Filter (ai-coustics SDK) - gürültü giderici
    aic_enabled: bool = field(default_factory=lambda: _env_bool("AIC_ENABLED", "true"))
    # Lisans anahtarı: AIC_LICENSE_KEY veya AIC_SDK_LICENSE (ai-coustics resmi adı)
    aic_license_key: str = field(default_factory=lambda: os.getenv("AIC_LICENSE_KEY") or os.getenv("AIC_SDK_LICENSE", ""))
    aic_model_id: str = field(default_factory=lambda: os.getenv("AIC_MODEL_ID", "quail-vf-l-16khz"))
    # Gain compensation: AIC azalttığı ses seviyesini otomatik geri yükler
    aic_gain_compensation: bool = field(default_factory=lambda: _env_bool("AIC_GAIN_COMPENSATION", "true"))


@dataclass
class VerifierConfig:
    """Fast Verifier LLM yapılandırması"""
    enabled: bool = field(default_factory=lambda: _env_bool("VERIFIER_ENABLED", "false"))
    provider: str = field(default_factory=lambda: os.getenv("VERIFIER_PROVIDER", "groq"))
    model: str = field(default_factory=lambda: os.getenv("VERIFIER_MODEL", "llama3-8b-8192"))
    timeout: float = field(default_factory=lambda: float(os.getenv("VERIFIER_TIMEOUT", "3.0")))
    prompt: str = field(default_factory=lambda: os.getenv("VERIFIER_PROMPT", "You are a fast speech-to-text verifier. Your job is to read transcriptions and fix minor errors or drop garbage transcriptions (like background noise transcribed as 'you', 'so', 'right', 'uh'). If the text is garbage or incomplete meaningless fragment, respond exactly with 'DROP'. Otherwise, respond with 'KEEP|' followed by the corrected translation. Example: 'KEEP|This is the corrected text.'"))



@dataclass
class TranslationConfig:
    """Ana yapılandırma"""
    source_language: str = field(default_factory=lambda: os.getenv("SOURCE_LANGUAGE", "tr"))
    target_language: str = field(default_factory=lambda: os.getenv("TARGET_LANGUAGE", "en"))
    
    stt: STTConfig = field(default_factory=STTConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    verifier: VerifierConfig = field(default_factory=VerifierConfig)
    
    # Latency hedefi (ms) - kalite öncelikli
    target_latency_ms: int = field(default_factory=lambda: int(os.getenv("TARGET_LATENCY_MS", "5000")))
    
    # Logging
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


# Global config instance
config = TranslationConfig()


def get_config() -> TranslationConfig:
    """Yapılandırmayı döndür"""
    return config
