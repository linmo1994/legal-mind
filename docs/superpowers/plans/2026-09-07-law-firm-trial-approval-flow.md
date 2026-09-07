# 办案阶段 + 文书审批流（P0）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付律所私有化薄切面：五阶段案件机、助理→主办→合伙人两级文书审批、待办、基础审计，以及会话/文件鉴权；AI `draft_doc` 产物进入 `draft` 后由人工提交审核。

**Architecture:** 新增 `approval_store`（SQLite：doc_artifacts / approval_tasks / audit_events）与案件阶段常量/迁移 API；审批挂在 artifact 层，不改 `docx_form_fill` 内核。HTTP 经现有 `http_rbac_api` / `mcp_server` 路由挂载；聊天卡片读 artifact 审批字段并调提交/下载分流接口。

**Tech Stack:** Python 3 + sqlite3、现有 RBAC/FileService/SessionService、unittest、`mcp_client.js` / `admin_cases.html`

**Spec:** `docs/superpowers/specs/2026-09-07-law-firm-trial-approval-flow-design.md`（仅实现 **P0**；P1/P2 不在本计划）

---

## File map

| File | Responsibility |
|------|----------------|
| Create: `server/approval_store.py` | artifacts / tasks / audit CRUD + stage helpers used by API |
| Create: `server/http_approval_api.py` | `/api/cases/{id}/stage`、`/api/artifacts*`、`/api/approvals*`、`/api/audit` |
| Create: `tests/test_approval_store.py` | 阶段迁移、提交/通过/驳回、lead 自提跳级 |
| Create: `tests/test_http_approval_api.py` | API + 权限冒烟 |
| Create: `admin_approvals.html` | 「我的待办」页 |
| Modify: `server/rbac_store.py` | 新 PERMISSIONS、CASE 五阶段常量、status 读写兼容 |
| Modify: `server/session_service.py` | sessions.user_id |
| Modify: `server/http_api_extra.py` | orchestrate 登记 artifact；session 写 user_id |
| Modify: `server/agents/pe_tools.py` | artifact 返回可带 `case_id` 透传 |
| Modify: `server/mcp_server.py` | 挂载 approval API；files download 鉴权 |
| Modify: `mcp_client.js` | 卡片：提交审核 / 定稿 vs 工作稿 |
| Modify: `admin_cases.html` / `admin_nav.js` | 阶段推进 UI、待办入口 |
| Modify: `auth.js`（若需） | 导航链到待办页 |

---

### Task 1: 权限码 + 五阶段常量

**Files:**
- Modify: `server/rbac_store.py`
- Create: `tests/test_case_stages.py`

- [ ] **Step 1: Write failing tests for stage order**

```python
# tests/test_case_stages.py
import unittest
from rbac_store import (
    CASE_STAGE_CODES,
    CASE_STAGE_ORDER,
    next_stage,
    can_transition_stage,
)

class TestCaseStages(unittest.TestCase):
    def test_five_stages_ordered(self):
        self.assertEqual(
            CASE_STAGE_ORDER,
            ["intake", "materials_ready", "strategy_docs", "litigation", "closed"],
        )
        self.assertTrue(can_transition_stage("intake", "materials_ready"))
        self.assertFalse(can_transition_stage("intake", "closed"))
        self.assertEqual(next_stage("intake"), "materials_ready")
        self.assertIsNone(next_stage("closed"))
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTHONPATH=server python3 -m pytest tests/test_case_stages.py -q --tb=short`  
Expected: FAIL (import / missing symbols)

- [ ] **Step 3: Implement constants + helpers in rbac_store.py**

在 `CASE_STATUSES` 附近增加（保留旧常量供迁移映射）：

```python
CASE_STAGE_INTAKE = "intake"
CASE_STAGE_MATERIALS = "materials_ready"
CASE_STAGE_STRATEGY = "strategy_docs"
CASE_STAGE_LITIGATION = "litigation"
CASE_STAGE_CLOSED = "closed"
CASE_STAGE_ORDER = [
    CASE_STAGE_INTAKE,
    CASE_STAGE_MATERIALS,
    CASE_STAGE_STRATEGY,
    CASE_STAGE_LITIGATION,
    CASE_STAGE_CLOSED,
]
CASE_STAGE_CODES = set(CASE_STAGE_ORDER)
CASE_STAGE_LABELS = {
    "intake": "收案分案",
    "materials_ready": "材料完备",
    "strategy_docs": "策略与文书",
    "litigation": "诉讼推进",
    "closed": "结案归档",
}
# 旧 status → 新 stage
LEGACY_STATUS_TO_STAGE = {
    "init": "intake",
    "assigned": "intake",
    "analyzing": "materials_ready",
    "handling": "strategy_docs",
    "closed": "closed",
}

def normalize_case_stage(code: Optional[str]) -> str:
    if code in CASE_STAGE_CODES:
        return code
    return LEGACY_STATUS_TO_STAGE.get(code or "", CASE_STAGE_INTAKE)

def next_stage(current: str) -> Optional[str]:
    cur = normalize_case_stage(current)
    try:
        i = CASE_STAGE_ORDER.index(cur)
    except ValueError:
        return None
    if i + 1 >= len(CASE_STAGE_ORDER):
        return None
    return CASE_STAGE_ORDER[i + 1]

def can_transition_stage(frm: str, to: str) -> bool:
    return next_stage(frm) == to
```

在 `PERMISSIONS` 追加：

```python
("cap.doc_submit", "提交文书审核", "capability", "业务"),
("cap.doc_approve_lead", "主办审文书", "capability", "业务"),
("cap.doc_approve_partner", "合伙人审文书", "capability", "业务"),
("cap.case_stage_advance", "推进案件阶段", "capability", "业务"),
("cap.audit_read", "审计只读", "capability", "管理"),
("page.admin.approvals", "审批待办", "page", "页面"),
```

在 `DEFAULT_ROLE_PERMS` 中：
- `assistant`：+ `cap.doc_submit`、`page.admin.approvals`（只看待办里与己相关由 API 过滤）
- `lead_lawyer`：+ submit、approve_lead、case_stage_advance、page.admin.approvals
- `partner`：+ approve_partner、case_stage_advance、page.admin.approvals
- `director`：已有全量则自动包含；确保含 `cap.audit_read`

`enrich_case`：增加 `stage` / `stage_label`（`normalize_case_stage(status)`）。

- [ ] **Step 4: Run tests — expect pass**

Run: `PYTHONPATH=server python3 -m pytest tests/test_case_stages.py -q --tb=short`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/rbac_store.py tests/test_case_stages.py
git commit -m "feat(rbac): case stages and approval permission codes"
```

---

### Task 2: approval_store — artifacts / tasks / audit

**Files:**
- Create: `server/approval_store.py`
- Create: `tests/test_approval_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_approval_store.py
import os, tempfile, unittest
from approval_store import ApprovalStore
from rbac_store import RbacStore

class TestApprovalStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rbac = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.rbac.ensure_schema()
        # create users + case with partner/lead/assistant via existing helpers if available;
        # otherwise insert minimal rows matching schema used in test_http_rbac_api
        self.store = ApprovalStore(
            os.path.join(self.tmp.name, "approval.db"),
            rbac_store=self.rbac,
        )
        self.store.ensure_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_submit_by_assistant_creates_lead_task(self):
        # Arrange: case_id with lead_user_id / partner_user_id known
        art = self.store.create_artifact(
            case_id=1, file_id="f1", title="起诉状", doc_type="起诉状",
            created_by=10, source="ai_draft_doc",
        )
        out = self.store.submit_for_review(art["id"], actor_user_id=10, actor_case_role="assistant")
        self.assertEqual(out["approval_status"], "pending_lead")
        tasks = self.store.list_open_tasks_for_user(lead_user_id)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["step"], "lead")

    def test_lead_self_submit_skips_to_partner(self):
        art = self.store.create_artifact(
            case_id=1, file_id="f2", title="起诉状", doc_type="起诉状",
            created_by=20, source="ai_draft_doc",
        )
        out = self.store.submit_for_review(art["id"], actor_user_id=20, actor_case_role="lead_lawyer")
        self.assertEqual(out["approval_status"], "pending_partner")

    def test_reject_returns_draft_and_cancels_open(self):
        ...
```

（测试里用 `RbacStore` 现有 `create_user` / `create_case` API；若签名不同，按 `tests/test_http_rbac_api.py` 抄最小建案夹具。）

- [ ] **Step 2: Run — expect fail**

Run: `PYTHONPATH=server python3 -m pytest tests/test_approval_store.py -q --tb=short`  
Expected: FAIL

- [ ] **Step 3: Implement ApprovalStore**

`server/approval_store.py` 要点：

```python
class ApprovalStore:
    def __init__(self, db_path: str, rbac_store=None):
        self.db_path = db_path
        self.rbac = rbac_store

    def ensure_schema(self) -> None:
        # doc_artifacts: id, case_id, file_id, version, title, doc_type,
        #   created_by, source, approval_status, reject_comment, created_at, updated_at
        # approval_tasks: id, artifact_id, case_id, assignee_user_id, step,
        #   status, decision, comment, created_at, decided_at
        # audit_events: id, actor_user_id, action, object_type, object_id,
        #   case_id, detail_json, created_at

    def create_artifact(...)-> dict:  # status=draft, version=1 or max+1
    def get_artifact(self, artifact_id: int) -> Optional[dict]: ...
    def list_artifacts_for_case(self, case_id: int) -> List[dict]: ...

    def submit_for_review(self, artifact_id, actor_user_id, actor_case_role) -> dict:
        # draft only; resolve lead/partner from rbac.list_case_members
        # if actor_case_role == lead_lawyer -> pending_partner + partner task
        # else -> pending_lead + lead task
        # audit action=artifact_submit

    def decide(self, task_id, actor_user_id, decision, comment="") -> dict:
        # approve/reject; idempotent if task already done
        # lead approve -> pending_partner; partner approve -> approved
        # reject -> artifact draft + cancel other open tasks
        # audit

    def list_open_tasks_for_user(self, user_id: int) -> List[dict]: ...
    def write_audit(...): ...
    def list_audit(self, *, case_id=None, limit=100) -> List[dict]: ...
```

成员解析：

```python
def _member_user_id(self, case_id: int, role: str) -> Optional[int]:
    for m in self.rbac.list_case_members(case_id):
        if m.get("role") == role:
            return int(m["user_id"])
    return None
```

- [ ] **Step 4: Run — expect pass**

Run: `PYTHONPATH=server python3 -m pytest tests/test_approval_store.py -q --tb=short`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/approval_store.py tests/test_approval_store.py
git commit -m "feat(approval): store for artifacts, tasks, and audit"
```

---

### Task 3: 案件阶段推进 API

**Files:**
- Modify: `server/http_rbac_api.py`（或新建方法挂在现有 Cases API）
- Modify: `server/mcp_server.py`（路由）
- Modify: `tests/test_http_rbac_api.py` 或 Create: `tests/test_http_approval_api.py`

- [ ] **Step 1: Failing API test**

```python
def test_advance_case_stage_adjacent_only(self):
    # login as lead on case in intake
    # POST /api/cases/{id}/stage {"to":"materials_ready"} -> 200
    # POST ... {"to":"closed"} -> 400
```

- [ ] **Step 2: Implement**

`POST /api/cases/{case_id}/stage` body `{"to":"materials_ready"}`：

1. Auth + `cap.case_stage_advance`（或案角色 lead/partner）+ 案内成员  
2. `can_transition_stage(current, to)`  
3. `rbac.update_case_status(case_id, to)`（或专用 `update_case_stage`；**将 cases.status 存新 stage 码**）  
4. `approval_store.write_audit(action="case_stage_advance", ...)`  

`GET /api/cases/{id}` 响应已含 `stage`/`stage_label`（Task 1 enrich）。

- [ ] **Step 3: admin_cases.html** — 显示阶段标签 +「推进到 xxx」按钮（仅下一阶段）。

- [ ] **Step 4: Tests pass + commit**

```bash
git commit -m "feat(cases): enforce adjacent stage transitions"
```

---

### Task 4: HTTP 审批 API（登记 / 提交 / 决定 / 待办）

**Files:**
- Create: `server/http_approval_api.py`
- Modify: `server/mcp_server.py` — 构造 `ApprovalStore("./approval.db")`，挂路由
- Modify: `tests/test_http_approval_api.py`

- [ ] **Step 1: Routes**

| Method | Path | Behavior |
|--------|------|----------|
| POST | `/api/artifacts` | 登记 draft（orchestrate/内部用）；需 case 成员 |
| GET | `/api/artifacts/{id}` | 详情含 approval_status |
| POST | `/api/artifacts/{id}/submit` | 提交审核 |
| GET | `/api/approvals/inbox` | 当前用户 open tasks |
| POST | `/api/approvals/{task_id}/decide` | `{decision, comment}` |
| GET | `/api/audit?case_id=` | director 或案内 partner |

鉴权：复用 `http_rbac_api` 的 bearer 解析；决定时校验 task.assignee == 当前用户，或 director 代审 partner 步（配置常量 `DIRECTOR_MAY_APPROVE_PARTNER = True`）。

- [ ] **Step 2: Tests** — assistant 不能 decide partner task；decide 幂等。

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(api): artifact submit and approval inbox endpoints"
```

---

### Task 5: orchestrate / draft_doc 登记 DocArtifact

**Files:**
- Modify: `server/agents/pe_tools.py` — artifact dict 增加透传 `case_id`（从 ctx）
- Modify: `server/http_api_extra.py` — `handle_orchestrate` 在 `result["artifact"]` 且 `parsed_case_id` 时调用 `approval_store.create_artifact`，把 `artifact_id` / `approval_status` 写回 `result["artifact"]`
- Modify: `tests/test_orchestrate.py` 或 pe 集成测：有 case_id 时 artifact 含 `artifact_id`

- [ ] **Step 1: pe_tools** — `_artifact_from_saved_docx` / `_export_docx_artifact` 接受可选 `case_id` 写入返回 dict。

- [ ] **Step 2: http_api_extra**

```python
art = result.get("artifact")
if art and parsed_case_id and approval_store:
    row = approval_store.create_artifact(
        case_id=int(parsed_case_id),
        file_id=art["file_id"],
        title=art.get("title") or art.get("filename") or "法律文书",
        doc_type=art.get("title") or "法律文书",
        created_by=body.get("_auth_user_id"),
        source="ai_draft_doc",
    )
    art["artifact_id"] = row["id"]
    art["approval_status"] = row["approval_status"]
    approval_store.write_audit(
        actor_user_id=body.get("_auth_user_id"),
        action="artifact_created",
        object_type="doc_artifact",
        object_id=row["id"],
        case_id=int(parsed_case_id),
        detail={"file_id": art["file_id"]},
    )
```

无 `case_id`：不登记；前端提示文案见 Task 6。

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(orchestrate): register draft artifacts for case approval"
```

---

### Task 6: 聊天卡片 UI — 提交审核与下载分流

**Files:**
- Modify: `mcp_client.js` — `addOrchestrateDownload`
- Modify: `mcp_client.css`（必要时）
- Modify: `mcp_client.html` — cache bust query

- [ ] **Step 1: Card behavior**

若 `artifact.artifact_id` 存在：

- 展示状态徽章：`draft` / `pending_lead` / `pending_partner` / `approved` / `rejected`  
- `draft` 或 `rejected`：按钮「提交审核」→ `POST /api/artifacts/{id}/submit`（带 Authorization）  
- `approved`：主按钮「定稿下载」→ 原 download URL  
- 非 approved：主按钮文案「下载工作稿」，下载时 `filename` 加 `_草稿` 后缀（客户端 rename 即可）  
- 无 `artifact_id`：保持现状下载 + 灰字「未绑定案件，无法进入所内审批」

- [ ] **Step 2: Manual smoke** — 选案件起草 → 卡片有 artifact_id → 提交后状态变 pending_lead。

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(ui): approval actions on generated doc cards"
```

---

### Task 7: 我的待办页

**Files:**
- Create: `admin_approvals.html`
- Modify: `admin_nav.js` / `admin.html` — 入口 `page.admin.approvals`
- Style：复用现有 admin 样式

- [ ] **Step 1: Page** — 拉取 `GET /api/approvals/inbox`，列表展示案件号、文书标题、步骤；操作通过/驳回（驳回必填意见）。

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(admin): approvals inbox page"
```

---

### Task 8: 会话 user_id + 文件下载鉴权

**Files:**
- Modify: `server/session_service.py` — `sessions.user_id` 列（ALTER 兼容）
- Modify: `server/http_api_extra.py` / session API — create/list 按 user 过滤
- Modify: `server/mcp_server.py` — `/api/files/{id}/download` 与 preview：要求 Authorization；校验上传者 session 所属用户 **或** 文件关联案件的成员（查 `doc_artifacts.file_id` / case meta file ids）

最小可行规则（P0）：

1. 必须登录。  
2. 若 `approval_store` 中 file_id 属于某 case artifact → 调用者须为该案成员或 director。  
3. 否则：允许上传者（files 表 session→user 若可得）或 director；若无法判定归属则仅 director（避免继续完全公开）。  

- [ ] **Step 1: Tests** — 未授权 download → 401/403。

- [ ] **Step 2: Commit**

```bash
git commit -m "fix(security): bind sessions to users and gate file downloads"
```

---

### Task 9: 回归与文档勾选

- [ ] **Step 1: Run**

```bash
PYTHONPATH=server python3 -m pytest \
  tests/test_case_stages.py \
  tests/test_approval_store.py \
  tests/test_http_approval_api.py \
  tests/test_pe_tools.py \
  tests/test_plan_execute.py \
  tests/test_orchestrate.py \
  tests/test_http_rbac_api.py -q --tb=line
```

Expected: PASS（或仅记录与本特性无关的既有失败）

- [ ] **Step 2: Manual checklist**

1. 建案含 partner+lead+assistant  
2. 推进 intake → materials_ready → strategy_docs  
3. 助理对话生成起诉状 → 提交 → 主办待办通过 → 合伙人通过 → 定稿下载  
4. 未登录无法 download 案内文件  

- [ ] **Step 3: Commit only if fixes**

```bash
git commit -m "test: harden approval-flow P0 coverage"
```

---

## Spec coverage (P0)

| Spec P0 item | Task |
|--------------|------|
| 五阶段状态机 + 案件台 | 1, 3 |
| DocArtifact + ApprovalTask | 2, 4 |
| 两级审批 + 待办 | 4, 7 |
| 聊天卡片提交/下载分流 | 5, 6 |
| AuditEvent 最小 | 2, 4 |
| 会话 user_id + files 鉴权 | 8 |
| AI 不自动提交 | 5（仅 create draft） |
| lead 自提跳级 | 2 |
| 无 case 不建审批 | 5, 6 |

P1（材料门禁强制、通知、报表）/ P2 **不在本计划**。

## Placeholder scan

无 TBD；测试夹具中「...」处实现时按 `test_http_rbac_api` 补全建案，不得留空提交。
