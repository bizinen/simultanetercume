"""
LLM Service Proxy — Hot-swap LLM providers at runtime without restart.

Mirrors the STTServiceProxy/TTSServiceProxy pattern already used in the project.
Delegates to the active LLM service and supports hot-swap via switch_provider().
"""

import logging

from providers.base_proxy import BaseServiceProxy
from providers.llm_factory import create_llm_service

logger = logging.getLogger(__name__)


class LLMServiceProxy(BaseServiceProxy):
    """Proxy that delegates to the active LLM service and supports hot-swap."""

    _service_type = "LLM"

    async def switch_provider(self, provider_name: str, config) -> bool:
        """Switch to a different LLM provider at runtime with rollback on failure."""
        async with self._lock:
            if provider_name == self._active_provider:
                logger.debug(f"LLM already using {provider_name}, skip")
                return True

            self._switching = True
            try:
                logger.info(f"LLM hot-swap: {self._active_provider} → {provider_name}")
                original = config.llm.provider
                config.llm.provider = provider_name
                try:
                    new_llm = create_llm_service(config)
                finally:
                    config.llm.provider = original

                if await self._swap_inner(new_llm, provider_name):
                    logger.info(f"LLM hot-swap to {provider_name} complete")
                    return True
                return False
            except Exception as e:
                logger.error(f"LLM hot-swap to {provider_name} failed: {e}")
                return False
            finally:
                self._switching = False

    async def recreate_current(self, config) -> bool:
        """Recreate current LLM provider with updated settings."""
        async with self._lock:
            provider = self._active_provider
            self._switching = True
            try:
                logger.info(f"LLM recreate: {provider}")
                new_llm = create_llm_service(config)
                if await self._swap_inner(new_llm, provider):
                    logger.info(f"LLM recreate {provider} complete")
                    return True
                logger.error("LLM recreate init failed, rolling back")
                return False
            except Exception as e:
                logger.error(f"LLM recreate {provider} failed: {e}")
                return False
            finally:
                self._switching = False
