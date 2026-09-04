#!/usr/bin/env python3
"""
测试服务端能力声明
"""

import requests
import json

def test_capabilities():
    """测试服务端能力声明"""
    print("=" * 60)
    print("测试服务端能力声明")
    print("=" * 60)
    
    # 发送initialize请求
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
    
    if response.status_code != 200:
        print(f"❌ HTTP错误: {response.status_code}")
        return
    
    data = response.json()
    
    if 'error' in data:
        print(f"❌ 错误: {data['error']}")
        return
    
    if 'result' not in data:
        print("❌ 响应格式错误：缺少result字段")
        return
    
    result = data['result']
    
    print("\n📋 服务端能力声明详情：")
    print("-" * 60)
    
    # 协议版本
    print(f"协议版本 (protocolVersion): {result.get('protocolVersion')}")
    
    # 服务端信息
    server_info = result.get('serverInfo', {})
    print(f"\n服务端信息 (serverInfo):")
    print(f"  名称: {server_info.get('name')}")
    print(f"  版本: {server_info.get('version')}")
    
    # 能力声明
    capabilities = result.get('capabilities', {})
    print(f"\n能力声明 (capabilities):")
    print(f"  类型: {type(capabilities)}")
    print(f"  内容: {json.dumps(capabilities, indent=2, ensure_ascii=False)}")
    
    # 详细分析每个能力
    print(f"\n📊 能力详细分析：")
    print("-" * 60)
    
    if 'resources' in capabilities:
        resources_cap = capabilities['resources']
        print(f"\n✅ Resources能力:")
        if isinstance(resources_cap, bool):
            print(f"  支持: {resources_cap}")
        elif isinstance(resources_cap, dict):
            print(f"  支持: True")
            print(f"  详细配置: {json.dumps(resources_cap, indent=4, ensure_ascii=False)}")
        else:
            print(f"  值: {resources_cap} (类型: {type(resources_cap)})")
    else:
        print(f"\n❌ Resources能力: 未声明")
    
    if 'prompts' in capabilities:
        prompts_cap = capabilities['prompts']
        print(f"\n✅ Prompts能力:")
        if isinstance(prompts_cap, bool):
            print(f"  支持: {prompts_cap}")
        elif isinstance(prompts_cap, dict):
            print(f"  支持: True")
            print(f"  详细配置: {json.dumps(prompts_cap, indent=4, ensure_ascii=False)}")
        else:
            print(f"  值: {prompts_cap} (类型: {type(prompts_cap)})")
    else:
        print(f"\n❌ Prompts能力: 未声明")
    
    if 'tools' in capabilities:
        tools_cap = capabilities['tools']
        print(f"\n✅ Tools能力:")
        if isinstance(tools_cap, bool):
            print(f"  支持: {tools_cap}")
        elif isinstance(tools_cap, dict):
            print(f"  支持: True")
            print(f"  详细配置: {json.dumps(tools_cap, indent=4, ensure_ascii=False)}")
        else:
            print(f"  值: {tools_cap} (类型: {type(tools_cap)})")
    else:
        print(f"\n❌ Tools能力: 未声明")
    
    # 其他能力
    other_caps = {k: v for k, v in capabilities.items() if k not in ['resources', 'prompts', 'tools']}
    if other_caps:
        print(f"\n📦 其他能力:")
        for key, value in other_caps.items():
            print(f"  {key}: {value}")
    
    # 总结
    print(f"\n" + "=" * 60)
    print("📝 总结:")
    print("=" * 60)
    print(f"服务端声明了 {len(capabilities)} 种能力:")
    for key, value in capabilities.items():
        status = "✅ 支持" if value else "❌ 不支持"
        print(f"  - {key}: {status}")
    
    # 验证能力是否与实际功能匹配
    print(f"\n🔍 能力验证:")
    print("-" * 60)
    
    # 测试resources/list
    if capabilities.get('resources'):
        res_response = requests.post(
            'http://localhost:8000',
            json={"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
            timeout=5
        )
        if res_response.status_code == 200:
            res_data = res_response.json()
            if 'error' not in res_data:
                print("✅ Resources能力验证通过（可以调用resources/list）")
            else:
                print(f"❌ Resources能力验证失败: {res_data['error']}")
        else:
            print(f"❌ Resources能力验证失败: HTTP {res_response.status_code}")
    else:
        print("⚠️  Resources能力未声明，跳过验证")
    
    # 测试prompts/list
    if capabilities.get('prompts'):
        prompts_response = requests.post(
            'http://localhost:8000',
            json={"jsonrpc": "2.0", "id": 3, "method": "prompts/list"},
            timeout=5
        )
        if prompts_response.status_code == 200:
            prompts_data = prompts_response.json()
            if 'error' not in prompts_data:
                print("✅ Prompts能力验证通过（可以调用prompts/list）")
            else:
                print(f"❌ Prompts能力验证失败: {prompts_data['error']}")
        else:
            print(f"❌ Prompts能力验证失败: HTTP {prompts_response.status_code}")
    else:
        print("⚠️  Prompts能力未声明，跳过验证")
    
    # 测试tools/list
    if capabilities.get('tools'):
        tools_response = requests.post(
            'http://localhost:8000',
            json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
            timeout=5
        )
        if tools_response.status_code == 200:
            tools_data = tools_response.json()
            if 'error' not in tools_data:
                print("✅ Tools能力验证通过（可以调用tools/list）")
            else:
                print(f"❌ Tools能力验证失败: {tools_data['error']}")
        else:
            print(f"❌ Tools能力验证失败: HTTP {tools_response.status_code}")
    else:
        print("⚠️  Tools能力未声明（符合需求：暂无工具）")

if __name__ == "__main__":
    try:
        test_capabilities()
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()











