#!/usr/bin/env python3
"""
测试删除会话功能
验证服务端是否真正从数据库删除数据
"""

import sqlite3
import requests
import json
import sys

# 配置
DB_PATH = 'sessions.db'
SERVER_URL = 'http://localhost:8000'

def get_session_count():
    """获取当前会话数量"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sessions")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_message_count(session_id=None):
    """获取消息数量"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if session_id:
        cursor.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,))
    else:
        cursor.execute("SELECT COUNT(*) FROM messages")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_test_session():
    """获取一个测试会话"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT session_id, title FROM sessions ORDER BY updated_at DESC LIMIT 1")
    session = cursor.fetchone()
    conn.close()
    return session

def check_session_exists(session_id):
    """检查会话是否存在"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sessions WHERE session_id = ?", (session_id,))
    exists = cursor.fetchone()[0] > 0
    conn.close()
    return exists

def test_delete_session():
    """测试删除会话功能"""
    print("=" * 60)
    print("测试删除会话功能")
    print("=" * 60)
    print()
    
    # 1. 获取测试会话
    print("【步骤1】获取测试会话")
    session = get_test_session()
    if not session:
        print("❌ 没有找到测试会话，请先创建一些会话")
        return False
    
    session_id, title = session
    print(f"  会话ID: {session_id}")
    print(f"  会话标题: {title}")
    print()
    
    # 2. 检查删除前的状态
    print("【步骤2】检查删除前的状态")
    before_session_count = get_session_count()
    before_message_count = get_message_count(session_id)
    session_exists_before = check_session_exists(session_id)
    
    print(f"  数据库会话总数: {before_session_count}")
    print(f"  该会话的消息数: {before_message_count}")
    print(f"  会话是否存在: {session_exists_before}")
    print()
    
    if not session_exists_before:
        print("❌ 会话不存在，无法测试")
        return False
    
    # 3. 调用删除API
    print("【步骤3】调用删除API")
    try:
        url = f"{SERVER_URL}/api/sessions/{session_id}"
        print(f"  请求URL: {url}")
        print(f"  请求方法: DELETE")
        
        response = requests.delete(url, timeout=5)
        print(f"  响应状态码: {response.status_code}")
        print(f"  响应内容: {response.text}")
        print()
        
        if response.status_code != 200:
            print(f"❌ API返回错误状态码: {response.status_code}")
            return False
        
        result = response.json()
        if not result.get('success'):
            print(f"❌ API返回失败: {result}")
            return False
        
        print("✅ API调用成功")
        print()
        
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到服务器，请确保服务端正在运行")
        return False
    except Exception as e:
        print(f"❌ API调用失败: {e}")
        return False
    
    # 4. 检查删除后的状态
    print("【步骤4】检查删除后的状态")
    after_session_count = get_session_count()
    after_message_count = get_message_count(session_id)
    session_exists_after = check_session_exists(session_id)
    
    print(f"  数据库会话总数: {after_session_count}")
    print(f"  该会话的消息数: {after_message_count}")
    print(f"  会话是否存在: {session_exists_after}")
    print()
    
    # 5. 验证结果
    print("【步骤5】验证删除结果")
    success = True
    
    if session_exists_after:
        print("❌ 会话仍然存在于数据库中")
        success = False
    else:
        print("✅ 会话已从数据库删除")
    
    if after_session_count != before_session_count - 1:
        print(f"❌ 会话总数不正确: 期望 {before_session_count - 1}, 实际 {after_session_count}")
        success = False
    else:
        print(f"✅ 会话总数正确: {after_session_count}")
    
    if after_message_count != 0:
        print(f"❌ 消息未被级联删除: 仍有 {after_message_count} 条消息")
        success = False
    else:
        print(f"✅ 所有消息已级联删除")
    
    print()
    print("=" * 60)
    if success:
        print("✅ 测试通过：删除功能正常工作")
    else:
        print("❌ 测试失败：删除功能存在问题")
    print("=" * 60)
    
    return success

if __name__ == '__main__':
    try:
        success = test_delete_session()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)











