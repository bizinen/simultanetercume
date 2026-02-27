"""
Routes context module - provides access to global state for route handlers.

This module acts as a bridge between bot_runner.py's global state and the route handlers,
avoiding circular imports and keeping routes testable.
"""

import asyncio
from types import SimpleNamespace
from typing import Optional

# All mutable global state in one namespace — eliminates `global` declarations in setters
_s = SimpleNamespace(
    control_processor=None,
    audio_filter=None,
    stt_proxy=None,
    tts_proxy=None,
    llm_proxy=None,
    aiohttp_session=None,
    pipeline_task=None,
    mp3_stream_task=None,
    transport=None,
    client_connected=None,
    pending_mp3_url=None,
    active_connections=set(),
    rejected_connections=set(),
)


def set_control_processor(v): _s.control_processor = v
def get_control_processor(): return _s.control_processor

def set_audio_filter(v): _s.audio_filter = v
def get_audio_filter(): return _s.audio_filter

def set_stt_proxy(v): _s.stt_proxy = v
def get_stt_proxy(): return _s.stt_proxy

def set_tts_proxy(v): _s.tts_proxy = v
def get_tts_proxy(): return _s.tts_proxy

def set_llm_proxy(v): _s.llm_proxy = v
def get_llm_proxy(): return _s.llm_proxy

def set_aiohttp_session(v): _s.aiohttp_session = v
def get_aiohttp_session(): return _s.aiohttp_session

def set_pipeline_task(v): _s.pipeline_task = v
def get_pipeline_task(): return _s.pipeline_task

def set_mp3_stream_task(v): _s.mp3_stream_task = v
def get_mp3_stream_task(): return _s.mp3_stream_task

def set_transport(v): _s.transport = v
def get_transport(): return _s.transport

def set_client_connected(event: asyncio.Event): _s.client_connected = event
def get_client_connected() -> Optional[asyncio.Event]: return _s.client_connected

def set_pending_mp3_url(url: Optional[str]): _s.pending_mp3_url = url
def get_pending_mp3_url() -> Optional[str]: return _s.pending_mp3_url


# ── Connection tracking ────────────────────────────────────────────────────

def get_active_connection_count() -> int:
    """Get the number of currently active WebRTC connections."""
    return len(_s.active_connections)


def add_active_connection(conn_id: str) -> int:
    """Add an active connection. Returns new count."""
    _s.active_connections.add(conn_id)
    return len(_s.active_connections)


def remove_active_connection(conn_id: str) -> int:
    """Remove an active connection. Returns new count (min 0)."""
    _s.active_connections.discard(conn_id)
    return len(_s.active_connections)


def reset_active_connections() -> None:
    """Reset connections (e.g. on pipeline restart)."""
    _s.active_connections.clear()
    _s.rejected_connections.clear()


def mark_connection_rejected(conn_id: str) -> None:
    """Mark a connection ID as rejected so disconnect won't decrement counter."""
    _s.rejected_connections.add(conn_id)


def is_connection_rejected(conn_id: str) -> bool:
    """Check if a connection was rejected."""
    return conn_id in _s.rejected_connections


def clear_rejected_connection(conn_id: str) -> None:
    """Remove a connection ID from the rejected set."""
    _s.rejected_connections.discard(conn_id)
