"""
音频处理器
负责音频格式转换、VAD 静音检测
"""

import subprocess
from typing import Optional
import numpy as np
from loguru import logger

from .. import config


class AudioProcessor:
    """音频预处理器"""

    def __init__(self):
        self._vad = None

    def init_vad(self, aggressiveness: int = None) -> None:
        """初始化 WebRTC VAD"""
        try:
            import webrtcvad
            level = aggressiveness or config.VAD_AGGRESSIVENESS
            self._vad = webrtcvad.Vad(level)
            logger.info(f"VAD 初始化完成 (aggressiveness={level})")
        except ImportError:
            logger.warning("webrtcvad 未安装，VAD 功能不可用")

    def decode_audio(
        self,
        audio_bytes: bytes,
        source_format: str = "webm",
        target_sample_rate: int = None,
    ) -> np.ndarray:
        """
        将浏览器发送的音频字节流解码为 numpy 数组
        通过 stdin 管道直接传给 ffmpeg

        Args:
            audio_bytes: 原始音频字节（完整的 webm 文件）
            source_format: 源格式
            target_sample_rate: 目标采样率

        Returns:
            float32 numpy array，值域 [-1, 1]
        """
        target_sample_rate = target_sample_rate or config.AUDIO_SAMPLE_RATE

        try:
            cmd = [
                "ffmpeg", "-y",
                "-f", "matroska",
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
