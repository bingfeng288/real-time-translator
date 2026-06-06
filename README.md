<p align="center">
  <a href="./README_EN.md">English</a> | <strong>中文</strong>
</p>

<h1 align="center">🎙️ 实时语音翻译插件</h1>

<p align="center">
  基于腾讯混元 <strong>Hy-MT2-1.8B</strong> 翻译模型的离线实时语音翻译工具<br>
  语音转文字 + 自动翻译 · 可集成到任意 Web 播放器
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/离线-可用-brightgreen" alt="Offline">
  <img src="https://img.shields.io/badge/翻译模型-Hy--MT2--1.8B-orange" alt="Model">
</p>

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 🎤 **实时语音识别** | 支持 Whisper（多语言）和 FunASR（中文优化）双引擎 |
| 🌐 **离线翻译** | 基于 Hy-MT2-1.8B 模型，本地推理，无需联网 |
| 🔀 **多语言支持** | 中、英、日、韩、法、德、西、俄等 17 种语言互译 |
| ⚡ **WebSocket 实时通信** | 低延迟音频流传输，准实时翻译 |
| 🎯 **浏览器端 VAD** | 静音时不传输，节省带宽和算力 |
| 🔄 **Whisper 模型切换** | 支持自动推荐 / 手动选择 tiny/base/small/medium/large |
| 🧩 **可嵌入组件** | 提供 Web 组件，一行代码集成到播放器页面 |
| 🖥️ **Apple Silicon 加速** | 自动检测 MPS/CUDA/CPU，Apple Silicon Mac 即开即用 |

## 🏗️ 技术架构

```
浏览器麦克风 ──WebSocket──▶ FastAPI 后端
                               ├── ASR (Whisper / FunASR)
                               └── Hy-MT2-1.8B 翻译
  ◀──WebSocket── 翻译结果 ◀────┘
浏览器字幕展示
```

## 📦 安装

### 环境要求

- Python 3.9+
- Apple Silicon Mac（MPS 加速）/ NVIDIA GPU（CUDA）/ CPU
- 约 5GB 磁盘空间（模型下载）

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/YOUR_USERNAME/real-time-translator.git
cd real-time-translator

# 2. 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
```

### 模型下载

首次运行时模型会**自动下载**到 `./models/` 目录。也可手动预下载：

```bash
# Whisper 模型（约 140MB，base 模型）
python3 -c "import whisper; whisper.load_model('base', download_root='models/whisper')"

# Hy-MT2-1.8B 翻译模型（约 3.6GB）
python3 -c "
from transformers import AutoModelForCausalLM, AutoTokenizer
AutoTokenizer.from_pretrained('Tencent-Hunyuan/Hy-MT2-1.8B', trust_remote_code=True, cache_dir='models/hy-mt2')
AutoModelForCausalLM.from_pretrained('Tencent-Hunyuan/Hy-MT2-1.8B', trust_remote_code=True, cache_dir='models/hy-mt2')
"
```

## 🚀 启动

```bash
python run.py
```

服务启动后打开浏览器访问 **http://localhost:11234**

### 使用步骤

1. 选择**源语言**和**目标语言**
2. 选择**识别引擎**（Whisper 通用 / FunASR 中文优化）
3. 如选 Whisper，可切换**自动/手动**模式选择模型大小
4. 点击**麦克风按钮**开始录音
5. 对着麦克风说话，实时看到：
   - 📝 语音识别原文
   - 🌐 翻译结果
   - ⏱️ 响应延迟

### 快捷键

- `空格键` — 开始/停止录音

## 🔌 集成到你的播放器

将翻译字幕组件嵌入任意 Web 播放器页面，只需 3 步：

### 方法一：引入远程服务（推荐）

```html
<!-- 1. 引入字幕组件 JS -->
<script src="http://localhost:11234/static/js/subtitle.js"></script>

<!-- 2. 添加字幕容器（放在播放器合适位置） -->
<div id="translation-subtitle" style="
  position: absolute; bottom: 80px; left: 50%; transform: translateX(-50%);
  width: 80%; max-width: 800px; z-index: 999;
"></div>

<!-- 3. 连接翻译服务 -->
<script>
const ws = new WebSocket('ws://localhost:11234/ws/translate');
const subMgr = new SubtitleManager('translation-subtitle');

// 配置语言（可动态修改）
ws.onopen = () => {
    ws.send(JSON.stringify({
        type: 'config',
        source_lang: 'zh',   // 源语言
        target_lang: 'en',   // 目标语言
        asr_engine: 'whisper',
    }));
};

// 接收翻译结果并显示字幕
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'result') {
        subMgr.add(
            data.original,
            data.translated,
            data.source_lang,
            data.target_lang,
            data.latency_ms
        );
    }
};

// 发送音频（需要配合麦克风采集）
// 参考 frontend/js/audio-recorder.js 的实现
</script>
```

### 方法二：完整嵌入（含录音控件）

将 `frontend/` 目录下的文件作为参考，在你的播放器页面中：

```html
<!-- 引入完整组件 -->
<link rel="stylesheet" href="http://localhost:11234/static/css/style.css">
<script src="http://localhost:11234/static/js/audio-recorder.js"></script>
<script src="http://localhost:11234/static/js/subtitle.js"></script>
<script src="http://localhost:11234/static/js/app.js"></script>
```

> 💡 **提示**：`SubtitleManager` 类提供 `add()`、`clear()`、`getCount()` 等方法，方便自定义字幕样式和行为。

## 📁 项目结构

```
real-time-translator/
├── backend/
│   ├── main.py              # FastAPI 服务入口 + WebSocket
│   ├── config.py            # 配置（模型、端口、语言）
│   ├── asr/
│   │   ├── base.py          # ASR 引擎抽象基类
│   │   ├── whisper_engine.py # Whisper（支持模型热切换）
│   │   └── funasr_engine.py  # FunASR
│   ├── translator/
│   │   └── hy_mt2.py        # Hy-MT2-1.8B 翻译引擎
│   └── audio/
│       └── processor.py     # 音频解码、VAD、重采样
├── frontend/
│   ├── index.html           # 主页面
│   ├── css/style.css        # 暗色主题 UI
│   └── js/
│       ├── app.js           # 主逻辑（WebSocket、录音）
│       ├── audio-recorder.js # 麦克风采集 + 浏览器端 VAD
│       └── subtitle.js      # 字幕渲染组件（可独立引用）
├── models/                  # 模型文件（自动下载）
├── requirements.txt
├── run.py                   # 启动脚本
└── README.md
```

## ⚙️ 配置说明

编辑 `backend/config.py` 可修改：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `ASR_ENGINE` | ASR 引擎 | `whisper` |
| `WHISPER_MODEL_SIZE` | Whisper 模型大小 | `base` |
| `WHISPER_MODEL_MODE` | 模型选择模式 | `auto` |
| `DEFAULT_SOURCE_LANG` | 默认源语言 | `zh` |
| `DEFAULT_TARGET_LANG` | 默认目标语言 | `en` |
| `AUDIO_CHUNK_DURATION` | 音频块时长（秒） | `3.0` |
| `PORT` | 服务端口 | `11234` |

### Whisper 模型说明

| 模型 | 参数量 | 显存 | 速度 | 精度 |
|------|--------|------|------|------|
| `tiny` | 39M | ~1GB | ⚡⚡⚡⚡ | ⭐ |
| `base` | 74M | ~1GB | ⚡⚡⚡ | ⭐⭐ |
| `small` | 244M | ~2GB | ⚡⚡ | ⭐⭐⭐ |
| `medium` | 769M | ~5GB | ⚡ | ⭐⭐⭐⭐ |
| `large` | 1550M | ~10GB | 🐌 | ⭐⭐⭐⭐⭐ |

> **自动模式**会根据你的设备自动选择：Apple Silicon → `small`，GPU → `medium`，CPU → `tiny`

## 📡 API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 前端页面 |
| `/ws/translate` | WebSocket | 实时翻译 |
| `/api/status` | GET | 服务状态 |
| `/api/config` | GET | 获取配置 |
| `/api/config` | POST | 更新配置 |

### WebSocket 协议

**客户端发送：**
```json
// 配置消息
{"type": "config", "source_lang": "zh", "target_lang": "en", "asr_engine": "whisper", "whisper_model_mode": "auto"}

// 音频数据：直接发送二进制 (webm/opus)
```

**服务端返回：**
```json
// 翻译结果
{"type": "result", "original": "你好世界", "translated": "Hello world", "latency_ms": 150.5}

// 配置更新确认
{"type": "config_updated", "whisper_model_size": "small", "whisper_model_mode": "auto"}
```

## 📄 License

MIT License
