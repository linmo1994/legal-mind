# 单次 LLM 法律意图门闸 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 多轮编排入口用一次短 LLM 调用输出 `non_legal` 或 `legal`+细意图；非法律直接回答并提示更擅长法律；法律映射现有 plan；失败回退关键词门闸。

**Architecture:** 新建 `intent_gate.py`（解析 + 分类调用）；`run_orchestrate` 在启发式/LangGraph 之前跑门闸；`non_legal` 短路径用 `write_llm`；`legal` 用 `plan_for_intent(intent)`（复用/抽取 `heuristic_plan` 映射）。分类与写作共用传入的 `write_llm`（或同签名 `classify_llm`），假 LLM 可计数断言仅一次分类调用。

**Tech Stack:** 现有 `complete_chat` / `write_llm`、unittest、`agents.orchestrator`。

**Spec:** `docs/superpowers/specs/2026-09-05-legal-intent-gate-design.md`

## Global Constraints

- 单次分类 LLM，禁止二次细分调用
- 失败 → `classify_intent` + `heuristic_plan`
- 不自动 commit（除非用户要求）
- 测试：`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=server python3 -m unittest …`

## File map

| File | Responsibility |
|------|----------------|
| `server/agents/intent_gate.py` | Prompt、解析 JSON、`classify_domain_intent`、收尾句常量 |
| `server/agents/orchestrator.py` | `plan_for_intent`；`run_orchestrate` 前置门闸；non_legal 路径 |
| `tests/test_intent_gate.py` | 解析与门闸单测 |
| `tests/test_orchestrate.py` | 集成：非法律不 retrieve；法律 law_search；坏 JSON 回退 |

---

### Task 1: `intent_gate` 解析与契约

**Files:**
- Create: `server/agents/intent_gate.py`
- Test: `tests/test_intent_gate.py`

**Interfaces:**

```python
LEGAL_INTENTS = ("law_search", "case_search", "doc_writing", "contract_review", "legal_analysis")
NON_LEGAL_CLOSING = "另外说明：我更擅长解答法律法规、类案检索与法律文书相关问题，有这类需求随时问我。"

CLASSIFY_SYSTEM = """你是意图分类器。只输出一个 JSON 对象，不要其它文字。
非法律问题：{"domain":"non_legal"}
法律相关（法规/类案/文书/合同审查/案情分析）：{"domain":"legal","intent":"<枚举>"}
intent 只能是：law_search, case_search, doc_writing, contract_review, legal_analysis。"""

def parse_gate_payload(raw: str) -> dict | None:
    """Extract first JSON object; validate domain/intent; return None if invalid."""

def classify_domain_intent(llm_fn, user_text: str, messages=None) -> dict:
    """
    llm_fn(system, user, hist=None) -> str
    Returns {"domain":"non_legal"} or {"domain":"legal","intent":"..."}.
    Raises or returns None-path: caller handles — prefer return None on failure.
    """
```

推荐：`classify_domain_intent` 失败时返回 `None`（不抛），由 orchestrator 兜底。

- [ ] **Step 1: Failing tests**

```python
# tests/test_intent_gate.py
from agents.intent_gate import parse_gate_payload, classify_domain_intent, NON_LEGAL_CLOSING

class TestIntentGate(unittest.TestCase):
    def test_parse_non_legal(self):
        self.assertEqual(parse_gate_payload('{"domain":"non_legal"}')["domain"], "non_legal")

    def test_parse_legal_intent(self):
        p = parse_gate_payload('思考\n{"domain":"legal","intent":"law_search"}')
        self.assertEqual(p["intent"], "law_search")

    def test_parse_invalid_intent(self):
        self.assertIsNone(parse_gate_payload('{"domain":"legal","intent":"foo"}'))

    def test_classify_calls_llm_once(self):
        calls = []
        def llm(system, user, hist=None):
            calls.append(1)
            return '{"domain":"non_legal"}'
        out = classify_domain_intent(llm, "今天天气怎么样")
        self.assertEqual(out["domain"], "non_legal")
        self.assertEqual(len(calls), 1)
```

- [ ] **Step 2: Run FAIL**

- [ ] **Step 3: Implement `intent_gate.py`**

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit if asked**

---

### Task 2: `plan_for_intent` + `run_orchestrate` 门闸

**Files:**
- Modify: `server/agents/orchestrator.py`
- Test: `tests/test_orchestrate.py`

**行为：**

1. 抽取 `plan_for_intent(intent: str) -> dict`：把现有 `heuristic_plan` 里按 intent 分支提出来；`heuristic_plan` 改为 `plan_for_intent(classify_intent(text))`。
2. `run_orchestrate` 开头（在 `llm` 编排计划之前）：
   - 若 `write_llm` 可用：`gate = classify_domain_intent(write_llm, user_text, messages)`
   - `gate is None` → 现有启发式
   - `domain == non_legal` → 短路径（Task 3 可一并做）
   - `domain == legal` → `local_plan = plan_for_intent(gate["intent"])`，**跳过**后续关键词/旧 orch-llm plan（或仅当 gate 成功时覆盖 heuristic）
3. 计数：分类只用 `write_llm` 一次；non_legal 回答再调一次 writing（允许，不算「细分」）。

**注意：** 当前 `handle_orchestrate` 传 `llm=None`，计划本就靠 heuristic。门闸后法律路径用 `plan_for_intent`，不再依赖关键词（除非兜底）。

- [ ] **Step 1: Test** — mock `write_llm` 第一次返回 legal law_search JSON，retrieve 被调用且 scopes `("law",)`；第二次若被调用则为 specialist 写作

```python
def test_llm_gate_law_search_uses_kb(self):
    calls = {"n": 0, "retrieve": []}
    def write_llm(system, user, hist=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"domain":"legal","intent":"law_search"}'
        return "unused"
    def retrieve(q, scopes=None):
        calls["retrieve"].append(tuple(scopes or ()))
        return {"laws": "劳动合同法第六十四条", "cases": "", "law_citations": [], "case_citations": []}
    result = run_orchestrate(
        user_text="检索劳动合同法第64条",
        messages=[],
        llm=None,
        retrieve_fn=retrieve,
        write_llm=write_llm,
        skills=[],
    )
    self.assertEqual(calls["retrieve"], [("law",)])
    self.assertEqual(result.get("plan", {}).get("intent"), "law_search")
```

- [ ] **Step 2–4: Implement + PASS existing orchestrate tests**（`write_llm=None` 时行为不变：纯关键词）

- [ ] **Step 5: Commit if asked**

---

### Task 3: `non_legal` 短路径 + 收尾句

**Files:**
- Modify: `orchestrator.py`（`_run_non_legal` 或内联）
- Test: `tests/test_orchestrate.py`

```python
def test_llm_gate_non_legal_skips_retrieve(self):
    retrieve_calls = []
    def write_llm(system, user, hist=None):
        if "分类" in system or "JSON" in system or "intent" in system.lower():
            return '{"domain":"non_legal"}'
        return "今天适合出门。"
    def retrieve(q, scopes=None):
        retrieve_calls.append(q)
        return {"laws": "x", "cases": "y"}
    result = run_orchestrate(..., write_llm=write_llm, retrieve_fn=retrieve)
    self.assertFalse(retrieve_calls)
    self.assertIn("更擅长", result["visible_text"])
    self.assertIn("今天适合出门", result["visible_text"])
```

实现要点：

- non_legal system：「简洁回答用户；不要编造法律意见。」
- 追加 `NON_LEGAL_CLOSING`（若正文已包含「更擅长」则不重复）
- `plan={"type":"plan","intent":"non_legal","retrieval_scopes":[],"steps":[]}` 或单步占位
- `emit_step` 可选 `classify`
- `citations=[]`

- [ ] **Step 1–4: TDD + PASS**

- [ ] **Step 5: Commit if asked**

---

### Task 4: 坏 JSON / 异常兜底

**Test:**

```python
def test_llm_gate_bad_json_falls_back_to_keyword(self):
    def write_llm(system, user, hist=None):
        if "JSON" in system or "分类" in system:
            return "不是json"
        return "ok"
    # 「你好」关键词 → chitchat，不 retrieve
    ...
```

- [ ] Implement：`classify_domain_intent` 返回 None；orchestrator 用 `heuristic_plan`
- [ ] PASS + 全量 `tests.test_orchestrate tests.test_intent_gate`

---

### Task 5: 回归与 MCP 重启

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=server python3 -m unittest \
  tests.test_intent_gate tests.test_orchestrate -v
```

重启 MCP；手工：非法律一句、法规检索一句。

---

## Spec coverage

| Spec | Task |
|------|------|
| 单次 JSON 契约 | 1 |
| legal → plan | 2 |
| non_legal + 收尾 | 3 |
| 关键词兜底 | 4 |
| 一次分类断言 | 1–2 |

## Self-review

- `write_llm` 兼分类与写作：用 system 内容区分；测试按调用序或 system 关键字分支。  
- `llm=` 编排器计划（legacy）若将来启用：门闸仍应先于它；本期 `handle_orchestrate` 为 `llm=None`。  
- 不强制改 mcp_client UI。
