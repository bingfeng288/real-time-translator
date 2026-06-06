<p align="center">
  <strong>English</strong> | <a href="./README.md">中文</a>
</p>

<h1 align="center">🎙️ Real-Time Voice Translation Plugin</h1>

<p align="center">
  Offline real-time voice translation powered by Tencent Hunyuan <strong>Hy-MT2-1.8B</strong><br>
  Speech-to-Text + Auto Translation · Embeddable in any Web player
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/Offline-Ready-brightgreen" alt="Offline">
  <img src="https://img.shields.io/badge/Model-Hy--MT2--1.8B-orange" alt="Model">
</p>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🎤 **Real-time ASR** | Whisper (multilingual) + FunASR (Chinese-optimized) dual engines |
| 🌐 **Offline Translation** | Hy-MT2-1.8B local inference, no internet required |
| 🔀 **Multilingual** | 17+ languages: Chinese, English, Japanese, Korean, French, German, Spanish, Russian, etc. |
| ⚡ **WebSocket Streaming** | Low-latency audio streaming for near real-time translation |
| 🎯 **Browser VAD** | Voice Activity Detection — silence isn't transmitted |
| 🔄 **Whisper Model Switching** | Auto-recommend / manual select: tiny/base/small/medium/large |
| 🧩 **Embeddable Component** | One-line integration into any web player |
| 🖥️ **Apple Silicon Support** | Auto-detects MPS/CUDA/CPU, works out of the box on M-series Macs |

## 🏗️ Architecture

```
Browser Mic ──WebSocket──▶ FastAPI Backend
                              ├── ASR (Whisper / FunASR)
                              └── Hy-MT2-1.8B Translation
  ◀──WebSocket── Results ◀────┘
Browser Subtitles
```

## 📦 Installation

### Requirements

- Python 3.9+
- Apple Silicon Mac (MPS) / NVIDIA GPU (CUDA) / CPU
- ~5GB disk space for models

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/real-time-translator.git
cd real-time-translator

# 2. Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Model Download

Models download **automatically** on first run to `./models/`. Manual pre-download:

```bash
# Whisper base model (~140MB)
python3 -c "import whisper; whisper.load_model('base', download_root='models/whisper')"

# Hy-MT2-1.8B translation model (~3.6GB)
python3 -c "
from transformers import AutoModelForCausalLM, AutoTokenizer
AutoTokenizer.from_pretrained('Tencent-Hunyuan/Hy-MT2-1.8B', trust_remote_code=True, cache_dir='models/hy-mt2')
AutoModelForCausalLM.from_pretrained('Tencent-Hunyuan/Hy-MT2-1.8B', trust_remote_code=True, cache_dir='models/hy-mt2')
"
```

## 🚀 Usage

```bash
python run.py
```

Open browser at **http://localhost:11234**

### Steps

1. Select **source** and **target** languages
2. Choose **ASR engine** (Whisper multilingual / FunASR Chinese)
3. For Whisper, toggle **Auto/Manual** mode to select model size
4. Click the **microphone button** to start recording
5. Speak and see real-time: original text, translation, and latency

### Keyboard Shortcuts

- `Space` — Start/Stop recording

## 🔌 Embed in Your Player

Integrate the translation subtitle component into any web player in 3 steps:

### Method 1: Remote Service (Recommended)

```html
<!-- 1. Import subtitle component -->
<script src="http://localhost:11234/static/js/subtitle.js"></script>

<!-- 2. Add subtitle container -->
<div id="translation-subtitle" style="
  position: absolute; bottom: 80px; left: 50%; transform: translateX(-50%);
  width: 80%; max-width: 800px; z-index: 999;
"></div>

<!-- 3. Connect to translation service -->
<script>
const ws = new WebSocket('ws://localhost:11234/ws/translate');
const subMgr = new SubtitleManager('translation-subtitle');

ws.onopen = () => {
    ws.send(JSON.stringify({
        type: 'config',
        source_lang: 'zh',
        target_lang: 'en',
        asr_engine: 'whisper',
    }));
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'result') {
        subMgr.add(data.original, data.translated, data.source_lang, data.target_lang, data.latency_ms);
    }
};
</script>
```

### Method 2: Full Embed (with Recording Controls)

Reference the `frontend/` files and include in your player page:

```html
<link rel="stylesheet" href="http://localhost:11234/static/css/style.css">
<script src="http://localhost:11234/static/js/audio-recorder.js"></script>
<script src="http://localhost:11234/static/js/subtitle.js"></script>
<script src="http://localhost:11234/static/js/app.js"></script>
```

> 💡 The `SubtitleManager` class provides `add()`, `clear()`, `getCount()` methods for custom styling and behavior.

## 📁 Project Structure

```
real-time-translator/
├── backend/
│   ├── main.py              # FastAPI + WebSocket
│   ├── config.py            # Configuration
│   ├── asr/
│   │   ├── base.py          # ASR engine base class
│   │   ├── whisper_engine.py # Whisper (hot-swappable models)
│   │   └── funasr_engine.py  # FunASR
│   ├── translator/
│   │   └── hy_mt2.py        # Hy-MT2-1.8B engine
│   └── audio/
│       └── processor.py     # Audio decode, VAD, resample
├── frontend/
│   ├── index.html           # Main page
│   ├── css/style.css        # Dark theme UI
│   └── js/
│       ├── app.js           # Main logic
│       ├── audio-recorder.js # Mic capture + VAD
│       └── subtitle.js      # Subtitle component
├── models/                  # Models (auto-downloaded)
├── requirements.txt
├── run.py                   # Start script
└── README.md
```

## ⚙️ Configuration

Edit `backend/config.py`:

| Config | Description | Default |
|--------|-------------|---------|
| `ASR_ENGINE` | ASR engine | `whisper` |
| `WHISPER_MODEL_SIZE` | Whisper model size | `base` |
| `WHISPER_MODEL_MODE` | Model selection mode | `auto` |
| `DEFAULT_SOURCE_LANG` | Source language | `zh` |
| `DEFAULT_TARGET_LANG` | Target language | `en` |
| `AUDIO_CHUNK_DURATION` | Audio chunk duration (sec) | `3.0` |
| `PORT` | Server port | `11234` |

### Whisper Models

| Model | Params | VRAM | Speed | Accuracy |
|-------|--------|------|-------|----------|
| `tiny` | 39M | ~1GB | ⚡⚡⚡⚡ | ⭐ |
| `base` | 74M | ~1GB | ⚡⚡⚡ | ⭐⭐ |
| `small` | 244M | ~2GB | ⚡⚡ | ⭐⭐⭐ |
| `medium` | 769M | ~5GB | ⚡ | ⭐⭐⭐⭐ |
| `large` | 1550M | ~10GB | 🐌 | ⭐⭐⭐⭐⭐ |

> **Auto mode**: Apple Silicon → `small`, GPU → `medium`, CPU → `tiny`

## 📡 API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Frontend page |
| `/ws/translate` | WebSocket | Real-time translation |
| `/api/status` | GET | Service status |
| `/api/config` | GET | Get config |
| `/api/config` | POST | Update config |

## 📄 License

MIT License
