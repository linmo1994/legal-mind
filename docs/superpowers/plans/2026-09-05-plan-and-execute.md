# Plan-and-Execute 编排环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 法律路径用显式 Plan-and-Execute（自然语言步骤 + 白名单一步一 tool + 有限 Replan + ask_user 续跑），并在多轮对话展示计划面板。

**Architecture:** 新建 `plan_execute.py` 环与 `pe_tools.py` 工具适配；`run_orchestrate` 在 intent gate 判定 legal 后默认进入 PnE（`PLAN_EXECUTE=0` 可关）；旧 LangGraph 仅作不可恢复失败时的 fallback。前端根据响应中的 `plan` / `past_steps` 渲染计划面板，并用 `resume_state` 续跑 ask_user。

**Tech Stack:** Python unittest、现有 `write_llm` / `retrieve_fn` / case_materials、`WorkflowTracer`、`mcp_client.js`

**Spec:** `docs/superpowers/specs/2026-09-05-plan-and-execute-design.md`

## File structure

| File | Responsibility |
|------|----------------|
| Create: `server/agents/pe_tools.py` | 白名单 tool 注册与执行（retrieve_law/case、read_evidence、draft_doc、reason） |
| Create: `server/agents/plan_execute.py` | Planner / Executor / Replanner 环与预算 |
| Modify: `server/agents/orchestrator.py` | legal → PnE；失败 fallback；响应字段 |
| Modify: `server/http_api_extra.py` | 传入 `resume_state`；ask_user 时勿把空助手答当完结（可选跳过 persist） |
| Modify: `server/agents/workflow.py` | `emit` 支持可选 `detail`（计划列表等） |
| Modify: `mcp_client.js` / `mcp_client.html` / CSS | 计划面板；`resume_state`；cache-bust |
| Create: `tests/test_pe_tools.py` | 工具适配单测 |
| Create: `tests/test_plan_execute.py` | 环：happy / ask_user / 预算 / JSON 失败 |
| Modify: `tests/test_orchestrate.py` | legal 走 PnE（mock）；non_legal 不变 |

## Global constraints

- 预算：`MAX_PLAN_STEPS=8`、`MAX_REPLANS=5`、`MAX_TOOL_CALLS=15`（`reason` 计入 tool）
- 一步一 tool；不做步内 ReAct
- 测试：`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 -m unittest …`
- 不自动 `git push`；commit 步骤仅在用户要求提交时执行（本计划仍列出 commit 内容供选用）

---

### Task 1: 白名单 tools（`pe_tools.py`）

**Files:**
- Create: `server/agents/pe_tools.py`
- Test: `tests/test_pe_tools.py`

- [x] **Step 1: Write the failing test**

```python
# tests/test_pe_tools.py
#!/usr/bin/env python3
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from agents.pe_tools import TOOL_NAMES, run_tool  # noqa: E402


class TestPeTools(unittest.TestCase):
    def test_tool_names(self):
        self.assertEqual(
            set(TOOL_NAMES),
            {"retrieve_law", "retrieve_case", "read_evidence", "draft_doc", "reason"},
        )

    def test_retrieve_law_calls_retrieve_fn(self):
        seen = []

        def retrieve(query, scopes=None):
            seen.append((query, tuple(scopes or ())))
            return {"text": "法条摘要", "citations": [{"title": "民法典", "article": "第667条"}]}

        out = run_tool(
            "retrieve_law",
            {"query": "民间借贷利率"},
            ctx={"retrieve_fn": retrieve, "write_llm": None},
        )
        self.assertEqual(seen, [("民间借贷利率", ("law",))])
        self.assertIn("法条摘要", out["observation"])
        self.assertEqual(len(out.get("citations") or []), 1)

    def test_unknown_tool(self):
        out = run_tool("nope", {}, ctx={})
        self.assertIn("unknown", out["observation"].lower())

    def test_reason_uses_write_llm(self):
        def write_llm(system, user, hist=None):
            return "推理结论"

        out = run_tool(
            "reason",
            {"prompt": "分析利率是否合法"},
            ctx={"write_llm": write_llm},
        )
        self.assertEqual(out["observation"], "推理结论")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 -m unittest tests.test_pe_tools -v`  
Expected: FAIL (`ModuleNotFoundError: agents.pe_tools`)

- [x] **Step 3: Write minimal implementation**

```python
# server/agents/pe_tools.py
"""Plan-and-Execute whitelist tools (one call per plan step)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

TOOL_NAMES = (
    "retrieve_law",
    "retrieve_case",
    "read_evidence",
    "draft_doc",
    "reason",
)

OBS_MAX = 6000


def _trim(text: str, limit: int = OBS_MAX) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n…(truncated)"


def run_tool(name: str, args: Optional[Dict[str, Any]], ctx: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Execute one whitelist tool. Returns {observation, citations?, artifact?}."""
    args = args or {}
    ctx = ctx or {}
    name = (name or "").strip()
    if name not in TOOL_NAMES:
        return {"observation": f"unknown tool: {name}", "citations": []}

    retrieve_fn: Optional[Callable] = ctx.get("retrieve_fn")
    write_llm = ctx.get("write_llm")
    citations: List[Dict[str, Any]] = []
    artifact = None

    if name == "retrieve_law":
        query = str(args.get("query") or "").strip() or str(ctx.get("objective") or "")
        if not retrieve_fn:
            return {"observation": "retrieve_fn unavailable", "citations": []}
        raw = retrieve_fn(query, scopes=["law"]) or {}
        citations = list(raw.get("citations") or [])
        return {"observation": _trim(str(raw.get("text") or raw)), "citations": citations}

    if name == "retrieve_case":
        query = str(args.get("query") or "").strip() or str(ctx.get("objective") or "")
        if not retrieve_fn:
            return {"observation": "retrieve_fn unavailable", "citations": []}
        raw = retrieve_fn(query, scopes=["case"]) or {}
        citations = list(raw.get("citations") or [])
        return {"observation": _trim(str(raw.get("text") or raw)), "citations": citations}

    if name == "read_evidence":
        from case_materials import get_case_evidence_text

        file_id = args.get("file_id")
        case_id = ctx.get("case_id")
        case_store = ctx.get("case_store")
        file_service = ctx.get("file_service")
        if not (file_id and case_id and case_store and file_service):
            return {
                "observation": "read_evidence requires case_id, file_id, case_store, file_service",
                "citations": [],
            }
        try:
            text = get_case_evidence_text(case_id, int(file_id), case_store, file_service)
        except Exception as exc:
            return {"observation": f"read_evidence failed: {exc}", "citations": []}
        return {"observation": _trim(text or "(empty)"), "citations": []}

    if name == "draft_doc":
        # Thin wrapper: prefer write_llm with a drafting system prompt; optional template later.
        prompt = str(args.get("prompt") or args.get("instruction") or ctx.get("objective") or "")
        if not write_llm:
            return {"observation": "write_llm unavailable for draft_doc", "citations": []}
        system = (
            "你是法律文书助手。根据用户指示起草文书正文，不要编造未提供的当事人信息。"
        )
        try:
            body = write_llm(system, prompt, ctx.get("messages") or []) or ""
        except Exception as exc:
            return {"observation": f"draft_doc failed: {exc}", "citations": []}
        return {"observation": _trim(body), "citations": [], "artifact": artifact}

    if name == "reason":
        prompt = str(args.get("prompt") or args.get("instruction") or ctx.get("objective") or "")
        if not write_llm:
            return {"observation": "(no write_llm) " + prompt, "citations": []}
        system = "你是法律分析助手。根据给定步骤要求给出简明推理或结论，引用须基于已提供材料。"
        try:
            body = write_llm(system, prompt, ctx.get("messages") or []) or ""
        except Exception as exc:
            return {"observation": f"reason failed: {exc}", "citations": []}
        return {"observation": _trim(body), "citations": []}

    return {"observation": f"unhandled tool: {name}", "citations": []}
```

- [x] **Step 4: Run test to verify it passes**

Run: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 -m unittest tests.test_pe_tools -v`  
Expected: PASS

- [x] **Step 5: Commit (only if user asked to commit)**

```bash
git add server/agents/pe_tools.py tests/test_pe_tools.py
git commit -m "$(cat <<'EOF'
feat(agents): add Plan-and-Execute whitelist tools

EOF
)"
```

---

### Task 2: PnE 环核心（假 LLM）

**Files:**
- Create: `server/agents/plan_execute.py`
- Test: `tests/test_plan_execute.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/test_plan_execute.py
#!/usr/bin/env python3
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from agents.plan_execute import (  # noqa: E402
    MAX_REPLANS,
    MAX_TOOL_CALLS,
    run_plan_execute,
)


class TestPlanExecute(unittest.TestCase):
    def test_happy_path_retrieve_then_response(self):
        # scripted write_llm: planner → executor choose → replan response
        calls = {"n": 0}

        def write_llm(system, user, hist=None):
            calls["n"] += 1
            s = system or ""
            if "规划" in s or "planner" in s.lower() or "步骤列表" in s:
                return '{"plan":["检索民间借贷利率规定","结合材料给出结论"]}'
            if "选择工具" in s or "executor" in s.lower() or "选一个工具" in s:
                return '{"tool":"retrieve_law","args":{"query":"民间借贷利率"}}'
            # replanner
            return '{"action":"response","response":"利率应受保护限度约束。"}'

        def retrieve(query, scopes=None):
            return {"text": "法条…", "citations": [{"title": "民法典"}]}

        out = run_plan_execute(
            objective="借款利率是否合法",
            messages=[],
            write_llm=write_llm,
            retrieve_fn=retrieve,
        )
        self.assertEqual(out["status"], "complete")
        self.assertIn("利率", out["visible_text"])
        self.assertEqual(out["orchestration_mode"], "plan_execute")
        self.assertGreaterEqual(len(out["past_steps"]), 1)
        self.assertTrue(out.get("citations"))

    def test_ask_user_then_resume(self):
        phase = {"p": "plan"}

        def write_llm(system, user, hist=None):
            s = system or ""
            if "步骤列表" in s or "规划" in s:
                return '{"plan":["确认借款金额"]}'
            if "选一个工具" in s:
                return '{"tool":"reason","args":{"prompt":"检查是否有金额"}}'
            if phase["p"] == "plan":
                phase["p"] = "resume"
                return '{"action":"ask_user","question":"借款本金是多少？"}'
            return '{"action":"response","response":"本金按您补充的金额计算。"}'

        first = run_plan_execute(
            objective="分析借贷",
            messages=[],
            write_llm=write_llm,
            retrieve_fn=lambda q, scopes=None: {},
        )
        self.assertEqual(first["status"], "awaiting_user")
        self.assertIn("本金", first["pending_question"])
        resume = first["resume_state"]
        second = run_plan_execute(
            objective="本金10万元",
            messages=[{"role": "user", "content": "本金10万元"}],
            write_llm=write_llm,
            retrieve_fn=lambda q, scopes=None: {},
            resume_state=resume,
        )
        self.assertEqual(second["status"], "complete")
        self.assertIn("本金", second["visible_text"])

    def test_budget_stops(self):
        def write_llm(system, user, hist=None):
            s = system or ""
            if "步骤列表" in s or "规划" in s:
                return '{"plan":["a","b","c"]}'
            if "选一个工具" in s:
                return '{"tool":"reason","args":{"prompt":"x"}}'
            return '{"action":"continue","plan":["keep-going"]}'

        out = run_plan_execute(
            objective="x",
            messages=[],
            write_llm=write_llm,
            retrieve_fn=None,
            max_replans=2,
            max_tool_calls=3,
        )
        self.assertIn(out["status"], ("complete", "error"))
        self.assertLessEqual(out.get("replan_count", 0), 2)
        self.assertLessEqual(out.get("tool_calls_used", 0), 3)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 -m unittest tests.test_plan_execute -v`  
Expected: FAIL (import error)

- [x] **Step 3: Implement `plan_execute.py`**

实现要点（完整实现写入该文件）：

1. 常量：`MAX_PLAN_STEPS=8`、`MAX_REPLANS=5`、`MAX_TOOL_CALLS=15`
2. `_extract_json(text)`：从模型输出中取首个 `{...}`
3. `_plan_llm` / `_exec_llm` / `_replan_llm`：用不同 system 提示；解析失败各重试 1 次
4. `run_plan_execute(...)`：
   - 若 `resume_state`：恢复 `plan/past_steps/counts/objective`；把新 `objective` 当作用户补充并入上下文
   - 否则 planner 生成 plan（截断至 8）
   - `emit_step("plan", "plan", ...)`（若有 detail 支持则带 steps）
   - loop：若无 plan 或超预算 → 强制用 past_steps 让 write_llm 收口 response
   - else execute plan[0] → past_steps → replan
   - ask_user → `status=awaiting_user`，返回 `resume_state` 快照
   - response → complete
5. 返回字段对齐 spec：`visible_text`、`plan`、`past_steps`、`pending_question`、`citations`、`orchestration_mode`、`resume_state`、`status`、`tool_calls_used`、`replan_count`

System 提示关键词必须与测试一致（含「步骤列表」「选一个工具」），或同步改测试字符串。

伪结构：

```python
def run_plan_execute(
    objective: str,
    messages=None,
    write_llm=None,
    retrieve_fn=None,
    file_service=None,
    case_id=None,
    case_store=None,
    skills=None,
    session_id=None,
    resume_state=None,
    max_plan_steps=MAX_PLAN_STEPS,
    max_replans=MAX_REPLANS,
    max_tool_calls=MAX_TOOL_CALLS,
) -> Dict[str, Any]:
    ...
```

Tool ctx 传入：`retrieve_fn`、`write_llm`、`file_service`、`case_id`、`case_store`、`messages`、`objective`。

- [x] **Step 4: Run tests**

Run: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 -m unittest tests.test_plan_execute -v`  
Expected: PASS（若 flaky，收紧假 LLM 分支条件）

- [x] **Step 5: Commit (if requested)**

```bash
git add server/agents/plan_execute.py tests/test_plan_execute.py
git commit -m "$(cat <<'EOF'
feat(agents): add Plan-and-Execute loop with replan and ask_user

EOF
)"
```

---

### Task 3: 接入 `run_orchestrate`

**Files:**
- Modify: `server/agents/orchestrator.py`
- Modify: `tests/test_orchestrate.py`

- [x] **Step 1: Write / extend failing test**

在 `tests/test_orchestrate.py` 增加：

```python
def test_legal_gate_uses_plan_execute_when_enabled(self):
    import os
    os.environ.pop("PLAN_EXECUTE", None)  # default on

    seq = {"n": 0}

    def write_llm(system, user, hist=None):
        seq["n"] += 1
        s = system or ""
        # intent gate first
        if "non_legal" in s or "domain" in s.lower() or "意图" in s or "JSON" in s:
            if seq["n"] <= 2 and "plan" not in s.lower() and "步骤" not in s:
                # gate prompts vary — return legal if looks like gate
                if "domain" in s.lower() or "法律" in s or "non_legal" in s:
                    return '{"domain":"legal","intent":"legal_analysis"}'
        if "步骤列表" in s or "规划" in s:
            return '{"plan":["给出简要法律意见"]}'
        if "选一个工具" in s:
            return '{"tool":"reason","args":{"prompt":"简要意见"}}'
        return '{"action":"response","response":"PnE答复"}'

    from agents.intent_gate import CLASSIFY_SYSTEM

    def write_llm2(system, user, hist=None):
        if system == CLASSIFY_SYSTEM:
            return '{"domain":"legal","intent":"legal_analysis"}'
        if "步骤列表" in (system or "") or "规划" in (system or ""):
            return '{"plan":["给出简要法律意见"]}'
        if "选一个工具" in (system or ""):
            return '{"tool":"reason","args":{"prompt":"x"}}'
        return '{"action":"response","response":"PnE答复"}'

    result = run_orchestrate(
        user_text="请分析民间借贷纠纷焦点",
        messages=[],
        write_llm=write_llm2,
        retrieve_fn=lambda q, scopes=None: {"text": "", "citations": []},
    )
    self.assertEqual(result.get("orchestration_mode"), "plan_execute")
    self.assertIn("PnE", result.get("visible_text") or "")
```

先读 `server/agents/intent_gate.py` 中真实 system 常量名，再写断言，避免测歪。

另测：`os.environ["PLAN_EXECUTE"]="0"` 时仍走旧图（可 assert `plan` 含 `steps` agent 字段）。

- [x] **Step 2: Run test — expect fail**（尚无 orchestration_mode）

- [x] **Step 3: Wire orchestrator**

在 `run_orchestrate` 的 `_execute` 内，gate 判定 `domain==legal` 之后（`from_gate` 且非 non_legal）：

```python
import os
from agents.plan_execute import run_plan_execute

use_pe = os.environ.get("PLAN_EXECUTE", "1").strip() not in ("0", "false", "False")
if use_pe and write_llm is not None:
    try:
        pe = run_plan_execute(
            objective=user_text,
            messages=messages,
            write_llm=write_llm,
            retrieve_fn=retrieve_fn,
            file_service=file_service,
            case_id=case_id,
            case_store=case_store,
            skills=skills,
            session_id=session_id,
            resume_state=None,  # filled in Task 4 from caller
        )
        return attach_call_flow(pe, workflow)
    except Exception as exc:
        print(f"[orchestrator] plan_execute failed, fallback graph: {exc}")
# existing plan_for_intent + langgraph path…
```

将 `resume_state` 参数加到 `run_orchestrate(...)` 签名并下传。

`_run_non_legal` 结果增加 `orchestration_mode: "non_legal"`。

- [x] **Step 4: Run** `tests.test_orchestrate` + `tests.test_plan_execute` — PASS

- [x] **Step 5: Commit (if requested)**

---

### Task 4: HTTP `resume_state` 与 session 持久化

**Files:**
- Modify: `server/http_api_extra.py` — `handle_orchestrate` 读取 `body["resume_state"]` 传给 `run_orchestrate`
- Modify: `handle_orchestrate`：若 `status == "awaiting_user"`，助手消息写入 `pending_question`，并在 extra 中存 `resume_state` / `plan` / `past_steps`（便于刷新恢复；首期客户端回传为准）

```python
result = run_orchestrate(
    ...
    resume_state=body.get("resume_state"),
)
# persist:
assistant_text = result.get("visible_text") or ""
if result.get("status") == "awaiting_user":
    assistant_text = result.get("pending_question") or assistant_text
extra = {}
if result.get("resume_state"):
    extra["resume_state"] = result["resume_state"]
...
```

- [x] **Step 1:** 小测或扩展现有 HTTP 测（若有 `tests/test_http_*` 编排测）断言 body 透传；无则依赖单元测 `run_orchestrate(resume_state=...)`。

- [x] **Step 2: Implement + run relevant tests**

- [x] **Step 3: Commit (if requested)**

---

### Task 5: workflow `detail` + plan 事件

**Files:**
- Modify: `server/agents/workflow.py`
- Modify: `server/agents/plan_execute.py`（emit plan / plan_step）

- [x] **Step 1:** 扩展 `emit`：

```python
def emit(self, kind: str, ident: str, name: str, status: str = "done", detail: Any = None) -> Dict[str, str]:
    item = {"kind": str(kind), "id": str(ident or ""), "name": str(name or ""), "status": status}
    if detail is not None:
        item["detail"] = detail
    ...
```

- [x] **Step 2:** 在 planner 成功后 `emit_step`/`emit` kind=`plan`；每步执行前后 kind=`plan_step`。

- [x] **Step 3:** 单测 tracer.events 含 plan（可放在 `tests/test_plan_execute.py`）。

- [x] **Step 4: Commit (if requested)**

---

### Task 6: 前端计划面板 + resume

**Files:**
- Modify: `mcp_client.js`
- Modify: `mcp_client.html`（若需样式链接 / cache-bust `?v=`）
- Modify: `mcp_client.css`（或现有 css）

- [x] **Step 1: Shell 增加计划槽**

在 `addOrchestrateProgressShell` 中，`flowSlot` 下增加：

```javascript
const planSlot = document.createElement('div');
planSlot.className = 'orchestrate-plan-slot';
planSlot.hidden = true;
contentDiv.insertBefore(planSlot, answerEl);
// return { ..., planSlot }
```

- [x] **Step 2: `paintOrchestratePlan(slot, data)`**

```javascript
function paintOrchestratePlan(slot, data) {
  if (!slot) return;
  const past = (data && data.past_steps) || [];
  const plan = (data && data.plan) || [];
  if (!past.length && !plan.length) {
    slot.hidden = true;
    slot.innerHTML = '';
    return;
  }
  slot.hidden = false;
  let html = '<div class="orchestrate-plan"><div class="orchestrate-plan-title">执行计划</div><ol>';
  past.forEach(function (p) {
    const label = (p && (p.step || p)) || '';
    html += '<li class="done">' + escapeHtml(String(label)) + '</li>';
  });
  plan.forEach(function (step, i) {
    const cls = i === 0 && data.status !== 'complete' ? 'current' : 'todo';
    html += '<li class="' + cls + '">' + escapeHtml(String(step)) + '</li>';
  });
  html += '</ol>';
  if (data.status === 'awaiting_user') {
    html += '<div class="orchestrate-plan-wait">等待你的补充</div>';
  }
  html += '</div>';
  slot.innerHTML = html;
}
```

（复用项目已有 `escapeHtml`；若无则写本地一小段。）

- [x] **Step 3: `applyOrchestrateSuccess` 调用 `paintOrchestratePlan`；若 `awaiting_user`，保存**

```javascript
window.__orchestrateResumeState = data.resume_state || null;
```

- [x] **Step 4: `doRequest` body 增加**

```javascript
resume_state: window.__orchestrateResumeState || undefined
```

成功且 `status === 'complete'` 时清空 `__orchestrateResumeState`。

- [x] **Step 5: Cache-bust** `mcp_client.js?v=20260905pne1`（改 html 引用）

- [x] **Step 6: CSS**

```css
.orchestrate-plan { font-size: 13px; margin: 8px 0; }
.orchestrate-plan-title { font-weight: 600; margin-bottom: 4px; }
.orchestrate-plan li.done { opacity: 0.55; text-decoration: line-through; }
.orchestrate-plan li.current { font-weight: 600; }
.orchestrate-plan-wait { margin-top: 6px; color: #8a5a00; }
```

- [x] **Step 7: 手动验收清单**（见下）— 自动化前端测非必须

- [x] **Step 8: Commit (if requested)**

---

### Task 7: 回归与收尾

- [x] **Step 1: Run full related suite**

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 -m unittest \
  tests.test_pe_tools tests.test_plan_execute tests.test_orchestrate tests.test_intent_gate -v
```

Expected: all PASS

- [x] **Step 2: Manual smoke**（重启 MCP）

1. 法律分析问 → 见计划面板 + 最终答  
2. 故意缺事实 → ask_user → 补充后续跑完成  
3. 非法律闲聊 → 无冗长计划  
4. `PLAN_EXECUTE=0` 重启 → 旧路径仍可用  

- [x] **Step 3: 若用户要求，一次性 commit 剩余文件并（仅当要求时）push**

---

## Spec coverage check

| Spec 项 | Task |
|---------|------|
| PnE 环 + 预算 | Task 2 |
| 白名单 tools 一步一动 | Task 1–2 |
| ask_user + resume_state | Task 2, 4, 6 |
| 接入 orchestrate + fallback / env | Task 3 |
| API 字段 / session | Task 4 |
| plan 事件 | Task 5 |
| 计划面板 UI | Task 6 |
| non_legal 不变 | Task 3, 7 |
| 测试最小集 | Task 1–3, 7 |

## Placeholder scan

无 TBD；`draft_doc` 首期可不产 docx artifact（observation 为正文即可；docx 可后续把 `run_doc_writing` 接入同一 tool）。

## Type consistency

- `resume_state`: `{objective, plan, past_steps, tool_calls_used, replan_count}`
- `status`: `complete` | `awaiting_user` | `error`
- `orchestration_mode`: `plan_execute` | `non_legal` | `legacy_graph`
