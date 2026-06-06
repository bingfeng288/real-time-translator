/**
 * 音频录制器
 * 负责麦克风 / 系统声音采集、浏览器端 VAD、音频分块发送
 */

class AudioRecorder {
    constructor(options = {}) {
        this.sampleRate = options.sampleRate || 16000;
        this.chunkInterval = options.chunkInterval || 3000;
        this.vadThreshold = options.vadThreshold || 0.01;

        this.mediaRecorder = null;
        this.audioContext = null;
        this.analyser = null;
        this.stream = null;
        this.isRecording = false;
        this.chunks = [];
        this.onAudioData = options.onAudioData || (() => {});
        this.onVolumeChange = options.onVolumeChange || (() => {});
        this.onError = options.onError || (() => {});

        this.audioSource = options.audioSource || 'microphone';
        this._analyseTimer = null;
        this._systemVadThreshold = 0.002;

        // webm 头部（不含音频 Cluster），用于初始化后端解码器
        this._webmHeader = null;
        this._headerSent = false;
    }

    setSource(source) {
        if (this.isRecording) {
            this.onError(new Error('请先停止录音再切换音频源'));
            return;
        }
        this.audioSource = source;
    }

    async _startMicrophone() {
        this.stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: this.sampleRate, channelCount: 1,
                echoCancellation: true, noiseSuppression: true, autoGainControl: true,
            },
        });
    }

    async _startSystemAudio() {
        const displayStream = await navigator.mediaDevices.getDisplayMedia({
            video: { width: 1, height: 1, frameRate: 1 },
            audio: {
                sampleRate: this.sampleRate, channelCount: 1,
                echoCancellation: false, noiseSuppression: false, autoGainControl: false,
            },
        });

        const audioTracks = displayStream.getAudioTracks();
        if (audioTracks.length === 0) {
            displayStream.getTracks().forEach(t => t.stop());
            throw new Error('未检测到音频。请在共享时勾选「共享音频」选项。');
        }

        displayStream.getVideoTracks().forEach(t => t.stop());
        this.stream = new MediaStream(audioTracks);

        audioTracks[0].addEventListener('ended', () => {
            if (this.isRecording) {
                this.onError(new Error('共享已结束'));
                if (typeof this.onSystemAudioEnded === 'function') this.onSystemAudioEnded();
            }
        });
    }

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

            this.mediaRecorder = new MediaRecorder(this.stream, {
                mimeType: this._getSupportedMimeType(),
                audioBitsPerSecond: 16000,
            });

            this.chunks = [];
            this._webmHeader = null;
            this._headerSent = false;

            this.mediaRecorder.ondataavailable = async (e) => {
                if (e.data.size > 0) {
                    if (!this._webmHeader) {
                        // 第一个分片：提取 webm 头部（到第一个 Cluster 之前）
                        const buffer = await e.data.arrayBuffer();
                        const headerEnd = this._findClusterStart(buffer);
                        if (headerEnd > 0) {
                            this._webmHeader = buffer.slice(0, headerEnd);
                            // 剩余部分是音频数据，保存为 chunk
                            const audioData = buffer.slice(headerEnd);
                            if (audioData.byteLength > 0) {
                                this.chunks.push(new Blob([audioData], { type: e.data.type }));
                            }
                        } else {
                            // 找不到 Cluster，整个作为 header
                            this._webmHeader = buffer;
                        }
                    } else {
                        this.chunks.push(e.data);
                    }
                }
            };

            this.mediaRecorder.start(this.chunkInterval);
            this.isRecording = true;
            this._startVolumeAnalysis();
            return true;

        } catch (err) {
            if (err.name === 'NotAllowedError') return false;
            this.onError(err);
            return false;
        }
    }

    /**
     * 查找 webm 中第一个 Cluster 元素的起始位置
     * Cluster element ID = 0x1F43B675
     */
    _findClusterStart(buffer) {
        const bytes = new Uint8Array(buffer);
        for (let i = 0; i < bytes.length - 3; i++) {
            if (bytes[i] === 0x1F && bytes[i+1] === 0x43 && bytes[i+2] === 0xB6 && bytes[i+3] === 0x75) {
                return i;
            }
        }
        return -1;
    }

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
        this._webmHeader = null;
        this._headerSent = false;
    }

    /**
     * 获取待发送的音频数据
     * 第一次返回：{ type: 'init', data: webmHeader }
     * 后续返回：{ type: 'audio', data: audioChunks }
     */
    flushChunks() {
        const threshold = this.audioSource === 'system' ? this._systemVadThreshold : this.vadThreshold;
        const volume = this._currentVolume || 0;

        // 第一次：发送 webm 头部
        if (!this._headerSent && this._webmHeader) {
            this._headerSent = true;
            return { type: 'init', data: new Blob([this._webmHeader]) };
        }

        // 后续：只发送新增的音频 chunks
        const newChunks = this.chunks.splice(0);
        if (newChunks.length === 0) return null;

        if (volume > threshold) {
            return { type: 'audio', data: new Blob(newChunks) };
        }

        return null;
    }

    _getSupportedMimeType() {
        const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
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

    getVolume() { return this._currentVolume || 0; }
}

window.AudioRecorder = AudioRecorder;
