# 知识库向量化（法规库 / 裁判案例库）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理后台新增「知识库 · 法规库 / 裁判案例库」：上传文件 → LLM 抽元数据 → 自动写入 `kb_documents` + Chroma（`doc_type` 过滤），并支持列表编辑元数据、删除与试检索。

**Architecture:** 新建 SQLite `kb.db` 存知识条目；`kb_meta_extract` 按 schema 调 LLM；`kb_ingest` 编排「提文本→抽元数据→落库→向量化」；`http_kb_api` 提供 `/api/admin/kb/*`；扩展 `VectorService.search(..., where=)` 与 `update_document_metadata`；两页管理 UI 共用权限 `cap.vectorize`。原 `vectorize.html` 降级为「向量调试」。

**Tech Stack:** Python 3 + sqlite3、现有 `llm_complete.complete_chat`、ChromaDB `VectorService`、`FileService`、`http.server` MCP 路由、静态 HTML/JS（`admin_ui.js` / `admin_nav.js`）。

## Global Constraints

- 规格：`docs/superpowers/specs/2026-09-04-knowledge-base-vectorize-design.md`（已定稿）
- 单集合 `legal_documents` + 强制 `doc_type` ∈ {`law`,`case`}；检索必须带类型过滤
- 上传后自动入库，无人工确认门禁；元数据缺失不阻断向量化
- 与办案 `cases` / `cap.case_manage` **无数据耦合**
- 首版权限：`cap.vectorize`（及既有 `page.admin.vectorize`）；不拆新权限码
- 元数据更新策略：**只更新 Chroma chunk metadata，不重切正文**（正文变更才删旧再向量化——首版不做正文替换）
- 开放问题锁定（P0）：`procedure` 自由文本；不做「指导案例编号」字段；`vectorize.html` 改名为「向量调试」并保留入口
- 测试用临时目录下的 `kb.db` / chroma；不碰开发机真实库；LLM 测试注入假 `complete_fn`
- 不改造对话 `legal_retrieval`（P2）

## File map

| File | Responsibility |
|------|----------------|
| `server/kb_store.py` | `kb_documents` schema + CRUD |
| `server/kb_meta_extract.py` | 法规/案例 JSON schema 抽取与解析 |
| `server/kb_ingest.py` | 上传入库管道（文本→元数据→条目→向量） |
| `server/http_kb_api.py` | `/api/admin/kb/*` 可测 handler |
| `server/vector_service.py` | `where` 检索、按 `document_id` 更新 metadata |
| `server/mcp_server.py` | 挂载 KB API、初始化 `KbStore` |
| `admin_nav.js` | 知识库双子页 + 向量调试标签 |
| `admin_kb_laws.html` | 法规库 UI |
| `admin_kb_cases.html` | 裁判案例库 UI |
| `admin.html` | 工具区卡片指向法规库（可选统计） |
| `vectorize.html` | 标题改为向量调试（轻改） |
| `tests/test_kb_store.py` 等 | 单元与 API 测试 |

---

### Task 1: `KbStore`（SQLite 知识条目）

**Files:**
- Create: `server/kb_store.py`
- Test: `tests/test_kb_store.py`

**Interfaces:**
- Produces:
  - `DOC_TYPES = ("law", "case")`
  - `STATUSES = ("processing", "ready", "meta_failed", "vector_failed", "extract_failed", "deleted")`
  - `KbStore(db_path: str)`
  - `ensure_schema() -> None`
  - `create_document(*, id: str, doc_type: str, file_id: str|None, title: str, status: str, meta: dict, created_by: str|None) -> dict`
  - `get_document(id: str) -> dict|None`（不含 `deleted` 除非 `include_deleted=True`）
  - `list_documents(*, doc_type: str, limit: int=50, offset: int=0) -> list[dict]`
  - `count_documents(*, doc_type: str|None=None) -> int`（不含 deleted）
  - `update_document(id: str, *, title: str|None=None, status: str|None=None, meta: dict|None=None) -> dict|None`
  - `soft_delete(id: str) -> bool`

行字段：`id, doc_type, file_id, title, status, meta_json, created_at, updated_at, created_by`。返回 dict 时 `meta` 为解析后的对象。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kb_store.py
import os
import tempfile
import unittest

from kb_store import KbStore


class TestKbStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = KbStore(os.path.join(self.tmp.name, "kb.db"))
        self.store.ensure_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_list_by_type(self):
        self.store.create_document(
            id="kb_law_1",
            doc_type="law",
            file_id="f1",
            title="劳动合同法",
            status="ready",
            meta={"law_name": "劳动合同法", "effect_level": "法律"},
            created_by="u1",
        )
        self.store.create_document(
            id="kb_case_1",
            doc_type="case",
            file_id="f2",
            title="(2020)京01民终1号",
            status="ready",
            meta={"case_no": "(2020)京01民终1号", "case_kind": "ordinary"},
            created_by="u1",
        )
        laws = self.store.list_documents(doc_type="law")
        self.assertEqual(len(laws), 1)
        self.assertEqual(laws[0]["meta"]["law_name"], "劳动合同法")
        self.assertEqual(self.store.count_documents(doc_type="law"), 1)
        self.assertEqual(self.store.count_documents(doc_type="case"), 1)

    def test_soft_delete_hides_from_list(self):
        self.store.create_document(
            id="kb_x",
            doc_type="law",
            file_id=None,
            title="x",
            status="ready",
            meta={},
            created_by=None,
        )
        self.assertTrue(self.store.soft_delete("kb_x"))
        self.assertEqual(self.store.list_documents(doc_type="law"), [])
        self.assertIsNone(self.store.get_document("kb_x"))
        self.assertIsNotNone(self.store.get_document("kb_x", include_deleted=True))

    def test_update_meta_and_status(self):
        self.store.create_document(
            id="kb_u",
            doc_type="case",
            file_id="f",
            title="旧",
            status="meta_failed",
            meta={},
            created_by=None,
        )
        row = self.store.update_document(
            "kb_u",
            title="新案号",
            status="ready",
            meta={"case_no": "新案号", "case_kind": "guiding"},
        )
        self.assertEqual(row["title"], "新案号")
        self.assertEqual(row["status"], "ready")
        self.assertEqual(row["meta"]["case_kind"], "guiding")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kanglinlin/Documents/cursor/AI法官 && PYTHONPATH=server python3 -m pytest tests/test_kb_store.py -v`  
Expected: FAIL（无法 import `kb_store`）

- [ ] **Step 3: Write minimal implementation**

实现 `server/kb_store.py`：

```python
# server/kb_store.py（要点）
import json, sqlite3, time
from typing import Any, Dict, List, Optional

DOC_TYPES = ("law", "case")
STATUSES = ("processing", "ready", "meta_failed", "vector_failed", "extract_failed", "deleted")

class KbStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_documents (
              id TEXT PRIMARY KEY,
              doc_type TEXT NOT NULL,
              file_id TEXT,
              title TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              meta_json TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              created_by TEXT
            )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kb_doc_type_status ON kb_documents(doc_type, status)"
            )

    def _row_to_dict(self, row) -> Dict[str, Any]:
        d = dict(row)
        d["meta"] = json.loads(d.pop("meta_json") or "{}")
        return d

    # create_document / get_document / list_documents / count_documents /
    # update_document / soft_delete —— 按 Interfaces 实现；
    # create/update 校验 doc_type∈DOC_TYPES、status∈STATUSES；
    # list/get 默认排除 status='deleted'
```

- [ ] **Step 4: Run tests — expect pass**

Run: `PYTHONPATH=server python3 -m pytest tests/test_kb_store.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/kb_store.py tests/test_kb_store.py
git commit -m "feat(kb): add kb_documents SQLite store"
```

---

### Task 2: `VectorService` — `where` 检索 + 更新 metadata

**Files:**
- Modify: `server/vector_service.py`
- Test: `tests/test_vector_service_kb.py`

**Interfaces:**
- Consumes: 现有 `add_document` / `delete_document`
- Produces:
  - `search(self, query: str, n_results: int = 5, boost_keywords: bool = True, where: Optional[Dict] = None) -> List[Dict]`
  - `update_document_metadata(self, document_id: str, metadata: Dict) -> Dict`  
    行为：`get(where={"document_id": document_id})` → 对每个 chunk `metadata` **浅合并** `metadata`（保留 `document_id`/`chunk_index`/`total_chunks`）→ `collection.update(ids=..., metadatas=...)`；值一律转为 Chroma 标量（`None` 跳过；list 用 `"; "` join 成 str）
  - `count_by_doc_type(self, doc_type: str) -> int`（按唯一 `document_id` 计，metadata.doc_type 匹配）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vector_service_kb.py
import os
import tempfile
import unittest

from vector_service import VectorService


class TestVectorServiceKb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vs = VectorService(persist_directory=os.path.join(self.tmp.name, "chroma"))
        # 强制哈希向量，避免下载模型
        self.vs.model = None

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_filters_by_doc_type(self):
        self.vs.add_document("d_law", "劳动合同法第五十条 劳动者权利", {
            "doc_type": "law", "title": "劳动合同法", "law_name": "劳动合同法"
        })
        self.vs.add_document("d_case", "劳动合同法第五十条 相关判决事实", {
            "doc_type": "case", "title": "案1", "case_no": "A1"
        })
        laws = self.vs.search("第五十条", n_results=5, boost_keywords=False, where={"doc_type": "law"})
        cases = self.vs.search("第五十条", n_results=5, boost_keywords=False, where={"doc_type": "case"})
        self.assertTrue(all(r["metadata"].get("doc_type") == "law" for r in laws))
        self.assertTrue(all(r["metadata"].get("doc_type") == "case" for r in cases))
        self.assertTrue(any(r["metadata"].get("document_id") == "d_law" for r in laws))
        self.assertTrue(any(r["metadata"].get("document_id") == "d_case" for r in cases))

    def test_update_document_metadata_merges(self):
        self.vs.add_document("d1", "正文一段用于切分测试。" * 20, {
            "doc_type": "case", "title": "旧", "case_no": "旧号"
        })
        out = self.vs.update_document_metadata("d1", {
            "title": "新", "case_no": "新号", "court": "北京一中院", "judges": ["张三", "李四"]
        })
        self.assertTrue(out["success"])
        got = self.vs.collection.get(where={"document_id": "d1"}, include=["metadatas"])
        self.assertTrue(got["ids"])
        meta = got["metadatas"][0]
        self.assertEqual(meta["title"], "新")
        self.assertEqual(meta["case_no"], "新号")
        self.assertEqual(meta["court"], "北京一中院")
        self.assertEqual(meta["judges"], "张三; 李四")
        self.assertEqual(meta["doc_type"], "case")
        self.assertIn("chunk_index", meta)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=server python3 -m pytest tests/test_vector_service_kb.py -v`  
Expected: FAIL（`search` 不接受 `where` 或无 `update_document_metadata`）

- [ ] **Step 3: Implement**

在 `search` 的 `collection.query(...)` 增加：

```python
kwargs = dict(query_embeddings=[query_embedding], n_results=query_n_results)
if where:
    kwargs["where"] = where
results = self.collection.query(**kwargs)
```

新增：

```python
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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `PYTHONPATH=server python3 -m pytest tests/test_vector_service_kb.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/vector_service.py tests/test_vector_service_kb.py
git commit -m "feat(vector): filter search by metadata and update chunk meta"
```

---

### Task 3: `kb_meta_extract`（LLM JSON 抽取）

**Files:**
- Create: `server/kb_meta_extract.py`
- Test: `tests/test_kb_meta_extract.py`

**Interfaces:**
- Produces:
  - `LAW_META_KEYS = ("law_name", "effect_level", "issuing_authority", "document_number", "effective_date")`
  - `CASE_META_KEYS = ("cause_of_action", "court", "procedure", "case_no", "judges", "case_kind")`
  - `parse_json_object(text: str) -> dict`（剥离 markdown 代码篱，失败 raise `ValueError`）
  - `normalize_law_meta(raw: dict) -> dict` / `normalize_case_meta(raw: dict) -> dict`  
    - 只保留已知键；缺省 `""`；`case_kind` 仅允许 `ordinary`|`guiding`，否则 `ordinary`；`judges` 若 list 则 join 为 `"; "` 字符串
  - `extract_metadata(doc_type: str, text: str, *, complete_fn=None) -> tuple[dict, str]`  
    返回 `(meta, status)`，`status` 为 `"ready"` 或 `"meta_failed"`；`complete_fn(system, user) -> str`，默认 `llm_complete.complete_chat`；截断正文至 12000 字；temperature 由 `complete_chat` 配置控制（调用方可在假函数中忽略）

System prompt（法规）要点：只输出 JSON；字段中文含义见规格；未知填 `""`。  
System prompt（案例）同理，并说明 `case_kind` 取值。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kb_meta_extract.py
import unittest
from kb_meta_extract import extract_metadata, parse_json_object, normalize_case_meta


class TestKbMetaExtract(unittest.TestCase):
    def test_parse_fenced_json(self):
        raw = '```json\n{"law_name":"民法典","effect_level":"法律"}\n```'
        self.assertEqual(parse_json_object(raw)["law_name"], "民法典")

    def test_normalize_case_kind_and_judges(self):
        m = normalize_case_meta({
            "case_kind": "指导",
            "judges": ["甲", "乙"],
            "case_no": "1号",
        })
        self.assertEqual(m["case_kind"], "ordinary")  # 非法值回落
        self.assertEqual(m["judges"], "甲; 乙")
        m2 = normalize_case_meta({"case_kind": "guiding", "judges": "甲"})
        self.assertEqual(m2["case_kind"], "guiding")

    def test_extract_success(self):
        def fake(system, user):
            return '{"law_name":"X法","effect_level":"法律","issuing_authority":"全国人大","document_number":"","effective_date":"2008-01-01"}'

        meta, status = extract_metadata("law", "正文", complete_fn=fake)
        self.assertEqual(status, "ready")
        self.assertEqual(meta["law_name"], "X法")

    def test_extract_failure_returns_empty_meta(self):
        def fake(system, user):
            return "不是JSON"

        meta, status = extract_metadata("case", "正文", complete_fn=fake)
        self.assertEqual(status, "meta_failed")
        self.assertEqual(meta["case_kind"], "ordinary")
        self.assertEqual(meta["case_no"], "")
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTHONPATH=server python3 -m pytest tests/test_kb_meta_extract.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement `server/kb_meta_extract.py`**（完整实现上述接口与两套 system prompt）

- [ ] **Step 4: Run — expect pass**

Run: `PYTHONPATH=server python3 -m pytest tests/test_kb_meta_extract.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/kb_meta_extract.py tests/test_kb_meta_extract.py
git commit -m "feat(kb): add LLM metadata extractors for laws and cases"
```

---

### Task 4: `kb_ingest` 管道

**Files:**
- Create: `server/kb_ingest.py`
- Test: `tests/test_kb_ingest.py`

**Interfaces:**
- Produces:
  - `new_document_id(doc_type: str) -> str`  # 如 `kb_law_<uuid4.hex[:12]>`
  - `title_from_meta(doc_type: str, meta: dict, fallback: str = "") -> str`  
    law → `law_name` or fallback；case → `case_no` or `cause_of_action` or fallback
  - `chunk_metadata(doc_type: str, document_id: str, file_id: str|None, title: str, meta: dict) -> dict`  
    公共：`document_id, doc_type, title, file_id(optional), source="kb"` + 业务字段（全标量化）
  - `ingest_uploaded_file(*, doc_type, file_id, created_by, kb_store, file_service, vector_service, complete_fn=None) -> dict`  
    流程：
    1. 校验 `doc_type`
    2. `text = file_service.get_file_text(file_id)`；若空 → 建条目 `extract_failed`，**不**向量化，返回条目
    3. 建条目 `processing`（title 暂用 file_id）
    4. `meta, meta_status = extract_metadata(...)`
    5. `title = title_from_meta(...)`
    6. `vector_service.add_document(document_id, text, chunk_metadata(...))`
    7. 成功 → `update_document(..., status=meta_status if meta_status=="meta_failed" else "ready", title=..., meta=...)`  
       失败 → `status=vector_failed`，仍保留 meta
    8. 返回最终 `get_document`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kb_ingest.py
import os, tempfile, unittest
from kb_store import KbStore
from kb_ingest import ingest_uploaded_file, title_from_meta
from vector_service import VectorService


class FakeFileService:
    def __init__(self, mapping):
        self.mapping = mapping
    def get_file_text(self, file_id):
        return self.mapping.get(file_id)


class TestKbIngest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kb = KbStore(os.path.join(self.tmp.name, "kb.db"))
        self.kb.ensure_schema()
        self.vs = VectorService(persist_directory=os.path.join(self.tmp.name, "chroma"))
        self.vs.model = None
        self.files = FakeFileService({"f1": "中华人民共和国劳动合同法 第一条 …" * 5})

    def tearDown(self):
        self.tmp.cleanup()

    def test_title_from_meta(self):
        self.assertEqual(title_from_meta("law", {"law_name": "民法典"}, "x"), "民法典")
        self.assertEqual(title_from_meta("case", {"case_no": "", "cause_of_action": "劳动争议"}, "x"), "劳动争议")

    def test_ingest_happy_path(self):
        def fake(system, user):
            return '{"law_name":"劳动合同法","effect_level":"法律","issuing_authority":"全国人大常委会","document_number":"","effective_date":"2008-01-01"}'
        doc = ingest_uploaded_file(
            doc_type="law",
            file_id="f1",
            created_by="u1",
            kb_store=self.kb,
            file_service=self.files,
            vector_service=self.vs,
            complete_fn=fake,
        )
        self.assertEqual(doc["status"], "ready")
        self.assertEqual(doc["meta"]["law_name"], "劳动合同法")
        hits = self.vs.search("劳动合同法", n_results=3, boost_keywords=False, where={"doc_type": "law"})
        self.assertTrue(any(h["metadata"]["document_id"] == doc["id"] for h in hits))

    def test_ingest_empty_text(self):
        files = FakeFileService({"f2": None})
        doc = ingest_uploaded_file(
            doc_type="case",
            file_id="f2",
            created_by=None,
            kb_store=self.kb,
            file_service=files,
            vector_service=self.vs,
            complete_fn=lambda s, u: "{}",
        )
        self.assertEqual(doc["status"], "extract_failed")
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTHONPATH=server python3 -m pytest tests/test_kb_ingest.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement `server/kb_ingest.py`**

- [ ] **Step 4: Run — expect pass**

Run: `PYTHONPATH=server python3 -m pytest tests/test_kb_ingest.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/kb_ingest.py tests/test_kb_ingest.py
git commit -m "feat(kb): add upload ingest pipeline with auto vectorize"
```

---

### Task 5: `http_kb_api` + 路由挂载

**Files:**
- Create: `server/http_kb_api.py`
- Modify: `server/mcp_server.py`（初始化 `KbStore`，路由分发）
- Test: `tests/test_http_kb_api.py`

**Interfaces:**
- Produces: `KbHttpApi(store: KbStore, auth: AuthService, rbac: RbacService, *, file_service, vector_service, complete_fn=None)`
  - `POST /documents` body `{doc_type, file_id}` → `ingest_uploaded_file`；需 `cap.vectorize`
  - `GET /documents?doc_type=&limit=&offset=` → list
  - `GET /documents/{id}`
  - `PATCH /documents/{id}` body `{title?, meta?}` → 更新 store + `vector_service.update_document_metadata`（合并 `title`+整份 meta + `doc_type`）；若条目不存在或 deleted → 404
  - `DELETE /documents/{id}` → soft_delete + `vector_service.delete_document`
  - `POST /search` body `{doc_type, query, n_results?}` → `vector_service.search(..., where={"doc_type": doc_type})`
- HTTP 路径前缀：`/api/admin/kb/...`（与上表对应：`/api/admin/kb/documents`，`/api/admin/kb/search`）
- 响应形状：与现有 admin API 一致，成功直接 JSON 对象/数组；错误 `{ "error": "..." }` + 状态码

Handler 签名风格对齐 `RbacHttpApi`：方法返回 `Tuple[int, Dict|List]`。

```python
# server/http_kb_api.py 方法示例
def create_from_file(self, authorization, body: dict) -> StatusPayload: ...
def list_documents(self, authorization, doc_type: str, limit=50, offset=0) -> StatusPayload: ...
def get_document(self, authorization, doc_id: str) -> StatusPayload: ...
def patch_document(self, authorization, doc_id: str, body: dict) -> StatusPayload: ...
def delete_document(self, authorization, doc_id: str) -> StatusPayload: ...
def search(self, authorization, body: dict) -> StatusPayload: ...
```

`mcp_server.py` 改动要点：
1. 在 RBAC 初始化附近：`self.kb_store = KbStore("./kb.db"); self.kb_store.ensure_schema()`
2. `self.kb_api = KbHttpApi(..., file_service=self.file_service, vector_service=self.vector_service)`（注意 vector_service 可能异步初始化：handler 内若 `not self.vector_service` 返回 503）
3. 在 `do_GET`/`do_POST`/`do_PATCH`/`do_DELETE`（或现有统一 admin 分发）增加 `/api/admin/kb` 分支，解析 path 调用 `kb_api`

若项目无 `do_PATCH`，用 `POST /api/admin/kb/documents/{id}/update` 代替 PATCH——**优先实现 PATCH**；若 `BaseHTTPRequestHandler` 需加 `do_PATCH` 转发到同一分发函数则加上。

- [ ] **Step 1: Write the failing API test**

```python
# tests/test_http_kb_api.py
import os, tempfile, unittest
from auth_service import AuthService
from rbac_service import RbacService
from rbac_store import RbacStore
from kb_store import KbStore
from http_kb_api import KbHttpApi
from vector_service import VectorService


class FakeFiles:
    def get_file_text(self, file_id):
        return "法规正文测试内容 " * 10


class TestHttpKbApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rbac_path = os.path.join(self.tmp.name, "rbac.db")
        self.rbac_store = RbacStore(rbac_path)
        self.rbac_store.ensure_schema()
        self.rbac_store.seed_defaults()
        self.auth = AuthService(self.rbac_store)
        self.auth.ensure_seed_director("ChangeMe123!")
        login = self.auth.login("director", "ChangeMe123!")
        self.token = login["token"]
        self.authz = f"Bearer {self.token}"
        self.kb = KbStore(os.path.join(self.tmp.name, "kb.db"))
        self.kb.ensure_schema()
        self.vs = VectorService(persist_directory=os.path.join(self.tmp.name, "chroma"))
        self.vs.model = None
        self.api = KbHttpApi(
            self.kb, self.auth, RbacService(self.rbac_store),
            file_service=FakeFiles(), vector_service=self.vs,
            complete_fn=lambda s, u: '{"law_name":"测试法","effect_level":"法律","issuing_authority":"","document_number":"","effective_date":""}',
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_ingest_list_search_patch_delete(self):
        st, body = self.api.create_from_file(self.authz, {"doc_type": "law", "file_id": "f1"})
        self.assertEqual(st, 200, body)
        doc_id = body["id"]
        st, listed = self.api.list_documents(self.authz, "law")
        self.assertEqual(st, 200)
        self.assertEqual(len(listed["items"]), 1)
        st, search = self.api.search(self.authz, {"doc_type": "law", "query": "测试法", "n_results": 3})
        self.assertEqual(st, 200)
        self.assertTrue(len(search["results"]) >= 1)
        st, patched = self.api.patch_document(self.authz, doc_id, {
            "meta": {**body["meta"], "effect_level": "行政法规"}
        })
        self.assertEqual(st, 200)
        self.assertEqual(patched["meta"]["effect_level"], "行政法规")
        st, _ = self.api.delete_document(self.authz, doc_id)
        self.assertEqual(st, 200)
        st, listed2 = self.api.list_documents(self.authz, "law")
        self.assertEqual(listed2["items"], [])
```

`list_documents` 返回 `{"items": [...], "total": N}`；`search` 返回 `{"results": [...]}`。

- [ ] **Step 2: Run — expect fail**

Run: `PYTHONPATH=server python3 -m pytest tests/test_http_kb_api.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement `http_kb_api.py` + wire `mcp_server.py`**

鉴权：`require_perm(authorization, "cap.vectorize")`（可复制 `RbacHttpApi.require_perm` 逻辑，或组合注入同一 `rbac`）。

- [ ] **Step 4: Run — expect pass**

Run: `PYTHONPATH=server python3 -m pytest tests/test_http_kb_api.py tests/test_kb_store.py tests/test_kb_meta_extract.py tests/test_kb_ingest.py tests/test_vector_service_kb.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/http_kb_api.py server/mcp_server.py tests/test_http_kb_api.py
git commit -m "feat(kb): expose /api/admin/kb HTTP APIs"
```

---

### Task 6: 导航与总览入口

**Files:**
- Modify: `admin_nav.js`
- Modify: `admin.html`（工具卡片：拆成法规库 / 案例库，或把原「向量化文档」改为链到法规库并增加案例库卡；原调试页可不再占主统计卡）
- Modify: `vectorize.html`（`<h1>` / `<title>` / 说明改为「向量调试」）

**Interfaces:**
- Nav `tools.items` 变为：
  - skills / mcp
  - `{ id: "kb-laws", href: "admin_kb_laws.html", label: "知识库 · 法规库", perm: "cap.vectorize" }`
  - `{ id: "kb-cases", href: "admin_kb_cases.html", label: "知识库 · 裁判案例库", perm: "cap.vectorize" }`
  - `{ id: "vectorize", href: "vectorize.html", label: "向量调试", perm: "cap.vectorize" }`

- [ ] **Step 1: 改 `admin_nav.js` 如上**

- [ ] **Step 2: 改 `admin.html` 工具区**

将原单卡替换为两卡（法规库 / 裁判案例库），`statDocs` 可暂显示总向量文档数并 hint「含法规与案例」；链接分别到两页。若 stats API 暂未拆分，两边可显示同一 `documents` 计数（P1 再按 `doc_type` 拆）。

- [ ] **Step 3: 改 `vectorize.html` 文案为调试用途**

- [ ] **Step 4: 手动打开 admin 确认二级菜单出现（无需自动化）**

- [ ] **Step 5: Commit**

```bash
git add admin_nav.js admin.html vectorize.html
git commit -m "feat(kb): add knowledge-base nav entries and demote vectorize debug"
```

---

### Task 7: 法规库页面 `admin_kb_laws.html`

**Files:**
- Create: `admin_kb_laws.html`
- Reuse: `auth.js`, `admin_nav.js`, `admin_ui.js`, `admin.css`

**Interfaces:**
- 调用（需 Bearer，与 `admin_clients.html` 相同取 `LegalMindAuth` / `AdminUI` 模式）：
  - `POST {MCP}/api/files/upload` 拿 `file_id`（沿用现有上传）
  - `POST {MCP}/api/admin/kb/documents` `{doc_type:"law", file_id}`
  - `GET .../api/admin/kb/documents?doc_type=law`
  - `PATCH .../api/admin/kb/documents/{id}`
  - `DELETE ...`
  - `POST .../api/admin/kb/search`

UI 要求：
- `data-admin-page="kb-laws"`
- 工具栏：文件多选上传 → **串行** ingest；状态文案「上传中 / 识别中 / 向量化中」可用按钮 disabled + `#uploadStatus`
- 表格列：法律名称、效力级别、发布机关、文号、施行日期、状态、操作
- 空 meta 显示 `—`
- 编辑：`AdminUI.openDrawer` 表单改 meta 五字段 + title
- 试检索：查询框 + 结果列表（snippet）
- 删除前 `confirm`

上传实现参考 `admin_cases.html` 的 FormData 上传；API base URL 与现有 admin 页一致（读 MCP 端口 / `LegalMindAuth.apiBase` 若有）。

- [ ] **Step 1: 实现完整单页 HTML+JS**（可先列表+mock 再接真 API；提交时须接真 API）

- [ ] **Step 2: 手工验收**
  1. 登录 director
  2. 上传一份 txt/docx 法规
  3. 列表出现且状态 ready 或 meta_failed
  4. 试检索能命中
  5. 编辑效力级别后保存成功

- [ ] **Step 3: Commit**

```bash
git add admin_kb_laws.html
git commit -m "feat(kb): add laws knowledge-base admin page"
```

---

### Task 8: 裁判案例库页面 `admin_kb_cases.html`

**Files:**
- Create: `admin_kb_cases.html`

**Interfaces:** 同 Task 7，但 `doc_type: "case"`；列：案号、案由、法院、审理程序、案例类型、审判人员、状态；编辑表单含 `case_kind` select（`ordinary`/`guiding`）；试检索 `doc_type=case`。

- [ ] **Step 1: 实现页面**（可与法规页共享一小段内联 helper，但 YAGNI：允许两页复制粘贴后再抽 `admin_kb_common.js`——**首版允许复制**，不要为 DRY 强抽除非明显重复超 80 行）

- [ ] **Step 2: 手工验收**（上传裁判文书样例、编辑、检索隔离：法规检索不得出现该案例）

- [ ] **Step 3: Commit**

```bash
git add admin_kb_cases.html
git commit -m "feat(kb): add case judgments knowledge-base admin page"
```

---

### Task 9: 端到端回归与规格对照

**Files:** 按需修缺陷；更新规格状态行：

- Modify: `docs/superpowers/specs/2026-09-04-knowledge-base-vectorize-design.md` 状态 → `已定稿（P0 已实现）`（仅当代码完成时）

- [ ] **Step 1: Run full related tests**

```bash
cd /Users/kanglinlin/Documents/cursor/AI法官
PYTHONPATH=server python3 -m pytest \
  tests/test_kb_store.py \
  tests/test_kb_meta_extract.py \
  tests/test_kb_ingest.py \
  tests/test_vector_service_kb.py \
  tests/test_http_kb_api.py \
  -v
```

Expected: all PASS

- [ ] **Step 2: 对照验收标准（规格 §10）勾选**

| # | 标准 | 验证方式 |
|---|------|----------|
| 1 | 导航双子页 + `cap.vectorize` | 手工 |
| 2 | 法规上传→列表→law 检索命中 | 手工 + API 测 |
| 3 | 案例上传→元数据可空→case 检索 | 手工 |
| 4 | 编辑元数据后过滤/展示一致 | API patch 测 + 手工 |
| 5 | 跨类型不污染 | `test_search_filters_by_doc_type` |
| 6 | 删除后不可检索 | API delete 测 |

- [ ] **Step 3: Commit 文档状态（若有改动）**

```bash
git add docs/superpowers/specs/2026-09-04-knowledge-base-vectorize-design.md
git commit -m "docs(kb): mark knowledge-base spec P0 implemented"
```

---

## Self-review（写计划后）

1. **Spec coverage：** P0 导航、kb_documents、管道、两页、编辑/删除、doc_type 检索均有 Task；P1 批量队列 UI 深化/概览拆分统计/旧数据迁移、P2 对话检索 **明确不做**。开放问题已在 Global Constraints 锁定。
2. **Placeholder scan：** 无 TBD；PATCH 不可用时的 fallback 已写明优先方案。
3. **Type consistency：** `doc_type`/`meta`/`status`/`document_id` 在 store→ingest→chroma→HTTP→UI 一致；`case_kind` 仅 `ordinary|guiding`；`judges` 存字符串。

---

## 执行交接

Plan complete and saved to `docs/superpowers/plans/2026-09-04-knowledge-base-vectorize.md`. Two execution options:

**1. Subagent-Driven (recommended)** — 每个 Task 派一个新 subagent，任务间评审，迭代快  

**2. Inline Execution** — 本会话用 executing-plans 按任务推进，设检查点  

Which approach?
