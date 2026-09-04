#!/usr/bin/env python3
"""
测试resources/list接口返回内容
"""

import requests
import json

def test_resources_list():
    """测试resources/list接口"""
    print("=" * 60)
    print("测试 resources/list 接口")
    print("=" * 60)
    
    # 发送请求
    response = requests.post(
        'http://localhost:8000',
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/list"
        },
        timeout=5
    )
    
    if response.status_code != 200:
        print(f"❌ HTTP错误: {response.status_code}")
        print(response.text)
        return
    
    data = response.json()
    
    print("\n📋 完整响应内容:")
    print("-" * 60)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    
    print("\n" + "=" * 60)
    print("📊 响应分析")
    print("=" * 60)
    
    # 检查错误
    if 'error' in data:
        print(f"❌ 错误: {data['error']}")
        return
    
    # 检查result
    if 'result' not in data:
        print("❌ 响应格式错误：缺少result字段")
        return
    
    result = data['result']
    
    # 检查resources
    if 'resources' not in result:
        print("❌ 响应格式错误：缺少resources字段")
        return
    
    resources = result['resources']
    
    print(f"\n✅ 资源数量: {len(resources)}")
    print(f"资源类型: {type(resources)}")
    
    print("\n" + "-" * 60)
    print("📝 资源详细列表:")
    print("-" * 60)
    
    for i, resource in enumerate(resources, 1):
        print(f"\n资源 {i}:")
        print(f"  URI: {resource.get('uri', 'N/A')}")
        print(f"  名称: {resource.get('name', 'N/A')}")
        print(f"  描述: {resource.get('description', 'N/A')}")
        print(f"  MIME类型: {resource.get('mimeType', 'N/A')}")
        
        # 显示其他字段
        other_fields = {k: v for k, v in resource.items() 
                       if k not in ['uri', 'name', 'description', 'mimeType']}
        if other_fields:
            print(f"  其他字段:")
            for key, value in other_fields.items():
                print(f"    {key}: {value}")
    
    print("\n" + "=" * 60)
    print("📋 JSON格式输出:")
    print("=" * 60)
    print(json.dumps(resources, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    try:
        test_resources_list()
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()











