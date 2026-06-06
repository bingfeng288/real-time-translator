/**
 * 字幕管理器
 * 负责字幕条目的渲染和管理
 */

class SubtitleManager {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.placeholder = document.getElementById('subtitlePlaceholder');
        this.items = [];
        this.maxItems = 100; // 最多保留条目数
    }

    /**
     * 添加一条字幕
     */
    add(original, translated, sourceLang, targetLang, latencyMs) {
        // 隐藏占位文字
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

        // 限制数量
        if (this.items.length > this.maxItems) {
            const removed = this.items.shift();
            const el = document.getElementById(`subtitle-${removed.id}`);
            if (el) el.remove();
        }

        this._renderItem(item);
        this._scrollToBottom();

        return item;
    }

    /**
     * 渲染单条字幕
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

        this.container.appendChild(div);
    }

    /**
     * 清空字幕
     */
    clear() {
        this.items = [];
        // 移除所有字幕条目，保留占位文字
        const items = this.container.querySelectorAll('.subtitle-item');
        items.forEach(el => el.remove());

        if (this.placeholder) {
            this.placeholder.style.display = 'block';
        }
    }

    /**
     * 滚动到底部
     */
    _scrollToBottom() {
        this.container.scrollTop = this.container.scrollHeight;
    }

    /**
     * HTML 转义
     */
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * 获取字幕条数
     */
    getCount() {
        return this.items.length;
    }

    /**
     * 获取最后一条的延迟
     */
    getLastLatency() {
        if (this.items.length === 0) return null;
        return this.items[this.items.length - 1].latencyMs;
    }
}

window.SubtitleManager = SubtitleManager;
