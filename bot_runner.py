"""
Pipecat Bot Runner - Real-time simultaneous translation.

Entry point for the translation bot using Pipecat's development runner.
Supports both SmallWebRTC (local dev) and Daily (production) transports.

Usage:
  python bot_runner.py -t webrtc   # Local dev with SmallWebRTC
  python bot_runner.py -t daily    # Production with Daily.co

Then open browser:
  http://localhost:7860/client
"""

import asyncio
import logging
import os
from pathlib import Path
from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter
import aiohttp
from config import get_config
# Import routes context for global state management
import routes.context as routes_ctx
from routes.context import (
    add_active_connection, remove_active_connection,
    reset_active_connections,
    mark_connection_rejected, is_connection_rejected, clear_rejected_connection,
)
# Import logging utilities
from utils.logger import log_translation, log_stt_response
# Pipecat imports (after logger setup to reduce spam)
from pipecat.frames.frames import EndFrame, OutputAudioRawFrame
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.runner.types import RunnerArguments, SmallWebRTCRunnerArguments, DailyRunnerArguments
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.daily.transport import DailyTransport, DailyParams
from pipeline.builder import PipelineBuilder
from processors.control_processor import ControlProcessor
from providers.stt_factory import create_stt_service
from providers.tts_factory import create_tts_service
from providers.llm_factory import create_llm_service
from providers.stt_switcher import STTServiceProxy
from providers.tts_switcher import TTSServiceProxy
from providers.llm_switcher import LLMServiceProxy
from audio.timed_filter import TimedFilterWrapper

config = get_config()
logger = logging.getLogger(__name__)

# AIC Filter import (ai-coustics SDK) - optional advanced noise reduction
AIC_FILTER_AVAILABLE = False
try:
    # Use local fixed version instead of pipecat's aic_filter.
    # Pipecat's filter() holds a memoryview on _audio_buffer across an 'await',
    # which causes "Existing exports of data: object cannot be re-sized" when a
    # concurrent filter() call tries to extend the same bytearray.
    from aic_filter_source import AICFilter
    from processors.aic_debug_wrapper import AICDebugWrapper
    AIC_FILTER_AVAILABLE = True
except ImportError:
    pass

def _create_aic_filter(config):
    """Create AIC filter with optional debug wrapper."""
    if not AIC_FILTER_AVAILABLE:
        return None

    try:
        cache_dir = Path.home() / ".cache" / "pipecat" / "aic-models"
        model_id = config.audio.aic_model_id

        logger.info(f"Creating AIC Filter with model: {model_id}")
        aic_filter = AICFilter(
            license_key=config.audio.aic_license_key,
            model_id=model_id,
            model_download_dir=cache_dir,
        )

        # VAD pasifize edildi (Sadece gürültü temizleme yapacak, kelimeleri kesmeyecek)
        # aic_filter.create_vad_analyzer(
        #     speech_hold_duration=0.2,
        #     sensitivity=5.0
        # )

        # ALWAYS wrap with AICDebugWrapper for crash safety (bytearray→bytes coercion fix).
        # debug_enabled only controls WAV recording to disk; the wrapper is ALWAYS active.
        debug_enabled = os.getenv("DEBUG_AUDIO", "false").lower() == "true"
        aic_filter = AICDebugWrapper(
            aic_filter,
            debug_enabled=debug_enabled,
            gain_compensation=config.audio.aic_gain_compensation,
        )
        state = "with WAV recording" if debug_enabled else "without WAV recording"
        logger.info(f"AICDebugWrapper ACTIVE ({state})")

        return aic_filter
    except Exception as e:
        logger.error(f"Failed to create AIC Filter: {e}")
        return None


def _parse_cli_options(runner_args) -> dict:
    """Extract CLI options from runner arguments."""
    cli = getattr(runner_args, "cli_args", None)
    return {
        "mp3_url": getattr(cli, "mp3_url", None),
        "monitor_source": bool(getattr(cli, "monitor_source", False)),
    }


def _get_conn_id(connection) -> str:
    """Return a stable identifier for a WebRTC/Daily connection object."""
    return getattr(connection, 'pc_id', None) or getattr(connection, 'id', 'unknown')


def _audio_out_sample_rate(url_mode: bool, monitor_source: bool) -> int:
    """Return the correct output sample rate depending on streaming mode."""
    return (
        config.audio.sample_rate if (url_mode and monitor_source)
        else config.audio.output_sample_rate
    )


def _create_transport(runner_args, url_mode: bool, monitor_source: bool, audio_filter=None) -> SmallWebRTCTransport:
    """Create WebRTC transport with appropriate settings."""

    # Use provided audio filter or fall back to RNNoise
    if audio_filter is None:
        audio_filter = RNNoiseFilter()

    return SmallWebRTCTransport(
        params=TransportParams(
            audio_in_enabled=not url_mode,
            audio_in_stream_on_start=not url_mode,
            audio_in_sample_rate=config.audio.sample_rate,
            audio_in_channels=config.audio.channels,
            audio_in_filter=audio_filter,
            audio_out_enabled=True,
            # In monitor mode, use STT sample rate for direct playback
            audio_out_sample_rate=_audio_out_sample_rate(url_mode, monitor_source),
            audio_out_channels=config.audio.channels,
            video_in_enabled=False,
            video_out_enabled=False,
            camera_in_enabled=False,
            camera_out_enabled=False,
        ),
        webrtc_connection=runner_args.webrtc_connection,
    )


def _create_daily_transport(runner_args: DailyRunnerArguments, url_mode: bool, monitor_source: bool, audio_filter=None) -> DailyTransport:
    """Create Daily transport with appropriate settings."""

    # Use provided audio filter or fall back to RNNoise
    if audio_filter is None:
        audio_filter = RNNoiseFilter()

    return DailyTransport(
        room_url=runner_args.room_url,
        token=runner_args.token,
        bot_name="Translator Bot",
        params=DailyParams(
            api_key=os.getenv("DAILY_API_KEY", ""),
            audio_in_enabled=not url_mode,
            audio_in_sample_rate=config.audio.sample_rate,
            audio_in_channels=config.audio.channels,
            audio_in_filter=audio_filter,
            audio_out_enabled=True,
            audio_out_sample_rate=_audio_out_sample_rate(url_mode, monitor_source),
            audio_out_channels=config.audio.channels,
            video_in_enabled=False,
            video_out_enabled=False,
            camera_out_enabled=False,
            microphone_out_enabled=True,
        ),
    )


def _create_services(session: aiohttp.ClientSession) -> tuple:
    """Create STT, LLM, and TTS services using provider factories."""
    # STT via factory (supports elevenlabs, deepgram, gladia)
    stt = create_stt_service(config, session)

    # Register STT event handler for logging (if supported)
    try:
        @stt.event_handler("on_transcription")
        async def on_transcription(stt_service, text, is_final, words):
            log_stt_response(words=words, text=text, is_final=is_final)
    except Exception:
        logger.debug(f"STT provider {config.stt.provider} does not support on_transcription event")

    # LLM via factory (supports openai, gemini, groq)
    llm = create_llm_service(config)

    # TTS via factory (supports elevenlabs, deepgram)
    tts = create_tts_service(config)

    return stt, llm, tts


async def _stream_mp3_to_pipeline(
    mp3_url: str,
    task: PipelineTask,
    transport,
    session: aiohttp.ClientSession,
    monitor_source: bool,
    audio_filter=None
) -> None:
    """Stream MP3 audio to the pipeline with optional noise filtering."""
    from audio.mp3_reader import MP3Reader
    from pipecat.frames.frames import InputAudioRawFrame

    mp3_reader = MP3Reader(
        sample_rate=config.audio.sample_rate,
        chunk_duration_ms=config.audio.chunk_size_ms,
    )

    # Initialize audio filter for URL mode (transport doesn't start it since audio_in is disabled)
    if audio_filter:
        try:
            await audio_filter.start(config.audio.sample_rate)
            logger.info("Audio filter started for URL mode")
        except Exception as e:
            logger.error(f"Failed to start audio filter for URL mode: {e}")
            audio_filter = None

    try:
        async for audio_frame in mp3_reader.stream_frames_from_url(
            mp3_url, realtime=True, aiohttp_session=session
        ):
            # Apply noise filter to audio if available
            audio_data = audio_frame.audio

            if audio_filter:
                try:
                    filtered_audio = await audio_filter.filter(audio_data)
                    if filtered_audio:
                        audio_data = filtered_audio
                except Exception as e:
                    logger.error(f"Audio filter error: {e}")

            # In monitor mode, send original audio directly to client
            if monitor_source:
                out = OutputAudioRawFrame(
                    audio=audio_data,
                    sample_rate=audio_frame.sample_rate,
                    num_channels=audio_frame.num_channels,
                )
                if hasattr(audio_frame, "pts"):
                    try:
                        out.pts = audio_frame.pts
                    except Exception:
                        pass
                await transport.send_audio(out)

            # Create new frame with (possibly filtered) audio
            filtered_frame = InputAudioRawFrame(
                audio=audio_data,
                sample_rate=audio_frame.sample_rate,
                num_channels=audio_frame.num_channels,
            )
            filtered_frame._is_mp3_stream = True
            await task.queue_frame(filtered_frame)
    except (asyncio.CancelledError, BrokenPipeError, ConnectionResetError, RuntimeError, asyncio.TimeoutError, TimeoutError) as e:
        # BrokenPipeError/RuntimeError from ffmpeg when stream ends or is interrupted - normal
        if isinstance(e, RuntimeError) and "ffmpeg" not in str(e).lower():
            raise
        logger.debug(f"MP3 stream ended: {type(e).__name__}")
        return
    finally:
        # Stop audio filter
        if audio_filter:
            try:
                await audio_filter.stop()
                logger.info("Audio filter stopped for URL mode")
            except Exception:
                pass
        await task.queue_frame(EndFrame(reason="url_mp3_finished"))


def _create_audio_filter():
    """Create audio filter: AIC (if enabled + available) or RNNoise fallback."""
    if config.audio.aic_enabled:
        aic_filter = _create_aic_filter(config)
        audio_filter = aic_filter if aic_filter else RNNoiseFilter()
    else:
        audio_filter = RNNoiseFilter()
        logger.info("AIC filter disabled by config, using RNNoise")

    # Wrap audio filter with timing measurement
    return TimedFilterWrapper(audio_filter, sample_rate=config.audio.sample_rate)


async def _dispatch_control_message(control_processor, message: dict) -> None:
    """Dispatch a control message dict to the control processor and log the response."""
    msg_type = message.get("type", "")
    data = message.get("data", {})
    response = await control_processor.handle_client_message(msg_type, data)
    logger.debug(f"Control response: {response}")


async def _run_bot_pipeline(transport, url_mode: bool, monitor_source: bool, audio_filter, mp3_url=None):
    """Shared pipeline logic for both SmallWebRTC and Daily transports."""

    # Reset connection counter at pipeline start (handles crash/restart case)
    reset_active_connections()

    client_connected = asyncio.Event()
    routes_ctx.set_client_connected(client_connected)

    # Store transport reference for MP3 streaming API
    routes_ctx.set_transport(transport)

    # Create control processor
    control_processor = ControlProcessor()

    # Set global reference for API endpoint
    routes_ctx.set_control_processor(control_processor)

    @transport.event_handler("on_client_connected")
    async def _on_client_connected(_transport, connection):
        conn_id = _get_conn_id(connection)
        logger.info(f"Client connected: {conn_id}")

        # Enforce single active connection — reject if someone else is already connected
        count = add_active_connection(conn_id)
        if count > 1:
            logger.warning(f"Connection rejected: session busy ({count - 1} active). Ignoring {conn_id}")
            remove_active_connection(conn_id)
            mark_connection_rejected(conn_id)  # track so disconnect won't affect counter
            return

        client_connected.set()

        # Check for pending MP3 URL first — if set, skip microphone capture
        pending_url = routes_ctx.get_pending_mp3_url()

        # SmallWebRTC needs manual capture; skip if MP3 mode is active
        if not url_mode and not pending_url and hasattr(_transport, 'capture_participant_audio'):
            try:
                await _transport.capture_participant_audio()
            except Exception:
                pass

        if pending_url:
            logger.info(f"Client connected — starting pending MP3 stream (mic disabled): {pending_url}")
            # Cancel any existing mp3 stream task
            existing = routes_ctx.get_mp3_stream_task()
            if existing and not existing.done():
                existing.cancel()
            pipeline_task = routes_ctx.get_pipeline_task()
            session = routes_ctx.get_aiohttp_session()
            af = routes_ctx.get_audio_filter()
            if pipeline_task and session:
                mp3_task = asyncio.create_task(
                    _stream_mp3_to_pipeline(pending_url, pipeline_task, _transport, session, monitor_source, af)
                )
                routes_ctx.set_mp3_stream_task(mp3_task)


    @transport.event_handler("on_client_disconnected")
    async def _on_client_disconnected(_transport, connection):
        conn_id = _get_conn_id(connection)
        logger.warning(f"Client disconnected: {conn_id}")

        # If this was a rejected connection, don't touch the counter
        if is_connection_rejected(conn_id):
            clear_rejected_connection(conn_id)
            logger.debug(f"Rejected connection {conn_id} cleaned up — counter unchanged")
            return

        remove_active_connection(conn_id)
        # Stop any running MP3 stream on disconnect — but keep pending URL
        # so toggle stays ON in admin panel and MP3 auto-restarts on next Connect
        existing_mp3 = routes_ctx.get_mp3_stream_task()
        if existing_mp3 and not existing_mp3.done():
            existing_mp3.cancel()
            logger.info("MP3 stream paused on client disconnect (URL preserved for reconnect)")
        routes_ctx.set_mp3_stream_task(None)

        # Save debug audio files (if DEBUG_AUDIO is enabled)
        af = routes_ctx.get_audio_filter()
        if af:
            try:
                await af.stop()
                logger.info("Audio filter stopped on client disconnect")
            except Exception:
                pass

    # SmallWebRTC uses on_client_message; Daily uses on_app_message
    try:
        @transport.event_handler("on_client_message")
        async def _on_client_message(_transport, message):
            """Handle custom client control messages via data channel."""
            try:
                await _dispatch_control_message(control_processor, message)
            except Exception as e:
                logger.error(f"Error handling client message: {e}")
    except Exception:
        pass

    try:
        @transport.event_handler("on_app_message")
        async def _on_app_message(_transport, message, sender):
            """Handle custom client control messages via Daily app message."""
            try:
                if isinstance(message, dict):
                    await _dispatch_control_message(control_processor, message)
            except Exception as e:
                logger.error(f"Error handling app message: {e}")
    except Exception:
        pass

    async with aiohttp.ClientSession() as session:
        # Store session globally for live config provider hot-swap
        routes_ctx.set_aiohttp_session(session)

        # Create services
        stt, llm, tts = _create_services(session)

        # Wrap STT, LLM, and TTS in hot-swap proxies for admin panel provider switching
        stt_proxy = STTServiceProxy(stt, config.stt.provider)
        tts_proxy = TTSServiceProxy(tts, config.tts.provider)
        llm_proxy = LLMServiceProxy(llm, config.llm.provider)
        routes_ctx.set_stt_proxy(stt_proxy)
        routes_ctx.set_tts_proxy(tts_proxy)
        routes_ctx.set_llm_proxy(llm_proxy)

        # Build pipeline (proxies act as drop-in FrameProcessor replacements)
        components = PipelineBuilder.create_components(
            transport=transport,
            stt=stt_proxy,
            llm=llm_proxy,
            tts=tts_proxy,
            control_processor=control_processor,
            url_mode=url_mode,
            audio_filter=audio_filter,
            on_translation=lambda src, tgt, latency, **kwargs: log_translation(
                source_text=src,
                translated_text=tgt,
                latency_ms=latency,
                source_lang=config.source_language,
                target_lang=config.target_language,
                **kwargs
            ),
        )

        # Connect control processor to translator, TTS, and audio filter
        control_processor.set_translator(components.translator)
        control_processor.set_tts_service(tts)
        control_processor.set_audio_filter(audio_filter)

        # Register services for live hot-reload from admin panel
        from live_config import register_services
        register_services(
            stt=stt, tts=tts, llm=llm,
            translator=components.translator,
            control_processor=control_processor,
            stt_proxy=stt_proxy,
            tts_proxy=tts_proxy,
            llm_proxy=llm_proxy,
            aiohttp_session=session,
        )

        builder = PipelineBuilder(components, url_mode=url_mode, monitor_source=monitor_source)
        pipeline = builder.build()

        # Create and run task
        task = PipelineTask(
            pipeline,
            params=PipelineParams(allow_interruptions=True, enable_metrics=True),
        )
        routes_ctx.set_pipeline_task(task)
        runner = PipelineRunner()

        try:
            runner_task = asyncio.create_task(runner.run(task))

            if url_mode:
                await client_connected.wait()
                await _stream_mp3_to_pipeline(mp3_url, task, transport, session, monitor_source, audio_filter)

            await runner_task
        finally:
            try:
                await task.queue_frame(EndFrame())
            except Exception:
                pass
            # Ensure debug audio files are saved on pipeline shutdown
            if audio_filter:
                try:
                    await audio_filter.stop()
                except Exception:
                    pass


def _prepare_bot_options(runner_args) -> tuple:
    """Parse CLI options and return (mp3_url, url_mode, monitor_source, audio_filter).

    monitor_source is forced False when url_mode is False (mic mode cannot monitor source).
    The audio filter is also created and registered in routes_ctx here.
    """
    options = _parse_cli_options(runner_args)
    mp3_url = options["mp3_url"]
    url_mode = bool(mp3_url)
    monitor_source = options["monitor_source"] and url_mode
    audio_filter = _create_audio_filter()
    routes_ctx.set_audio_filter(audio_filter)
    return mp3_url, url_mode, monitor_source, audio_filter


async def run_webrtc_bot(runner_args: SmallWebRTCRunnerArguments):
    """Run the WebRTC translation bot (SmallWebRTC transport)."""
    mp3_url, url_mode, monitor_source, audio_filter = _prepare_bot_options(runner_args)
    transport = _create_transport(runner_args, url_mode, monitor_source, audio_filter)
    await _run_bot_pipeline(transport, url_mode, monitor_source, audio_filter, mp3_url)


async def run_daily_bot(runner_args: DailyRunnerArguments):
    """Run the translation bot with Daily transport."""
    mp3_url, url_mode, monitor_source, audio_filter = _prepare_bot_options(runner_args)
    transport = _create_daily_transport(runner_args, url_mode, monitor_source, audio_filter)
    await _run_bot_pipeline(transport, url_mode, monitor_source, audio_filter, mp3_url)


async def bot(runner_args: RunnerArguments):
    """Pipecat development runner entry point. Handles both SmallWebRTC and Daily."""
    if isinstance(runner_args, SmallWebRTCRunnerArguments):
        await run_webrtc_bot(runner_args)
        return
    if isinstance(runner_args, DailyRunnerArguments):
        await run_daily_bot(runner_args)
        return

if __name__ == "__main__":
    import argparse
    import contextlib
    import io
    import signal
    import sys

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    def signal_handler(_sig, _frame):
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    parser = argparse.ArgumentParser(description="Translator Bot Runner")

    # Runner args
    parser.add_argument("--host", type=str, default="localhost")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("-t", "--transport", type=str, choices=["webrtc", "daily"], default="daily")
    parser.add_argument("-f", "--folder", type=str, help="Path to downloads folder")
    parser.add_argument("--esp32", action="store_true", default=False)
    parser.add_argument("--whatsapp", action="store_true", default=False)
    parser.add_argument("--dialin", action="store_true", default=False)

    # Translation options
    parser.add_argument(
        "--mp3-url",
        help="Stream and translate MP3 from URL when client connects",
    )
    parser.add_argument(
        "--monitor-source",
        action="store_true",
        help="(URL mode only) Play original audio to client speaker",
    )

    args = parser.parse_args()

    print(f"transport: {args.transport}")

    app = FastAPI()

    allow_origins_str = os.getenv("CORS_ORIGINS", "*")
    if allow_origins_str == "*":
        allow_origins = ["*"]
    else:
        allow_origins = [origin.strip() for origin in allow_origins_str.split(",") if origin.strip()]

    # CORS spec: allow_credentials=True, allow_origins=["*"] birlikte kullanılamaz.
    # Wildcard origins'de credentials devre dışı bırakılmalı.
    allow_credentials = allow_origins != ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ============================
    # Auth middleware - protect page routes
    # ============================
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import RedirectResponse as StarletteRedirect
    from auth import verify_token

    PROTECTED_PATHS = {"/client", "/client-controls", "/admin"}

    class AuthPageMiddleware(BaseHTTPMiddleware):
        """Redirect unauthenticated users to /login for protected page routes."""
        async def dispatch(self, request, call_next):
            path = request.url.path.rstrip("/")
            if path in PROTECTED_PATHS:
                token = request.cookies.get("access_token", "")
                if not token or not verify_token(token):
                    return StarletteRedirect(url="/login")
            return await call_next(request)

    app.add_middleware(AuthPageMiddleware)

    # Setup transport-specific routes
    with contextlib.redirect_stdout(io.StringIO()):
        if args.transport == "webrtc":
            from pipecat.runner.run import _setup_webrtc_routes
            _setup_webrtc_routes(app, args)
        elif args.transport == "daily":
            from pipecat.runner.run import _setup_daily_routes
            _setup_daily_routes(app, args)

            # Remove the auto-generated GET "/" route from _setup_daily_routes
            # (it redirects to Daily room URL, but we want "/" -> "/login")
            app.routes[:] = [r for r in app.routes if not (hasattr(r, 'path') and r.path == '/' and hasattr(r, 'methods') and 'GET' in r.methods)]

            # Mount daily-client UI at /client (used by client-controls iframe)
            daily_client_dist = os.path.join(os.path.dirname(__file__), "daily-client", "dist")
            if os.path.exists(daily_client_dist):
                from fastapi.staticfiles import StaticFiles as DailyStaticFiles
                app.mount("/client", DailyStaticFiles(directory=daily_client_dist, html=True), name="daily-client")


    # Serve static files
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        from fastapi.staticfiles import StaticFiles
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # ============================
    # Setup all routes
    # ============================
    from routes import setup_routes
    setup_routes(app, static_dir)

    print(f"login:    http://{args.host}:{args.port}/login")
    print(f"admin:    http://{args.host}:{args.port}/admin")
    print(f"controls: http://{args.host}:{args.port}/client-controls (kontrol panelli)")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
