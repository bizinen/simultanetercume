"""
TTS Service Proxy — Hot-swap TTS providers at runtime without restart.

Properly initializes inner services using Pipecat's full lifecycle:
  1. setup(clock, task_manager)  →  creates input task
  2. process_frame(StartFrame)   →  sets __started, creates process task
  3. _next/_prev links           →  routes output through proxy
"""

import logging

from providers.base_proxy import BaseServiceProxy
from providers.tts_factory import create_tts_service

logger = logging.getLogger(__name__)


class TTSServiceProxy(BaseServiceProxy):
    """Proxy that delegates to the active TTS service and supports hot-swap."""

    _service_type = "TTS"

    async def switch_provider(self, provider_name: str, config) -> bool:
        """Switch to a different TTS provider at runtime with rollback on failure."""
        async with self._lock:
            if provider_name == self._active_provider:
                logger.debug(f"TTS already using {provider_name}, skip")
                return True

            self._switching = True
            try:
                logger.info(f"TTS hot-swap: {self._active_provider} → {provider_name}")
                original = config.tts.provider
                config.tts.provider = provider_name
                try:
                    new_tts = create_tts_service(config)
                finally:
                    config.tts.provider = original

                if await self._swap_inner(new_tts, provider_name):
                    logger.info(f"TTS hot-swap to {provider_name} complete")
                    return True
                return False
            except Exception as e:
                logger.error(f"TTS hot-swap to {provider_name} failed: {e}")
                return False
            finally:
                self._switching = False

    async def recreate_current(self, config) -> bool:
        """Recreate current TTS provider with updated settings, with rollback on failure."""
        async with self._lock:
            provider = self._active_provider
            self._switching = True
            try:
                logger.info(f"TTS recreate: {provider}")
                new_tts = create_tts_service(config)
                if await self._swap_inner(new_tts, provider):
                    logger.info(f"TTS recreate {provider} complete")
                    return True
                logger.error("TTS recreate init failed, rolling back")
                return False
            except Exception as e:
                logger.error(f"TTS recreate {provider} failed: {e}")
                return False
            finally:
                self._switching = False
