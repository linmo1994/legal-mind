# 无案件门禁 + 案件「全选」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 未选案件时 `read_evidence` 返回中文引导并可 ask_user；下拉「全选」传 `case_id:"*"`，在有权限案件内按需读证据；单案行为不变。

**Architecture:** 鉴权接受哨兵 `"*"`；编排入口解析 `case_scope`（none/single/all_permitted）并填充 `permitted_case_ids`；`read_evidence` 按 scope 门禁；前端下拉增加全选；planner 提示词最小补丁。

**Tech Stack:** Python unittest + 现有 `mcp_client` / `auth.js`

**Spec:** `docs/superpowers/specs/2026-09-06-case-all-and-no-case-guard-design.md`

## Global Constraints

- 全选哨兵：字符串 `"*"`（不要 `int("*")`）。
- 全选 = 按需读有权限案件，**不**整包注入全部材料。
- 无案件文书：先追问；用户坚持后允许占位起草。
- 不改 PnE 预算 / 法规检索排序。
- 提交仅当用户明确要求时执行。

## File map

| File | Responsibility |
|------|----------------|
| `server/http_rbac_api.py` | `check_orchestrate_access` 接受 `"*"` |
| `server/case_materials.py` | `resolve_evidence_case_ids`（全选归属）可选 |
| `server/agents/pe_tools.py` | `read_evidence` 门禁 |
| `server/http_api_extra.py` | 解析 scope、permitted ids、跳过 `*` 注入 |
| `server/agents/plan_execute.py` | ctx + 提示词 |
| `auth.js` / `mcp_client.js` / `mcp_client.html` | 全选 UI + 传参 + cache-bust |
| `tests/test_orchestrate_auth.py` | `"*"` / 非法串 |
| `tests/test_pe_tools.py` | 无案 / 全选 read_evidence |

---

### Task 1: 鉴权接受 `case_id="*"`（TDD）

**Files:**
- Modify: `server/http_rbac_api.py` — `check_orchestrate_access`
- Modify: `tests/test_orchestrate_auth.py`

**Interfaces:**
- Produces: `case_id="*"` → status 200；body 含 `case_id: "*"`（或保持字符串）且 `case_scope: "all_permitted"`；非法非数字非 `*` 仍 400；`null` 仍 200 且 case_id None

- [ ] **Step 1: 写失败测试**

```python
def test_case_id_all_permitted_sentinel(self):
    st, body = self.api.check_orchestrate_access(
        self.hdr, {"case_id": "*", "user_text": "hi"}
    )
    self.assertEqual(st, 200)
    self.assertEqual(body.get("case_id"), "*")
    self.assertEqual(body.get("case_scope"), "all_permitted")

def test_case_id_garbage_still_400(self):
    st, body = self.api.check_orchestrate_access(
        self.hdr, {"case_id": "abc", "user_text": "hi"}
    )
    self.assertEqual(st, 400)
```

- [ ] **Step 2: 跑测确认失败**

```bash
cd /Users/kanglinlin/Documents/cursor/AI法官 && PYTHONPATH=server python3 -m unittest tests.test_orchestrate_auth.TestOrchestrateAuth.test_case_id_all_permitted_sentinel tests.test_orchestrate_auth.TestOrchestrateAuth.test_case_id_garbage_still_400 -v
```

Expected: FAIL（未知属性或 400 on `*`）

- [ ] **Step 3: 改 `check_orchestrate_access`**

在解析 `raw_case` 处：

```python
raw_case = body.get("case_id")
case_id: Optional[int] = None
case_scope = "none"
if raw_case == "*":
    case_scope = "all_permitted"
elif raw_case is not None and raw_case != "":
    try:
        case_id = int(raw_case)
        case_scope = "single"
    except (TypeError, ValueError):
        return _deny(400, "case_id 无效")
    if not self.store.get_case(case_id):
        return _deny(404, "案件不存在")
# require cap.chat with case_id (None when * or unset)
if not self.rbac.require(user["id"], "cap.chat", case_id):
    return _deny(403, "无权限：cap.chat")
# ... existing judge/doc_write checks with case_id (None for *) ...
out = {"user": user, "case_id": ("*" if case_scope == "all_permitted" else case_id)}
if case_scope != "none":
    out["case_scope"] = case_scope
elif case_id is None and raw_case not in (None, ""):
    pass
# always include case_scope for clarity:
out["case_scope"] = case_scope
return _ok(out)
```

注意：`cap.doc_write` 等在 `case_id is None`（含 `*`）时用律所级权限，与未选案一致。

- [ ] **Step 4: 跑测通过**

同 Step 2；另跑整文件：

```bash
PYTHONPATH=server python3 -m unittest tests.test_orchestrate_auth -v
```

Expected: OK

- [ ] **Step 5: Commit** — 仅当用户要求。

---

### Task 2: `read_evidence` 无案中文门禁 + 全选归属（TDD）

**Files:**
- Modify: `server/case_materials.py` — 增加 `resolve_cases_for_file_id`
- Modify: `server/agents/pe_tools.py` — `read_evidence` 分支
- Modify: `tests/test_pe_tools.py`

**Interfaces:**
- Consumes: `ctx.case_scope`, `ctx.case_id`, `ctx.permitted_case_ids`, `ctx.case_store`, `ctx.file_service`
- Produces:
  - `resolve_cases_for_file_id(file_id, case_ids, store) -> List[int]`
  - 无案 observation 含「请选择案件」或「全选」中文，**不含** raw `case_store` 堆砌优先（可保留简短原因）

- [ ] **Step 1: 失败测试**

```python
def test_read_evidence_no_case_chinese_hint(self):
    out = run_tool(
        "read_evidence",
        {"file_id": "f1"},
        ctx={"case_scope": "none", "case_id": None},
    )
    self.assertIn("选择案件", out["observation"])
    self.assertIn("全选", out["observation"])
    self.assertNotIn("case_store", out["observation"])

@patch("case_materials.get_case_evidence_text")
def test_read_evidence_all_scope_resolves_unique(self, mock_get):
    mock_get.return_value = "全文A"
    store = type("S", (), {})()
    def get_case(cid):
        if cid == 7:
            return {"id": 7, "meta": {"evidence_file_ids": ["f1"]}}
        return {"id": cid, "meta": {"evidence_file_ids": []}}
    store.get_case = get_case
    out = run_tool(
        "read_evidence",
        {"file_id": "f1"},
        ctx={
            "case_scope": "all_permitted",
            "permitted_case_ids": [7, 8],
            "case_store": store,
            "file_service": object(),
        },
    )
    mock_get.assert_called_once()
    self.assertEqual(mock_get.call_args[0][0], 7)
    self.assertIn("全文A", out["observation"])

def test_read_evidence_all_scope_ambiguous(self):
    store = type("S", (), {})()
    store.get_case = lambda cid: {
        "id": cid,
        "meta": {"evidence_file_ids": ["f1"]},
    }
    out = run_tool(
        "read_evidence",
        {"file_id": "f1"},
        ctx={
            "case_scope": "all_permitted",
            "permitted_case_ids": [1, 2],
            "case_store": store,
            "file_service": object(),
        },
    )
    self.assertIn("多个案件", out["observation"])
```

- [ ] **Step 2: 跑测确认失败**

```bash
PYTHONPATH=server python3 -m unittest \
  tests.test_pe_tools.TestPeTools.test_read_evidence_no_case_chinese_hint \
  tests.test_pe_tools.TestPeTools.test_read_evidence_all_scope_resolves_unique \
  tests.test_pe_tools.TestPeTools.test_read_evidence_all_scope_ambiguous -v
```

- [ ] **Step 3: 实现 `resolve_cases_for_file_id`**

在 `case_materials.py`：

```python
def resolve_cases_for_file_id(file_id: str, case_ids: List[int], store) -> List[int]:
    fid = str(file_id or "").strip()
    hits: List[int] = []
    if not fid or not store:
        return hits
    for cid in case_ids or []:
        try:
            case = store.get_case(int(cid))
        except Exception:
            continue
        if not case:
            continue
        meta = dict(case.get("meta") or {})
        bag = set(str(x) for x in (meta.get("evidence_file_ids") or []))
        bag |= set(str(x) for x in (meta.get("contract_file_ids") or []))
        if fid in bag:
            hits.append(int(cid))
    return hits
```

- [ ] **Step 4: 改 `read_evidence` in `pe_tools.py`**

```python
if name == "read_evidence":
    from case_materials import get_case_evidence_text, resolve_cases_for_file_id

    file_id = args.get("file_id")
    scope = str(ctx.get("case_scope") or ("single" if ctx.get("case_id") not in (None, "") else "none"))
    case_store = ctx.get("case_store")
    file_service = ctx.get("file_service")
    case_id = ctx.get("case_id")

    if scope == "none" or (case_id in (None, "", "*") and scope != "all_permitted"):
        if scope != "all_permitted":
            return {
                "observation": (
                    "当前未选择案件，无法读取证据材料。"
                    "请在下拉框选择具体案件或「全选（我有权限的案件）」，"
                    "或直接补充原告/被告等当事人信息后继续；"
                    "若坚持不绑定案件，请说明「先按占位起草」。"
                ),
                "citations": [],
            }

    if scope == "all_permitted":
        arg_case = args.get("case_id")
        permitted = [int(x) for x in (ctx.get("permitted_case_ids") or [])]
        if arg_case not in (None, ""):
            try:
                cid = int(arg_case)
            except (TypeError, ValueError):
                return {"observation": "read_evidence 的 case_id 无效", "citations": []}
            if cid not in permitted:
                return {"observation": "无权在该案件下读取证据", "citations": []}
            case_id = cid
        else:
            if not file_id:
                return {
                    "observation": "全选模式下请提供 file_id，或指定案件 case_id",
                    "citations": [],
                }
            hits = resolve_cases_for_file_id(str(file_id), permitted, case_store)
            if len(hits) == 0:
                return {
                    "observation": "在有权限的案件中未找到该证据文件，请确认 file_id 或改选具体案件",
                    "citations": [],
                }
            if len(hits) > 1:
                return {
                    "observation": f"该文件关联多个案件 {hits}，请指定 case_id 后再读取",
                    "citations": [],
                }
            case_id = hits[0]

    if not (file_id and case_id not in (None, "") and case_store and file_service):
        return {
            "observation": (
                "读取证据缺少必要参数。请选择案件并提供 file_id，或改用「全选」后提供可定位的文件标识。"
            ),
            "citations": [],
        }
    try:
        text = get_case_evidence_text(int(case_id), str(file_id), case_store, file_service)
    except Exception as exc:
        return {"observation": f"读取证据失败：{exc}", "citations": []}
    return {"observation": _trim(text or "(empty)"), "citations": []}
```

保留原 `test_read_evidence_passes_str_file_id` 仍通过（single + case_id=1）。

- [ ] **Step 5: 跑测通过**

```bash
PYTHONPATH=server python3 -m unittest tests.test_pe_tools -v
```

Expected: OK

- [ ] **Step 6: Commit** — 仅当用户要求。

---

### Task 3: 编排入口解析 scope + 跳过 `*` 注入 + ctx 下传

**Files:**
- Modify: `server/http_api_extra.py`（orchestrate handler 中 case_id 解析段）
- Modify: `server/agents/plan_execute.py` — `run_plan_execute` ctx 增加 `case_scope` / `permitted_case_ids`；planner/replan 提示一行
- Test: 可在 `tests/test_orchestrate.py` 增一条「body case_id=* 时不调用 build_case_material_context」若现有 mock 方便；否则手工 + 小单测解析函数

**Interfaces:**
- Consumes: Task 1–2
- Produces: `run_plan_execute(..., case_scope=..., permitted_case_ids=...)`；ctx 同步字段

- [ ] **Step 1: 解析辅助（可放 http_api_extra 内联）**

替换现有 `parsed_case_id` 块为：

```python
raw_case = body.get("case_id")
parsed_case_id = None
case_scope = "none"
permitted_case_ids = []
if raw_case == "*":
    case_scope = "all_permitted"
    # build permitted list from store + current user if available
    user = None
    try:
        # if check_orchestrate_access already ran, reuse; else list via store
        gated = getattr(mcp_server, "rbac_api", None)
        # Prefer: list_cases for token user — implement via rbac_api.store.list_cases_for_user
        authz = ...  # existing authorization header in handler
        if gated:
            st_u, me = gated.require_user(authz) if hasattr(gated, "require_user") else (None, None)
            # Simpler approach used in plan:
            pass
    except Exception:
        pass
elif raw_case not in (None, ""):
    try:
        parsed_case_id = int(raw_case)
        case_scope = "single"
    except (TypeError, ValueError):
        print(f"[orchestrate] invalid case_id={raw_case!r}")
```

**具体可运行写法（按现有 handler 变量名对齐）：** 在 `check_orchestrate_access` 已通过之后：

```python
raw_case = body.get("case_id")
parsed_case_id = None
case_scope = "none"
permitted_case_ids: list = []
if raw_case == "*":
    case_scope = "all_permitted"
    # access_body from check_orchestrate_access
    user = (access_body or {}).get("user") or {}
    uid = user.get("id")
    if store and uid is not None:
        try:
            # directors: list_cases_for_user(uid, all_cases=can_manage)
            cases = store.list_cases_for_user(int(uid), all_cases=False)
            if not cases and hasattr(store, "list_cases"):
                # fallback if empty and user is director — match list_cases mine=0 behavior if needed
                pass
            permitted_case_ids = [int(c["id"]) for c in (cases or []) if c.get("id") is not None]
        except Exception as exc:
            print(f"[orchestrate] permitted cases failed: {exc}")
elif raw_case not in (None, ""):
    try:
        parsed_case_id = int(raw_case)
        case_scope = "single"
    except (TypeError, ValueError):
        print(f"[orchestrate] invalid case_id={raw_case!r}")

if case_scope == "single" and parsed_case_id is not None and store and file_service:
    try:
        case_ctx = build_case_material_context(...)
    except ...
# do NOT build case_ctx when case_scope in ("none", "all_permitted")

result = run_orchestrate(
    ...
    case_id=parsed_case_id,
    case_store=store,
    case_scope=case_scope,
    permitted_case_ids=permitted_case_ids,
    ...
)
```

查阅 `http_api_extra.py` 中现有 `check_orchestrate_access` 调用，把返回的 `user` 接出来。若 `list_cases_for_user(..., all_cases=False)` 对 director 过窄：与前端 `loadActiveCaseOptions` 同一 API（`/api/admin/cases` 默认）对齐——读 `RbacHttpApi.list_cases` 的 `mine` 默认逻辑，编排全选用**相同**列表函数。

推荐：调用与 GET `/api/admin/cases` 相同的内部方法（无 mine 或 mine=0 时 director 见全部）以匹配下拉。

```python
st_c, payload = rbac_api.list_cases(authorization, mine=False)
if st_c == 200:
    permitted_case_ids = [int(c["id"]) for c in (payload.get("cases") or [])]
```

- [ ] **Step 2: `run_orchestrate` / `run_plan_execute` 签名**

把 `case_scope`、`permitted_case_ids` 传入并写入 tool `ctx`：

```python
ctx = {
    ...
    "case_id": case_id,
    "case_scope": case_scope or ("single" if case_id is not None else "none"),
    "permitted_case_ids": list(permitted_case_ids or []),
}
```

- [ ] **Step 3: 提示词补丁**

在 `PLANNER` / replan 系统串追加：

```text
无案件时不要假设能读取卷宗证据；缺当事人信息应 ask_user，请用户选择案件、「全选」或粘贴当事人信息。用户已表示不绑定案件并要求占位起草时，可用 draft_doc/reason，缺失项标注【待补充】。
```

- [ ] **Step 4: 测试**

若有现成 orchestrate HTTP 测：断言 `case_id=*` 时 mock `build_case_material_context` 未被调用。否则：

```bash
PYTHONPATH=server python3 -m unittest tests.test_orchestrate_auth tests.test_pe_tools tests.test_orchestrate -v
```

Expected: OK（修好签名相关失败）

- [ ] **Step 5: Commit** — 仅当用户要求。

---

### Task 4: 前端「全选」+ cache-bust

**Files:**
- Modify: `mcp_client.js` — `loadActiveCaseOptions`
- Modify: `auth.js` — 注释/确保 `"*"` 可存（已原样存，确认 `getCaseId` 不 `parseInt`）
- Modify: `mcp_client.html` — `?v=20260906case1`（css+js；`auth.js` 若有独立 cache 一并改）

**Interfaces:**
- Produces: option `value="*"` 文案 `全选（我有权限的案件）`；onchange 设 `LegalMindAuth.setCaseId('*')` 或 `null` / number

- [ ] **Step 1: `loadActiveCaseOptions`**

在插入案件 options **之前**：

```javascript
sel.innerHTML = '<option value="">请选择案件…</option>';
const allOpt = document.createElement('option');
allOpt.value = '*';
allOpt.textContent = '全选（我有权限的案件）';
sel.appendChild(allOpt);
(data.cases || []).forEach(...);
```

恢复选中：

```javascript
const prevCaseId = LegalMindAuth.getCaseId();
if (prevCaseId === '*' || prevCaseId === '*') {
  sel.value = '*';
  LegalMindAuth.setCaseId('*');
} else {
  const prevStr = prevCaseId != null ? String(prevCaseId) : '';
  ...
}
```

onchange：

```javascript
sel.onchange = function () {
  const raw = sel.value;
  if (raw === '*') LegalMindAuth.setCaseId('*');
  else if (!raw) LegalMindAuth.setCaseId(null);
  else LegalMindAuth.setCaseId(parseInt(raw, 10));
};
```

确认编排 `doRequest` / `callLLM` 的 `case_id: LegalMindAuth.getCaseId()` **不要** `parseInt` 掉 `*`。

- [ ] **Step 2: cache-bust**

```html
<link rel="stylesheet" href="mcp_client.css?v=20260906case1">
<script src="auth.js?v=20260906case1">  <!-- if present -->
<script src="mcp_client.js?v=20260906case1"></script>
```

- [ ] **Step 3: 手工验收**

1. 下拉可见「全选…」；选中后发消息，网络面板 JSON `case_id` 为 `"*"`。  
2. 未选案件生成起诉状：中文引导，非英文 `case_store` 堆砌。  
3. 单案仍注入材料（有材料时）。

- [ ] **Step 4: Commit** — 仅当用户要求。

---

## Spec coverage (self-review)

| Spec | Task |
|------|------|
| 哨兵 `*` + 鉴权 | Task 1 |
| read_evidence 无案/全选 | Task 2 |
| 不整包注入 `*` | Task 3 |
| permitted_case_ids | Task 3 |
| 提示词 ask_user / 占位 | Task 3 |
| 下拉全选 UI | Task 4 |
| 验收 1–6 | Task 2–4 |

无 TBD。`list_cases` 与下拉同源在 Task 3 Step 1 已写明。
