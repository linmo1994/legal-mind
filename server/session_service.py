#!/usr/bin/env python3
"""
会话管理服务模块
使用SQLite数据库存储会话历史数据
"""

import sqlite3
import json
import os
from typing import Dict, List, Optional
from datetime import datetime

class SessionService:
    """会话管理服务类"""
    
    def __init__(self, db_path: str = "./sessions.db"):
        """
        初始化会话服务
        
        Args:
            db_path: SQLite数据库文件路径
        """
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        
        # 创建会话表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT,
                status TEXT,
                current_intent TEXT,
                collected_parameters TEXT,
                missing_parameters TEXT,
                stage TEXT,
                context_cache TEXT,
                created_at TEXT,
                updated_at TEXT,
                last_user_input TEXT,
                last_user_input_time TEXT
            )
        """)
        
        # 如果表已存在但没有last_user_input_time字段，添加该字段
        try:
            cursor.execute("ALTER TABLE sessions ADD COLUMN last_user_input_time TEXT")
            conn.commit()
            print("[SessionService] 已添加last_user_input_time字段")
        except sqlite3.OperationalError:
            # 字段已存在，忽略错误
            pass
        
        # 创建消息表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
        """)
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session_id 
            ON messages(session_id, timestamp)
        """)
        
        conn.commit()
        conn.close()
        print(f"[SessionService] 数据库初始化完成: {self.db_path}")
    
    def create_session(self, session_id: str, title: str = None) -> Dict:
        """
        创建新会话
        
        Args:
            session_id: 会话ID
            title: 会话标题（可选）
            
        Returns:
            会话信息
        """
        conn = sqlite3.connect(self.db_path)
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        cursor.execute("""
            INSERT OR REPLACE INTO sessions (
                session_id, title, status, current_intent, 
                collected_parameters, missing_parameters, stage,
                context_cache, created_at, updated_at, last_user_input, last_user_input_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            title or '',
            'active',
            None,
            json.dumps({}),
            json.dumps([]),
            'idle',
            json.dumps({}),
            now,
            now,
            '',
            None
        ))
        
        conn.commit()
        conn.close()
        
        return self.get_session(session_id)
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """
        获取会话信息
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话信息，如果不存在返回None
        """
        conn = sqlite3.connect(self.db_path)
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        session = dict(row)
        # 解析JSON字段
        session['collected_parameters'] = json.loads(session.get('collected_parameters') or '{}')
        session['missing_parameters'] = json.loads(session.get('missing_parameters') or '[]')
        session['context_cache'] = json.loads(session.get('context_cache') or '{}')
        
        # 获取会话消息历史
        session['conversation_history'] = self.get_session_messages(session_id)
        
        return session
    
    def update_session(self, session_id: str, updates: Dict) -> Dict:
        """
        更新会话信息
        
        Args:
            session_id: 会话ID
            updates: 要更新的字段字典
            
        Returns:
            更新后的会话信息
        """
        conn = sqlite3.connect(self.db_path)
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        
        # 构建更新语句
        set_clauses = []
        values = []
        
        allowed_fields = [
            'title', 'status', 'current_intent', 'collected_parameters',
            'missing_parameters', 'stage', 'context_cache', 'last_user_input', 'last_user_input_time'
        ]
        
        for field in allowed_fields:
            if field in updates:
                if field in ['collected_parameters', 'missing_parameters', 'context_cache']:
                    set_clauses.append(f"{field} = ?")
                    values.append(json.dumps(updates[field]))
                else:
                    set_clauses.append(f"{field} = ?")
                    values.append(updates[field])
        
        # 总是更新updated_at
        set_clauses.append("updated_at = ?")
        values.append(datetime.now().isoformat())
        values.append(session_id)
        
        if not set_clauses:
            # 如果没有要更新的字段，直接返回当前会话
            conn.close()
            return self.get_session(session_id)
        
        # 先检查会话是否存在
        cursor.execute("SELECT COUNT(*) FROM sessions WHERE session_id = ?", (session_id,))
        if cursor.fetchone()[0] == 0:
            conn.close()
            raise ValueError(f"会话不存在: {session_id}")
        
        # 执行更新
        sql = f"UPDATE sessions SET {', '.join(set_clauses)} WHERE session_id = ?"
        cursor.execute(sql, values)
        conn.commit()
        
        conn.close()
        
        # 返回更新后的会话
        updated_session = self.get_session(session_id)
        if not updated_session:
            raise ValueError(f"更新后无法获取会话: {session_id}")
        
        return updated_session
    
    def add_message(self, session_id: str, role: str, content: str) -> int:
        """
        添加消息到会话
        
        Args:
            session_id: 会话ID
            role: 消息角色（user/assistant）
            content: 消息内容
            
        Returns:
            消息ID
        """
        conn = sqlite3.connect(self.db_path)
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        
        # 如果是用户消息，更新会话的last_user_input、last_user_input_time和title
        if role == 'user':
            # 提取用户输入的前50个字符作为标题（如果标题为空或过长）
            title = content[:50] + ('...' if len(content) > 50 else '')
            current_time = datetime.now().isoformat()
            cursor.execute("""
                UPDATE sessions 
                SET last_user_input = ?, 
                    last_user_input_time = ?,
                    title = CASE 
                        WHEN title = '' OR title IS NULL THEN ? 
                        ELSE title 
                    END,
                    updated_at = ?
                WHERE session_id = ?
            """, (content, current_time, title, current_time, session_id))
            conn.commit()
        
        cursor.execute("""
            INSERT INTO messages (session_id, role, content, timestamp)
            VALUES (?, ?, ?, ?)
        """, (session_id, role, content, datetime.now().isoformat()))
        
        message_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return message_id
    
    def get_session_messages(self, session_id: str) -> List[Dict]:
        """
        获取会话的所有消息
        
        Args:
            session_id: 会话ID
            
        Returns:
            消息列表
        """
        conn = sqlite3.connect(self.db_path)
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT role, content, timestamp 
            FROM messages 
            WHERE session_id = ? 
            ORDER BY timestamp ASC
        """, (session_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [{'role': row['role'], 'content': row['content']} for row in rows]
    
    def list_sessions(self, limit: int = 100) -> List[Dict]:
        """
        获取会话列表
        
        Args:
            limit: 返回数量限制
            
        Returns:
            会话列表，按更新时间倒序
        """
        conn = sqlite3.connect(self.db_path)
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT session_id, title, status, created_at, updated_at, last_user_input, last_user_input_time
            FROM sessions
            ORDER BY updated_at DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        sessions = []
        for row in rows:
            session = dict(row)
            # 如果没有标题，使用最后用户输入的前50个字符
            if not session.get('title'):
                session['title'] = (session.get('last_user_input') or '新会话')[:50]
                if len(session.get('last_user_input') or '') > 50:
                    session['title'] += '...'
            sessions.append(session)
        
        return sessions
    
    def delete_session(self, session_id: str) -> bool:
        """
        删除会话（级联删除消息）
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否删除成功
        """
        print(f"[SessionService] 开始删除会话: {session_id}")
        conn = sqlite3.connect(self.db_path)
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        
        # 先查询会话是否存在，以及关联的消息数量
        cursor.execute("SELECT COUNT(*) FROM sessions WHERE session_id = ?", (session_id,))
        session_exists = cursor.fetchone()[0] > 0
        
        if not session_exists:
            print(f"[SessionService] 会话不存在: {session_id}")
            conn.close()
            return False
        
        cursor.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,))
        message_count = cursor.fetchone()[0]
        print(f"[SessionService] 会话存在，关联消息数: {message_count}")
        
        # 执行删除操作
        cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        deleted = cursor.rowcount > 0
        
        if deleted:
            print(f"[SessionService] ✅ 成功删除会话，影响行数: {cursor.rowcount}")
        else:
            print(f"[SessionService] ❌ 删除失败，影响行数: {cursor.rowcount}")
        
        # 提交事务
        conn.commit()
        print(f"[SessionService] 事务已提交")
        
        # 验证删除结果
        cursor.execute("SELECT COUNT(*) FROM sessions WHERE session_id = ?", (session_id,))
        still_exists = cursor.fetchone()[0] > 0
        if still_exists:
            print(f"[SessionService] ⚠️ 警告：删除后会话仍然存在！")
        else:
            print(f"[SessionService] ✅ 验证：会话已从数据库删除")
        
        # 验证消息是否被级联删除
        cursor.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,))
        remaining_messages = cursor.fetchone()[0]
        if remaining_messages > 0:
            print(f"[SessionService] ⚠️ 警告：仍有 {remaining_messages} 条消息未被级联删除")
        else:
            print(f"[SessionService] ✅ 验证：所有关联消息已级联删除")
        
        conn.close()
        
        return deleted
    
    def delete_all_sessions(self) -> int:
        """
        删除所有会话
        
        Returns:
            删除的会话数量
        """
        conn = sqlite3.connect(self.db_path)
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM sessions")
        count = cursor.fetchone()[0]
        
        cursor.execute("DELETE FROM sessions")
        conn.commit()
        conn.close()
        
        return count

