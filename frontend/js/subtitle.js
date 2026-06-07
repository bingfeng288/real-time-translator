/**
 * 字幕管理器
 * 负责字幕条目的渲染和管理，支持画中画窗口同步
 */

class SubtitleManager {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.placeholder = document.getElementById('subtitlePlaceholder');
        this.items = [];
        this.maxItems = 100;

        // 画中画
        this._pipWindow = null;
        this._pipContainer = null;
        this._pipPlaceholder = null;
    }

    /**
     * 添加一条字幕
     */
    add(original, translated, sourceLang, targetLang, latencyMs) {
        if (this.placeholder) {
            this.placeholder.style.display = 'none';
        }

        const item = {
            id: Date.now(),
            original,
            translated,
            sourceLang,
            targetLang,
            latencyMs,
            timestamp: new Date(),
        };

        this.items.push(item);

        if (this.items.length > this.maxItems) {
            const removed = this.items.shift();
            const el = document.getElementById(`subtitle-${removed.id}`);
            if (el) el.remove();
            // PiP 中也移除
            const pipEl = document.getElementById(`pip-${removed.id}`);
            if (pipEl) pipEl.remove();
        }

        this._renderItem(item);
        this._renderPipItem(item);
        this._scrollToBottom();

        return item;
    }

    /**
     * 渲染主页面字幕（新内容插入到最上方）
     */
    _renderItem(item) {
        const div = document.createElement('div');
        div.className = 'subtitle-item';
        div.id = `subtitle-${item.id}`;

        const langNames = {
            zh: '中文', en: 'English', ja: '日本語',
            ko: '한국어', fr: 'Français', de: 'Deutsch',
            es: 'Español', ru: 'Русский',
        };

        div.innerHTML = `
            <div class="subtitle-original">${this._escapeHtml(item.original)}</div>
            <div class="subtitle-translated">${this._escapeHtml(item.translated)}</div>
            <div class="subtitle-meta">
                <span>${langNames[item.sourceLang] || item.sourceLang} → ${langNames[item.targetLang] || item.targetLang}</span>
                <span>${item.latencyMs}ms</span>
            </div>
        `;

        // 插入到占位文字之后（即最上方）
        if (this.placeholder && this.placeholder.nextSibling) {
            this.container.insertBefore(div, this.placeholder.nextSibling);
        } else {
            this.container.appendChild(div);
        }
    }

    /**
     * 渲染画中画窗口字幕（新内容插入到最上方）
     */
    _renderPipItem(item) {
        if (!this._pipContainer) return;

        // 隐藏占位文字
        if (this._pipPlaceholder) {
            this._pipPlaceholder.style.display = 'none';
        }

        const div = document.createElement('div');
        div.className = 'pip-item';
        div.id = `pip-${item.id}`;
        div.innerHTML = `
            <div class="pip-original">${this._escapeHtml(item.original)}</div>
            <div class="pip-translated">${this._escapeHtml(item.translated)}</div>
        `;

        // 插入到最上方
        if (this._pipContainer.firstChild) {
            this._pipContainer.insertBefore(div, this._pipContainer.firstChild);
        } else {
            this._pipContainer.appendChild(div);
        }
    }

    // ============================================================
    // 画中画功能
    // ============================================================

    /**
     * 打开画中画窗口
     */
    async openPip() {
        if (this._pipWindow && !this._pipWindow.closed) {
            this._pipWindow.focus();
            return;
        }

        // 检查浏览器支持
        if (!('documentPictureInPicture' in window)) {
            throw new Error('当前浏览器不支持画中画功能，请使用 Chrome 116+');
        }

        try {
            this._pipWindow = await window.documentPictureInPicture.requestWindow({
                width: 380,
                height: 500,
            });

            // 注入样式
            const style = this._pipWindow.document.createElement('style');
            style.textContent = this._getPipStyles();
            this._pipWindow.document.head.appendChild(style);

            // 设置标题
            this._pipWindow.document.title = '实时翻译字幕';

            // 构建 body
            const body = this._pipWindow.document.body;
            body.className = 'pip-body';

            // 标题
            const title = this._pipWindow.document.createElement('div');
            title.className = 'pip-title';
            title.textContent = '🎙️ 实时翻译字幕';
            body.appendChild(title);

            // 占位文字
            this._pipPlaceholder = this._pipWindow.document.createElement('div');
            this._pipPlaceholder.className = 'pip-placeholder';
            this._pipPlaceholder.textContent = '等待翻译...';
            body.appendChild(this._pipPlaceholder);

            // 字幕容器
            this._pipContainer = this._pipWindow.document.createElement('div');
            this._pipContainer.id = 'pip-subtitles';
            body.appendChild(this._pipContainer);

            // 同步已有字幕
            for (const item of this.items) {
                this._renderPipItem(item);
            }

            // 窗口关闭时清理
            this._pipWindow.addEventListener('pagehide', () => {
                this._closePipCleanup();
            });

            return this._pipWindow;

        } catch (err) {
            this._closePipCleanup();
            throw err;
        }
    }

    /**
     * 关闭画中画窗口
     */
    closePip() {
        if (this._pipWindow && !this._pipWindow.closed) {
            this._pipWindow.close();
        }
        this._closePipCleanup();
    }

    /**
     * 切换画中画
     */
    async togglePip() {
        if (this._pipWindow && !this._pipWindow.closed) {
            this.closePip();
            return false;
        } else {
            await this.openPip();
            return true;
        }
    }

    /**
     * 清理 PiP 状态
     */
    _closePipCleanup() {
        this._pipWindow = null;
        this._pipContainer = null;
        this._pipPlaceholder = null;
    }

    /**
     * PiP 是否打开
     */
    get isPipOpen() {
        return this._pipWindow && !this._pipWindow.closed;
    }

    /**
     * PiP 窗口样式
     */
    _getPipStyles() {
        return `
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                background: #0f0f0f;
                color: #e0e0e0;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                overflow-y: auto;
                height: 100vh;
                padding: 12px;
            }
            .pip-title {
                font-size: 12px;
                color: #a0a0a0;
                text-align: center;
                margin-bottom: 8px;
                padding-bottom: 8px;
                border-bottom: 1px solid rgba(255,255,255,0.08);
            }
            .pip-item {
                padding: 10px 12px;
                margin-bottom: 8px;
                background: #16213e;
                border-radius: 8px;
                border-left: 3px solid #00d4ff;
                animation: slideIn 0.3s ease-out;
            }
            .pip-original {
                font-size: 13px;
                color: #e0e0e0;
                margin-bottom: 4px;
                line-height: 1.4;
            }
            .pip-translated {
                font-size: 15px;
                color: #00d4ff;
                font-weight: 500;
                line-height: 1.4;
            }
            .pip-placeholder {
                color: #a0a0a0;
                text-align: center;
                padding: 40px 10px;
                font-size: 13px;
            }
            @keyframes slideIn {
                from { opacity: 0; transform: translateY(8px); }
                to { opacity: 1; transform: translateY(0); }
            }
            ::-webkit-scrollbar { width: 6px; }
            ::-webkit-scrollbar-track { background: transparent; }
            ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
        `;
    }

    /**
     * 清空字幕
     */
    clear() {
        this.items = [];
        const items = this.container.querySelectorAll('.subtitle-item');
        items.forEach(el => el.remove());

        if (this.placeholder) {
            this.placeholder.style.display = 'block';
        }

        // 清空 PiP
        if (this._pipContainer) {
            this._pipContainer.innerHTML = '';
        }
        if (this._pipPlaceholder) {
            this._pipPlaceholder.style.display = 'block';
        }
    }

    _scrollToBottom() {
        // 新内容在最上方，滚动到顶部
        this.container.scrollTop = 0;
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    getCount() { return this.items.length; }

    getLastLatency() {
        if (this.items.length === 0) return null;
        return this.items[this.items.length - 1].latencyMs;
    }
}

window.SubtitleManager = SubtitleManager;
