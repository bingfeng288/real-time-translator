"""
实时语音翻译服务 - FastAPI 入口
WebSocket 端点：接收音频流 → ASR → 翻译 → 返回结果
"""

import json
import time
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from loguru import logger

from . import config
from .asr.base import ASREngine
from .asr.whisper_engine import WhisperEngine
from .asr.funasr_engine import FunASREngine
from .translator.hy_mt2 import HyMT2Translator
from .audio.processor import AudioProcessor

# ============================================================
# 全局实例
# ============================================================
app = FastAPI(title="实时语音翻译", version="1.0.0")

# 模型实例（启动时预加载）
asr_engine: Optional[ASREngine] = None
translator: Optional[HyMT2Translator] = None
audio_processor = AudioProcessor()


def get_asr_engine(engine_name: str = None) -> ASREngine:
    """获取 ASR 引擎"""
    name = engine_name or config.ASR_ENGINE
    if name == "whisper":
        return WhisperEngine()
    elif name == "funasr":
        return FunASREngine()
    else:
        raise ValueError(f"不支持的 ASR 引擎: {name}")


# ============================================================
# 启动事件 - 预加载模型
# ============================================================
@app.on_event("startup")
async def startup_event():
    """启动时预加载模型"""
    global asr_engine, translator

    logger.info("=" * 50)
    logger.info("实时语音翻译服务启动中...")
    logger.info("=" * 50)

    # 初始化音频处理器
    audio_processor.init_vad()

    # 加载 ASR 引擎
    try:
        asr_engine = get_asr_engine()
        asr_engine.load_model()
        logger.info(f"ASR 引擎就绪: {asr_engine.name}")
    except Exception as e:
        logger.error(f"ASR 引擎加载失败: {e}")

    # 加载翻译模型
    try:
        translator = HyMT2Translator()
        translator.load_model()
        logger.info(f"翻译模型就绪: {translator.name}")
    except Exception as e:
        logger.error(f"翻译模型加载失败: {e}")

    logger.info("=" * 50)
    logger.info(f"服务已就绪: http://{config.HOST}:{config.PORT}")
    logger.info("=" * 50)


# ============================================================
# API 路由
# ============================================================
@app.get("/")
async def root():
    """服务首页"""
    frontend_dir = Path(__file__).parent.parent / "frontend"
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>实时语音翻译服务</h1><p>前端文件未找到</p>")


@app.get("/api/status")
async def status():
    """服务状态"""
    whisper_model_size = None
    if asr_engine and hasattr(asr_engine, '_model_size'):
        whisper_model_size = asr_engine._model_size

    return {
        "status": "ok",
        "asr": {
            "engine": asr_engine.name if asr_engine else None,
            "loaded": asr_engine.is_loaded() if asr_engine else False,
            "whisper_model_size": whisper_model_size,
            "whisper_model_mode": config.WHISPER_MODEL_MODE,
        },
        "translator": {
            "model": translator.name if translator else None,
            "loaded": translator.is_loaded() if translator else False,
        },
        "languages": config.LANGUAGE_MAP,
    }


@app.get("/api/config")
async def get_config():
    """获取当前配置"""
    whisper_info = {}
    if asr_engine and isinstance(asr_engine, WhisperEngine):
        whisper_info = {
            "whisper_model_size": asr_engine._model_size,
            "whisper_model_mode": config.WHISPER_MODEL_MODE,
            "whisper_models": WhisperEngine.get_available_models(),
            "whisper_auto_recommendation": WhisperEngine.get_auto_recommendation(),
        }

    return {
        "asr_engine": config.ASR_ENGINE,
        "source_lang": config.DEFAULT_SOURCE_LANG,
        "target_lang": config.DEFAULT_TARGET_LANG,
        "languages": config.LANGUAGE_MAP,
        "audio_chunk_duration": config.AUDIO_CHUNK_DURATION,
        **whisper_info,
    }


@app.post("/api/config")
async def update_config(data: dict):
    """更新配置（运行时切换）"""
    global asr_engine

    if "asr_engine" in data:
        new_engine = data["asr_engine"]
        if new_engine != config.ASR_ENGINE:
            config.ASR_ENGINE = new_engine
            try:
                asr_engine = get_asr_engine(new_engine)
                asr_engine.load_model()
                logger.info(f"ASR 引擎切换为: {asr_engine.name}")
            except Exception as e:
                logger.error(f"ASR 引擎切换失败: {e}")
                return {"error": str(e)}

    # 切换 Whisper 模型大小
    if "whisper_model_size" in data and isinstance(asr_engine, WhisperEngine):
        new_size = data["whisper_model_size"]
        if new_size in config.WHISPER_MODELS:
            try:
                asr_engine.switch_model(new_size)
                logger.info(f"Whisper 模型切换为: {new_size}")
            except Exception as e:
                logger.error(f"Whisper 模型切换失败: {e}")
                return {"error": str(e)}
        else:
            return {"error": f"不支持的 Whisper 模型: {new_size}"}

    # 切换 Whisper 模式 (auto/manual)
    if "whisper_model_mode" in data:
        mode = data["whisper_model_mode"]
        if mode in ("auto", "manual"):
            config.WHISPER_MODEL_MODE = mode
            if mode == "auto" and isinstance(asr_engine, WhisperEngine):
                recommended = WhisperEngine.get_auto_recommendation()
                if recommended != asr_engine._model_size:
                    try:
                        asr_engine.switch_model(recommended)
                        logger.info(f"自动模式切换 Whisper 模型为: {recommended}")
                    except Exception as e:
                        logger.warning(f"自动切换失败，保持当前模型: {e}")

    if "source_lang" in data:
        config.DEFAULT_SOURCE_LANG = data["source_lang"]
    if "target_lang" in data:
        config.DEFAULT_TARGET_LANG = data["target_lang"]

    return {"status": "ok"}


# ============================================================
# WebSocket 端点 - 实时语音翻译
# ============================================================
@app.websocket("/ws/translate")
async def websocket_translate(websocket: WebSocket):
    global asr_engine, translator

    """
    实时语音翻译 WebSocket

    协议：
    - 客户端发送：音频数据（binary）或控制消息（text JSON）
    - 服务端返回：翻译结果（text JSON）

    控制消息格式：
    {
        "type": "config",
        "source_lang": "zh",
        "target_lang": "en",
        "asr_engine": "whisper"
    }

    结果消息格式：
    {
        "type": "result",
        "original": "识别的原文",
        "translated": "翻译结果",
        "source_lang": "zh",
        "target_lang": "en",
        "timestamp": 1234567890.123,
        "latency_ms": 150.5
    }

    错误消息格式：
    {
        "type": "error",
        "message": "错误信息"
    }
    """
    await websocket.accept()
    logger.info("WebSocket 客户端已连接")

    # 当前会话配置
    source_lang = config.DEFAULT_SOURCE_LANG
    target_lang = config.DEFAULT_TARGET_LANG

    # 上一次识别的文本，用于去重
    last_recognized_text = ""

    try:
        while True:
            message = await websocket.receive()

            if "text" in message:
                # 控制消息
                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")

                    if msg_type == "config":
                        source_lang = data.get("source_lang", source_lang)
                        target_lang = data.get("target_lang", target_lang)

                        # 切换 ASR 引擎
                        if "asr_engine" in data:
                            new_engine = data["asr_engine"]
                            if new_engine != config.ASR_ENGINE:
                                try:
                                    asr_engine = get_asr_engine(new_engine)
                                    asr_engine.load_model()
                                    config.ASR_ENGINE = new_engine
                                except Exception as e:
                                    await websocket.send_json({
                                        "type": "error",
                                        "message": f"ASR 引擎切换失败: {e}",
                                    })

                        # 切换 Whisper 模型大小
                        if "whisper_model_size" in data and isinstance(asr_engine, WhisperEngine):
                            new_size = data["whisper_model_size"]
                            if new_size in config.WHISPER_MODELS:
                                try:
                                    asr_engine.switch_model(new_size)
                                    logger.info(f"Whisper 模型切换为: {new_size}")
                                except Exception as e:
                                    await websocket.send_json({
                                        "type": "error",
                                        "message": f"Whisper 模型切换失败: {e}",
                                    })

                        # 切换 Whisper 模式
                        if "whisper_model_mode" in data:
                            mode = data["whisper_model_mode"]
                            if mode in ("auto", "manual"):
                                config.WHISPER_MODEL_MODE = mode

                        whisper_size = asr_engine._model_size if isinstance(asr_engine, WhisperEngine) else None
                        await websocket.send_json({
                            "type": "config_updated",
                            "source_lang": source_lang,
                            "target_lang": target_lang,
                            "asr_engine": config.ASR_ENGINE,
                            "whisper_model_size": whisper_size,
                            "whisper_model_mode": config.WHISPER_MODEL_MODE,
                        })
                        logger.info(f"配置更新: {source_lang} -> {target_lang}")

                    elif msg_type == "ping":
                        await websocket.send_json({"type": "pong"})

                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "message": "无效的 JSON 格式",
                    })

            elif "bytes" in message:
                # 音频数据（每个消息 = 一个完整的 webm 文件，含 init 段 + 音频数据）
                audio_bytes = message["bytes"]
                start_time = time.time()

                try:
                    # 1. 解码音频
                    audio_data = audio_processor.decode_audio(
                        audio_bytes, source_format="webm"
                    )

                    if len(audio_data) == 0:
                        continue

                    # 2. 语音识别
                    if asr_engine is None or not asr_engine.is_loaded():
                        await websocket.send_json({
                            "type": "error",
                            "message": "ASR 引擎未就绪",
                        })
                        continue

                    recognized_text = asr_engine.transcribe(
                        audio_data,
                        sample_rate=config.AUDIO_SAMPLE_RATE,
                        language=source_lang,
                    )

                    if not recognized_text:
                        continue

                    # 去重：如果识别结果和上次完全相同，跳过
                    if recognized_text == last_recognized_text:
                        continue

                    last_recognized_text = recognized_text

                    # 3. 翻译
                    if translator is None or not translator.is_loaded():
                        await websocket.send_json({
                            "type": "error",
                            "message": "翻译模型未就绪",
                        })
                        continue

                    translated_text = translator.translate(
                        recognized_text,
                        source_lang=source_lang,
                        target_lang=target_lang,
                    )

                    # 4. 返回结果
                    latency = (time.time() - start_time) * 1000

                    await websocket.send_json({
                        "type": "result",
                        "original": recognized_text,
                        "translated": translated_text,
                        "source_lang": source_lang,
                        "target_lang": target_lang,
                        "timestamp": time.time(),
                        "latency_ms": round(latency, 1),
                    })

                    logger.info(
                        f"[{source_lang}→{target_lang}] "
                        f"{recognized_text} => {translated_text} "
                        f"({latency:.0f}ms)"
                    )

                except Exception as e:
                    logger.error(f"处理音频失败: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                    })

    except WebSocketDisconnect:
        logger.info("WebSocket 客户端已断开")
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")


# ============================================================
# 静态文件服务
# ============================================================
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.DEBUG,
        log_level="info",
    )
