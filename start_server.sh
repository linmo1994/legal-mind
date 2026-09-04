#!/bin/bash
# MCP服务器启动脚本

echo "正在启动MCP服务器..."
cd "$(dirname "$0")"
python3 server/mcp_server.py











