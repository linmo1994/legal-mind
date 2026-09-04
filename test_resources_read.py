#!/usr/bin/env python3
"""
测试每个资源的读取内容
"""

import requests
import json

def test_resource_read(uri, resource_name):
    """测试单个资源的读取"""
    print(f"\n{'='*60}")
    print(f"测试资源: {resource_name}")
    print(f"URI: {uri}")
    print(f"{'='*60}")
    
    # 测试不同的参数组合
    test_cases = [
        {"uri": uri},  # 无参数
        {"uri": uri, "template_name": "劳动合同"},  # 带参数（如果适用）
    ]
    
    for i, params in enumerate(test_cases, 1):
        print(f"\n--- 测试用例 {i} ---")
        print(f"参数: {json.dumps(params, ensure_ascii=False)}")
        
        response = requests.post(
            'http://localhost:8000',
            json={
                "jsonrpc": "2.0",
                "id": i,
                "method": "resources/read",
                "params": params
            },
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"❌ HTTP错误: {response.status_code}")
            print(response.text)
            continue
        
        data = response.json()
        
        if 'error' in data:
            print(f"❌ 错误: {data['error']}")
            continue
        
        if 'result' not in data:
            print("❌ 响应格式错误：缺少result字段")
            continue
        
        result = data['result']
        
        print(f"\n✅ 读取成功")
        print(f"内容类型: {result.get('mimeType', 'N/A')}")
        
        contents = result.get('contents', [])
        print(f"内容块数量: {len(contents)}")
        
        for j, content in enumerate(contents, 1):
            print(f"\n  内容块 {j}:")
            print(f"    URI: {content.get('uri', 'N/A')}")
            print(f"    MIME类型: {content.get('mimeType', 'N/A')}")
            print(f"    文本长度: {len(content.get('text', ''))} 字符")
            
            text = content.get('text', '')
            if text:
                # 显示前500个字符
                preview = text[:500] + ('...' if len(text) > 500 else '')
                print(f"\n    内容预览:")
                print(f"    {'-'*56}")
                for line in preview.split('\n')[:20]:  # 最多显示20行
                    print(f"    {line}")
                line_count = len(text.split('\n'))
                if line_count > 20:
                    print(f"    ... (共 {line_count} 行)")
                print(f"    {'-'*56}")

def test_all_resources():
    """测试所有资源"""
    print("="*60)
    print("测试所有资源的读取内容")
    print("="*60)
    
    resources = [
        ("legal://doc_template", "法律文书模板"),
        ("legal://law_regulation", "法律法规"),
        ("legal://similar_cases", "类案检索"),
        ("legal://contract_review_rules", "合同审查规则"),
    ]
    
    for uri, name in resources:
        try:
            test_resource_read(uri, name)
        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
        
        print("\n" + "="*60)

def test_specific_resource(uri, params=None):
    """测试特定资源（带参数）"""
    print(f"\n{'='*60}")
    print(f"测试资源读取: {uri}")
    if params:
        print(f"参数: {json.dumps(params, ensure_ascii=False)}")
    print(f"{'='*60}")
    
    request_params = {"uri": uri}
    if params:
        request_params.update(params)
    
    response = requests.post(
        'http://localhost:8000',
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": request_params
        },
        timeout=10
    )
    
    if response.status_code != 200:
        print(f"❌ HTTP错误: {response.status_code}")
        print(response.text)
        return
    
    data = response.json()
    
    print("\n📋 完整响应:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    
    if 'result' in data:
        result = data['result']
        contents = result.get('contents', [])
        for i, content in enumerate(contents, 1):
            print(f"\n内容块 {i} 完整文本:")
            print("-"*60)
            print(content.get('text', ''))
            print("-"*60)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # 测试特定资源
        uri = sys.argv[1]
        params = {}
        if len(sys.argv) > 2:
            # 解析额外参数（简单处理）
            for arg in sys.argv[2:]:
                if '=' in arg:
                    key, value = arg.split('=', 1)
                    params[key] = value
        test_specific_resource(uri, params if params else None)
    else:
        # 测试所有资源
        test_all_resources()

