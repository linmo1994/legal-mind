#!/usr/bin/env python3
"""
向量化服务模块
使用ChromaDB存储向量，支持持久化到本地文件
"""

import os
import json
import time
import numpy as np
import chromadb
from chromadb.config import Settings
# 在导入SentenceTransformer之前设置环境变量，确保离线模式生效
os.environ.setdefault('HF_HUB_OFFLINE', '0')  # 默认允许在线，但会在检查缓存后设置为离线
os.environ.setdefault('TRANSFORMERS_VERBOSITY', 'error')
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '300')
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Optional
import hashlib

class VectorService:
    """向量化服务类"""
    
    def __init__(self, persist_directory: str = "./chroma_db"):
        """
        初始化向量化服务
        
        Args:
            persist_directory: ChromaDB持久化目录
        """
        self.persist_directory = persist_directory
        self.collection_name = "legal_documents"
        
        # 确保目录存在
        os.makedirs(persist_directory, exist_ok=True)
        
        # 初始化ChromaDB客户端（支持持久化）
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # 初始化嵌入模型（使用轻量级中文模型）
        print(f"[VectorService] 正在加载嵌入模型...")
        try:
            # 设置环境变量
            os.environ['TRANSFORMERS_VERBOSITY'] = 'error'
            # 增加超时时间，允许更长的下载时间（如果网络可用）
            os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = '300'  # 5分钟
            # 设置离线模式，优先使用本地缓存
            os.environ['TRANSFORMERS_OFFLINE'] = '0'  # 允许在线，但优先使用缓存
            
            model_name = 'paraphrase-multilingual-MiniLM-L12-v2'
            cache_dir = os.path.expanduser('~/.cache/huggingface')
            
            # 检查本地缓存是否存在
            import glob
            cache_path = os.path.join(cache_dir, 'hub')
            pattern = f"models--sentence-transformers--{model_name.replace('/', '--')}"
            cached_model_path = os.path.join(cache_path, pattern)
            
            if os.path.exists(cached_model_path):
                print(f"[VectorService] ✅ 发现本地缓存模型: {cached_model_path}")
                print(f"[VectorService] 使用本地缓存，跳过网络下载...")
                # 直接使用本地缓存，不尝试网络连接
                try:
                    # 设置离线模式，强制使用本地缓存
                    os.environ['HF_HUB_OFFLINE'] = '1'
                    self.model = SentenceTransformer(model_name, device='cpu', cache_folder=cache_dir)
                    print(f"[VectorService] ✅ 从本地缓存加载模型成功")
                except Exception as local_error:
                    print(f"[VectorService] ⚠️  从本地缓存加载失败: {local_error}")
                    print(f"[VectorService] 尝试在线模式...")
                    # 如果本地加载失败，尝试在线模式
                    os.environ['HF_HUB_OFFLINE'] = '0'
                    self.model = SentenceTransformer(model_name, device='cpu', cache_folder=cache_dir)
            else:
                print(f"[VectorService] 本地缓存不存在，尝试从网络下载...")
                print(f"[VectorService] 注意：如果网络无法访问huggingface.co，下载会失败")
                # 尝试下载（如果网络可用）
                self.model = SentenceTransformer(model_name, device='cpu', cache_folder=cache_dir)
                print(f"[VectorService] ✅ 模型下载并加载成功")
            
        except Exception as e:
            print(f"[VectorService] ⚠️  警告：无法加载嵌入模型: {e}")
            print(f"[VectorService] 可能原因：")
            print(f"  1. 网络无法访问 huggingface.co（连接超时）")
            print(f"  2. 本地缓存不存在且无法下载")
            print(f"  3. 模型文件损坏或不完整")
            print(f"[VectorService] 使用备用方案（哈希向量）...")
            print(f"[VectorService] 注意：使用哈希向量会影响向量搜索的准确性，建议修复网络问题后重新加载模型")
            # 如果无法加载模型，使用简单的哈希作为占位符
            self.model = None
        
        # 获取或创建集合
        try:
            # 使用余弦距离作为度量标准（更适合文本相似度）
            # ChromaDB支持多种距离度量：l2（欧氏距离）、cosine（余弦距离）、ip（内积）
            # 余弦距离更适合语义相似度搜索
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "法律文档向量库"},
                # 设置距离度量为余弦距离
                # 注意：如果集合已存在，需要重新创建才能更改距离度量
            )
            # 检查集合的距离度量
            collection_metadata = self.collection.metadata or {}
            if 'hnsw:space' not in collection_metadata:
                print(f"[VectorService] ⚠️  注意：集合可能使用默认L2距离，建议使用余弦距离以获得更好的语义相似度")
                print(f"[VectorService] 提示：如需更改，请删除现有集合并重新创建")
            print(f"[VectorService] 向量集合 '{self.collection_name}' 已就绪")
        except Exception as e:
            print(f"[VectorService] 错误：无法创建集合: {e}")
            raise
    
    def _generate_embedding(self, text: str) -> List[float]:
        """
        生成文本的向量嵌入
        
        Args:
            text: 输入文本
            
        Returns:
            向量嵌入列表
        """
        if self.model is None:
            # 备用方案：使用简单的哈希向量（仅用于测试）
            hash_obj = hashlib.md5(text.encode('utf-8'))
            hash_hex = hash_obj.hexdigest()
            # 将哈希转换为384维向量（与模型输出维度一致）
            vector = [float(int(hash_hex[i:i+2], 16)) / 255.0 for i in range(0, min(384, len(hash_hex)), 2)]
            # 填充到384维
            while len(vector) < 384:
                vector.append(0.0)
            return vector[:384]
        
        # 使用模型生成嵌入
        # normalize_embeddings=True 会归一化向量，使向量长度为1
        # 这对于余弦相似度计算很重要，即使使用L2距离，归一化后的向量也能提供更好的语义相似度
        embedding = self.model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return embedding.tolist()
    
    def _split_text(self, text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
        """
        将文本分割成块
        
        Args:
            text: 输入文本
            chunk_size: 块大小（字符数）
            chunk_overlap: 重叠大小（字符数）
            
        Returns:
            文本块列表
        """
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            
            # 尝试在句号、换行符等位置分割
            if end < len(text):
                # 查找最后一个句号或换行符
                last_period = chunk.rfind('。')
                last_newline = chunk.rfind('\n')
                split_pos = max(last_period, last_newline)
                
                if split_pos > chunk_size * 0.5:  # 如果找到的分割点不太靠前
                    chunk = chunk[:split_pos + 1]
                    end = start + split_pos + 1
            
            chunks.append(chunk.strip())
            start = end - chunk_overlap  # 重叠
            
        return chunks
    
    def add_document(self, document_id: str, text: str, metadata: Optional[Dict] = None) -> Dict:
        """
        添加文档到向量库
        
        Args:
            document_id: 文档ID
            text: 文档文本
            metadata: 文档元数据
            
        Returns:
            操作结果
        """
        try:
            # 分割文本
            chunks = self._split_text(text)
            
            # 生成向量和ID
            ids = []
            embeddings = []
            documents = []
            metadatas = []
            
            for i, chunk in enumerate(chunks):
                chunk_id = f"{document_id}_chunk_{i}"
                embedding = self._generate_embedding(chunk)
                
                chunk_metadata = {
                    "document_id": document_id,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    **(metadata or {})
                }
                
                ids.append(chunk_id)
                embeddings.append(embedding)
                documents.append(chunk)
                metadatas.append(chunk_metadata)
            
            # 添加到集合
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            
            return {
                "success": True,
                "document_id": document_id,
                "chunks_count": len(chunks),
                "message": f"文档已成功向量化，共 {len(chunks)} 个文本块"
            }
            
        except Exception as e:
            print(f"[VectorService] 添加文档失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def search(self, query: str, n_results: int = 5, boost_keywords: bool = True, where: Optional[Dict] = None) -> List[Dict]:
        """
        搜索相似文档
        
        Args:
            query: 查询文本
            n_results: 返回结果数量
            boost_keywords: 是否对包含查询关键词的结果进行boost（提升排名）
            where: 可选的元数据过滤条件（传给 ChromaDB query）
            
        Returns:
            相似文档列表
        """
        try:
            # 生成查询向量（已归一化）
            query_embedding = self._generate_embedding(query)
            
            # 提取查询中的关键词（用于boost）
            query_keywords = []
            if boost_keywords:
                # 提取数字（如"第五十二条"中的"52"、"五十二"）
                import re
                # 提取阿拉伯数字
                numbers = re.findall(r'\d+', query)
                query_keywords.extend(numbers)
                # 提取中文数字（如"五十二"、"五十一"等）
                chinese_numbers = re.findall(r'[一二三四五六七八九十]+', query)
                query_keywords.extend(chinese_numbers)
                # 提取"第X条"、"第X章"等模式
                article_patterns = re.findall(r'第[一二三四五六七八九十\d]+条', query)
                query_keywords.extend(article_patterns)
                # 提取法律名称关键词
                if "劳动合同法" in query:
                    query_keywords.append("劳动合同法")
                if "合同法" in query and "劳动合同法" not in query:
                    query_keywords.append("合同法")
                if "民法典" in query:
                    query_keywords.append("民法典")
            
            # #region agent log
            log_path = os.path.expanduser('/Users/kanglinlin/Documents/cursor/AI法官/.cursor/debug.log')
            try:
                with open(log_path, 'a', encoding='utf-8') as f:
                    # 检查向量归一化状态
                    embedding_norm = np.linalg.norm(query_embedding) if query_embedding else None
                    f.write(json.dumps({
                        "location": "vector_service.py:256",
                        "message": "查询向量生成",
                        "data": {
                            "query": query[:100],
                            "embedding_dim": len(query_embedding) if query_embedding else 0,
                            "embedding_norm": float(embedding_norm) if embedding_norm is not None else None,
                            "is_normalized": abs(embedding_norm - 1.0) < 0.01 if embedding_norm is not None else None
                        },
                        "timestamp": int(time.time() * 1000),
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "C"
                    }, ensure_ascii=False) + '\n')
            except Exception as e:
                pass
            # #endregion
            
            # 搜索
            # 对于归一化的向量，即使使用L2距离，也能提供合理的相似度
            # 归一化后的L2距离范围：0到2（0表示完全相同，2表示完全相反）
            # #region agent log
            log_path = os.path.expanduser('/Users/kanglinlin/Documents/cursor/AI法官/.cursor/debug.log')
            try:
                with open(log_path, 'a', encoding='utf-8') as f:
                    # 检查集合中的文档数量
                    collection_count = self.collection.count()
                    f.write(json.dumps({
                        "location": "vector_service.py:286",
                        "message": "开始向量搜索",
                        "data": {
                            "query": query[:100],
                            "n_results": n_results,
                            "collection_count": collection_count,
                            "query_embedding_dim": len(query_embedding) if query_embedding else 0
                        },
                        "timestamp": int(time.time() * 1000),
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "D"
                    }, ensure_ascii=False) + '\n')
            except Exception as e:
                pass
            # #endregion
            
            # 如果启用关键词boost，需要查询更多结果以确保包含关键词的结果能被boost到前面
            # 查询数量 = 请求数量 * 2，但至少10个，最多50个
            query_n_results = max(min(n_results * 2, 50), 10) if boost_keywords else n_results
            
            kwargs = dict(query_embeddings=[query_embedding], n_results=query_n_results)
            if where:
                kwargs["where"] = where
            results = self.collection.query(**kwargs)
            
            # #region agent log
            try:
                with open(log_path, 'a', encoding='utf-8') as f:
                    result_count = len(results['ids'][0]) if results.get('ids') and results['ids'][0] else 0
                    f.write(json.dumps({
                        "location": "vector_service.py:295",
                        "message": "向量搜索完成",
                        "data": {
                            "query": query[:100],
                            "result_count": result_count,
                            "has_results": result_count > 0,
                            "sample_ids": results['ids'][0][:3] if results.get('ids') and results['ids'][0] else []
                        },
                        "timestamp": int(time.time() * 1000),
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "D"
                    }, ensure_ascii=False) + '\n')
            except Exception as e:
                pass
            # #endregion
            
            # 格式化结果
            formatted_results = []
            if results['ids'] and len(results['ids'][0]) > 0:
                # #region agent log
                log_path = os.path.expanduser('/Users/kanglinlin/Documents/cursor/AI法官/.cursor/debug.log')
                try:
                    with open(log_path, 'a', encoding='utf-8') as f:
                        distances = results['distances'][0] if 'distances' in results else []
                        # 获取查询文本和返回的前几个文档内容用于调试
                        query_text = query[:100] if query else ""
                        sample_docs = []
                        if results.get('documents') and len(results['documents'][0]) > 0:
                            for i in range(min(3, len(results['documents'][0]))):
                                doc_text = results['documents'][0][i][:100] if results['documents'][0][i] else ""
                                sample_docs.append({"index": i, "preview": doc_text, "distance": distances[i] if i < len(distances) else None})
                        
                        f.write(json.dumps({
                            "location": "vector_service.py:253",
                            "message": "ChromaDB返回的距离值和搜索结果",
                            "data": {
                                "query": query_text,
                                "n_results": n_results,
                                "distances": distances[:5] if len(distances) > 5 else distances,
                                "min_distance": min(distances) if distances else None,
                                "max_distance": max(distances) if distances else None,
                                "has_negative": any(d < 0 for d in distances) if distances else False,
                                "sample_documents": sample_docs
                            },
                            "timestamp": int(time.time() * 1000),
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "B"
                        }, ensure_ascii=False) + '\n')
                except Exception as e:
                    pass
                # #endregion
                
                for i in range(len(results['ids'][0])):
                    doc_text = results['documents'][0][i]
                    distance = results['distances'][0][i] if 'distances' in results else None
                    
                    # 计算关键词匹配分数（用于boost）
                    keyword_score = 0.0
                    if query_keywords:
                        for keyword in query_keywords:
                            # 检查文档中是否包含关键词
                            if keyword in doc_text:
                                # 根据关键词长度和重要性给予不同的权重
                                if len(keyword) >= 2:  # 较长的关键词（如"第五十二条"）权重更高
                                    keyword_score += 0.3
                                else:  # 单个数字或短关键词
                                    keyword_score += 0.1
                    
                    # 调整distance：包含关键词的结果distance降低（提升排名）
                    adjusted_distance = distance
                    if keyword_score > 0 and distance is not None:
                        # 对包含关键词的结果，降低distance（相当于提升相似度）
                        # 降低幅度根据keyword_score调整，最多降低0.2
                        boost_amount = min(keyword_score * 0.2, 0.2)
                        adjusted_distance = max(0, distance - boost_amount)
                    
                    formatted_results.append({
                        "id": results['ids'][0][i],
                        "document": doc_text,
                        "metadata": results['metadatas'][0][i],
                        "distance": distance,  # 保留原始distance
                        "adjusted_distance": adjusted_distance,  # 调整后的distance（用于排序）
                        "keyword_score": keyword_score  # 关键词匹配分数
                    })
                
                # 根据adjusted_distance重新排序（包含关键词的结果会排到前面）
                formatted_results.sort(key=lambda x: x.get('adjusted_distance') if x.get('adjusted_distance') is not None else (x.get('distance') if x.get('distance') is not None else float('inf')))
                
                # 如果启用了boost，只返回前n_results个结果（因为查询了更多结果用于boost）
                if boost_keywords and len(formatted_results) > n_results:
                    formatted_results = formatted_results[:n_results]
            
            return formatted_results
            
        except Exception as e:
            print(f"[VectorService] 搜索失败: {e}")
            return []
    
    def delete_document(self, document_id: str) -> Dict:
        """
        删除文档
        
        Args:
            document_id: 文档ID
            
        Returns:
            操作结果
        """
        try:
            # 查找所有相关的chunk
            results = self.collection.get(
                where={"document_id": document_id}
            )
            
            if results['ids']:
                # 删除所有chunk
                self.collection.delete(ids=results['ids'])
                return {
                    "success": True,
                    "deleted_count": len(results['ids']),
                    "message": f"已删除文档 {document_id} 的 {len(results['ids'])} 个文本块"
                }
            else:
                return {
                    "success": False,
                    "message": f"未找到文档 {document_id}"
                }
                
        except Exception as e:
            print(f"[VectorService] 删除文档失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _chroma_scalar(self, value):
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return "; ".join(str(x) for x in value if x is not None)
        return str(value)

    def update_document_metadata(self, document_id: str, metadata: dict) -> dict:
        results = self.collection.get(where={"document_id": document_id}, include=["metadatas"])
        ids = results.get("ids") or []
        if not ids:
            return {"success": False, "message": f"未找到文档 {document_id}"}
        new_metas = []
        for old in results["metadatas"]:
            merged = dict(old or {})
            for k, v in (metadata or {}).items():
                sv = self._chroma_scalar(v)
                if sv is None:
                    continue
                merged[k] = sv
            merged["document_id"] = document_id
            new_metas.append(merged)
        self.collection.update(ids=ids, metadatas=new_metas)
        return {"success": True, "updated_count": len(ids)}

    def count_by_doc_type(self, doc_type: str) -> int:
        results = self.collection.get(where={"doc_type": doc_type}, include=["metadatas"])
        ids = set()
        for m in results.get("metadatas") or []:
            if m and m.get("document_id"):
                ids.add(m["document_id"])
        return len(ids)
    
    def get_collection_info(self) -> Dict:
        """
        获取集合信息
        
        Returns:
            集合信息
        """
        try:
            count = self.collection.count()
            return {
                "collection_name": self.collection_name,
                "document_count": count,
                "persist_directory": self.persist_directory
            }
        except Exception as e:
            return {
                "error": str(e)
            }

    def count_documents(self) -> Dict:
        """Count unique source documents vs stored chunks."""
        info = self.get_collection_info()
        if info.get("error"):
            return {"document_count": 0, "chunk_count": 0, "error": info["error"]}
        chunk_count = int(info.get("document_count") or 0)
        unique_ids = set()
        try:
            results = self.collection.get(include=["metadatas"])
            for meta in results.get("metadatas") or []:
                if isinstance(meta, dict) and meta.get("document_id"):
                    unique_ids.add(meta["document_id"])
        except Exception as e:
            return {
                "document_count": chunk_count,
                "chunk_count": chunk_count,
                "error": str(e),
            }
        if unique_ids:
            return {
                "document_count": len(unique_ids),
                "chunk_count": chunk_count,
            }
        return {
            "document_count": chunk_count,
            "chunk_count": chunk_count,
        }
    
    def list_documents(self, limit: int = 10) -> Dict:
        """
        列出向量库中的文档（用于调试）
        
        Args:
            limit: 返回的文档数量限制
            
        Returns:
            文档列表
        """
        try:
            # 获取所有文档
            results = self.collection.get(limit=limit)
            
            documents = []
            if results.get('ids') and len(results['ids']) > 0:
                for i in range(min(limit, len(results['ids']))):
                    doc_id = results['ids'][i]
                    doc_text = results['documents'][i] if results.get('documents') and i < len(results['documents']) else ""
                    doc_metadata = results['metadatas'][i] if results.get('metadatas') and i < len(results['metadatas']) else {}
                    
                    documents.append({
                        "id": doc_id,
                        "document_id": doc_metadata.get("document_id", "unknown"),
                        "chunk_index": doc_metadata.get("chunk_index", "N/A"),
                        "title": doc_metadata.get("title", "N/A"),
                        "preview": doc_text[:100] + "..." if len(doc_text) > 100 else doc_text
                    })
            
            return {
                "success": True,
                "total_count": self.collection.count(),
                "returned_count": len(documents),
                "documents": documents
            }
        except Exception as e:
            print(f"[VectorService] 列出文档失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def clear_collection(self) -> Dict:
        """
        清空集合中的所有向量
        
        Returns:
            操作结果
        """
        try:
            # 获取所有ID
            results = self.collection.get()
            if results['ids']:
                count = len(results['ids'])
                # 删除所有向量
                self.collection.delete(ids=results['ids'])
                return {
                    "success": True,
                    "deleted_count": count,
                    "message": f"已清空集合，删除了 {count} 个向量"
                }
            else:
                return {
                    "success": True,
                    "deleted_count": 0,
                    "message": "集合已为空，无需清空"
                }
        except Exception as e:
            print(f"[VectorService] 清空集合失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def reset_collection(self) -> Dict:
        """
        重置集合（删除并重新创建）
        
        Returns:
            操作结果
        """
        try:
            # 删除现有集合
            try:
                self.client.delete_collection(name=self.collection_name)
                print(f"[VectorService] 已删除集合: {self.collection_name}")
            except Exception as e:
                print(f"[VectorService] 删除集合时出现错误（可能集合不存在）: {e}")
            
            # 重新创建集合
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "法律文档向量库"}
            )
            print(f"[VectorService] 已重新创建集合: {self.collection_name}")
            
            return {
                "success": True,
                "message": "集合已重置（删除并重新创建）"
            }
        except Exception as e:
            print(f"[VectorService] 重置集合失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

