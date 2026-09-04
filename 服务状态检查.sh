#!/bin/bash
# 服务状态检查脚本

echo "=========================================="
echo "模拟裁判系统服务状态检查"
echo "=========================================="
echo ""

# 检查MCP服务端 (端口8000)
echo "1. MCP服务端 (端口8000):"
if lsof -ti:8000 > /dev/null 2>&1; then
    echo "   ✅ 服务正在运行"
    echo "   进程ID: $(lsof -ti:8000 | head -1)"
    echo "   健康检查:"
    curl -s http://localhost:8000/health | head -3 | sed 's/^/      /'
else
    echo "   ❌ 服务未运行"
    echo "   启动命令: python3 server/mcp_server.py"
fi
echo ""

# 检查HTTP服务器 (端口8888)
echo "2. HTTP服务器 (端口8888):"
HTTP_PID=$(ps aux | grep "http_server.py" | grep -v grep | awk '{print $2}' | head -1)
if [ -n "$HTTP_PID" ]; then
    echo "   ✅ 服务正在运行"
    echo "   进程ID: $HTTP_PID"
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/index.html 2>/dev/null)
    if [ "$HTTP_CODE" = "200" ]; then
        echo "   ✅ 页面可访问 (HTTP $HTTP_CODE)"
    else
        echo "   ⚠️  页面访问异常 (HTTP $HTTP_CODE)"
    fi
else
    echo "   ❌ 服务未运行"
    echo "   启动命令: python3 server/http_server.py 8888"
fi
echo ""

# 访问地址
echo "=========================================="
echo "访问地址:"
echo "=========================================="
echo "主页面: http://localhost:8888/index.html"
echo "MCP客户端: http://localhost:8888/mcp_client.html"
echo "向量化页面: http://localhost:8888/vectorize.html"
echo ""

