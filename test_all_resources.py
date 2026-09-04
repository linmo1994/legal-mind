#!/usr/bin/env python3
"""
测试所有资源的读取内容（使用正确的参数格式）
"""

import requests
import json

def test_resource(uri, resource_name, arguments=None):
    """测试单个资源"""
    print(f"\n{'='*70}")
    print(f"📋 资源: {resource_name}")
    print(f"URI: {uri}")
    if arguments:
        print(f"参数: {json.dumps(arguments, ensure_ascii=False)}")
    print(f"{'='*70}")
    
    params = {"uri": uri}
    if arguments:
        params["arguments"] = arguments
    
    response = requests.post(
        'http://localhost:8000',
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": params
        },
        timeout=10
    )
    
    if response.status_code != 200:
        print(f"❌ HTTP错误: {response.status_code}")
        return
    
    data = response.json()
    
    if 'error' in data:
        print(f"❌ 错误: {data['error']}")
        return
    
    if 'result' not in data:
        print("❌ 响应格式错误")
        return
    
    result = data['result']
    contents = result.get('contents', [])
    
    print(f"\n✅ 读取成功，内容块数量: {len(contents)}")
    
    for i, content in enumerate(contents, 1):
        print(f"\n{'─'*70}")
        print(f"内容块 {i}:")
        print(f"  URI: {content.get('uri')}")
        print(f"  MIME类型: {content.get('mimeType')}")
        text = content.get('text', '')
        print(f"  文本长度: {len(text)} 字符")
        print(f"\n  完整内容:")
        print(f"  {'─'*70}")
        print(text)
        print(f"  {'─'*70}")

def main():
    """测试所有资源"""
    print("="*70)
    print("测试所有资源的读取内容")
    print("="*70)
    
    # 1. 法律文书模板 - 需要template_name参数
    templates = ["劳动合同", "民间借贷纠纷起诉状", "离婚协议书", "房屋租赁合同"]
    for template_name in templates:
        test_resource(
            "legal://doc_template",
            "法律文书模板",
            {"template_name": template_name}
        )
    
    # 2. 法律法规 - 需要query参数
    queries = ["合同法", "劳动法", "民法典"]
    for query in queries:
        test_resource(
            "legal://law_regulation",
            "法律法规",
            {"query": query}
        )
    
    # 3. 类案检索 - 可选case_description参数
    test_resource(
        "legal://similar_cases",
        "类案检索",
        {"case_description": "民间借贷纠纷"}
    )
    
    # 4. 合同审查规则 - 无需参数
    test_resource(
        "legal://contract_review_rules",
        "合同审查规则"
    )
    
    print(f"\n{'='*70}")
    print("✅ 所有资源测试完成")
    print(f"{'='*70}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()











