# Citation file_id + Retrieve Plan Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Citations from KB retrieve carry resolvable `file_id` so UI links open previews; Plan-and-Execute prompts and a light plan injector ensure law/case retrieve steps when answers need authority.

**Architecture:** Enrich citations at `hits_to_citations` via optional `resolve_kb_doc` callback backed by `KbStore` (id lookup then title match). Wire `make_kb_retrieve_fn` to `mcp_server.kb_store`. Separately, extend PnE planner/executor/replan prompts and add `_ensure_retrieve_steps` after plan/replan to prepend missing retrieve steps.

**Tech Stack:** Python 3, unittest, existing `KbStore` / `http_api_extra` / `agents.plan_execute`.

## Global Constraints

- Do not re-embed Chroma or force re-ingest.
- Do not add response hard-gate (approach 3); injection + prompts only.
- Do not change frontend citation UX semantics (disabled without `file_id` remains).
- Do not invent citations without retrieve hits.
- Prefer exact title match over substring; prefer newer `updated_at` on ties.
- Respect `MAX_PLAN_STEPS` when injecting.
- User rule: do not `git commit` unless the user explicitly asks; skip commit steps or stage only.

---

## File map

| File | Responsibility |
|------|----------------|
| `server/kb_store.py` | `find_documents_by_title(doc_type, title)` for enrichment |
| `server/http_api_extra.py` | `resolve_file_id_from_store`, `hits_to_citations(..., resolve_doc=)`, wire store in `make_kb_retrieve_fn` |
| `server/agents/plan_execute.py` | Prompt text; `_wants_law_retrieve` / `_wants_case_retrieve`; `_ensure_retrieve_steps`; call after plan/replan |
| `tests/test_kb_retrieve.py` | file_id enrichment cases |
| `tests/test_kb_store.py` or extend existing | title find (if new method) |
| `tests/test_plan_execute.py` | injection + no-duplicate cases |

---

### Task 1: KbStore title lookup

**Files:**
- Modify: `server/kb_store.py`
- Test: `tests/test_kb_store_title.py` (create) — or append to existing kb_store tests if present

**Interfaces:**
- Produces: `KbStore.find_documents_by_title(self, *, doc_type: str, title: str, limit: int = 10) -> list[dict]` — non-deleted rows where `title == title` OR title contains / is contained by query title (both stripped); ordered by exact match first, then `updated_at DESC`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kb_store_title.py
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from kb_store import KbStore


class TestKbStoreTitle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = KbStore(self.tmp.name)
        self.store.ensure_schema()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_find_by_exact_title_prefers_newer(self):
        self.store.create_document(
            id="old",
            doc_type="law",
            file_id="f-old",
            title="中华人民共和国劳动合同法",
            status="ready",
            meta={},
            created_by=None,
        )
        import time
        time.sleep(0.02)
        self.store.create_document(
            id="new",
            doc_type="law",
            file_id="f-new",
            title="中华人民共和国劳动合同法",
            status="ready",
            meta={},
            created_by=None,
        )
        rows = self.store.find_documents_by_title(
            doc_type="law", title="中华人民共和国劳动合同法"
        )
        self.assertEqual(rows[0]["id"], "new")
        self.assertEqual(rows[0]["file_id"], "f-new")

    def test_skips_deleted(self):
        self.store.create_document(
            id="d1",
            doc_type="law",
            file_id="f1",
            title="X法",
            status="deleted",
            meta={},
            created_by=None,
        )
        self.assertEqual(
            self.store.find_documents_by_title(doc_type="law", title="X法"), []
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kanglinlin/Documents/cursor/AI法官 && PYTHONPATH=server python3 -m unittest tests.test_kb_store_title -v`  
Expected: FAIL — `find_documents_by_title` missing

- [ ] **Step 3: Implement `find_documents_by_title`**

```python
# server/kb_store.py — add method on KbStore
def find_documents_by_title(
    self, *, doc_type: str, title: str, limit: int = 10
) -> list[dict]:
    self._validate_doc_type(doc_type)
    q = (title or "").strip()
    if not q:
        return []
    with self._conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM kb_documents
            WHERE doc_type = ? AND status != 'deleted'
              AND (
                title = ?
                OR title LIKE '%' || ? || '%'
                OR ? LIKE '%' || title || '%'
              )
              AND length(trim(title)) > 0
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (doc_type, q, q, q, max(1, int(limit))),
        ).fetchall()
    docs = [self._row_to_dict(r) for r in rows]
    docs.sort(
        key=lambda d: (
            0 if (d.get("title") or "").strip() == q else 1,
            -(float(d.get("updated_at") or 0)),
        )
    )
    return docs[: max(1, int(limit))]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=server python3 -m unittest tests.test_kb_store_title -v`  
Expected: PASS

- [ ] **Step 5: Commit** (only if user asked)

```bash
# skip unless user requested commit
```

---

### Task 2: Enrich `hits_to_citations` with `file_id`

**Files:**
- Modify: `server/http_api_extra.py` (`hits_to_citations`, helpers, `make_kb_retrieve_fn`)
- Test: `tests/test_kb_retrieve.py`

**Interfaces:**
- Consumes: `KbStore.get_document`, `KbStore.find_documents_by_title`
- Produces:
  - `def resolve_kb_file_id(store, *, document_id: str = "", title: str = "", doc_type: str = "") -> tuple[str | None, dict | None]`  
    Returns `(file_id, doc_row_or_None)`.
  - `hits_to_citations(hits, query="", *, resolve_doc=None)` where `resolve_doc(document_id, title, doc_type) -> dict | None` with keys `file_id`, `title`, `doc_type`, `document_id` (optional).
  - `make_kb_retrieve_fn` passes resolve_doc when `mcp_server.kb_store` present.

- [ ] **Step 1: Write failing tests in `tests/test_kb_retrieve.py`**

```python
def test_hits_to_citations_resolves_file_id_by_document_id(self):
    hits = [
        {
            "id": "kb_law_abc_chunk_0",
            "document": "第六十四条 非全日制用工……",
            "metadata": {
                "doc_type": "law",
                "document_id": "kb_law_abc",
                "title": "中华人民共和国劳动合同法",
                # no file_id
            },
        }
    ]

    def resolve_doc(document_id, title, doc_type):
        if document_id == "kb_law_abc":
            return {
                "file_id": "file-uuid-1",
                "title": "中华人民共和国劳动合同法",
                "doc_type": "law",
                "document_id": "kb_law_abc",
            }
        return None

    cites = hits_to_citations(hits, "劳动合同法第64条", resolve_doc=resolve_doc)
    self.assertEqual(cites[0]["file_id"], "file-uuid-1")

def test_hits_to_citations_resolves_file_id_by_title_when_legacy_id(self):
    hits = [
        {
            "id": "legacy_0",
            "document": "第六十四条 ……",
            "metadata": {
                "document_id": "中华人民共和国劳动合同法",
                # no title, no file_id, no doc_type
            },
        }
    ]

    def resolve_doc(document_id, title, doc_type):
        key = title or document_id
        if key == "中华人民共和国劳动合同法":
            return {
                "file_id": "file-uuid-2",
                "title": "中华人民共和国劳动合同法",
                "doc_type": "law",
                "document_id": "kb_law_real",
            }
        return None

    cites = hits_to_citations(hits, "劳动合同法第六十四条", resolve_doc=resolve_doc)
    self.assertEqual(cites[0]["file_id"], "file-uuid-2")
    self.assertEqual(cites[0]["title"], "中华人民共和国劳动合同法")

def test_hits_to_citations_keeps_missing_file_id_when_unresolved(self):
    hits = [
        {
            "id": "x",
            "document": "第一条",
            "metadata": {"title": "未知法", "doc_type": "law"},
        }
    ]
    cites = hits_to_citations(hits, "未知法", resolve_doc=lambda *a, **k: None)
    self.assertTrue(cites[0]["file_id"] in (None, ""))
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `PYTHONPATH=server python3 -m unittest tests.TestKbRetrieve.test_hits_to_citations_resolves_file_id_by_document_id tests.TestKbRetrieve.test_hits_to_citations_resolves_file_id_by_title_when_legacy_id -v`  
(Adjust class path: `tests.test_kb_retrieve.TestKbRetrieve.test_...`)  
Expected: FAIL on `resolve_doc` kwarg / missing file_id

- [ ] **Step 3: Implement enrichment**

In `server/http_api_extra.py`:

```python
def resolve_kb_file_id(store, *, document_id: str = "", title: str = "", doc_type: str = ""):
    """Look up kb_documents for file_id. Returns (file_id|None, row|None)."""
    if store is None:
        return None, None
    doc_id = (document_id or "").strip()
    if doc_id:
        try:
            row = store.get_document(doc_id)
        except Exception:
            row = None
        if row and row.get("file_id"):
            return row.get("file_id"), row
    title_q = (title or "").strip() or doc_id
    if not title_q:
        return None, None
    types = []
    if doc_type in ("law", "case"):
        types = [doc_type]
    else:
        types = ["law", "case"]
    for dt in types:
        try:
            rows = store.find_documents_by_title(doc_type=dt, title=title_q, limit=5)
        except Exception:
            rows = []
        for row in rows or []:
            if row.get("file_id"):
                return row.get("file_id"), row
    return None, None


def make_resolve_doc_from_store(store):
    def resolve_doc(document_id, title, doc_type):
        fid, row = resolve_kb_file_id(
            store,
            document_id=document_id or "",
            title=title or "",
            doc_type=doc_type or "",
        )
        if not row and not fid:
            return None
        out = {
            "file_id": fid or (row or {}).get("file_id"),
            "title": (row or {}).get("title") or title,
            "doc_type": (row or {}).get("doc_type") or doc_type,
            "document_id": (row or {}).get("id") or document_id,
        }
        return out if out.get("file_id") else None

    return resolve_doc
```

Update `hits_to_citations`:

```python
def hits_to_citations(hits: list, query: str = "", *, resolve_doc=None) -> list:
    # ... existing loop ...
        file_id = meta.get("file_id") or None
        document_id = meta.get("document_id") or ""
        title = (
            meta.get("title") or meta.get("law_name") or meta.get("case_no") or ""
        ).strip()
        doc_type = meta.get("doc_type") or ""
        if (not file_id or not title or not doc_type) and callable(resolve_doc):
            try:
                resolved = resolve_doc(document_id, title, doc_type)
            except Exception:
                resolved = None
            if isinstance(resolved, dict):
                file_id = file_id or resolved.get("file_id") or None
                title = title or (resolved.get("title") or "").strip()
                doc_type = doc_type or resolved.get("doc_type") or ""
                if resolved.get("document_id") and (
                    not document_id or document_id == title
                ):
                    # prefer real kb id when legacy used title as document_id
                    document_id = resolved.get("document_id") or document_id
        # ... rest unchanged, use enriched title/doc_type/file_id/document_id ...
```

Wire in `make_kb_retrieve_fn`:

```python
def make_kb_retrieve_fn(mcp_server):
    store = getattr(mcp_server, "kb_store", None)
    resolve_doc = make_resolve_doc_from_store(store) if store else None
    # in retrieve():
    out["law_citations"] = hits_to_citations(hits, q, resolve_doc=resolve_doc)
    out["case_citations"] = hits_to_citations(hits, q, resolve_doc=resolve_doc)
```

- [ ] **Step 4: Run enrichment + existing retrieve tests**

Run: `PYTHONPATH=server python3 -m unittest tests.test_kb_retrieve tests.test_kb_store_title -v`  
Expected: PASS

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 3: PnE prompt guidance for retrieve

**Files:**
- Modify: `server/agents/plan_execute.py` — `PLANNER_SYSTEM`, `EXECUTOR_SYSTEM`, `REPLAN_SYSTEM`
- Test: `tests/test_plan_execute.py` — assert prompt substrings via importing constants (lightweight)

**Interfaces:**
- Produces: updated system prompt strings containing explicit `retrieve_law` / `retrieve_case` guidance (Chinese OK).

- [ ] **Step 1: Write failing assertion test**

```python
# tests/test_plan_execute.py
from agents.plan_execute import PLANNER_SYSTEM, EXECUTOR_SYSTEM, REPLAN_SYSTEM

def test_prompts_mention_retrieve_tools(self):
    self.assertIn("retrieve_law", PLANNER_SYSTEM)
    self.assertIn("retrieve_case", PLANNER_SYSTEM)
    self.assertIn("retrieve_law", EXECUTOR_SYSTEM)
    self.assertIn("retrieve_case", REPLAN_SYSTEM)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `PYTHONPATH=server python3 -m unittest tests.test_plan_execute.TestPlanExecute.test_prompts_mention_retrieve_tools -v`

- [ ] **Step 3: Append guidance to prompts**

```python
_RETRIEVE_GUIDANCE = (
    "需要法条依据或用户要求检索法规时，计划须含法规检索（工具 retrieve_law）；"
    "需要类案/判例或用户要求检索案例时，须含类案检索（工具 retrieve_case）。"
    "纯闲聊或仅收集当事人信息、不给出实体法结论时可不检索。"
    "最终答复应写明所依据的法规名称与条款（及类案标识），与检索结果一致。"
)

PLANNER_SYSTEM = (
    "你是法律任务规划助手（planner）。根据用户目标产出可执行的步骤列表。"
    "只输出 JSON：{\"plan\":[\"步骤1\", ...]}，步骤为自然语言，长度 1–8。"
    + _NO_CASE_GUIDANCE
    + _RETRIEVE_GUIDANCE
)

EXECUTOR_SYSTEM = (
    "你是法律步骤执行器（executor）。根据当前步骤选一个工具并给出参数。"
    f"可用工具：{', '.join(TOOL_NAMES)}。"
    "只输出 JSON：{\"tool\":\"工具名\",\"args\":{...}}。"
    "若当前步骤是检索法规，选择 retrieve_law；检索类案则 retrieve_case；"
    "args.query 尽量保留用户提到的法名、条款、案由关键词。"
    "若目标是生成起诉状/文书且用户已给出原告与被告（或明确要求占位起草），"
    "在无法读卷宗时优先选择 draft_doc，不要反复选择 read_evidence。"
)

REPLAN_SYSTEM = (
    "你是法律任务收口助手。根据目标、已执行步骤与剩余待办，"
    "在三种动作中选其一，只输出 JSON：\n"
    "- {\"action\":\"continue\",\"plan\":[\"尚未做的步骤\",...]}\n"
    "- {\"action\":\"response\",\"response\":\"最终答复\"}\n"
    "- {\"action\":\"ask_user\",\"question\":\"向用户追问\"}\n"
    + _NO_CASE_GUIDANCE
    + _RETRIEVE_GUIDANCE
    + "若仍需法源而过去步骤尚未检索成功，优先 continue 并补上检索步骤，再 response。"
    + "若用户要生成起诉状/导出文书且已提供原告与被告（或要求占位起草），"
    "应 continue 并安排 draft_doc，或在已起草后 response；不要在能起草时仅 ask_user。"
)
```

Note: existing tests key off substrings like `"步骤列表"` / `"选一个工具"` / `"规划"` — keep those strings intact.

- [ ] **Step 4: Run plan_execute tests**

Run: `PYTHONPATH=server python3 -m unittest tests.test_plan_execute -v`  
Expected: PASS

---

### Task 4: Plan retrieve-step injection

**Files:**
- Modify: `server/agents/plan_execute.py`
- Test: `tests/test_plan_execute.py`

**Interfaces:**
- Produces:
  - `_wants_law_retrieve(text: str) -> bool`
  - `_wants_case_retrieve(text: str) -> bool`
  - `_past_has_tool(past_steps, tool_name) -> bool`
  - `_plan_mentions_law_retrieve(plan: list) -> bool` / `_plan_mentions_case_retrieve`
  - `_ensure_retrieve_steps(objective: str, plan: list, past_steps: list | None, *, max_steps: int) -> list[str]`
- Call sites: after `_plan_llm` returns; after replan `continue` assigns new `plan`; after resume replan assigns `plan`.

- [ ] **Step 1: Write failing unit tests (pure functions)**

```python
from agents.plan_execute import _ensure_retrieve_steps

def test_ensure_retrieve_steps_injects_law_when_article_query(self):
    plan = ["直接给出结论"]
    out = _ensure_retrieve_steps(
        "请检索劳动合同法第64条并回答",
        plan,
        [],
        max_steps=8,
    )
    self.assertTrue(any("法规" in s or "法条" in s for s in out[:2]))
    self.assertLessEqual(len(out), 8)

def test_ensure_retrieve_steps_skips_if_retrieve_law_done(self):
    plan = ["给出结论"]
    past = [{"tool": "retrieve_law", "observation": "..."}]
    out = _ensure_retrieve_steps(
        "劳动合同法第六十四条",
        plan,
        past,
        max_steps=8,
    )
    self.assertEqual(out, ["给出结论"])

def test_ensure_retrieve_steps_injects_case_when_requested(self):
    plan = ["分析争议焦点"]
    out = _ensure_retrieve_steps(
        "帮我检索类似案例作为参考",
        plan,
        [],
        max_steps=8,
    )
    self.assertTrue(any("类案" in s or "案例" in s for s in out[:2]))
```

- [ ] **Step 2: Run — expect FAIL (import/missing)**

Run: `PYTHONPATH=server python3 -m unittest tests.test_plan_execute.TestPlanExecute.test_ensure_retrieve_steps_injects_law_when_article_query -v`

- [ ] **Step 3: Implement helpers + wire**

```python
_LAW_RETRIEVE_STEP = "检索相关法规并整理可引用条文"
_CASE_RETRIEVE_STEP = "检索相关类案并整理可引用案例"

def _wants_law_retrieve(text: str) -> bool:
    t = text or ""
    if any(k in t for k in ("法条", "法规", "法律依据", "检索法")):
        return True
    if "第" in t and "条" in t:
        return True
    if any(k in t for k in ("依据", "引用")) and any(
        k in t for k in ("法", "条例", "规定")
    ):
        return True
    return False

def _wants_case_retrieve(text: str) -> bool:
    t = text or ""
    return any(k in t for k in ("类案", "案例", "判例", "检索案"))

def _past_has_tool(past_steps, name: str) -> bool:
    return any((p or {}).get("tool") == name for p in (past_steps or []))

def _plan_mentions_law_retrieve(plan: list) -> bool:
    blob = "\n".join(plan or [])
    return any(k in blob for k in ("检索", "法规", "法条", "法律")) and (
        "法规" in blob or "法条" in blob or "法律" in blob
    )

def _plan_mentions_case_retrieve(plan: list) -> bool:
    blob = "\n".join(plan or [])
    return any(k in blob for k in ("类案", "案例", "判例"))

def _ensure_retrieve_steps(
    objective: str,
    plan: list,
    past_steps=None,
    *,
    max_steps: int = MAX_PLAN_STEPS,
) -> list:
    steps = [s for s in (plan or []) if isinstance(s, str) and s.strip()]
    inject: list = []
    if (
        _wants_law_retrieve(objective)
        and not _past_has_tool(past_steps, "retrieve_law")
        and not _plan_mentions_law_retrieve(steps)
    ):
        inject.append(_LAW_RETRIEVE_STEP)
    if (
        _wants_case_retrieve(objective)
        and not _past_has_tool(past_steps, "retrieve_case")
        and not _plan_mentions_case_retrieve(steps)
    ):
        inject.append(_CASE_RETRIEVE_STEP)
    if not inject:
        return steps[:max_steps]
    # dedupe if identical string already present
    merged = inject + [s for s in steps if s not in inject]
    return merged[:max_steps]
```

Wire after planning:

```python
# after plan = _plan_llm(...)
plan = _ensure_retrieve_steps(objective, plan, past_steps, max_steps=max_plan_steps)
emit_step(...)

# after decision continue:
plan = list(decision.get("plan") or [])
plan = _ensure_retrieve_steps(objective, plan, past_steps, max_steps=max_plan_steps)
```

Use the same `objective` string already available in `run_plan_execute` (include user_supplement in blob if resume path has it — pass `f"{objective}\n{user_supplement}"` when applicable).

- [ ] **Step 4: Integration-style test — planner returns no retrieve, injection forces law step then executor runs**

```python
def test_injected_law_step_runs_retrieve(self):
    def write_llm(system, user, hist=None):
        s = system or ""
        if "步骤列表" in s or "规划" in s:
            return '{"plan":["直接回答非全日制要点"]}'
        if "选一个工具" in s:
            # first step should be injected retrieve
            return '{"tool":"retrieve_law","args":{"query":"劳动合同法第六十四条"}}'
        return '{"action":"response","response":"依据《中华人民共和国劳动合同法》第六十四条……"}'

    def retrieve(query, scopes=None):
        return {
            "laws": "…",
            "law_citations": [
                {
                    "title": "中华人民共和国劳动合同法",
                    "article": "第六十四条",
                    "file_id": "f1",
                }
            ],
            "case_citations": [],
        }

    out = run_plan_execute(
        objective="请检索劳动合同法第64条并引用法条回答非全日制用工要点",
        messages=[],
        write_llm=write_llm,
        retrieve_fn=retrieve,
    )
    self.assertEqual(out["status"], "complete")
    tools = [p.get("tool") for p in out.get("past_steps") or []]
    self.assertIn("retrieve_law", tools)
    self.assertTrue(out.get("citations"))
```

- [ ] **Step 5: Run all related tests**

Run: `PYTHONPATH=server python3 -m unittest tests.test_plan_execute tests.test_kb_retrieve tests.test_kb_store_title -v`  
Expected: PASS

---

### Task 5: Live smoke (manual / script)

**Files:** none required (optional one-off script; do not commit secrets)

- [ ] **Step 1:** Ensure MCP on `:8001`, login as `director` / `ChangeMe123!`

- [ ] **Step 2:** `POST /api/orchestrate` with  
  `{"user_text":"请检索劳动合同法第64条并引用法条回答非全日制用工要点","stream":false}`  
  Assert: `citations[0].file_id` non-empty; `past_steps` includes `retrieve_law`.

- [ ] **Step 3:** In UI hard-refresh: answer shows clickable cite-inline / cite-list; preview opens.

---

## Spec coverage self-check

| Spec section | Task |
|--------------|------|
| 3.1–3.2 file_id resolve order | Task 2 |
| 3.3 FTS optional | Covered by Task 2 enrich (no FTS change required) |
| 3.4 tests | Task 1–2 |
| 4 Prompt | Task 3 |
| 5 Plan injection | Task 4 |
| 8 Acceptance | Task 4 integration + Task 5 |
| Non-goal hard gate | Not implemented |

## Placeholder scan

None intentional. Commit steps deferred to user request per repo rules.
