# LegalMind RBAC 与案级权限设计

日期：2026-09-04  
状态：待用户审阅  

## 1. 目标

在管理后台实现完整 RBAC（用户、角色、功能），并覆盖业务能力控制。权限分为两轨：

- **所级**：律所主任、行政主管 — 用户绑定角色，角色绑定功能；可管后台与分案，不依赖入案。
- **案级**：合伙人、主办律师、助理 — **入案时指定角色**（人 ↔ 案件 ↔ 角色），角色再绑定功能；仅在该案件上下文中生效。

## 2. 范围

**本期包含**

- 本地账号密码登录（SQLite + token 会话）
- 用户 / 角色 / 功能 / 案件（含分案）管理页与 API
- 页面入口 + 能力点双重控制（前端显隐 + 服务端强制校验）
- 对话等业务 API 要求登录，并携带或绑定 `case_id` 后按案级权限校验
- 内置五角色种子与默认可改权限矩阵

**本期不包含**

- 企业 SSO / OAuth
- 一人一案多角色（首期一人一案一个角色；表结构可后续扩展）
- 细粒度字段级 ACL、审计日志产品化（可留扩展点）

## 3. 角色定义

| 角色 code | 名称 | 轨 | 说明 |
|-----------|------|-----|------|
| `director` | 律所主任 | 所级 | 全所最高权限；任命行政主管；用户/角色/功能/案件/分案；可代操作业务 |
| `admin_officer` | 行政主管 | 所级 | 由主任分配所级角色；不办案；案件管理与分案；无断案/文书终稿写权限 |
| `partner` | 合伙人 | 案级为主 | 通过入案角色获得业务能力 |
| `lead_lawyer` | 主办律师 | 案级为主 | 通过入案角色获得业务能力 |
| `assistant` | 助理 | 案级为主 | 通过入案角色获得业务能力（偏检索与辅助） |

内置角色不可删除，可调整其功能绑定。可扩展自定义角色（可选，首期以五类内置为主）。

**约定**：主任与行政主管 **不写入** `case_members`；办案权限仅通过所级特权或（主任）显式代操作策略，行政主管默认不可写断案/文书。

## 4. 数据模型

持久化：SQLite，与现有会话库同库或并列 `rbac` 表前缀，便于备份。

| 表 | 用途 |
|----|------|
| `users` | id, username, password_hash, display_name, is_active, created_at, must_change_password |
| `roles` | id, code, name, is_system, track (`firm` \| `case`), description |
| `permissions` | id, code, name, kind (`page` \| `capability`), group_name, description |
| `user_roles` | user_id, role_id（所级多角色，权限取并集） |
| `role_permissions` | role_id, permission_id |
| `auth_sessions` | token, user_id, expires_at, created_at |
| `cases` | id, case_no, title, status, created_by, created_at, updated_at, meta_json |
| `case_members` | user_id, case_id, role_id, assigned_by, assigned_at；**UNIQUE(user_id, case_id)** |

### 4.1 权限码（code 稳定，后台可改显示名）

**页面（page）**

- `page.home`、`page.chat`
- `page.admin`、`page.admin.users`、`page.admin.roles`、`page.admin.perms`、`page.admin.cases`
- `page.admin.skills`、`page.admin.mcp`、`page.admin.vectorize`

**能力（capability）**

- `cap.user_manage`、`cap.role_manage`、`cap.perm_manage`
- `cap.case_manage`、`cap.case_assign`
- `cap.skill_manage`、`cap.mcp_manage`、`cap.vectorize`
- `cap.chat`、`cap.judge`、`cap.doc_write`、`cap.retrieve`

### 4.2 默认权限矩阵（可在功能/角色管理中修改）

| 能力 | 主任 | 行政主管 | 合伙人 | 主办律师 | 助理 |
|------|------|----------|--------|----------|------|
| 用户/角色/功能管理 | ✓ | | | | |
| 案件管理 / 分案 | ✓ | ✓ | | | |
| 技能 / MCP / 向量化 | ✓ | ✓ | | | |
| 对话 | ✓ | 只读概览可选 | ✓（案级） | ✓ | ✓ |
| 断案 | ✓ | | ✓ | ✓ | |
| 文书终稿 | ✓ | | ✓ | ✓ | |
| 检索 | ✓ | | ✓ | ✓ | ✓ |

案级三角色的业务勾选写在 `role_permissions` 上；用户未入案时不获得这些能力（即使用户被误挂所级办案角色，产品上仍以入案为准——所级 `user_roles` 对 partner/lead/assistant 默认不授业务 cap，仅授 `page.home` 等必要入口）。

## 5. 权限解析

```
effective_firm(user) = ∪ permissions(all roles in user_roles)
effective_case(user, case_id) = permissions(role on case_members for (user, case_id))
effective(user, case_id?) = effective_firm(user) ∪ (effective_case if case_id else ∅)
```

请求校验：

1. 无有效 token → 401  
2. 管理类 API：需要对应 `cap.*` / `page.*` ∈ `effective_firm`  
3. 业务类 API：需要 `case_id`（案件上下文）；需要对应 `cap.*` ∈ `effective(user, case_id)`  
   - 主任因所级角色带有 `cap.judge` 等，可不入案即可在指定案件上操作  
   - 行政主管所级角色不授予写类业务 cap，故即使有 `case_id` 也不能断案/出文书  
   - 合伙人/主办/助理的业务 cap 来自入案角色，未入案则为空  
4. 列表「我的案件」：默认仅 `case_members` 中自己的案件；拥有 `cap.case_manage` 者可看全所案件  

## 6. API

### 认证

- `POST /api/auth/login` `{username, password}` → `{token, user, firm_roles, firm_permissions}`
- `POST /api/auth/logout`
- `GET /api/auth/me?case_id=` → 所级权限；若带 case_id 则附加 `case_role`、`case_permissions`

请求头：`Authorization: Bearer <token>`

### 管理（均需登录 + 所级能力）

- `/api/admin/users` CRUD、启停、重置密码、设置 `user_roles`
- `/api/admin/roles` 列表、更新描述、替换 `role_permissions`（系统角色不可删）
- `/api/admin/permissions` 列表、更新 name/group/description（code 只读）
- `/api/admin/cases` CRUD
- `/api/admin/cases/:id/members` 分案：增删改 `(user_id, role_id)`；角色必须为案级角色（partner/lead_lawyer/assistant）

### 业务

- 现有 `/api/orchestrate`、LLM 代理、检索等：强制登录；body/query/会话绑定 `case_id`；按第 5 节校验 `cap.chat` / `cap.judge` / `cap.doc_write` / `cap.retrieve` 等

## 7. 前端

- `login.html`：登录；成功后存 token  
- 管理：`admin_users.html`、`admin_roles.html`、`admin_perms.html`、`admin_cases.html`；`admin_nav.js` 按所级权限显隐  
- 业务：首页/对话页登录门禁；对话区 **当前案件选择器**（我的入案列表；有 `cap.case_manage` 者可看全所并分案入口）  
- 无权限入口隐藏；API 仍返回 403

## 8. 安全

- 密码：PBKDF2 或 bcrypt 哈希，禁止明文  
- Token 随机、服务端存哈希或明文 token+过期（首期可存 token 哈希）  
- 种子主任账号首次部署创建（如 `director` / 初始密码），`must_change_password` 建议为 true  
- 分案 API 拒绝将 `director` / `admin_officer` 写入 `case_members`

## 9. 测试

- 单元：所级并集、案级解析、主任/行政主管特权边界  
- API：登录失败、401/403、分案校验、无 case_id 业务拒绝  
- 冒烟：主任任命行政主管 → 行政主管分案给主办 → 主办在案内断案成功、案外失败；助理无文书权限

## 10. 实现落点（相对现仓库）

- 新服务模块：如 `server/rbac_service.py`、`server/auth_service.py`  
- HTTP：`mcp_server.py` / `http_api_extra.py` 注册路由与中间件式校验  
- 静态页：与现有 `admin_*.html` 风格一致  
- 配置：`config.example.json` 可增加 auth 相关说明（不含密钥明文提交）

## 11. 成功标准

1. 后台可管理用户、五类角色绑定、功能点、案件与分案  
2. 未登录无法使用管理与业务敏感 API  
3. 案级用户仅在入案且角色允许时使用对应业务能力  
4. 行政主管能分案、不能以办案身份出断案/文书终稿  
5. 默认矩阵可在角色-功能管理中调整并立即生效
