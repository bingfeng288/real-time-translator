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

        // 保存 webm 初始化段（文件头），后续每个分片都需要带上它才能被 ffmpeg 解码
        this._initSegment = null;
        this._chunkIndex = 0;
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
     *
     * 浏览器会弹出一个选择框，让用户选择共享哪个屏幕/标签页，
     * 用户需要勾选"共享音频"选项。
     * macOS 注意：系统设置 → 声音 → 输出 不能设为 BlackHole 等虚拟设备，
     *            需要是实际的扬声器/耳机，否则 getDisplayMedia 可能采集不到。
     */
    async _startSystemAudio() {
        // getDisplayMedia 必须同时请求视频（浏览器规范要求），
        // 我们拿到流后丢弃视频轨道，只保留音频。
        const displayStream = await navigator.mediaDevices.getDisplayMedia({
            video: {
                // 使用最小分辨率，减少性能开销
                width: 1,
                height: 1,
                frameRate: 1,
            },
            audio: {
                sampleRate: this.sampleRate,
                channelCount: 1,
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
            },
        });

        // 检查是否包含音频轨道
        const audioTracks = displayStream.getAudioTracks();
        if (audioTracks.length === 0) {
            // 用户没有勾选"共享音频"
            displayStream.getTracks().forEach(t => t.stop());
            throw new Error(
                '未检测到音频。请在共享时勾选「共享音频」选项。\n' +
                '提示：选择共享"标签页"效果最佳。'
            );
        }

        // 丢弃视频轨道，只保留音频
        displayStream.getVideoTracks().forEach(t => t.stop());

        // 用纯音频轨道创建新流
        this.stream = new MediaStream(audioTracks);

        // 监听用户通过浏览器 UI 停止共享
        audioTracks[0].addEventListener('ended', () => {
            if (this.isRecording) {
                this.onError(new Error('共享已结束'));
                // 触发停止
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
            this._initSegment = null;
            this._chunkIndex = 0;
            this._headerSent = false;

            this.mediaRecorder.ondataavailable = async (e) => {
                if (e.data.size > 0) {
                    if (!this._headerSent) {
                        // 第一个分片 = 文件头 + 少量音频，整个作为初始化段
                        this._initSegment = await e.data.arrayBuffer();
                        this._headerSent = true;
                        console.log(`[AudioRecorder] 初始化段: ${this._initSegment.byteLength} bytes`);
                    } else {
                        // 后续分片：只保存增量数据
                        this.chunks.push(e.data);
                    }
                }
            };

            // 每 chunkInterval 毫秒触发一次 ondataavailable
            this.mediaRecorder.start(this.chunkInterval);
            this.isRecording = true;

            // 开始音量分析
            this._startVolumeAnalysis();

            return true;

        } catch (err) {
            // 用户取消选择屏幕时不报错
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
    }

    /**
     * 获取当前音频块并发送
     * 第一次返回完整初始化段（含文件头+首段音频）
     * 后续每次返回 初始化段 + 新增音频增量
     */
    flushChunks() {
        // 根据音频源选择 VAD 阈值
        const threshold = this.audioSource === 'system' ? this._systemVadThreshold : this.vadThreshold;
        const volume = this._currentVolume || 0;

        this._chunkIndex++;

        // 第一次 flush：发送初始化段（它已经包含首段音频）
        if (this._chunkIndex === 1 && this._initSegment) {
            const blob = new Blob([this._initSegment], { type: this._getSupportedMimeType() });
            console.log(`[AudioRecorder] flush #1 (init): vol=${volume.toFixed(4)}, size=${blob.size}`);
            return blob;
        }

        // 后续 flush：发送 init + 新增增量
        const newChunkCount = this.chunks.length;
        if (newChunkCount === 0) return null;

        const rawBlob = new Blob(this.chunks, { type: this._getSupportedMimeType() });
        this.chunks = []; // 清空，下次只拿新增的

        // 拼接初始化段确保格式完整
        const finalBlob = this._initSegment
            ? new Blob([this._initSegment, rawBlob], { type: rawBlob.type })
            : rawBlob;

        console.log(`[AudioRecorder] flush #${this._chunkIndex}: newChunks=${newChunkCount}, vol=${volume.toFixed(4)}, size=${finalBlob.size}`);

        if (volume > threshold) {
            return finalBlob;
        }

        console.log(`[AudioRecorder] 音量过低，跳过`);
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
