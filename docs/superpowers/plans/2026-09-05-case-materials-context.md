# 选案后携带案件材料进模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对话选中案件后，编排与单智能体访问模型时注入委托合同全文与证据清单（含 ≤200 字说明）；证据全文经一次工具回环按需拉取。

**Architecture:** 新增 `server/case_materials.py` 统一组装/说明生成/取证；案件 `update`/`create` 挂接证据时补说明；`handle_orchestrate` 与 `/api/llm/chat` 注入上下文；编排分析/文书在模型返回工具 JSON 时最多再取证一轮。

**Tech Stack:** 现有 `FileService`、`complete_chat`、`rbac_store`、orchestrator、mcp_client。

**Spec:** `docs/superpowers/specs/2026-09-05-case-materials-context-design.md`

## Global Constraints

- 不自动 commit（除非用户要求）
- 说明字段固定为文件 `metadata["evidence_brief"]`（≤200 字）；注入时优先读该字段
- 合同全文上限 `CONTRACT_TEXT_MAX = 20000`；工具正文上限 `EVIDENCE_TEXT_MAX = 15000`
- 工具名固定：`get_case_evidence_file`
- 客户端单智能体路径须附带 `case_id`（与 orchestrate 一致）

## File map

| File | Responsibility |
|------|----------------|
| `server/case_materials.py` | 组装上下文、生成/补写说明、按需取证、解析工具调用 |
| `server/file_service.py` | `update_file_metadata` / 合并 metadata |
| `server/http_rbac_api.py` | create/update case 后触发 `ensure_evidence_briefs` |
| `server/http_api_extra.py` | orchestrate 注入 `case_id` 材料 |
| `server/agents/orchestrator.py` | 用户上下文含材料；工具一轮回填 |
| `server/mcp_server.py` | `/api/llm/chat` 注入材料块 |
| `mcp_client.js` / `home.js`（若走 chat） | 请求体附带 `case_id` |
| `tests/test_case_materials.py` | 单元测试 |

---

### Task 1: `case_materials` 核心 + FileService metadata 更新

**Files:**
- Create: `server/case_materials.py`
- Modify: `server/file_service.py`
- Test: `tests/test_case_materials.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_case_materials.py
import unittest
from unittest.mock import MagicMock

from case_materials import (
    build_case_material_context,
    ensure_evidence_briefs,
    get_case_evidence_text,
    parse_evidence_tool_call,
    truncate_chars,
    EVIDENCE_BRIEF_MAX,
)


class TestCaseMaterials(unittest.TestCase):
    def test_truncate(self):
        self.assertEqual(truncate_chars("abcd", 3), "abc…[已截断]")

    def test_build_includes_contract_and_evidence_brief(self):
        store = MagicMock()
        store.get_case.return_value = {
            "id": 1,
            "case_no": "A1",
            "title": "借贷",
            "meta": {
                "case_type": "civil",
                "contract_file_ids": ["c1"],
                "evidence_file_ids": ["e1"],
            },
        }
        fs = MagicMock()
        def get_file(fid):
            if fid == "c1":
                return {"file_id": "c1", "original_name": "委托.pdf", "file_type": "pdf",
                        "text_content": "合同正文" * 10, "metadata": {}}
            return {"file_id": "e1", "original_name": "转账.png", "file_type": "png",
                    "text_content": "长正文", "metadata": {"evidence_brief": "银行转账截图摘要"}}
        fs.get_file.side_effect = get_file
        fs.get_file_text.side_effect = lambda fid: get_file(fid).get("text_content")
        text = build_case_material_context(1, store, fs)
        self.assertIn("【委托合同】", text)
        self.assertIn("合同正文", text)
        self.assertIn("转账.png", text)
        self.assertIn("银行转账截图摘要", text)
        self.assertNotIn("长正文", text)

    def test_get_evidence_rejects_non_case_file(self):
        store = MagicMock()
        store.get_case.return_value = {"id": 1, "meta": {"evidence_file_ids": ["e1"]}}
        fs = MagicMock()
        with self.assertRaises(ValueError):
            get_case_evidence_text(1, "e99", store, fs)

    def test_parse_tool_call(self):
        raw = '需要看全文\n{"tool":"get_case_evidence_file","file_id":"e1"}\n'
        self.assertEqual(parse_evidence_tool_call(raw), "e1")
        self.assertIsNone(parse_evidence_tool_call("普通回答"))

    def test_ensure_brief_writes_metadata(self):
        fs = MagicMock()
        fs.get_file.return_value = {
            "file_id": "e1", "text_content": "证据全文内容足够长", "metadata": {}, "description": None
        }
        def write_llm(system, user, hist=None):
            return "这是一份不超过二百字的说明。"
        ensure_evidence_briefs(fs, ["e1"], write_llm=write_llm)
        fs.update_file_metadata.assert_called()
        args = fs.update_file_metadata.call_args
        self.assertEqual(args[0][0], "e1")
        self.assertIn("evidence_brief", args[0][1])
        self.assertLessEqual(len(args[0][1]["evidence_brief"]), EVIDENCE_BRIEF_MAX)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测确认失败**

```bash
cd /Users/kanglinlin/Documents/cursor/AI法官 && PYTHONPATH=server python3 -m unittest tests.test_case_materials -v
```

Expected: FAIL（模块不存在）

- [ ] **Step 3: FileService 增加 metadata 合并更新**

在 `server/file_service.py` 的 `get_file` 方法后增加：

```python
def update_file_metadata(self, file_id: str, patch: Dict) -> Optional[Dict]:
    """合并写入 files.metadata（JSON）。返回更新后的 get_file 结果。"""
    info = self.get_file(file_id)
    if not info:
        return None
    meta = dict(info.get("metadata") or {})
    meta.update(patch or {})
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE files SET metadata = ? WHERE file_id = ?",
        (json.dumps(meta, ensure_ascii=False), file_id),
    )
    conn.commit()
    conn.close()
    return self.get_file(file_id)
```

- [ ] **Step 4: 实现 `server/case_materials.py`**

```python
"""Assemble case contract/evidence context for LLM prompts."""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

EVIDENCE_BRIEF_MAX = 200
CONTRACT_TEXT_MAX = 20000
EVIDENCE_TEXT_MAX = 15000
TOOL_NAME = "get_case_evidence_file"

WriteLlm = Callable[..., str]


def truncate_chars(text: str, limit: int) -> str:
    t = text or ""
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 1)] + "…[已截断]"


def _meta(case: Dict[str, Any]) -> Dict[str, Any]:
    return dict(case.get("meta") or {})


def _heuristic_brief(text: str) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if not compact:
        return "暂无摘要"
    return truncate_chars(compact, EVIDENCE_BRIEF_MAX).replace("…[已截断]", "…")


def generate_evidence_brief(text: str, write_llm: Optional[WriteLlm] = None) -> str:
    body = (text or "").strip()
    if not body:
        return "暂无摘要"
    if write_llm:
        try:
            raw = write_llm(
                "你是法律助理。根据证据材料正文写中文说明，不超过200字，只输出说明本身。",
                truncate_chars(body, 6000),
            )
            brief = re.sub(r"\s+", " ", (raw or "").strip())
            if brief:
                return truncate_chars(brief, EVIDENCE_BRIEF_MAX).replace("…[已截断]", "…")
        except Exception as exc:
            print(f"[case_materials] brief llm failed: {exc}")
    return _heuristic_brief(body)


def ensure_evidence_briefs(
    file_service,
    file_ids: List[str],
    write_llm: Optional[WriteLlm] = None,
) -> None:
    for fid in file_ids or []:
        info = file_service.get_file(fid)
        if not info:
            continue
        meta = dict(info.get("metadata") or {})
        if (meta.get("evidence_brief") or "").strip():
            continue
        text = info.get("text_content")
        if text is None and hasattr(file_service, "get_file_text"):
            text = file_service.get_file_text(fid)
        brief = generate_evidence_brief(text or "", write_llm=write_llm)
        file_service.update_file_metadata(fid, {"evidence_brief": brief})


def build_case_material_context(
    case_id: int,
    store,
    file_service,
    write_llm: Optional[WriteLlm] = None,
) -> str:
    case = store.get_case(int(case_id))
    if not case:
        return ""
    meta = _meta(case)
    evidence_ids = list(meta.get("evidence_file_ids") or [])
    ensure_evidence_briefs(file_service, evidence_ids, write_llm=write_llm)

    lines = ["【当前案件】"]
    lines.append(
        f"案号：{case.get('case_no') or '-'}｜标题：{case.get('title') or '-'}｜"
        f"类型：{meta.get('case_type') or '-'}"
    )
    lines.append("")
    lines.append("【委托合同】")
    contract_ids = list(meta.get("contract_file_ids") or [])
    if not contract_ids:
        lines.append("未上传委托合同。")
    else:
        for fid in contract_ids:
            info = file_service.get_file(fid) or {}
            name = info.get("original_name") or fid
            text = info.get("text_content")
            if text is None and hasattr(file_service, "get_file_text"):
                text = file_service.get_file_text(fid)
            lines.append(f"文件名：{name}（file_id={fid}）")
            lines.append(truncate_chars(text or "（无解析正文）", CONTRACT_TEXT_MAX))
    lines.append("")
    lines.append("【证据材料】")
    if not evidence_ids:
        lines.append("未上传证据材料。")
    else:
        for i, fid in enumerate(evidence_ids, 1):
            info = file_service.get_file(fid) or {}
            meta_f = dict(info.get("metadata") or {})
            brief = (meta_f.get("evidence_brief") or "").strip() or "暂无摘要"
            lines.append(
                f"{i}. file_id={fid}｜文件名={info.get('original_name') or fid}｜"
                f"类型={info.get('file_type') or '-'}｜说明={brief}"
            )
        lines.append(
            f"如需某份证据全文，请单独回复一行 JSON："
            f'{{"tool":"{TOOL_NAME}","file_id":"<id>"}}'
        )
    return "\n".join(lines).strip()


def get_case_evidence_text(
    case_id: int,
    file_id: str,
    store,
    file_service,
) -> str:
    case = store.get_case(int(case_id))
    if not case:
        raise ValueError("案件不存在")
    allowed = set(_meta(case).get("evidence_file_ids") or [])
    if file_id not in allowed:
        raise ValueError("该文件不属于本案证据材料")
    info = file_service.get_file(file_id)
    if not info:
        raise ValueError("文件不存在")
    text = info.get("text_content")
    if text is None and hasattr(file_service, "get_file_text"):
        text = file_service.get_file_text(file_id)
    name = info.get("original_name") or file_id
    body = truncate_chars(text or "（无解析正文）", EVIDENCE_TEXT_MAX)
    return f"【证据全文】{name}（file_id={file_id}）\n{body}"


def parse_evidence_tool_call(reply: str) -> Optional[str]:
    if not reply:
        return None
    for line in (reply or "").splitlines():
        s = line.strip()
        if not (s.startswith("{") and s.endswith("}")):
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if obj.get("tool") == TOOL_NAME and obj.get("file_id"):
            return str(obj["file_id"]).strip()
    # 全文仅含一个 JSON 对象时
    m = re.search(
        r'\{\s*"tool"\s*:\s*"' + re.escape(TOOL_NAME) + r'"\s*,\s*"file_id"\s*:\s*"([^"]+)"\s*\}',
        reply,
    )
    return m.group(1) if m else None
```

- [ ] **Step 5: 跑测通过**

```bash
PYTHONPATH=server python3 -m unittest tests.test_case_materials -v
```

Expected: OK

- [ ] **Step 6: Commit only if user asks**

---

### Task 2: 案件保存时补生成证据说明

**Files:**
- Modify: `server/http_rbac_api.py`（`create_case` / `update_case` 成功写 meta 后）

- [ ] **Step 1: 在 API 类中增加辅助方法**

```python
def _ensure_case_evidence_briefs(self, evidence_ids: List[str]) -> None:
    fs = getattr(self, "file_service", None)
    if fs is None:
        # HttpRbacApi 构造时若无 file_service，从 mcp 挂载处注入；见 Step 2
        return
    write_llm = None
    try:
        from llm_complete import complete_chat
        write_llm = complete_chat
    except Exception:
        write_llm = None
    from case_materials import ensure_evidence_briefs
    ensure_evidence_briefs(fs, evidence_ids, write_llm=write_llm)
```

- [ ] **Step 2: 注入 `file_service`**

找到 `HttpRbacApi` 的 `__init__`（或创建处）。若当前只有 `store`/`rbac`，增加可选 `file_service=None`，并在 `mcp_server` 构造 API 时传入 `file_service=self.file_service`。

- [ ] **Step 3: create/update 成功后调用**

在 `create_case` 写入 `contract_file_ids`/`evidence_file_ids` 成功返回前：

```python
self._ensure_case_evidence_briefs(_normalize_file_ids(meta.get("evidence_file_ids")))
```

在 `update_case` 于 `meta_changed` 且证据列表可能变化后同样调用（使用更新后的 `evidence_file_ids`）。

- [ ] **Step 4: 手工或单测** — mock `update_file_metadata` 在 append evidence 后被调用（可选短测放 `tests/test_http_rbac_api.py`）。

---

### Task 3: 编排路径注入 + 工具一轮

**Files:**
- Modify: `server/http_api_extra.py` → `handle_orchestrate`
- Modify: `server/agents/orchestrator.py` → `_run_text_analysis` / `_run_doc_writing`（及 `run_orchestrate` 签名）

- [ ] **Step 1: `handle_orchestrate` 组装并前缀**

```python
case_id = body.get("case_id")
case_ctx = ""
store = getattr(getattr(mcp_server, "rbac_api", None), "store", None) or getattr(mcp_server, "rbac_store", None)
if case_id and store and file_service:
    try:
        from case_materials import build_case_material_context
        case_ctx = build_case_material_context(int(case_id), store, file_service, write_llm=write_llm)
    except Exception as exc:
        print(f"[orchestrate] case materials failed: {exc}")
enriched = user_text
if case_ctx:
    enriched = case_ctx + "\n\n" + (user_text or "")
result = run_orchestrate(
    user_text=enriched,
    ...
    case_id=int(case_id) if case_id not in (None, "") else None,
    case_store=store,
)
```

注意：会话落库仍用原始 `user_text`，不要把整段材料块写入用户消息历史。

- [ ] **Step 2: `run_orchestrate` / 子 agent 支持工具一轮**

为 `_run_text_analysis`（文书路径同理）在 `write_llm` 返回后：

```python
from case_materials import parse_evidence_tool_call, get_case_evidence_text

fid = parse_evidence_tool_call(body)
if fid and case_id and case_store and file_service and write_llm:
    try:
        ev = get_case_evidence_text(case_id, fid, case_store, file_service)
        body2 = write_llm(
            _analysis_system_prompt(skills),
            user_prompt + "\n\n" + ev + "\n\n请基于证据全文继续回答用户，不要再输出工具 JSON。",
            messages,
        )
        if body2:
            body = body2
    except Exception as exc:
        body = (body or "") + f"\n\n（无法读取证据 {fid}：{exc}）"
```

将 `case_id` / `case_store` 经 `run_orchestrate` → `_dispatch` → 子函数参数向下传递（缺省 `None`）。

- [ ] **Step 3: 扩展 `tests/test_orchestrate.py`**

增加：带 mock store/file_service 时，`user_text` 前缀含 `【当前案件】`；模拟 LLM 先返回工具 JSON 再返回终答，断言终答来自第二轮。

- [ ] **Step 4: 跑相关单测**

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=server python3 -m unittest tests.test_case_materials tests.test_orchestrate -v
```

---

### Task 4: 单智能体 `/api/llm/chat` + 客户端 `case_id`

**Files:**
- Modify: `server/mcp_server.py` → `_handle_llm_proxy` 拼 `context_parts` 处
- Modify: `mcp_client.js`（`callLLMViaProxy` / 组 `requestBody`）
- Modify: `home.js`（若首页同样走 `/api/llm/chat`）

- [ ] **Step 1: 服务端**

在构建 `context_parts`、处理完本轮 `file_ids` 之后：

```python
raw_case = request_data.get("case_id")
if raw_case not in (None, ""):
    try:
        cid = int(raw_case)
        store = MCPHTTPHandler.server_instance.rbac_store
        fs = MCPHTTPHandler.server_instance.file_service
        from case_materials import build_case_material_context
        from llm_complete import complete_chat
        block = build_case_material_context(cid, store, fs, write_llm=complete_chat)
        if block:
            context_parts.insert(0, block)
    except Exception as exc:
        print(f"[llm_proxy] case materials failed: {exc}")
```

单智能体工具：若响应解析到 `get_case_evidence_file`，可在**同一请求内**再取证拼入后重呼一轮（与编排对称）；若 `_handle_llm_proxy` 结构过重，最小实现为：仅注入清单+合同，工具回环只保证编排可用，并在代理路径增加同等一轮（推荐对称实现）。

- [ ] **Step 2: 客户端附带 case_id**

在 `mcp_client.js` 组装 `requestBody` 处：

```javascript
case_id: (typeof LegalMindAuth !== 'undefined' && LegalMindAuth.getCaseId)
  ? LegalMindAuth.getCaseId()
  : null
```

`home.js` 中发往 `/api/llm/chat` 的请求同样附带 `LegalMindAuth.getCaseId()`。

- [ ] **Step 3: 冒烟** — 选案后提问，代理日志或调试中可见 `【当前案件】`；未选案无该块。

---

### Task 5: 验收收尾

- [ ] 对照 spec §5：合同全文、证据清单+说明、工具越权、未选案。
- [ ] `rg evidence_brief|build_case_material_context|get_case_evidence_file` 确认接线完整。
- [ ] Commit only if user asks。

---

## Spec coverage

| Spec | Task |
|------|------|
| 证据上传/挂接时 ≤200 字说明 | 1–2 |
| 合同全文 + 证据清单注入 | 1, 3, 4 |
| 编排 + 单智能体 | 3, 4 |
| 工具按需取证 | 3（+4 对称） |
| 权限/越权 | 1 `get_case_evidence_text` |
| 降级暂无摘要 | 1 `generate_evidence_brief` |

## Self-review

- 无 TBD；字段名统一 `evidence_brief` / `get_case_evidence_file`。
- 会话落库使用原始用户句，避免材料块污染历史。
- `HttpRbacApi` 必须能拿到 `file_service`，否则 Task 2 空转。
