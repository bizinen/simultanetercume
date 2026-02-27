"""
API routes - configuration and control endpoints.
"""

import asyncio
import io
import json
import logging
import os
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse

from auth import get_current_user
from config_manager import get_all_config, update_config_section
from routes.context import (
    get_control_processor, get_mp3_stream_task, set_mp3_stream_task,
    set_pending_mp3_url, get_pending_mp3_url,
    get_active_connection_count,
)

logger = logging.getLogger(__name__)


async def _cancel_mp3_task() -> None:
    """Cancel and await the current MP3 stream task, if running."""
    existing = get_mp3_stream_task()
    if existing and not existing.done():
        existing.cancel()
        try:
            await existing
        except (asyncio.CancelledError, Exception):
            pass
        set_mp3_stream_task(None)


# Simple per-user rate limiter for config updates (max 10 per minute)
_config_rate: dict = {}  # { user: [timestamp, ...] }
_CONFIG_RATE_LIMIT = 10
_CONFIG_RATE_WINDOW = 60  # seconds


def setup_api_routes(app):
    """Register API routes with the FastAPI app."""

    @app.get("/api/config")
    async def get_config_api(user: str = Depends(get_current_user)):
        """Get all config (masked API keys)."""
        return get_all_config()

    @app.post("/api/system/reset")
    async def reset_config_api(user: str = Depends(get_current_user)):
        """Reset configuration to factory defaults (except API keys)."""
        logger.info(f"User '{user}' triggering factory reset for settings")
        try:
            from config_manager import reset_to_defaults
            result = reset_to_defaults()
            return {"status": "ok", "message": "Ayarlar varsayilan degerlere donduruldu. Lutfen sayfayi yenileyip sunucuyu baslatin.", "details": result}
        except Exception as e:
            logger.error(f"Reset failed: {e}", exc_info=True)
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail=str(e))

    @app.put("/api/config/{section}")
    async def update_config_api(section: str, request: Request, user: str = Depends(get_current_user)):
        """Update a config section with live hot-reload."""
        import time as _time
        now = _time.monotonic()
        hits = _config_rate.setdefault(user, [])
        hits[:] = [t for t in hits if now - t < _CONFIG_RATE_WINDOW]
        if len(hits) >= _CONFIG_RATE_LIMIT:
            return {"status": "error", "message": "Too many config updates. Try again later."}
        hits.append(now)

        valid_sections = {"stt", "tts", "llm", "audio", "general", "buffer", "verifier"}
        if section not in valid_sections:
            return {"status": "error", "message": f"Invalid section: {section}"}
        try:
            data = await request.json()
            # 1. Persist to .env
            result = update_config_section(section, data)

            # 2. Apply live to running pipeline (no restart needed)
            from live_config import apply_live_config
            live_result = await apply_live_config(section, data)
            result["live_applied"] = live_result.get("live_applied", [])
            result["live_skipped"] = live_result.get("live_skipped", [])

            # Only require restart if there are skipped fields
            result["restart_required"] = len(live_result.get("live_skipped", [])) > 0

            return result
        except Exception as e:
            logger.error(f"Config update error: {e}", exc_info=True)
            return {"status": "error", "message": "Internal Server Error"}

    @app.post("/api/control")
    async def control_api(request: Request, user: str = Depends(get_current_user)):
        """Handle control messages from the web UI."""
        try:
            body = await request.body()
            data = json.loads(body)
            msg_type = data.get("type", "")
            msg_data = data.get("data", {})
            logger.info(f"Control API: {msg_type} (user={user})")

            control_processor = get_control_processor()
            if control_processor:
                response = await control_processor.handle_client_message(msg_type, msg_data)
                return response
            else:
                return {"status": "ok", "type": msg_type, "translator_connected": False}
        except Exception as e:
            logger.error(f"Control API error: {e}", exc_info=True)
            return {"status": "error", "message": "Internal Server Error"}

    @app.post("/api/mp3-stream/start")
    async def start_mp3_stream(request: Request, user: str = Depends(get_current_user)):
        """Queue an MP3 URL for streaming. Streaming starts when a client connects."""
        try:
            data = await request.json()
            mp3_url = data.get("url", "").strip()
            if not mp3_url:
                return {"status": "error", "message": "URL is required"}

            # SSRF koruması: sadece http/https URL'lerine izin ver
            parsed = urlparse(mp3_url)
            if parsed.scheme not in ("http", "https"):
                return {"status": "error", "message": "Only HTTP(S) URLs are allowed"}

            # Stop existing stream if running
            await _cancel_mp3_task()

            # Store the URL — bot_runner will pick it up when client connects
            set_pending_mp3_url(mp3_url)
            logger.info(f"MP3 stream URL queued: {mp3_url}")
            return {"status": "ok", "message": "MP3 streaming will start when client connects", "url": mp3_url}
        except Exception as e:
            logger.error(f"MP3 stream start error: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    @app.post("/api/mp3-stream/stop")
    async def stop_mp3_stream(user: str = Depends(get_current_user)):
        """Stop the current MP3 stream and clear pending URL."""
        try:
            set_pending_mp3_url(None)
            had_task = (existing := get_mp3_stream_task()) is not None and not existing.done()
            await _cancel_mp3_task()
            if had_task:
                logger.info("MP3 stream stopped")
                return {"status": "ok", "message": "MP3 streaming stopped"}
            return {"status": "ok", "message": "No stream running"}
        except Exception as e:
            logger.error(f"MP3 stream stop error: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    @app.get("/api/mp3-stream/status")
    async def mp3_stream_status(user: str = Depends(get_current_user)):
        """Get MP3 stream status."""
        existing = get_mp3_stream_task()
        is_streaming = existing is not None and not existing.done()
        pending_url = get_pending_mp3_url()
        return {
            "status": "ok",
            "streaming": is_streaming,
            "pending": pending_url is not None and not is_streaming,
            "url": pending_url,
        }

    @app.get("/api/session/status")
    async def session_status(user: str = Depends(get_current_user)):
        """Get active connection count — used by admin panel to show test indicator."""
        count = get_active_connection_count()
        return {
            "status": "ok",
            "active_connections": count,
            "session_busy": count > 0,
        }

    # ============================
    # Debug / Download endpoints
    # ============================

    _BASE_DIR = Path(__file__).parent.parent
    _RESULTS_DIR = _BASE_DIR / "results"
    _DEBUG_AUDIO_DIR = _BASE_DIR / "debug_audio"

    @app.get("/api/debug/status")
    async def debug_status(user: str = Depends(get_current_user)):
        """Return whether DEBUG_AUDIO is enabled and list available files."""
        debug_audio = os.getenv("DEBUG_AUDIO", "false").lower() == "true"

        # List JSONL files in results/
        jsonl_files = []
        if _RESULTS_DIR.exists():
            for f in sorted(_RESULTS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
                jsonl_files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                })

        # List audio files in debug_audio/ (only if DEBUG_AUDIO is on)
        audio_files = []
        if debug_audio and _DEBUG_AUDIO_DIR.exists():
            for f in sorted(_DEBUG_AUDIO_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True):
                audio_files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                })

        return {
            "status": "ok",
            "debug_audio": debug_audio,
            "jsonl_files": jsonl_files,
            "audio_files": audio_files,
        }

    @app.get("/api/download/jsonl")
    async def download_jsonl_zip(user: str = Depends(get_current_user)):
        """Download the most recent JSONL file from results/."""
        if not _RESULTS_DIR.exists():
            return {"status": "error", "message": "No results directory"}

        files = sorted(_RESULTS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return {"status": "error", "message": "No JSONL files found"}

        latest = files[0]
        return StreamingResponse(
            open(latest, "rb"),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={latest.name}"},
        )

    @app.get("/api/download/audio")
    async def download_audio_zip(user: str = Depends(get_current_user)):
        """Download the latest original + filtered WAV pair from debug_audio/. Requires DEBUG_AUDIO=true."""
        debug_audio = os.getenv("DEBUG_AUDIO", "false").lower() == "true"
        if not debug_audio:
            return {"status": "error", "message": "DEBUG_AUDIO is not enabled"}

        if not _DEBUG_AUDIO_DIR.exists():
            return {"status": "error", "message": "No debug_audio directory"}

        # Find the most recent original_*.wav to determine the session timestamp
        originals = sorted(
            _DEBUG_AUDIO_DIR.glob("original_*.wav"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not originals:
            return {"status": "error", "message": "No audio files found"}

        # Extract timestamp from the latest original file (original_YYYYMMDD_HHMMSS.wav)
        latest_name = originals[0].stem  # "original_20260212_015006"
        ts = latest_name.replace("original_", "", 1)  # "20260212_015006"

        # Collect the original + filtered pair for this session
        session_files = [
            f for f in _DEBUG_AUDIO_DIR.glob(f"*_{ts}.wav")
            if f.name.startswith(("original_", "filtered_"))
        ]
        if not session_files:
            return {"status": "error", "message": "No audio files found"}

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in session_files:
                zf.write(f, f.name)
        buf.seek(0)

        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=audio_log_{ts}.zip"},
        )
