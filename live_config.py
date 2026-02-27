"""
Live Config Hot-Reload — Applies admin panel changes to running pipeline
without restarting.

Uses Pipecat's UpdateSettingsFrame mechanism + direct attribute updates.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Valid provider names — must match factory supported providers
VALID_STT_PROVIDERS = {"elevenlabs", "deepgram", "gladia", "speechmatics", "gemini_live", "gemini_live_translate"}
VALID_TTS_PROVIDERS = {"elevenlabs", "deepgram"}
VALID_LLM_PROVIDERS = {"openai", "gemini", "groq"}

# Global references to active pipeline services (set by bot_runner.py)
_active_stt: Any = None
_active_tts: Any = None
_active_llm: Any = None
_active_translator: Any = None
_active_control_processor: Any = None
_active_stt_proxy: Any = None
_active_tts_proxy: Any = None
_active_llm_proxy: Any = None
_active_aiohttp_session: Any = None


def _collect_remaining_as_skipped(data: dict, applied: list, skipped: list) -> None:
    """Add any unprocessed data fields to the skipped list."""
    for f in data:
        if f not in applied and f not in skipped:
            skipped.append(f)


def register_services(
    stt=None, tts=None, llm=None, translator=None, control_processor=None,
    stt_proxy=None, tts_proxy=None, llm_proxy=None, aiohttp_session=None,
):
    """Register active pipeline services for hot-reload. Called once at pipeline setup."""
    global _active_stt, _active_tts, _active_llm, _active_translator, _active_control_processor
    global _active_stt_proxy, _active_tts_proxy, _active_llm_proxy, _active_aiohttp_session
    _active_stt = stt
    _active_tts = tts
    _active_llm = llm
    _active_translator = translator
    _active_control_processor = control_processor
    _active_stt_proxy = stt_proxy
    _active_tts_proxy = tts_proxy
    _active_llm_proxy = llm_proxy
    _active_aiohttp_session = aiohttp_session
    logger.info("Live config: services registered for hot-reload (with proxy support)")


async def apply_live_config(section: str, data: dict) -> dict:
    """Apply config changes to live pipeline services.

    Called AFTER config_manager has persisted to .env.
    Returns dict with applied changes info.
    """
    applied = []
    skipped = []

    try:
        if section == "tts":
            applied, skipped = await _apply_tts(data)
        elif section == "stt":
            applied, skipped = await _apply_stt(data)
        elif section == "llm":
            applied, skipped = await _apply_llm(data)
        elif section == "verifier":
            applied, skipped = _apply_verifier(data)
        elif section == "buffer":
            applied, skipped = _apply_buffer(data)
        elif section == "general":
            applied, skipped = _apply_general(data)
        elif section == "audio":
            skipped = list(data.keys())  # Audio sample rates need restart

        else:
            skipped = list(data.keys())
    except Exception as e:
        logger.error(f"Live config apply error for {section}: {e}")
        return {"live_applied": [], "live_skipped": list(data.keys()), "error": str(e)}

    if applied:
        logger.info(f"Live config applied [{section}]: {applied}")
    if skipped:
        logger.debug(f"Live config skipped [{section}]: {skipped}")

    return {"live_applied": applied, "live_skipped": skipped}


# ── Verifier live updates ─────────────────────────────────────────

def _apply_verifier(data: dict) -> tuple[list, list]:
    """Apply Fast Verifier settings. Refreshes the cached client when provider/model/enabled changes."""
    applied = list(data.keys())

    # If critical verifier fields changed, refresh the cached client in the translator
    if _active_translator and any(k in data for k in ("provider", "model", "enabled")):
        if hasattr(_active_translator, "_refresh_verifier_client"):
            try:
                _active_translator._refresh_verifier_client()
                logger.info("[Live Config] Verifier client refreshed")
            except Exception as e:
                logger.error(f"[Live Config] Verifier client refresh failed: {e}")

    return applied, []


# ── TTS live updates ──────────────────────────────────────────────

async def _apply_tts(data: dict) -> tuple[list, list]:
    """Apply TTS changes — supports provider hot-swap via proxy."""
    applied, skipped = [], []

    # ── Provider swap (hot-swap via TTSServiceProxy) ──────────────────
    if "provider" in data and _active_tts_proxy:
        new_provider = data["provider"]
        if new_provider not in VALID_TTS_PROVIDERS:
            logger.warning(f"Invalid TTS provider rejected: {new_provider!r}")
            return [], list(data.keys())
        from config import get_config
        cfg = get_config()
        success = await _active_tts_proxy.switch_provider(new_provider, cfg)
        if success:
            # Provider swap creates a fresh instance with full config —
            # all fields in this request are effectively applied
            applied = list(data.keys())
            global _active_tts
            _active_tts = _active_tts_proxy.active_service
            logger.info(f"TTS provider hot-swapped to: {new_provider}")
            return applied, []
        else:
            skipped.append("provider")

    # ── API key / model change → recreate current provider ────────────
    needs_recreate = False
    if "api_key" in data and "****" not in str(data.get("api_key", "")):
        needs_recreate = True
    if "model" in data:
        needs_recreate = True
    if "deepgram_api_key" in data and "****" not in str(data.get("deepgram_api_key", "")):
        needs_recreate = True

    if needs_recreate and _active_tts_proxy and "provider" not in data:
        from config import get_config
        cfg = get_config()
        success = await _active_tts_proxy.recreate_current(cfg)
        if success:
            _active_tts = _active_tts_proxy.active_service
            # Recreate builds fresh instance — all fields applied
            applied = list(data.keys())
            return applied, []
        else:
            for field in ("api_key", "model", "deepgram_api_key"):
                if field in data:
                    skipped.append(field)

    # ── Live-updatable settings via TTSUpdateSettingsFrame ────────────
    if not _active_control_processor:
        for field in data:
            if field not in applied and field not in skipped:
                skipped.append(field)
        return applied, skipped

    from pipecat.frames.frames import TTSUpdateSettingsFrame
    from pipecat.processors.frame_processor import FrameDirection

    # Fields that can be live-updated via TTSUpdateSettingsFrame
    tts_live_fields = {
        "voice_id": "voice_id",
        "voice_id_male": None,      # Stored for future use, no live push needed
        "voice_id_female": None,     # Stored for future use, no live push needed
        "speed": "speed",
        "stability": "stability",
        "similarity_boost": "similarity_boost",
        "style": "style",
        "use_speaker_boost": "use_speaker_boost",
        "apply_text_normalization": None,  # Restart required (URL param)
        "deepgram_encoding": None,         # Restart required
    }

    settings_to_push = {}

    for field, frame_key in tts_live_fields.items():
        if field in data and field not in applied:
            if frame_key:
                value = data[field]
                # Convert numeric strings
                if field in ("speed", "stability", "similarity_boost", "style"):
                    try:
                        value = float(value)
                    except (ValueError, TypeError):
                        continue
                if field == "use_speaker_boost":
                    if isinstance(value, str):
                        value = value.strip().lower() in ("true", "1", "yes", "on")
                    else:
                        value = bool(value)
                settings_to_push[frame_key] = value
            applied.append(field)

    # Push single combined UpdateSettingsFrame
    if settings_to_push:
        try:
            await _active_control_processor.push_frame(
                TTSUpdateSettingsFrame(settings=settings_to_push),
                FrameDirection.DOWNSTREAM,
            )
            logger.info(f"TTS live update pushed: {list(settings_to_push.keys())}")
        except Exception as e:
            logger.error(f"TTSUpdateSettingsFrame push failed: {e}")
            # Fallback: try direct attribute update on TTS service
            if _active_tts:
                _try_direct_tts_update(settings_to_push)

    _collect_remaining_as_skipped(data, applied, skipped)
    return applied, skipped


def _try_direct_tts_update(settings: dict):
    """Fallback: update TTS service attributes directly."""
    if not _active_tts:
        return
    try:
        if hasattr(_active_tts, "_settings"):
            s = _active_tts._settings
            for k, v in settings.items():
                if isinstance(s, dict):
                    s[k] = v
                elif hasattr(s, k):
                    setattr(s, k, v)
            logger.info(f"TTS direct update applied: {list(settings.keys())}")
    except Exception as e:
        logger.error(f"TTS direct update failed: {e}")


# ── STT live updates ──────────────────────────────────────────────

async def _apply_stt(data: dict) -> tuple[list, list]:
    """Apply STT changes — supports provider hot-swap via proxy."""
    applied, skipped = [], []

    # ── Provider swap (hot-swap via STTServiceProxy) ──────────────────
    if "provider" in data and _active_stt_proxy:
        new_provider = data["provider"]
        if new_provider not in VALID_STT_PROVIDERS:
            logger.warning(f"Invalid STT provider rejected: {new_provider!r}")
            return [], list(data.keys())
        from config import get_config
        cfg = get_config()
        # Get session from registered services
        session = _active_aiohttp_session
        if session:
            success = await _active_stt_proxy.switch_provider(new_provider, cfg, session)
            if success:
                # Provider swap creates a fresh instance — all fields applied
                applied = list(data.keys())
                global _active_stt
                _active_stt = _active_stt_proxy.active_service
                logger.info(f"STT provider hot-swapped to: {new_provider}")
                return applied, []
            else:
                skipped.append("provider")
        else:
            skipped.append("provider")
            logger.warning("STT provider swap skipped — no active aiohttp session")

    # ── API key / model / param change → recreate current provider ────
    needs_recreate = False
    _RECREATE_FIELDS = (
        "api_key", "deepgram_api_key", "gladia_api_key", "speechmatics_api_key",
        "gemini_api_key",
        "model", "deepgram_model", "gladia_model", "gemini_stt_model",
        "deepgram_smart_format", "deepgram_punctuate", "deepgram_keywords",
        "deepgram_utterance_end_ms", "deepgram_no_delay",
        "gladia_code_switching", "gladia_audio_enhancer",
        "gladia_endpointing", "gladia_max_duration",
        "speechmatics_language", "speechmatics_enable_partials",
        "speechmatics_max_delay", "speechmatics_turn_detection",
        "enable_custom_vocabulary", "stt_deepgram_vocabulary",
        "stt_gladia_vocabulary", "stt_speechmatics_vocabulary",
        # Gemini Live STT — değişince servisi yeniden oluştur
        "gemini_stt_silence_duration_ms",
        "gemini_stt_end_sensitivity",
        "gemini_stt_start_sensitivity",
        "gemini_stt_prefix_padding_ms",
        "gemini_stt_system_instruction",
        "gemini_stt_context_compression",
        "gemini_stt_domain_vocabulary",
        "gemini_stt_punctuation_mode",
        # Gemini Live Translate — değişince servisi yeniden oluştur
        "gemini_live_translate_model",
        "gemini_live_translate_instruction",
    )
    for key_field in _RECREATE_FIELDS:
        if key_field in data:
            if "api_key" in key_field and "****" in str(data.get(key_field, "")):
                continue
            needs_recreate = True
            break

    if needs_recreate and _active_stt_proxy and "provider" not in data:
        from config import get_config
        cfg = get_config()
        session = _active_aiohttp_session
        if session:
            success = await _active_stt_proxy.recreate_current(cfg, session)
            if success:
                _active_stt = _active_stt_proxy.active_service
                # Recreate builds fresh instance — all fields applied
                applied = list(data.keys())
                return applied, []
            else:
                for field in _RECREATE_FIELDS:
                    if field in data:
                        skipped.append(field)

    # ── Live-updatable settings via STTUpdateSettingsFrame ────────────
    if not _active_control_processor:
        for field in data:
            if field not in applied and field not in skipped:
                skipped.append(field)
        return applied, skipped

    from pipecat.processors.frame_processor import FrameDirection

    # VAD settings can be updated live
    stt_live_fields = {
        "language": "language",
        "vad_silence_threshold": "vad_silence_threshold_secs",
        "vad_threshold": "vad_threshold",
        "min_speech_duration_ms": "min_speech_duration_ms",
        "min_silence_duration_ms": "min_silence_duration_ms",
    }

    settings_to_push = {}

    for field, frame_key in stt_live_fields.items():
        if field in data and field not in applied:
            value = data[field]
            if field in ("vad_silence_threshold", "vad_threshold"):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    continue
            elif field in ("min_speech_duration_ms", "min_silence_duration_ms"):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    continue
            settings_to_push[frame_key] = value
            applied.append(field)

    if settings_to_push:
        try:
            from pipecat.frames.frames import STTUpdateSettingsFrame
            await _active_control_processor.push_frame(
                STTUpdateSettingsFrame(settings=settings_to_push),
                FrameDirection.UPSTREAM,
            )
            logger.info(f"STT live update pushed (upstream): {list(settings_to_push.keys())}")
        except ImportError:
            logger.warning("STTUpdateSettingsFrame not available in this Pipecat version")
            skipped.extend(applied[-len(settings_to_push):])
            applied = applied[:-len(settings_to_push)]
        except Exception as e:
            logger.error(f"STTUpdateSettingsFrame push failed: {e}")

    _collect_remaining_as_skipped(data, applied, skipped)
    return applied, skipped


# ── LLM live updates ──────────────────────────────────────────────

async def _apply_llm(data: dict) -> tuple[list, list]:
    """Apply LLM changes — supports provider hot-swap via proxy."""
    applied, skipped = [], []

    # ── Provider swap (hot-swap via LLMServiceProxy) ──────────────────
    if "provider" in data and _active_llm_proxy:
        new_provider = data["provider"]
        if new_provider not in VALID_LLM_PROVIDERS:
            logger.warning(f"Invalid LLM provider rejected: {new_provider!r}")
            return [], list(data.keys())
        from config import get_config
        cfg = get_config()
        success = await _active_llm_proxy.switch_provider(new_provider, cfg)
        if success:
            applied = list(data.keys())
            global _active_llm
            _active_llm = _active_llm_proxy.active_service
            # Update translator's direct client with the NEW provider
            if _active_translator and hasattr(_active_translator, "_aclient"):
                from providers.llm_factory import create_async_client
                # Temporarily set provider so create_async_client uses correct endpoint
                old_prov = cfg.llm.provider
                cfg.llm.provider = new_provider
                try:
                    _active_translator._aclient = create_async_client(cfg)
                finally:
                    cfg.llm.provider = old_prov
            logger.info(f"LLM provider hot-swapped to: {new_provider}")
            return applied, []
        else:
            skipped.append("provider")

    # ── API key / model change → recreate current provider ────
    _RECREATE_FIELDS = (
        "api_key", "gemini_api_key", "groq_api_key", "model",
    )
    needs_recreate = False
    for key_field in _RECREATE_FIELDS:
        if key_field in data:
            val = str(data.get(key_field, ""))
            if "api_key" in key_field and "****" in val:
                continue  # masked — user didn't change it
            needs_recreate = True
            break

    if needs_recreate and _active_llm_proxy and "provider" not in data:
        from config import get_config
        cfg = get_config()
        success = await _active_llm_proxy.recreate_current(cfg)
        if success:
            _active_llm = _active_llm_proxy.active_service
            # Update translator's direct client too
            if _active_translator and hasattr(_active_translator, "_aclient"):
                from providers.llm_factory import create_async_client
                _active_translator._aclient = create_async_client(cfg)
            applied = list(data.keys())
            return applied, []
        else:
            for field in _RECREATE_FIELDS:
                if field in data:
                    skipped.append(field)

    # ── System prompt — update translator's context ────────────────
    if "system_prompt" in data and "system_prompt" not in applied and _active_translator:
        applied.append("system_prompt")
        logger.info("LLM system prompt updated (llm_prompt.txt saved)")

    for field in data:
        if field not in applied and field not in skipped and not field.startswith("_"):
            skipped.append(field)

    return applied, skipped


# ── Buffer live updates ───────────────────────────────────────────

def _apply_buffer(data: dict) -> tuple[list, list]:
    """Apply buffer config changes to translator's InputBuffer."""
    applied, skipped = [], []

    if not _active_translator:
        return [], list(data.keys())

    # Access the input buffer's config
    input_buffer = getattr(_active_translator, "_input_buffer", None)
    if not input_buffer:
        return [], list(data.keys())

    buf_config = getattr(input_buffer, "_config", None)
    if not buf_config:
        return [], list(data.keys())

    # Map admin panel fields to InputBufferConfig attributes
    field_map = {
        "flush_timeout_secs": ("flush_timeout_secs", float),
        "min_words_long": ("min_words_long", int),
        "min_words_with_punct": ("min_words_with_punct", int),
        "min_sentences": ("min_sentences", int),
        "min_words_timeout": ("min_words_timeout", int),
        "max_buffer_words": ("max_buffer_words", int),
    }

    for field, (attr, cast) in field_map.items():
        if field in data:
            try:
                value = cast(data[field])
                setattr(buf_config, attr, value)
                applied.append(field)
                logger.info(f"Buffer config live-updated: {attr} = {value}")
            except (ValueError, TypeError, AttributeError) as e:
                logger.error(f"Buffer config update failed for {field}: {e}")
                skipped.append(field)

    return applied, skipped


# ── General live updates ──────────────────────────────────────────

def _apply_general(data: dict) -> tuple[list, list]:
    """Apply general settings changes."""
    applied, skipped = [], []

    # Target latency — update translator config
    if "target_latency_ms" in data and _active_translator:
        try:
            cfg = getattr(_active_translator, "_config", None)
            if cfg:
                cfg.target_latency_ms = int(data["target_latency_ms"])
                applied.append("target_latency_ms")
        except Exception:
            skipped.append("target_latency_ms")

    # Log level — can be changed live
    if "log_level" in data:
        try:
            import logging as _logging
            level = getattr(_logging, data["log_level"].upper(), None)
            if level:
                _logging.getLogger().setLevel(level)
                applied.append("log_level")
        except Exception:
            skipped.append("log_level")

    # Source/target language changes need pipeline awareness
    for field in ("source_language", "target_language"):
        if field in data:
            skipped.append(field)  # Needs restart for now

    return applied, skipped
