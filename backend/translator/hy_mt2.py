"""
Hy-MT2-1.8B 翻译引擎
基于腾讯混元机器翻译模型，支持多语言互译
"""

from typing import Optional
from loguru import logger

from .. import config


class HyMT2Translator:
    """
    腾讯混元 Hy-MT2-1.8B 翻译引擎

    使用 transformers 加载模型，通过 prompt 驱动翻译任务。
    支持中、英、日、韩、法、德、西、葡、俄等多语言。
    """

    # 翻译 prompt 模板（更明确的指令，提高准确度）
    PROMPT_TEMPLATES = {
        "translate": "Translate the following {source} text to {target}. Only output the translation, nothing else.\n\n{text}",
        "translate_zh_to_en": "将以下中文翻译为地道的英文。只输出翻译结果，不要添加任何解释。\n\n{text}",
        "translate_en_to_zh": "将以下英文翻译为流畅的中文。只输出翻译结果，不要添加任何解释。\n\n{text}",
        "translate_zh_to_ja": "将以下中文翻译为日文。只输出翻译结果。\n\n{text}",
        "translate_ja_to_zh": "将以下日文翻译为中文。只输出翻译结果。\n\n{text}",
        "translate_zh_to_ko": "将以下中文翻译为韩文。只输出翻译结果。\n\n{text}",
        "translate_ko_to_zh": "将以下韩文翻译为中文。只输出翻译结果。\n\n{text}",
        "translate_en_to_ja": "Translate the following English text to Japanese. Output only the translation.\n\n{text}",
        "translate_ja_to_en": "Translate the following Japanese text to English. Output only the translation.\n\n{text}",
        "translate_en_to_ko": "Translate the following English text to Korean. Output only the translation.\n\n{text}",
        "translate_ko_to_en": "Translate the following Korean text to English. Output only the translation.\n\n{text}",
    }

    def __init__(
        self,
        model_id: str = None,
        model_dir: str = None,
        device: str = None,
    ):
        self._model_id = model_id or config.TRANSLATION_MODEL_ID
        self._model_dir = str(model_dir or config.TRANSLATION_MODEL_DIR)
        self._device = device or self._detect_device()
        self._model = None
        self._tokenizer = None

    @staticmethod
    def _detect_device() -> str:
        """自动检测设备"""
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        elif torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def load_model(self) -> None:
        """加载 Hy-MT2 模型和 tokenizer"""
        if self._model is not None:
            return

        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch

            logger.info(f"加载翻译模型: {self._model_id} (device={self._device})")

            self._tokenizer = AutoTokenizer.from_pretrained(
                self._model_id,
                trust_remote_code=True,
                cache_dir=self._model_dir,
            )

            # 根据设备选择 dtype
            dtype = torch.float16 if self._device != "cpu" else torch.float32

            self._model = AutoModelForCausalLM.from_pretrained(
                self._model_id,
                trust_remote_code=True,
                torch_dtype=dtype,
                cache_dir=self._model_dir,
            )

            # 移动到设备
            if self._device == "mps":
                self._model = self._model.to("mps")
            elif self._device == "cuda":
                self._model = self._model.to("cuda")

            self._model.eval()
            logger.info("翻译模型加载完成")

        except Exception as e:
            logger.error(f"翻译模型加载失败: {e}")
            raise

    def _build_prompt(
        self, text: str, source_lang: str, target_lang: str
    ) -> str:
        """构造翻译 prompt"""
        source_name = config.LANGUAGE_MAP.get(source_lang, source_lang)
        target_name = config.LANGUAGE_MAP.get(target_lang, target_lang)

        # 优先使用特定语言对模板
        template_key = f"translate_{source_lang}_to_{target_lang}"
        if template_key in self.PROMPT_TEMPLATES:
            return self.PROMPT_TEMPLATES[template_key].format(text=text)

        # 使用通用模板
        return self.PROMPT_TEMPLATES["translate"].format(
            source=source_name,
            target=target_name,
            text=text,
        )

    def translate(
        self,
        text: str,
        source_lang: str = None,
        target_lang: str = None,
    ) -> str:
        """
        翻译文本

        Args:
            text: 待翻译文本
            source_lang: 源语言代码（如 "zh"）
            target_lang: 目标语言代码（如 "en"）

        Returns:
            翻译结果
        """
        if not self.is_loaded():
            raise RuntimeError("翻译模型未加载，请先调用 load_model()")

        if not text or not text.strip():
            return ""

        source_lang = source_lang or config.DEFAULT_SOURCE_LANG
        target_lang = target_lang or config.DEFAULT_TARGET_LANG

        prompt = self._build_prompt(text, source_lang, target_lang)

        try:
            import torch

            inputs = self._tokenizer(prompt, return_tensors="pt")

            # 移动到同一设备
            device = next(self._model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}

            gen_kwargs = {
                "max_new_tokens": config.TRANSLATION_MAX_NEW_TOKENS,
                "do_sample": False,  # 贪心解码，翻译更稳定
                "pad_token_id": self._tokenizer.eos_token_id,
                "repetition_penalty": 1.15,  # 避免重复输出
                "no_repeat_ngram_size": 3,   # 禁止 3-gram 重复
            }

            with torch.no_grad():
                outputs = self._model.generate(**inputs, **gen_kwargs)

            # 只取新生成的 token
            new_tokens = outputs[0][inputs["input_ids"].shape[-1]:]
            result = self._tokenizer.decode(new_tokens, skip_special_tokens=True)

            # 清理结果
            result = self._clean_translation(result)

            return result

        except Exception as e:
            logger.error(f"翻译失败: {e}")
            return ""

    def _clean_translation(self, text: str) -> str:
        """清理翻译结果，去除模型生成的噪音"""
        if not text:
            return ""

        # 去除首尾空白
        text = text.strip()

        # 取第一行（模型有时会生成多行）
        text = text.split("\n")[0].strip()

        # 去除常见的 prompt 残留
        for prefix in ["翻译：", "Translation:", "译文：", "输出：", "Output:", "答案："]:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()

        # 去除引号包裹
        if len(text) >= 2 and text[0] in ('"', '"', '「') and text[-1] in ('"', '"', '」'):
            text = text[1:-1].strip()

        # 过滤明显的垃圾输出（全是重复字符）
        if len(text) > 3 and len(set(text)) <= 2:
            return ""

        # 过滤太短的无意义输出
        if len(text) <= 1:
            return ""

        return text

    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def name(self) -> str:
        return "Hy-MT2-1.8B"

    def get_supported_languages(self) -> dict:
        """返回支持的语言映射"""
        return config.LANGUAGE_MAP.copy()
