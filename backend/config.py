"""
配置文件 - 实时语音翻译插件
"""

from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(exist_ok=True)

# ============================================================
# ASR 配置
# ============================================================
ASR_ENGINE = "whisper"  # "whisper" 或 "funasr"

WHISPER_MODEL_SIZE = "small"  # tiny / base / small / medium / large（small 精度更高）
WHISPER_MODEL_DIR = MODEL_DIR / "whisper"
WHISPER_LANGUAGE = None  # None = 自动检测，或指定 "zh" / "en" / "ja" 等

# Whisper 模型配置（名称 -> 参数量 / 适用场景）
WHISPER_MODELS = {
    "tiny":   {"params": "39M",   "vram": "~1GB", "speed": "最快",   "desc": "速度优先，精度较低"},
    "base":   {"params": "74M",   "vram": "~1GB", "speed": "快",     "desc": "速度与精度平衡（默认）"},
    "small":  {"params": "244M",  "vram": "~2GB", "speed": "中等",   "desc": "较好的识别精度"},
    "medium": {"params": "769M",  "vram": "~5GB", "speed": "较慢",   "desc": "高精度识别"},
    "large":  {"params": "1550M", "vram": "~10GB","speed": "最慢",   "desc": "最高精度，需要较大显存"},
}

# 自动选择模式: "auto" 根据设备自动推荐, "manual" 用户手动选择
WHISPER_MODEL_MODE = "auto"  # "auto" 或 "manual"

FUNASR_MODEL_ID = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
FUNASR_VAD_MODEL_ID = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
FUNASR_PUNC_MODEL_ID = "iic/punc_ct-transformer_cn-en-common-vocab471067-large"
FUNASR_MODEL_DIR = MODEL_DIR / "funasr"

# ============================================================
# 翻译配置 (Hy-MT2-1.8B)
# ============================================================
TRANSLATION_MODEL_ID = "tencent/Hy-MT2-1.8B"
TRANSLATION_MODEL_DIR = MODEL_DIR / "hy-mt2"

# 支持的语言映射（ISO 639-1 -> 模型语言名）
LANGUAGE_MAP = {
    "zh": "Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "th": "Thai",
    "vi": "Vietnamese",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "id": "Indonesian",
}

# 默认翻译方向
DEFAULT_SOURCE_LANG = "zh"
DEFAULT_TARGET_LANG = "en"

# 翻译生成参数
TRANSLATION_MAX_NEW_TOKENS = 512
TRANSLATION_TEMPERATURE = None  # 不设置 temperature，避免警告
TRANSLATION_DO_SAMPLE = False

# ============================================================
# 音频配置
# ============================================================
AUDIO_SAMPLE_RATE = 16000      # 16kHz（ASR 标准采样率）
AUDIO_CHANNELS = 1             # 单声道
AUDIO_SAMPLE_WIDTH = 2         # 16-bit
AUDIO_CHUNK_DURATION = 3.0     # 每块音频时长（秒）
AUDIO_OVERLAP_DURATION = 0.5   # 块间重叠时长（秒）

# VAD 配置
VAD_AGGRESSIVENESS = 3         # 0-3，越高越敏感
VAD_FRAME_DURATION = 30        # 帧时长（ms）
VAD_SILENCE_THRESHOLD = 0.5    # 静音阈值（秒）

# ============================================================
# 服务配置
# ============================================================
HOST = "0.0.0.0"
PORT = 11234
DEBUG = True
