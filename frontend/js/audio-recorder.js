/**
 * 音频录制器
 * 负责麦克风 / 系统声音采集、浏览器端 VAD、音频分块发送
 *
 * 系统声音采集需要安装虚拟音频设备：
 *   macOS: BlackHole (brew install blackhole-2ch) 或 LoopBack
 *   Windows: VB-Audio Virtual Cable
 *   Linux: PulseAudio monitor
 */

class AudioRecorder {
    constructor(options = {}) {
        this.sampleRate = options.sampleRate || 16000;
        this.chunkInterval = options.chunkInterval || 3000; // 3秒一块
        this.vadThreshold = options.vadThreshold || 0.01;   // VAD 阈值

        this.mediaRecorder = null;
        this.audioContext = null;
        this.analyser = null;
        this.stream = null;
        this.isRecording = false;
        this.chunks = [];
        this.onAudioData = options.onAudioData || (() => {});
        this.onVolumeChange = options.onVolumeChange || (() => {});
        this.onError = options.onError || (() => {});

        // 音频输入源：'microphone' 或 'system'
        this.audioSource = options.audioSource || 'microphone';
        // 指定设备 ID（可选，优先级高于 audioSource）
        this.deviceId = options.deviceId || null;

        this._chunkTimer = null;
        this._analyseTimer = null;
    }

    /**
     * 枚举所有可用的音频输入设备
     * @returns {Promise<{microphones: [], systemAudios: [], all: []}>}
     */
    static async enumerateDevices() {
        try {
            // 先请求一次权限，否则部分浏览器不返回设备标签
            const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            tempStream.getTracks().forEach(t => t.stop());

            const devices = await navigator.mediaDevices.enumerateDevices();
            const audioInputs = devices.filter(d => d.kind === 'audioinput');

            // 系统声音设备的关键词
            const systemKeywords = [
                'blackhole', 'soundflower', 'loopback', 'virtual',
                'screen capture', 'screen capture', 'monitor',
                'stereo mix', 'what u hear', 'wave out mix',
                'vb-audio', 'cable output', 'cable input',
                'pulseaudio', 'pipewire',
            ];

            const microphones = [];
            const systemAudios = [];

            for (const device of audioInputs) {
                const label = (device.label || '').toLowerCase();
                const isSystem = systemKeywords.some(kw => label.includes(kw));

                const info = {
                    deviceId: device.deviceId,
                    label: device.label || `音频输入 ${microphones.length + systemAudios.length + 1}`,
                    group: device.groupId,
                };

                if (isSystem) {
                    systemAudios.push(info);
                } else {
                    microphones.push(info);
                }
            }

            return { microphones, systemAudios, all: audioInputs };

        } catch (err) {
            console.error('枚举音频设备失败:', err);
            return { microphones: [], systemAudios: [], all: [] };
        }
    }

    /**
     * 设置音频输入源
     * @param {'microphone'|'system'|string} source - 'microphone', 'system', 或具体 deviceId
     */
    setSource(source) {
        if (this.isRecording) {
            this.onError(new Error('请先停止录音再切换音频源'));
            return;
        }

        if (source === 'microphone' || source === 'system') {
            this.audioSource = source;
            this.deviceId = null;
        } else {
            // 指定 deviceId
            this.deviceId = source;
            this.audioSource = 'custom';
        }
    }

    /**
     * 获取音频流约束
     */
    _getAudioConstraints() {
        // 指定了具体设备 ID
        if (this.deviceId) {
            return {
                audio: {
                    deviceId: { exact: this.deviceId },
                    sampleRate: this.sampleRate,
                    channelCount: 1,
                },
            };
        }

        // 系统声音：不使用回声消除/降噪（会破坏系统音频质量）
        if (this.audioSource === 'system') {
            return {
                audio: {
                    sampleRate: this.sampleRate,
                    channelCount: 1,
                    echoCancellation: false,
                    noiseSuppression: false,
                    autoGainControl: false,
                },
            };
        }

        // 默认麦克风
        return {
            audio: {
                sampleRate: this.sampleRate,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            },
        };
    }

    /**
     * 开始录音
     */
    async start() {
        try {
            const constraints = this._getAudioConstraints();

            // 如果是系统声音且没有指定 deviceId，尝试自动查找虚拟音频设备
            if (this.audioSource === 'system' && !this.deviceId) {
                const devices = await AudioRecorder.enumerateDevices();
                if (devices.systemAudios.length > 0) {
                    constraints.audio.deviceId = { exact: devices.systemAudios[0].deviceId };
                } else {
                    this.onError(new Error(
                        '未检测到虚拟音频设备。\n' +
                        '请安装 BlackHole (macOS)、VB-Audio (Windows) 或配置 PulseAudio monitor (Linux)。\n' +
                        'macOS 安装: brew install blackhole-2ch'
                    ));
                    return false;
                }
            }

            this.stream = await navigator.mediaDevices.getUserMedia(constraints);

            // 创建 AudioContext 用于音量分析
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const source = this.audioContext.createMediaStreamSource(this.stream);
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 256;
            source.connect(this.analyser);

            // 使用 MediaRecorder 录制 webm/opus 格式
            const mimeType = this._getSupportedMimeType();
            this.mediaRecorder = new MediaRecorder(this.stream, {
                mimeType: mimeType,
                audioBitsPerSecond: 16000,
            });

            this.chunks = [];

            this.mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) {
                    this.chunks.push(e.data);
                }
            };

            // 每 chunkInterval 毫秒触发一次 ondataavailable
            this.mediaRecorder.start(this.chunkInterval);
            this.isRecording = true;

            // 开始音量分析
            this._startVolumeAnalysis();

            return true;

        } catch (err) {
            this.onError(err);
            return false;
        }
    }

    /**
     * 停止录音
     */
    stop() {
        this.isRecording = false;

        if (this._analyseTimer) {
            cancelAnimationFrame(this._analyseTimer);
            this._analyseTimer = null;
        }

        if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
            this.mediaRecorder.stop();
        }

        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
        }

        if (this.audioContext) {
            this.audioContext.close();
        }

        this.chunks = [];
    }

    /**
     * 获取当前音频块并发送
     */
    flushChunks() {
        if (this.chunks.length === 0) return null;

        const blob = new Blob(this.chunks, { type: this._getSupportedMimeType() });
        this.chunks = [];

        // 检测是否有声音（基于音量）
        if (this._currentVolume > this.vadThreshold) {
            return blob;
        }

        return null;
    }

    /**
     * 获取支持的 MIME 类型
     */
    _getSupportedMimeType() {
        const types = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/ogg;codecs=opus',
            'audio/mp4',
        ];

        for (const type of types) {
            if (MediaRecorder.isTypeSupported(type)) {
                return type;
            }
        }

        return ''; // 让浏览器选择默认
    }

    /**
     * 音量分析（用于可视化和 VAD）
     */
    _startVolumeAnalysis() {
        this._currentVolume = 0;
        const dataArray = new Uint8Array(this.analyser.frequencyBinCount);

        const analyse = () => {
            if (!this.isRecording) return;

            this.analyser.getByteFrequencyData(dataArray);

            // 计算平均音量 (0-1)
            let sum = 0;
            for (let i = 0; i < dataArray.length; i++) {
                sum += dataArray[i];
            }
            this._currentVolume = sum / dataArray.length / 255;

            this.onVolumeChange(this._currentVolume, dataArray);

            this._analyseTimer = requestAnimationFrame(analyse);
        };

        analyse();
    }

    /**
     * 获取当前音量
     */
    getVolume() {
        return this._currentVolume || 0;
    }
}

// 导出
window.AudioRecorder = AudioRecorder;
