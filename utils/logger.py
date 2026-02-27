"""
Logging Modülü - Renkli console ve dosya logging
"""

import sys
import threading
import queue
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Any
from loguru import logger

# Varsayılan log dizini
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Background logging queue
_log_queue = queue.Queue()
_stop_event = threading.Event()


def setup_logger(level: str = "INFO"):
    """Logger'ı yapılandır"""
    
    # Windows konsolda Unicode (TR/RU) logları için
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Mevcut handler'ları temizle
    logger.remove()
  

    def _terminal_filter(record) -> bool:
        # ERROR+ logları ayrı sink'te gösteriyoruz; burada sadece "stt/llm" satırları
        return record["extra"].get("terminal") is True and record["level"].no < 40

    def _error_filter(record) -> bool:
        return record["level"].no >= 40

    # Console handler (stdout): sadece stt/llm satırları
    logger.add(
        sys.stdout,
        level="INFO",
        format="{message}",
        filter=_terminal_filter,
        colorize=False,
        enqueue=True,
    )

    # Console handler (stderr): sadece hatalar
    logger.add(
        sys.stderr,
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} - {message}\n{exception}",
        filter=_error_filter,
        colorize=False,
        backtrace=False,
        diagnose=False,
        enqueue=True,
    )
    
    # Dosya handler - günlük log dosyası
    try:
        log_file = LOG_DIR / f"translator_{datetime.now().strftime('%Y-%m-%d')}.log"
        logger.add(
            log_file,
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
            rotation="1 day",
            retention="7 days"
        )
        json_log = LOG_DIR / f"debug_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        logger.add(
            json_log,
            level="DEBUG",
            format="{message}",
            serialize=True
        )
    except (PermissionError, OSError) as e:
        logger.warning(f"Dosya loglama başlatılamadı ({e}), sadece konsol loglaması aktif.")
    
    return logger


def get_logger(name: str = "translator"):
    """Named logger döndür"""
    # Not: Loguru'nun {name} alanı call-site module adına bağlıdır.
    # Biz burada ekstra alan olarak "logger_name" tutuyoruz.
    return logger.bind(logger_name=name)


# Default setup
setup_logger()


# ============================
# Background Logging Worker
# ============================

def _logging_worker():
    """Background thread worker that writes log entries to files."""
    while not _stop_event.is_set() or not _log_queue.empty():
        try:
            # Wait for an item with a timeout to allow checking stop_event
            file_path, entry = _log_queue.get(timeout=1.0)
            
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to file (blocking I/O happens here, in background thread)
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            
            _log_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            # We use standard print here to avoid recursion with loguru
            print(f"Error in logging worker: {e}", file=sys.stderr)

# Start background worker
_worker_thread = threading.Thread(target=_logging_worker, daemon=True)
_worker_thread.start()

# Results directory for logging
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

def log_translation(
    source_text: str,
    translated_text: str,
    latency_ms: float = 0,
    source_lang: str = "tr",
    target_lang: str = "en",
    source_text_logprobs: str = None,
    filter_ms: float = 0,
    stt_ms: float = 0,
    llm_ms: float = 0,
    tts_ms: float = 0,
    segment_latency: Optional[Any] = None
):
    """Enqueue translation log entry for background writing."""

    if not hasattr(log_translation, 'file'):
        log_translation.file = RESULTS_DIR / f"translations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        log_translation.session_start_ts = None
        logger.info(f"Logging translations to: {log_translation.file}")

    # Compute audio_start_sec: seconds elapsed since session start
    audio_start_sec = None
    if segment_latency and getattr(segment_latency, 'stt_first_audio_ts', None):
        if log_translation.session_start_ts is None:
            log_translation.session_start_ts = segment_latency.stt_first_audio_ts
        audio_start_sec = round(segment_latency.stt_first_audio_ts - log_translation.session_start_ts, 2)

    if segment_latency:
        latencies_dict = segment_latency.to_dict()
        # For backward compatibility and console logging
        filter_ms = segment_latency.filter_ms
        stt_ms = segment_latency.stt_processing_ms
        llm_ms = segment_latency.llm_ms
        tts_ms = segment_latency.tts_synthesis_ms
    else:
        latencies_dict = {
             "filter_ms": round(filter_ms, 1),
             "stt_ms": round(stt_ms, 1),
             "llm_ms": round(llm_ms, 1),
             "tts_ms": round(tts_ms, 1)
        }

    entry = {
        "timestamp": datetime.now().isoformat(),
        "audio_start_sec": audio_start_sec,
        "source_language": source_lang,
        "target_language": target_lang,
        "source_text_logprobs": source_text_logprobs,
        "source_text": source_text,
        "translated_text": translated_text,
        "latency_ms": round(latency_ms, 1),
        "latencies": latencies_dict
    }

    # Console summary
    status = "✓" if (latency_ms < 4000) else "!"
    print(f"[LATENCY] {status} FLT:{filter_ms:.0f} STT:{stt_ms:.0f} LLM:{llm_ms:.0f} TTS:{tts_ms:.0f}ms")

    # Put entry in queue for background thread to handle disk I/O
    _log_queue.put((log_translation.file, entry))


def log_stt_response(words: list, text: str, is_final: bool = True):
    """Enqueue raw STT response for background writing."""
    
    if not hasattr(log_stt_response, 'file'):
        log_stt_response.file = RESULTS_DIR / f"stt_raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        logger.info(f"Logging STT responses to: {log_stt_response.file}")

    word_data = []
    for w in words:
        word_entry = {"text": str(w)}
        if hasattr(w, 'start_time'):
            word_entry["start_time"] = w.start_time
        if hasattr(w, 'end_time'):
            word_entry["end_time"] = w.end_time
        if hasattr(w, 'confidence') and w.confidence is not None:
            word_entry["logprob"] = w.confidence
        word_data.append(word_entry)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "is_final": is_final,
        "text": text,
        "words": word_data,
    }

    # Put entry in queue for background thread to handle disk I/O
    _log_queue.put((log_stt_response.file, entry))
