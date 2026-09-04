#!/usr/bin/env python3
"""
简单的HTTP服务器，用于提供静态文件服务
解决CORS问题和config.json加载问题
"""

import http.server
import socketserver
import os
import sys

# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """自定义HTTP请求处理器，添加CORS支持"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)
    
    def end_headers(self):
        # 添加CORS头；HTML/JSON 禁用缓存，避免向量化页仍使用旧的 8000 端口脚本
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        super().end_headers()
    
    def do_OPTIONS(self):
        """处理CORS预检请求"""
        self.send_response(200)
        self.end_headers()
    
    def log_message(self, format, *args):
        """自定义日志输出"""
        # 可以在这里添加日志记录
        pass

def run_server(port=8888):
    """启动HTTP服务器"""
    os.chdir(BASE_DIR)
    
    with socketserver.TCPServer(("", port), CustomHTTPRequestHandler) as httpd:
        print(f"HTTP服务器已启动")
        print(f"访问地址: http://localhost:{port}")
        print(f"主页面: http://localhost:{port}/index.html")
        print(f"MCP客户端: http://localhost:{port}/mcp_client.html")
        print(f"\n按 Ctrl+C 停止服务器")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务器已停止")
            httpd.shutdown()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    run_server(port)











