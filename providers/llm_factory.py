"""
LLM Provider Factory - Creates the appropriate LLM service based on config.

Supported providers:
- openai: OpenAILLMService (default) — including fine-tuned models (ft:...)
- gemini: GoogleLLMService — Google Gemini 2.5 Flash, Pro, etc.
- groq: GroqLLMService — Llama, Mixtral, Gemma (ultra-fast LPU)

Note: gemini_live is now an STT provider. Use STT_PROVIDER=gemini_live for
real-time audio transcription via Gemini Live WebSocket API.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def create_llm_service(config) -> Any:
    """Create LLM service based on config.llm.provider.

    Returns a Pipecat FrameProcessor-compatible LLM service.
    """
    provider = getattr(config.llm, "provider", "openai")
    logger.info(f"Creating LLM service: provider={provider}")

    if provider == "openai":
        return _create_openai_llm(config)
    elif provider == "gemini":
        return _create_gemini_llm(config)
    elif provider == "groq":
        return _create_groq_llm(config)
    else:
        logger.warning(f"Unknown LLM provider: {provider!r}, falling back to OpenAI")
        return _create_openai_llm(config)


def _create_openai_llm(config):
    """Create OpenAI LLM service (supports standard and fine-tuned models)."""
    from pipecat.services.openai.llm import OpenAILLMService

    api_key = getattr(config.llm, "api_key", "") or ""
    model = getattr(config.llm, "model", "gpt-4o-mini")

    if not api_key:
        raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY in .env or admin panel.")

    llm = OpenAILLMService(
        api_key=api_key,
        model=model,
    )
    logger.info(f"OpenAI LLM created: model={model}")
    return llm


def _create_gemini_llm(config):
    """Create Google Gemini LLM service."""
    from pipecat.services.google import GoogleLLMService

    api_key = getattr(config.llm, "gemini_api_key", "") or ""
    model = getattr(config.llm, "model", "gemini-2.5-flash")
    system_prompt = getattr(config.llm, "system_prompt", None)

    if not api_key:
        raise ValueError("Google API key is required. Set GOOGLE_API_KEY in .env or admin panel.")

    kwargs = {
        "api_key": api_key,
        "model": model,
    }
    # Gemini uses system_instruction instead of system_prompt in the LLM context
    if system_prompt:
        kwargs["system_instruction"] = system_prompt

    llm = GoogleLLMService(**kwargs)
    logger.info(f"Google Gemini LLM created: model={model}")
    return llm


def _create_groq_llm(config):
    """Create Groq LLM service (native Pipecat GroqLLMService).

    Groq provides ultra-fast inference via LPU hardware.
    Supports Llama, Mixtral, Gemma, DeepSeek and fine-tuned LoRA models (Enterprise).
    Fine-tuned models use the same model ID format as returned by Groq console.
    """
    from pipecat.services.groq.llm import GroqLLMService

    api_key = getattr(config.llm, "groq_api_key", "") or ""
    model = getattr(config.llm, "model", "llama-3.3-70b-versatile")

    if not api_key:
        raise ValueError("Groq API key is required. Set GROQ_API_KEY in .env or admin panel.")

    llm = GroqLLMService(
        api_key=api_key,
        model=model,
    )
    logger.info(f"Groq LLM created: model={model}")
    return llm


# Provider → (config_key_attr, base_url, error_message)
_ASYNC_CLIENT_CONFIG = {
    "openai": ("api_key",        None,                                                          "OPENAI_API_KEY not set"),
    "gemini": ("gemini_api_key", "https://generativelanguage.googleapis.com/v1beta/openai/",   "GOOGLE_API_KEY not set"),
    "groq":   ("groq_api_key",   "https://api.groq.com/openai/v1",                             "GROQ_API_KEY not set"),
}


def create_async_client(config):
    """Create a provider-specific async OpenAI-compatible client for the translator.

    All supported providers (openai, gemini, groq) expose an OpenAI-compatible
    streaming interface so the translator can use the same code path for all.
    """
    import openai
    provider = getattr(config.llm, "provider", "openai")

    if provider in _ASYNC_CLIENT_CONFIG:
        key_attr, base_url, err_msg = _ASYNC_CLIENT_CONFIG[provider]
        api_key = getattr(config.llm, key_attr, "") or ""
        if not api_key:
            raise ValueError(err_msg)
    else:
        # Unknown provider — fall back to OpenAI
        logger.warning(f"Unknown LLM provider {provider!r}, falling back to OpenAI client")
        api_key = getattr(config.llm, "api_key", "") or ""
        base_url = None

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return openai.AsyncOpenAI(**kwargs)

