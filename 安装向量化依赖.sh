#!/bin/bash
# 安装向量化功能所需的Python依赖

echo "正在安装向量化功能依赖..."
cd "$(dirname "$0")"

# 安装ChromaDB和sentence-transformers
pip3 install chromadb>=0.4.0 sentence-transformers>=2.2.0 --quiet

echo "✅ 依赖安装完成！"
echo ""
echo "注意：首次运行时会自动下载嵌入模型（约400MB），请耐心等待。"











