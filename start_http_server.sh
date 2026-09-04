#!/bin/bash
# 启动HTTP服务器（用于提供静态文件服务）

echo "正在启动HTTP服务器..."
cd "$(dirname "$0")"
python3 server/http_server.py 8888











