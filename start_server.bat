@echo off
REM MCP服务器启动脚本（Windows）

echo 正在启动MCP服务器...
cd /d %~dp0
python server\mcp_server.py
pause











