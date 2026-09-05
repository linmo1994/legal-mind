# 法规精检索与引用预览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 纠偏「法名+条号」检索误召回，并在多轮对话、首页（若可接到引用数据）、管理端试检索中提供可点法规链接，页内预览并在提取文本中高亮定位条文。

**Architecture:** 在 `kb_fts` 增加查询解析与 AND 构造；`VectorService.search` 融合后按标题加权；retrieve/试检索输出 `citations`；前端复用并扩展 `KbFilePreview.open(..., { article })`。

**Tech Stack:** Python FTS5 / Chroma（现有）、unittest、静态 JS（`admin_kb_files.js` / `mcp_client.js` / 管理端 KB 页）。

**Spec:** `docs/superpowers/specs/2026-09-05-law-citation-preview-design.md`

## Global Constraints

- 不引入 PDF.js / jieba / cross-encoder
- 不自动 git commit（除非用户明确要求）
- 测试命令：`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=server python3 -m unittest …`
- 首页若当前不走 orchestrate、无 citations 通道：Task 6 仅做「有则渲染」的轻量挂钩或注明跳过，不强制改造整条首页会话协议

## File map

| File | Responsibility |
|------|----------------|
| `server/kb_query_parse.py`（新建）或扩 `kb_fts.py` | 抽法名/条号、条号规范化、AND FTS 串 |
| `server/kb_fts.py` | 标题写入 `body_idx`；`normalize_fts_query` 支持 AND 模式 |
| `server/vector_service.py` | 标题加权重排；hybrid 时弱化纯条号 boost |
| `server/http_api_extra.py` | `format_kb_hits` / retrieve 输出 citations |
| `server/agents/orchestrator.py` | 透传 `citations` 到编排结果 |
| `admin_kb_files.js` | `open` 支持 article 高亮滚动 |
| `mcp_client.js` | 回答区挂法规链接 |
| `home.js` / `home.html` | 若有助手消息渲染点则挂链；否则记录限制 |
| `admin_kb_laws.html` / `admin_kb_cases.html` | 试检索结果可点预览 |
| `tests/test_kb_query_parse.py` / `tests/test_hybrid_search.py` / `tests/test_kb_retrieve.py` | 单测 |

---

### Task 1: 查询解析 + FTS AND 构造

**Files:**
- Create: `server/kb_query_parse.py`（推荐独立，保持 `kb_fts` 精简）
- Modify: `server/kb_fts.py` — `normalize_fts_query` 接受解析结果或 `mode`
- Test: `tests/test_kb_query_parse.py`

**Interfaces:**

```python
# server/kb_query_parse.py
def extract_articles(query: str) -> list[str]:
    """返回原文中的条号字符串列表，如 ['第六十四条'] 或 ['第64条']。"""

def normalize_article_forms(article: str) -> list[str]:
    """同一条号的阿拉伯/中文变体，用于高亮与匹配。"""

def extract_law_name_hint(query: str) -> str | None:
    """启发式：去掉检索动词后，取含「法|条例|规定|办法」的片段。"""

def build_fts_match(query: str) -> str:
    """
    若同时有法名线索与条号：('"法名…" AND "第X条"')（可带法名其它 token AND）。
    否则：沿用现有 OR 策略（调用 kb_fts 内部逻辑或共享）。
    """
```

- [ ] **Step 1: Write failing tests**

```python
# tests/test_kb_query_parse.py
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
from kb_query_parse import extract_articles, extract_law_name_hint, build_fts_match, normalize_article_forms

class TestKbQueryParse(unittest.TestCase):
    def test_extract_article_and_law(self):
        self.assertIn("第六十四条", extract_articles("检索劳动合同法第六十四条")
                      or extract_articles("检索劳动合同法第64条")
                      or ["第64条"])
        self.assertTrue(extract_law_name_hint("检索劳动合同法第64条"))
        self.assertIn("劳动", extract_law_name_hint("检索劳动合同法第64条") or "")

    def test_and_when_law_and_article(self):
        m = build_fts_match("检索劳动合同法第六十四条")
        self.assertIn(" AND ", m)
        self.assertNotIn(" OR ", m.split("AND")[0] + "AND")  # 主连接为 AND；允许法名内部无 OR
        # 更稳：断言同时含法名与条号引号片段且含 AND
        self.assertIn("AND", m)
        self.assertTrue("第六十四条" in m or "第64条" in m)

    def test_article_forms(self):
        forms = normalize_article_forms("第64条")
        self.assertTrue(any("六十四" in f or f == "第64条" for f in forms))
```

（按实现微调断言，但必须锁住 AND 行为。）

- [ ] **Step 2: Run — FAIL**

`PYTHONPATH=server python3 -m unittest tests.test_kb_query_parse -v`

- [ ] **Step 3: Implement `kb_query_parse.py`；改 `KbFtsIndex.search` 使用 `build_fts_match` 替代裸 `normalize_fts_query`**

保留 `normalize_fts_query` 作 OR 回退，供 `build_fts_match` 调用。

- [ ] **Step 4: Run — PASS；再跑 `tests.test_kb_fts` 确认不回归**

- [ ] **Step 5: Commit only if user asks**

---

### Task 2: FTS 索引带标题 + 融合后标题加权

**Files:**
- Modify: `server/kb_fts.py` — `upsert_chunks` 接受可选 `title`，`body_idx = prepare(title + " " + body)`
- Modify: `server/vector_service.py` — `_sync_fts_for_chunks` 传入 metadata title/law_name；`search` 在 RRF 后调用 `_boost_title_matches(query, hits)`
- Modify: `rebuild_fts_from_chroma` 同步带 title
- Test: `tests/test_hybrid_search.py` 增加标题加权用例

- [ ] **Step 1: Failing test — 两 chunk 同条号，仅 A 标题含「劳动合同法」，query 含该法名时 A 排前**

用 `__new__` + mock `collection.query` + 真实/临时 FTS：upsert 两文，「食品安全法…第六十四条」与「劳动合同法…第六十四条」；search 后 assert top title。

- [ ] **Step 2: Run FAIL**

- [ ] **Step 3: Implement**

```python
def _title_from_meta(meta: dict) -> str:
    return (meta.get("law_name") or meta.get("title") or "").strip()

def _boost_title_matches(query: str, hits: list) -> list:
    hint = extract_law_name_hint(query)
    if not hint:
        return hits
    def score(h):
        t = _title_from_meta(h.get("metadata") or {})
        bonus = 1.0 if hint in t or t in hint else 0.0
        # 也可：hint 去掉「法」后子串
        return (bonus, h.get("rrf_score") or 0.0)
    return sorted(hits, key=score, reverse=True)
```

Hybrid 时：若 `boost_keywords` 且存在条号，跳过「仅数字/条号」类 boost（保留法名字符串 boost），或在 hybrid 默认 `boost_keywords=False` 对条号部分 —— 按 spec：弱化纯条号 boost。

- [ ] **Step 4: PASS + `tests.test_kb_fts`**

- [ ] **Step 5: Commit if asked**

**迁移：** 标题进入 FTS 需重建索引。在 `attach_fts` 后增加一次条件重建策略二选一（实现时选 A）：

- **A（推荐）：** 若 Chroma count > 0，增加 metadata 标记/版本号 `fts_schema_version`；版本低于 2 则 `rebuild_fts_from_chroma`  
- **B：** 文档说明需手动清空 FTS 或重启触发空库重建（已有文档可能 FTS 非空则不重建）→ **必须实现 A 或显式管理 API**，否则标题加权对旧数据无效

---

### Task 3: citations 结构化输出

**Files:**
- Modify: `server/http_api_extra.py` — `format_kb_hits` 保留；新增 `hits_to_citations(hits, query) -> list[dict]`；`make_kb_retrieve_fn` 返回 `law_citations` / `case_citations`
- Modify: `server/agents/orchestrator.py` — `_run_legal_retrieval` 结果增加 `citations`（合并 law+case）；顶层 orchestrate result 透出 `citations`
- Test: `tests/test_kb_retrieve.py`

Citation shape（spec）：

```python
{
  "id": chunk_id,
  "doc_type": "law",
  "document_id": "...",
  "file_id": meta.get("file_id"),
  "title": "...",
  "article": extract first article from query or snippet,
  "snippet": doc[:400],
  "rrf_score": ...,
}
```

- [ ] **Step 1: Test retrieve returns law_citations with file_id/title**

- [ ] **Step 2–4: Implement + PASS**

- [ ] **Step 5: Commit if asked**

确认 `handle_orchestrate` 返回 JSON 含 `citations`（从 specialist result 提升到顶层，便于前端）。

---

### Task 4: `KbFilePreview` 条号高亮

**Files:**
- Modify: `admin_kb_files.js` — `open(fileId, fallbackName, options)`
- 可选：极简 DOM 测无法做则手工清单；可加 `highlightArticleInText(text, article) -> { html, index }` 纯函数到同文件或 `kb_preview_utils.js`，用 node 难跑则把纯函数放到可 unittest 的小段 —— **优先在 JS 内实现，Python 侧不测 DOM**

行为：

```javascript
async function open(fileId, fallbackName, options) {
  options = options || {};
  const article = options.article || "";
  // ... existing load ...
  // when rendering <pre> from text_content:
  // split/mark first match of any normalize forms; scrollIntoView
  // PDF: set subtitle/hint "请在文内查找：第X条"
}
```

导出 `normalizeArticleForms` 可与后端规则对齐的简化版（至少 `第64条` / `第六十四条` 双向：可用固定映射表 1–99 或只高亮 query 原文 +「第」+数字+「条」变体）。

- [ ] **Step 1:** 实现 `open` 第三参；文本路径高亮；PDF 提示  
- [ ] **Step 2:** 手工：管理端打开一带「第64条」的 txt/抽取 Word  
- [ ] **Step 3:** Commit if asked

---

### Task 5: 管理端试检索可点预览

**Files:**
- Modify: `admin_kb_laws.html`、`admin_kb_cases.html`（templates 若有同类试检索则一并）

在 `runSearch` 结果渲染：

```javascript
const fileId = md.file_id;
const article = /* 从 query 用简单正则抽第X条 */;
const titleEl = document.createElement("button"); // or <a>
titleEl.type = "button";
titleEl.className = "sr-title-link";
titleEl.textContent = title;
titleEl.disabled = !fileId;
titleEl.onclick = function () {
  if (!fileId) { UI.toast("未关联源文件", false); return; }
  filePreview.open(fileId, title, { article: article });
};
```

确保上传入库 metadata 含 `file_id`（`kb_ingest` / `chunk_metadata` 已有则核验）。

- [ ] **Step 1–2:** 改两页 + 冒烟  
- [ ] **Step 3:** Commit if asked

---

### Task 6: 多轮对话（+ 首页尽力）挂链

**Files:**
- Modify: `mcp_client.js` — 处理 orchestrate `data.citations`；在 `orchestrate-answer` 中渲染链接列表或把标题替换为按钮  
- Modify: `home.js` — 仅当存在可注入 citations 的响应路径时挂载；否则在计划验收中注明「首页当前非 orchestrate，本 Task 跳过」

推荐 UI：回答正文下方增加「引用」区：

```html
<div class="cite-list">
  <button type="button" class="cite-link" data-file-id="..." data-article="第六十四条">《劳动合同法》第六十四条</button>
</div>
```

点击调用已有 `chatFilePreview.open(...)`。

无 `file_id`：按钮 disabled + title 提示。

- [ ] **Step 1:** mcp_client 渲染 citations  
- [ ] **Step 2:** 确认 `mcp_client.html` 已引入 `admin_kb_files.js`  
- [ ] **Step 3:** home 评估后实现或显式跳过并更新 spec 验收注记  
- [ ] **Step 4:** Commit if asked

---

### Task 7: 回归与 MCP 重启

- [ ] **Step 1:**

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=server python3 -m unittest \
  tests.test_kb_query_parse tests.test_kb_fts tests.test_hybrid_search \
  tests.test_kb_retrieve tests.test_orchestrate -v
```

Expected: OK

- [ ] **Step 2:** 重启 MCP（触发 FTS schema/version 重建）

- [ ] **Step 3:** 手工验收  
  - 多轮：「检索劳动合同法第64条」→ 首条非食品安全法（库内有劳合时）  
  - 点击引用 → 文本高亮  
  - 管理端试检索同 query → 可点预览  

---

## Spec coverage

| Spec | Task |
|------|------|
| 法名∧条号 AND | 1 |
| 标题索引 + 加权 | 2 |
| hybrid 弱化条号 boost | 2 |
| citations 结构 | 3 |
| KbFilePreview 高亮 | 4 |
| 试检索可点 | 5 |
| 对话可点 | 6 |
| PDF 提示 | 4 |
| 验收用例 | 7 |

## Self-review notes

- 首页可能无 orchestrate：Task 6 允许跳过并写明，避免假完成。  
- 旧 FTS 无标题：Task 2 必须带 versioned rebuild。  
- Commit 步骤默认跳过，遵从用户规则。
