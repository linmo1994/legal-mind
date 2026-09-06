# 本地 KB 未命中 → 外源导引 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 法规本地检索未命中时返回 `external_search`（国家法律法规数据库提示+链接），并在回答区与编排时间线展示；不抓取外网正文。

**Architecture:** 纯函数 `assess_law_retrieve_miss` + `build_external_search_hint` 判定 miss 并拼 hint；`retrieve_law` 附带字段；PnE 上提并 `emit_step(kind=external)`；前端渲染提示块与「外源」徽章。

**Tech Stack:** 现有 Python 服务端 + `mcp_client` 静态页（无新框架）

**Spec:** `docs/superpowers/specs/2026-09-06-kb-external-fallback-hint-design.md`

## Global Constraints

- 外源形态 C：仅提示 + 官网链接，**不**自动抓取 / 调 flk API / MCP 外源拉正文。
- 未命中规则 A：`empty` | `law_mismatch` | `article_mismatch`。
- 官网 provider：`npc_flk`，默认站 `https://flk.npc.gov.cn/`。
- 外链**不**写入 `citations`。
- 仅 `retrieve_law` 触发；`retrieve_case` 本期不触发。
- 提交仅当用户明确要求时执行。

## File map

| File | Responsibility |
|------|----------------|
| `server/kb_external_hint.py` | miss 判定 + hint/URL 拼装 |
| `tests/test_kb_external_hint.py` | 单元测试 |
| `server/agents/pe_tools.py` | `retrieve_law` 附加 `external_search` |
| `tests/test_pe_tools.py` | 工具返回含/不含 hint |
| `server/agents/plan_execute.py` | 上提字段 + emit external |
| `mcp_client.js` / `.css` / `.html` | 提示块 + 时间线 + cache-bust |

---

### Task 1: `assess_law_retrieve_miss` + hint builder（TDD）

**Files:**
- Create: `server/kb_external_hint.py`
- Create: `tests/test_kb_external_hint.py`

**Interfaces:**
- Produces:
  - `title_matches_law_hint(title: str, hint: str) -> bool`（可与 VectorService 逻辑对齐的副本，避免循环导入）
  - `assess_law_retrieve_miss(query: str, *, citations: list = None, hits: list = None, laws_text: str = "") -> Optional[str]`  
    返回 `None`（命中）或 reason `"empty"|"law_mismatch"|"article_mismatch"`
  - `build_external_search_hint(query: str, reason: str) -> dict`  
    返回完整 `ExternalSearchHint`（`needed=True`, `provider="npc_flk"`, `label="国家法律法规数据库"`, `url`, `note`, `query`）

- [ ] **Step 1: Write failing tests** in `tests/test_kb_external_hint.py`:

```python
# tests/test_kb_external_hint.py
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from kb_external_hint import (
    assess_law_retrieve_miss,
    build_external_search_hint,
)

class TestKbExternalHint(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(
            assess_law_retrieve_miss("劳动合同法第六十四条", citations=[], laws_text=""),
            "empty",
        )

    def test_hit_no_hint(self):
        cites = [{
            "title": "中华人民共和国劳动合同法",
            "article": "第六十四条",
            "snippet": "第六十四条　被派遣劳动者有权……",
        }]
        self.assertIsNone(
            assess_law_retrieve_miss("帮我检索劳动合同法第64条", citations=cites)
        )

    def test_law_mismatch(self):
        cites = [{
            "title": "中华人民共和国食品安全法",
            "article": "第六十四条",
            "snippet": "第六十四条　食用农产品……",
        }]
        self.assertEqual(
            assess_law_retrieve_miss("帮我检索劳动合同法第64条", citations=cites),
            "law_mismatch",
        )

    def test_article_mismatch(self):
        cites = [{
            "title": "中华人民共和国劳动合同法",
            "article": "第三十八条",
            "snippet": "第三十八条 用人单位有下列情形……",
        }]
        self.assertEqual(
            assess_law_retrieve_miss("帮我检索劳动合同法第64条", citations=cites),
            "article_mismatch",
        )

    def test_build_hint_fields(self):
        h = build_external_search_hint("帮我检索劳动合同法第64条", "article_mismatch")
        self.assertTrue(h["needed"])
        self.assertEqual(h["provider"], "npc_flk")
        self.assertEqual(h["label"], "国家法律法规数据库")
        self.assertIn("flk.npc.gov.cn", h["url"])
        self.assertIn("未自动抓取", h["note"])
        self.assertIn("劳动", h["query"])
        self.assertTrue("64" in h["query"] or "六十四" in h["query"])
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `PYTHONPATH=server python3 -m unittest tests.test_kb_external_hint -v`  
Expected: import/assert failures

- [ ] **Step 3: Implement `server/kb_external_hint.py`**

```python
"""Local law-retrieve miss detection + NPC FLK external search hint (no scraping)."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from kb_query_parse import (
    doc_has_article,
    extract_articles,
    extract_law_name_hint,
    normalize_article_forms,
)

NPC_FLK_HOME = "https://flk.npc.gov.cn/"
NOTE = "本地知识库未命中；未自动抓取外网正文，请打开官网核对。"

def title_matches_law_hint(title: str, hint: str) -> bool:
    # Same soft rules as VectorService._title_matches_hint
    ...

def _docs_from(citations, hits, laws_text) -> List[Dict[str, str]]:
    # Normalize to {title, text} from citations (title+snippet), hits (metadata+document), or laws_text alone
    ...

def assess_law_retrieve_miss(query: str, *, citations=None, hits=None, laws_text: str = "") -> Optional[str]:
    docs = _docs_from(citations, hits, laws_text)
    if not docs and not (laws_text or "").strip():
        return "empty"
    hint = extract_law_name_hint(query)
    arts = extract_articles(query)
    if hint:
        titled = [d for d in docs if title_matches_law_hint(d.get("title") or "", hint)]
        if not titled:
            return "law_mismatch"
        pool = titled
    else:
        pool = docs
    if arts:
        if not any(any(doc_has_article(d.get("text") or "", a) for a in arts) for d in pool):
            return "article_mismatch"
    return None

def build_suggest_query(query: str) -> str:
    hint = extract_law_name_hint(query) or ""
    arts = extract_articles(query)
    art = ""
    if arts:
        forms = normalize_article_forms(arts[0])
        art = next((f for f in forms if "六" in f or not f[1:-1].isdigit()), forms[0]) if forms else arts[0]
    return " ".join(x for x in (hint, art) if x).strip() or (query or "").strip()

def build_external_search_hint(query: str, reason: str) -> Dict[str, Any]:
    sq = build_suggest_query(query)
    # Prefer homepage + encoded query in fragment/note; deep link optional:
    url = NPC_FLK_HOME  # stable; note carries 检索词
    return {
        "needed": True,
        "reason": reason,
        "query": sq,
        "provider": "npc_flk",
        "label": "国家法律法规数据库",
        "url": url,
        "note": NOTE + (f" 建议检索词：{sq}" if sq else ""),
    }
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `PYTHONPATH=server python3 -m unittest tests.test_kb_external_hint -v`  
Expected: OK

---

### Task 2: Wire `retrieve_law` + PnE emit / 上提

**Files:**
- Modify: `server/agents/pe_tools.py`（`retrieve_law` 分支）
- Modify: `server/agents/plan_execute.py`（工具结果处理、`_result`）
- Modify: `tests/test_pe_tools.py`

**Interfaces:**
- Consumes: `assess_law_retrieve_miss`, `build_external_search_hint`
- Produces: `run_tool("retrieve_law", ...)` → 可含 `external_search`；PnE 顶层 `external_search`（最后一次未命中）

- [ ] **Step 1: Extend pe_tools test**

```python
def test_retrieve_law_miss_adds_external_search(self):
    def retrieve(q, scopes=None):
        return {"laws": "", "law_citations": []}
    out = run_tool("retrieve_law", {"query": "某某不存在法第一条"}, {"retrieve_fn": retrieve, "objective": "x"})
    self.assertTrue(out.get("external_search", {}).get("needed"))
    self.assertEqual(out["external_search"]["provider"], "npc_flk")

def test_retrieve_law_hit_no_external_search(self):
    def retrieve(q, scopes=None):
        return {
            "laws": "《劳动合同法》\n第六十四条……",
            "law_citations": [{
                "title": "中华人民共和国劳动合同法",
                "article": "第六十四条",
                "snippet": "第六十四条　被派遣劳动者……",
            }],
        }
    out = run_tool("retrieve_law", {"query": "劳动合同法第六十四条"}, {"retrieve_fn": retrieve})
    self.assertFalse(out.get("external_search"))
```

- [ ] **Step 2: Run — expect FAIL** then implement in `pe_tools.py`:

```python
if name == "retrieve_law":
    ...
    raw = retrieve_fn(query, scopes=["law"]) or {}
    cites = _citations_from_retrieve(raw)
    out = {
        "observation": _observation_from_retrieve(raw, "law"),
        "citations": cites,
    }
    from kb_external_hint import assess_law_retrieve_miss, build_external_search_hint
    reason = assess_law_retrieve_miss(
        query,
        citations=cites,
        laws_text=str(raw.get("laws") or ""),
    )
    if reason:
        out["external_search"] = build_external_search_hint(query, reason)
    return out
```

- [ ] **Step 3: PnE** — 在执行循环中：

```python
external_search = None  # before loop / resume carry optional
...
tool_out = run_tool(...)
if tool_out.get("external_search"):
    external_search = tool_out["external_search"]
    emit_step(
        "external",
        "npc_flk",
        "国家法律法规数据库（未自动抓取）",
        status="done",
        detail={
            "reason": external_search.get("reason"),
            "query": external_search.get("query"),
            "url": external_search.get("url"),
        },
    )
...
# all _result(...) include external_search=external_search
```

Update `_result` signature to accept `external_search: Optional[Dict] = None` and put it on the returned dict when truthy.

- [ ] **Step 4: Run**

`PYTHONPATH=server python3 -m unittest tests.test_pe_tools tests.test_plan_execute tests.test_kb_external_hint -v`  
Expected: OK

---

### Task 3: Frontend 提示块 + 时间线

**Files:**
- Modify: `mcp_client.js`（`applyOrchestrateSuccess` / `buildOrchestrateTurnView` / `buildWorkbenchTimeline` / 新 `renderExternalSearchHint`）
- Modify: `mcp_client.css`
- Modify: `mcp_client.html` cache-bust → `?v=20260906ext1`

**Interfaces:**
- Consumes: `data.external_search`；`view.external_search`；flow `kind=external`
- Produces: 回答下方提示块；时间线徽章「外源」

- [ ] **Step 1: `buildOrchestrateTurnView`** 增加 `external_search: data.external_search || null`

- [ ] **Step 2: `kindBadgeClass`** — `k === 'external'` → `kind-external`；徽章文案「外源」

- [ ] **Step 3: `buildWorkbenchTimeline`** — 保留 flow 中 `kind=external`（不要过滤掉）

- [ ] **Step 4: `renderExternalSearchHint(host, hint)`**

```javascript
function renderExternalSearchHint(host, hint) {
  if (!host || !hint || !hint.needed) return;
  const prev = host.querySelector('.external-search-hint');
  if (prev) prev.remove();
  const wrap = document.createElement('div');
  wrap.className = 'external-search-hint';
  wrap.innerHTML = ''; // use DOM APIs:
  // note text, query line, <a href=url target=_blank rel="noopener noreferrer">打开国家法律法规数据库</a>
  host.appendChild(wrap);
}
```

Call after citations in `applyOrchestrateSuccess`（`listHost` = `targetShell.content`）。

- [ ] **Step 5: CSS**

```css
.external-search-hint {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid #c7d2fe;
  background: #eef2ff;
  border-radius: 8px;
  font-size: 13px;
  color: #312e81;
}
.external-search-hint a { color: #3730a3; font-weight: 600; }
.orchestrate-wb-badge.kind-external { background: #fae8ff; color: #86198f; }
```

- [ ] **Step 6:** `node --check mcp_client.js`；cache-bust `20260906ext1`

---

### Task 4: 手工验收

- [ ] 硬刷新多轮页（`v=20260906ext1`），重启 MCP 加载后端。
- [ ] 问库内有的「劳动合同法第六十四条」：无外源块；时间线有知识库、无「外源」。
- [ ] 问明显不存在的法条名：有提示块 + flk 链接；时间线有「外源」；引用区无假 citation。
- [ ] 链接新标签打开官网；文案含「未自动抓取」。

---

## Spec coverage (self-review)

| Spec | Task |
|------|------|
| miss A 三分支 + 命中 | T1 |
| `external_search` 结构 / 不上 citations | T1–T2 |
| emit external + 顶层字段 | T2 |
| 回答区提示块 | T3 |
| 时间线外源 | T3 |
| 不抓取 flk | 全局约束；无爬虫任务 |
| 验收 1–5 | T4 |
