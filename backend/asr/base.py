"""
ASR 引擎抽象基类
"""

from abc import ABC, abstractmethod
from typing import Optional
import numpy as np


class ASREngine(ABC):
    """语音识别引擎基类"""

    @abstractmethod
    def load_model(self) -> None:
        """加载模型到内存"""
        ...

    @abstractmethod
    def transcribe(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> str:
        """
        将音频数据转为文字

        Args:
            audio_data: 音频数据，float32 numpy array，值域 [-1, 1]
            sample_rate: 采样率
            language: 语言代码（None 表示自动检测）

        Returns:
            识别出的文字
        """
        ...

    @abstractmethod
    def is_loaded(self) -> bool:
        """模型是否已加载"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎名称"""
        ...
