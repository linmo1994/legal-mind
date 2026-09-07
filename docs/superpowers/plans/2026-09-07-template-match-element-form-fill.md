# Template Match + Element-Form Word Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the user asks to draft a legal document, auto-match the best KB template, fill 要素式 Word tables (placeholders + label→right cell) with case+user elements, and fall back to free `draft_doc` drafting if unmatched.

**Architecture:** Extend `kb_template_resolve` with scored `match_template`. Add `docx_form_fill` to scan/fill `python-docx` tables and emit new docx bytes. Wire both into PnE `draft_doc` via `tool_ctx.kb_store` + existing `case_context` / `file_service`. Element dict: rules first, optional LLM JSON completion; missing → `【待补充】`.

**Tech Stack:** Python 3, `python-docx`, existing `KbStore` / `FileService`, PnE (`plan_execute` + `pe_tools`), unittest.

**Spec:** `docs/superpowers/specs/2026-09-07-template-match-element-form-fill-design.md`

---

## File map

| File | Responsibility |
|------|----------------|
| Create `server/docx_form_fill.py` | Slot scan, element fill into tables, return docx bytes |
| Modify `server/kb_template_resolve.py` | `match_template`, doc-type/cause boosts, threshold 40 |
| Modify `server/agents/pe_tools.py` | `draft_doc`: match → form fill or text+LLM or free draft |
| Modify `server/agents/plan_execute.py` | Pass `kb_store` in `tool_ctx` |
| Modify `server/agents/orchestrator.py` | Pass `kb_store` into `run_plan_execute` |
| Modify `server/http_api_extra.py` | Pass `mcp_server.kb_store` into orchestrate |
| Create `tests/test_docx_form_fill.py` | Table placeholder + label-right + 【待补充】 |
| Modify `tests/test_kb_template_resolve.py` | `match_template` score / threshold / meta boost |
| Modify `tests/test_pe_tools.py` | `draft_doc` match / form / fallback paths |

---

### Task 1: `match_template` in kb_template_resolve

**Files:**
- Modify: `server/kb_template_resolve.py`
- Test: `tests/test_kb_template_resolve.py`

- [ ] **Step 1: Write failing tests for match_template**

Append to `tests/test_kb_template_resolve.py`:

```python
from kb_template_resolve import match_template, MATCH_SCORE_THRESHOLD

class TestMatchTemplate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kb = KbStore(os.path.join(self.tmp.name, "kb.db"))
        self.kb.ensure_schema()
        self.kb.create_document(
            id="t1",
            doc_type="template",
            file_id="f1",
            title="民间借贷纠纷起诉状",
            status="ready",
            meta={
                "template_name": "民间借贷纠纷起诉状",
                "document_type": "起诉状",
                "case_category": "民事",
                "validity": "有效",
            },
            created_by="u",
        )
        self.kb.create_document(
            id="t2",
            doc_type="template",
            file_id="f2",
            title="劳动争议仲裁申请书",
            status="ready",
            meta={
                "template_name": "劳动争议仲裁申请书",
                "document_type": "申请书",
                "validity": "有效",
            },
            created_by="u",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_match_picks_lending_complaint(self):
        hit = match_template(self.kb, "请写一份民间借贷纠纷起诉状")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["document_id"], "t1")
        self.assertEqual(hit["name"], "民间借贷纠纷起诉状")
        self.assertGreaterEqual(hit["score"], MATCH_SCORE_THRESHOLD)
        self.assertEqual(hit["file_id"], "f1")

    def test_match_below_threshold_returns_none(self):
        hit = match_template(self.kb, "今天天气怎么样")
        self.assertIsNone(hit)

    def test_document_type_boost(self):
        hit = match_template(self.kb, "起诉状 民间借贷")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["meta"].get("document_type"), "起诉状")
```

- [ ] **Step 2: Run tests — expect fail**

Run: `PYTHONPATH=server python3 -m pytest tests/test_kb_template_resolve.py::TestMatchTemplate -q --tb=short`  
Expected: FAIL (`match_template` / `MATCH_SCORE_THRESHOLD` missing)

- [ ] **Step 3: Implement match_template**

Add to `server/kb_template_resolve.py`:

```python
MATCH_SCORE_THRESHOLD = 40

_DOC_TYPE_HINTS = (
    ("起诉状", "起诉状"),
    ("答辩状", "答辩状"),
    ("申请书", "申请书"),
    ("判决书", "判决书"),
    ("调解书", "调解书"),
    ("协议书", "协议书"),
)


def _infer_doc_type_from_query(query: str) -> str:
    q = query or ""
    for needle, label in _DOC_TYPE_HINTS:
        if needle in q:
            return label
    return ""


def score_template_candidate(query: str, doc: dict) -> int:
    meta = doc.get("meta") or {}
    name = _display_name(doc)
    score = _score_match(query, name)
    hint = _infer_doc_type_from_query(query)
    dtype = (meta.get("document_type") or "").strip()
    if hint and dtype and hint == dtype:
        score += 25
    # light cause overlap already partially in _score_match substrings
    return score


def match_template(kb_store, query: str, *, limit: int = 200) -> Optional[dict]:
    """Return best usable template hit above MATCH_SCORE_THRESHOLD, or None.

    Hit shape: {name, score, document_id, file_id, meta}
    """
    if kb_store is None:
        return None
    q = (query or "").strip()
    if not q:
        return None
    docs = [
        d
        for d in kb_store.list_documents(doc_type="template", limit=limit, offset=0)
        if _is_usable(d)
    ]
    best = None
    best_score = 0
    for doc in docs:
        score = score_template_candidate(q, doc)
        if score > best_score:
            best_score = score
            best = doc
    if best is None or best_score < MATCH_SCORE_THRESHOLD:
        return None
    return {
        "name": _display_name(best),
        "score": best_score,
        "document_id": best.get("id"),
        "file_id": best.get("file_id"),
        "meta": dict(best.get("meta") or {}),
    }
```

Keep `find_template_doc` / `resolve_template_text` unchanged for compatibility.

- [ ] **Step 4: Run tests — expect pass**

Run: `PYTHONPATH=server python3 -m pytest tests/test_kb_template_resolve.py -q --tb=short`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/kb_template_resolve.py tests/test_kb_template_resolve.py
git commit -m "feat(kb): scored match_template for document templates"
```

---

### Task 2: docx_form_fill — scan slots + fill tables

**Files:**
- Create: `server/docx_form_fill.py`
- Create: `tests/test_docx_form_fill.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_docx_form_fill.py`:

```python
import io
import unittest
from docx import Document

from docx_form_fill import (
    PLACEHOLDER_MISSING,
    fill_docx_bytes,
    scan_slots_from_document,
)


def _doc_with_placeholder_and_label():
    doc = Document()
    t1 = doc.add_table(rows=1, cols=1)
    t1.cell(0, 0).text = "原告：{原告姓名}"
    t2 = doc.add_table(rows=1, cols=2)
    t2.cell(0, 0).text = "被告"
    t2.cell(0, 1).text = ""
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class TestDocxFormFill(unittest.TestCase):
    def test_scan_finds_placeholder_and_label_right(self):
        raw = _doc_with_placeholder_and_label()
        doc = Document(io.BytesIO(raw))
        slots = scan_slots_from_document(doc)
        keys = {s["key"] for s in slots}
        self.assertIn("原告姓名", keys)
        self.assertIn("被告", keys)
        modes = {s["key"]: s["mode"] for s in slots}
        self.assertEqual(modes["原告姓名"], "placeholder")
        self.assertEqual(modes["被告"], "label_right")

    def test_fill_writes_values_and_missing_marker(self):
        raw = _doc_with_placeholder_and_label()
        out = fill_docx_bytes(raw, {"原告姓名": "张三"})
        doc = Document(io.BytesIO(out))
        self.assertIn("张三", doc.tables[0].cell(0, 0).text)
        self.assertIn(PLACEHOLDER_MISSING, doc.tables[1].cell(0, 1).text)
        self.assertNotIn("{原告姓名}", doc.tables[0].cell(0, 0).text)
```

- [ ] **Step 2: Run tests — expect fail**

Run: `PYTHONPATH=server python3 -m pytest tests/test_docx_form_fill.py -q --tb=short`  
Expected: FAIL (module missing)

- [ ] **Step 3: Implement docx_form_fill.py**

Create `server/docx_form_fill.py`:

```python
"""Scan and fill 要素式 Word tables (placeholders + label→right cell)."""
from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional

PLACEHOLDER_MISSING = "【待补充】"

# Normalized label text → canonical element key
LABEL_KEYS = {
    "原告": "原告",
    "被告": "被告",
    "申请人": "申请人",
    "被申请人": "被申请人",
    "法定代表人": "法定代表人",
    "委托诉讼代理人": "委托诉讼代理人",
    "身份证号": "身份证号",
    "身份证号码": "身份证号",
    "住所地": "住所地",
    "住址": "住所地",
    "联系电话": "联系电话",
    "诉讼请求": "诉讼请求",
    "事实与理由": "事实与理由",
    "事实和理由": "事实与理由",
}

_PLACEHOLDER_RES = (
    re.compile(r"\{([^{}]+)\}"),
    re.compile(r"\{\{([^{}]+)\}\}"),
    re.compile(r"【([^【】]+)】"),
)


def _norm_label(text: str) -> str:
    t = re.sub(r"\s+", "", (text or "").strip())
    t = t.strip("：:．.、")
    return t


def _cell_empty(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if re.fullmatch(r"[_＿…\-\s]+", t):
        return True
    if t in ("【待补充】", "（待填写）", "(待填写)"):
        return True
    return False


def scan_slots_from_document(doc) -> List[Dict[str, Any]]:
    slots: List[Dict[str, Any]] = []
    seen = set()
    for ti, table in enumerate(doc.tables):
        for ri, row in enumerate(table.rows):
            cells = row.cells
            for ci, cell in enumerate(cells):
                text = cell.text or ""
                for rx in _PLACEHOLDER_RES:
                    for m in rx.finditer(text):
                        key = _norm_label(m.group(1))
                        if not key or key in ("待补充",):
                            continue
                        # Skip if key is only a section header style placeholder duplicate
                        sig = ("placeholder", ti, ri, ci, key)
                        if sig in seen:
                            continue
                        seen.add(sig)
                        slots.append(
                            {
                                "key": key,
                                "mode": "placeholder",
                                "table_i": ti,
                                "row_i": ri,
                                "cell_i": ci,
                                "raw": m.group(0),
                            }
                        )
            # label → right cell (2+ cols)
            if len(cells) >= 2:
                left = _norm_label(cells[0].text or "")
                key = LABEL_KEYS.get(left)
                if key and _cell_empty(cells[1].text or ""):
                    sig = ("label_right", ti, ri, 1, key)
                    if sig not in seen:
                        seen.add(sig)
                        slots.append(
                            {
                                "key": key,
                                "mode": "label_right",
                                "table_i": ti,
                                "row_i": ri,
                                "cell_i": 1,
                                "label": left,
                            }
                        )
    return slots


def _set_cell_text(cell, value: str) -> None:
    value = value if value is not None else ""
    # Clear paragraphs then set first paragraph text (simple, preserves table)
    if cell.paragraphs:
        cell.paragraphs[0].text = value
        for p in cell.paragraphs[1:]:
            p.text = ""
    else:
        cell.text = value


def fill_document(doc, elements: Dict[str, Any], slots: Optional[List[Dict[str, Any]]] = None):
    slots = slots if slots is not None else scan_slots_from_document(doc)
    elements = elements or {}
    for slot in slots:
        key = slot["key"]
        raw_val = elements.get(key)
        if raw_val is None or str(raw_val).strip() == "":
            val = PLACEHOLDER_MISSING
        else:
            val = str(raw_val).strip()
        ti, ri, ci = slot["table_i"], slot["row_i"], slot["cell_i"]
        if ti >= len(doc.tables):
            continue
        table = doc.tables[ti]
        if ri >= len(table.rows):
            continue
        row = table.rows[ri]
        if ci >= len(row.cells):
            continue
        cell = row.cells[ci]
        if slot["mode"] == "placeholder":
            text = cell.text or ""
            raw = slot.get("raw") or ""
            if raw and raw in text:
                _set_cell_text(cell, text.replace(raw, val, 1))
            else:
                # replace any {key} / 【key】 occurrence
                new_text = text
                for rx in _PLACEHOLDER_RES:
                    new_text = rx.sub(
                        lambda m: val if _norm_label(m.group(1)) == key else m.group(0),
                        new_text,
                        count=1,
                    )
                _set_cell_text(cell, new_text)
        else:
            _set_cell_text(cell, val)
    return doc


def fill_docx_bytes(docx_bytes: bytes, elements: Dict[str, Any]) -> bytes:
    from docx import Document

    doc = Document(io.BytesIO(docx_bytes or b""))
    fill_document(doc, elements)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def has_fillable_slots(docx_bytes: bytes) -> bool:
    from docx import Document

    try:
        doc = Document(io.BytesIO(docx_bytes or b""))
    except Exception:
        return False
    return bool(scan_slots_from_document(doc))
```

- [ ] **Step 4: Run tests — expect pass**

Run: `PYTHONPATH=server python3 -m pytest tests/test_docx_form_fill.py -q --tb=short`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/docx_form_fill.py tests/test_docx_form_fill.py
git commit -m "feat(docx): scan and fill element-form Word table slots"
```

---

### Task 3: Element dict builder (rules + optional LLM)

**Files:**
- Create helpers in `server/docx_form_fill.py` (or `server/element_dict.py` if preferred — keep in `docx_form_fill.py` for YAGNI unless file grows past ~250 lines)
- Modify: `tests/test_docx_form_fill.py`

- [ ] **Step 1: Write failing tests**

```python
from docx_form_fill import build_element_dict

class TestElementDict(unittest.TestCase):
    def test_rules_extract_plaintiff_defendant(self):
        text = "原告张三，被告李四。请求还款。"
        d = build_element_dict(text, slot_keys=["原告", "被告", "诉讼请求"], write_llm=None)
        self.assertEqual(d.get("原告"), "张三")
        self.assertEqual(d.get("被告"), "李四")

    def test_llm_fills_missing_keys(self):
        def write_llm(system, user, hist=None):
            return '{"住所地":"本市某路1号"}'

        d = build_element_dict(
            "原告张三",
            slot_keys=["原告", "住所地"],
            write_llm=write_llm,
        )
        self.assertEqual(d.get("原告"), "张三")
        self.assertEqual(d.get("住所地"), "本市某路1号")
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTHONPATH=server python3 -m pytest tests/test_docx_form_fill.py::TestElementDict -q --tb=short`  
Expected: FAIL

- [ ] **Step 3: Implement build_element_dict**

Append to `server/docx_form_fill.py`:

```python
import json

_PARTY_PATTERNS = (
    ("原告", re.compile(r"原告[:：\s]*([^\s，。,；;]{1,30})")),
    ("被告", re.compile(r"被告[:：\s]*([^\s，。,；;]{1,30})")),
    ("申请人", re.compile(r"申请人[:：\s]*([^\s，。,；;]{1,30})")),
    ("被申请人", re.compile(r"被申请人[:：\s]*([^\s，。,；;]{1,30})")),
)


def build_element_dict(
    source_text: str,
    *,
    slot_keys: Optional[List[str]] = None,
    write_llm=None,
) -> Dict[str, Any]:
    text = source_text or ""
    out: Dict[str, Any] = {}
    for key, rx in _PARTY_PATTERNS:
        if slot_keys is not None and key not in slot_keys:
            continue
        m = rx.search(text)
        if m:
            out[key] = m.group(1).strip()
    # 身份证
    if slot_keys is None or "身份证号" in slot_keys:
        m = re.search(r"身份证[号码]*[:：\s]*([0-9Xx]{15,18})", text)
        if m:
            out["身份证号"] = m.group(1)
    missing = []
    if slot_keys:
        missing = [k for k in slot_keys if k not in out or not str(out.get(k) or "").strip()]
    if write_llm and missing:
        try:
            raw = write_llm(
                "你是法律文书要素抽取助手。只输出一个 JSON 对象，键为给定字段。"
                "未知填 null，禁止编造当事人身份信息。",
                "字段：" + "、".join(missing) + "\n\n材料：\n" + text[:8000],
            )
            raw = (raw or "").strip()
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                data = json.loads(raw[start : end + 1])
                if isinstance(data, dict):
                    for k in missing:
                        v = data.get(k)
                        if v is not None and str(v).strip() and str(v).strip().lower() != "null":
                            out[k] = str(v).strip()
        except Exception as exc:
            print(f"[docx_form_fill] element llm failed: {exc}")
    return out
```

- [ ] **Step 4: Run tests — expect pass**

Run: `PYTHONPATH=server python3 -m pytest tests/test_docx_form_fill.py -q --tb=short`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/docx_form_fill.py tests/test_docx_form_fill.py
git commit -m "feat(docx): build element dict from text with optional LLM"
```

---

### Task 4: Wire kb_store into PnE tool_ctx

**Files:**
- Modify: `server/agents/plan_execute.py` (`run_plan_execute` signature + `tool_ctx`)
- Modify: `server/agents/orchestrator.py` (`run_plan_execute(...)` call)
- Modify: `server/http_api_extra.py` (`handle_orchestrate` → `run_orchestrate`)

- [ ] **Step 1: Add kb_store through the stack**

In `run_plan_execute`:

```python
def run_plan_execute(
    ...
    kb_store=None,
    ...
):
    tool_ctx = {
        ...
        "kb_store": kb_store,
    }
```

In `run_orchestrate` / PE call: `kb_store=kb_store` (add param to `run_orchestrate`).

In `handle_orchestrate`:

```python
kb_store = getattr(mcp_server, "kb_store", None)
...
result = run_orchestrate(..., kb_store=kb_store)
```

- [ ] **Step 2: Smoke import / existing PE tests**

Run: `PYTHONPATH=server python3 -m pytest tests/test_plan_execute.py tests/test_pe_tools.py -q --tb=short`  
Expected: PASS (backward compatible defaults)

- [ ] **Step 3: Commit**

```bash
git add server/agents/plan_execute.py server/agents/orchestrator.py server/http_api_extra.py
git commit -m "feat(pe): pass kb_store into plan-execute tool context"
```

---

### Task 5: draft_doc — match + form fill + fallbacks

**Files:**
- Modify: `server/agents/pe_tools.py` (`draft_doc` branch, helpers)
- Modify: `tests/test_pe_tools.py`

- [ ] **Step 1: Write failing PE tool tests**

Add tests that use in-memory fake kb + fake file_service returning docx bytes from Task 2 helper.

```python
def test_draft_doc_fills_matched_element_template(self):
    # FakeKb with template meta; FakeFS.get_file returns path/bytes; get_file_bytes or read file_path
    ...
    out = run_tool("draft_doc", {"prompt": "请写民间借贷纠纷起诉状，原告张三被告李四"}, ctx)
    self.assertIn("模版", out["observation"])
    self.assertIsNotNone(out.get("artifact"))
    self.assertIn("file_id", out["artifact"])

def test_draft_doc_unmatched_mentions_fallback(self):
    out = run_tool("draft_doc", {"prompt": "随便写点闲聊"}, {
        "write_llm": lambda s, u, h=None: "自由起草正文",
        "kb_store": empty_or_unrelated_kb,
        "file_service": fs,
    })
    self.assertIn("未命中模版", out["observation"])
```

Implement fakes consistent with `file_service.get_file` → `file_path` readable bytes, or add `get_file_bytes` on FakeFS used only in tests; production path:

```python
info = file_service.get_file(file_id)
path = info.get("file_path")
with open(path, "rb") as f:
    raw = f.read()
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTHONPATH=server python3 -m pytest tests/test_pe_tools.py -k draft_doc -q --tb=short`  
Expected: FAIL on new assertions

- [ ] **Step 3: Implement draft_doc branching**

Replace `draft_doc` body in `pe_tools.py` with logic:

1. Build `prompt` (+ `case_context` via `format_user_with_case_context`) as today.
2. `query = (ctx.objective or prompt)`
3. `hit = match_template(ctx.get("kb_store"), query)` if kb_store else None
4. If hit and file_service:
   - load docx bytes from `hit["file_id"]`
   - if `has_fillable_slots(raw)`:
     - `slots = scan...` / `elements = build_element_dict(prompt, slot_keys=[...], write_llm=write_llm)`
     - `filled = fill_docx_bytes(raw, elements)`
     - save via `file_service.save_file(filled, filename, session_id=..., description="plan_execute draft_doc")`
     - observation: `已根据模版《{name}》填写要素式文书…`
     - return artifact
   - else:
     - `resolve_template_text` or file text → LLM fill with system noting template → `_export_docx_artifact`
     - observation includes `已套用模版《{name}》（非表格填槽）`
5. If no hit:
   - existing free LLM draft + export
   - prefix observation with `未命中模版库，已按说明自由起草。\n\n`

Helper `_load_template_docx_bytes(file_service, file_id) -> Optional[bytes]`.

- [ ] **Step 4: Run PE + form + resolve tests**

Run: `PYTHONPATH=server python3 -m pytest tests/test_pe_tools.py tests/test_docx_form_fill.py tests/test_kb_template_resolve.py -q --tb=short`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/agents/pe_tools.py tests/test_pe_tools.py
git commit -m "feat(pe): draft_doc matches KB templates and fills element forms"
```

---

### Task 6: End-to-end sanity + docs touch-up

**Files:**
- Optionally note in spec that plan path is `docs/superpowers/plans/2026-09-07-template-match-element-form-fill.md`
- Manual checklist only (no new product UI)

- [ ] **Step 1: Run broader regression**

Run:

```bash
PYTHONPATH=server python3 -m pytest \
  tests/test_kb_template_resolve.py \
  tests/test_docx_form_fill.py \
  tests/test_pe_tools.py \
  tests/test_plan_execute.py \
  tests/test_orchestrate.py -q --tb=line
```

Expected: PASS (or only pre-existing failures unrelated to this work)

- [ ] **Step 2: Manual smoke (local MCP)**

1. Upload/ensure KB has 要素式 docx with `{原告姓名}` or 原告|空白格  
2. Select a case, ask「请写一份民间借贷纠纷起诉状」  
3. Expect process/observation mentions matched template; Word download has filled cells  
4. Ask unrelated draft with empty/unrelated templates →「未命中模版库」

- [ ] **Step 3: Commit any test fixes**

```bash
git add -A
git status
git commit -m "test: harden template match and form-fill coverage"
```

(Only if there are changes.)

---

## Spec coverage self-check

| Spec requirement | Task |
|------------------|------|
| Auto highest-score match | Task 1, 5 |
| Threshold + meta document_type boost | Task 1 |
| Case + user merge in prompt / element source | Task 5 (existing case_context + prompt) |
| 【待补充】 | Task 2, 3 |
| Placeholder + label→right | Task 2 |
| Unmatched → free draft + message | Task 5 |
| Non-slot matched template → text+LLM path | Task 5 |
| PnE `draft_doc` mount | Task 4–5 |
| No approval / no user pick | N/A (out of scope) |
| python-docx fill preserve tables | Task 2 |

## Placeholder scan

No TBD / “add error handling later” left in steps; fakes and APIs are named consistently (`match_template`, `fill_docx_bytes`, `build_element_dict`, `PLACEHOLDER_MISSING`).
