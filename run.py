#!/usr/bin/env python3
"""
实时语音翻译服务 - 启动脚本
"""

import uvicorn
from backend.config import HOST, PORT

if __name__ == "__main__":
    print("=" * 50)
    print("  实时语音翻译服务")
    print(f"  地址: http://localhost:{PORT}")
    print("  按 Ctrl+C 停止")
    print("=" * 50)

    uvicorn.run(
        "backend.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="debug",
    )
