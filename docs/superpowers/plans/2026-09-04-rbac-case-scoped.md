# RBAC 与案级权限 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 LegalMind 实现本地登录、所级 RBAC（主任/行政主管）、案级入案角色（合伙人/主办/助理）、案件分案，以及管理后台与业务 API 权限拦截。

**Architecture:** SQLite 新库 `rbac.db`（与 `sessions.db` / `files.db` 并列）存用户、角色、权限、案件与成员；`auth_service` 管密码与 token；`rbac_service` 解析所级∪案级权限；MCP HTTP 增加 `/api/auth/*` 与 `/api/admin/{users,roles,permissions,cases}`；静态页增加登录与四个管理页；业务请求带 Bearer token 与 `case_id`。

**Tech Stack:** Python 3 + sqlite3、stdlib `hashlib`/`secrets`/`hmac`（PBKDF2）、现有 `http.server` MCP、静态 HTML/JS/CSS。

## Global Constraints

- 规格：`docs/superpowers/specs/2026-09-04-rbac-case-scoped-design.md`
- 内置角色 code：`director`、`admin_officer`、`partner`、`lead_lawyer`、`assistant`（不可删）
- 主任/行政主管不写入 `case_members`
- 一人一案一个角色：`UNIQUE(user_id, case_id)`
- 权限解析：`effective = firm ∪ case(case_id)`
- 不提交真实生产密码到 git；种子主任默认 `director` / `ChangeMe123!`，`must_change_password=1`
- 测试用临时目录下的 sqlite，不碰开发机真实 `rbac.db`

## File map

| File | Responsibility |
|------|----------------|
| `server/rbac_store.py` | SQLite schema、种子数据、CRUD |
| `server/auth_service.py` | 密码哈希、login/logout/me、session token |
| `server/rbac_service.py` | 权限解析、require_perm 辅助 |
| `server/http_rbac_api.py` | HTTP handlers 纯函数（便于测） |
| `server/mcp_server.py` | 路由挂载、读 Authorization |
| `server/http_api_extra.py` | orchestrate 等处注入鉴权（若合适） |
| `login.html` / `auth.js` | 登录与 token 存储 |
| `admin_users.html` 等 + `admin_nav.js` | 管理 UI |
| `mcp_client.js` / `home.js` | 登录门禁、案件选择、请求头 |
| `tests/test_rbac_*.py` | 单元与 API 级测试 |

---

### Task 1: RBAC store + seed

**Files:**
- Create: `server/rbac_store.py`
- Test: `tests/test_rbac_store.py`

**Interfaces:**
- Produces: `RbacStore(db_path)` with `ensure_schema()`, `seed_defaults()`, `get_role_by_code(code)`, `list_permissions()`, `create_user(...)`, `set_user_roles(user_id, role_codes)`, `set_role_permissions(role_code, perm_codes)`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_rbac_store.py
import os, tempfile, unittest
from rbac_store import RbacStore

class TestRbacStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.store.ensure_schema()
        self.store.seed_defaults()

    def tearDown(self):
        self.tmp.cleanup()

    def test_seeds_five_system_roles(self):
        codes = {r["code"] for r in self.store.list_roles()}
        self.assertEqual(codes, {"director", "admin_officer", "partner", "lead_lawyer", "assistant"})

    def test_director_has_user_manage(self):
        perms = self.store.permissions_for_role_codes(["director"])
        self.assertIn("cap.user_manage", perms)
        self.assertIn("cap.case_assign", perms)

    def test_admin_officer_no_judge(self):
        perms = self.store.permissions_for_role_codes(["admin_officer"])
        self.assertIn("cap.case_assign", perms)
        self.assertNotIn("cap.judge", perms)

    def test_seed_director_user(self):
        u = self.store.get_user_by_username("director")
        self.assertIsNotNone(u)
        self.assertTrue(u["must_change_password"])
```

- [ ] **Step 2: Run tests — expect fail (import/module missing)**

Run: `cd /Users/kanglinlin/Documents/cursor/AI法官 && PYTHONPATH=server python3 -m pytest tests/test_rbac_store.py -v`  
Expected: FAIL (cannot import `rbac_store`)

- [ ] **Step 3: Implement `server/rbac_store.py`**

实现要点：
- 表：`users`, `roles`, `permissions`, `user_roles`, `role_permissions`, `auth_sessions`, `cases`, `case_members`
- `seed_defaults()`：插入五角色、全部 permission codes（见规格 4.1）、默认矩阵（规格 4.2）、若不存在则创建用户 `director`（仅占位 password_hash 空字符串，Task 2 再设哈希；或 Task 1 只建角色权限，Task 2 建种子用户——**本任务创建用户行并用临时 hash `!unset`，Task 2 覆盖为 PBKDF2**）
- `permissions_for_role_codes(codes: List[str]) -> Set[str]`

- [ ] **Step 4: Run tests — expect pass**

Run: `PYTHONPATH=server python3 -m pytest tests/test_rbac_store.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/rbac_store.py tests/test_rbac_store.py
git commit -m "feat(rbac): add SQLite store and default role/permission seed"
```

---

### Task 2: Auth service (PBKDF2 + sessions)

**Files:**
- Create: `server/auth_service.py`
- Modify: `server/rbac_store.py`（若需 session CRUD 方法）
- Test: `tests/test_auth_service.py`

**Interfaces:**
- Consumes: `RbacStore`
- Produces: `AuthService(store)` — `hash_password(pw)`, `verify_password(pw, hash)`, `login(username, password) -> dict|None`, `logout(token)`, `resolve_token(token) -> user|None`, `ensure_seed_director(password="ChangeMe123!")`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_auth_service.py
import os, tempfile, unittest
from rbac_store import RbacStore
from auth_service import AuthService

class TestAuth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.store.ensure_schema()
        self.store.seed_defaults()
        self.auth = AuthService(self.store)
        self.auth.ensure_seed_director("ChangeMe123!")

    def tearDown(self):
        self.tmp.cleanup()

    def test_login_ok(self):
        out = self.auth.login("director", "ChangeMe123!")
        self.assertIsNotNone(out)
        self.assertIn("token", out)
        self.assertIn("cap.user_manage", out["firm_permissions"])

    def test_login_bad_password(self):
        self.assertIsNone(self.auth.login("director", "wrong"))

    def test_resolve_token(self):
        out = self.auth.login("director", "ChangeMe123!")
        user = self.auth.resolve_token(out["token"])
        self.assertEqual(user["username"], "director")
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTHONPATH=server python3 -m pytest tests/test_auth_service.py -v`  
Expected: FAIL missing `auth_service`

- [ ] **Step 3: Implement auth**

- PBKDF2-HMAC-SHA256，格式 `pbkdf2$iterations$salt_hex$hash_hex`
- Token：`secrets.token_urlsafe(32)`，存 `auth_sessions`，默认 7 天过期
- `login` 返回 `{token, user:{id,username,display_name,...}, firm_roles, firm_permissions}`

- [ ] **Step 4: Tests pass**

- [ ] **Step 5: Commit** `feat(auth): add PBKDF2 login and session tokens`

---

### Task 3: Permission resolution + cases membership

**Files:**
- Create: `server/rbac_service.py`
- Extend: `server/rbac_store.py` with case CRUD / members
- Test: `tests/test_rbac_service.py`

**Interfaces:**
- Produces: `RbacService(store)` —
  - `effective_permissions(user_id, case_id=None) -> Set[str]`
  - `require(user_id, perm, case_id=None) -> bool`
  - store: `create_case(...)`, `add_case_member(case_id, user_id, role_code, assigned_by)`, `list_cases_for_user(...)`

- [ ] **Step 1: Failing tests**

```python
def test_case_member_gets_judge(self):
    # create lawyer user with no firm caps
    # create case, add as lead_lawyer
    # effective(user, case_id) contains cap.judge
    # effective(user, None) does not contain cap.judge

def test_reject_director_as_case_member(self):
    with self.assertRaises(ValueError):
        self.store.add_case_member(case_id, director_id, "lead_lawyer", assigned_by=1)
```

- [ ] **Step 2–4: Implement + pass**
- [ ] **Step 5: Commit** `feat(rbac): resolve firm∪case permissions and case members`

---

### Task 4: HTTP API — auth + admin users/roles/permissions/cases

**Files:**
- Create: `server/http_rbac_api.py`
- Modify: `server/mcp_server.py`（路由 + CORS + 读 Bearer）
- Test: `tests/test_http_rbac_api.py`（直接调 handler 函数，不启真服务器）

**Interfaces:**
- Produces handlers:
  - `handle_login(auth, body) -> (status, dict)`
  - `handle_me(auth, token, case_id)`
  - `handle_users_*`, `handle_roles_*`, `handle_permissions_*`, `handle_cases_*`
- mcp_server: `GET/POST/PUT/DELETE` 路径挂载；从 header 取 token

- [ ] **Step 1: Tests for login 200 / 401, users list requires `cap.user_manage`, assign member**
- [ ] **Step 2–4: Implement handlers + wire mcp_server**
- [ ] **Step 5: Commit** `feat(api): expose auth and RBAC admin HTTP endpoints`

---

### Task 5: Guard business orchestrate + LLM proxy

**Files:**
- Modify: `server/mcp_server.py` `_handle_orchestrate_api`、`/api/llm/chat`（及必要的文件 API）
- Modify: `server/http_api_extra.py` `handle_orchestrate` 接受 `case_id` / `user_id`（若只需在入口校验则可只改 mcp_server）
- Test: `tests/test_orchestrate_auth.py`

**Rules:**
- 无 token → 401
- 无 `case_id` → 400（业务）
- 缺 `cap.chat`（或编排对应 cap）→ 403
- 断案路径额外要 `cap.judge`（若编排入口统一 `cap.chat`，则 orchestrate 至少 `cap.chat`；细粒度可在 plan agent 后再加——**首期 orchestrate 要求 `cap.chat`，文书生成要求 `cap.doc_write` 在 doc_writing 分支前校验**）

- [ ] Implement + test + commit `feat(api): require auth and case-scoped caps on orchestrate`

---

### Task 6: Frontend login + auth.js

**Files:**
- Create: `login.html`, `auth.js`
- Modify: `index.html` / `home.html` / `mcp_client.html` 引入鉴权跳转
- Modify: `admin_nav.js` 未登录跳转 login

**auth.js API:**
- `getToken()`, `setSession(payload)`, `clearSession()`, `authHeaders()`, `requireLogin()`, `fetchMe()`

- [ ] Implement login form → POST `/api/auth/login` → localStorage
- [ ] Commit `feat(ui): add login page and client auth helper`

---

### Task 7: Admin UI — users, roles, permissions, cases

**Files:**
- Create: `admin_users.html`, `admin_roles.html`, `admin_perms.html`, `admin_cases.html`
- Modify: `admin_nav.js`, `admin.css`, `admin_ui.js`（复用 drawer）

- [ ] 用户：列表、创建、启停、分配所级角色（director/admin_officer）
- [ ] 角色：展示五角色、勾选 permissions 保存
- [ ] 功能：列表编辑 name/group
- [ ] 案件：CRUD + 成员分案（选用户 + partner/lead_lawyer/assistant）
- [ ] Commit `feat(admin): RBAC and case assignment admin pages`

---

### Task 8: Chat/home case picker + wire token

**Files:**
- Modify: `mcp_client.js`, `home.js`（fetch 带 Authorization；orchestrate body 加 `case_id`）
- UI：当前案件下拉（`GET /api/admin/cases?mine=1` 或 `/api/cases/mine`）

- [ ] 无案件时提示先选案件；请求失败 401 跳转登录
- [ ] Commit `feat(chat): send auth token and case_id with orchestrate`

---

### Task 9: Smoke script + docs touch

**Files:**
- Create: `tests/test_rbac_smoke.py`（内存/临时 db 全流程）
- Modify: `config.example.json` 增加 `"auth": {"rbac_db": "./rbac.db"}` 说明字段（无密钥）

- [ ] 冒烟：主任登录 → 建用户行政主管 → 建案分给主办 → 主办 token+case 有 judge；行政主管无 judge
- [ ] Commit `test(rbac): end-to-end permission smoke`

---

## Spec coverage check

| Spec section | Tasks |
|--------------|-------|
| 所级/案级双轨 | 1, 3 |
| 五角色 + 行政主管 | 1, 7 |
| 入案定角色 | 3, 4, 7 |
| 登录 PBKDF2 | 2, 6 |
| Admin CRUD API | 4, 7 |
| 业务拦截 | 5, 8 |
| 默认矩阵可改 | 1, 4, 7 |
| 主任/行政不入 case_members | 3 |

## Execution

Preferred after plan save: **Inline Execution**（用户已要求先开发）或 Subagent-Driven。
