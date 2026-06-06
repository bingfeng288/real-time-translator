/**
 * 音频录制器
 * 负责麦克风 / 系统声音采集、浏览器端 VAD、音频分块发送
 *
 * 系统声音采集方案：
 *   使用浏览器原生 getDisplayMedia API，用户选择"共享标签页"或"共享屏幕"并勾选"共享音频"
 *   零安装零配置，Chrome / Edge / Firefox 均支持
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

        this._chunkTimer = null;
        this._analyseTimer = null;

        // 系统音频音量通常较低，使用更低的 VAD 阈值
        this._systemVadThreshold = 0.002;

        // 保存 webm 初始化段（文件头），每次发送时拼接
        this._initSegment = null;
    }

    /**
     * 设置音频输入源
     * @param {'microphone'|'system'} source
     */
    setSource(source) {
        if (this.isRecording) {
            this.onError(new Error('请先停止录音再切换音频源'));
            return;
        }
        this.audioSource = source;
    }

    /**
     * 麦克风录音（getUserMedia）
     */
    async _startMicrophone() {
        this.stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: this.sampleRate,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            },
        });
    }

    /**
     * 系统声音录音（getDisplayMedia + 只保留音频轨道）
     */
    async _startSystemAudio() {
        const displayStream = await navigator.mediaDevices.getDisplayMedia({
            video: { width: 1, height: 1, frameRate: 1 },
            audio: {
                sampleRate: this.sampleRate,
                channelCount: 1,
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
            },
        });

        const audioTracks = displayStream.getAudioTracks();
        if (audioTracks.length === 0) {
            displayStream.getTracks().forEach(t => t.stop());
            throw new Error(
                '未检测到音频。请在共享时勾选「共享音频」选项。\n' +
                '提示：选择共享"标签页"效果最佳。'
            );
        }

        displayStream.getVideoTracks().forEach(t => t.stop());
        this.stream = new MediaStream(audioTracks);

        audioTracks[0].addEventListener('ended', () => {
            if (this.isRecording) {
                this.onError(new Error('共享已结束'));
                if (typeof this.onSystemAudioEnded === 'function') {
                    this.onSystemAudioEnded();
                }
            }
        });
    }

    /**
     * 开始录音
     */
    async start() {
        try {
            if (this.audioSource === 'system') {
                await this._startSystemAudio();
            } else {
                await this._startMicrophone();
            }

            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const source = this.audioContext.createMediaStreamSource(this.stream);
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 256;
            source.connect(this.analyser);

            const mimeType = this._getSupportedMimeType();
            this.mediaRecorder = new MediaRecorder(this.stream, {
                mimeType: mimeType,
                audioBitsPerSecond: 16000,
            });

            this.chunks = [];
            this._initSegment = null;

            this.mediaRecorder.ondataavailable = async (e) => {
                if (e.data.size > 0) {
                    // 第一个分片包含 webm 文件头，保存它
                    if (this._initSegment === null) {
                        this._initSegment = await e.data.arrayBuffer();
                    }
                    this.chunks.push(e.data);
                }
            };

            this.mediaRecorder.start(this.chunkInterval);
            this.isRecording = true;
            this._startVolumeAnalysis();

            return true;

        } catch (err) {
            if (err.name === 'NotAllowedError') {
                return false;
            }
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
        this._initSegment = null;
    }

    /**
     * 获取当前音频块并发送
     * 每次都拼接 initSegment + 新增 chunks，形成完整的 webm 文件
     */
    flushChunks() {
        const threshold = this.audioSource === 'system' ? this._systemVadThreshold : this.vadThreshold;
        const volume = this._currentVolume || 0;

        if (this.chunks.length === 0) return null;

        // 拼接所有新增 chunk
        const rawBlob = new Blob(this.chunks, { type: this._getSupportedMimeType() });
        this.chunks = [];

        // 拼接初始化段，形成完整可解码的 webm
        let finalBlob;
        if (this._initSegment) {
            finalBlob = new Blob([this._initSegment, rawBlob], { type: rawBlob.type });
        } else {
            finalBlob = rawBlob;
        }

        if (volume > threshold) {
            return finalBlob;
        }

        return null;
    }

    _getSupportedMimeType() {
        const types = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/ogg;codecs=opus',
            'audio/mp4',
        ];
        for (const type of types) {
            if (MediaRecorder.isTypeSupported(type)) return type;
        }
        return '';
    }

    _startVolumeAnalysis() {
        this._currentVolume = 0;
        const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
        const analyse = () => {
            if (!this.isRecording) return;
            this.analyser.getByteFrequencyData(dataArray);
            let sum = 0;
            for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
            this._currentVolume = sum / dataArray.length / 255;
            this.onVolumeChange(this._currentVolume, dataArray);
            this._analyseTimer = requestAnimationFrame(analyse);
        };
        analyse();
    }

    getVolume() {
        return this._currentVolume || 0;
    }
}

window.AudioRecorder = AudioRecorder;
