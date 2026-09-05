# 知识库混合检索（向量 + SQLite FTS5 + RRF）设计

**日期：** 2026-09-05  
**状态：** 已定稿  
**范围：** 统一升级 `VectorService.search` 为混合检索；对话编排、管理端试检索、模板解析等凡经该入口的调用一并受益。

---

## 1. 背景与目标

### 现状

- 主路径为 **Chroma 向量检索**（embedding + L2/距离排序），按 `where`（如 `doc_type`）过滤。
- 另有 **关键词轻量 boost**：从 query 抽取数字、「第X条」、法名等，在向量候选内调低 distance 再排序。候选仍只来自向量召回。
- 对话侧已按意图门闸限定 `law` / `case` 范围，并走 `make_kb_retrieve_fn` → `vector_service.search`。
- **没有** 独立的全文/倒排召回，也没有 BM25、RRF 或 cross-encoder rerank。

### 问题

纯向量对法条号、案号、专有名词等「必须字面命中」的场景易漏召；现有 boost 无法补救「未进入向量候选集」的结果。

### 目标

1. 采用 **方案 B**：向量召回 + **SQLite FTS5** 词法召回，再用 **RRF** 融合排序。
2. 索引粒度与 Chroma **chunk 一一对应**（方案 1），保证返回形态与现网一致。
3. **统一入口**：改造 `VectorService.search`，使管理端试检索、对话检索、模板相关检索等全部走混合策略。
4. FTS 失败或未回填时 **降级为纯向量**，不阻断业务。

### 非目标（本期不做）

- Cross-encoder / LLM rerank。
- 更换 embedding 模型或第二套向量库。
- 引入 jieba 等分词依赖（首期用 FTS5 `unicode61` + 查询侧保守切词/保留专名）。
- 文档级（整篇）FTS 后再向量精排的方案 2。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 混合策略 | 向量 + FTS5，RRF 融合 |
| FTS 实现 | SQLite FTS5（与知识库 SQLite 同库或同数据目录可配置） |
| 索引粒度 | Chunk 级，id 与 Chroma `document_id_chunk_i` 对齐 |
| 覆盖范围 | 所有 `VectorService.search` 调用方 |
| 中文分词 | 首期无 jieba；`unicode61` + query 侧保留「第X条」/案号等 |
| 降级 | FTS 不可用 → 仅向量（可保留现有 keyword boost） |
| Rerank | 不做 |

---

## 3. 数据模型

### 3.1 Content 表 + FTS5

在知识库 SQLite（与 `KbStore` 同一 `kb.db`，便于备份与权限边界一致）增加：

```sql
CREATE TABLE IF NOT EXISTS kb_chunks (
  chunk_id   TEXT PRIMARY KEY,   -- 与 Chroma id 一致，如 {document_id}_chunk_0
  document_id TEXT NOT NULL,
  doc_type    TEXT NOT NULL,     -- law | case | template
  chunk_index INTEGER NOT NULL,
  body        TEXT NOT NULL,
  updated_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc
  ON kb_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_type
  ON kb_chunks(doc_type);

CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks_fts USING fts5(
  body,
  content='kb_chunks',
  content_rowid='rowid',
  tokenize='unicode61'
);
```

说明：

- `kb_chunks` 为权威正文副本；FTS 用 `content=` 外挂，避免双份正文漂移时难排查（写入时按 SQLite FTS5 外挂约定维护）。
- 若外挂 triggers 实现成本过高，可退化为 **FTS5 自带存储**（`kb_chunks_fts(chunk_id UNINDEXED, document_id UNINDEXED, doc_type UNINDEXED, body)`），仍以 `chunk_id` 关联 Chroma；实现计划阶段二选一，**默认优先外挂 content 表 + triggers**，测不通再退自带存储。

### 3.2 生命周期同步

| 事件 | 行为 |
|------|------|
| `add_document` 写入 Chroma 成功 | 按 chunk upsert `kb_chunks` + FTS |
| `delete_document(document_id)` | 删除该文档全部 chunk 行及 FTS |
| 元数据仅改 title/meta、不改正文 | 可不碰 FTS；若重切向量则先删后写 |
| 进程启动或管理「重建索引」 | 从 Chroma `get`/遍历或原文重切回填；幂等 |

---

## 4. 检索算法

### 4.1 入口签名

保持：

```text
search(query, n_results=5, boost_keywords=True, where=None) -> List[Dict]
```

新增可选参数（向后兼容，默认开启混合）：

- `hybrid: bool = True`
- `k_vec: int`（默认 `max(n_results*2, 10)`，上限 50）
- `k_lex: int`（同上）
- `rrf_k: int = 60`

### 4.2 流程

```
query + where
    ├─ 向量路：现有 embedding → collection.query(n=k_vec, where)
    └─ 词法路：规范化 query → FTS5 MATCH（附加 doc_type 等过滤）→ top k_lex
         ↓
    RRF：对 chunk_id，score += 1/(rrf_k + rank_i)（各路独立排名，1-based）
         ↓
    按 RRF 降序取 n_results
         ↓
    组装返回：优先用向量路已有 document/metadata；仅 FTS 命中的从 kb_chunks 补全文，metadata 尽量从 Chroma get 或 kb 行补齐
```

### 4.3 返回字段（兼容扩展）

现有：`id`, `document`, `metadata`, `distance`, …

增量（便于试检索调试，UI 可不展示）：

- `rrf_score`
- `vector_rank`（未进向量路则为 null）
- `fts_rank`（未进 FTS 路则为 null）
- 可保留 `keyword_score` / `adjusted_distance`（若仍跑 boost）；混合稳定后可将 boost 降为可选默认关。

### 4.4 Query 规范化（词法路）

- 去掉无意义标点；保留汉字、字母、数字。
- **整段保留**：`第[一二三四五六七八九十百千零\d]+条`、连续案号样式、书名号内短标题。
- 其余按空白/`unicode61` 可匹配 token 拼接为 FTS 查询；禁止把用户输入直接拼进 SQL（一律参数化或安全 escape）。
- FTS 无命中或语法失败：该路返回空列表，不抛给上层。

### 4.5 where 对齐

- 向量路：继续传 Chroma `where`。
- FTS 路：至少支持 `doc_type`；若 `where` 含 `document_id`，FTS 同等过滤。其它复杂 where 首期可不支持词法路（仅向量），并在日志中注明。

---

## 5. 调用方影响

| 调用方 | 影响 |
|--------|------|
| `http_api_extra.make_kb_retrieve_fn` | 无改或仅透传；自动混合 |
| `http_kb_api` 试检索 | 结果可多 `rrf_score`；行为更偏字面+语义 |
| `kb_template_resolve` 等 | 同入口，受益 |
| 单测 | 增加 FTS 入库/混合排序/降级用例；mock 向量时需可关 hybrid 或 stub FTS |

---

## 6. 回填与运维

1. **增量**：新入库文档自动写 FTS。  
2. **全量重建**：内部方法 `rebuild_fts_from_chroma()`（或管理 API，权限同 vectorize）；可阻塞或后台，首期同步即可（库不大）。  
3. **一致性检查**（可选日志）：Chroma chunk 数 vs `kb_chunks` 行数按 `document_id` 对比。  
4. **迁移**：升级后首次启动若 FTS 空且 Chroma 非空，自动触发一次重建（或打印明确警告，由管理端按钮触发——**默认自动重建一次**，避免静默纯向量）。

---

## 7. 测试要点

- 法条号查询（如「劳动合同法第64条」）在向量较弱时仍能经 FTS 进入 top‑N。  
- `doc_type` 过滤：law 查询不混入 case chunk。  
- 删除文档后 FTS 与向量均无残留。  
- FTS 表缺失/只读失败时 search 仍返回向量结果。  
- RRF：两路皆命中的 chunk 排名高于单路边缘命中（构造小夹具验证）。

---

## 8. 实现落点（供后续 plan）

- `server/kb_store.py` 或新建 `server/kb_fts.py`：schema、upsert、delete、fts_search。  
- `server/vector_service.py`：`add_document` / `delete_document` / `search` 接入。  
- `server/kb_ingest.py`：通常已走 `add_document`，无需重复写；确认无旁路写 Chroma。  
- 测试：`tests/test_hybrid_retrieval.py`（及既有 retrieve 单测回归）。

---

## 9. 验收标准

1. `VectorService.search` 在默认配置下对同一 query 可同时利用语义与字面信号。  
2. 管理端试检索与对话法规/类案检索行为一致（同源）。  
3. 无 FTS 数据时系统仍可用（纯向量）。  
4. 相关单元测试通过；MCP 重启后手工抽检一条法条号查询。
