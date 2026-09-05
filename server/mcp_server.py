#!/usr/bin/env python3
"""
MCP服务端实现
实现MCP协议握手、资源列表、提示词模板列表等功能
"""

import json
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
import uuid

# 模拟数据存储
MOCK_DATA = {
    "law_regulations": {
        "民法典311条": """《中华人民共和国民法典》第三百一十一条

无处分权人将不动产或者动产转让给受让人的，所有权人有权追回；除法律另有规定外，符合下列情形的，受让人取得该不动产或者动产的所有权：

（一）受让人受让该不动产或者动产时是善意；
（二）以合理的价格转让；
（三）转让的不动产或者动产依照法律规定应当登记的已经登记，不需要登记的已经交付给受让人。

受让人依据前款规定取得不动产或者动产的所有权的，原所有权人有权向无处分权人请求损害赔偿。

当事人善意取得其他物权的，参照适用前两款规定。""",
        "合同法第52条": """《中华人民共和国合同法》第五十二条

有下列情形之一的，合同无效：

（一）一方以欺诈、胁迫的手段订立合同，损害国家利益；
（二）恶意串通，损害国家、集体或者第三人利益；
（三）以合法形式掩盖非法目的；
（四）损害社会公共利益；
（五）违反法律、行政法规的强制性规定。""",
        "劳动合同法第64条": """《中华人民共和国劳动合同法》第六十四条

被派遣劳动者有权在劳务派遣单位或者用工单位依法参加或者组织工会，维护自身的合法权益。""",
        "劳动合同法64条": """《中华人民共和国劳动合同法》第六十四条

被派遣劳动者有权在劳务派遣单位或者用工单位依法参加或者组织工会，维护自身的合法权益。""",
        "劳动合同的第六十四条": """《中华人民共和国劳动合同法》第六十四条

被派遣劳动者有权在劳务派遣单位或者用工单位依法参加或者组织工会，维护自身的合法权益。""",
        "民法典": """《中华人民共和国民法典》相关条文

如需查询具体条文，请提供准确的条文编号，例如：民法典311条、民法典第500条等。""",
        "合同法": """《中华人民共和国合同法》相关条文

如需查询具体条文，请提供准确的条文编号，例如：合同法第52条、合同法第107条等。""",
        "劳动合同法": """《中华人民共和国劳动合同法》相关条文

如需查询具体条文，请提供准确的条文编号，例如：劳动合同法第64条、劳动合同法第52条等。"""
    },
    "similar_cases": {
        "default": [
            """案例1：民间借贷纠纷案
案号：（2023）京0101民初12345号
裁判要点：原告与被告之间存在民间借贷关系，被告未按约定还款，应承担违约责任。
判决结果：支持原告诉讼请求，判令被告偿还本金及利息。""",
            """案例2：民间借贷纠纷案
案号：（2023）沪0101民初67890号
裁判要点：借贷双方约定的利率未超过合同成立时一年期贷款市场报价利率四倍的，应予支持。
判决结果：支持原告诉讼请求，利息按约定利率计算。"""
        ]
    },
    "contract_review_rules": [
        "合同主体审查：确认合同双方主体资格，检查营业执照、授权委托书等",
        "合同标的审查：明确标的物名称、规格、数量、质量等关键信息",
        "合同价款审查：确认价格、支付方式、支付时间、发票开具等条款",
        "违约责任审查：检查违约责任的约定是否明确、合理、可执行",
        "争议解决审查：确认争议解决方式（仲裁或诉讼）及管辖法院",
        "合同期限审查：明确合同生效时间、履行期限、终止条件",
        "保密条款审查：涉及商业秘密的合同应包含保密条款",
        "不可抗力条款审查：明确不可抗力的定义及处理方式"
    ]
}


class MCPServer:
    """MCP服务器实现"""
    
    def __init__(self):
        self.server_info = {
            "name": "ai-judge-mcp-server",
            "version": "1.0.0"
        }
        self.capabilities = {
            "resources": True,
            "prompts": True,
            "tools": True  # 启用工具支持
        }
        
        # 初始化会话服务
        try:
            from session_service import SessionService
            self.session_service = SessionService()
            print("[MCP Server] 会话服务初始化成功")
        except Exception as e:
            print(f"[MCP Server] 警告：会话服务初始化失败: {e}")
            self.session_service = None

        # RBAC / 认证
        self.rbac_store = None
        self.auth_service = None
        self.rbac_service = None
        self.rbac_api = None
        try:
            from auth_service import AuthService
            from http_rbac_api import RbacHttpApi
            from rbac_service import RbacService
            from rbac_store import RbacStore
            rbac_db = "./rbac.db"
            try:
                cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
                with open(cfg_path, "r", encoding="utf-8") as f:
                    _cfg = json.load(f)
                rbac_db = ((_cfg.get("auth") or {}).get("rbac_db")) or rbac_db
            except Exception:
                pass
            self.rbac_store = RbacStore(rbac_db)
            self.rbac_store.ensure_schema()
            self.rbac_store.seed_defaults()
            self.auth_service = AuthService(self.rbac_store)
            self.auth_service.ensure_seed_director()
            self.rbac_service = RbacService(self.rbac_store)
            self.rbac_api = RbacHttpApi(self.rbac_store, self.auth_service, self.rbac_service)
            print(f"[MCP Server] RBAC 服务初始化成功: {rbac_db}")
        except Exception as e:
            print(f"[MCP Server] 警告：RBAC 服务初始化失败: {e}")

        # 知识库（SQLite）；HTTP API 在 file_service 就绪后挂载
        self.kb_store = None
        self.kb_api = None
        try:
            from kb_store import KbStore
            self.kb_store = KbStore("./kb.db")
            self.kb_store.ensure_schema()
            print("[MCP Server] 知识库 KbStore 初始化成功: ./kb.db")
        except Exception as e:
            print(f"[MCP Server] 警告：知识库 KbStore 初始化失败: {e}")
        
        # 初始化向量化服务（使用超时机制，避免长时间阻塞）
        self.vector_service = None
        self._vector_service_init_thread = None
        self._vector_service_instance = [None]
        self._vector_service_init_error = [None]
        self._vector_service_init_lock = None
        try:
            import threading
            
            # 使用线程和超时机制初始化向量化服务
            self._vector_service_instance = [None]
            self._vector_service_init_error = [None]
            self._vector_service_init_lock = threading.Lock()
            
            def init_vector_service():
                try:
                    print("[VectorService] 后台线程开始初始化向量化服务...")
                    from vector_service import VectorService
                    service = VectorService()
                    with self._vector_service_init_lock:
                        self._vector_service_instance[0] = service
                    print("[VectorService] ✅ 后台线程完成向量化服务初始化")
                except Exception as e:
                    print(f"[VectorService] ❌ 后台线程初始化失败: {e}")
                    with self._vector_service_init_lock:
                        self._vector_service_init_error[0] = e
            
            # 在单独线程中初始化；导入也放线程内，避免主线程被 HF 下载卡住
            self._vector_service_init_thread = threading.Thread(target=init_vector_service, daemon=True)
            self._vector_service_init_thread.start()
            self._vector_service_init_thread.join(timeout=3)
            
            if self._vector_service_init_thread.is_alive():
                print("[MCP Server] ⚠️  警告：向量化服务初始化超时（30秒），服务器继续启动")
                print("[MCP Server] 提示：向量化服务将在后台继续初始化，完成后会自动可用")
                print("[MCP Server] 提示：如果网络无法访问huggingface.co，建议检查网络或使用本地缓存")
                # 不设置为None，允许后台线程完成后更新
                self.vector_service = None
            elif self._vector_service_init_error[0]:
                print(f"[MCP Server] ⚠️  警告：向量化服务初始化失败: {self._vector_service_init_error[0]}")
                print("[MCP Server] 提示：向量化功能将不可用，但其他功能（LLM、会话管理等）正常")
                self.vector_service = None
            elif self._vector_service_instance[0]:
                print("[MCP Server] ✅ 向量化服务初始化成功（30秒内完成）")
                self.vector_service = self._vector_service_instance[0]
                self._attach_fts_if_ready()
            else:
                print("[MCP Server] ⚠️  警告：向量化服务初始化返回None，跳过")
                self.vector_service = None
        except ImportError as e:
            print(f"[MCP Server] ⚠️  警告：无法导入向量化服务模块: {e}")
            print("[MCP Server] 提示：请安装依赖: pip3 install chromadb sentence-transformers")
            self.vector_service = None
        except Exception as e:
            print(f"[MCP Server] ⚠️  警告：向量化服务初始化异常: {e}")
            print("[MCP Server] 提示：向量化功能将不可用，但其他功能正常")
            self.vector_service = None
        
        # 初始化文件服务
        try:
            from file_service import FileService
            self.file_service = FileService()
            print("[MCP Server] 文件服务初始化成功")
        except Exception as e:
            print(f"[MCP Server] 警告：文件服务初始化失败: {e}")
            self.file_service = None

        # 知识库 HTTP API（依赖 auth/rbac + file/vector）
        if self.kb_store and self.auth_service and self.rbac_service:
            try:
                from http_kb_api import KbHttpApi
                self.kb_api = KbHttpApi(
                    self.kb_store,
                    self.auth_service,
                    self.rbac_service,
                    file_service=self.file_service,
                    vector_service=self.vector_service,
                )
                print("[MCP Server] 知识库 HTTP API 初始化成功")
            except Exception as e:
                print(f"[MCP Server] 警告：知识库 HTTP API 初始化失败: {e}")
                self.kb_api = None

        self.resources = self._init_resources()
        self.prompts = self._init_prompts()
    
    def _init_resources(self) -> List[Dict]:
        """初始化资源列表"""
        return [
            {
                "uri": "legal://doc_template",
                "name": "法律文书模板",
                "description": "从知识库要素文书检索模板：按模板名称匹配已入库的要素式法律文书正文，用于后续生成完整文书。",
                "mimeType": "text/plain"
            },
            {
                "uri": "legal://law_regulation",
                "name": "法律法规",
                "description": "检索法律法规：根据用户检索内容返回相关法律法规条文文本。",
                "mimeType": "text/plain"
            },
            {
                "uri": "legal://similar_cases",
                "name": "类案检索",
                "description": "检索类案：根据案情内容返回相似案例的裁判文书文本列表。",
                "mimeType": "text/plain"
            },
            {
                "uri": "legal://contract_review_rules",
                "name": "合同审查规则",
                "description": "检索合同审查规则：返回静态的合同审查规则列表，用于合同风险识别。",
                "mimeType": "text/plain"
            }
        ]
    
    def _init_prompts(self) -> List[Dict]:
        """初始化提示词模板列表"""
        return [
            {
                "name": "gen_legal_doc_guide",
                "description": "生成法律文书提示词指南：指导 LLM 按规范步骤生成法律文书的工作流说明。"
            },
            {
                "name": "contract_review_guide",
                "description": "合同审查提示词指南：指导 LLM 按规则审查合同条款并输出风险建议的工作流说明。"
            },
            {
                "name": "judge_work_guide",
                "description": "法官工作指南：指导 AI 法官以法官思维和心理学家同理心，通过对话引导用户提供信息，逐步梳理案情，并生成模拟裁判文书。"
            }
        ]
    
    def handle_request(self, request: Dict) -> Optional[Dict]:
        """处理MCP请求"""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
        
        try:
            if method == "initialize":
                return self._handle_initialize(request_id, params)
            elif method == "resources/list":
                return self._handle_resources_list(request_id)
            elif method == "resources/read":
                return self._handle_resource_read(request_id, params)
            elif method == "tools/list":
                return self._handle_tools_list(request_id)
            elif method == "tools/call":
                return self._handle_tool_call(request_id, params)
            elif method == "prompts/list":
                return self._handle_prompts_list(request_id)
            elif method == "prompts/get":
                return self._handle_prompt_get(request_id, params)
            elif method == "notifications/initialized":
                return None  # 通知不需要响应
            else:
                return self._error_response(request_id, -32601, f"Method not found: {method}")
        except Exception as e:
            return self._error_response(request_id, -32603, f"Internal error: {str(e)}")
    
    def _handle_initialize(self, request_id: Any, params: Dict) -> Dict:
        """处理初始化请求"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": self.capabilities,
                "serverInfo": self.server_info
            }
        }
    
    def _handle_resources_list(self, request_id: Any) -> Dict:
        """处理资源列表请求"""
        print(f"[DEBUG] 处理resources/list请求，资源数量: {len(self.resources)}")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "resources": self.resources
            }
        }
    
    def _attach_fts_if_ready(self) -> None:
        """Mount KbFtsIndex on vector_service when both vs and kb_store are ready."""
        if not self.vector_service or not self.kb_store:
            return
        try:
            self.vector_service.attach_fts(self.kb_store.db_path)
        except Exception as e:
            print(f"[MCP Server] FTS attach failed: {e}")
            return
        try:
            fts = getattr(self.vector_service, "fts", None)
            if fts and fts.count() == 0:
                chroma_n = self.vector_service.collection.count()
                if chroma_n and int(chroma_n) > 0:
                    print("[MCP Server] FTS empty, rebuilding from Chroma...")
                    print(self.vector_service.rebuild_fts_from_chroma())
        except Exception as e:
            print(f"[MCP Server] FTS rebuild skipped: {e}")

    def _init_tools(self) -> List[Dict]:
        """初始化工具列表"""
        tools = []
        
        # 检查向量化服务是否可用，如果后台初始化已完成，更新服务实例
        if not self.vector_service and self._vector_service_init_thread:
            # 检查后台初始化线程是否已完成
            if not self._vector_service_init_thread.is_alive():
                # 线程已完成，检查是否有可用的服务实例
                if self._vector_service_init_lock:
                    with self._vector_service_init_lock:
                        if self._vector_service_instance[0]:
                            print("[MCP Server] ✅ 检测到后台初始化完成，启用向量化服务")
                            self.vector_service = self._vector_service_instance[0]
                            self._attach_fts_if_ready()
                        elif self._vector_service_init_error[0]:
                            print(f"[MCP Server] ⚠️  后台初始化失败: {self._vector_service_init_error[0]}")
        
        # 向量化文档工具
        if self.vector_service:
            tools.append({
                "name": "vectorize_document",
                "description": "将文档向量化并存储到ChromaDB中",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "文档唯一标识符"
                        },
                        "text": {
                            "type": "string",
                            "description": "要向量化的文档文本内容"
                        },
                        "metadata": {
                            "type": "object",
                            "description": "文档元数据（可选）",
                            "properties": {
                                "title": {"type": "string"},
                                "source": {"type": "string"},
                                "category": {"type": "string"}
                            }
                        }
                    },
                    "required": ["document_id", "text"]
                }
            })
            
            tools.append({
                "name": "search_documents",
                "description": "在向量库中搜索相似文档",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询文本"
                        },
                        "n_results": {
                            "type": "integer",
                            "description": "返回结果数量（默认5）",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            })
            
            tools.append({
                "name": "delete_document",
                "description": "从向量库中删除文档",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "要删除的文档ID"
                        }
                    },
                    "required": ["document_id"]
                }
            })
            
            tools.append({
                "name": "get_vector_db_info",
                "description": "获取向量数据库信息",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            })
            
            tools.append({
                "name": "clear_vector_db",
                "description": "清空向量数据库中的所有向量（用于重新向量化）",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "description": "清空所有向量，返回删除的向量数量"
                }
            })
            
            tools.append({
                "name": "reset_vector_db",
                "description": "重置向量数据库（删除并重新创建集合）",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "description": "删除现有集合并重新创建，用于完全重置向量库"
                }
            })
            
            tools.append({
                "name": "list_vector_documents",
                "description": "列出向量库中的文档（用于调试和查看向量库内容）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "返回的文档数量限制（默认10）",
                            "default": 10
                        }
                    }
                }
            })
        
        return tools
    
    def _handle_tools_list(self, request_id: Any) -> Dict:
        """处理工具列表请求"""
        print(f"[DEBUG] 处理tools/list请求")
        tools = self._init_tools()
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": tools
            }
        }
    
    def _handle_tool_call(self, request_id: Any, params: Dict) -> Dict:
        """处理工具调用请求"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        print(f"[DEBUG] 调用工具: {tool_name}, 参数: {arguments}")
        
        # 检查工具是否存在
        available_tools = [t.get("name") for t in self._init_tools()]
        if tool_name not in available_tools:
            return self._error_response(
                request_id,
                -32601,
                f"工具不存在: {tool_name}。可用工具: {', '.join(available_tools) if available_tools else '无（向量化服务未初始化）'}"
            )
        
        # 检查向量化服务是否可用，如果后台线程已完成初始化，更新服务实例
        if not self.vector_service:
            # 检查后台初始化线程是否已完成
            if self._vector_service_init_thread and not self._vector_service_init_thread.is_alive():
                # 线程已完成，检查是否有可用的服务实例
                if self._vector_service_init_lock:
                    with self._vector_service_init_lock:
                        if self._vector_service_instance[0]:
                            print("[MCP Server] ✅ 检测到后台初始化完成，启用向量化服务")
                            self.vector_service = self._vector_service_instance[0]
                            self._attach_fts_if_ready()
                        elif self._vector_service_init_error[0]:
                            return self._error_response(
                                request_id, 
                                -32603, 
                                f"向量化服务初始化失败: {self._vector_service_init_error[0]}"
                            )
            
            # 如果仍然不可用，返回错误
            if not self.vector_service:
                if self._vector_service_init_thread and self._vector_service_init_thread.is_alive():
                    return self._error_response(
                        request_id, 
                        -32603, 
                        "向量化服务正在初始化中，请稍后重试（通常需要30-60秒）"
                    )
                else:
                    return self._error_response(
                        request_id, 
                        -32603, 
                        "向量化服务未初始化。请安装依赖: pip3 install chromadb sentence-transformers"
                    )
        
        try:
            if tool_name == "vectorize_document":
                document_id = arguments.get("document_id")
                text = arguments.get("text")
                metadata = arguments.get("metadata", {})
                
                if not document_id or not text:
                    return self._error_response(
                        request_id,
                        -32602,
                        "缺少必需参数: document_id 或 text"
                    )
                
                result = self.vector_service.add_document(
                    document_id=document_id,
                    text=text,
                    metadata=metadata
                )
                
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False)
                            }
                        ]
                    }
                }
            
            elif tool_name == "search_documents":
                query = arguments.get("query")
                n_results = arguments.get("n_results", 5)
                
                if not query:
                    return self._error_response(
                        request_id,
                        -32602,
                        "缺少必需参数: query"
                    )
                
                results = self.vector_service.search(query, n_results)
                
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(results, ensure_ascii=False, indent=2)
                            }
                        ]
                    }
                }
            
            elif tool_name == "delete_document":
                document_id = arguments.get("document_id")
                
                if not document_id:
                    return self._error_response(
                        request_id,
                        -32602,
                        "缺少必需参数: document_id"
                    )
                
                result = self.vector_service.delete_document(document_id)
                
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False)
                            }
                        ]
                    }
                }
            
            elif tool_name == "get_vector_db_info":
                info = self.vector_service.get_collection_info()
                
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(info, ensure_ascii=False, indent=2)
                            }
                        ]
                    }
                }
            
            elif tool_name == "clear_vector_db":
                result = self.vector_service.clear_collection()
                
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False, indent=2)
                            }
                        ]
                    }
                }
            
            elif tool_name == "reset_vector_db":
                result = self.vector_service.reset_collection()
                
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False, indent=2)
                            }
                        ]
                    }
                }
            
            elif tool_name == "list_vector_documents":
                limit = arguments.get("limit", 10)
                result = self.vector_service.list_documents(limit=limit)
                
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False, indent=2)
                            }
                        ]
                    }
                }
            
            else:
                return self._error_response(
                    request_id,
                    -32601,
                    f"未知工具: {tool_name}"
                )
                
        except Exception as e:
            print(f"[ERROR] 工具调用失败: {e}")
            import traceback
            traceback.print_exc()
            return self._error_response(
                request_id,
                -32603,
                f"工具调用失败: {str(e)}"
            )
    
    def _handle_resource_read(self, request_id: Any, params: Dict) -> Dict:
        """处理资源读取请求"""
        uri = params.get("uri")
        arguments = params.get("arguments", {})
        
        print(f"[DEBUG] 资源读取请求 - URI: {uri}, 参数: {arguments}")
        
        # 如果URI不是标准格式，尝试从URI中提取信息并转换为标准格式
        if uri and not uri.startswith("legal://"):
            print(f"[DEBUG] URI格式不标准，尝试转换: {uri}")
            # 尝试识别资源类型
            if uri.startswith("laws/") or (uri.startswith("法律/") and "/" in uri):
                # 这是一个法律法规查询请求（laws/法律名称/条文编号格式）
                uri = "legal://law_regulation"
                # 从URI中提取查询内容
                if not arguments.get("query"):
                    # 例如: laws/中华人民共和国劳动合同法/52
                    # 或者: 法律/劳动合同法/52
                    parts = uri.split("/")
                    if len(parts) >= 3:
                        # 提取法律名称和条文编号
                        law_name = parts[1]  # 中华人民共和国劳动合同法
                        article_num = parts[2]  # 52
                        # 构建查询字符串
                        query = f"{law_name}{article_num}条"
                        # 尝试简化法律名称匹配
                        if "劳动合同法" in law_name:
                            query = f"劳动合同法{article_num}条"
                        elif "合同法" in law_name:
                            query = f"合同法第{article_num}条"
                        elif "民法典" in law_name:
                            query = f"民法典{article_num}条"
                        arguments["query"] = query
                        print(f"[DEBUG] 从URI中提取查询内容: {query}")
                    elif len(parts) == 2:
                        # 只有法律名称，没有条文编号
                        query = parts[1]
                        arguments["query"] = query
                        print(f"[DEBUG] 从URI中提取查询内容: {query}")
            elif uri.startswith("doc_template/") or uri.startswith("legal_document_templates") or "模板" in uri or "文书" in uri or "template" in uri.lower():
                # 这是一个文档模板请求
                original_uri = params.get("uri", uri)  # 保存原始URI用于提取模板名称
                uri = "legal://doc_template"
                # 尝试从URI路径中提取模板名称
                # 同时支持 template_name 和 document_type 参数名
                template_name = arguments.get("template_name") or arguments.get("document_type")
                if not template_name:
                    # 从URI中提取模板名称
                    # 例如: doc_template/民间借贷纠纷起诉状
                    # 或者: legal_document_templates/civil_complaint/private_lending
                    # 或者: legal_document_templates/民间借贷/起诉状
                    parts = original_uri.split("/")
                    if len(parts) > 1:
                        # 取最后一部分或组合
                        potential_name = parts[-1]
                        # 尝试匹配中文模板名称
                        if "civil_complaint" in original_uri or "private_lending" in original_uri or "民间借贷" in original_uri:
                            potential_name = "民间借贷纠纷起诉状"
                        elif "divorce" in original_uri or "离婚" in original_uri:
                            potential_name = "离婚协议书"
                        elif "labor" in original_uri or "劳动" in original_uri:
                            potential_name = "劳动合同"
                        elif "rent" in original_uri or "租赁" in original_uri:
                            potential_name = "房屋租赁合同"
                        if potential_name:
                            arguments["template_name"] = potential_name
                            print(f"[DEBUG] 从URI中提取模板名称: {potential_name}")
                elif template_name:
                    # 如果参数中已经有模板名称（无论是template_name还是document_type），直接使用
                    arguments["template_name"] = template_name
                    print(f"[DEBUG] 使用参数中的模板名称: {template_name}")
            elif uri.startswith("laws/") or ("法律" in uri and "/" in uri) or "法律法规" in uri or "法规" in uri or "条" in uri:
                # 这是一个法律法规查询请求
                uri = "legal://law_regulation"
                # 尝试从URI中提取查询内容
                if not arguments.get("query"):
                    # 如果是 laws/法律名称/条文编号 格式
                    original_uri = params.get("uri", "")
                    if original_uri.startswith("laws/"):
                        parts = original_uri.split("/")
                        if len(parts) >= 3:
                            law_name = parts[1]
                            article_num = parts[2]
                            # 构建查询字符串
                            if "劳动合同法" in law_name:
                                query = f"劳动合同法{article_num}条"
                            elif "合同法" in law_name:
                                query = f"合同法第{article_num}条"
                            elif "民法典" in law_name:
                                query = f"民法典{article_num}条"
                            else:
                                query = f"{law_name}{article_num}条"
                            arguments["query"] = query
                            print(f"[DEBUG] 从URI中提取查询内容: {query}")
                        elif len(parts) == 2:
                            query = parts[1]
                            arguments["query"] = query
                            print(f"[DEBUG] 从URI中提取查询内容: {query}")
                    else:
                        # 从URI中提取查询关键词
                        query = original_uri.replace("法律法规数据库/", "").replace("法律/", "").replace("法规/", "")
                        if query:
                            arguments["query"] = query
                            print(f"[DEBUG] 从URI中提取查询内容: {query}")
            elif "案例" in uri or "类案" in uri:
                uri = "legal://similar_cases"
            elif "合同" in uri and "审查" in uri:
                uri = "legal://contract_review_rules"
        
        if uri == "legal://doc_template":
            # 支持 template_name 和 document_type 两种参数名；内容来自知识库要素文书
            template_name = arguments.get("template_name") or arguments.get("document_type") or ""
            print(f"[DEBUG] 文档模板查询 - template_name: {template_name}, arguments: {arguments}")
            try:
                from kb_template_resolve import resolve_template_text

                text, matched, available = resolve_template_text(
                    template_name,
                    kb_store=getattr(self, "kb_store", None),
                    file_service=getattr(self, "file_service", None),
                    vector_service=getattr(self, "vector_service", None),
                )
            except Exception as exc:
                print(f"[DEBUG] 知识库模板解析失败: {exc}")
                return self._error_response(
                    request_id, -32603, f"知识库模板读取失败: {exc}"
                )

            if text:
                label = matched or template_name
                print(f"[DEBUG] 知识库模板命中: {label}")
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": "text/plain",
                                "text": text,
                            }
                        ]
                    },
                }

            if available:
                avail = "、".join(available[:30])
                msg = (
                    f"未在知识库要素文书中找到匹配模板：{template_name or '（未指定）'}\n"
                    f"当前可用模板：{avail}"
                )
            else:
                msg = (
                    f"未在知识库要素文书中找到匹配模板：{template_name or '（未指定）'}\n"
                    "当前知识库无可用要素文书，请先在管理端「要素文书」上传模板。"
                )
            return self._error_response(request_id, -32602, msg)

        elif uri == "legal://law_regulation":
            # 从多个可能的位置提取query参数
            query = ""
            if "arguments" in params and isinstance(params["arguments"], dict):
                query = params["arguments"].get("query", "")
            # 如果URI中包含query参数（如 legal://law_regulation?query=xxx）
            if not query and "?" in uri:
                uri_parts = uri.split("?")
                if len(uri_parts) > 1:
                    query_params = uri_parts[1]
                    if "query=" in query_params:
                        query = query_params.split("query=")[1].split("&")[0]
                        # URL解码
                        import urllib.parse
                        query = urllib.parse.unquote(query)
            
            if not query:
                query = ""
            
            print(f"[DEBUG] law_regulation查询 - query: '{query}', uri: '{uri}'")
            
            # 首先尝试精确匹配
            if query in MOCK_DATA["law_regulations"]:
                print(f"[DEBUG] 精确匹配成功: '{query}'")
                regulation = MOCK_DATA["law_regulations"][query]
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": "text/plain",
                                "text": regulation
                            }
                        ]
                    }
                }
            
            # 尝试模糊匹配：支持多种格式
            # 例如："劳动合同的第六十四条" -> "劳动合同法第64条" -> "劳动合同法64条"
            import re
            
            # 中文数字到阿拉伯数字的转换字典
            chinese_digit_map = {
                "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                "六": 6, "七": 7, "八": 8, "九": 9, "十": 10
            }
            
            def chinese_to_arabic(chinese_num_str):
                """将中文数字转换为阿拉伯数字"""
                if not chinese_num_str:
                    return None
                # 处理"六十四"这种格式
                if "十" in chinese_num_str:
                    parts = chinese_num_str.split("十")
                    if len(parts) == 2:
                        tens = chinese_digit_map.get(parts[0], 0)
                        ones = chinese_digit_map.get(parts[1], 0)
                        if tens == 0:  # "十四" -> 14
                            return 10 + ones
                        else:  # "六十四" -> 64
                            return tens * 10 + ones
                    elif len(parts) == 1:
                        # "十" 或 "十X"
                        if parts[0]:
                            return 10 + chinese_digit_map.get(parts[0], 0)
                        else:
                            return 10
                else:
                    # 单个数字
                    return chinese_digit_map.get(chinese_num_str, None)
            
            # 尝试匹配各种可能的key格式
            possible_keys = []
            if "劳动合同" in query or "劳动合同法" in query:
                # 先尝试提取阿拉伯数字
                numbers = re.findall(r'\d+', query)
                # 如果没有阿拉伯数字，尝试提取中文数字
                if not numbers:
                    # 匹配"第六十四"、"六十四"等格式
                    chinese_num_match = re.search(r'第?([一二三四五六七八九十]+)', query)
                    if chinese_num_match:
                        chinese_num = chinese_num_match.group(1)
                        arabic_num = chinese_to_arabic(chinese_num)
                        if arabic_num:
                            numbers = [str(arabic_num)]
                
                if numbers:
                    num = numbers[0]
                    possible_keys = [
                        f"劳动合同法第{num}条",
                        f"劳动合同法{num}条",
                        f"劳动合同的第{num}条",
                        f"劳动合同的{num}条",
                        query  # 原始查询
                    ]
                    print(f"[DEBUG] 劳动合同法查询，提取数字: {num}, 可能的keys: {possible_keys}")
            elif "合同法" in query and "劳动合同" not in query:
                numbers = re.findall(r'\d+', query)
                if numbers:
                    num = numbers[0]
                    possible_keys = [
                        f"合同法第{num}条",
                        f"合同法{num}条",
                        query
                    ]
            elif "民法典" in query:
                numbers = re.findall(r'\d+', query)
                if numbers:
                    num = numbers[0]
                    possible_keys = [
                        f"民法典{num}条",
                        f"民法典第{num}条",
                        query
                    ]
            else:
                possible_keys = [query]
            
            # 尝试匹配
            print(f"[DEBUG] 尝试匹配查询: '{query}', 可能的keys: {possible_keys}")
            for key in possible_keys:
                if key in MOCK_DATA["law_regulations"]:
                    regulation = MOCK_DATA["law_regulations"][key]
                    print(f"[DEBUG] 模糊匹配成功: '{query}' -> '{key}'")
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "contents": [
                                {
                                    "uri": uri,
                                    "mimeType": "text/plain",
                                    "text": regulation
                                }
                            ]
                        }
                    }
            
            # 如果都匹配不上，返回默认提示
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "text/plain",
                            "text": f"未找到关于'{query}'的具体法规，请提供更准确的法规编号或关键词。\n\n提示：支持的格式包括：\n- 劳动合同法第64条\n- 劳动合同法64条\n- 劳动合同的第六十四条\n- 合同法第52条\n- 民法典311条"
                        }
                    ]
                }
            }
        
        elif uri == "legal://similar_cases":
            case_description = params.get("arguments", {}).get("case_description", "")
            cases = MOCK_DATA["similar_cases"].get("default", [])
            cases_text = "\n\n".join(cases)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "text/plain",
                            "text": f"根据案情描述：{case_description}\n\n找到以下相似案例：\n\n{cases_text}"
                        }
                    ]
                }
            }
        
        elif uri == "legal://contract_review_rules":
            rules = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(MOCK_DATA["contract_review_rules"])])
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "text/plain",
                            "text": f"合同审查规则：\n\n{rules}"
                        }
                    ]
                }
            }
        
        else:
            # 如果URI完全不匹配，尝试更智能的匹配
            print(f"[DEBUG] URI不匹配，尝试智能匹配: {uri}")
            
            # 如果URI包含文档模板相关关键词
            if uri.startswith("doc_template/") or uri.startswith("legal_document_templates") or "template" in uri.lower() or "模板" in uri or "文书" in uri:
                # 提取模板名称
                template_name = None
                # 首先尝试从参数中获取
                if "template_name" in arguments:
                    template_name = arguments["template_name"]
                elif "document_type" in arguments:
                    template_name = arguments["document_type"]
                
                # 如果参数中没有，从URI中提取
                if not template_name:
                    if "/" in uri:
                        parts = uri.split("/")
                        # 尝试从路径中提取模板名称
                        if uri.startswith("doc_template/"):
                            # doc_template/民间借贷纠纷起诉状 格式
                            template_name = parts[-1]  # 直接使用最后一部分作为模板名称
                        elif "civil_complaint" in uri or "private_lending" in uri or "民间借贷" in uri:
                            template_name = "民间借贷纠纷起诉状"
                        elif "divorce" in uri or "离婚" in uri:
                            template_name = "离婚协议书"
                        elif "labor" in uri or "劳动" in uri:
                            template_name = "劳动合同"
                        elif "rent" in uri or "租赁" in uri:
                            template_name = "房屋租赁合同"
                        else:
                            template_name = parts[-1]  # 取最后一部分
                    else:
                        template_name = uri
                
                print(f"[DEBUG] 智能匹配：将URI '{uri}' 转换为文档模板查询，template_name: '{template_name}'")
                # 递归调用，使用标准URI，保留原始参数
                new_arguments = arguments.copy()
                new_arguments["template_name"] = template_name
                return self._handle_resource_read(request_id, {
                    "uri": "legal://doc_template",
                    "arguments": new_arguments
                })
            
            # 如果URI包含"法律法规"相关关键词，尝试作为法律法规查询
            elif uri.startswith("laws/") or "法律法规" in uri or ("法律" in uri and "/" in uri) or "法规" in uri or "条" in uri:
                # 提取查询内容
                query = uri
                # 如果是 laws/法律名称/条文编号 格式
                if uri.startswith("laws/"):
                    parts = uri.split("/")
                    if len(parts) >= 3:
                        law_name = parts[1]
                        article_num = parts[2]
                        # 构建查询字符串
                        if "劳动合同法" in law_name:
                            query = f"劳动合同法{article_num}条"
                        elif "合同法" in law_name:
                            query = f"合同法第{article_num}条"
                        elif "民法典" in law_name:
                            query = f"民法典{article_num}条"
                        else:
                            query = f"{law_name}{article_num}条"
                    elif len(parts) == 2:
                        query = parts[1]
                else:
                    # 尝试清理URI格式
                    query = query.replace("法律法规数据库/", "").replace("法律/", "").replace("法规/", "")
                    if "/" in query:
                        parts = query.split("/")
                        query = parts[-1]  # 取最后一部分
                
                print(f"[DEBUG] 智能匹配：将URI '{uri}' 转换为法律法规查询，query: '{query}'")
                # 递归调用，使用标准URI
                return self._handle_resource_read(request_id, {
                    "uri": "legal://law_regulation",
                    "arguments": {"query": query}
                })
            
            return self._error_response(request_id, -32602, f"Resource not found: {uri}")
    
    def _handle_prompts_list(self, request_id: Any) -> Dict:
        """处理提示词模板列表请求"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "prompts": self.prompts
            }
        }
    
    def _handle_prompt_get(self, request_id: Any, params: Dict) -> Dict:
        """处理提示词模板获取请求"""
        name = params.get("name", "")
        
        if name == "gen_legal_doc_guide":
            guide = """生成法律文书提示词指南：

1. 首先检索并获取对应的法律文书模板
2. 分析模板中的占位符，提取需要填充的信息
3. 根据用户提供的信息，填充模板占位符
4. 检查文书的格式规范和法律术语使用
5. 确保文书符合相关法律法规要求
6. 生成完整的法律文书

注意事项：
- 保持法律文书的正式性和规范性
- 确保所有必要信息都已填写
- 检查日期、金额等关键信息的准确性
- 使用标准的法律术语和表达方式"""
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "description": "生成法律文书提示词指南",
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": guide
                            }
                        }
                    ]
                }
            }
        
        elif name == "contract_review_guide":
            guide = """合同审查提示词指南：

1. 首先检索合同审查规则列表
2. 逐条检查合同条款是否符合审查规则
3. 识别合同中的潜在风险和问题
4. 检查合同主体、标的、价款、违约责任等关键条款
5. 评估合同条款的合法性和可执行性
6. 提供具体的修改建议和风险提示

审查重点：
- 合同主体资格和授权
- 合同标的的明确性
- 价格和支付条款
- 违约责任和争议解决
- 合同期限和终止条件
- 保密和不可抗力条款"""
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "description": "合同审查提示词指南",
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": guide
                            }
                        }
                    ]
                }
            }
        
        elif name == "judge_work_guide":
            guide = """# 角色 
你是{#InputSlot placeholder="角色设定，比如xx领域的专家"#}法官和心理学家，善于解析案情并同用户同理心{#/InputSlot#}
你的目标是{#InputSlot placeholder="希望模型执行什么任务，达成什么目标"#}以法官的思维方式和心理学家的同理心，通过简洁、自然的对话（一次只提一个问题，用户回答后再继续），引导用户提供必要信息，逐步梳理案情，并最终基于分析预测性地生成一份模拟裁判文书。{#/InputSlot#}

## 工作步骤 
1. {#InputSlot placeholder="工作流程1的一句话概括"#}分析材料并识别出案由{#/InputSlot#} 
2. 当事人是否适格 
3. {#InputSlot placeholder="工作流程3的一句话概括"#}分析证据齐全{#/InputSlot#}
4. 核实证据三性
5.争议焦点归纳
6.AI法官最后提问
7.类案检索
8.输出标准裁判文书
9.判后答疑

### 第一步 {#InputSlot placeholder="工作流程1标题"#}分析材料并识别出案由
1.先解析用户输入了哪些信息（比如当事人信息、诉讼请求、事实与理由、原告证据材料、被告答辩事项和证据等），将关键信息逐项列出展示给用户，如用户输入内容过于简单则引导用户进一步输入案情信息 2.明确识别出用户所咨询问题是哪一种案由（比如"民间借贷纠纷"） 3.明确案由后进入下一步。

### 第二步  当事人是否适格{#/InputSlot#} 
分析当事人是否具有完全民事能力，不要直接问"精神疾病"，否则会让用户被冒犯到，可以换个方式问年龄或者行为能力，比如"请问原告/被告[姓名]的年龄是多少？" 或识别到未成年或特别情况下问"是否有监护人或者法定代理人？"或识别到是合同的情况下不确定当事人适格时可以提问是否是"合同相对方？"。明确"适格"不仅指行为能力，还包括诉讼主体资格（如合同相对方）。如果用户输入的案情中相关当事人具有工作则默认该当事人具备民事行为能力。如果当事人不具备民事行为能力则提示用户依据相关法律诉讼请求会被裁定驳回。

### 第三步 {#InputSlot placeholder="工作流程2标题"#}分析必要证据齐全
明确核心证据： 根据已识别的案由，明确该类型案件必不可少的核心证据清单。例如：

民间借贷：借据/欠条、转账凭证（核心）；催款记录（辅助）。

离婚：结婚证（核心）；涉及财产分割需财产证明、涉及抚养权需子女情况证明（核心）。

交通事故：事故认定书（核心）；医疗费票据、伤残鉴定（如涉及）。

逐项核对： 将用户已提供的证据与核心证据清单逐项对比。

清晰提示缺失： 对于缺失的核心证据，明确、具体地告知用户："要证明[关键事实，如借款关系存在]，通常需要提供[缺失的证据名称，如银行转账记录]。您是否持有这份证据？" （符合"问一个"原则）。

处理用户回应： 如果用户回答"有"，则视为持有（如提示词所述）；如果回答"没有"或"不确定"，则在后续分析（如争议焦点、判决预测）中考虑该证据缺失可能导致的不利后果（如主张不被支持），并在最终文书中说明。

区分核心与辅助： 对于辅助性证据，可以稍后（如在"证据三性"或"争议焦点"步骤）提及或询问，避免初期信息过载。{#/InputSlot#} 
{#InputSlot placeholder="工作流程步骤2的具体工作要求和举例说明，可以分点列出希望在本步骤做哪些事情，需要完成什么阶段性的工作目标"#}{#/InputSlot#}
### 第四步 {#InputSlot placeholder="工作流程3标题"#}核实证据三性{#/InputSlot#}
{#InputSlot placeholder="工作流程步骤3的具体工作要求和举例说明，可以分点列出希望在本步骤做哪些事情，需要完成什么阶段性的工作目标"#}对于用于提交的证据材料，1.逐项向用户提问真实性，如果用户对某项证据的真实性存疑则直接排除该证据；如用户对某项证据的真实性是确认的，则AI法官即认为是真实 2.逐项分析证据与案由是否有关联性，如果不存在关联性则排除该证据  3.逐项询问证据合法性，给用户列举出常见的不合法取证行为，比如录音是偷拍，如果通过不合法方式取得则应予以排除。例如：
真实性： 提问方式要自然："您确认您提供的'[证据名称，如微信聊天记录截图]'是真实的、未经修改的吗？"

关联性： AI可以主动分析："据我的经验来看这份'[证据名称]'看起来是为了证明[某个事实点]，与本案的[案由]有关联，对此你是否有异议？" (用户通常只需确认，除非有特殊异议)。

合法性： 提问更侧重方式："这份'[证据名称，如录音文件]'是通过什么方式取得的？（例如：双方当面交谈时录的？电话录音？）" 然后AI根据回答判断合法性风险（如"如果是未经对方同意的偷录，在特定情况下可能不被采纳…"）。明确告知非法证据会被排除。 

###  第五步  争议焦点归纳
务必清晰地向用户复述确认："根据目前的信息，本案可能的争议焦点（如果没有答辩则说明在没有答辩的情况下可能存在的争议焦点）是：1. [焦点一，如借款是否实际发生]；2. [焦点二，如利息计算是否合法]；3. [焦点三，是否已过诉讼时效]。您看这样归纳是否准确？或者您认为还有别的关键分歧点吗？" 这既是反馈也是进一步引导 

###  第六步  AI法官最后提问
梳理案情时间线，输出事件时间历史图，并明确相关证据的有效性，然后询用户对本案最后是否还有补充说明？如果有补充，若用户补充的有新证据，则需要以第四步的方式核实新证据的三性；若用户想推翻之前陈述的事实，则需要质询推翻的原因，如果原因与最终的裁判结果有必然联系，则允许用户推翻之前的陈述事实；若用户没有补充则自动进入类案检索步骤。提问要极其简洁直接："关于这个案件，您还有任何其他信息需要补充说明吗？（例如新证据或对之前说的内容有修正）" 


### 第七步  类案检索
明确告知： 在检索前或后明确告知用户："现在我将根据本案的案由([案由])和关键事实([简述1-2个核心事实])，检索最高人民法院发布的类似指导案例供参考。" 

输出格式： 检索结果输出应简洁，包括：案例名称/编号、核心裁判观点/规则、与本案的相似点。例如："参考案例：(202X)最高法民申XXXX号。该案认定：[核心规则]。这与您案件中[相似点]的情况类似。"

根据案由及现有的证据优先从最高院指导案例库检索相似案例，如果有同案则同判。 最后加一句说明："模拟裁判文书将综合本案所有事实证据、法律规定和指导案例作出如下裁判：（ 此处加一条横线用户隔开上述内容与下面的裁判文书，然后自动进入第八步输出裁判文书）"。{#/InputSlot#}

### 第八步  输出标准裁判文书
 模型根据上文收集的案情信息基于模型能力输出裁判意见文书，对于程序性事项出具完整的模拟裁定书（比如当事人不适格、管辖异议），对于实体权利事项出具完整的模拟判决书。具体要求：1)首行标题为谁与谁XXX纠纷案"模拟裁定书"或"模拟判决书"，比如"张三和李四民间借贷纠纷案民事判决书" 2)在1）的名称下输出案由和案号，案号值为"（年份）+得理+号码"，其中年份取值为当前的年份，比如2025，得理为固定字样，号码值为时间戳，最终输出效果示例："案由 （2025）得理1752547191号" 3)将用户输入的案情相关信息填入到最终的裁判文书中 4)如果用户自己没有写法律依据，请你自动写出关联的法律依据 5）最后的审判长名字为"审判长：得理AI"，判决日期格式为大写的当前的年月日，例如"二〇二四年八月十八日"。
 完整输出裁判文书后自动画出一条横线，然后自动进入下一步。

### 第九步  判后答疑
生成文书后空三行，然后延迟2秒钟再主动提示用户"如果您对于裁判结果有疑问，我可以判后答疑哦～" """
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "description": "法官工作指南",
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": guide
                            }
                        }
                    ]
                }
            }
        
        else:
            return self._error_response(request_id, -32602, f"Prompt not found: {name}")
    
    def _error_response(self, request_id: Any, code: int, message: str) -> Dict:
        """生成错误响应"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message
            }
        }


# HTTP服务器包装（用于Web客户端调用）
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.parse
import urllib.request
import threading

# 从config.json加载LLM配置
def load_llm_config():
    """加载LLM配置"""
    import os
    # 尝试多个可能的路径
    config_paths = [
        'config.json',  # 当前目录
        '../config.json',  # 上级目录
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')  # 项目根目录
    ]
    
    for config_path in config_paths:
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    llm_config = config.get('llm', {})
                    
                    # 修复timeout单位：如果大于100，认为是毫秒，转换为秒
                    timeout = llm_config.get('timeout', 60)
                    if timeout > 100:
                        timeout_seconds = timeout / 1000
                        llm_config['timeout'] = timeout_seconds
                        print(f"[LLM配置] timeout已从毫秒转换为秒: {timeout}ms -> {timeout_seconds}s")
                    
                    print(f"[LLM配置] 从 {config_path} 加载配置成功")
                    print(f"[LLM配置] API URL: {llm_config.get('api_url', '未配置')}")
                    print(f"[LLM配置] Model: {llm_config.get('model', '未配置')}")
                    print(f"[LLM配置] API Key: {'已配置' if llm_config.get('api_key') else '未配置'}")
                    print(f"[LLM配置] Timeout: {llm_config.get('timeout', 60)}秒")
                    print(f"[LLM配置] Max Retries: {llm_config.get('max_retries', 3)}")
                    return llm_config
        except Exception as e:
            print(f"[LLM配置] 尝试从 {config_path} 加载失败: {e}")
            continue
    
    # 如果所有路径都失败，返回默认配置或空配置
    print("[LLM配置] 警告：无法从任何路径加载config.json，使用默认配置")
    return {
        'api_url': 'https://api.deepseek.com/v1/chat/completions',
        'api_key': '',  # 需要用户配置
        'model': 'deepseek-chat',
        'timeout': 60,
        'temperature': 0.0,
        'max_tokens': 2048
    }

LLM_CONFIG = load_llm_config()


def load_mcp_listen_port(default: int = 8000) -> int:
    """从项目根目录 config.json 读取 MCP 监听端口（与 load_llm_config 相同搜索路径）。"""
    import os
    config_paths = [
        'config.json',
        '../config.json',
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json'),
    ]
    for config_path in config_paths:
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                mcp = cfg.get('mcp_server') or {}
                p = mcp.get('port', default)
                return int(p)
        except Exception:
            continue
    return default


class MCPHTTPHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器，将HTTP请求转换为MCP协议请求"""
    
    server_instance = MCPServer()
    
    def do_OPTIONS(self):
        """处理CORS预检请求"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Access-Control-Max-Age', '86400')
        self.end_headers()
    
    def do_POST(self):
        """处理POST请求"""
        # 检查是否是LLM代理请求（支持带查询参数的路径）
        path = self.path.split('?')[0]  # 移除查询参数
        print(f"[DEBUG] 收到POST请求，路径: {path}")  # 调试日志
        
        if path == '/api/llm/chat':
            print("[DEBUG] 识别为LLM代理请求，调用_handle_llm_proxy")
            self._handle_llm_proxy()
            return
        
        # 检查是否是会话管理API
        if path.startswith('/api/sessions'):
            self._handle_session_api(path)
            return
        
        # 检查是否是文件上传API
        if path == '/api/files/upload':
            self._handle_file_upload()
            return

        if path == '/api/orchestrate':
            self._handle_orchestrate_api()
            return
        if path == '/api/auth/login' or path == '/api/auth/logout':
            self._handle_rbac_api('POST')
            return
        if path == '/api/admin/users' or path.startswith('/api/admin/users/'):
            self._handle_rbac_api('POST')
            return
        if path == '/api/admin/cases' or path.startswith('/api/admin/cases/'):
            self._handle_rbac_api('POST')
            return
        if path == '/api/admin/clients' or path.startswith('/api/admin/clients/'):
            self._handle_rbac_api('POST')
            return
        if path.startswith('/api/admin/kb'):
            self._handle_kb_api('POST')
            return
        if path == '/api/skills':
            self._handle_skills_api('POST')
            return
        if path.startswith('/api/skills/'):
            self._handle_skills_api('POST')
            return
        if path == '/api/admin/mcp-config':
            self._handle_mcp_config_api('POST')
            return
        if path == '/api/admin/profiles' or path.startswith('/api/admin/profiles/'):
            self._handle_admin_profiles_api('POST')
            return
        
        print(f"[DEBUG] 识别为MCP协议请求，路径: {path}")
        
        # 处理MCP协议请求
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        print(f"[DEBUG] MCP请求 - Content-Length: {content_length}, 数据长度: {len(post_data)}")
        
        try:
            request = json.loads(post_data.decode('utf-8'))
            print(f"[DEBUG] MCP请求解析成功 - method: {request.get('method')}, id: {request.get('id')}")
            print(f"[DEBUG] MCP请求参数: {json.dumps(request.get('params', {}), ensure_ascii=False, indent=2)}")
            
            # 同步调用（因为handle_request已经是同步的）
            response = self.server_instance.handle_request(request)
            
            print(f"[DEBUG] MCP请求处理完成 - response类型: {type(response)}, response是否为None: {response is None}")
            if response:
                print(f"[DEBUG] MCP响应 - 是否有result: {'result' in response}, 是否有error: {'error' in response}")
            
            # 如果response为None（如notifications/initialized），返回空响应体
            if response is None:
                print("[DEBUG] 通知方法返回None，发送空响应体")
                empty = b''
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Private-Network', 'true')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return

            response_json = json.dumps(response, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
            self.send_header('Content-Length', str(len(response_json)))
            self.end_headers()
            print(f"[DEBUG] MCP响应已写入，长度: {len(response_json)}")
            self.wfile.write(response_json)
            print(f"[DEBUG] ✅ MCP响应已发送完成")
        except Exception as e:
            import traceback
            print(f"[ERROR] MCP请求处理异常: {str(e)}")
            print(f"[ERROR] 异常堆栈:\n{traceback.format_exc()}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            error_response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if 'request' in locals() else None,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
            error_json = json.dumps(error_response, ensure_ascii=False).encode('utf-8')
            print(f"[ERROR] 发送错误响应，长度: {len(error_json)}")
            self.wfile.write(error_json)
    
    def _handle_llm_proxy(self):
        """处理LLM API代理请求"""
        # 标记是否已发送响应头（用于流式模式）
        headers_sent = False
        stream_mode = False
        try:
            print("[DEBUG] _handle_llm_proxy被调用")
            content_length = int(self.headers.get('Content-Length', 0))
            print(f"[DEBUG] Content-Length: {content_length}")
            post_data = self.rfile.read(content_length)
            print(f"[DEBUG] 读取到数据长度: {len(post_data)}")
            
            if not post_data:
                raise ValueError("请求体为空")
            
            request_data = json.loads(post_data.decode('utf-8'))
            print(f"[DEBUG] ========== LLM代理请求数据（客户端发送） ==========")
            print(f"[DEBUG] 流式输出: {request_data.get('stream', False)}")
            print(f"[DEBUG] 完整请求数据:")
            print(json.dumps(request_data, ensure_ascii=False, indent=2))
            print(f"[DEBUG] =================================================")
            
            # 使用配置中的LLM设置
            api_url = LLM_CONFIG.get('api_url', 'https://api.deepseek.com/v1/chat/completions')
            api_key = LLM_CONFIG.get('api_key', '')
            model = LLM_CONFIG.get('model', 'deepseek-chat')
            
            if not api_key:
                raise ValueError("LLM API Key未配置，请检查config.json")
            
            # 检查请求数据格式：如果是旧的messages格式，直接使用；否则根据requestData构建
            current_user_input = ''  # 用于后续获取question
            
            if 'messages' in request_data and isinstance(request_data.get('messages'), list) and len(request_data.get('messages', [])) > 0:
                # 旧格式：直接使用messages（向后兼容）
                print(f"[DEBUG] 检测到旧格式（messages数组），直接使用")
                messages = request_data.get('messages', [])
                # 直接使用服务端LLM_CONFIG中的temperature和max_tokens
                temperature = LLM_CONFIG.get('temperature', 0.0)
                max_tokens = LLM_CONFIG.get('max_tokens', 2048)
                # 从messages中提取最后一个user消息作为question
                user_messages = [msg for msg in messages if msg.get('role') == 'user']
                if user_messages:
                    current_user_input = user_messages[-1].get('content', '')
            else:
                # 新格式：根据requestData构建messages数组
                print(f"[DEBUG] 检测到新格式（requestData），构建messages数组")
                print(f"[DEBUG] request_data的键: {list(request_data.keys())}")
                
                # 提取system_prompt
                system_prompt = request_data.get('system_prompt', '')
                print(f"[DEBUG] system_prompt存在: {bool(system_prompt)}, 长度: {len(system_prompt) if system_prompt else 0}")
                
                # 提取服务端能力（支持新旧两种格式）
                # 新格式：server_ability.tools、server_ability.resources、server_ability.prompts
                # 旧格式：tools、resources、prompts（向后兼容）
                server_ability = request_data.get('server_ability')
                if server_ability and isinstance(server_ability, dict):
                    # 新格式
                    tools = server_ability.get('tools', [])
                    resources = server_ability.get('resources', [])
                    prompts = server_ability.get('prompts', [])
                    print(f"[DEBUG] 使用新格式提取服务端能力: tools={len(tools)}, resources={len(resources)}, prompts={len(prompts)}")
                else:
                    # 旧格式（向后兼容）
                    tools = request_data.get('tools', [])
                    resources = request_data.get('resources', [])
                    prompts = request_data.get('prompts', [])
                    print(f"[DEBUG] 使用旧格式提取服务端能力: tools={len(tools)}, resources={len(resources)}, prompts={len(prompts)}")
                
                # 提取conversation_history并转换为messages格式
                conversation_history = request_data.get('conversation_history', [])
                print(f"[DEBUG] conversation_history存在: {bool(conversation_history)}, 类型: {type(conversation_history)}, 长度: {len(conversation_history) if isinstance(conversation_history, list) else 0}")
                
                # 提取用户输入（支持多种格式）
                # 格式1：user_input.text 和 user_input.file_ids（正常用户输入）
                # 格式2：user_input.role='system' 和 user_input.content（系统行为，调用资源/工具/提示词模版后）
                # 格式3：current_user_input 和 file_ids（旧格式，向后兼容）
                user_input_obj = request_data.get('user_input')
                current_user_input = ''
                file_ids = []
                user_input_is_system = False
                
                if user_input_obj and isinstance(user_input_obj, dict):
                    # 检查是否是系统消息格式（调用资源/工具/提示词模版后）
                    if 'role' in user_input_obj and user_input_obj.get('role') == 'system':
                        # 系统行为：user_input 是 system 消息
                        system_content = user_input_obj.get('content', '')
                        if system_content:
                            # 将 system 消息添加到 conversation_history 中，而不是作为当前用户输入
                            # 注意：这里不设置 current_user_input，因为这是系统行为，不是用户输入
                            user_input_is_system = True
                            print(f"[DEBUG] 检测到系统行为：user_input 是 system 消息，内容长度={len(system_content)}")
                            print(f"[DEBUG] System 消息内容预览: {system_content[:100]}")
                            # 这个 system 消息会在后面添加到 conversation_history 中
                    else:
                        # 正常格式：user_input.text 和 user_input.file_ids
                        current_user_input = user_input_obj.get('text', '')
                        file_ids = user_input_obj.get('file_ids', [])
                        print(f"[DEBUG] 使用新格式提取用户输入: text长度={len(current_user_input) if current_user_input else 0}, file_ids数量={len(file_ids) if file_ids else 0}")
                else:
                    # 旧格式（向后兼容）
                    current_user_input = request_data.get('current_user_input', '')
                    file_ids = request_data.get('file_ids', [])
                    print(f"[DEBUG] 使用旧格式提取用户输入: current_user_input长度={len(current_user_input) if current_user_input else 0}, file_ids数量={len(file_ids) if file_ids else 0}")
                
                print(f"[DEBUG] 最终用户输入: 长度={len(current_user_input) if current_user_input else 0}, 内容预览: {current_user_input[:50] if current_user_input else '(空)'}, 是否为系统行为: {user_input_is_system}")
                
                # 额外：从 conversation_history 中提取 file_ids（支持“文件ID只存在于历史消息”的场景）
                # 说明：客户端可能会把 file_ids 记录在历史对话消息对象中（如 {role, content, file_ids}），
                # 特别是 afterInvocation=true 时请求体可能不包含 user_input，此时必须从历史里补齐 file_ids。
                try:
                    merged_file_ids = []
                    file_id_set = set()
                    
                    # 先合并从 user_input / 顶层提取到的 file_ids
                    if isinstance(file_ids, list):
                        for fid in file_ids:
                            if isinstance(fid, str) and fid and fid not in file_id_set:
                                merged_file_ids.append(fid)
                                file_id_set.add(fid)
                    else:
                        file_ids = []
                    
                    # 再从历史对话中提取
                    if isinstance(conversation_history, list):
                        for msg in conversation_history:
                            if isinstance(msg, dict):
                                msg_file_ids = msg.get('file_ids')
                                if isinstance(msg_file_ids, list):
                                    for fid in msg_file_ids:
                                        if isinstance(fid, str) and fid and fid not in file_id_set:
                                            merged_file_ids.append(fid)
                                            file_id_set.add(fid)
                    
                    file_ids = merged_file_ids
                    if file_ids:
                        print(f"[DEBUG] 已合并历史对话中的 file_ids，总数={len(file_ids)}")
                except Exception as e:
                    print(f"[DEBUG] 从 conversation_history 合并 file_ids 失败: {e}")
                
                # 构建messages数组
                messages = []
                
                # 1. 添加system消息（Skill 与 MCP 提示词重叠时优先 Skill）
                try:
                    import os
                    from skill_service import SkillService, ensure_skill_priority_in_prompt
                    _skills_root = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "skills",
                    )
                    system_prompt = ensure_skill_priority_in_prompt(
                        system_prompt or "",
                        SkillService(_skills_root).list_skills(),
                    )
                except Exception as skill_exc:
                    print(f"[DEBUG] Skill 优先说明注入失败: {skill_exc}")
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                    print(f"[DEBUG] 添加system消息，长度: {len(system_prompt)}")
                else:
                    print(f"[DEBUG] 警告：system_prompt为空，跳过system消息")
                
                # 2. 将历史对话转换为messages格式
                # 注意：如果 user_input_is_system 为 True，system 消息和 user 消息已经在 conversation_history 中了
                if isinstance(conversation_history, list):
                    for i, msg in enumerate(conversation_history):
                        if isinstance(msg, dict):
                            role = msg.get('role', 'user')
                            content = msg.get('content', '')
                            if content:  # 只添加有内容的消息
                                messages.append({"role": role, "content": content})
                                print(f"[DEBUG] 添加历史消息{i+1} ({role})，长度: {len(content)}")
                        else:
                            print(f"[DEBUG] 警告：历史消息{i+1}不是字典格式: {type(msg)}")
                    print(f"[DEBUG] 添加历史对话，数量: {len(conversation_history)}")
                    if user_input_is_system:
                        print(f"[DEBUG] 系统行为：system 消息和 user 消息已包含在 conversation_history 中")
                else:
                    print(f"[DEBUG] 警告：conversation_history不是列表格式: {type(conversation_history)}")
                
                # 3. 检查是否有资源数据或工具结果（资源/工具已调用的情况）
                resource_data = request_data.get('resource_data')
                resource_uri = request_data.get('resource_uri')
                resource_called = request_data.get('resource_called', False)
                resource_stage = request_data.get('resource_stage', '')
                
                tool_result = request_data.get('tool_result')
                tool_name = request_data.get('tool_name')
                tool_called = request_data.get('tool_called', False)
                tool_stage = request_data.get('tool_stage', '')
                
                prompt_template = request_data.get('prompt_template')
                prompt_name = request_data.get('prompt_name')
                prompt_called = request_data.get('prompt_called', False)
                prompt_stage = request_data.get('prompt_stage', '')

                # 兼容新的 invokeDetail 字段（提示词模版调用）
                invoke_detail = request_data.get('invokeDetail')
                if isinstance(invoke_detail, dict):
                    invoke_type = invoke_detail.get('type')
                    if invoke_type == 'prompt':
                        prompt_name = invoke_detail.get('name') or prompt_name
                        prompt_called = bool(invoke_detail.get('completed', prompt_called))
                        prompt_stage = 'completed' if prompt_called else prompt_stage
                        prompt_template = invoke_detail.get('result') or prompt_template
                
                # 构建上下文信息
                context_parts = []
                
                # 如果请求中包含文件ID，获取文件文字内容并添加到上下文
                # 注意：file_ids 已经在上面从 user_input 或顶层提取了
                # 确保 file_ids 是列表格式
                if not isinstance(file_ids, list):
                    file_ids = []
                
                if file_ids and len(file_ids) > 0 and MCPHTTPHandler.server_instance.file_service:
                    print(f"[DEBUG] 检测到文件ID列表: {file_ids}")
                    file_service = MCPHTTPHandler.server_instance.file_service
                    file_contents = []
                    for file_id in file_ids:
                        try:
                            file_info = file_service.get_file(file_id)
                            if file_info:
                                text_content = file_service.get_file_text(file_id)
                                if text_content:
                                    file_name = file_info.get('original_name', '未知文件')
                                    file_contents.append(f"文件名称: {file_name}\n文件内容:\n{text_content}")
                                    print(f"[DEBUG] 已添加文件内容到上下文: {file_name} (长度: {len(text_content)})")
                                else:
                                    print(f"[DEBUG] 文件 {file_id} 没有文字内容")
                            else:
                                print(f"[DEBUG] 文件 {file_id} 不存在")
                        except Exception as e:
                            print(f"[DEBUG] 获取文件 {file_id} 内容失败: {e}")
                    
                    if file_contents:
                        file_context = "\n\n".join([f"[附件{i+1}]\n{content}" for i, content in enumerate(file_contents)])
                        file_context += "\n\n请基于上述附件内容回答用户问题。"
                        context_parts.append(file_context)
                        print(f"[DEBUG] 已添加文件上下文，文件数量: {len(file_contents)}")
                
                # 如果资源已调用，添加资源数据上下文
                if resource_data and resource_uri:
                    print(f"[DEBUG] 检测到资源已调用: resource_uri={resource_uri}, resource_called={resource_called}, resource_stage={resource_stage}")
                    resource_context = f"[资源已调用] 资源URI: {resource_uri}\n资源数据:\n{resource_data}\n\n请基于上述资源数据生成最终结论，无需再次调用资源。"
                    context_parts.append(resource_context)
                
                # 如果工具已调用，添加工具结果上下文
                if tool_result and tool_name:
                    print(f"[DEBUG] 检测到工具已调用: tool_name={tool_name}, tool_called={tool_called}, tool_stage={tool_stage}")
                    tool_context = f"[工具已调用] 工具名称: {tool_name}\n工具结果:\n{str(tool_result)}\n\n请基于上述工具结果生成最终结论，无需再次调用工具。"
                    context_parts.append(tool_context)
                
                # 如果提示词模板已调用，添加提示词模板上下文
                if prompt_template and prompt_name:
                    print(f"[DEBUG] 检测到提示词模板已调用: prompt_name={prompt_name}, prompt_called={prompt_called}, prompt_stage={prompt_stage}")
                    
                    # 提取提示词模板的实际内容
                    prompt_text = None
                    if isinstance(prompt_template, dict):
                        # 如果prompt_template是对象，尝试从messages中提取内容
                        if 'messages' in prompt_template and isinstance(prompt_template['messages'], list) and len(prompt_template['messages']) > 0:
                            first_message = prompt_template['messages'][0]
                            if isinstance(first_message, dict):
                                content = first_message.get('content', {})
                                if isinstance(content, dict) and 'text' in content:
                                    prompt_text = content['text']
                                elif isinstance(content, str):
                                    prompt_text = content
                        # 如果没有messages，尝试直接获取text字段
                        if not prompt_text and 'text' in prompt_template:
                            prompt_text = prompt_template['text']
                        # 如果还是没有，尝试将整个对象转换为字符串（向后兼容）
                        if not prompt_text:
                            prompt_text = str(prompt_template)
                    elif isinstance(prompt_template, str):
                        prompt_text = prompt_template
                    else:
                        prompt_text = str(prompt_template)
                    
                    print(f"[DEBUG] 提取的提示词模板内容长度: {len(prompt_text) if prompt_text else 0}")
                    
                    # 将提示词模板内容添加到system_prompt或作为系统消息
                    if prompt_text:
                        # 【方案优化】保持 system_prompt 不变（因为它是固定的配置）
                        # 在提示词模板内容前添加明确的说明，告诉 LLM 这是已调用的模板
                        # 这样既解决了死循环问题，又保持了配置的固定性
                        if system_prompt:
                            # 在提示词模板内容前添加说明，组合成新的 system_prompt
                            # 注意：这里不是修改原始配置，而是组合新的 system_prompt 内容
                            prompt_instruction = f"""【重要：提示词模板已调用】
提示词模板 "{prompt_name}" 已经调用，你现在应该直接按照以下提示词模板的内容工作，**不要再返回调用提示词模板的指令**。

请直接按照提示词模板中的工作流程执行任务，输出最终结果，而不是再次返回 invoke_tool_or_resource 或 invoke_prompt 的指令。

--- 提示词模板内容（优先级最高） ---
{prompt_text}

--- 系统提示（保持不变） ---
{system_prompt}"""
                            
                            system_prompt = prompt_instruction
                        else:
                            system_prompt = prompt_text
                        print(f"[DEBUG] 已将提示词模板内容添加到system_prompt，总长度: {len(system_prompt)}")
                    else:
                        # 如果无法提取内容，使用旧的格式（向后兼容）
                        prompt_context = f"[提示词模板已调用] 模板名称: {prompt_name}\n模板内容:\n{str(prompt_template)}\n\n请基于上述提示词模板生成最终结论，无需再次调用提示词模板。"
                        context_parts.append(prompt_context)
                
                # 如果有上下文，添加到用户输入前（仅当不是系统行为时）
                if context_parts and not user_input_is_system:
                    combined_context = "\n\n".join(context_parts)
                    if current_user_input:
                        current_user_input = combined_context + "\n\n用户问题: " + current_user_input
                    else:
                        current_user_input = combined_context
                    print(f"[DEBUG] 已添加资源/工具上下文到用户输入，总长度: {len(current_user_input)}")
                
                # 3. 添加当前用户输入（可能已包含资源/工具上下文）
                # 注意：如果是系统行为（user_input_is_system=True），则不添加 user 消息
                if user_input_is_system:
                    print(f"[DEBUG] 系统行为：跳过添加 user 消息（user_input 已作为 system 消息添加到 conversation_history 中）")
                elif current_user_input:
                    messages.append({"role": "user", "content": current_user_input})
                    print(f"[DEBUG] 添加当前用户输入，长度: {len(current_user_input)}")
                else:
                    print(f"[DEBUG] 警告：current_user_input为空，且不是系统行为")
                
                # 直接使用服务端LLM_CONFIG中的temperature和max_tokens
                temperature = LLM_CONFIG.get('temperature', 0.0)
                max_tokens = LLM_CONFIG.get('max_tokens', 2048)
                
                print(f"[DEBUG] 最终构建的messages数组长度: {len(messages)}")
                if len(messages) == 0:
                    error_msg = "无法构建有效的messages数组：system_prompt、conversation_history和current_user_input都为空或无效"
                    print(f"[ERROR] {error_msg}")
                    print(f"[ERROR] 请检查：system_prompt={bool(system_prompt)}, conversation_history={len(conversation_history) if isinstance(conversation_history, list) else 'N/A'}, current_user_input={bool(current_user_input)}")
                    raise ValueError(error_msg)
            
            # 检查是否要求流式输出
            stream = request_data.get('stream', False)
            
            # 验证messages数组不为空（双重检查）
            if not messages or len(messages) == 0:
                error_msg = "messages数组为空，无法调用LLM API"
                print(f"[ERROR] {error_msg}")
                raise ValueError(error_msg)
            
            # 构建LLM请求
            llm_request = {
                "model": request_data.get('model', model),
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": stream
            }
            
            print(f"[DEBUG] ========== 发送给DeepSeek API的请求数据 ==========")
            print(f"[DEBUG] API URL: {api_url}")
            print(f"[DEBUG] 模型: {llm_request.get('model')}")
            print(f"[DEBUG] 消息数量: {len(llm_request.get('messages', []))}")
            print(f"[DEBUG] 流式输出: {llm_request.get('stream')}")
            print(f"[DEBUG] 温度: {llm_request.get('temperature')}")
            print(f"[DEBUG] 最大token数: {llm_request.get('max_tokens')}")
            print(f"[DEBUG] 消息内容预览:")
            for i, msg in enumerate(llm_request.get('messages', [])):
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                content_preview = content[:200] + ('...' if len(content) > 200 else '')
                print(f"[DEBUG]   消息{i+1} ({role}): {content_preview}")
            print(f"[DEBUG] 完整请求数据:")
            print(json.dumps(llm_request, ensure_ascii=False, indent=2))
            print(f"[DEBUG] =================================================")
            
            print(f"[DEBUG] ========== 发送给DeepSeek API的请求数据 ==========")
            print(f"[DEBUG] API URL: {api_url}")
            print(f"[DEBUG] 模型: {llm_request.get('model')}")
            print(f"[DEBUG] 消息数量: {len(llm_request.get('messages', []))}")
            print(f"[DEBUG] 流式输出: {llm_request.get('stream')}")
            print(f"[DEBUG] 温度: {llm_request.get('temperature')}")
            print(f"[DEBUG] 最大token数: {llm_request.get('max_tokens')}")
            print(f"[DEBUG] 消息内容预览:")
            for i, msg in enumerate(llm_request.get('messages', [])):
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                content_preview = content[:200] + ('...' if len(content) > 200 else '')
                print(f"[DEBUG]   消息{i+1} ({role}): {content_preview}")
            print(f"[DEBUG] 完整请求数据:")
            print(json.dumps(llm_request, ensure_ascii=False, indent=2))
            print(f"[DEBUG] =================================================")
            
            # 调用DeepSeek API
            req = urllib.request.Request(
                api_url,
                data=json.dumps(llm_request).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {api_key}'
                }
            )
            
            # 初始化response变量为None，避免UnboundLocalError
            response = None
            
            if stream:
                stream_mode = True
                # 流式输出 - 解析并格式化返回
                print("[DEBUG] ========== 开始流式输出 ==========")
                print(f"[DEBUG] 准备发送响应头...")
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('Connection', 'keep-alive')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    headers_sent = True
                    print(f"[DEBUG] ✅ 响应头已发送")
                except Exception as header_error:
                    print(f"[ERROR] 发送响应头失败: {header_error}")
                    import traceback
                    traceback.print_exc()
                    raise
                
                # 累积的完整内容
                full_content = ''
                reasoning_text = ''  # 思考内容
                law_text = ''  # 结论内容
                separator = '==JSON=='
                separator_found = False
                
                chunk_count = 0
                buffer = ''  # 在with块外初始化buffer，避免UnboundLocalError
                
                print(f"[DEBUG] 准备调用DeepSeek API（流式）...")
                print(f"[DEBUG] API URL: {api_url}")
                timeout = LLM_CONFIG.get('timeout', 60)
                max_retries = LLM_CONFIG.get('max_retries', 3)
                print(f"[DEBUG] 超时设置: {timeout}秒")
                print(f"[DEBUG] 最大重试次数: {max_retries}")
                
                # 实现重试机制
                retry_count = 0
                last_error = None
                llm_response = None
                
                while retry_count < max_retries:
                    try:
                        print(f"[DEBUG] 开始urllib.request.urlopen调用... (尝试 {retry_count + 1}/{max_retries})")
                        llm_response = urllib.request.urlopen(req, timeout=timeout)
                        print(f"[DEBUG] ✅ DeepSeek API连接成功")
                        break
                    except Exception as e:
                        last_error = e
                        retry_count += 1
                        if retry_count < max_retries:
                            wait_time = retry_count  # 递增等待时间：1秒、2秒、3秒...
                            print(f"[DEBUG] ⚠️ LLM API调用失败，{retry_count}/{max_retries}次重试，等待{wait_time}秒后重试...")
                            print(f"[DEBUG] 错误信息: {str(e)[:200]}")
                            import time
                            time.sleep(wait_time)
                        else:
                            print(f"[ERROR] LLM API调用失败，已重试{max_retries}次，放弃重试")
                            raise last_error
                
                # 如果成功获取响应，处理流式数据
                if llm_response:
                    try:
                        with llm_response:
                            print(f"[DEBUG] ✅ DeepSeek API连接成功，开始读取流式数据...")
                            
                            # 为流式读取设置socket超时，避免无限期等待
                            # urllib的timeout只控制连接超时，不控制读取超时
                            import socket
                            import time
                            read_start_time = time.time()
                            read_timeout = timeout  # 使用配置的超时时间
                            
                            # 尝试设置socket读取超时
                            try:
                                if hasattr(llm_response, 'fp') and hasattr(llm_response.fp, 'raw'):
                                    if hasattr(llm_response.fp.raw, 'sock'):
                                        llm_response.fp.raw.sock.settimeout(read_timeout)
                                        print(f"[DEBUG] ✅ 已设置socket读取超时: {read_timeout}秒")
                                    elif hasattr(llm_response.fp, 'sock'):
                                        llm_response.fp.sock.settimeout(read_timeout)
                                        print(f"[DEBUG] ✅ 已设置socket读取超时（备用方式）: {read_timeout}秒")
                            except Exception as sock_timeout_err:
                                print(f"[DEBUG] ⚠️ 设置socket超时失败（将使用时间检查）: {sock_timeout_err}")
                            
                            while True:
                                # 检查是否超时（双重保护）
                                elapsed_time = time.time() - read_start_time
                                if elapsed_time > read_timeout:
                                    print(f"[ERROR] 流式读取超时: 已用时 {elapsed_time:.1f}秒，超过超时限制 {read_timeout}秒")
                                    raise TimeoutError(f"流式读取超时: 已用时 {elapsed_time:.1f}秒，超过超时限制 {read_timeout}秒")
                                
                                try:
                                    chunk = llm_response.read(4096)
                                    if not chunk:
                                        break
                                    chunk_count += 1
                                except socket.timeout:
                                    print(f"[ERROR] Socket读取超时: 已用时 {time.time() - read_start_time:.1f}秒")
                                    raise TimeoutError(f"Socket读取超时: 已用时 {time.time() - read_start_time:.1f}秒")
                                except Exception as read_err:
                                    print(f"[ERROR] 读取数据时出错: {read_err}")
                                    raise
                                
                                # 解码chunk
                                buffer += chunk.decode('utf-8', errors='ignore')
                                lines = buffer.split('\n')
                                buffer = lines.pop() if lines else ''  # 保留最后不完整的行
                                
                                for line in lines:
                                    line = line.strip()
                                    if not line or not line.startswith('data: '):
                                        continue
                                    
                                    data_str = line[6:].strip()  # 移除 'data: ' 前缀
                                    if data_str == '[DONE]':
                                        continue
                                    
                                    try:
                                        data_json = json.loads(data_str)
                                        delta = data_json.get('choices', [{}])[0].get('delta', {}).get('content', '')
                                        if delta:
                                            full_content += delta
                                            
                                            # 检查是否找到分隔符
                                            if not separator_found and separator in full_content:
                                                separator_found = True
                                                separator_index = full_content.index(separator)
                                                reasoning_text = full_content[:separator_index].strip()
                                                # 结论内容从分隔符后开始
                                                law_text_start = separator_index + len(separator)
                                                law_text = full_content[law_text_start:].strip()
                                            elif separator_found:
                                                # 分隔符已找到，新内容追加到结论
                                                law_text = full_content[full_content.index(separator) + len(separator):].strip()
                                            else:
                                                # 分隔符未找到，新内容追加到思考内容
                                                reasoning_text = full_content
                                            
                                            # 构建返回数据结构
                                            response_data = {
                                                "type": 7,
                                                "dateStr": datetime.now().strftime("%H:%M"),
                                                "date": int(datetime.now().timestamp() * 1000),
                                                "qaId": f"qa_{int(datetime.now().timestamp() * 1000)}",
                                                "sessionId": request_data.get('session_id', ''),
                                                "userId": request_data.get('user_id', ''),
                                                "identify": None,
                                                "talk": "gpt",
                                                "data": {
                                                    "question": current_user_input,
                                                    "useful": 1,
                                                    "showLawQaButton": True,
                                                    "reasoningQaText": reasoning_text,
                                                    "reasoningErrorIs": False,
                                                    "lawQaText": law_text if separator_found else None,
                                                    "streamLawQaText": None
                                                },
                                                "intent": None,
                                                "questionContext": None
                                            }
                                            
                                            # 发送SSE格式数据
                                            sse_data = f"data: {json.dumps(response_data, ensure_ascii=False)}\n\n"
                                            self.wfile.write(sse_data.encode('utf-8'))
                                            self.wfile.flush()
                                            
                                    except json.JSONDecodeError as json_err:
                                        # 忽略JSON解析错误，继续处理下一个chunk
                                        print(f"[DEBUG] JSON解析错误（忽略）: {json_err}, 数据: {data_str[:100] if 'data_str' in locals() else 'N/A'}")
                                        continue
                                    except Exception as e:
                                        print(f"[ERROR] 处理流式数据时出错: {e}")
                                        import traceback
                                        traceback.print_exc()
                                        continue
                    except urllib.error.URLError as url_error:
                        # URL错误（网络问题、超时等）
                        url_error_msg = str(url_error)  # 提前转换为字符串，避免后续作用域问题
                        print(f"[ERROR] DeepSeek API连接失败: {url_error_msg}")
                        import traceback
                        traceback.print_exc()
                        # 发送错误响应给客户端（SSE格式，因为响应头已经发送）
                        try:
                            error_data = {
                                "type": 7,
                                "dateStr": datetime.now().strftime("%H:%M"),
                                "date": int(datetime.now().timestamp() * 1000),
                                "qaId": f"qa_{int(datetime.now().timestamp() * 1000)}",
                                "sessionId": request_data.get('session_id', ''),
                                "userId": request_data.get('user_id', ''),
                                "identify": None,
                                "talk": "gpt",
                                "data": {
                                    "question": current_user_input,
                                    "useful": 1,
                                    "showLawQaButton": False,
                                    "reasoningQaText": f"连接DeepSeek API失败: {url_error_msg}",
                                    "reasoningErrorIs": True,
                                    "lawQaText": None,
                                    "streamLawQaText": None
                                },
                                "intent": None,
                                "questionContext": None
                            }
                            sse_error = f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                            self.wfile.write(sse_error.encode('utf-8'))
                            self.wfile.write(b'data: [DONE]\n\n')
                            self.wfile.flush()
                            print("[DEBUG] 错误响应已发送（SSE格式）")
                        except Exception as send_err:
                            print(f"[ERROR] 发送错误响应失败: {send_err}")
                            import traceback
                            traceback.print_exc()
                    except TimeoutError as timeout_err:
                        # 流式读取超时异常
                        timeout_msg = str(timeout_err)
                        print(f"[ERROR] 流式读取超时: {timeout_msg}")
                        import traceback
                        traceback.print_exc()
                        # 发送超时错误响应给客户端（SSE格式，因为响应头已经发送）
                        try:
                            error_data = {
                                "type": 7,
                                "dateStr": datetime.now().strftime("%H:%M"),
                                "date": int(datetime.now().timestamp() * 1000),
                                "qaId": f"qa_{int(datetime.now().timestamp() * 1000)}",
                                "sessionId": request_data.get('session_id', ''),
                                "userId": request_data.get('user_id', ''),
                                "identify": None,
                                "talk": "gpt",
                                "data": {
                                    "question": current_user_input,
                                    "useful": 1,
                                    "showLawQaButton": False,
                                    "reasoningQaText": f"请求超时: {timeout_msg}。可能是对话历史过长或网络延迟，请尝试简化问题或稍后重试。",
                                    "reasoningErrorIs": True,
                                    "lawQaText": None,
                                    "streamLawQaText": None
                                },
                                "intent": None,
                                "questionContext": None
                            }
                            sse_error = f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                            self.wfile.write(sse_error.encode('utf-8'))
                            self.wfile.write(b'data: [DONE]\n\n')
                            self.wfile.flush()
                            print("[DEBUG] 超时错误响应已发送（SSE格式）")
                        except Exception as send_err:
                            print(f"[ERROR] 发送超时错误响应失败: {send_err}")
                            import traceback
                            traceback.print_exc()
                    except Exception as stream_error:
                        # 流式请求过程中的其他异常
                        print(f"[ERROR] 流式请求处理异常: {stream_error}")
                        import traceback
                        traceback.print_exc()
                        # 发送错误响应给客户端（SSE格式，因为响应头已经发送）
                        try:
                            error_data = {
                                "type": 7,
                                "dateStr": datetime.now().strftime("%H:%M"),
                                "date": int(datetime.now().timestamp() * 1000),
                                "qaId": f"qa_{int(datetime.now().timestamp() * 1000)}",
                                "sessionId": request_data.get('session_id', ''),
                                "userId": request_data.get('user_id', ''),
                                "identify": None,
                                "talk": "gpt",
                                "data": {
                                    "question": current_user_input,
                                    "useful": 1,
                                    "showLawQaButton": False,
                                    "reasoningQaText": f"处理请求时出错: {str(stream_error)}",
                                    "reasoningErrorIs": True,
                                    "lawQaText": None,
                                    "streamLawQaText": None
                                },
                                "intent": None,
                                "questionContext": None
                            }
                            sse_error = f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                            self.wfile.write(sse_error.encode('utf-8'))
                            self.wfile.write(b'data: [DONE]\n\n')
                            self.wfile.flush()
                            print("[DEBUG] 错误响应已发送（SSE格式）")
                        except Exception as send_err:
                            print(f"[ERROR] 发送错误响应失败: {send_err}")
                
                # 处理剩余的buffer
                if buffer and buffer.strip():
                    try:
                        if buffer.strip().startswith('data: '):
                            data_str = buffer.strip()[6:].strip()
                            if data_str != '[DONE]':
                                data_json = json.loads(data_str)
                                delta = data_json.get('choices', [{}])[0].get('delta', {}).get('content', '')
                                if delta:
                                    full_content += delta
                                    if not separator_found and separator in full_content:
                                        separator_found = True
                                        separator_index = full_content.index(separator)
                                        reasoning_text = full_content[:separator_index].strip()
                                        law_text = full_content[separator_index + len(separator):].strip()
                                    elif separator_found:
                                        law_text = full_content[full_content.index(separator) + len(separator):].strip()
                                    else:
                                        reasoning_text = full_content
                                    
                                    response_data = {
                                        "type": 7,
                                        "dateStr": datetime.now().strftime("%H:%M"),
                                        "date": int(datetime.now().timestamp() * 1000),
                                        "qaId": f"qa_{int(datetime.now().timestamp() * 1000)}",
                                        "sessionId": request_data.get('session_id', ''),
                                        "userId": request_data.get('user_id', ''),
                                        "identify": None,
                                        "talk": "gpt",
                                        "data": {
                                            "question": current_user_input,
                                            "useful": 1,
                                            "showLawQaButton": True,
                                            "reasoningQaText": reasoning_text,
                                            "reasoningErrorIs": False,
                                            "lawQaText": law_text if separator_found else None,
                                            "streamLawQaText": None
                                        },
                                        "intent": None,
                                        "questionContext": None
                                    }
                                    
                                    sse_data = f"data: {json.dumps(response_data, ensure_ascii=False)}\n\n"
                                    self.wfile.write(sse_data.encode('utf-8'))
                                    self.wfile.flush()
                    except Exception as e:
                        print(f"[DEBUG] 处理剩余buffer时出错: {e}")
                
                print(f"[DEBUG] 流式输出完成，共{chunk_count}个数据块")
                
                # 在发送结束标记前，检查最终的lawQaText是否为空
                # 如果为空且没有分隔符，将完整内容填充到lawQaText
                if not separator_found and full_content and (not law_text or not law_text.strip()):
                    print(f"[DEBUG] 检测到lawQaText为空且无分隔符，将完整内容填充到lawQaText（长度: {len(full_content)}）")
                    # 重新计算reasoning_text和law_text
                    # 如果没有分隔符：为了避免客户端同时展示“思考+结论”（重复），这里强制将 reasoningQaText 置空，
                    # 只把完整内容放到 lawQaText，交由客户端作为最终展示内容。
                    final_law_text = full_content.strip()
                    final_reasoning_text = ''
                    
                    # 发送最终的响应，确保lawQaText有内容
                    final_response_data = {
                        "type": 7,
                        "dateStr": datetime.now().strftime("%H:%M"),
                        "date": int(datetime.now().timestamp() * 1000),
                        "qaId": f"qa_{int(datetime.now().timestamp() * 1000)}",
                        "sessionId": request_data.get('session_id', ''),
                        "userId": request_data.get('user_id', ''),
                        "identify": None,
                        "talk": "gpt",
                        "data": {
                            "question": current_user_input,
                            "useful": 1,
                            "showLawQaButton": True,
                            "reasoningQaText": final_reasoning_text,
                            "reasoningErrorIs": False,
                            "lawQaText": final_law_text,
                            "streamLawQaText": None
                        },
                        "intent": None,
                        "questionContext": None
                    }
                    sse_final = f"data: {json.dumps(final_response_data, ensure_ascii=False)}\n\n"
                    self.wfile.write(sse_final.encode('utf-8'))
                    self.wfile.flush()
                    print("[DEBUG] 已发送最终响应，lawQaText已填充完整内容")
                
                # 发送结束标记
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()
                print("[DEBUG] 流式输出结束标记已发送")
            else:
                # 非流式输出（原有逻辑）
                timeout = LLM_CONFIG.get('timeout', 60)
                max_retries = LLM_CONFIG.get('max_retries', 3)
                print(f"[DEBUG] 非流式输出 - 超时设置: {timeout}秒，最大重试次数: {max_retries}")
                
                # 实现重试机制
                retry_count = 0
                last_error = None
                response = None
                
                while retry_count < max_retries:
                    try:
                        print(f"[DEBUG] 开始urllib.request.urlopen调用（非流式）... (尝试 {retry_count + 1}/{max_retries})")
                        response = urllib.request.urlopen(req, timeout=timeout)
                        print(f"[DEBUG] ✅ DeepSeek API连接成功（非流式）")
                        break
                    except Exception as e:
                        last_error = e
                        retry_count += 1
                        if retry_count < max_retries:
                            wait_time = retry_count  # 递增等待时间：1秒、2秒、3秒...
                            print(f"[DEBUG] ⚠️ LLM API调用失败，{retry_count}/{max_retries}次重试，等待{wait_time}秒后重试...")
                            print(f"[DEBUG] 错误信息: {str(e)[:200]}")
                            import time
                            time.sleep(wait_time)
                        else:
                            print(f"[ERROR] LLM API调用失败，已重试{max_retries}次，放弃重试")
                            raise last_error
                
                # 如果成功获取响应，读取数据
                if response:
                    with response:
                        response_data = response.read().decode('utf-8')
                        
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(response_data.encode('utf-8'))
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else '{}'
            print(f"[ERROR] DeepSeek API返回HTTP错误: {e.code}")
            print(f"[ERROR] 错误响应体: {error_body[:500]}")
            # 检查是否已经发送了响应头（流式模式）
            if headers_sent and stream_mode:
                # 流式模式：响应头已发送，发送SSE格式的错误
                try:
                    current_user_input = request_data.get('current_user_input', '') if 'request_data' in locals() else ''
                    error_data = {
                        "type": 7,
                        "dateStr": datetime.now().strftime("%H:%M"),
                        "date": int(datetime.now().timestamp() * 1000),
                        "qaId": f"qa_{int(datetime.now().timestamp() * 1000)}",
                        "sessionId": request_data.get('session_id', '') if 'request_data' in locals() else '',
                        "userId": request_data.get('user_id', '') if 'request_data' in locals() else '',
                        "identify": None,
                        "talk": "gpt",
                        "data": {
                            "question": current_user_input,
                            "useful": 1,
                            "showLawQaButton": False,
                            "reasoningQaText": f"DeepSeek API返回错误: HTTP {e.code} - {error_body[:200]}",
                            "reasoningErrorIs": True,
                            "lawQaText": None,
                            "streamLawQaText": None
                        },
                        "intent": None,
                        "questionContext": None
                    }
                    sse_error = f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                    self.wfile.write(sse_error.encode('utf-8'))
                    self.wfile.write(b'data: [DONE]\n\n')
                    self.wfile.flush()
                    print("[DEBUG] 错误响应已发送（SSE格式）")
                except Exception as send_err:
                    print(f"[ERROR] 发送SSE错误响应失败: {send_err}")
            else:
                # 非流式模式或响应头未发送：发送JSON格式的错误
                try:
                    self.send_response(e.code)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(error_body.encode('utf-8'))
                except Exception as send_err:
                    print(f"[ERROR] 发送HTTP错误响应失败: {send_err}")
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"[ERROR] LLM代理请求处理失败: {e}")
            print(f"[ERROR] 错误类型: {type(e).__name__}")
            print(f"[ERROR] 错误堆栈:\n{error_trace}")
            
            # 检查是否已经发送了响应头（流式模式）
            if headers_sent and stream_mode:
                # 流式模式：响应头已发送，发送SSE格式的错误
                try:
                    current_user_input = request_data.get('current_user_input', '') if 'request_data' in locals() else ''
                    error_data = {
                        "type": 7,
                        "dateStr": datetime.now().strftime("%H:%M"),
                        "date": int(datetime.now().timestamp() * 1000),
                        "qaId": f"qa_{int(datetime.now().timestamp() * 1000)}",
                        "sessionId": request_data.get('session_id', '') if 'request_data' in locals() else '',
                        "userId": request_data.get('user_id', '') if 'request_data' in locals() else '',
                        "identify": None,
                        "talk": "gpt",
                        "data": {
                            "question": current_user_input,
                            "useful": 1,
                            "showLawQaButton": False,
                            "reasoningQaText": f"处理请求时出错: {str(e)}",
                            "reasoningErrorIs": True,
                            "lawQaText": None,
                            "streamLawQaText": None
                        },
                        "intent": None,
                        "questionContext": None
                    }
                    sse_error = f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                    self.wfile.write(sse_error.encode('utf-8'))
                    self.wfile.write(b'data: [DONE]\n\n')
                    self.wfile.flush()
                    print("[DEBUG] 错误响应已发送（SSE格式）")
                except Exception as send_err:
                    print(f"[ERROR] 发送SSE错误响应失败: {send_err}")
            else:
                # 非流式模式或响应头未发送：发送JSON格式的错误
                try:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    error_response = {
                        "error": {
                            "message": str(e),
                            "type": type(e).__name__
                        }
                    }
                    self.wfile.write(json.dumps(error_response, ensure_ascii=False).encode('utf-8'))
                except Exception as send_err:
                    print(f"[ERROR] 发送JSON错误响应失败: {send_err}")
                    print(f"[ERROR] 错误堆栈:\n{traceback.format_exc()}")
    
    def do_GET(self):
        """处理GET请求（用于健康检查和会话列表）"""
        path = self.path.split('?')[0]
        
        if path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode('utf-8'))
        elif path == '/api/auth/me':
            self._handle_rbac_api('GET')
        elif path.startswith('/api/admin/users') or path.startswith('/api/admin/roles') or path.startswith('/api/admin/permissions') or path.startswith('/api/admin/cases') or path.startswith('/api/admin/clients'):
            self._handle_rbac_api('GET')
        elif path.startswith('/api/admin/kb'):
            self._handle_kb_api('GET')
        elif path.startswith('/api/sessions'):
            self._handle_session_api(path, method='GET')
        elif path.startswith('/api/files'):
            self._handle_file_api(path, method='GET')
        elif path == '/api/skills' or path.startswith('/api/skills/'):
            self._handle_skills_api('GET')
        elif path == '/api/admin/mcp-config':
            self._handle_mcp_config_api('GET')
        elif path == '/api/admin/stats':
            self._handle_admin_stats_api()
        elif path == '/api/admin/profiles' or path.startswith('/api/admin/profiles/'):
            self._handle_admin_profiles_api('GET')
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_DELETE(self):
        """处理DELETE请求（用于删除会话）"""
        path = self.path.split('?')[0]
        if path.startswith('/api/sessions'):
            self._handle_session_api(path, method='DELETE')
        elif path.startswith('/api/files'):
            self._handle_file_api(path, method='DELETE')
        elif path.startswith('/api/skills/'):
            self._handle_skills_api('DELETE')
        elif path.startswith('/api/admin/cases/') and '/members/' in path:
            self._handle_rbac_api('DELETE')
        elif path.startswith('/api/admin/cases/'):
            self._handle_rbac_api('DELETE')
        elif path.startswith('/api/admin/clients/'):
            self._handle_rbac_api('DELETE')
        elif path.startswith('/api/admin/kb'):
            self._handle_kb_api('DELETE')
        elif path.startswith('/api/admin/profiles/'):
            self._handle_admin_profiles_api('DELETE')
        else:
            self.send_response(404)
            self.end_headers()

    def do_PATCH(self):
        """处理 PATCH 请求（知识库元数据更新等）"""
        path = self.path.split('?')[0]
        if path.startswith('/api/admin/kb'):
            self._handle_kb_api('PATCH')
        else:
            self.send_response(404)
            self.end_headers()
    
    def _handle_session_api(self, path: str, method: str = 'POST'):
        """处理会话管理API请求"""
        print(f"[DEBUG] _handle_session_api 被调用，路径: {path}, 方法: {method}")
        if not MCPHTTPHandler.server_instance.session_service:
            print("[DEBUG] 会话服务未初始化")
            self.send_response(503)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "会话服务未初始化"}).encode('utf-8'))
            return
        
        try:
            session_service = MCPHTTPHandler.server_instance.session_service
            print(f"[DEBUG] 会话服务已初始化，开始处理请求")
            
            if method == 'GET':
                # GET /api/sessions - 获取会话列表
                if path == '/api/sessions':
                    sessions = session_service.list_sessions()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps(sessions, ensure_ascii=False).encode('utf-8'))
                # GET /api/sessions/{session_id} - 获取会话详情
                elif path.startswith('/api/sessions/'):
                    session_id = path.split('/')[-1]
                    session = session_service.get_session(session_id)
                    if session:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps(session, ensure_ascii=False).encode('utf-8'))
                    else:
                        self.send_response(404)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "会话不存在"}).encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()
                    
            elif method == 'POST':
                # POST /api/sessions - 创建会话
                if path == '/api/sessions':
                    content_length = int(self.headers.get('Content-Length', 0))
                    post_data = self.rfile.read(content_length)
                    data = json.loads(post_data.decode('utf-8'))
                    
                    session_id = data.get('session_id')
                    title = data.get('title')
                    
                    if not session_id:
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "缺少session_id"}).encode('utf-8'))
                        return
                    
                    session = session_service.create_session(session_id, title)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps(session, ensure_ascii=False).encode('utf-8'))
                
                # POST /api/sessions/{session_id}/messages - 添加消息
                elif path.endswith('/messages'):
                    print(f"[DEBUG] ========== 收到添加消息请求 ==========")
                    print(f"[DEBUG] 路径: {path}")
                    session_id = path.split('/')[3]
                    print(f"[DEBUG] 会话ID: {session_id}")
                    content_length = int(self.headers.get('Content-Length', 0))
                    print(f"[DEBUG] Content-Length: {content_length}")
                    post_data = self.rfile.read(content_length)
                    print(f"[DEBUG] 读取到数据长度: {len(post_data)}")
                    data = json.loads(post_data.decode('utf-8'))
                    print(f"[DEBUG] 解析后的数据: role={data.get('role')}, content长度={len(data.get('content', ''))}")
                    
                    role = data.get('role')
                    content = data.get('content')
                    
                    if not role or not content:
                        print(f"[ERROR] 缺少role或content: role={role}, content存在={bool(content)}")
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "缺少role或content"}).encode('utf-8'))
                        return
                    
                    extra = data.get('extra')
                    if extra is None and data.get('artifact'):
                        extra = {'artifact': data.get('artifact')}
                    if extra is not None and not isinstance(extra, dict):
                        extra = None

                    print(f"[DEBUG] 调用session_service.add_message...")
                    try:
                        message_id = session_service.add_message(session_id, role, content, extra=extra)
                        print(f"[DEBUG] ✅ 消息已添加，message_id: {message_id}")
                    except Exception as e:
                        print(f"[ERROR] 添加消息失败: {e}")
                        import traceback
                        traceback.print_exc()
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                        return
                    
                    print(f"[DEBUG] 准备发送响应...")
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    response_data = json.dumps({"message_id": message_id}, ensure_ascii=False).encode('utf-8')
                    print(f"[DEBUG] 响应数据长度: {len(response_data)}")
                    self.wfile.write(response_data)
                    self.wfile.flush()
                    print(f"[DEBUG] ✅ 响应已发送")
                    print(f"[DEBUG] =================================================")
                
                # POST /api/sessions/{session_id} - 更新会话
                elif path.startswith('/api/sessions/') and not path.endswith('/messages'):
                    try:
                        session_id = path.split('/')[-1]
                        print(f"[DEBUG] 收到更新会话请求: session_id={session_id}")
                        content_length = int(self.headers.get('Content-Length', 0))
                        post_data = self.rfile.read(content_length)
                        updates = json.loads(post_data.decode('utf-8'))
                        print(f"[DEBUG] 更新内容: {updates}")
                        
                        # 检查会话是否存在
                        existing_session = session_service.get_session(session_id)
                        if not existing_session:
                            print(f"[ERROR] 会话不存在: {session_id}")
                            self.send_response(404)
                            self.send_header('Content-Type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            self.wfile.write(json.dumps({"error": "会话不存在"}).encode('utf-8'))
                            return
                        
                        # 执行更新
                        session = session_service.update_session(session_id, updates)
                        if not session:
                            print(f"[ERROR] 更新会话失败: session_id={session_id}")
                            self.send_response(500)
                            self.send_header('Content-Type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            self.wfile.write(json.dumps({"error": "更新会话失败"}).encode('utf-8'))
                            return
                        
                        print(f"[DEBUG] ✅ 会话更新成功: {session.get('title', 'N/A')}")
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps(session, ensure_ascii=False).encode('utf-8'))
                    except ValueError as e:
                        print(f"[ERROR] 更新会话参数错误: {e}")
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                    except Exception as e:
                        print(f"[ERROR] 更新会话异常: {e}")
                        import traceback
                        traceback.print_exc()
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": f"更新会话失败: {str(e)}"}).encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()
                    
            elif method == 'DELETE':
                # DELETE /api/sessions/{session_id} - 删除会话
                if path.startswith('/api/sessions/'):
                    session_id = path.split('/')[-1]
                    if session_id == 'all':
                        # 删除所有会话
                        count = session_service.delete_all_sessions()
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"deleted_count": count}).encode('utf-8'))
                    else:
                        # 删除指定会话
                        print(f"[MCP Server] 收到删除会话请求: {session_id}")
                        print(f"[MCP Server] 调用 session_service.delete_session({session_id})")
                        deleted = session_service.delete_session(session_id)
                        print(f"[MCP Server] 删除结果: {deleted}")
                        if deleted:
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                            print(f"[MCP Server] ✅ 返回200成功响应")
                        else:
                            self.send_response(404)
                            self.send_header('Content-Type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            self.wfile.write(json.dumps({"error": "会话不存在"}).encode('utf-8'))
                            print(f"[MCP Server] ❌ 返回404错误响应")
                else:
                    self.send_response(404)
                    self.end_headers()
                    
        except Exception as e:
            print(f"[Session API] 错误: {e}")
            import traceback
            traceback.print_exc()
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
    
    def _handle_file_upload(self):
        """处理文件上传请求"""
        if not MCPHTTPHandler.server_instance.file_service:
            self.send_response(503)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "文件服务未初始化"}).encode('utf-8'))
            return
        
        try:
            # 解析multipart/form-data
            content_type = self.headers.get('Content-Type', '')
            if not content_type.startswith('multipart/form-data'):
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Content-Type必须是multipart/form-data"}).encode('utf-8'))
                return
            
            # 解析boundary
            boundary = None
            for part in content_type.split(';'):
                part = part.strip()
                if part.startswith('boundary='):
                    boundary = part[9:].strip('"')
                    break
            
            if not boundary:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "无法解析boundary"}).encode('utf-8'))
                return
            
            # 读取请求体
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            
            # 解析multipart数据
            parts = body.split(f'--{boundary}'.encode())
            file_data = None
            original_filename = None
            session_id = None
            description = None
            
            for part in parts:
                if not part.strip() or part.strip() == b'--':
                    continue
                
                # 分离头部和内容
                if b'\r\n\r\n' in part:
                    header, content = part.split(b'\r\n\r\n', 1)
                    # 使用更安全的解码方式处理header
                    try:
                        header_str = header.decode('utf-8', errors='replace')
                    except Exception:
                        # 如果UTF-8解码失败，尝试latin-1（不会失败）
                        header_str = header.decode('latin-1', errors='replace')
                    
                    # 检查是否是文件字段
                    if 'Content-Disposition: form-data' in header_str:
                        if 'name="file"' in header_str:
                            # 提取文件名 - 使用更安全的方式
                            if 'filename=' in header_str:
                                # 尝试从header bytes中直接提取文件名，避免编码问题
                                filename_match = None
                                # 方法1: 尝试从header_str提取
                                try:
                                    filename_start = header_str.find('filename="') + 10
                                    filename_end = header_str.find('"', filename_start)
                                    if filename_end > filename_start:
                                        filename_match = header_str[filename_start:filename_end]
                                except Exception:
                                    pass
                                
                                # 方法2: 如果方法1失败，从bytes中提取
                                if not filename_match:
                                    try:
                                        filename_bytes = header
                                        if b'filename="' in filename_bytes:
                                            start_idx = filename_bytes.find(b'filename="') + 10
                                            end_idx = filename_bytes.find(b'"', start_idx)
                                            if end_idx > start_idx:
                                                filename_bytes_part = filename_bytes[start_idx:end_idx]
                                                # 尝试多种编码
                                                for encoding in ['utf-8', 'latin-1', 'gbk', 'gb2312']:
                                                    try:
                                                        filename_match = filename_bytes_part.decode(encoding)
                                                        break
                                                    except (UnicodeDecodeError, UnicodeError):
                                                        continue
                                                # 如果都失败，使用latin-1（不会失败）
                                                if not filename_match:
                                                    filename_match = filename_bytes_part.decode('latin-1', errors='replace')
                                    except Exception as e:
                                        print(f"[File Upload] 文件名提取失败: {e}")
                                        filename_match = "uploaded_file"
                                
                                if filename_match:
                                    original_filename = filename_match
                                    # 移除末尾的\r\n
                                    file_data = content.rstrip(b'\r\n')
                        elif 'name="session_id"' in header_str:
                            try:
                                session_id = content.rstrip(b'\r\n').decode('utf-8', errors='ignore')
                                if not session_id:
                                    session_id = None
                            except Exception:
                                session_id = None
                        elif 'name="description"' in header_str:
                            try:
                                description = content.rstrip(b'\r\n').decode('utf-8', errors='ignore')
                                if not description:
                                    description = None
                            except Exception:
                                description = None
            
            # 验证文件
            if not file_data or not original_filename:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "未找到文件或文件名为空"}).encode('utf-8'))
                return
            
            # 保存文件
            file_service = MCPHTTPHandler.server_instance.file_service
            
            # 确保文件名是有效的Unicode字符串
            try:
                # 如果文件名不是有效的UTF-8，尝试修复
                if isinstance(original_filename, bytes):
                    original_filename = original_filename.decode('utf-8', errors='replace')
                elif not isinstance(original_filename, str):
                    original_filename = str(original_filename)
            except Exception as e:
                print(f"[File Upload] 文件名处理警告: {e}")
                original_filename = "uploaded_file"
            
            file_info = file_service.save_file(
                file_data=file_data,
                original_filename=original_filename,
                session_id=session_id,
                description=description
            )
            
            # 清理file_info中的字符串，确保可以安全序列化为JSON
            try:
                # 确保所有字符串字段都是有效的Unicode
                safe_file_info = {}
                for key, value in file_info.items():
                    if isinstance(value, str):
                        # 确保字符串可以安全编码为UTF-8
                        try:
                            value.encode('utf-8')
                            safe_file_info[key] = value
                        except UnicodeEncodeError:
                            # 如果编码失败，使用replace策略
                            safe_file_info[key] = value.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                    else:
                        safe_file_info[key] = value
            except Exception as e:
                print(f"[File Upload] 文件信息清理警告: {e}")
                safe_file_info = file_info
            
            # 返回文件信息
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                response_json = json.dumps(safe_file_info, ensure_ascii=False)
                self.wfile.write(response_json.encode('utf-8'))
            except Exception as e:
                print(f"[File Upload] JSON序列化错误: {e}")
                # 如果序列化失败，使用ASCII模式
                response_json = json.dumps(safe_file_info, ensure_ascii=True)
                self.wfile.write(response_json.encode('utf-8'))
            
        except Exception as e:
            print(f"[File Upload] 错误: {e}")
            import traceback
            traceback.print_exc()
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
    
    def _handle_file_api(self, path: str, method: str = 'GET'):
        """处理文件API请求"""
        if not MCPHTTPHandler.server_instance.file_service:
            self.send_response(503)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "文件服务未初始化"}).encode('utf-8'))
            return
        
        try:
            file_service = MCPHTTPHandler.server_instance.file_service
            
            if method == 'GET':
                # GET /api/files - 获取文件列表
                if path == '/api/files':
                    # 获取查询参数
                    import urllib.parse
                    query_params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    session_id = query_params.get('session_id', [None])[0]
                    limit = int(query_params.get('limit', [100])[0])
                    offset = int(query_params.get('offset', [0])[0])
                    
                    files = file_service.list_files(session_id=session_id, limit=limit, offset=offset)
                    
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps(files, ensure_ascii=False).encode('utf-8'))
                
                # GET /api/files/{file_id}/preview - 预览文件（内联显示）
                # 注意：必须在获取文件信息之前检查，因为路径匹配的顺序很重要
                elif path.endswith('/preview'):
                    file_id = path.split('/')[-2]
                    file_info = file_service.get_file(file_id)
                    
                    if not file_info:
                        self.send_response(404)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "文件不存在"}).encode('utf-8'))
                        return
                    
                    file_data = file_service.get_file_data(file_id)
                    if not file_data:
                        self.send_response(404)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "文件数据不存在"}).encode('utf-8'))
                        return
                    
                    # 发送文件（内联显示，用于预览）
                    mime_type = file_info.get('mime_type', 'application/octet-stream')
                    original_name = file_info["original_name"]
                    
                    # 处理中文文件名编码问题
                    # 使用RFC 5987标准编码文件名，支持中文
                    # 注意：Python HTTP服务器在发送响应头时使用latin-1编码，无法直接包含中文字符
                    import urllib.parse
                    encoded_filename = urllib.parse.quote(original_name.encode('utf-8'))
                    # 生成ASCII安全的fallback文件名（移除所有非ASCII字符）
                    safe_filename = ''.join(c if ord(c) < 128 else '_' for c in original_name) or 'file'
                    # 只使用filename*参数支持中文，filename参数使用ASCII安全的名称
                    content_disposition = f'inline; filename="{safe_filename}"; filename*=UTF-8\'\'{encoded_filename}'
                    
                    self.send_response(200)
                    self.send_header('Content-Type', mime_type)
                    # 使用 inline 让浏览器直接显示文件，而不是下载
                    self.send_header('Content-Disposition', content_disposition)
                    self.send_header('Content-Length', str(len(file_data)))
                    self.send_header('Access-Control-Allow-Origin', '*')
                    # 添加缓存控制，确保文件可以完整加载
                    self.send_header('Cache-Control', 'public, max-age=3600')
                    self.end_headers()
                    self.wfile.write(file_data)
                
                # GET /api/files/{file_id}/download - 下载文件（原文件）
                elif path.endswith('/download'):
                    file_id = path.split('/')[-2]
                    file_info = file_service.get_file(file_id)
                    
                    if not file_info:
                        self.send_response(404)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "文件不存在"}).encode('utf-8'))
                        return
                    
                    # 获取原始文件数据（确保是二进制模式读取）
                    file_data = file_service.get_file_data(file_id)
                    if not file_data:
                        self.send_response(404)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "文件数据不存在"}).encode('utf-8'))
                        return
                    
                    # 验证文件数据完整性
                    stored_file_size = file_info.get('file_size', 0)
                    actual_file_size = len(file_data)
                    if stored_file_size > 0 and actual_file_size != stored_file_size:
                        print(f"[File Download] 警告: 文件大小不匹配 - 存储大小: {stored_file_size}, 实际大小: {actual_file_size}")
                    
                    # 发送文件（下载模式，确保是原始文件）
                    mime_type = file_info.get('mime_type', 'application/octet-stream')
                    original_name = file_info["original_name"]
                    
                    # 处理中文文件名编码问题
                    # 使用RFC 5987标准编码文件名，支持中文
                    # 注意：Python HTTP服务器在发送响应头时使用latin-1编码，无法直接包含中文字符
                    import urllib.parse
                    encoded_filename = urllib.parse.quote(original_name.encode('utf-8'))
                    # 生成ASCII安全的fallback文件名（移除所有非ASCII字符）
                    safe_filename = ''.join(c if ord(c) < 128 else '_' for c in original_name) or 'file'
                    # 只使用filename*参数支持中文，filename参数使用ASCII安全的名称
                    content_disposition = f'attachment; filename="{safe_filename}"; filename*=UTF-8\'\'{encoded_filename}'
                    
                    self.send_response(200)
                    self.send_header('Content-Type', mime_type)
                    self.send_header('Content-Disposition', content_disposition)
                    self.send_header('Content-Length', str(len(file_data)))
                    self.send_header('Access-Control-Allow-Origin', '*')
                    # 确保浏览器不会对文件进行任何处理，直接下载原文件
                    self.send_header('Content-Transfer-Encoding', 'binary')
                    self.end_headers()
                    
                    # 直接写入原始二进制数据（确保不被编码转换）
                    self.wfile.write(file_data)
                    self.wfile.flush()
                    
                    print(f"[File Download] 已发送原文件: {original_name} ({actual_file_size} 字节)")
                
                # GET /api/files/{file_id} - 获取文件信息（JSON格式）
                # 注意：必须在 /preview 和 /download 之后检查
                elif path.startswith('/api/files/'):
                    file_id = path.split('/')[-1]
                    file_info = file_service.get_file(file_id)
                    
                    if file_info:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps(file_info, ensure_ascii=False).encode('utf-8'))
                    else:
                        self.send_response(404)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "文件不存在"}).encode('utf-8'))
            
            elif method == 'DELETE':
                # DELETE /api/files/{file_id} - 删除文件
                if path.startswith('/api/files/'):
                    file_id = path.split('/')[-1]
                    success = file_service.delete_file(file_id)
                    
                    if success:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": True, "message": "文件已删除"}).encode('utf-8'))
                    else:
                        self.send_response(404)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "文件不存在"}).encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()
            else:
                self.send_response(405)
                self.end_headers()
                
        except Exception as e:
            print(f"[File API] 错误: {e}")
            import traceback
            traceback.print_exc()
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

    def do_PUT(self):
        path = self.path.split('?')[0]
        if path.startswith('/api/skills/'):
            self._handle_skills_api('PUT')
        elif path.startswith('/api/admin/users/') or path.startswith('/api/admin/roles/') or path.startswith('/api/admin/permissions/') or path.startswith('/api/admin/cases/') or path.startswith('/api/admin/clients/'):
            self._handle_rbac_api('PUT')
        elif path == '/api/admin/mcp-config':
            self._handle_mcp_config_api('PUT')
        elif path.startswith('/api/admin/profiles/'):
            self._handle_admin_profiles_api('PUT')
        else:
            self.send_response(404)
            self.end_headers()

    def _read_json_body(self) -> dict:
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length) if length else b'{}'
        if not raw:
            return {}
        return json.loads(raw.decode('utf-8'))

    def _write_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_rbac_api(self, method: str):
        api = getattr(MCPHTTPHandler.server_instance, "rbac_api", None)
        if not api:
            self._write_json(503, {"error": "RBAC 服务未初始化"})
            return
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query or "")
            authz = self.headers.get("Authorization")
            body = {}
            if method in ("POST", "PUT"):
                body = self._read_json_body() or {}

            if path == "/api/auth/login" and method == "POST":
                self._write_json(*api.login(body))
                return
            if path == "/api/auth/logout" and method == "POST":
                self._write_json(*api.logout(authz))
                return
            if path == "/api/auth/me" and method == "GET":
                case_id = qs.get("case_id", [None])[0]
                self._write_json(*api.me(authz, int(case_id) if case_id else None))
                return

            if path == "/api/admin/users" and method == "GET":
                self._write_json(*api.list_users(authz))
                return
            if path == "/api/admin/users" and method == "POST":
                self._write_json(*api.create_user(authz, body))
                return
            if path.startswith("/api/admin/users/") and method == "PUT":
                user_id = int(path.rstrip("/").split("/")[-1])
                self._write_json(*api.update_user(authz, user_id, body))
                return

            if path == "/api/admin/roles" and method == "GET":
                self._write_json(*api.list_roles(authz))
                return
            if path.startswith("/api/admin/roles/") and method == "PUT":
                code = path.rstrip("/").split("/")[-1]
                self._write_json(*api.update_role(authz, code, body))
                return

            if path == "/api/admin/permissions" and method == "GET":
                self._write_json(*api.list_permissions(authz))
                return
            if path.startswith("/api/admin/permissions/") and method == "PUT":
                code = path.rstrip("/").split("/")[-1]
                self._write_json(*api.update_permission(authz, code, body))
                return

            if path == "/api/admin/cases" and method == "GET":
                mine = qs.get("mine", ["0"])[0] in ("1", "true", "True")
                self._write_json(*api.list_cases(authz, mine=mine))
                return
            if path == "/api/admin/cases/next-no" and method == "GET":
                case_type = qs.get("case_type", [""])[0]
                self._write_json(*api.preview_case_no(authz, case_type))
                return
            if path == "/api/admin/cases" and method == "POST":
                self._write_json(*api.create_case(authz, body))
                return
            if path.startswith("/api/admin/cases/") and "/members/" in path and method == "DELETE":
                parts = path.rstrip("/").split("/")
                # /api/admin/cases/{id}/members/{user_id}
                case_id = int(parts[4])
                user_id = int(parts[6])
                self._write_json(*api.remove_member(authz, case_id, user_id))
                return
            if path.endswith("/members") and method == "POST":
                case_id = int(path.rstrip("/").split("/")[-2])
                self._write_json(*api.add_member(authz, case_id, body))
                return
            if path.startswith("/api/admin/cases/") and method == "GET":
                case_id = int(path.rstrip("/").split("/")[-1])
                self._write_json(*api.get_case(authz, case_id))
                return
            if path.startswith("/api/admin/cases/") and method == "PUT":
                case_id = int(path.rstrip("/").split("/")[-1])
                self._write_json(*api.update_case(authz, case_id, body))
                return
            if path.startswith("/api/admin/cases/") and method == "DELETE" and "/members/" not in path:
                case_id = int(path.rstrip("/").split("/")[-1])
                self._write_json(*api.delete_case(authz, case_id))
                return

            if path == "/api/admin/clients" and method == "GET":
                self._write_json(*api.list_clients(authz))
                return
            if path.startswith("/api/admin/clients/") and method == "GET":
                client_id = int(path.rstrip("/").split("/")[-1])
                self._write_json(*api.get_client(authz, client_id))
                return
            if path == "/api/admin/clients" and method == "POST":
                self._write_json(*api.create_client(authz, body))
                return
            if path.startswith("/api/admin/clients/") and method == "PUT":
                client_id = int(path.rstrip("/").split("/")[-1])
                self._write_json(*api.update_client(authz, client_id, body))
                return
            if path.startswith("/api/admin/clients/") and method == "DELETE":
                client_id = int(path.rstrip("/").split("/")[-1])
                self._write_json(*api.delete_client(authz, client_id))
                return

            self._write_json(404, {"error": "未找到接口"})
        except Exception as e:
            import traceback
            print(f"[ERROR] rbac api: {e}\n{traceback.format_exc()}")
            self._write_json(400, {"error": "RBAC 请求失败", "detail": str(e)})

    def _sync_kb_vector_service(self, api) -> None:
        """Refresh kb_api.vector_service after async VectorService init."""
        server = MCPHTTPHandler.server_instance
        if not server.vector_service and getattr(server, "_vector_service_init_thread", None):
            if not server._vector_service_init_thread.is_alive():
                lock = getattr(server, "_vector_service_init_lock", None)
                if lock:
                    with lock:
                        if server._vector_service_instance[0]:
                            server.vector_service = server._vector_service_instance[0]
                            server._attach_fts_if_ready()
                elif getattr(server, "_vector_service_instance", [None])[0]:
                    server.vector_service = server._vector_service_instance[0]
                    server._attach_fts_if_ready()
        api.vector_service = server.vector_service
        api.file_service = server.file_service

    def _handle_kb_api(self, method: str):
        api = getattr(MCPHTTPHandler.server_instance, "kb_api", None)
        if not api:
            self._write_json(503, {"error": "知识库服务未初始化"})
            return
        try:
            from urllib.parse import urlparse, parse_qs
            from http_kb_api import parse_kb_path
            self._sync_kb_vector_service(api)
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            qs = parse_qs(parsed.query or "")
            authz = self.headers.get("Authorization")
            body = {}
            if method in ("POST", "PATCH", "PUT"):
                body = self._read_json_body() or {}

            action, doc_id = parse_kb_path(path, method)
            if action == "list":
                doc_type = qs.get("doc_type", [""])[0]
                limit = qs.get("limit", ["50"])[0]
                offset = qs.get("offset", ["0"])[0]
                self._write_json(
                    *api.list_documents(authz, doc_type, limit=limit, offset=offset)
                )
                return
            if action == "create":
                self._write_json(*api.create_from_file(authz, body))
                return
            if action == "search":
                self._write_json(*api.search(authz, body))
                return
            if action == "get" and doc_id:
                self._write_json(*api.get_document(authz, doc_id))
                return
            if action in ("patch", "update") and doc_id:
                self._write_json(*api.patch_document(authz, doc_id, body))
                return
            if action == "delete" and doc_id:
                self._write_json(*api.delete_document(authz, doc_id))
                return

            self._write_json(404, {"error": "未找到接口"})
        except Exception as e:
            import traceback
            print(f"[ERROR] kb api: {e}\n{traceback.format_exc()}")
            self._write_json(400, {"error": "知识库请求失败", "detail": str(e)})

    def _handle_orchestrate_api(self):
        try:
            from http_api_extra import handle_orchestrate
            body = self._read_json_body() or {}
            api = getattr(MCPHTTPHandler.server_instance, "rbac_api", None)
            if api is not None:
                status, payload = api.check_orchestrate_access(
                    self.headers.get("Authorization"), body
                )
                if status != 200:
                    self._write_json(status, payload)
                    return
                body["_auth_user_id"] = payload["user"]["id"]
                body["case_id"] = payload["case_id"]
            want_stream = bool(body.get("stream")) or "stream=1" in (self.path or "")
            if want_stream:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Private-Network', 'true')
                self.end_headers()

                def on_event(event):
                    payload = json.dumps({"type": "step", **event}, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()

                result = handle_orchestrate(MCPHTTPHandler.server_instance, body, on_event=on_event)
                done = json.dumps({"type": "done", "result": result}, ensure_ascii=False)
                self.wfile.write(f"data: {done}\n\n".encode("utf-8"))
                self.wfile.flush()
                return
            result = handle_orchestrate(MCPHTTPHandler.server_instance, body)
            self._write_json(200, result)
        except Exception as e:
            import traceback
            print(f"[ERROR] orchestrate: {e}\n{traceback.format_exc()}")
            self._write_json(400, {"error": "任务编排失败", "detail": str(e)})

    def _handle_skills_api(self, method: str):
        try:
            from http_api_extra import skill_id_from_path, skill_service
            svc = skill_service()
            path = self.path.split('?')[0]
            sid = skill_id_from_path(path)
            if method == 'GET':
                if sid:
                    self._write_json(200, svc.get(sid))
                else:
                    self._write_json(200, {"skills": svc.list_skills()})
                return
            if method == 'POST' and path.rstrip('/') == '/api/skills':
                created = svc.create(self._read_json_body())
                self._write_json(201, created)
                return
            if method == 'PUT' and sid:
                updated = svc.update(sid, self._read_json_body())
                self._write_json(200, updated)
                return
            if method == 'DELETE' and sid:
                svc.delete(sid)
                self._write_json(200, {"ok": True})
                return
            self._write_json(405, {"error": "method not allowed"})
        except FileNotFoundError:
            self._write_json(404, {"error": "skill not found"})
        except Exception as e:
            self._write_json(400, {"error": str(e)})

    def _handle_admin_profiles_api(self, method: str):
        try:
            from http_api_extra import (
                handle_profile_create,
                handle_profile_delete,
                handle_profile_get,
                handle_profile_update,
                profile_path_parts,
                public_profiles,
            )
            path = self.path.split('?')[0]
            parts = profile_path_parts(path)
            if method == 'GET':
                if path.rstrip('/') == '/api/admin/profiles':
                    self._write_json(200, public_profiles())
                    return
                if parts:
                    self._write_json(200, handle_profile_get(parts[0], parts[1]))
                    return
                self._write_json(404, {"error": "not found"})
                return
            if method == 'POST' and path.rstrip('/') == '/api/admin/profiles':
                self._write_json(201, handle_profile_create(self._read_json_body()))
                return
            if method == 'PUT' and parts:
                self._write_json(200, handle_profile_update(parts[0], parts[1], self._read_json_body()))
                return
            if method == 'DELETE' and parts:
                self._write_json(200, handle_profile_delete(parts[0], parts[1]))
                return
            self._write_json(405, {"error": "method not allowed"})
        except FileNotFoundError:
            self._write_json(404, {"error": "profile not found"})
        except ValueError as e:
            self._write_json(400, {"error": str(e)})
        except Exception as e:
            self._write_json(400, {"error": str(e)})

    def _handle_admin_stats_api(self):
        try:
            from http_api_extra import admin_overview_stats
            self._write_json(200, admin_overview_stats(MCPHTTPHandler.server_instance))
        except Exception as e:
            self._write_json(500, {"error": str(e)})

    def _handle_mcp_config_api(self, method: str):
        try:
            from http_api_extra import apply_mcp_config, public_mcp_config
            if method == 'GET':
                self._write_json(200, public_mcp_config())
                return
            if method in ('PUT', 'POST'):
                self._write_json(200, apply_mcp_config(self._read_json_body()))
                return
            self._write_json(405, {"error": "method not allowed"})
        except Exception as e:
            self._write_json(400, {"error": str(e)})
    
    def log_message(self, format, *args):
        """禁用默认日志输出"""
        pass


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """支持多线程的HTTP服务器"""
    daemon_threads = True  # 允许主线程退出时自动终止工作线程

def run_server(port=8000):
    """启动HTTP服务器（多线程版本）"""
    server_address = ('', port)
    httpd = ThreadingHTTPServer(server_address, MCPHTTPHandler)
    print(f"MCP服务器已启动（多线程模式），监听端口 {port}")
    print(f"访问 http://localhost:{port}/health 进行健康检查")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
        httpd.shutdown()


if __name__ == "__main__":
    import sys
    port = load_mcp_listen_port(8000)
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    run_server(port)

