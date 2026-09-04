#!/usr/bin/env python3
"""
连接测试脚本
测试客户端与服务端的连接状态
"""

import requests
import json
import sys

def test_mcp_server():
    """测试MCP服务端"""
    print("=" * 50)
    print("测试1: MCP服务端连接")
    print("=" * 50)
    
    try:
        # 测试健康检查
        response = requests.get('http://localhost:8000/health', timeout=5)
        if response.status_code == 200:
            print("✅ MCP服务端健康检查通过")
            print(f"   响应: {response.json()}")
            return True
        else:
            print(f"❌ MCP服务端健康检查失败: HTTP {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到MCP服务端 (端口8000)")
        print("   请确保MCP服务端已启动: python server/mcp_server.py")
        return False
    except Exception as e:
        print(f"❌ MCP服务端测试失败: {e}")
        return False

def test_mcp_initialize():
    """测试MCP协议初始化"""
    print("\n" + "=" * 50)
    print("测试2: MCP协议初始化")
    print("=" * 50)
    
    try:
        response = requests.post(
            'http://localhost:8000',
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "test-client",
                        "version": "1.0.0"
                    }
                }
            },
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'result' in data:
                print("✅ MCP协议初始化成功")
                print(f"   协议版本: {data['result'].get('protocolVersion')}")
                print(f"   服务端能力: {data['result'].get('capabilities')}")
                return True
            elif 'error' in data:
                print(f"❌ MCP协议初始化失败: {data['error']}")
                return False
            else:
                print(f"❌ 响应格式错误: {data}")
                return False
        else:
            print(f"❌ HTTP错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ MCP协议初始化测试失败: {e}")
        return False

def test_mcp_resources():
    """测试MCP资源列表"""
    print("\n" + "=" * 50)
    print("测试3: MCP资源列表")
    print("=" * 50)
    
    try:
        response = requests.post(
            'http://localhost:8000',
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "resources/list"
            },
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'resources' in data['result']:
                resources = data['result']['resources']
                print(f"✅ 获取资源列表成功，共 {len(resources)} 个资源")
                for i, res in enumerate(resources, 1):
                    print(f"   资源{i}: {res.get('uri')} - {res.get('name')}")
                return True
            else:
                print(f"❌ 响应格式错误: {data}")
                return False
        else:
            print(f"❌ HTTP错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 资源列表测试失败: {e}")
        return False

def test_llm_proxy():
    """测试LLM代理"""
    print("\n" + "=" * 50)
    print("测试4: LLM API代理")
    print("=" * 50)
    
    try:
        # 读取配置
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        api_key = config.get('llm', {}).get('api_key', '')
        if not api_key:
            print("⚠️  警告: config.json中未找到API Key")
        
        response = requests.post(
            'http://localhost:8000/api/llm/chat',
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "测试连接，请回复'连接成功'"}],
                "max_tokens": 10
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'choices' in data and len(data['choices']) > 0:
                content = data['choices'][0].get('message', {}).get('content', '')
                print("✅ LLM API代理测试成功")
                print(f"   LLM响应: {content}")
                return True
            else:
                print(f"❌ LLM响应格式错误: {data}")
                return False
        else:
            error_data = response.json() if response.text else {}
            print(f"❌ LLM API代理测试失败: HTTP {response.status_code}")
            print(f"   错误信息: {error_data}")
            return False
    except FileNotFoundError:
        print("❌ 找不到config.json文件")
        return False
    except Exception as e:
        print(f"❌ LLM代理测试失败: {e}")
        return False

def test_http_server():
    """测试HTTP服务器（静态文件服务）"""
    print("\n" + "=" * 50)
    print("测试5: HTTP服务器（静态文件）")
    print("=" * 50)
    
    try:
        response = requests.get('http://localhost:8888/config.json', timeout=5)
        if response.status_code == 200:
            config = response.json()
            print("✅ HTTP服务器正常，config.json可访问")
            print(f"   MCP服务端: {config.get('mcp_server', {}).get('host')}:{config.get('mcp_server', {}).get('port')}")
            print(f"   LLM模型: {config.get('llm', {}).get('model')}")
            return True
        else:
            print(f"❌ HTTP服务器响应错误: HTTP {response.status_code}")
            print("   请确保HTTP服务器已启动: python server/http_server.py 8888")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到HTTP服务器 (端口8888)")
        print("   请启动HTTP服务器: python server/http_server.py 8888")
        return False
    except Exception as e:
        print(f"❌ HTTP服务器测试失败: {e}")
        return False

def main():
    """运行所有测试"""
    print("\n" + "=" * 50)
    print("客户端与服务端连接测试")
    print("=" * 50 + "\n")
    
    results = []
    
    # 测试HTTP服务器
    results.append(("HTTP服务器", test_http_server()))
    
    # 测试MCP服务端
    results.append(("MCP服务端", test_mcp_server()))
    
    if results[1][1]:  # 如果MCP服务端连接成功，继续测试
        results.append(("MCP协议初始化", test_mcp_initialize()))
        results.append(("MCP资源列表", test_mcp_resources()))
        results.append(("LLM API代理", test_llm_proxy()))
    else:
        print("\n⚠️  跳过MCP相关测试（服务端未运行）")
        results.append(("MCP协议初始化", False))
        results.append(("MCP资源列表", False))
        results.append(("LLM API代理", False))
    
    # 汇总结果
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status}: {name}")
    
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！系统连接正常。")
        return 0
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败，请检查相关服务。")
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
        sys.exit(1)











