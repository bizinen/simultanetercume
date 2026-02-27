"""
Gemini Live STT Service — Google Gemini Live WebSocket API ile gerçek zamanlı ses transkripsiyonu.

Mimari:
- InputAudioRawFrame gelince ses bir queue'ya konur (max 500 paket)
- Arka planda asyncio Task, Gemini Live WebSocket bağlantısını yönetir
- Ses queue'dan okunarak session.send_realtime_input() ile Gemini'ye gönderilir
- input_audio_transcription aktif → server_content.input_transcription.text STT çıktısı
- turn_complete=True → TranscriptionFrame (final) yayınlanır
- Bağlantı koptuğunda exponential backoff (1s → 2s → 4s … max 60s) ile yeniden bağlanır
- InterimTranscriptionFrame 75ms throttle ile UI titrememesi önlenir

ÖNEMLI — Model ve config gereksinimleri:
  Native-audio modeller (gemini-2.5-flash-native-audio-*) YALNIZCA AUDIO çıktı destekler.
  response_modalities=["TEXT"] ile bağlanmak 1007 hatası verir.
  Doğru config: response_modalities=["AUDIO"] + input_audio_transcription
  Model audio üretir ama biz sadece input_transcription.text'i kullanırız;
  üretilen ses paketleri _receive_loop içinde sessizce atılır (bant genişliği tasarrufu için
  TEXT modality kullanmak istense de native-audio modeller bunu desteklememektedir).

NOTLAR:
  - Pipecat pipeline'daki AIC/RNNoise VAD ile Gemini'nin kendi VAD'ı (AutomaticActivityDetection)
    aynı anda çalışır. Bu "çift VAD" cümle sınırı tespitini etkileyebilir. Yüksek gürültülü
    ortamlarda silence_duration_ms değerini artırmayı deneyin.
  - google-genai>=0.7.0 gerektirir (AudioTranscriptionConfig, ContextWindowCompressionConfig vb.).
"""

import asyncio
import logging
import time
from typing import Optional

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

_LANG_NAMES = {
    "tr": "Turkish",
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "ru": "Russian",
    "ar": "Arabic",
    "it": "Italian",
}

# Reconnect parametreleri
_RECONNECT_BASE_DELAY  = 1.0   # ilk bekleme (saniye)
_RECONNECT_MAX_DELAY   = 60.0  # maksimum bekleme (saniye)
_RECONNECT_MULTIPLIER  = 2.0   # katlanma katsayısı

# InterimTranscriptionFrame throttle — UI titrememesi için
_INTERIM_THROTTLE_SECS = 0.075  # 75 ms


class GeminiLiveSTTService(FrameProcessor):
    """Gemini Live WebSocket API kullanarak gerçek zamanlı ses transkripsiyonu.

    Özellikler:
    - Exponential backoff ile otomatik yeniden bağlanma
    - InterimTranscriptionFrame 75 ms throttle
    - Sınırlı audio queue (maxsize=500, drop-oldest strateji)
    - Bağlantı durum takibi (is_connected property)
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        language: str,
        sample_rate: int,
        silence_duration_ms: int = 400,
        end_sensitivity: str = "HIGH",
        start_sensitivity: str = "HIGH",
        prefix_padding_ms: int = 0,
        custom_system_instruction: str = "",
        context_compression: bool = True,
        domain_vocabulary: str = "",
        punctuation_mode: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._api_key = api_key
        self._model = model
        self._language = language.lower()
        self._sample_rate = sample_rate
        self._silence_duration_ms = max(100, int(silence_duration_ms))
        self._end_sensitivity = end_sensitivity.upper() if end_sensitivity else "HIGH"
        self._start_sensitivity = start_sensitivity.upper() if start_sensitivity else "HIGH"
        self._prefix_padding_ms = max(0, int(prefix_padding_ms)) if prefix_padding_ms else 0
        self._custom_system_instruction = custom_system_instruction.strip()
        self._context_compression = bool(context_compression)
        self._domain_vocabulary = domain_vocabulary.strip()
        self._punctuation_mode = bool(punctuation_mode)

        lang_code = self._language[:2]
        self._lang_name = _LANG_NAMES.get(lang_code, lang_code)

        # maxsize=500 → bağlantı gecikmesinde bellek koruması
        self._audio_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._connection_task: Optional[asyncio.Task] = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._accumulated_text: str = ""
        self._is_connected: bool = False      # gerçek bağlantı durum bayrağı
        self._last_interim_time: float = 0.0  # throttle için

        logger.info(
            f"Gemini Live STT created: model={model}, lang={language}, "
            f"silence={self._silence_duration_ms}ms, sensitivity={self._end_sensitivity}, "
            f"compression={self._context_compression}, punctuation={self._punctuation_mode}"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        """Gemini Live WebSocket'in gerçekten bağlı olup olmadığını döndürür."""
        return self._is_connected

    # ── Frame processing ──────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            await self._start_connection()

        elif isinstance(frame, InputAudioRawFrame):
            audio_bytes = bytes(frame.audio)
            if audio_bytes:
                try:
                    self._audio_queue.put_nowait(audio_bytes)
                except asyncio.QueueFull:
                    # Queue dolu → en eski paketi at, yenisini ekle (drop-oldest)
                    try:
                        self._audio_queue.get_nowait()
                        self._audio_queue.put_nowait(audio_bytes)
                    except asyncio.QueueEmpty:
                        pass

        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop_connection()
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def _start_connection(self) -> None:
        self._stop_event.clear()
        self._is_connected = False
        self._accumulated_text = ""
        self._last_interim_time = 0.0
        self._connection_task = asyncio.create_task(
            self._connection_loop(),
            name="gemini_stt_connection",
        )
        logger.info("Gemini Live STT: connection task started")

    async def _stop_connection(self) -> None:
        self._stop_event.set()
        self._is_connected = False
        if self._connection_task and not self._connection_task.done():
            self._connection_task.cancel()
            try:
                await self._connection_task
            except (asyncio.CancelledError, Exception):
                pass
        self._connection_task = None
        logger.info("Gemini Live STT: connection stopped")

    # ── WebSocket connection loop (exponential backoff ile retry) ─────────────

    async def _connection_loop(self) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            logger.error(
                "google-genai paketi kurulu değil. "
                "Çalıştırın: pip install 'google-genai>=0.7.0'"
            )
            return

        system_instruction = self._build_system_instruction()
        config = self._build_live_config(types, system_instruction)
        client = genai.Client(api_key=self._api_key)

        delay = _RECONNECT_BASE_DELAY

        while not self._stop_event.is_set():
            try:
                logger.info(
                    f"Gemini Live STT: {self._model}'e bağlanılıyor "
                    f"(AUDIO modality + input_audio_transcription)"
                )
                async with client.aio.live.connect(model=self._model, config=config) as session:
                    self._is_connected = True
                    delay = _RECONNECT_BASE_DELAY  # başarılı bağlantıda backoff'u sıfırla
                    logger.info("Gemini Live STT: WebSocket bağlantısı kuruldu")

                    try:
                        await asyncio.gather(
                            self._send_loop(session),
                            self._receive_loop(session),
                        )
                    except asyncio.CancelledError:
                        return
                    except Exception as e:
                        logger.error(f"Gemini Live STT session hatası: {e}", exc_info=True)
                    finally:
                        self._is_connected = False

            except asyncio.CancelledError:
                return
            except Exception as e:
                self._is_connected = False
                logger.error(f"Gemini Live STT bağlantı hatası: {e}", exc_info=True)

            # Stop event kontrolü — bağlantı kapandıktan hemen sonra
            if self._stop_event.is_set():
                return

            logger.warning(
                f"Gemini Live STT: bağlantı koptu — {delay:.1f}s sonra yeniden denenecek "
                f"(max {_RECONNECT_MAX_DELAY:.0f}s)"
            )

            # Backoff bekleme: stop_event gelirse erken çık
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=delay,
                )
                return  # stop event geldi
            except asyncio.TimeoutError:
                pass  # normal bekleme süresi doldu, retry

            delay = min(delay * _RECONNECT_MULTIPLIER, _RECONNECT_MAX_DELAY)

    # ── System instruction builder ────────────────────────────────────────────

    def _build_system_instruction(self) -> str:
        """Katmanlı system instruction oluşturur."""
        base = self._custom_system_instruction

        if self._punctuation_mode:
            punct_prompt = (
                "Apply proper punctuation (periods, commas, question marks, exclamation marks). "
                "Capitalize the first word of each sentence and all proper nouns and names. "
                "Do NOT add punctuation that was not implied by the audio."
            )
            base = f"{base} {punct_prompt}".strip() if base else punct_prompt

        if self._domain_vocabulary:
            terms = [t.strip() for t in self._domain_vocabulary.split(",") if t.strip()]
            if terms:
                term_list = ", ".join(terms)
                vocab_prompt = (
                    f"Pay special attention to these domain-specific terms and transcribe them exactly: {term_list}. "
                    f"If you hear a word that sounds similar to one of these terms, prefer the exact term."
                )
                base = f"{base} {vocab_prompt}".strip() if base else vocab_prompt

        logger.debug(f"Gemini Live STT: system_instruction={base[:120]}...")
        return base

    # ── Live connect config builder ───────────────────────────────────────────

    def _build_live_config(self, types, system_instruction: str):
        """LiveConnectConfig nesnesini oluşturur. SDK uyumsuzluğunda dict fallback kullanır."""
        config_dict = {
            "response_modalities": ["AUDIO"],
            "system_instruction": system_instruction,
        }

        # input_audio_transcription — SDK 0.7+ gerektirir
        try:
            config_dict["input_audio_transcription"] = types.AudioTranscriptionConfig()
            logger.debug("Gemini Live STT: input_audio_transcription etkin")
        except AttributeError:
            config_dict["input_audio_transcription"] = {}
            logger.debug("Gemini Live STT: AudioTranscriptionConfig dict fallback kullanılıyor")

        # VAD — admin panelden yönetilebilir
        try:
            end_enum = getattr(
                types.EndSensitivity,
                f"END_SENSITIVITY_{self._end_sensitivity}",
                types.EndSensitivity.END_SENSITIVITY_HIGH,
            )
            start_enum = getattr(
                types.StartSensitivity,
                f"START_SENSITIVITY_{self._start_sensitivity}",
                types.StartSensitivity.START_SENSITIVITY_HIGH,
            )
            vad_kwargs = {
                "start_of_speech_sensitivity": start_enum,
                "end_of_speech_sensitivity": end_enum,
                "silence_duration_ms": self._silence_duration_ms,
            }
            if self._prefix_padding_ms > 0:
                vad_kwargs["prefix_padding_ms"] = self._prefix_padding_ms
            config_dict["realtime_input_config"] = types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(**vad_kwargs)
            )
            logger.debug(
                f"Gemini Live STT: VAD start={self._start_sensitivity} "
                f"end={self._end_sensitivity} silence={self._silence_duration_ms}ms "
                f"prefix={self._prefix_padding_ms}ms"
            )
        except Exception as vad_e:
            logger.debug(f"Gemini Live STT: VAD config uygulanamadı: {vad_e}")

        # Context Window Compression: uzun konferanslarda session kopmaz
        if self._context_compression:
            try:
                config_dict["context_window_compression"] = types.ContextWindowCompressionConfig(
                    sliding_window=types.SlidingWindow(),
                )
                logger.debug("Gemini Live STT: context_window_compression (SlidingWindow) etkin")
            except Exception as cw_e:
                logger.debug(f"Gemini Live STT: context_window_compression uygulanamadı: {cw_e}")

        try:
            return types.LiveConnectConfig(**config_dict)
        except Exception as e:
            logger.debug(f"Gemini Live STT: LiveConnectConfig fallback (dict): {e}")
            return config_dict

    # ── Send loop ─────────────────────────────────────────────────────────────

    async def _send_loop(self, session) -> None:
        """Audio queue'dan oku ve Gemini'ye PCM olarak gönder.

        Stop event set edilene kadar çalışır; geçici send hataları loop'u kesmez.
        """
        try:
            from google.genai import types
            mime_type = f"audio/pcm;rate={self._sample_rate}"

            while not self._stop_event.is_set():
                try:
                    audio_bytes = await asyncio.wait_for(
                        self._audio_queue.get(),
                        timeout=0.1,
                    )
                    await session.send_realtime_input(
                        audio=types.Blob(data=audio_bytes, mime_type=mime_type)
                    )
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(f"Gemini Live STT gönderme hatası (devam): {e}")
                    await asyncio.sleep(0.05)

        except asyncio.CancelledError:
            pass

    # ── Receive loop ──────────────────────────────────────────────────────────

    async def _receive_loop(self, session) -> None:
        """Gemini'den transkripsiyon al ve Pipecat frame olarak yayınla.

        KRİTİK — session.receive() DAVRANIŞI:
          Her çağrı, yalnızca o anki konuşma turuna (turn) ait mesajları verir.
          Turn_complete gelince iterator tükenir; sonraki tur için receive() TEKRAR çağrılmalıdır.

        Pipecat resmi implementasyonu (gemini_live/llm.py):
            while True:
                turn = session.receive()
                async for message in turn:
                    ...

        NOT: Model AUDIO modality üretir (native-audio gereksinimi), ancak bu ses paketleri
        intentionally atılır — yalnızca input_transcription.text kullanılır.
        """
        try:
            while not self._stop_event.is_set():
                # Her konuşma turu için yeni bir receive() iterator'ı oluştur
                turn = session.receive()

                async for response in turn:
                    if self._stop_event.is_set():
                        return

                    sc = getattr(response, "server_content", None)
                    if sc is None:
                        continue

                    # ── input_transcription → kullanıcı sesinin transkripsiyonu ──
                    input_trans = getattr(sc, "input_transcription", None)
                    if input_trans is not None:
                        chunk = getattr(input_trans, "text", "") or ""
                        if chunk:
                            self._accumulated_text += chunk
                            logger.debug(f"Gemini Live STT chunk: {chunk!r}")

                            # 75ms throttle — art arda gelen chunk'larda UI titrememesi
                            now = time.monotonic()
                            if now - self._last_interim_time >= _INTERIM_THROTTLE_SECS:
                                self._last_interim_time = now
                                await self.push_frame(
                                    InterimTranscriptionFrame(
                                        text=self._accumulated_text.strip(),
                                        user_id="",
                                        timestamp="",
                                        language=self._language,
                                    )
                                )

                    # ── Turn tamamlandı ─────────────────────────────────────
                    turn_complete = bool(getattr(sc, "turn_complete", False))
                    interrupted = bool(getattr(sc, "interrupted", False))

                    if turn_complete or interrupted:
                        final = self._accumulated_text.strip()
                        if final:
                            label = "interrupted" if interrupted else "turn_complete"
                            logger.info(f"Gemini Live STT final [{label}]: {final!r}")
                            await self.push_frame(
                                TranscriptionFrame(
                                    text=final,
                                    user_id="",
                                    timestamp="",
                                    language=self._language,
                                )
                            )
                        # Buffer ve throttle sıfırla; while döngüsü yeni turn için döner
                        self._accumulated_text = ""
                        self._last_interim_time = 0.0
                        logger.debug("Gemini Live STT: tur bitti, yeni tur bekleniyor")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Gemini Live STT alma hatası: {e}", exc_info=True)
