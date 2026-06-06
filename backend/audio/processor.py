"""
音频处理器
负责音频格式转换、持久化流式解码
"""

import subprocess
import threading
import time
from typing import Optional
import numpy as np
from loguru import logger

from .. import config


class StreamDecoder:
    """
    持久化 ffmpeg 流式解码器
    1. 用 webm 头部初始化 ffmpeg 进程
    2. 后续音频 Cluster 数据写入 stdin，从 stdout 读取 PCM
    """

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self._sample_rate = sample_rate
        self._channels = channels
        self._process: Optional[subprocess.Popen] = None
        self._pcm_buffer = bytearray()
        self._lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self, webm_header: bytes) -> bool:
        """
        用 webm 头部（EBML + Segment + Tracks，不含 Cluster）启动 ffmpeg
        """
        if self._process is not None:
            self.stop()

        try:
            self._process = subprocess.Popen(
                [
                    "ffmpeg", "-y",
                    "-f", "webm",
                    "-i", "pipe:0",
                    "-ar", str(self._sample_rate),
                    "-ac", str(self._channels),
                    "-sample_fmt", "s16",
                    "-f", "s16le",
                    "pipe:1",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            # 写入 webm 头部
            self._process.stdin.write(webm_header)
            self._process.stdin.flush()

            # 启动读取线程
            self._running = True
            self._pcm_buffer = bytearray()
            self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
            self._reader_thread.start()

            logger.debug(f"StreamDecoder 启动, header={len(webm_header)} bytes")
            return True

        except Exception as e:
            logger.error(f"StreamDecoder 启动失败: {e}")
            return False

    def write(self, audio_chunk: bytes) -> None:
        """写入音频 Cluster 数据"""
        if self._process is None or self._process.poll() is not None:
            return
        try:
            self._process.stdin.write(audio_chunk)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def read_pcm(self) -> np.ndarray:
        """读取当前可用的 PCM 数据"""
        with self._lock:
            if len(self._pcm_buffer) == 0:
                return np.array([], dtype=np.float32)
            pcm_bytes = bytes(self._pcm_buffer)
            self._pcm_buffer.clear()

        pcm_data = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        return pcm_data / 32768.0

    def _read_stdout(self) -> None:
        """后台线程持续读取 ffmpeg stdout"""
        while self._running and self._process and self._process.poll() is None:
            try:
                data = self._process.stdout.read(4096)
                if data:
                    with self._lock:
                        self._pcm_buffer.extend(data)
                else:
                    time.sleep(0.01)
            except Exception:
                break

    def stop(self) -> None:
        """停止解码器"""
        self._running = False
        if self._process:
            try:
                self._process.stdin.close()
            except Exception:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2)

        with self._lock:
            self._pcm_buffer.clear()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None


class AudioProcessor:
    """音频预处理器"""

    def __init__(self):
        self._vad = None
        self._decoders: dict[str, StreamDecoder] = {}

    def init_vad(self, aggressiveness: int = None) -> None:
        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(aggressiveness or config.VAD_AGGRESSIVENESS)
            logger.info(f"VAD 初始化完成")
        except ImportError:
            logger.warning("webrtcvad 未安装")

    def create_decoder(self, client_id: str) -> StreamDecoder:
        """为客户端创建解码器"""
        if client_id in self._decoders:
            self._decoders[client_id].stop()
        decoder = StreamDecoder(config.AUDIO_SAMPLE_RATE, config.AUDIO_CHANNELS)
        self._decoders[client_id] = decoder
        return decoder

    def remove_decoder(self, client_id: str) -> None:
        if client_id in self._decoders:
            self._decoders[client_id].stop()
            del self._decoders[client_id]

    @staticmethod
    def normalize(audio: np.ndarray) -> np.ndarray:
        max_val = np.abs(audio).max()
        return audio / max_val if max_val > 0 else audio
