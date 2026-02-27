"""
STT Service Proxy — Hot-swap STT providers at runtime without restart.

Properly initializes inner services using Pipecat's full lifecycle:
  1. setup(clock, task_manager)  →  creates input task
  2. process_frame(StartFrame)   →  sets __started, creates process task
  3. _next/_prev links           →  routes output through proxy
"""

import logging

import aiohttp

from providers.base_proxy import BaseServiceProxy
from providers.stt_factory import create_stt_service

logger = logging.getLogger(__name__)


class STTServiceProxy(BaseServiceProxy):
    """Proxy that delegates to the active STT service and supports hot-swap."""

    _service_type = "STT"

    async def switch_provider(
        self,
        provider_name: str,
        config,
        session: aiohttp.ClientSession,
    ) -> bool:
        """Switch to a different STT provider at runtime with rollback on failure."""
        async with self._lock:
            if provider_name == self._active_provider:
                logger.debug(f"STT already using {provider_name}, skip")
                return True

            self._switching = True
            try:
                logger.info(f"STT hot-swap: {self._active_provider} → {provider_name}")
                original = config.stt.provider
                config.stt.provider = provider_name
                try:
                    new_stt = create_stt_service(config, session)
                finally:
                    config.stt.provider = original

                if await self._swap_inner(new_stt, provider_name):
                    logger.info(f"STT hot-swap to {provider_name} complete")
                    return True
                return False
            except Exception as e:
                logger.error(f"STT hot-swap to {provider_name} failed: {e}")
                return False
            finally:
                self._switching = False

    async def recreate_current(
        self,
        config,
        session: aiohttp.ClientSession,
    ) -> bool:
        """Recreate current STT provider with updated settings, with rollback on failure."""
        async with self._lock:
            provider = self._active_provider
            self._switching = True
            try:
                logger.info(f"STT recreate: {provider}")
                new_stt = create_stt_service(config, session)
                if await self._swap_inner(new_stt, provider):
                    logger.info(f"STT recreate {provider} complete")
                    return True
                logger.error("STT recreate init failed, rolling back")
                return False
            except Exception as e:
                logger.error(f"STT recreate {provider} failed: {e}")
                return False
            finally:
                self._switching = False
