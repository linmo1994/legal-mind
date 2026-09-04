#!/usr/bin/env python3
"""
测试LLM代理接口的连续请求
模拟客户端在同一个对话中发送两次请求
"""

import requests
import json
import time
import threading

# 配置
BASE_URL = "http://localhost:8000"
LLM_ENDPOINT = f"{BASE_URL}/api/llm/chat"

# 测试数据
system_prompt = "你是一名 AI 法官智能体，精通法律实务。"
conversation_history = []

def send_request(request_num, user_input, conversation_history):
    """发送单个请求"""
    print(f"\n{'='*60}")
    print(f"【请求 {request_num}】开始发送")
    print(f"时间: {time.strftime('%H:%M:%S')}")
    print(f"用户输入: {user_input}")
    print(f"历史对话数量: {len(conversation_history)}")
    
    request_data = {
        "system_prompt": system_prompt,
        "conversation_history": conversation_history,
        "current_user_input": user_input,
        "stream": True,
        "config": {
            "temperature": 0.0,
            "max_tokens": 100  # 减少token数，加快测试
        }
    }
    
    start_time = time.time()
    
    try:
        print(f"发送请求到: {LLM_ENDPOINT}")
        print(f"请求数据大小: {len(json.dumps(request_data))} 字节")
        
        # 发送流式请求
        response = requests.post(
            LLM_ENDPOINT,
            json=request_data,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream"
            },
            stream=True,
            timeout=120  # 120秒超时（流式响应可能需要更长时间）
        )
        
        elapsed = time.time() - start_time
        print(f"收到响应，耗时: {elapsed:.2f}秒")
        print(f"状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")
        
        if response.status_code != 200:
            print(f"❌ 请求失败: {response.status_code}")
            print(f"响应内容: {response.text[:200]}")
            return None
        
        # 读取流式响应
        print("开始读取流式数据...")
        chunk_count = 0
        full_content = ""
        start_read_time = time.time()
        
        try:
            for line in response.iter_lines(decode_unicode=True, chunk_size=8192):
                if line:
                    line_text = line if isinstance(line, str) else line.decode('utf-8')
                    if line_text.startswith('data: '):
                        data_str = line_text[6:].strip()
                        if data_str == '[DONE]':
                            print("收到结束标记 [DONE]")
                            break
                        try:
                            data_json = json.loads(data_str)
                            chunk_count += 1
                            if chunk_count <= 3:  # 只打印前3个chunk
                                print(f"  Chunk {chunk_count}: {str(data_json)[:100]}...")
                            elif chunk_count % 10 == 0:  # 每10个chunk打印一次
                                elapsed = time.time() - start_read_time
                                print(f"  已接收 {chunk_count} 个chunk，耗时 {elapsed:.1f}秒...")
                        except json.JSONDecodeError as e:
                            print(f"  JSON解析错误: {e}, 数据: {data_str[:50]}")
        except requests.exceptions.ChunkedEncodingError as e:
            print(f"  流式读取完成（可能已结束）: {e}")
        except Exception as e:
            print(f"  读取流式数据时出错: {type(e).__name__}: {e}")
        
        total_time = time.time() - start_time
        print(f"✅ 请求 {request_num} 完成")
        print(f"总耗时: {total_time:.2f}秒")
        print(f"收到 {chunk_count} 个数据块")
        
        # 更新对话历史
        conversation_history.append({
            "role": "user",
            "content": user_input
        })
        conversation_history.append({
            "role": "assistant",
            "content": "测试响应"
        })
        
        return True
        
    except requests.exceptions.Timeout:
        elapsed = time.time() - start_time
        print(f"❌ 请求 {request_num} 超时 (已等待 {elapsed:.2f}秒)")
        return False
    except requests.exceptions.ConnectionError as e:
        elapsed = time.time() - start_time
        print(f"❌ 请求 {request_num} 连接错误: {e}")
        return False
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ 请求 {request_num} 异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主测试函数"""
    print("="*60)
    print("LLM代理接口连续请求测试")
    print("="*60)
    
    # 检查服务端是否运行
    try:
        health_response = requests.get(f"{BASE_URL}/health", timeout=3)
        if health_response.status_code == 200:
            print("✅ 服务端健康检查通过")
        else:
            print(f"❌ 服务端健康检查失败: {health_response.status_code}")
            return
    except Exception as e:
        print(f"❌ 无法连接到服务端: {e}")
        print("请确保服务端正在运行: python3 server/mcp_server.py")
        return
    
    # 第一次请求
    print("\n" + "="*60)
    print("【测试场景】同一个对话中的两次连续请求")
    print("="*60)
    
    result1 = send_request(1, "你好", conversation_history)
    
    if not result1:
        print("\n❌ 第一次请求失败，停止测试")
        return
    
    # 等待一段时间
    wait_time = 2
    print(f"\n等待 {wait_time} 秒后发送第二次请求...")
    time.sleep(wait_time)
    
    # 第二次请求
    result2 = send_request(2, "请介绍一下你自己", conversation_history)
    
    # 测试结果
    print("\n" + "="*60)
    print("【测试结果】")
    print("="*60)
    print(f"第一次请求: {'✅ 成功' if result1 else '❌ 失败'}")
    print(f"第二次请求: {'✅ 成功' if result2 else '❌ 失败'}")
    
    if result1 and result2:
        print("\n✅ 所有测试通过！服务端能正常处理连续请求")
    else:
        print("\n❌ 测试失败，服务端在处理连续请求时出现问题")
        print("\n建议检查:")
        print("  1. 服务端日志: tail -f mcp_server.log")
        print("  2. 是否有资源锁定或状态保持问题")
        print("  3. DeepSeek API连接是否正常")

if __name__ == "__main__":
    main()

