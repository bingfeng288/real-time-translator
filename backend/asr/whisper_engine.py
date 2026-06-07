"""
Whisper ASR 引擎实现
基于 OpenAI Whisper，支持多语言语音识别
"""

from typing import Optional
import numpy as np
import whisper
from loguru import logger

from .base import ASREngine
from .. import config


class WhisperEngine(ASREngine):
    """OpenAI Whisper 语音识别引擎"""

    # 设备 -> 推荐模型大小（精度优先）
    AUTO_MODEL_RECOMMENDATIONS = {
        "mps":  "small",   # Apple Silicon 推荐 small（精度高，MPS 加速可接受）
        "cuda": "medium",  # NVIDIA GPU 推荐 medium
        "cpu":  "base",    # CPU 推荐 base
    }

    def __init__(
        self,
        model_size: str = None,
        model_dir: str = None,
        device: str = None,
    ):
        self._model_dir = str(model_dir or config.WHISPER_MODEL_DIR)
        self._device = device or self._detect_device()
        self._model = None

        # 自动模式：根据设备推荐模型大小
        if config.WHISPER_MODEL_MODE == "auto" and model_size is None:
            self._model_size = self.AUTO_MODEL_RECOMMENDATIONS.get(self._device, "base")
            logger.info(f"自动选择 Whisper 模型: {self._model_size} (设备: {self._device})")
        else:
            self._model_size = model_size or config.WHISPER_MODEL_SIZE

    @staticmethod
    def _detect_device() -> str:
        """自动检测可用设备"""
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        elif torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def load_model(self) -> None:
        """加载 Whisper 模型"""
        if self._model is not None:
            return

        logger.info(f"加载 Whisper 模型: {self._model_size} (device={self._device})")
        try:
            self._model = whisper.load_model(
                self._model_size,
                device=self._device,
                download_root=self._model_dir,
            )
            logger.info("Whisper 模型加载完成")
        except Exception as e:
            logger.error(f"Whisper 模型加载失败: {e}")
            raise

    def switch_model(self, new_model_size: str) -> None:
        """
        热切换 Whisper 模型大小

        Args:
            new_model_size: 新的模型大小 (tiny/base/small/medium/large)
        """
        if new_model_size == self._model_size and self._model is not None:
            return  # 已经是目标模型

        logger.info(f"切换 Whisper 模型: {self._model_size} -> {new_model_size}")

        # 释放旧模型
        if self._model is not None:
            del self._model
            self._model = None
            import gc
            gc.collect()

        self._model_size = new_model_size
        self.load_model()

    @staticmethod
    def get_available_models() -> dict:
        """返回所有可用的 Whisper 模型及其配置"""
        return config.WHISPER_MODELS.copy()

    @staticmethod
    def get_auto_recommendation(device: str = None) -> str:
        """获取自动推荐的模型大小"""
        if device is None:
            device = WhisperEngine._detect_device()
        return WhisperEngine.AUTO_MODEL_RECOMMENDATIONS.get(device, "base")

    # 上一次识别结果，用于上下文连贯
    _last_text: str = ""

    def transcribe(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> str:
        """
        语音转文字（优化精度）

        Args:
            audio_data: float32 numpy array，值域 [-1, 1]
            sample_rate: 采样率（Whisper 固定需要 16kHz）
            language: 语言代码，None 表示自动检测

        Returns:
            识别文字
        """
        if not self.is_loaded():
            raise RuntimeError("Whisper 模型未加载，请先调用 load_model()")

        # Whisper 要求 float32，16kHz
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        # 归一化到 [-1, 1]
        max_val = np.abs(audio_data).max()
        if max_val > 1.0:
            audio_data = audio_data / max_val

        # 过滤太短的音频（小于 0.3 秒大概率是噪音）
        if len(audio_data) < sample_rate * 0.3:
            return ""

        lang = language or config.WHISPER_LANGUAGE

        options = {
            "fp16": self._device != "cpu",
            "language": lang,
            # 精度优化
            "condition_on_previous_text": True,  # 利用上文提高连贯性
            "no_speech_threshold": 0.6,           # 过滤静音/噪音
            "compression_ratio_threshold": 2.4,   # 过滤重复乱码
            "logprob_threshold": -1.0,            # 过滤低置信度
        }

        # 提供上文作为初始 prompt，帮助 Whisper 理解语境
        if self._last_text:
            options["initial_prompt"] = self._last_text[-200:]  # 取最后 200 字符

        try:
            result = self._model.transcribe(audio_data, **options)
            text = result["text"].strip()

            # 过滤 Whisper 返回的重复填充文本（常见于噪音输入）
            if not text or text == self._last_text:
                return ""

            # 检测是否是重复字符的垃圾输出
            if len(text) > 2 and len(set(text)) <= 2:
                return ""

            self._last_text = text
            return text

        except Exception as e:
            logger.error(f"Whisper 转录失败: {e}")
            return ""

    def reset_context(self) -> None:
        """重置上下文（切换语言或重新开始录音时调用）"""
        self._last_text = ""

    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def name(self) -> str:
        return f"whisper-{self._model_size}"
