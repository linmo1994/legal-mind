@echo off
REM 启动HTTP服务器（用于提供静态文件服务）

echo 正在启动HTTP服务器...
cd /d %~dp0
python server\http_server.py 8888
pause











