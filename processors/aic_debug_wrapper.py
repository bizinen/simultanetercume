"""
AIC Filter Debug Wrapper - Records original and filtered audio for comparison.

Wraps the Pipecat AICFilter and saves audio to debug_audio/ directory:
- original_{timestamp}.wav: Audio before AIC processing
- filtered_{timestamp}.wav: Audio after AIC processing

IMPORTANT: AIC Filter uses block-based buffering, so there may be a slight
time offset between original and filtered recordings.
"""

import os
import wave
from datetime import datetime
from typing import Optional
import numpy as np

from pipecat.audio.filters.base_audio_filter import BaseAudioFilter
from pipecat.frames.frames import FilterControlFrame

from utils.logger import get_logger

logger = get_logger("aic_debug_wrapper")

# Maximum debug buffer size (50MB). At 16kHz mono 16-bit, ~26 minutes of audio.
# Prevents unbounded memory growth on long sessions.
MAX_DEBUG_BUFFER_BYTES = 50 * 1024 * 1024


class AICDebugWrapper(BaseAudioFilter):
    """
    Debug wrapper for AIC Filter that records original and filtered audio.

    Usage:
        aic_filter = AICFilter(license_key=..., model_id=...)
        debug_wrapper = AICDebugWrapper(aic_filter, debug_enabled=True)
        # Pass debug_wrapper to transport instead of aic_filter
    """

    def __init__(
        self,
        aic_filter: BaseAudioFilter,
        debug_enabled: bool = True,
        debug_dir: Optional[str] = None,
        gain_compensation: bool = True,
    ):
        """
        Initialize the debug wrapper.

        Args:
            aic_filter: The actual AIC Filter instance to wrap
            debug_enabled: Whether to record debug audio
            debug_dir: Directory to save debug files (default: debug_audio/)
            gain_compensation: Automatically restore volume after AIC filtering.
                AIC reduces volume by ~10%, which can cause quiet speech
                (e.g. greetings, prayers) to fall below VAD threshold.
        """
        self._aic_filter = aic_filter
        self._debug_enabled = debug_enabled
        self._debug_dir = debug_dir or os.path.join(os.getcwd(), "debug_audio")

        self._sample_rate = 16000

        # --- Input limiter: protect AIC model from loud transients ---
        # Loud bursts (jingles, applause) corrupt AIC's internal noise model,
        # causing it to suppress speech for 10-15 seconds afterwards.
        # Two-tier protection:
        #   1. Absolute ceiling: hard cap on max RMS regardless of context
        #   2. Relative ceiling: cap sudden spikes relative to running speech level
        self._limiter_speech_ema = 2000.0  # Running average of SPEECH-level RMS
        self._limiter_alpha_up = 0.05  # Slow rise — don't let bursts inflate the EMA
        self._limiter_alpha_down = 0.02  # Very slow decay — silence doesn't drain it
        self._limiter_absolute_max = 8000.0  # Hard cap: no chunk goes above this RMS
        self._limiter_relative_ceiling = 3.0  # Max ratio above speech EMA
        self._limiter_count = 0  # Stats: how many chunks were limited

        # --- Suppression detector: bypass AIC when it outputs silence ---
        # When the AIC model erroneously suppresses speech (outputs ~0 for
        # chunks where input has speech), we detect this and pass original
        # audio through until the model recovers.
        self._suppressed_streak = 0  # Consecutive suppressed chunks
        self._suppression_threshold = 3  # Chunks before activating bypass
        self._suppression_bypass_active = False
        self._suppression_recovery_count = 0  # Good chunks needed to deactivate
        self._suppression_recovery_threshold = 5  # ~500ms of good output
        self._suppression_bypass_count = 0  # Stats

        # Gain compensation: AIC filter reduces volume, which can cause
        # quiet speech to be missed by VAD. This restores original volume.
        self._gain_compensation = gain_compensation
        self._gain_ema = 1.0  # Exponential moving average of gain ratio
        self._gain_alpha_normal = 0.15  # Normal EMA smoothing (faster adaptation)
        self._gain_alpha_fast = 0.5  # Fast EMA when large deviation detected
        self._gain_alpha = self._gain_alpha_normal
        # Minimum RMS to trigger gain calculation (ignore silence)
        self._gain_min_rms = 150.0
        # Track consecutive silent chunks to reset gain on silence→speech transitions
        self._silent_chunk_count = 0
        self._silent_reset_threshold = 10  # Reset gain EMA after ~1s of silence

        # Raw audio buffers (accumulate bytes, write on stop)
        self._original_buffer = bytearray()
        self._filtered_buffer = bytearray()

        # For tracking alignment
        self._aligned_original = bytearray()
        self._aligned_filtered = bytearray()

        self._started = False
        self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Statistics
        self._call_count = 0
        self._processed_count = 0
        self._total_input_bytes = 0
        self._total_output_bytes = 0
        self._modification_count = 0
        self._gain_applied_count = 0

        # For RMS comparison
        self._input_rms_sum = 0.0
        self._output_rms_sum = 0.0
        self._rms_samples = 0

        # Create debug directory immediately
        os.makedirs(self._debug_dir, exist_ok=True)
        gc_status = "ON" if gain_compensation else "OFF"
        logger.bind(terminal=True).info(
            f"AIC Debug Wrapper initialized (gain compensation: {gc_status}) - recording to: {self._debug_dir}"
        )

    async def start(self, sample_rate: int):
        """Initialize the filter with the transport's sample rate."""
        self._sample_rate = sample_rate
        self._started = True
        self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Clear buffers
        self._original_buffer.clear()
        self._filtered_buffer.clear()
        self._aligned_original.clear()
        self._aligned_filtered.clear()

        # Reset stats
        self._call_count = 0
        self._processed_count = 0
        self._total_input_bytes = 0
        self._total_output_bytes = 0
        self._modification_count = 0
        self._gain_applied_count = 0
        self._input_rms_sum = 0.0
        self._output_rms_sum = 0.0
        self._rms_samples = 0
        self._gain_ema = 1.0
        self._silent_chunk_count = 0
        self._gain_alpha = self._gain_alpha_normal
        self._limiter_speech_ema = 2000.0
        self._limiter_count = 0
        self._suppressed_streak = 0
        self._suppression_bypass_active = False
        self._suppression_recovery_count = 0
        self._suppression_bypass_count = 0

        logger.bind(terminal=True).info(f"AIC Debug recording STARTED at {sample_rate} Hz")

        # Start the wrapped AIC filter
        if self._aic_filter:
            await self._aic_filter.start(sample_rate)

            # Check if AIC filter is ready
            if hasattr(self._aic_filter, '_aic_ready'):
                if self._aic_filter._aic_ready:
                    logger.bind(terminal=True).info("AIC Filter is READY and processing audio")
                else:
                    logger.bind(terminal=True).error("AIC Filter initialization FAILED - audio will NOT be filtered!")

            # Check bypass mode
            if hasattr(self._aic_filter, '_bypass'):
                if self._aic_filter._bypass:
                    logger.bind(terminal=True).warning("AIC Filter is in BYPASS mode - audio will NOT be filtered!")
                else:
                    logger.bind(terminal=True).info("AIC Filter is in ACTIVE mode")

    async def stop(self):
        """Clean up resources and save WAV files."""
        logger.bind(terminal=True).info("AIC Debug recording STOPPING...")

        # Report statistics
        if self._call_count > 0:
            logger.bind(terminal=True).info(f"Filter calls: {self._call_count}, Processed (non-empty output): {self._processed_count}")
            logger.bind(terminal=True).info(f"Total input: {self._total_input_bytes} bytes, Total output: {self._total_output_bytes} bytes")

            if self._processed_count > 0:
                pct = (self._modification_count / self._processed_count) * 100
                logger.bind(terminal=True).info(f"Data modification: {self._modification_count}/{self._processed_count} chunks ({pct:.1f}%)")

            if self._rms_samples > 0:
                avg_input_rms = self._input_rms_sum / self._rms_samples
                avg_output_rms = self._output_rms_sum / self._rms_samples
                rms_diff = ((avg_output_rms - avg_input_rms) / avg_input_rms * 100) if avg_input_rms > 0 else 0
                logger.bind(terminal=True).info(f"Avg RMS - Input: {avg_input_rms:.2f}, Output: {avg_output_rms:.2f} (change: {rms_diff:+.1f}%)")

            if self._gain_compensation and self._gain_applied_count > 0:
                logger.bind(terminal=True).info(
                    f"Gain compensation applied to {self._gain_applied_count} chunks, final gain EMA: {self._gain_ema:.3f}"
                )

            if self._limiter_count > 0:
                logger.bind(terminal=True).info(
                    f"Input limiter activated {self._limiter_count} times (loud transient protection)"
                )

            if self._suppression_bypass_count > 0:
                logger.bind(terminal=True).info(
                    f"Suppression bypass activated {self._suppression_bypass_count} times (AIC model recovery)"
                )

            if self._modification_count == 0 and self._processed_count > 0:
                logger.bind(terminal=True).warning("NO AUDIO DATA WAS MODIFIED - AIC filter may not be working!")

        # Save accumulated audio to WAV files
        if self._debug_enabled and self._started:
            self._save_wav_files()

        self._started = False

        # Stop the wrapped filter
        if self._aic_filter:
            await self._aic_filter.stop()

        logger.bind(terminal=True).info("AIC Debug recording STOPPED")

    def _save_wav_files(self):
        """Save buffered audio data to WAV files."""
        try:
            original_path = os.path.join(self._debug_dir, f"original_{self._timestamp}.wav")
            filtered_path = os.path.join(self._debug_dir, f"filtered_{self._timestamp}.wav")

            # Save original audio (all input)
            if len(self._original_buffer) > 0:
                self._write_wav(original_path, bytes(self._original_buffer))
                logger.bind(terminal=True).info(f"Saved original audio: {original_path} ({len(self._original_buffer)} bytes)")
            else:
                logger.warning("No original audio data to save")

            # Save filtered audio (all output)
            if len(self._filtered_buffer) > 0:
                self._write_wav(filtered_path, bytes(self._filtered_buffer))
                logger.bind(terminal=True).info(f"Saved filtered audio: {filtered_path} ({len(self._filtered_buffer)} bytes)")
            else:
                logger.warning("No filtered audio data to save")

            # Also save aligned versions for direct comparison
            if len(self._aligned_original) > 0 and len(self._aligned_filtered) > 0:
                aligned_orig_path = os.path.join(self._debug_dir, f"aligned_original_{self._timestamp}.wav")
                aligned_filt_path = os.path.join(self._debug_dir, f"aligned_filtered_{self._timestamp}.wav")

                # Match lengths for fair comparison
                min_len = min(len(self._aligned_original), len(self._aligned_filtered))
                self._write_wav(aligned_orig_path, bytes(self._aligned_original[:min_len]))
                self._write_wav(aligned_filt_path, bytes(self._aligned_filtered[:min_len]))
                logger.bind(terminal=True).info(f"Saved aligned audio files for comparison ({min_len} bytes each)")

        except Exception as e:
            logger.error(f"Failed to save WAV files: {e}")

    def _write_wav(self, filepath: str, audio_data: bytes):
        """Write audio data to a WAV file."""
        with wave.open(filepath, "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(self._sample_rate)
            wav_file.writeframes(audio_data)

    def _calculate_rms(self, audio_bytes: bytes) -> float:
        """Calculate RMS of audio data."""
        if len(audio_bytes) < 2:
            return 0.0
        try:
            samples = np.frombuffer(audio_bytes, dtype=np.int16)
            return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        except Exception:
            return 0.0

    def _limit_input(self, audio: bytes) -> bytes:
        """Soft-limit loud transients to protect AIC model's internal state.

        The AIC neural model maintains an internal noise estimate. When hit
        with a sudden loud burst (jingles, applause, etc.), the model can
        misclassify subsequent speech as noise and suppress it for 10-15s.

        Two-tier protection:
        1. Absolute ceiling (8000 RMS): hard cap that catches any extreme burst.
           Normal speech peaks at ~3500 RMS, so 8000 is generous headroom.
        2. Relative ceiling (3x speech EMA): catches bursts that are loud
           relative to the current speech level.

        The speech EMA uses asymmetric alpha — rises slowly (so bursts don't
        inflate it) and decays slowly (so silence doesn't drain it).
        """
        if len(audio) < 2:
            return bytes(audio)

        # Coerce to bytes BEFORE frombuffer so NumPy's memoryview lock
        # does not conflict with Pipecat reusing/resizing the original bytearray.
        audio = bytes(audio)
        samples = np.frombuffer(audio, dtype=np.int16)
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))

        # Update speech-level EMA with asymmetric smoothing
        if rms > self._limiter_speech_ema:
            alpha = self._limiter_alpha_up  # Slow rise
        else:
            alpha = self._limiter_alpha_down  # Very slow decay
        self._limiter_speech_ema = (
            alpha * rms + (1.0 - alpha) * self._limiter_speech_ema
        )

        # Two-tier ceiling: whichever is more restrictive
        # 1. Absolute: never exceed _limiter_absolute_max
        # 2. Relative: never exceed _limiter_relative_ceiling * speech_ema
        speech_floor = max(self._limiter_speech_ema, 1000.0)
        relative_limit = speech_floor * self._limiter_relative_ceiling
        effective_limit = min(self._limiter_absolute_max, relative_limit)

        if rms > effective_limit and rms > 500:
            attenuation = effective_limit / rms
            limited = np.clip(
                samples.astype(np.float64) * attenuation,
                -32768,
                32767,
            ).astype(np.int16)
            self._limiter_count += 1
            if self._limiter_count <= 10 or self._limiter_count % 50 == 0:
                logger.bind(terminal=True).warning(
                    f"Input limiter: rms={rms:.0f} → {effective_limit:.0f} "
                    f"(speech_ema={self._limiter_speech_ema:.0f}, "
                    f"abs_limit={self._limiter_absolute_max:.0f}, "
                    f"rel_limit={relative_limit:.0f}, atten={attenuation:.2f})"
                )
            return limited.tobytes()

        return audio

    def _check_suppression(self, input_rms: float, output_rms: float) -> bool:
        """Detect when AIC model is erroneously suppressing speech.

        Returns True if the filter should be bypassed (pass original audio).

        After a loud transient, the AIC model can output near-silence even
        when the input contains clear speech. We detect this by comparing
        input vs output RMS — if the output is <10% of input for several
        consecutive speech chunks, we activate bypass mode.
        """
        has_speech = input_rms > self._gain_min_rms
        is_suppressed = has_speech and output_rms < (input_rms * 0.10)

        if self._suppression_bypass_active:
            # Currently bypassing — check if AIC model has recovered
            if has_speech and not is_suppressed:
                self._suppression_recovery_count += 1
                if self._suppression_recovery_count >= self._suppression_recovery_threshold:
                    self._suppression_bypass_active = False
                    self._suppressed_streak = 0
                    self._suppression_recovery_count = 0
                    logger.bind(terminal=True).info(
                        "AIC suppression bypass DEACTIVATED - model recovered"
                    )
                    return False
            else:
                self._suppression_recovery_count = 0
            return True
        else:
            # Not bypassing — check if suppression is starting
            if is_suppressed:
                self._suppressed_streak += 1
                if self._suppressed_streak >= self._suppression_threshold:
                    self._suppression_bypass_active = True
                    self._suppression_recovery_count = 0
                    self._suppression_bypass_count += 1
                    logger.bind(terminal=True).warning(
                        f"AIC suppression bypass ACTIVATED - model is suppressing speech "
                        f"(input_rms={input_rms:.0f}, output_rms={output_rms:.0f})"
                    )
                    return True
            else:
                self._suppressed_streak = 0
            return False

    async def process_frame(self, frame: FilterControlFrame):
        """Process control frames."""
        if self._aic_filter:
            await self._aic_filter.process_frame(frame)

    async def filter(self, audio: bytes) -> bytes:
        """
        Apply AIC enhancement and record both original and filtered audio.

        Pipeline:
        1. Input limiter: attenuate loud transients before AIC
        2. AIC filter: neural noise reduction
        3. Suppression detector: bypass AIC if it's outputting silence for speech
        4. Gain compensation: restore ~10% volume reduction from AIC

        Args:
            audio: Raw audio data as bytes (int16 PCM)

        Returns:
            Enhanced audio data as bytes (int16 PCM)
        """
        self._call_count += 1

        # Ensure audio is immutable bytes before we create any memoryviews via NumPy.
        # Pipecat uses bytearrays internally, and NumPy locks memoryviews of bytearrays,
        # causing "object cannot be re-sized" if Pipecat reuses the buffer.
        audio = bytes(audio) if audio else audio

        self._total_input_bytes += len(audio) if audio else 0

        # Record original audio to buffer (with size limit)
        if self._debug_enabled and audio:
            if len(self._original_buffer) < MAX_DEBUG_BUFFER_BYTES:
                self._original_buffer.extend(audio)
            elif self._call_count % 1000 == 0:
                logger.warning(f"Debug original buffer limit reached ({MAX_DEBUG_BUFFER_BYTES // (1024*1024)}MB), recording stopped")

        # Step 1: Limit loud transients before they reach AIC
        limited_audio = self._limit_input(audio) if audio else audio

        # Step 2: Apply AIC filter
        if self._aic_filter:
            filtered_audio = await self._aic_filter.filter(limited_audio)
        else:
            filtered_audio = limited_audio

        filtered_audio = bytes(filtered_audio) if filtered_audio else filtered_audio

        # Record filtered audio to buffer (only non-empty data)
        if filtered_audio and len(filtered_audio) > 0:
            self._processed_count += 1
            self._total_output_bytes += len(filtered_audio)

            # Pre-compute RMS once when input/output sizes match.
            # Both Step 3 (suppression) and Step 4 (gain) need the same values;
            # calculating twice is redundant and wastes CPU on every audio chunk.
            sizes_match = bool(audio and len(audio) == len(filtered_audio))
            input_rms: float = 0.0
            output_rms: float = 0.0
            if sizes_match:
                input_rms = self._calculate_rms(audio)
                output_rms = self._calculate_rms(filtered_audio)

            # Step 3: Check for AIC suppression and bypass if needed
            if sizes_match:
                if self._check_suppression(input_rms, output_rms):
                    # AIC is suppressing speech — pass original audio through
                    filtered_audio = audio

            # Step 4: Gain compensation — restore volume that AIC reduces
            if (
                self._gain_compensation
                and sizes_match
                and audio != filtered_audio
            ):
                # Only compensate for non-silent chunks (both have speech)
                if input_rms > self._gain_min_rms and output_rms > self._gain_min_rms:
                    # Reset gain EMA after prolonged silence to avoid
                    # stale gain from previous audio characteristics
                    if self._silent_chunk_count >= self._silent_reset_threshold:
                        self._gain_ema = 1.0
                        self._gain_alpha = self._gain_alpha_normal
                    self._silent_chunk_count = 0

                    chunk_gain = input_rms / output_rms
                    # Tighter clamp to prevent distortion (was 0.8-1.8)
                    chunk_gain = max(0.9, min(1.4, chunk_gain))

                    # Use faster alpha when chunk_gain deviates significantly
                    # from the current EMA (adapts quickly to audio changes)
                    deviation = abs(chunk_gain - self._gain_ema)
                    if deviation > 0.15:
                        self._gain_alpha = self._gain_alpha_fast
                    else:
                        self._gain_alpha = self._gain_alpha_normal

                    # Smooth gain with EMA to avoid per-chunk jumps
                    self._gain_ema = (
                        self._gain_alpha * chunk_gain
                        + (1.0 - self._gain_alpha) * self._gain_ema
                    )
                else:
                    # Track consecutive silent/quiet chunks
                    self._silent_chunk_count += 1

                # Apply accumulated gain if it's meaningful (>2% difference)
                if abs(self._gain_ema - 1.0) > 0.02:
                    samples = np.frombuffer(filtered_audio, dtype=np.int16)
                    boosted = np.clip(
                        samples.astype(np.float64) * self._gain_ema,
                        -32768,
                        32767,
                    ).astype(np.int16)
                    filtered_audio = boosted.tobytes()
                    self._gain_applied_count += 1

                # Track RMS stats (before gain, for accurate AIC measurement)
                if input_rms > self._gain_min_rms:
                    self._modification_count += 1
                    self._input_rms_sum += input_rms
                    self._output_rms_sum += output_rms
                    self._rms_samples += 1

            if self._debug_enabled and len(self._filtered_buffer) < MAX_DEBUG_BUFFER_BYTES:
                self._filtered_buffer.extend(filtered_audio)

                # For aligned comparison
                self._aligned_filtered.extend(filtered_audio)

                if len(audio) == len(filtered_audio):
                    self._aligned_original.extend(audio)

        return filtered_audio
