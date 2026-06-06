"""
音频处理器
负责音频格式转换、VAD 静音检测、持久化流式解码
"""

import subprocess
import threading
import time
from typing import Optional, Callable
import numpy as np
from loguru import logger

from .. import config


class StreamDecoder:
    """
    持久化 ffmpeg 流式解码器
    维护一个长生命周期的 ffmpeg 进程，持续接收 webm 分片并输出 raw PCM
    """

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self._sample_rate = sample_rate
        self._channels = channels
        self._process: Optional[subprocess.Popen] = None
        self._pcm_buffer = bytearray()
        self._lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self, init_data: bytes) -> bool:
        """
        用初始化段（webm 文件头）启动 ffmpeg 进程

        Args:
            init_data: webm 初始化段（第一个 dataavailable 块）
        Returns:
            是否成功启动
        """
        if self._process is not None:
            self.stop()

        try:
            self._process = subprocess.Popen(
                [
                    "ffmpeg", "-y",
                    "-f", "matroska",
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

            # 写入初始化段
            self._process.stdin.write(init_data)
            self._process.stdin.flush()

            # 启动读取线程
            self._running = True
            self._pcm_buffer = bytearray()
            self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
            self._reader_thread.start()

            logger.debug(f"StreamDecoder 启动成功, init={len(init_data)} bytes")
            return True

        except Exception as e:
            logger.error(f"StreamDecoder 启动失败: {e}")
            return False

    def write(self, audio_chunk: bytes) -> None:
        """写入音频分片到 ffmpeg stdin"""
        if self._process is None or self._process.poll() is not None:
            return

        try:
            self._process.stdin.write(audio_chunk)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.debug(f"StreamDecoder 写入失败: {e}")

    def read_pcm(self) -> np.ndarray:
        """
        读取当前可用的 PCM 数据

        Returns:
            float32 numpy array，值域 [-1, 1]
        """
        with self._lock:
            if len(self._pcm_buffer) == 0:
                return np.array([], dtype=np.float32)

            pcm_bytes = bytes(self._pcm_buffer)
            self._pcm_buffer.clear()

        pcm_data = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        pcm_data = pcm_data / 32768.0

        if self._channels > 1 and pcm_data.ndim > 1:
            pcm_data = pcm_data[:, 0]

        return pcm_data

    def _read_stdout(self) -> None:
        """后台线程：持续读取 ffmpeg stdout"""
        chunk_size = 4096
        while self._running and self._process and self._process.poll() is None:
            try:
                data = self._process.stdout.read(chunk_size)
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

        logger.debug("StreamDecoder 已停止")

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None


class AudioProcessor:
    """音频预处理器"""

    def __init__(self):
        self._vad = None
        self._stream_decoders: dict = {}  # websocket_id -> StreamDecoder

    def init_vad(self, aggressiveness: int = None) -> None:
        """初始化 WebRTC VAD"""
        try:
            import webrtcvad
            level = aggressiveness or config.VAD_AGGRESSIVENESS
            self._vad = webrtcvad.Vad(level)
            logger.info(f"VAD 初始化完成 (aggressiveness={level})")
        except ImportError:
            logger.warning("webrtcvad 未安装，VAD 功能不可用")

    def create_stream_decoder(self, client_id: str) -> StreamDecoder:
        """为每个 WebSocket 客户端创建独立的流式解码器"""
        if client_id in self._stream_decoders:
            self._stream_decoders[client_id].stop()

        decoder = StreamDecoder(
            sample_rate=config.AUDIO_SAMPLE_RATE,
            channels=config.AUDIO_CHANNELS,
        )
        self._stream_decoders[client_id] = decoder
        return decoder

    def remove_stream_decoder(self, client_id: str) -> None:
        """移除客户端的解码器"""
        if client_id in self._stream_decoders:
            self._stream_decoders[client_id].stop()
            del self._stream_decoders[client_id]

    def decode_audio(
        self,
        audio_bytes: bytes,
        source_format: str = "webm",
        target_sample_rate: int = None,
    ) -> np.ndarray:
        """
        将浏览器发送的音频字节流解码为 numpy 数组
        用于无流式解码器的回退方案

        Args:
            audio_bytes: 原始音频字节
            source_format: 源格式
            target_sample_rate: 目标采样率

        Returns:
            float32 numpy array，值域 [-1, 1]
        """
        target_sample_rate = target_sample_rate or config.AUDIO_SAMPLE_RATE

        try:
            formats_to_try = ["matroska", "webm", "ogg"]

            for fmt in formats_to_try:
                cmd = [
                    "ffmpeg", "-y",
                    "-f", fmt,
                    "-i", "pipe:0",
                    "-ar", str(target_sample_rate),
                    "-ac", str(config.AUDIO_CHANNELS),
                    "-sample_fmt", "s16",
                    "-f", "s16le",
                    "pipe:1",
                ]

                result = subprocess.run(
                    cmd,
                    input=audio_bytes,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                )

                if result.returncode == 0 and len(result.stdout) > 0:
                    pcm_data = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32)
                    pcm_data = pcm_data / 32768.0
                    return pcm_data

            logger.debug(f"所有格式解码失败, data_size={len(audio_bytes)}")
            return np.array([], dtype=np.float32)

        except Exception as e:
            logger.error(f"音频解码失败: {e}")
            return np.array([], dtype=np.float32)

    def is_speech(self, audio_chunk: bytes, sample_rate: int = 16000) -> bool:
        """使用 VAD 检测音频块中是否包含语音"""
        if self._vad is None:
            return True

        try:
            frame_duration_ms = config.VAD_FRAME_DURATION
            frame_size = int(sample_rate * frame_duration_ms / 1000) * 2

            for i in range(0, len(audio_chunk) - frame_size + 1, frame_size):
                frame = audio_chunk[i : i + frame_size]
                if len(frame) == frame_size and self._vad.is_speech(frame, sample_rate):
                    return True
            return False

        except Exception:
            return True

    @staticmethod
    def normalize(audio: np.ndarray) -> np.ndarray:
        """音频归一化"""
        max_val = np.abs(audio).max()
        if max_val > 0:
            audio = audio / max_val
        return audio
