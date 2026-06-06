/**
 * 实时语音翻译 - 主应用
 * WebSocket 连接管理、录音控制、UI 交互
 */

(function () {
    'use strict';

    // ============================================================
    // DOM 元素
    // ============================================================
    const elements = {
        statusDot: document.getElementById('statusDot'),
        statusText: document.getElementById('statusText'),
        sourceLang: document.getElementById('sourceLang'),
        targetLang: document.getElementById('targetLang'),
        asrEngine: document.getElementById('asrEngine'),
        swapBtn: document.getElementById('swapBtn'),
        recordBtn: document.getElementById('recordBtn'),
        recordIcon: document.getElementById('recordIcon'),
        recordText: document.getElementById('recordText'),
        visualizerCanvas: document.getElementById('visualizerCanvas'),
        statCount: document.getElementById('statCount'),
        statLatency: document.getElementById('statLatency'),
        // Whisper 模型切换
        whisperModelSection: document.getElementById('whisperModelSection'),
        modeAuto: document.getElementById('modeAuto'),
        modeManual: document.getElementById('modeManual'),
        whisperAutoInfo: document.getElementById('whisperAutoInfo'),
        whisperAutoBadge: document.getElementById('whisperAutoBadge'),
        whisperAutoDesc: document.getElementById('whisperAutoDesc'),
        whisperModelSize: document.getElementById('whisperModelSize'),
        // 音频输入源
        sourceMic: document.getElementById('sourceMic'),
        sourceSystem: document.getElementById('sourceSystem'),
        audioSourceHint: document.getElementById('audioSourceHint'),
    };

    // ============================================================
    // 状态
    // ============================================================
    let ws = null;
    let isRecording = false;
    let reconnectTimer = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 10;
    let whisperModelMode = 'auto'; // 'auto' 或 'manual'

    // ============================================================
    // 初始化组件
    // ============================================================
    const subtitleManager = new SubtitleManager('subtitleArea');

    const recorder = new AudioRecorder({
        chunkInterval: 3000,
        onAudioData: (blob) => {
            // 音频块准备好后通过 WebSocket 发送
            if (ws && ws.readyState === WebSocket.OPEN) {
                blob.arrayBuffer().then(buffer => {
                    ws.send(buffer);
                });
            }
        },
        onVolumeChange: (volume, frequencyData) => {
            drawVisualizer(frequencyData);
        },
        onError: (err) => {
            console.error('录音错误:', err);
            showToast('录音错误: ' + err.message, 'error');
        },
    });

    // ============================================================
    // WebSocket 连接
    // ============================================================
    function connect() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${location.host}/ws/translate`;

        ws = new WebSocket(wsUrl);
        ws.binaryType = 'arraybuffer';

        ws.onopen = () => {
            console.log('WebSocket 已连接');
            updateStatus('connected', '已连接');
            reconnectAttempts = 0;

            // 发送当前配置
            sendConfig();
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleMessage(data);
            } catch (e) {
                console.error('解析消息失败:', e);
            }
        };

        ws.onclose = () => {
            console.log('WebSocket 已断开');
            updateStatus('disconnected', '已断开');

            // 自动重连
            if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
                const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 10000);
                reconnectTimer = setTimeout(() => {
                    reconnectAttempts++;
                    connect();
                }, delay);
            }
        };

        ws.onerror = (err) => {
            console.error('WebSocket 错误:', err);
        };
    }

    function sendConfig() {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        const config = {
            type: 'config',
            source_lang: elements.sourceLang.value,
            target_lang: elements.targetLang.value,
            asr_engine: elements.asrEngine.value,
        };

        // Whisper 模型配置
        if (elements.asrEngine.value === 'whisper') {
            config.whisper_model_mode = whisperModelMode;
            if (whisperModelMode === 'manual') {
                config.whisper_model_size = elements.whisperModelSize.value;
            }
        }

        ws.send(JSON.stringify(config));
    }

    function handleMessage(data) {
        switch (data.type) {
            case 'result':
                // 添加字幕
                subtitleManager.add(
                    data.original,
                    data.translated,
                    data.source_lang,
                    data.target_lang,
                    data.latency_ms
                );

                // 更新统计
                updateStats();
                break;

            case 'config_updated':
                console.log('配置已更新:', data);
                // 更新 Whisper 模型信息
                if (data.whisper_model_size) {
                    updateWhisperModelDisplay(data.whisper_model_size, data.whisper_model_mode);
                }
                break;

            case 'error':
                console.error('服务端错误:', data.message);
                showToast('错误: ' + data.message, 'error');
                break;

            case 'pong':
                break;
        }
    }

    // ============================================================
    // 录音控制
    // ============================================================
    async function toggleRecording() {
        if (isRecording) {
            stopRecording();
        } else {
            await startRecording();
        }
    }

    async function startRecording() {
        const ok = await recorder.start();
        if (!ok) {
            // 用户取消选择屏幕时静默处理，其他错误已在 recorder.onError 中 showToast
            return;
        }

        isRecording = true;
        elements.recordBtn.classList.add('recording');
        elements.recordIcon.textContent = '⏹';
        elements.recordText.textContent = '点击停止';

        // 禁用音频源切换
        elements.sourceMic.disabled = true;
        elements.sourceSystem.disabled = true;

        // 启动定时发送
        startChunkSender();
    }

    function stopRecording() {
        isRecording = false;
        recorder.stop();
        elements.recordBtn.classList.remove('recording');

        // 恢复图标
        elements.recordIcon.textContent = currentAudioSource === 'system' ? '🔊' : '🎤';
        elements.recordText.textContent = '按住说话';

        // 启用音频源切换
        elements.sourceMic.disabled = false;
        elements.sourceSystem.disabled = false;

        // 停止定时发送
        stopChunkSender();

        // 发送最后一块
        const lastChunk = recorder.flushChunks();
        if (lastChunk && ws && ws.readyState === WebSocket.OPEN) {
            lastChunk.arrayBuffer().then(buffer => {
                ws.send(buffer);
            });
        }
    }

    // ============================================================
    // 定时发送音频块
    // ============================================================
    let chunkSenderTimer = null;

    function startChunkSender() {
        stopChunkSender();

        chunkSenderTimer = setInterval(() => {
            if (!isRecording) return;

            const blob = recorder.flushChunks();
            if (blob && ws && ws.readyState === WebSocket.OPEN) {
                blob.arrayBuffer().then(buffer => {
                    ws.send(buffer);
                });
            }
        }, 3000); // 每 3 秒发送一块
    }

    function stopChunkSender() {
        if (chunkSenderTimer) {
            clearInterval(chunkSenderTimer);
            chunkSenderTimer = null;
        }
    }

    // ============================================================
    // 音频可视化
    // ============================================================
    const canvasCtx = elements.visualizerCanvas.getContext('2d');

    function drawVisualizer(frequencyData) {
        const canvas = elements.visualizerCanvas;
        const width = canvas.width;
        const height = canvas.height;

        canvasCtx.fillStyle = getComputedStyle(document.documentElement)
            .getPropertyValue('--bg-secondary').trim();
        canvasCtx.fillRect(0, 0, width, height);

        if (!frequencyData) return;

        const barCount = 32;
        const barWidth = width / barCount - 2;
        const step = Math.floor(frequencyData.length / barCount);

        for (let i = 0; i < barCount; i++) {
            const value = frequencyData[i * step] / 255;
            const barHeight = value * height * 0.8;

            const gradient = canvasCtx.createLinearGradient(0, height, 0, height - barHeight);
            gradient.addColorStop(0, '#00d4ff');
            gradient.addColorStop(1, '#7b68ee');

            canvasCtx.fillStyle = gradient;
            canvasCtx.fillRect(
                i * (barWidth + 2),
                height - barHeight,
                barWidth,
                barHeight
            );
        }
    }

    // ============================================================
    // UI 更新
    // ============================================================
    function updateStatus(state, text) {
        elements.statusDot.className = 'status-dot' + (state === 'connected' ? ' connected' : '');
        elements.statusText.textContent = text;
    }

    function updateStats() {
        const count = subtitleManager.getCount();
        const latency = subtitleManager.getLastLatency();
        elements.statCount.textContent = `翻译: ${count} 条`;
        elements.statLatency.textContent = `延迟: ${latency || '-'} ms`;
    }

    function showToast(message, type) {
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
            padding: 12px 24px; border-radius: 8px; z-index: 1000;
            font-size: 0.9rem; color: #fff;
            background: ${type === 'error' ? '#ff4757' : type === 'info' ? '#1e90ff' : '#2ed573'};
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            animation: slideIn 0.3s ease-out;
        `;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // ============================================================
    // Whisper 模型切换 UI
    // ============================================================
    function updateWhisperModelDisplay(modelSize, mode) {
        const modelInfo = {
            tiny:   { params: '39M',   desc: '速度优先，精度较低' },
            base:   { params: '74M',   desc: '速度与精度平衡（默认）' },
            small:  { params: '244M',  desc: '较好的识别精度' },
            medium: { params: '769M',  desc: '高精度识别' },
            large:  { params: '1550M', desc: '最高精度，需要较大显存' },
        };

        const info = modelInfo[modelSize] || modelInfo.base;

        if (mode === 'auto') {
            whisperModelMode = 'auto';
            elements.modeAuto.classList.add('active');
            elements.modeManual.classList.remove('active');
            elements.whisperAutoInfo.style.display = 'flex';
            elements.whisperModelSize.style.display = 'none';
            elements.whisperAutoBadge.textContent = modelSize;
            elements.whisperAutoDesc.textContent = `自动推荐 (${info.params}) — ${info.desc}`;
        } else {
            whisperModelMode = 'manual';
            elements.modeAuto.classList.remove('active');
            elements.modeManual.classList.add('active');
            elements.whisperAutoInfo.style.display = 'none';
            elements.whisperModelSize.style.display = 'block';
            elements.whisperModelSize.value = modelSize;
        }

        // 控制整个区域的显示/隐藏（只有 whisper 引擎时显示）
        const isWhisper = elements.asrEngine.value === 'whisper';
        elements.whisperModelSection.style.display = isWhisper ? 'block' : 'none';
    }

    function fetchWhisperConfig() {
        fetch('/api/config')
            .then(r => r.json())
            .then(data => {
                if (data.whisper_model_size) {
                    updateWhisperModelDisplay(data.whisper_model_size, data.whisper_model_mode || 'auto');
                }
            })
            .catch(err => console.error('获取配置失败:', err));
    }

    // ============================================================
    // 事件绑定
    // ============================================================
    elements.recordBtn.addEventListener('click', toggleRecording);

    elements.swapBtn.addEventListener('click', () => {
        const src = elements.sourceLang.value;
        const tgt = elements.targetLang.value;
        elements.sourceLang.value = tgt;
        elements.targetLang.value = src;
        sendConfig();
    });

    elements.sourceLang.addEventListener('change', sendConfig);
    elements.targetLang.addEventListener('change', sendConfig);
    elements.asrEngine.addEventListener('change', () => {
        const isWhisper = elements.asrEngine.value === 'whisper';
        elements.whisperModelSection.style.display = isWhisper ? 'block' : 'none';
        sendConfig();
    });

    // Whisper 模式切换
    elements.modeAuto.addEventListener('click', () => {
        whisperModelMode = 'auto';
        updateWhisperModelDisplay(elements.whisperAutoBadge.textContent || 'base', 'auto');
        sendConfig();
    });

    elements.modeManual.addEventListener('click', () => {
        whisperModelMode = 'manual';
        updateWhisperModelDisplay(elements.whisperModelSize.value || 'base', 'manual');
        sendConfig();
    });

    elements.whisperModelSize.addEventListener('change', () => {
        if (whisperModelMode === 'manual') {
            sendConfig();
        }
    });

    // 键盘快捷键：空格键录音
    document.addEventListener('keydown', (e) => {
        if (e.code === 'Space' && e.target === document.body) {
            e.preventDefault();
            toggleRecording();
        }
    });

    // ============================================================
    // 音频输入源切换
    // ============================================================
    let currentAudioSource = 'microphone';

    function switchAudioSource(source) {
        if (isRecording) {
            showToast('请先停止录音再切换音频源', 'error');
            return;
        }

        currentAudioSource = source;

        // 更新按钮状态
        elements.sourceMic.classList.toggle('active', source === 'microphone');
        elements.sourceSystem.classList.toggle('active', source === 'system');

        // 更新录音器
        recorder.setSource(source);

        // 更新提示文字和录音按钮图标
        if (source === 'system') {
            elements.audioSourceHint.textContent = '点击录音后选择要共享的屏幕或标签页，记得勾选「共享音频」';
            elements.audioSourceHint.className = 'audio-source-hint';
            elements.recordIcon.textContent = '🔊';
        } else {
            elements.audioSourceHint.textContent = '';
            elements.audioSourceHint.className = 'audio-source-hint';
            elements.recordIcon.textContent = '🎤';
        }
    }

    // 系统声音共享结束时自动停止
    recorder.onSystemAudioEnded = () => {
        stopRecording();
        showToast('屏幕共享已结束', 'info');
    };

    // 音频源按钮事件
    elements.sourceMic.addEventListener('click', () => switchAudioSource('microphone'));
    elements.sourceSystem.addEventListener('click', () => switchAudioSource('system'));

    // ============================================================
    // 启动
    // ============================================================
    connect();
    fetchWhisperConfig();

})();
