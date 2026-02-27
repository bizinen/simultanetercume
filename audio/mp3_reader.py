"""
MP3 Reader - MP3 dosyalarını PCM audio frame'lere dönüştürür
"""

import asyncio
from pathlib import Path
from typing import AsyncIterator
import shutil

from pipecat.frames.frames import InputAudioRawFrame

from config import get_config

config = get_config()


class MP3Reader:
    """
    MP3 Dosya Okuyucu

    URL'den MP3 akışını PCM audio frame'lere dönüştürür.
    """

    def __init__(
        self,
        sample_rate: int = None,
        chunk_duration_ms: int = None,
    ):
        self.sample_rate = sample_rate or config.audio.sample_rate
        self.chunk_duration_ms = chunk_duration_ms or config.audio.chunk_size_ms

    @property
    def _bytes_per_chunk(self) -> int:
        # 16-bit mono PCM: 2 bytes/sample
        return int(self.sample_rate * 2 * (self.chunk_duration_ms / 1000))

    async def stream_frames_from_url(
        self,
        url: str,
        realtime: bool = True,
        aiohttp_session=None,
    ) -> AsyncIterator[InputAudioRawFrame]:
        """
        URL'den MP3'ü indirirken aynı anda decode edip PCM frame stream eder.

        Notlar:
        - Bu yöntem, tüm MP3'ü belleğe almadan STT'ye akış sağlamak içindir.
        - Sisteminizde `ffmpeg` binary'si PATH üzerinde olmalıdır (pydub için de genelde gerekir).
        """
        import aiohttp

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise RuntimeError(
                "ffmpeg bulunamadı. Lütfen ffmpeg'i kurup PATH'e ekleyin "
                "(Windows: winget install Gyan.FFmpeg veya choco install ffmpeg)."
            )

        close_session = False
        session = aiohttp_session
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        bytes_per_chunk = self._bytes_per_chunk
        if bytes_per_chunk <= 0:
            raise ValueError("chunk_duration_ms ve sample_rate geçersiz")

        # ffmpeg: mp3 stream (stdin) -> s16le mono pcm (stdout)
        proc = await asyncio.create_subprocess_exec(
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(self.sample_rate),
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _feed_mp3_to_ffmpeg():
            try:
                # Disable timeout for long MP3 streams (lectures, live recordings)
                stream_timeout = aiohttp.ClientTimeout(total=None, sock_read=None)
                async with session.get(url, timeout=stream_timeout) as response:
                    if response.status != 200:
                        raise Exception(f"Failed to download MP3: HTTP {response.status}")

                    total_size = response.content_length
                    downloaded = 0
                    last_progress = 0

                    async for chunk in response.content.iter_chunked(256 * 1024):
                        if not chunk:
                            continue
                        downloaded += len(chunk)

                        if total_size:
                            progress = int((downloaded / total_size) * 100)
                            if progress >= last_progress + 10:
                                last_progress = progress

                        assert proc.stdin is not None
                        proc.stdin.write(chunk)
                        await proc.stdin.drain()
            finally:
                if proc.stdin:
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass

        feeder_task = asyncio.create_task(_feed_mp3_to_ffmpeg())
        cancelled = False

        try:
            assert proc.stdout is not None
            while True:
                try:
                    pcm = await proc.stdout.readexactly(bytes_per_chunk)
                except asyncio.IncompleteReadError as e:
                    pcm = e.partial
                    if pcm:
                        yield InputAudioRawFrame(audio=pcm, sample_rate=self.sample_rate, num_channels=1)
                    break

                yield InputAudioRawFrame(audio=pcm, sample_rate=self.sample_rate, num_channels=1)

                if realtime:
                    await asyncio.sleep(self.chunk_duration_ms / 1000)
        except asyncio.CancelledError:
            # Ctrl+C veya task iptali durumunda ffmpeg'i temiz kapat
            cancelled = True
            feeder_task.cancel()
            try:
                proc.kill()
            except Exception:
                pass
            raise
        finally:
            # feeder tamamlandı mı?
            try:
                await feeder_task
            except asyncio.CancelledError:
                pass
            except ConnectionResetError:
                # ffmpeg kill sonrası normal olabilir
                if not cancelled:
                    raise
            except Exception:
                # ffmpeg'i de sonlandır, asıl hatayı yukarı taşı
                try:
                    proc.kill()
                except Exception:
                    pass
                raise

            # ffmpeg çıkışını kontrol et
            try:
                rc = await proc.wait()
            except Exception:
                rc = None

            if rc not in (0, None):
                stderr = b""
                try:
                    assert proc.stderr is not None
                    stderr = await proc.stderr.read()
                except Exception:
                    pass
                raise RuntimeError(f"ffmpeg decode failed (exit {rc}): {stderr.decode('utf-8', errors='replace')}")

            if close_session:
                await session.close()
