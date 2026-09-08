# 我的待办工作台（驳回感知 + 我的案件）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 扩展「我的待办」为工作台：待我审批 + 被驳回需处理 + 我的案件；壳层角标与每条驳回仅一次的强提醒弹窗。

**Architecture:** 在 `ApprovalStore` 增加 `rejection_acks` 与查询/ack/清 ack；`ApprovalHttpApi.workbench` / `ack_reject` 聚合待办、驳回文书、我的案件；`approvals.html` 三块 UI；`index.html` 用 workbench 角标并弹未 ack 驳回。

**Tech Stack:** Python 3 + sqlite3、现有 RBAC/`ApprovalHttpApi`、unittest、`approvals.html` / `index.html`

**Spec:** `docs/superpowers/specs/2026-09-08-approvals-workbench-reject-awareness-design.md`

---

## File map

| File | Responsibility |
|------|----------------|
| Modify: `server/approval_store.py` | `rejection_acks` schema；list rejected；ack；clear on re-reject |
| Modify: `server/http_approval_api.py` | `workbench`、`ack_reject`；路由解析 |
| Modify: `server/mcp_server.py` | 挂载 workbench / ack |
| Modify: `approvals.html` | 三块 UI + 绑案进对话 |
| Modify: `index.html` / `index.css` | 角标走 workbench；驳回弹窗 |
| Create: `tests/test_approval_workbench.py` | store + HTTP 覆盖 |
| Modify: `tests/test_http_approval_api.py` | 可选回归；以新文件为主 |

---

### Task 1: ApprovalStore — acks + rejected list + clear on re-reject

**Files:**
- Modify: `server/approval_store.py`
- Create: `tests/test_approval_workbench.py`

- [ ] **Step 1: Write failing tests**

在 `tests/test_approval_workbench.py`：

```python
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
from approval_store import ApprovalStore, ARTIFACT_STATUS_DRAFT
from rbac_store import RbacStore

class TestRejectionAcks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rbac = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.rbac.ensure_schema(); self.rbac.seed_defaults()
        self.store = ApprovalStore(os.path.join(self.tmp.name, "a.db"), rbac_store=self.rbac)
        self.store.ensure_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def _art(self, created_by=1, comment=None):
        row = self.store.create_artifact(
            case_id=1, file_id="f1", title="起诉状", doc_type="起诉状",
            created_by=created_by, source="ai_draft_doc",
        )
        if comment:
            conn = self.store._connect()
            conn.execute(
                "UPDATE doc_artifacts SET reject_comment=?, approval_status=? WHERE id=?",
                (comment, ARTIFACT_STATUS_DRAFT, row["id"]),
            )
            conn.commit(); conn.close()
            row = self.store.get_artifact(row["id"])
        return row

    def test_list_rejected_mine_and_ack(self):
        a = self._art(created_by=7, comment="缺证据")
        self._art(created_by=8, comment="别人的")
        rows = self.store.list_rejected_for_creator(7)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reject_comment"], "缺证据")
        self.assertFalse(self.store.is_rejection_acked(7, a["id"]))
        self.store.ack_rejection(7, a["id"])
        self.assertTrue(self.store.is_rejection_acked(7, a["id"]))

    def test_decide_reject_clears_acks(self):
        # minimal: create artifact, fake open task, ack, then decide reject -> ack gone
        pass  # implement with real submit/decide using rbac members if fixtures heavy;
              # or call clear_rejection_acks_for_artifact from decide(reject) path and unit-test clear_*
```

将 `test_decide_reject_clears_acks` 写成直接测 `clear_rejection_acks_for_artifact` + 在 `decide` reject 分支调用它（见 Step 3）。

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd /Users/kanglinlin/Documents/cursor/AI法官
PYTHONPATH=server python3 -m pytest tests/test_approval_workbench.py -q --tb=line
```

Expected: FAIL（方法不存在）

- [ ] **Step 3: Implement store**

在 `ensure_schema` 的 `executescript` 末尾追加：

```sql
CREATE TABLE IF NOT EXISTS rejection_acks (
  user_id INTEGER NOT NULL,
  artifact_id INTEGER NOT NULL,
  acked_at TEXT NOT NULL,
  PRIMARY KEY (user_id, artifact_id),
  FOREIGN KEY (artifact_id) REFERENCES doc_artifacts(id) ON DELETE CASCADE
);
```

新增方法：

```python
def list_rejected_for_creator(self, user_id: int) -> List[Dict[str, Any]]:
    conn = self._connect()
    rows = conn.execute(
        """
        SELECT * FROM doc_artifacts
        WHERE created_by = ?
          AND approval_status = ?
          AND reject_comment IS NOT NULL
          AND TRIM(reject_comment) != ''
        ORDER BY updated_at DESC
        """,
        (user_id, ARTIFACT_STATUS_DRAFT),
    ).fetchall()
    conn.close()
    return [self._enrich_artifact(dict(r)) for r in rows]

def is_rejection_acked(self, user_id: int, artifact_id: int) -> bool:
    conn = self._connect()
    row = conn.execute(
        "SELECT 1 FROM rejection_acks WHERE user_id=? AND artifact_id=?",
        (user_id, artifact_id),
    ).fetchone()
    conn.close()
    return row is not None

def ack_rejection(self, user_id: int, artifact_id: int) -> None:
    now = self._now()
    conn = self._connect()
    conn.execute(
        """
        INSERT INTO rejection_acks (user_id, artifact_id, acked_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, artifact_id) DO UPDATE SET acked_at=excluded.acked_at
        """,
        (user_id, artifact_id, now),
    )
    conn.commit()
    conn.close()

def clear_rejection_acks_for_artifact(self, artifact_id: int) -> None:
    conn = self._connect()
    conn.execute("DELETE FROM rejection_acks WHERE artifact_id=?", (artifact_id,))
    conn.commit()
    conn.close()
```

在 `decide(..., decision="reject")` 写完 artifact 更新、`conn.commit()` **之前或之后**调用 `clear_rejection_acks_for_artifact(artifact_id)`（若在同一连接外调用，在 commit/close 之后调用即可）。

- [ ] **Step 4: Tests PASS**

```bash
PYTHONPATH=server python3 -m pytest tests/test_approval_workbench.py -q --tb=line
```

- [ ] **Step 5: Commit**

```bash
git add server/approval_store.py tests/test_approval_workbench.py
git commit -m "$(cat <<'EOF'
feat(approval): rejection acks and list rejected drafts for creator

EOF
)"
```

---

### Task 2: HTTP workbench + ack_reject

**Files:**
- Modify: `server/http_approval_api.py`
- Modify: `tests/test_approval_workbench.py`（或扩展 `test_http_approval_api.py`）

- [ ] **Step 1: Failing HTTP tests**

复用 `TestHttpApprovalApi` 的建案夹具模式（见现有文件），新增：

```python
def test_workbench_badge_and_ack(self):
    assistant = self._login("a_appr")
    lead = self._login("l_appr")
    # create + submit as assistant, reject as lead (copy from existing tests)
    # then:
    st, wb = self.api.workbench(assistant)
    self.assertEqual(st, 200)
    self.assertGreaterEqual(len(wb["rejected_mine"]), 1)
    self.assertFalse(wb["rejected_mine"][0]["ack"])
    self.assertGreaterEqual(wb["badge_count"], 1)
    self.assertTrue(any(c["id"] == self._case_id for c in wb["my_cases"]))
    aid = wb["rejected_mine"][0]["artifact_id"]
    st, _ = self.api.ack_reject(assistant, aid)
    self.assertEqual(st, 200)
    st, wb2 = self.api.workbench(assistant)
    item = next(x for x in wb2["rejected_mine"] if x["artifact_id"] == aid)
    self.assertTrue(item["ack"])
    # badge_count should drop by 1 vs pre-ack if no pending for assistant
```

- [ ] **Step 2: Run — FAIL**（无 `workbench`）

- [ ] **Step 3: Implement API**

`parse_approval_path` 增加：

```python
if path == "/api/approvals/workbench" and method == "GET":
    return ("workbench", None)
if path.startswith("/api/approvals/rejects/") and path.endswith("/ack") and method == "POST":
    parts = path.split("/")
    if len(parts) == 6:  # /api/approvals/rejects/{id}/ack
        return ("ack_reject", parts[4])
```

`ApprovalHttpApi`：

```python
def workbench(self, authorization, *, badge_only: bool = False):
    gated = self.require_user(authorization)
    if gated[0] != 200:
        return gated
    user = gated[1]["user"]
    uid = int(user["id"])
    pending = self.approval_store.list_open_tasks_for_user(uid)
    rejected_rows = self.approval_store.list_rejected_for_creator(uid)
    rejected_mine = []
    unacked = 0
    for art in rejected_rows:
        ack = self.approval_store.is_rejection_acked(uid, int(art["id"]))
        if not ack:
            unacked += 1
        case = self.store.get_case(int(art["case_id"])) or {}
        rejected_mine.append({
            "artifact_id": art["id"],
            "case_id": art["case_id"],
            "case_no": case.get("case_no"),
            "title": art.get("title"),
            "reject_comment": art.get("reject_comment"),
            "updated_at": art.get("updated_at"),
            "file_id": art.get("file_id"),
            "ack": ack,
        })
    badge_count = len(pending) + unacked
    if badge_only:
        return _ok({"badge_count": badge_count})
    cases = self.store.list_cases_for_user(uid, all_cases=False)
    my_cases = []
    for c in cases:
        role = self.store.case_role_code(uid, int(c["id"]))
        member = self.store.get_case_member(int(c["id"]), uid) or {}
        my_cases.append({
            "id": c["id"],
            "case_no": c.get("case_no"),
            "title": c.get("title"),
            "stage": c.get("stage") or c.get("status"),
            "stage_label": c.get("stage_label") or c.get("status_label") or "",
            "my_role": role,
            "my_role_label": member.get("role_name") or role or "",
        })
    return _ok({
        "pending_tasks": pending,
        "rejected_mine": rejected_mine,
        "my_cases": my_cases,
        "badge_count": badge_count,
    })

def ack_reject(self, authorization, artifact_id: int):
    gated = self.require_user(authorization)
    if gated[0] != 200:
        return gated
    user = gated[1]["user"]
    art = self.approval_store.get_artifact(artifact_id)
    if not art:
        return _deny(404, "文书不存在")
    if art.get("created_by") is None or int(art["created_by"]) != int(user["id"]):
        return _deny(403, "仅发起人可确认驳回")
    if art.get("approval_status") != "draft" or not (art.get("reject_comment") or "").strip():
        return _deny(400, "文书当前不是被驳回草稿")
    self.approval_store.ack_rejection(int(user["id"]), artifact_id)
    return _ok({"ok": True})
```

- [ ] **Step 4: Tests PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(api): approvals workbench and reject ack endpoints"
```

---

### Task 3: Wire `mcp_server` routes

**Files:**
- Modify: `server/mcp_server.py`（`_handle_approval_api`；若 GET 列表里单独匹配 path，一并加上 `/api/approvals/workbench`）

- [ ] **Step 1:** 在 `parse_approval_path` 已支持的前提下，handler 增加：

```python
if action == "workbench":
    badge_only = (qs.get("badge_only", ["0"])[0] in ("1", "true", "yes"))
    self._write_json(*api.workbench(authz, badge_only=badge_only))
    return
if action == "ack_reject" and resource_id:
    self._write_json(*api.ack_reject(authz, int(resource_id)))
    return
```

确认 GET 路由能进 `_handle_approval_api`（现有 `inbox` 同路径族）。

- [ ] **Step 2:** 手动或用已有测试客户端冒烟（可选）

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(mcp): route workbench and reject ack APIs"
```

---

### Task 4: `approvals.html` 三块 UI

**Files:**
- Modify: `approvals.html`

- [ ] **Step 1:** 将数据源从 `/api/approvals/inbox` 改为 `/api/approvals/workbench`。

- [ ] **Step 2:** 渲染三节：
  - `#sectionPending` — 现有表格逻辑（`pending_tasks`）
  - `#sectionRejected` — `rejected_mine`：案号、标题、驳回意见、时间；按钮「下载工作稿」「打开对话」；可选「我知道了」→ `POST .../ack` 后刷新
  - `#sectionCases` — `my_cases`：案号、标题、阶段、角色；「进入对话」

- [ ] **Step 3:** 「打开对话 / 进入对话」：

```javascript
function openCaseChat(caseId) {
  if (window.parent && window.parent !== window && window.parent.loadPage) {
    window.parent.loadPage("mcp_client.html?case_id=" + encodeURIComponent(caseId));
  } else {
    location.href = "mcp_client.html?case_id=" + encodeURIComponent(caseId);
  }
}
```

（`mcp_client.js` 已支持 URL `case_id` → `LegalMindAuth.setCaseId`。）

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(ui): workbench sections for rejects and my cases"
```

---

### Task 5: 壳层角标 + 驳回弹窗（每条一次）

**Files:**
- Modify: `index.html`
- Modify: `index.css`（弹窗样式可复用 `contact-modal` 结构）

- [ ] **Step 1:** `refreshApprovalsBadge` 改为：

```javascript
const resp = await fetch(base + '/api/approvals/workbench?badge_only=1', {
  headers: LegalMindAuth.authHeaders()
});
// setApprovalsBadge(data.badge_count)
```

- [ ] **Step 2:** `syncShellNav` / 登录后：`fetch workbench`（完整），收集 `rejected_mine.filter(r => !r.ack)`；若长度 > 0，打开弹窗列出标题+意见截断。

- [ ] **Step 3:** 按钮：
  - 「知道了」：对每条 `POST /api/approvals/rejects/{id}/ack`，关弹窗，刷新角标  
  - 「去处理」：先 ack 同上，再 `loadPage('approvals.html')`

- [ ] **Step 4:** 会话内用 `sessionStorage` 键如 `lm_reject_prompted` 避免**同一次浏览器会话**内因多次 `syncShellNav` 重复弹（服务端 ack 后本就不会再弹；未点按钮前用 session 防抖）。逻辑：仅当存在未 ack 且本次会话尚未展示过该 artifact 集合时弹；点按钮后 ack。

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(shell): workbench badge and one-shot reject prompt"
```

---

### Task 6: 回归

- [ ] **Step 1: Run**

```bash
PYTHONPATH=server python3 -m pytest \
  tests/test_approval_workbench.py \
  tests/test_http_approval_api.py \
  tests/test_approval_store.py -q --tb=line
```

Expected: PASS

- [ ] **Step 2: Manual**（对照 spec 验收五步）

- [ ] **Step 3: Commit only if fixes**

```bash
git commit -m "test: harden approvals workbench coverage"
```

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| rejection_acks + clear on re-reject | 1 |
| workbench + ack API | 2–3 |
| 待办三块 UI + 绑案对话 | 4 |
| 角标 + 每条一次弹窗 | 5 |
| 非目标（邮件/阶段推进） | 不做 |

## Placeholder scan

无 TBD；测试夹具跟 `test_http_approval_api` 建案方式，勿留空提交。
