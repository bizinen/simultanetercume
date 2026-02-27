"""
Base Service Proxy — Common hot-swap logic for STT/TTS/LLM proxies.

Handles Pipecat lifecycle delegation, inner service linking, and the
common swap/rollback pattern. Concrete subclasses implement factory calls
in switch_provider() and recreate_current().
"""

import asyncio
import logging
from typing import Optional

from pipecat.frames.frames import (
    Frame,
    StartFrame,
    EndFrame,
    CancelFrame,
    StartInterruptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

_SYSTEM_FRAMES = (StartFrame, EndFrame, CancelFrame, StartInterruptionFrame)


class BaseServiceProxy(FrameProcessor):
    """Base proxy for hot-swappable pipeline services (STT/TTS/LLM).

    Handles Pipecat lifecycle delegation, inner service linking, and the
    common swap/rollback pattern. Subclasses implement factory calls in
    switch_provider() and recreate_current().
    """

    _service_type: str = "Service"

    def __init__(self, initial_service: FrameProcessor, initial_provider: str, **kwargs):
        super().__init__(**kwargs)
        self._inner: FrameProcessor = initial_service
        self._active_provider: str = initial_provider
        self._lock = asyncio.Lock()
        self._switching: bool = False
        self._last_start_frame: Optional[StartFrame] = None
        logger.info(f"{self._service_type}ServiceProxy initialized with provider: {initial_provider}")

    @property
    def active_provider(self) -> str:
        return self._active_provider

    @property
    def active_service(self) -> FrameProcessor:
        return self._inner

    def _link_inner(self):
        """Link inner service into the proxy's pipeline position."""
        self._inner._next = self._next
        self._inner._prev = self._prev

    async def _init_inner(self) -> bool:
        """Fully initialize inner service using Pipecat lifecycle (setup + StartFrame)."""
        if not self._last_start_frame:
            logger.warning("No StartFrame stored, cannot init inner")
            return False

        try:
            from pipecat.processors.frame_processor import FrameProcessorSetup
            await self._inner.setup(FrameProcessorSetup(
                clock=self._clock,
                task_manager=self._task_manager,
                observer=getattr(self, '_observer', None),
            ))
        except Exception as e:
            logger.error(f"{self._service_type} inner setup() failed: {e}")
            return False

        try:
            await self._inner.process_frame(self._last_start_frame, FrameDirection.DOWNSTREAM)
        except Exception as e:
            logger.error(f"{self._service_type} inner StartFrame processing failed: {e}")
            return False

        return True

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Delegate frames to inner service; handle lifecycle frames via super()."""
        if isinstance(frame, StartFrame):
            self._last_start_frame = frame
            await super().process_frame(frame, direction)
            self._link_inner()
            await self._init_inner()
            return

        if isinstance(frame, _SYSTEM_FRAMES):
            await super().process_frame(frame, direction)
            try:
                await self._inner.process_frame(frame, direction)
            except Exception as e:
                logger.debug(f"{self._service_type} inner system frame error (non-fatal): {e}")
            return

        if self._switching:
            logger.debug(f"{self._service_type} switching in progress, dropping data frame")
            return

        try:
            await self._inner.process_frame(frame, direction)
        except Exception as e:
            logger.error(f"{self._service_type} inner process_frame error: {e}")
            await self.push_frame(frame, direction)

    async def _swap_inner(self, new_service: FrameProcessor, new_provider: str) -> bool:
        """Replace inner service with rollback on failure.

        Assumes the caller holds self._lock and has set self._switching = True.
        On success, updates self._active_provider to new_provider.
        On failure, restores the original inner service and returns False.
        """
        old_inner = self._inner
        old_provider = self._active_provider

        self._inner = new_service
        self._link_inner()
        success = await self._init_inner()

        if not success:
            logger.error(f"{self._service_type} init failed, rolling back to {old_provider}")
            self._inner = old_inner
            self._link_inner()
            return False

        # Cancel old service safely
        try:
            old_inner._next = None
            old_inner._prev = None
            await old_inner.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM)
        except Exception:
            pass

        self._active_provider = new_provider
        return True
