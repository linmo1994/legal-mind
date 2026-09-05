# 知识库混合检索（向量 + FTS5 + RRF）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `VectorService.search` 升级为「Chroma 向量 + SQLite FTS5 词法 + RRF 融合」，使对话检索、管理端试检索与其它调用方统一受益。

**Architecture:** 新建 `KbFtsIndex`（与 `./kb.db` 同库）按 Chroma chunk_id 同步正文；`add_document`/`delete_document` 写删索引；`search` 双路召回后 RRF 排序。FTS 不可用时降级纯向量。首期 FTS5 采用**自带存储**（`chunk_id/document_id/doc_type UNINDEXED`），对应规格 §3.1 允许的可靠变体，避免 content= 外挂 triggers 复杂度。

**Tech Stack:** Python 3 `sqlite3` FTS5、现有 Chroma `VectorService`、unittest（`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=server`）。

**Spec:** `docs/superpowers/specs/2026-09-05-hybrid-retrieval-design.md`

## Global Constraints

- 不引入 jieba / rank_bm25 / cross-encoder
- 保持 `search(query, n_results=5, boost_keywords=True, where=None)` 签名兼容；新增 `hybrid=True` 等可选参数
- 测试用临时 `kb.db`；不写开发机真实 chroma 做破坏性操作
- 提交仅在用户明确要求时执行（计划中的 Commit 步骤可跳过或改为「暂存说明」）

## File map

| File | Responsibility |
|------|----------------|
| `server/kb_fts.py` | FTS schema、upsert/delete/search、query 规范化、RRF 工具函数 |
| `server/vector_service.py` | 挂载 FTS；写入/删除同步；`search` 混合 |
| `server/mcp_server.py` | 初始化后把 `kb.db` 路径交给 `VectorService`；可选启动回填 |
| `tests/test_kb_fts.py` | FTS CRUD、规范化、RRF、过滤 |
| `tests/test_hybrid_search.py` | 混合排序与降级（可 mock 向量路） |

---

### Task 1: `KbFtsIndex` — schema、upsert、delete、词法检索

**Files:**
- Create: `server/kb_fts.py`
- Test: `tests/test_kb_fts.py`

**Interfaces:**
- `normalize_fts_query(query: str) -> str` — 保留「第X条」、去掉危险字符，生成 FTS MATCH 表达式（token 用空格/`OR` 安全拼接）
- `rrf_fuse(rank_lists: list[list[str]], *, rrf_k: int = 60) -> list[tuple[str, float]]` — 输入各路按名次排列的 id 列表，返回 `(id, score)` 降序
- `KbFtsIndex(db_path: str)`
  - `ensure_schema() -> None`
  - `upsert_chunks(chunks: list[dict]) -> None` — 每项含 `chunk_id`, `document_id`, `doc_type`, `body`
  - `delete_by_document_id(document_id: str) -> int`
  - `search(query: str, *, doc_type: str | None = None, document_id: str | None = None, limit: int = 10) -> list[dict]` — 返回 `{chunk_id, document_id, doc_type, body, fts_rank}`（1-based rank）
  - `count() -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kb_fts.py
import os
import tempfile
import unittest
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from kb_fts import KbFtsIndex, normalize_fts_query, rrf_fuse  # noqa: E402


class TestKbFts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.idx = KbFtsIndex(os.path.join(self.tmp.name, "kb.db"))
        self.idx.ensure_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_and_search_article(self):
        self.idx.upsert_chunks([
            {
                "chunk_id": "d1_chunk_0",
                "document_id": "d1",
                "doc_type": "law",
                "body": "劳动合同法第六十四条 集体合同……",
            },
            {
                "chunk_id": "d2_chunk_0",
                "document_id": "d2",
                "doc_type": "case",
                "body": "某民间借贷纠纷判决要旨……",
            },
        ])
        hits = self.idx.search("第六十四条", doc_type="law", limit=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["chunk_id"], "d1_chunk_0")
        self.assertEqual(hits[0]["fts_rank"], 1)

    def test_delete_by_document(self):
        self.idx.upsert_chunks([{
            "chunk_id": "d1_chunk_0",
            "document_id": "d1",
            "doc_type": "law",
            "body": "测试条文",
        }])
        self.assertEqual(self.idx.delete_by_document_id("d1"), 1)
        self.assertEqual(self.idx.search("测试条文"), [])

    def test_rrf_fuse(self):
        fused = rrf_fuse([["a", "b"], ["b", "c"]], rrf_k=60)
        ids = [x[0] for x in fused]
        self.assertEqual(ids[0], "b")  # 两路皆命中

    def test_normalize_keeps_article(self):
        q = normalize_fts_query("检索劳动合同法第六十四条")
        self.assertIn("第六十四条", q)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=server python3 -m unittest tests.test_kb_fts -v`  
Expected: FAIL（`ModuleNotFoundError: kb_fts`）

- [ ] **Step 3: Write minimal implementation**

```python
# server/kb_fts.py
"""SQLite FTS5 index for knowledge-base chunks (hybrid retrieval)."""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple


def normalize_fts_query(query: str) -> str:
    text = (query or "").strip()
    if not text:
        return ""
    articles = re.findall(r"第[一二三四五六七八九十百千零〇\d]+条", text)
    # Strip quotes/operators that break MATCH
    cleaned = re.sub(r'["\'*():^]', " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    tokens = []
    for a in articles:
        if a not in tokens:
            tokens.append(a)
    for part in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9\-]+", cleaned):
        if part not in tokens and part not in "".join(articles):
            tokens.append(part)
    if not tokens:
        return ""
    # Phrase-ish: quote multi-char tokens for FTS5
    return " OR ".join('"' + t.replace('"', "") + '"' for t in tokens[:12])


def rrf_fuse(
    rank_lists: Sequence[Sequence[str]], *, rrf_k: int = 60
) -> List[Tuple[str, float]]:
    scores: Dict[str, float] = {}
    for ranking in rank_lists:
        for rank, item_id in enumerate(ranking, start=1):
            if not item_id:
                continue
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))


class KbFtsIndex:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks_fts USING fts5(
                  chunk_id UNINDEXED,
                  document_id UNINDEXED,
                  doc_type UNINDEXED,
                  body,
                  tokenize = 'unicode61'
                )
                """
            )

    def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        if not chunks:
            return
        with self._conn() as conn:
            for ch in chunks:
                cid = ch["chunk_id"]
                conn.execute(
                    "DELETE FROM kb_chunks_fts WHERE chunk_id = ?", (cid,)
                )
                conn.execute(
                    """
                    INSERT INTO kb_chunks_fts(chunk_id, document_id, doc_type, body)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        cid,
                        ch["document_id"],
                        ch["doc_type"],
                        ch.get("body") or "",
                    ),
                )

    def delete_by_document_id(self, document_id: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM kb_chunks_fts WHERE document_id = ?",
                (document_id,),
            )
            return int(cur.rowcount or 0)

    def count(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM kb_chunks_fts"
            ).fetchone()
            return int(row["c"] if row else 0)

    def search(
        self,
        query: str,
        *,
        doc_type: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        match = normalize_fts_query(query)
        if not match:
            return []
        limit = max(1, min(int(limit), 50))
        sql = (
            "SELECT chunk_id, document_id, doc_type, body, "
            "bm25(kb_chunks_fts) AS rank_score "
            "FROM kb_chunks_fts WHERE kb_chunks_fts MATCH ?"
        )
        params: List[Any] = [match]
        if doc_type:
            sql += " AND doc_type = ?"
            params.append(doc_type)
        if document_id:
            sql += " AND document_id = ?"
            params.append(document_id)
        sql += " ORDER BY rank_score LIMIT ?"
        params.append(limit)
        try:
            with self._conn() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            print(f"[KbFtsIndex] search failed: {exc}")
            return []
        out = []
        for i, row in enumerate(rows, start=1):
            out.append(
                {
                    "chunk_id": row["chunk_id"],
                    "document_id": row["document_id"],
                    "doc_type": row["doc_type"],
                    "body": row["body"],
                    "fts_rank": i,
                }
            )
        return out
```

Note: FTS5 `bm25()` 分值越低越好；`ORDER BY rank_score` 正确。若环境无 `bm25`，改为 `ORDER BY rank`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=server python3 -m unittest tests.test_kb_fts -v`  
Expected: OK

- [ ] **Step 5: Commit（仅当用户要求）**

```bash
git add server/kb_fts.py tests/test_kb_fts.py
git commit -m "feat(kb): add SQLite FTS5 chunk index helpers"
```

---

### Task 2: `VectorService` 挂载 FTS，写入/删除同步

**Files:**
- Modify: `server/vector_service.py`（`__init__`, `add_document`, `delete_document`）
- Modify: `server/mcp_server.py`（向量服务就绪后 `attach_fts`）
- Test: `tests/test_hybrid_search.py`（本 Task 先写同步相关用例）

- [ ] **Step 1: Write failing tests for sync**

```python
# tests/test_hybrid_search.py
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from kb_fts import KbFtsIndex  # noqa: E402


class TestVectorFtsSync(unittest.TestCase):
    def test_attach_and_upsert_on_add(self):
        # 使用轻量 stub：不加载真实 embedding
        from vector_service import VectorService

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        chroma_dir = os.path.join(tmp.name, "chroma")
        fts_path = os.path.join(tmp.name, "kb.db")

        with patch.object(VectorService, "_generate_embedding", return_value=[0.1] * 8):
            # 若 __init__ 仍加载模型，可再 patch SentenceTransformer / 设 model=None 路径
            vs = VectorService.__new__(VectorService)
            vs.persist_directory = chroma_dir
            vs.collection_name = "legal_documents"
            vs.model = None
            vs.fts = None
            vs.client = MagicMock()
            coll = MagicMock()
            vs.collection = coll
            vs.attach_fts(fts_path)
            vs.fts.ensure_schema()

            # 伪造 _split_text 单块
            vs._split_text = lambda text, **kw: [text]
            vs._generate_embedding = lambda text: [0.1] * 8

            result = VectorService.add_document(
                vs, "doc1", "劳动合同法第六十四条内容", {"doc_type": "law", "title": "劳动合同法"}
            )
            self.assertTrue(result.get("success"))
            hits = vs.fts.search("第六十四条", doc_type="law")
            self.assertTrue(hits)
            self.assertEqual(hits[0]["chunk_id"], "doc1_chunk_0")

            VectorService.delete_document(vs, "doc1")
            self.assertEqual(vs.fts.search("第六十四条"), [])
```

若 `VectorService.__init__` 难以 bypass，改为只测「公开方法 `attach_fts` + 手工调用内部 `_sync_fts_chunks`」，并在实现中抽出该 helper。

- [ ] **Step 2: Run to verify fail**

Run: `PYTHONPATH=server python3 -m unittest tests.TestVectorFtsSync -v`  
（或 `tests.test_hybrid_search.TestVectorFtsSync`）  
Expected: FAIL（无 `attach_fts`）

- [ ] **Step 3: Implement attach + sync**

在 `VectorService.__init__` 末尾：`self.fts = None`。

新增：

```python
def attach_fts(self, db_path: str) -> None:
    from kb_fts import KbFtsIndex
    self.fts = KbFtsIndex(db_path)
    self.fts.ensure_schema()

def _sync_fts_for_chunks(self, document_id: str, chunks: List[str], metadata: Optional[Dict]) -> None:
    if not self.fts:
        return
    doc_type = (metadata or {}).get("doc_type") or ""
    rows = []
    for i, body in enumerate(chunks):
        rows.append({
            "chunk_id": f"{document_id}_chunk_{i}",
            "document_id": document_id,
            "doc_type": doc_type,
            "body": body,
        })
    try:
        self.fts.delete_by_document_id(document_id)
        self.fts.upsert_chunks(rows)
    except Exception as exc:
        print(f"[VectorService] FTS sync failed: {exc}")
```

在 `add_document` 于 `collection.add` 成功后调用 `_sync_fts_for_chunks(document_id, chunks, metadata)`。  
在 `delete_document` 删除 Chroma 成功后：`if self.fts: self.fts.delete_by_document_id(document_id)`。

在 `mcp_server.py` 向量服务赋值成功处：

```python
if self.vector_service and self.kb_store:
    try:
        self.vector_service.attach_fts(self.kb_store.db_path)
    except Exception as e:
        print(f"[MCP Server] FTS attach failed: {e}")
```

（若向量异步初始化，在 `_ensure_vector_service` / 赋值 `self.vector_service = ...` 的两处都调用 attach。）

- [ ] **Step 4: Run sync tests — PASS**

- [ ] **Step 5: Commit（仅当用户要求）**

---

### Task 3: `search` 混合 RRF + 降级

**Files:**
- Modify: `server/vector_service.py` — `search`
- Test: `tests/test_hybrid_search.py` — 增加混合用例

- [ ] **Step 1: Write failing hybrid test**

```python
class TestHybridSearch(unittest.TestCase):
    def test_rrf_prefers_dual_hit(self):
        from vector_service import VectorService
        from kb_fts import rrf_fuse

        # 纯测 fuse 已在 Task1；此处测 search 组装
        vs = VectorService.__new__(VectorService)
        vs.fts = KbFtsIndex(tempfile.mktemp(suffix=".db"))  # 改用 TemporaryDirectory
        # ... ensure_schema, upsert 两 chunk
        # mock collection.query 只返回 chunk B
        # FTS 对 query 返回 A 然后 B
        # search 结果 top1 应为 B（双命中）或按构造断言 rrf_score 字段存在

    def test_fts_only_chunk_still_returned(self):
        # 向量路空、FTS 有命中 → 结果非空，document 来自 FTS body

    def test_hybrid_false_skips_fts(self):
        # hybrid=False 时不读 fts（可用 mock 断言 search 未被调用）
```

具体夹具：用 `TemporaryDirectory`；`vs.collection.query` MagicMock 返回固定 ids/documents/metadatas/distances；`vs._generate_embedding = lambda q: [0.0]*8`；`vs.model = None` 若 embedding 路径依赖 model。

- [ ] **Step 2: Run — FAIL（无 hybrid 参数/字段）**

- [ ] **Step 3: Implement hybrid search**

在 `search` 签名增加：

```python
def search(
    self,
    query: str,
    n_results: int = 5,
    boost_keywords: bool = True,
    where: Optional[Dict] = None,
    hybrid: bool = True,
    k_vec: Optional[int] = None,
    k_lex: Optional[int] = None,
    rrf_k: int = 60,
) -> List[Dict]:
```

逻辑纲要：

1. 计算 `k_vec = k_vec or max(min(n_results * 2, 50), 10)`（与现 boost 扩召回一致）；`k_lex` 同。
2. **向量路**：现有 `collection.query` + 可选 keyword boost → 得到 `vec_hits: list[dict]`（含 id/document/metadata/distance…），记下 `vector_rank`。
3. **词法路**（`hybrid and self.fts`）：
   - 从 `where` 取 `doc_type` / `document_id`（仅简单 equality dict；其它复杂 where 跳过 FTS）
   - `fts_hits = self.fts.search(query, doc_type=..., document_id=..., limit=k_lex)`
4. 若无 FTS 或未 hybrid：走现有返回（截断 `n_results`）。
5. `fused = rrf_fuse([[h['id'] for h in vec_hits], [h['chunk_id'] for h in fts_hits]], rrf_k=rrf_k)`
6. 建 lookup：向量 id → hit；FTS chunk_id → hit。
7. 按 fused 取前 `n_results`，合并字段：
   - `rrf_score`, `vector_rank`, `fts_rank`
   - 仅 FTS：`document=body`, `metadata={"document_id", "doc_type"}`, `distance=None`
8. 任一路异常：打日志，该路空列表。

- [ ] **Step 4: Run `tests.test_hybrid_search tests.test_kb_fts` — PASS**

- [ ] **Step 5: Commit（仅当用户要求）**

---

### Task 4: 启动回填 + 回归

**Files:**
- Modify: `server/vector_service.py` — `rebuild_fts_from_chroma(self) -> dict`
- Modify: `server/mcp_server.py` — attach 后若 `fts.count()==0` 且 chroma 有数据则调用重建
- Test: 单元测 rebuild（mock collection.get 分页或一次性 get）

- [ ] **Step 1: Test rebuild**

```python
def test_rebuild_fts_from_chroma(self):
    # mock collection.get 返回 ids/documents/metadatas
    # attach 空 FTS → rebuild → search 命中
```

- [ ] **Step 2: Implement**

```python
def rebuild_fts_from_chroma(self) -> Dict:
    if not self.fts:
        return {"ok": False, "error": "fts not attached"}
    # collection.get(include=["documents","metadatas"])；若量大可后续分页
    # 清空：DELETE FROM kb_chunks_fts（FTS5 用 `DELETE FROM kb_chunks_fts`）
    # upsert 全部
    return {"ok": True, "chunks": n}
```

MCP：`attach_fts` 后：

```python
try:
    if self.vector_service.fts and self.vector_service.fts.count() == 0:
        info = self.vector_service.collection.count()
        if info and int(info) > 0:
            print("[MCP Server] FTS empty, rebuilding from Chroma...")
            print(self.vector_service.rebuild_fts_from_chroma())
except Exception as e:
    print(f"[MCP Server] FTS rebuild skipped: {e}")
```

- [ ] **Step 3: Regression**

Run:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=server python3 -m unittest \
  tests.test_kb_fts tests.test_hybrid_search tests.test_kb_retrieve tests.test_orchestrate -v
```

Expected: OK

- [ ] **Step 4: 重启 MCP**（手工）使 attach/rebuild 生效；管理端试检索一条带「第X条」的 query 冒烟。

- [ ] **Step 5: Commit（仅当用户要求）**

---

## Spec coverage checklist

| Spec 项 | Task |
|---------|------|
| FTS5 chunk 索引 | Task 1 |
| add/delete 同步 | Task 2 |
| 统一 `search` + RRF | Task 3 |
| where/`doc_type` | Task 1–3 |
| 降级纯向量 | Task 3 |
| 启动回填 | Task 4 |
| 无 jieba / 无 rerank | 全任务遵守 |
| 调用方无需改 API | Task 3 默认 hybrid=True |

## Self-review notes

- 选用 FTS **自带存储**变体，与规格 §3.1 明确允许的退路一致，降低 triggers 风险。
- `bm25()` 依赖 SQLite 编译选项；若 CI 失败，改为 `ORDER BY rank`。
- 不强制改 `http_kb_api` / `make_kb_retrieve_fn` 签名。
