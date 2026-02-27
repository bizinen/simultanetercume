import asyncio
import logging
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Awaitable, Dict, Any

import regex

_non_latin_re = regex.compile(r'[^\p{Latin}\p{Punctuation}\p{N}\s]')


def _normalize_llm_output(text: str) -> str:
    """Remove parenthesized notes and non-Latin characters from LLM output."""
    text = re.sub(r'\s*\([^)]*\)', '', text).strip()
    return _non_latin_re.sub('', text).strip()

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    StartInterruptionFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from config import get_config

logger = logging.getLogger(__name__)


# ============================================================================
# Turkish Abbreviations & Sentence Detection
# ============================================================================

# Known Turkish abbreviations that end with '.' but are NOT sentence boundaries
TURKISH_ABBREVS = {
    # Titles
    'hz', 'prof', 'dr', 'doç', 'yrd', 'av', 'mhd', 'müh', 'arş', 'gör',
    'öğr', 'uzm',
    # Military ranks
    'yb', 'bnb', 'alb', 'gen', 'yzb', 'astsb', 'çvş', 'onb', 'er',
    # Common abbreviations
    'vb', 'vs', 'bkz', 'çev', 'ed', 'yy', 'no', 'tel', 'faks',
    # Address abbreviations
    'apt', 'mah', 'sok', 'cad', 'bul', 'sk', 'cd', 'bl', 'st', 'nr',
}

_PUNCT_RE = re.compile(r'[.!?]')


def _is_sentence_boundary(text: str, pos: int) -> bool:
    """Check if position is a real sentence boundary (not abbreviation/number)."""
    ch = text[pos]
    if ch == '.':
        # Skip digit+dot (verse/ordinal numbers like "255.", "10.")
        if pos > 0 and text[pos - 1].isdigit():
            return False
        # Skip known abbreviations
        before = text[:pos].rstrip()
        last_word = before.split()[-1].lower().rstrip('.') if before.split() else ""
        if last_word in TURKISH_ABBREVS:
            return False
    # Check it's followed by space or end (with optional closing quotes)
    after = text[pos + 1:]
    after_stripped = after.lstrip('"\u201d\u00BB)')
    return not after_stripped or after_stripped[0].isspace()


def find_last_sentence_end(text: str) -> int:
    """Find the position after the last real sentence-ending punctuation.

    Returns -1 if no sentence boundary found.
    Skips abbreviations (Hz., Dr., Prof., etc.) and numbers (10., 255.).
    """
    last_pos = -1
    for m in _PUNCT_RE.finditer(text):
        pos = m.start()
        if _is_sentence_boundary(text, pos):
            after = text[pos + 1:]
            after_stripped = after.lstrip('"\u201d\u00BB)')
            last_pos = pos + 1 + (len(after) - len(after_stripped))
    return last_pos


def count_sentences(text: str) -> int:
    """Count the number of complete sentences in text."""
    count = 0
    for m in _PUNCT_RE.finditer(text):
        if _is_sentence_boundary(text, m.start()):
            count += 1
    return count


def ends_with_sentence(text: str) -> bool:
    """Check if text ends with sentence-ending punctuation."""
    text = text.rstrip()
    if not text:
        return False
    # Check last char (possibly after closing quote)
    last_char = text[-1]
    if last_char in '.!?':
        pos = len(text) - 1
        return _is_sentence_boundary(text, pos)
    # Check if ends with quote after punctuation
    if last_char in '"\u201d\u00BB)':
        for i in range(len(text) - 2, -1, -1):
            if text[i] in '.!?':
                return _is_sentence_boundary(text, i)
            elif text[i] not in '"\u201d\u00BB)':
                break
    return False


# ============================================================================
# STT Buffer for Semantic Chunking (Hybrid with Timer)
# ============================================================================

@dataclass
class InputBufferConfig:
    """Configuration for the input buffer."""
    # Timeout to flush after last STT fragment (seconds)
    flush_timeout_secs: float = 3.0

    # Buffering thresholds
    min_words_long: int = 7  # Always send if >= N words (no punctuation safety net)
    min_words_with_punct: int = 5  # Send if ends with punct and >= N words
    min_sentences: int = 2  # Always send if >= N complete sentences

    # Minimum words required for timeout flush (prevents tiny fragments)
    min_words_timeout: int = 4  # Don't timeout-flush with fewer than N words

    # Maximum buffer size before forcing flush (safety valve)
    max_buffer_words: int = 30

    @classmethod
    def default(cls) -> "InputBufferConfig":
        return cls()


class InputBuffer:
    """Buffers STT output until semantically complete chunks are ready.

    Sends text to LLM when ANY of these conditions is met:
    - 7+ words (safety net for text without punctuation)
    - 2+ complete sentences (multiple short sentences)
    - 5+ words ending with sentence punctuation (single decent sentence)
    - Timeout after 2 seconds of silence (speaker paused)

    Uses semantic sentence detection to avoid false positives from:
    - Turkish abbreviations (Hz., Dr., Prof., etc.)
    - Ordinal numbers (10., 255., etc.)
    """

    def __init__(
        self,
        config: InputBufferConfig,
        on_flush: Callable[[str], Awaitable[None]],
    ):
        self._config = config
        self._on_flush = on_flush
        self._buffer_text: str = ""
        self._buffer_time: float | None = None
        self._flush_timer_task: Optional[asyncio.Task] = None

    def _get_word_count(self) -> int:
        return len(self._buffer_text.split()) if self._buffer_text else 0

    def _should_send(self, text: str) -> bool:
        """Determine if text has enough content to send to LLM."""
        word_count = len(text.split())

        # Safety: buffer too large
        if word_count >= self._config.max_buffer_words:
            return True

        # Long enough regardless of punctuation
        if word_count >= self._config.min_words_long:
            return True

        # Multiple sentences (even if short)
        if count_sentences(text) >= self._config.min_sentences:
            return True

        # Single decent sentence (uses semantic boundary detection)
        if ends_with_sentence(text) and word_count >= self._config.min_words_with_punct:
            return True

        return False

    async def add(self, text: str) -> None:
        """Add text to buffer, flush if ready (with semantic splitting)."""
        text = text.strip()
        if not text:
            return

        # Reset timer — speaker is still talking
        self._cancel_flush_timer()

        # Track when the very first fragment of this segment arrived
        if not self._buffer_text:
            self._buffer_time = time.time()

        # Merge with any buffered content
        if self._buffer_text:
            self._buffer_text = self._buffer_text + " " + text
            logger.debug(f"[STT buffer merged] {text}")
        else:
            self._buffer_text = text

        # Try to find a sentence boundary to split at
        last_sentence_end = find_last_sentence_end(self._buffer_text)
        
        if last_sentence_end != -1:
            # We have at least one complete sentence.
            # Extract the chunk up to the split point.
            candidate_chunk = self._buffer_text[:last_sentence_end].strip()
            remainder = self._buffer_text[last_sentence_end:].strip()
            
            # Check if this chunk is substantial enough to send
            word_count = len(candidate_chunk.split())
            if word_count >= self._config.min_words_with_punct:
                logger.info(f"[STT semantic split] Flushing: '{candidate_chunk}' | Remaining: '{remainder}'")
                
                # Flush the complete sentence(s)
                # We temporarily replace _buffer_text to flush just the chunk
                self._buffer_text = candidate_chunk
                await self._flush()
                
                # Restore the remainder
                self._buffer_text = remainder
                if self._buffer_text:
                    self._buffer_time = time.time()
                    self._start_flush_timer()
                return

        # If no split happened, check standard conditions on the whole buffer
        word_count = self._get_word_count()
        sentence_count = count_sentences(self._buffer_text)

        if self._should_send(self._buffer_text):
            logger.info(f"[STT send] ({word_count}w, {sentence_count}s) {self._buffer_text}")
            await self._flush()
        else:
            # Wait for more input or timeout
            logger.debug(f"[STT buffer] ({word_count}w, {sentence_count}s) {self._buffer_text}")
            self._start_flush_timer()

    async def _flush(self) -> None:
        """Flush buffer and call on_flush callback."""
        self._cancel_flush_timer()
        text = self._buffer_text
        
        # Capture timestamps before clearing
        # buffer_time is the start of the segment (first audio/stt arrival)
        segment_start_ts = self._buffer_time
        # current time is the flush time (completion of STT stage for this segment)
        flush_ts = time.time()
        
        self._buffer_text = ""
        self._buffer_time = None

        if text:
            await self._on_flush(text, stt_arrival_ts=flush_ts, segment_start_ts=segment_start_ts)

    async def force_flush(self) -> None:
        """Force flush any buffered content (e.g., on END_OF_SPEECH)."""
        if self._buffer_text:
            word_count = self._get_word_count()
            logger.info(f"[STT buffer flush] ({word_count}w) {self._buffer_text}")
        await self._flush()

    def _start_flush_timer(self) -> None:
        """Start a timer to flush after silence."""
        self._cancel_flush_timer()
        self._flush_timer_task = asyncio.create_task(self._flush_timer_callback())

    def _cancel_flush_timer(self) -> None:
        """Cancel any pending flush timer."""
        if self._flush_timer_task:
            self._flush_timer_task.cancel()
            self._flush_timer_task = None

    async def _flush_timer_callback(self) -> None:
        """Timer callback - flush if speaker stopped talking and we have enough words."""
        try:
            await asyncio.sleep(self._config.flush_timeout_secs)
            if self._buffer_text:
                word_count = self._get_word_count()
                # Only flush on timeout if we have minimum words
                # This prevents tiny fragments like "Allah'a," from being sent alone
                if word_count >= self._config.min_words_timeout:
                    logger.info(f"[STT timeout flush] ({word_count}w) {self._buffer_text}")
                    await self._flush()
                else:
                    # Not enough words - restart timer and wait for more input
                    logger.debug(f"[STT timeout skip] ({word_count}w < {self._config.min_words_timeout}) {self._buffer_text}")
                    self._start_flush_timer()
        except asyncio.CancelledError:
            pass

    @property
    def is_empty(self) -> bool:
        return not self._buffer_text

    @property
    def buffered_word_count(self) -> int:
        return self._get_word_count()


# ============================================================================
# Translation Entry Tracking
# ============================================================================

class TranslationStatus(str, Enum):
    PENDING = "pending"
    TRANSLATING = "translating"
    QUEUED = "queued"
    SPEAKING = "speaking"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass
class TranslationEntry:
    id: str
    source_text: str
    translated_text: Optional[str] = None
    status: TranslationStatus = TranslationStatus.PENDING
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_text": self.source_text,
            "translated_text": self.translated_text or "",
            "status": self.status.value,
        }


# ============================================================================
# Translator Processor
# ============================================================================

class TranslateToTTSSpeakProcessor(FrameProcessor):
    def __init__(
        self,
        llm_service,  # Any Pipecat LLM FrameProcessor (OpenAI, Gemini, Groq, etc.)
        speak_enabled: bool = True,
        input_buffer_config: Optional[InputBufferConfig] = None,
        on_translation: Optional[Callable[[str, str, float], None]] = None,
        audio_filter: Optional[Any] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._llm = llm_service
        self._speak_enabled = speak_enabled
        self._config = get_config()
        self._on_translation = on_translation
        self._audio_filter = audio_filter

        # Input buffer (STT → translation) with semantic chunking
        self._input_buffer = InputBuffer(
            input_buffer_config or InputBufferConfig.default(),
            on_flush=self._submit_translation,
        )

        # Latency tracking per segment
        from utils.latency import SegmentLatency
        self._segment_latencies: Dict[str, SegmentLatency] = {}

        # Ordered TTS queue: ensures speech order matches input order
        self._tts_queue: asyncio.Queue = asyncio.Queue()
        self._tts_consumer_task: Optional[asyncio.Task] = None

        # Provider-agnostic async streaming client
        # Uses provider-specific async client (OpenAI, Gemini, Groq)
        from providers.llm_factory import create_async_client
        self._aclient = create_async_client(self._config)

        # Verifier client — created once and cached (not per-call)
        # Refreshed automatically if provider/model changes via live config
        self._verifier_client = None
        self._verifier_client_key: Optional[tuple] = None  # (provider, model)
        if getattr(self._config, "verifier", None) and self._config.verifier.enabled:
            self._refresh_verifier_client()

        # Conversation history for cross-sentence context (sliding window)
        self._history: deque[dict] = deque(maxlen=6)  # last 3 source+translation pairs

        # Track last source texts for continuity context
        self._recent_sources: deque[str] = deque(maxlen=3)  # last 3 source texts

        # Track active LLM tasks for cancellation on clear/reset
        self._active_llm_tasks: set[asyncio.Task] = set()

        # Translation list: ordered registry of all translations with status tracking
        self._translations: dict[str, TranslationEntry] = {}
        # Queue of entry_id's currently being synthesized by TTS (FIFO)
        self._tts_in_flight: deque[str] = deque()
        # Maps translation_id -> (source_text, translated_text) for targeted history removal
        self._history_by_id: dict[str, tuple[str, str]] = {}

    def _refresh_verifier_client(self) -> None:
        """Create or refresh the cached verifier async client.

        Called once at __init__ and whenever provider/model changes via live config.
        """
        v_cfg = getattr(self._config, "verifier", None)
        if not v_cfg or not v_cfg.enabled:
            self._verifier_client = None
            self._verifier_client_key = None
            return

        provider = v_cfg.provider
        model = v_cfg.model

        try:
            import copy
            from providers.llm_factory import create_async_client
            v_config_copy = copy.deepcopy(self._config)
            v_config_copy.llm.provider = provider
            v_config_copy.llm.model = model
            self._verifier_client = create_async_client(v_config_copy)
            self._verifier_client_key = (provider, model)
            logger.info(f"[Fast Verifier] Client ready: provider={provider}, model={model}")
        except Exception as e:
            logger.error(f"[Fast Verifier] Failed to create client (provider={provider}): {e}")
            self._verifier_client = None
            self._verifier_client_key = None

    def _ensure_consumer_started(self) -> None:
        """Lazily start TTS consumer loop."""
        if self._tts_consumer_task is None or self._tts_consumer_task.done():
            self._tts_consumer_task = asyncio.create_task(self._tts_consumer_loop())

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterimTranscriptionFrame):
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame) and frame.text and frame.text.strip():
            source_text = frame.text.strip()
            await self._input_buffer.add(source_text)

        await self.push_frame(frame, direction)

    async def _submit_translation(self, text: str, stt_arrival_ts: Optional[float] = None, segment_start_ts: Optional[float] = None) -> None:
        self._ensure_consumer_started()

        # Create tracking entry
        entry_id = uuid.uuid4().hex[:8]
        entry = TranslationEntry(id=entry_id, source_text=text)
        self._translations[entry_id] = entry

        # Create segment latency tracker
        from utils.latency import SegmentLatency
        latency = SegmentLatency(segment_id=entry_id)
        # stt_arrival_ts is the time of flush (segment completion)
        latency.stt_arrival_ts = stt_arrival_ts or time.time()
        # stt_first_audio_ts is the time the segment started
        latency.stt_first_audio_ts = segment_start_ts or self._input_buffer._buffer_time or time.time()
        
        # Capture filter latency from the wrapper (if available)
        if hasattr(self._audio_filter, "last_filter_ms"):
            latency.filter_ms = self._audio_filter.last_filter_ms
            latency.audio_chunk_duration_ms = self._audio_filter.last_chunk_duration_ms
            
        self._segment_latencies[entry_id] = latency

        # Enqueue (entry_id, future) tuple FIRST to preserve ordering
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._tts_queue.put((entry_id, future))

        # Start LLM in background (runs concurrently)
        entry.status = TranslationStatus.TRANSLATING
        task = asyncio.create_task(self._run_translation(text, future, entry_id, latency))
        self._active_llm_tasks.add(task)
        task.add_done_callback(self._active_llm_tasks.discard)

    # LLM timeout: skip chunk if translation takes longer than this (seconds)
    LLM_TIMEOUT_SECS = 4.0

    async def _run_translation(self, text: str, future: asyncio.Future, entry_id: str, segment_latency: Optional[Any] = None) -> None:
        entry = self._translations.get(entry_id)

        # ====== FAST VERIFIER (Corrector) BLOCK ======
        if getattr(self._config, "verifier", None) and self._config.verifier.enabled:
            v_cfg = self._config.verifier
            current_key = (v_cfg.provider, v_cfg.model)

            # Refresh cached client if provider/model changed via live config
            if self._verifier_client_key != current_key:
                self._refresh_verifier_client()

            if self._verifier_client:
                v_start = time.time()
                try:
                    v_timeout = v_cfg.timeout
                    v_messages = [
                        {"role": "system", "content": v_cfg.prompt},
                        {"role": "user", "content": text}
                    ]

                    v_resp = await asyncio.wait_for(
                        self._verifier_client.chat.completions.create(
                            model=v_cfg.model,
                            messages=v_messages,
                            temperature=0.0,
                        ),
                        timeout=v_timeout,
                    )

                    # Safe choices access — guard against empty list
                    choices = getattr(v_resp, "choices", None)
                    v_text = choices[0].message.content.strip() if choices else ""
                    v_ms = (time.time() - v_start) * 1000
                    logger.info(f"[Fast Verifier] ({v_ms:.0f}ms) '{text}' -> '{v_text}'")

                    if v_text.strip().upper().startswith("DROP"):
                        # Anlamsız/gürültü parçası — çeviriyi iptal et
                        logger.info(f"[Fast Verifier] DROP: '{text}'")
                        if entry:
                            entry.status = TranslationStatus.CANCELLED
                        if not future.done():
                            future.set_result("")
                        return
                    elif "KEEP|" in v_text:
                        corrected_text = v_text.split("KEEP|", 1)[1].strip()
                        if corrected_text:
                            text = corrected_text
                    elif v_text:
                        # Prompt'tan gelen serbest format: doğrudan düzeltilmiş metin olarak kullan
                        text = v_text
                        logger.debug(f"[Fast Verifier] Free-format output used as corrected text: '{v_text[:80]}'")
                    # v_text boşsa: orijinal text ile devam

                except asyncio.TimeoutError:
                    v_ms = (time.time() - v_start) * 1000
                    logger.warning(f"[Fast Verifier] Timeout ({v_ms:.0f}ms), using original: '{text[:80]}'")
                except Exception as e:
                    logger.error(f"[Fast Verifier] Error: {e}")
        # ===============================================

        # LLM start zamanını verifier'dan SONRA kaydet — doğru metrik için
        llm_t0 = time.time()
        if segment_latency:
            segment_latency.llm_start_ts = llm_t0

        try:
            tokens: list[str] = []
            first_token_logged = False

            # Build user message with previous context for continuity
            if self._recent_sources:
                context_prefix = "[Previous: " + " | ".join(self._recent_sources) + "]\n"
                user_content = context_prefix + "Translate: " + text
            else:
                user_content = text

            # Build messages with conversation history for context
            messages = [{"role": "system", "content": self._config.llm.system_prompt}]
            messages.extend(self._history)
            messages.append({"role": "user", "content": user_content})

            stream = await self._aclient.chat.completions.create(
                model=self._config.llm.model,
                messages=messages,
                stream=True,
            )

            timed_out = False
            async for chunk in stream:
                # Check LLM timeout during streaming
                elapsed = time.time() - llm_t0
                if elapsed > self.LLM_TIMEOUT_SECS:
                    timed_out = True
                    logger.warning(
                        f"[LLM TIMEOUT] {elapsed:.1f}s > {self.LLM_TIMEOUT_SECS}s, "
                        f"skipping chunk: '{text[:80]}'"
                    )
                    await stream.close()
                    break

                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    if not first_token_logged:
                        now = time.time()
                        first_token_logged = True
                        if segment_latency:
                            segment_latency.llm_first_token_ts = now
                    tokens.append(token)

            if segment_latency:
                segment_latency.llm_end_ts = time.time()
                segment_latency.llm_token_count = len(tokens)

            # Skip this chunk if LLM timed out
            if timed_out:
                logger.warning(f"[LLM SKIP] Discarding timed-out translation for: '{text[:80]}'")
                if entry:
                    entry.status = TranslationStatus.CANCELLED
                if not future.done():
                    future.set_result("")
                return

            translated = _normalize_llm_output("".join(tokens))

            # Check if cancelled while translating
            if entry and entry.status == TranslationStatus.CANCELLED:
                if not future.done():
                    future.set_result("")
                return

            # Store in history for future context
            self._history.append({"role": "user", "content": user_content})
            self._history.append({"role": "assistant", "content": translated})

            # Track recent source texts for continuity
            self._recent_sources.append(text)

            # Update entry
            if entry:
                entry.translated_text = translated
                entry.status = TranslationStatus.QUEUED
                self._history_by_id[entry_id] = (text, translated)

            if not future.done():
                future.set_result(translated)

        except Exception as e:
            # Fallback: non-streaming (also with context)
            try:
                response = await asyncio.wait_for(
                    self._aclient.chat.completions.create(
                        model=self._config.llm.model,
                        messages=[
                            {"role": "system", "content": self._config.llm.system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        stream=False,
                    ),
                    timeout=self.LLM_TIMEOUT_SECS,
                )
                raw_text = response.choices[0].message.content
                result = _normalize_llm_output(raw_text) if raw_text else ""
                latency_ms = (time.time() - llm_t0) * 1000

                if entry and entry.status == TranslationStatus.CANCELLED:
                    if not future.done():
                        future.set_result("")
                    return

                if result:
                    self._recent_sources.append(text)
                    # Fallback path: also update conversation history for continuity
                    self._history.append({"role": "user", "content": user_content})
                    self._history.append({"role": "assistant", "content": result})
                if entry:
                    entry.translated_text = result
                    entry.status = TranslationStatus.QUEUED
                    self._history_by_id[entry_id] = (text, result)
                if self._on_translation and result and not self._speak_enabled:
                    self._on_translation(text, result, latency_ms)
                if not future.done():
                    future.set_result(result)
            except asyncio.TimeoutError:
                logger.warning(f"[LLM TIMEOUT] Fallback timed out for: '{text[:80]}'")
                if entry:
                    entry.status = TranslationStatus.CANCELLED
                if not future.done():
                    future.set_result("")
            except Exception as e2:
                logger.error(f"[LLM FALLBACK ERROR] Translation failed for: '{text[:80]}': {e2}", exc_info=True)
                if not future.done():
                    future.set_result("")

    async def _tts_consumer_loop(self) -> None:
        async def process_item(item):
            entry_id, future = item
            entry = self._translations.get(entry_id)

            # Skip cancelled immediate checks
            if entry and entry.status == TranslationStatus.CANCELLED:
                return

            try:
                translated = await future
            except Exception as e:
                logger.error(f"Error awaiting translation future: {e}")
                return

            # Re-check after await — may have been cancelled while waiting
            if entry and entry.status == TranslationStatus.CANCELLED:
                return

            if translated and self._speak_enabled:
                if entry:
                    entry.status = TranslationStatus.SPEAKING

                # Log LLM-to-TTS handoff timing
                latency = self._segment_latencies.get(entry_id)
                if latency and latency.llm_end_ts:
                    gap_ms = (time.time() - latency.llm_end_ts) * 1000
                    if gap_ms > 100:
                        logger.warning(f"[LLM→TTS GAP] {gap_ms:.0f}ms between LLM done and TTS push for '{translated[:50]}'")

                # Register that this segment is now in the TTS pipeline
                self._tts_in_flight.append(entry_id)

                await self.push_frame(
                    TTSSpeakFrame(translated),
                    FrameDirection.DOWNSTREAM,
                )
                if entry:
                    entry.status = TranslationStatus.DONE
            else:
                if entry:
                    entry.status = TranslationStatus.DONE
                # Cleanup latency tracking immediately since no TTS will happen
                self._segment_latencies.pop(entry_id, None)

        while True:
            try:
                item = await self._tts_queue.get()
                await process_item(item)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TTS consumer error: {e}", exc_info=True)

    def _on_tts_complete(self, started_ts: float, stopped_ts: float, audio_bytes: int, sample_rate: int) -> None:
        """Called by TTSTimingObserver when a TTS playback segment is complete."""
        if not self._tts_in_flight:
            return
            
        entry_id = self._tts_in_flight.popleft()
            
        latency = self._segment_latencies.get(entry_id)
        if not latency:
            return
            
        # Finalize TTS timing
        latency.tts_start_ts = started_ts
        latency.tts_end_ts = stopped_ts
        latency.tts_audio_bytes = audio_bytes
        latency.tts_sample_rate = sample_rate
        
        # Log translation with full latency data
        entry = self._translations.get(entry_id)
        if entry and self._on_translation:
            self._on_translation(
                entry.source_text,
                entry.translated_text or "",
                latency.llm_ms,
                segment_latency=latency
            )
            
        # Cleanup
        self._segment_latencies.pop(entry_id, None)

    async def clear_buffers(self) -> None:
        """
        Clear all buffers, cancel active tasks, and stop pending TTS.

        Called by ControlProcessor when user requests buffer clear.
        Clears input buffer, cancels LLM tasks, drains TTS queue,
        and restarts the TTS consumer. Preserves conversation history.
        """
        # 1. Cancel all active LLM tasks (stops ongoing API calls)
        cancelled_llm = 0
        for task in list(self._active_llm_tasks):
            if not task.done():
                task.cancel()
                cancelled_llm += 1
        self._active_llm_tasks.clear()

        # 2. Clear input buffer
        self._input_buffer._buffer_text = ""
        self._input_buffer._buffer_time = None
        self._input_buffer._cancel_flush_timer()

        # 3. Cancel TTS consumer (stops sending new frames to TTS)
        if self._tts_consumer_task and not self._tts_consumer_task.done():
            self._tts_consumer_task.cancel()
            self._tts_consumer_task = None

        # 4. Drain TTS queue (cancel all pending futures)
        cancelled_tts = 0
        while not self._tts_queue.empty():
            try:
                entry_id, future = self._tts_queue.get_nowait()
                if not future.done():
                    future.cancel()
                    cancelled_tts += 1
                entry = self._translations.get(entry_id)
                if entry and entry.status not in (TranslationStatus.DONE, TranslationStatus.CANCELLED):
                    entry.status = TranslationStatus.CANCELLED
            except asyncio.QueueEmpty:
                break

        # 5. Replace with fresh queue (avoids stale consumer references)
        self._tts_queue = asyncio.Queue()

        # 6. Mark active translations as cancelled
        for entry in self._translations.values():
            if entry.status not in (TranslationStatus.DONE, TranslationStatus.CANCELLED):
                entry.status = TranslationStatus.CANCELLED
        self._tts_in_flight.clear()
        self._segment_latencies.clear()

        logger.info(
            f"Buffers cleared: {cancelled_llm} LLM tasks, {cancelled_tts} TTS futures cancelled"
        )

    def get_translations_list(self) -> list[dict]:
        """Return all translations for the UI, ordered by creation time."""
        # Prune old done/cancelled entries if list is too long
        if len(self._translations) > 50:
            entries = list(self._translations.values())
            removable = [e for e in entries if e.status in (TranslationStatus.DONE, TranslationStatus.CANCELLED)]
            for e in removable[:-20]:
                self._translations.pop(e.id, None)
                self._history_by_id.pop(e.id, None)
                self._segment_latencies.pop(e.id, None)

        return [e.to_dict() for e in self._translations.values()]

    async def delete_translation_by_id(self, translation_id: str) -> dict:
        """Delete a specific translation by ID.

        Handles all states:
        - PENDING/TRANSLATING: mark cancelled, LLM will skip on completion
        - QUEUED: mark cancelled, TTS consumer will skip
        - SPEAKING: interrupt TTS playback
        - DONE: remove from history only
        """
        entry = self._translations.get(translation_id)
        if not entry:
            return {"status": "error", "message": "Translation not found"}

        was_speaking = (entry.status == TranslationStatus.SPEAKING
                        or translation_id in self._tts_in_flight)
        deleted_text = entry.translated_text or entry.source_text

        # Mark as cancelled — TTS consumer will skip it
        entry.status = TranslationStatus.CANCELLED

        # If currently speaking, interrupt TTS
        if was_speaking:
            logger.info(f"Interrupting TTS for {translation_id}")
            try:
                await self.push_frame(
                    StartInterruptionFrame(),
                    FrameDirection.DOWNSTREAM,
                )
                logger.debug("Pushed StartInterruptionFrame downstream")
            except Exception as e:
                logger.warning(f"Failed to push interruption frame: {e}")
            
            # Remove from in-flight queue if present
            try:
                self._tts_in_flight.remove(translation_id)
            except ValueError:
                pass
        else:
             logger.info(f"Not interrupting TTS for {translation_id} (was_speaking={was_speaking}, status={entry.status}, in_flight={translation_id in self._tts_in_flight})")

        # Remove from LLM history
        history_pair = self._history_by_id.pop(translation_id, None)
        if history_pair:
            self._remove_from_history(history_pair[0], history_pair[1])
            
        # Remove from latency tracking
        self._segment_latencies.pop(translation_id, None)

        logger.info(f"Deleted translation {translation_id}: {deleted_text}")
        return {
            "status": "ok",
            "deleted_id": translation_id,
            "deleted_text": deleted_text,
            "translations": self.get_translations_list(),
        }

    def _remove_from_history(self, source_text: str, translated_text: str) -> None:
        """Remove a specific source+translation pair from conversation history."""
        new_history = deque(maxlen=6)
        history_list = list(self._history)
        i = 0
        while i < len(history_list):
            if (i + 1 < len(history_list)
                    and history_list[i].get("role") == "user"
                    and history_list[i + 1].get("role") == "assistant"
                    and translated_text in history_list[i + 1].get("content", "")):
                i += 2  # skip this pair
                continue
            new_history.append(history_list[i])
            i += 1
        self._history = new_history

        # Remove from recent sources
        sources_list = list(self._recent_sources)
        for idx, s in enumerate(sources_list):
            if s == source_text:
                del sources_list[idx]
                self._recent_sources = deque(sources_list, maxlen=3)
                break

    async def delete_last_translation(self) -> dict:
        """Delete the most recent non-done translation. Backward compatible."""
        for entry in reversed(list(self._translations.values())):
            if entry.status not in (TranslationStatus.DONE, TranslationStatus.CANCELLED):
                return await self.delete_translation_by_id(entry.id)
        for entry in reversed(list(self._translations.values())):
            if entry.status == TranslationStatus.DONE:
                return await self.delete_translation_by_id(entry.id)
        return {"status": "ok", "deleted": "(none)"}

    async def reset_all(self) -> None:
        """
        Full state reset - clears everything and restarts from scratch.

        Called by ControlProcessor when user requests full reset.
        Clears all buffers, cancels tasks, resets conversation history,
        and restarts the TTS consumer loop.
        """
        # Clear all buffers and cancel active tasks
        await self.clear_buffers()

        # Clear conversation history (LLM context)
        self._history.clear()

        # Clear recent sources
        self._recent_sources.clear()

        # Clear translation tracking
        self._translations.clear()
        self._history_by_id.clear()
        self._segment_latencies.clear()
        self._tts_in_flight.clear()

        logger.info(
            "Full reset completed (buffers + LLM tasks + history + sources)"
        )
