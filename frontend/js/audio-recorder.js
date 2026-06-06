/**
 * 音频录制器
 * 负责麦克风采集、浏览器端 VAD、音频分块发送
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

        this._chunkTimer = null;
        this._analyseTimer = null;
    }

    /**
     * 请求麦克风权限并开始录音
     */
    async start() {
        try {
            // 请求麦克风
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: this.sampleRate,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            });

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
