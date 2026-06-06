"""
FunASR 引擎实现
基于阿里达摩院 FunASR，中文识别效果优秀
"""

from typing import Optional
import numpy as np
from loguru import logger

from .base import ASREngine
from .. import config


class FunASREngine(ASREngine):
    """阿里 FunASR 语音识别引擎"""

    def __init__(self, device: str = None):
        self._device = device or self._detect_device()
        self._model = None
        self._vad_model = None
        self._punc_model = None

    @staticmethod
    def _detect_device() -> str:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        elif torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def load_model(self) -> None:
        """加载 FunASR 模型"""
        if self._model is not None:
            return

        try:
            from funasr import AutoModel

            logger.info(f"加载 FunASR 模型 (device={self._device})")

            self._model = AutoModel(
                model=config.FUNASR_MODEL_ID,
                model_revision="v2.0.4",
                device=self._device,
            )

            self._vad_model = AutoModel(
                model=config.FUNASR_VAD_MODEL_ID,
                model_revision="v2.0.4",
                device=self._device,
            )

            self._punc_model = AutoModel(
                model=config.FUNASR_PUNC_MODEL_ID,
                model_revision="v2.0.4",
                device=self._device,
            )

            logger.info("FunASR 模型加载完成")

        except ImportError:
            logger.error("FunASR 未安装，请执行: pip install funasr")
            raise
        except Exception as e:
            logger.error(f"FunASR 模型加载失败: {e}")
            raise

    def transcribe(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> str:
        """
        语音转文字

        Args:
            audio_data: float32 numpy array，值域 [-1, 1]
            sample_rate: 采样率
            language: 语言代码（FunASR 主要支持中文）

        Returns:
            识别文字
        """
        if not self.is_loaded():
            raise RuntimeError("FunASR 模型未加载，请先调用 load_model()")

        # FunASR 需要 int16 或 float32
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        try:
            result = self._model.generate(input=audio_data, batch_size_s=300)
            if result and len(result) > 0:
                text = result[0].get("text", "").strip()
                # 加标点
                if text and self._punc_model:
                    punc_result = self._punc_model.generate(input=text)
                    if punc_result and len(punc_result) > 0:
                        text = punc_result[0].get("text", text)
                return text
            return ""
        except Exception as e:
            logger.error(f"FunASR 转录失败: {e}")
            return ""

    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def name(self) -> str:
        return "funasr"
