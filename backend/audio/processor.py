"""
音频处理器
负责音频格式转换、VAD 静音检测、音频分块
"""

import io
import subprocess
import tempfile
import os
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
        通过 stdin 管道直接传给 ffmpeg，避免临时文件和格式检测问题

        Args:
            audio_bytes: 原始音频字节
            source_format: 源格式（webm/opus/wav）
            target_sample_rate: 目标采样率

        Returns:
            float32 numpy array，值域 [-1, 1]
        """
        target_sample_rate = target_sample_rate or config.AUDIO_SAMPLE_RATE

        try:
            # 通过 stdin 管道喂给 ffmpeg，输出 raw PCM 到 stdout
            cmd = [
                "ffmpeg", "-y",
                "-f", source_format,       # 指定输入格式
                "-i", "pipe:0",            # 从 stdin 读取
                "-ar", str(target_sample_rate),
                "-ac", str(config.AUDIO_CHANNELS),
                "-sample_fmt", "s16",
                "-f", "s16le",             # 输出 raw 16-bit PCM
                "pipe:1",                  # 写到 stdout
            ]

            result = subprocess.run(
                cmd,
                input=audio_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
            )

            if result.returncode != 0:
                # 只在非格式错误时打印日志（避免刷屏）
                err = result.stderr.decode(errors="replace")
                if "Invalid data found" not in err:
                    logger.error(f"ffmpeg 解码失败: {err[-200:]}")
                return np.array([], dtype=np.float32)

            # 将 raw PCM bytes 转为 numpy array
            pcm_data = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32)
            pcm_data = pcm_data / 32768.0  # 归一化到 [-1, 1]

            return pcm_data

        except Exception as e:
            logger.error(f"音频解码失败: {e}")
            return np.array([], dtype=np.float32)

    def resample(
        self,
        audio: np.ndarray,
        orig_sr: int,
        target_sr: int,
    ) -> np.ndarray:
        """重采样"""
        if orig_sr == target_sr:
            return audio

        try:
            import torchaudio
            import torch

            tensor = torch.from_numpy(audio).unsqueeze(0)
            resampler = torchaudio.transforms.Resample(orig_sr, target_sr)
            resampled = resampler(tensor)
            return resampled.squeeze(0).numpy()
        except ImportError:
            # 简单线性插值回退
            duration = len(audio) / orig_sr
            target_len = int(duration * target_sr)
            indices = np.linspace(0, len(audio) - 1, target_len)
            return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

    def is_speech(self, audio_chunk: bytes, sample_rate: int = 16000) -> bool:
        """
        使用 VAD 检测音频块中是否包含语音

        Args:
            audio_chunk: 原始 PCM 音频字节（16-bit）
            sample_rate: 采样率

        Returns:
            是否包含语音
        """
        if self._vad is None:
            return True  # 没有 VAD 时默认认为有语音

        try:
            # WebRTC VAD 要求特定帧长
            frame_duration_ms = config.VAD_FRAME_DURATION
            frame_size = int(sample_rate * frame_duration_ms / 1000) * 2  # 16-bit = 2 bytes

            # 检查至少一个帧包含语音
            for i in range(0, len(audio_chunk) - frame_size + 1, frame_size):
                frame = audio_chunk[i : i + frame_size]
                if len(frame) == frame_size and self._vad.is_speech(frame, sample_rate):
                    return True
            return False

        except Exception:
            return True

    def split_audio(
        self,
        audio: np.ndarray,
        chunk_duration: float = None,
        overlap_duration: float = None,
        sample_rate: int = None,
    ) -> list:
        """
        将长音频分块

        Args:
            audio: 音频数据
            chunk_duration: 块时长（秒）
            overlap_duration: 重叠时长（秒）
            sample_rate: 采样率

        Returns:
            音频块列表
        """
        chunk_duration = chunk_duration or config.AUDIO_CHUNK_DURATION
        overlap_duration = overlap_duration or config.AUDIO_OVERLAP_DURATION
        sample_rate = sample_rate or config.AUDIO_SAMPLE_RATE

        chunk_size = int(chunk_duration * sample_rate)
        overlap_size = int(overlap_duration * sample_rate)
        step = chunk_size - overlap_size

        chunks = []
        start = 0
        while start < len(audio):
            end = min(start + chunk_size, len(audio))
            chunk = audio[start:end]

            # 跳过太短的块
            if len(chunk) < sample_rate * 0.5:  # 小于 0.5 秒
                break

            chunks.append(chunk)
            start += step

        return chunks

    @staticmethod
    def normalize(audio: np.ndarray) -> np.ndarray:
        """音频归一化"""
        max_val = np.abs(audio).max()
        if max_val > 0:
            audio = audio / max_val
        return audio

    @staticmethod
    def remove_silence(
        audio: np.ndarray,
        threshold: float = 0.01,
        sample_rate: int = 16000,
    ) -> np.ndarray:
        """简单的静音移除"""
        # 找到非静音区域
        non_silent = np.abs(audio) > threshold
        if not non_silent.any():
            return audio

        first = np.argmax(non_silent)
        last = len(audio) - np.argmax(non_silent[::-1]) - 1
        return audio[first:last+1]
