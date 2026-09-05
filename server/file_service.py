#!/usr/bin/env python3
"""
文件存储服务模块
轻量化文件存储方案，用于演示应用
- 文件存储在本地文件系统（uploads目录）
- 文件元数据存储在SQLite数据库
"""

import sqlite3
import os
import json
import hashlib
import uuid
from typing import Dict, List, Optional
from datetime import datetime
import shutil
import io

# 尝试导入文字提取库
try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    print("[FileService] 警告: python-docx未安装，无法提取DOCX文件文字")

try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False
    print("[FileService] 警告: PyPDF2未安装，无法提取PDF文件文字")

class FileService:
    """文件存储服务类"""
    
    def __init__(self, db_path: str = "./files.db", upload_dir: str = "./uploads"):
        """
        初始化文件服务
        
        Args:
            db_path: SQLite数据库文件路径
            upload_dir: 文件上传存储目录
        """
        self.db_path = db_path
        self.upload_dir = upload_dir
        
        # 确保上传目录存在
        os.makedirs(upload_dir, exist_ok=True)
        
        # 初始化数据库
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建文件表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                file_id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                file_type TEXT,
                mime_type TEXT,
                session_id TEXT,
                upload_time TEXT NOT NULL,
                description TEXT,
                metadata TEXT,
                text_content TEXT
            )
        """)
        
        # 如果表已存在但没有text_content字段，添加该字段
        try:
            cursor.execute("ALTER TABLE files ADD COLUMN text_content TEXT")
            conn.commit()
            print("[FileService] 已添加text_content字段到数据库")
        except sqlite3.OperationalError:
            # 字段已存在，忽略错误
            pass
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_files_session_id 
            ON files(session_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_files_upload_time 
            ON files(upload_time)
        """)
        
        conn.commit()
        conn.close()
        print(f"[FileService] 数据库初始化完成: {self.db_path}")
    
    def save_file(self, file_data: bytes, original_filename: str, 
                  session_id: Optional[str] = None, 
                  description: Optional[str] = None,
                  metadata: Optional[Dict] = None) -> Dict:
        """
        保存文件
        
        Args:
            file_data: 文件二进制数据
            original_filename: 原始文件名
            session_id: 关联的会话ID（可选）
            description: 文件描述（可选）
            metadata: 额外的元数据（可选）
            
        Returns:
            包含文件信息的字典
        """
        # 生成文件ID
        file_id = str(uuid.uuid4())
        
        # 生成存储文件名（使用文件ID + 原始扩展名）
        file_ext = os.path.splitext(original_filename)[1]
        stored_name = f"{file_id}{file_ext}"
        file_path = os.path.join(self.upload_dir, stored_name)
        
        # 保存文件到磁盘
        with open(file_path, 'wb') as f:
            f.write(file_data)
        
        # 获取文件信息
        file_size = len(file_data)
        file_type = file_ext[1:].lower() if file_ext else 'unknown'
        
        # 检测MIME类型（简单检测）
        mime_type = self._detect_mime_type(file_type, file_data[:100])
        
        # 计算文件哈希（用于去重，可选）
        file_hash = hashlib.md5(file_data).hexdigest()
        
        # 提取文件中的文字内容
        text_content = self._extract_text(file_data, file_type, file_path)
        
        # 保存元数据到数据库
        upload_time = datetime.now().isoformat()
        metadata_json = json.dumps(metadata or {})
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO files (
                file_id, original_name, stored_name, file_path,
                file_size, file_type, mime_type, session_id,
                upload_time, description, metadata, text_content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            file_id, original_filename, stored_name, file_path,
            file_size, file_type, mime_type, session_id,
            upload_time, description, metadata_json, text_content
        ))
        conn.commit()
        conn.close()
        
        # 安全打印文件名（处理编码问题）
        try:
            safe_filename = original_filename.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            print(f"[FileService] 文件已保存: {safe_filename} -> {file_path}")
        except Exception:
            print(f"[FileService] 文件已保存: [文件名包含特殊字符] -> {file_path}")
        
        return {
            "file_id": file_id,
            "original_name": original_filename,
            "stored_name": stored_name,
            "file_path": file_path,
            "file_size": file_size,
            "file_type": file_type,
            "mime_type": mime_type,
            "session_id": session_id,
            "upload_time": upload_time,
            "description": description,
            "url": f"/api/files/{file_id}"
        }
    
    def get_file(self, file_id: str) -> Optional[Dict]:
        """
        获取文件信息
        
        Args:
            file_id: 文件ID
            
        Returns:
            文件信息字典，如果不存在返回None
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM files WHERE file_id = ?
        """, (file_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            result = {
                "file_id": row['file_id'],
                "original_name": row['original_name'],
                "stored_name": row['stored_name'],
                "file_path": row['file_path'],
                "file_size": row['file_size'],
                "file_type": row['file_type'],
                "mime_type": row['mime_type'],
                "session_id": row['session_id'],
                "upload_time": row['upload_time'],
                "description": row['description'],
                "metadata": metadata,
                "url": f"/api/files/{row['file_id']}"
            }
            # 如果存在text_content字段，添加到结果中
            if 'text_content' in row.keys():
                result['text_content'] = row['text_content']
            return result
        return None

    def update_file_metadata(self, file_id: str, patch: Dict) -> Optional[Dict]:
        """合并写入 files.metadata（JSON）。返回更新后的 get_file 结果。"""
        info = self.get_file(file_id)
        if not info:
            return None
        meta = dict(info.get("metadata") or {})
        meta.update(patch or {})
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE files SET metadata = ? WHERE file_id = ?",
            (json.dumps(meta, ensure_ascii=False), file_id),
        )
        conn.commit()
        conn.close()
        return self.get_file(file_id)
    
    def get_file_data(self, file_id: str) -> Optional[bytes]:
        """
        获取文件二进制数据
        
        Args:
            file_id: 文件ID
            
        Returns:
            文件二进制数据，如果不存在返回None
        """
        file_info = self.get_file(file_id)
        if not file_info:
            return None
        
        file_path = file_info['file_path']
        if os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                return f.read()
        return None
    
    def list_files(self, session_id: Optional[str] = None, 
                   limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        列出文件
        
        Args:
            session_id: 会话ID（可选，用于过滤）
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            文件信息列表
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if session_id:
            cursor.execute("""
                SELECT * FROM files 
                WHERE session_id = ?
                ORDER BY upload_time DESC
                LIMIT ? OFFSET ?
            """, (session_id, limit, offset))
        else:
            cursor.execute("""
                SELECT * FROM files 
                ORDER BY upload_time DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
        
        rows = cursor.fetchall()
        conn.close()
        
        files = []
        for row in rows:
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            files.append({
                "file_id": row['file_id'],
                "original_name": row['original_name'],
                "stored_name": row['stored_name'],
                "file_size": row['file_size'],
                "file_type": row['file_type'],
                "mime_type": row['mime_type'],
                "session_id": row['session_id'],
                "upload_time": row['upload_time'],
                "description": row['description'],
                "metadata": metadata,
                "url": f"/api/files/{row['file_id']}"
            })
        
        return files
    
    def delete_file(self, file_id: str) -> bool:
        """
        删除文件
        
        Args:
            file_id: 文件ID
            
        Returns:
            是否删除成功
        """
        file_info = self.get_file(file_id)
        if not file_info:
            return False
        
        # 删除文件
        file_path = file_info['file_path']
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"[FileService] 删除文件失败: {e}")
            return False
        
        # 删除数据库记录
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
        conn.commit()
        conn.close()
        
        print(f"[FileService] 文件已删除: {file_id}")
        return True
    
    def _detect_mime_type(self, file_type: str, file_header: bytes) -> str:
        """
        检测MIME类型
        
        Args:
            file_type: 文件扩展名
            file_header: 文件头部字节（用于检测）
            
        Returns:
            MIME类型字符串
        """
        # 基于文件扩展名的简单映射
        mime_map = {
            'txt': 'text/plain',
            'pdf': 'application/pdf',
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'xls': 'application/vnd.ms-excel',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'zip': 'application/zip',
            'rar': 'application/x-rar-compressed'
        }
        
        return mime_map.get(file_type.lower(), 'application/octet-stream')
    
    def _extract_text(self, file_data: bytes, file_type: str, file_path: str) -> Optional[str]:
        """
        从文件中提取文字内容
        
        Args:
            file_data: 文件二进制数据
            file_type: 文件类型（扩展名）
            file_path: 文件路径
            
        Returns:
            提取的文字内容，如果提取失败返回None
        """
        try:
            file_type_lower = file_type.lower()
            
            # DOCX文件
            if file_type_lower == 'docx' and HAS_DOCX:
                try:
                    doc = DocxDocument(io.BytesIO(file_data))
                    paragraphs = [para.text for para in doc.paragraphs]
                    return '\n'.join(paragraphs)
                except Exception as e:
                    print(f"[FileService] DOCX文字提取失败: {e}")
                    return None
            
            # PDF文件
            elif file_type_lower == 'pdf' and HAS_PDF:
                try:
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_data))
                    text_parts = []
                    for page in pdf_reader.pages:
                        text_parts.append(page.extract_text())
                    return '\n'.join(text_parts)
                except Exception as e:
                    print(f"[FileService] PDF文字提取失败: {e}")
                    return None
            
            # TXT文件
            elif file_type_lower == 'txt':
                try:
                    # 尝试多种编码
                    for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
                        try:
                            return file_data.decode(encoding)
                        except UnicodeDecodeError:
                            continue
                    return None
                except Exception as e:
                    print(f"[FileService] TXT文字提取失败: {e}")
                    return None
            
            # 其他文件类型暂不支持文字提取
            else:
                return None
                
        except Exception as e:
            print(f"[FileService] 文字提取异常: {e}")
            return None
    
    def get_file_text(self, file_id: str) -> Optional[str]:
        """
        获取文件的文字内容
        
        Args:
            file_id: 文件ID
            
        Returns:
            文件的文字内容，如果不存在返回None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT text_content FROM files WHERE file_id = ?
        """, (file_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0]:
            return row[0]
        return None

