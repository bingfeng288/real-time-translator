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

    # 翻译 prompt 模板
    # 使用简洁的格式，避免模型续写
    PROMPT_TEMPLATES = {
        "translate": "Translate from {source} to {target}:\n{text}\n=",
        "translate_zh_to_en": "中文翻译英文：\n{text}\n=",
        "translate_en_to_zh": "英文翻译中文：\n{text}\n=",
        "translate_zh_to_ja": "中文翻译日文：\n{text}\n=",
        "translate_ja_to_zh": "日文翻译中文：\n{text}\n=",
        "translate_zh_to_ko": "中文翻译韩文：\n{text}\n=",
        "translate_ko_to_zh": "韩文翻译中文：\n{text}\n=",
        "translate_en_to_ja": "English to Japanese:\n{text}\n=",
        "translate_ja_to_en": "Japanese to English:\n{text}\n=",
        "translate_en_to_ko": "English to Korean:\n{text}\n=",
        "translate_ko_to_en": "Korean to English:\n{text}\n=",
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

            # 获取 eos_token_id 用于提前停止
            eos_token_id = self._tokenizer.eos_token_id

            gen_kwargs = {
                "max_new_tokens": 256,  # 限制生成长度，避免续写
                "do_sample": False,     # 贪心解码，翻译更稳定
                "pad_token_id": eos_token_id,
                "eos_token_id": eos_token_id,
                "repetition_penalty": 1.2,
                "no_repeat_ngram_size": 3,
            }

            with torch.no_grad():
                outputs = self._model.generate(**inputs, **gen_kwargs)

            # 只取新生成的 token
            new_tokens = outputs[0][inputs["input_ids"].shape[-1]:]
            result = self._tokenizer.decode(new_tokens, skip_special_tokens=True)

            # 清理结果
            result = self._clean_translation(result, source_lang, target_lang)

            return result

        except Exception as e:
            logger.error(f"翻译失败: {e}")
            return ""

    def _clean_translation(self, text: str, source_lang: str = None, target_lang: str = None) -> str:
        """清理翻译结果，去除续写内容和噪音"""
        if not text:
            return ""

        # 去除首尾空白
        text = text.strip()

        # 去除 prompt 残留标记
        for prefix in ["=", "翻译：", "Translation:", "译文：", "输出：", "Output:", "答案："]:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()

        # 按换行分割，取第一行（续写通常在第二行开始）
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            text = lines[0]

        # 检测续写：如果文本中出现源语言的常见续写标记，截断
        continuation_markers = [
            "。", "！", "？",  # 中文句子结束（如果目标是英文）
            ".", "!", "?",     # 英文句子结束
            "\n",
            "翻译", "Translation", "译文", "注", "Note", "解释",
            "原文", "Source", "原文是",
        ]

        # 如果目标语言是英文，中文句号可能是续写的开始
        if target_lang == "en" and source_lang == "zh":
            for marker in ["。", "！", "？"]:
                idx = text.find(marker)
                if idx > 0 and idx < len(text) - 1:
                    text = text[:idx].strip()

        # 如果目标语言是中文，英文句号可能是续写的开始
        if target_lang == "zh" and source_lang == "en":
            for marker in [".", "!", "?"]:
                idx = text.find(marker)
                if idx > 0 and idx < len(text) - 1:
                    # 检查句号后面是否有更多文本（可能是续写）
                    after = text[idx+1:].strip()
                    if after and len(after) > 5:
                        text = text[:idx+1].strip()

        # 去除引号包裹
        if len(text) >= 2:
            if (text[0] in ('"', '"', '「', '『', '"') and text[-1] in ('"', '"', '」', '』', '"')):
                text = text[1:-1].strip()
            elif (text[0] == '(' and text[-1] == ')'):
                text = text[1:-1].strip()

        # 过滤垃圾输出
        if len(text) > 3 and len(set(text)) <= 2:
            return ""

        if len(text) <= 1:
            return ""

        # 过滤明显的非翻译内容（模型输出了源语言而非目标语言）
        # 这是一个简单的启发式检查
        if target_lang == "en" and source_lang == "zh":
            # 如果输出大部分是中文，可能是续写而非翻译
            chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
            if chinese_chars > len(text) * 0.5 and len(text) > 5:
                return ""  # 丢弃，等待下一个有效翻译

        return text

    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def name(self) -> str:
        return "Hy-MT2-1.8B"

    def get_supported_languages(self) -> dict:
        """返回支持的语言映射"""
        return config.LANGUAGE_MAP.copy()
