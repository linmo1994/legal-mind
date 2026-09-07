# 律所私有化 · 办案阶段 + 文书审批流（设计）

**日期：** 2026-09-07  
**分支建议：** `feat/approval-flow`（可与现有模版填表能力并存）  
**状态：** 已定稿待实现计划  

## 背景与目标

LegalMind 面向**律所私有化部署**。现状已具备：所级/案级 RBAC、案件与材料、对话编排（Plan-and-Execute）、知识库模版匹配与要素式 Word 填表、文书 `artifact` 下载。

缺失的是把 AI 产出纳入**所内办案制度**：案件阶段可强制流转、文书须经审核方可定稿对外、操作可审计。

本设计落地「薄切面」：**五阶段案件机 + 两级文书审批（助理 → 主办 → 合伙人）+ 产物状态 + 待办 + 基础审计 + 鉴权补强**。

### 已确认决策

| 项 | 选择 |
|----|------|
| 范围 | 文书审批（A）+ 办案全流程（B），一期做薄切面贯通 |
| MVP 切法 | 粗阶段 + 一条起诉状/代理词类审批链打通 |
| 审批深度 | 两级：assistant → lead_lawyer → partner |
| 案件阶段 | 五阶段（含「材料完备」） |
| 实现路径 | **文书产物审批**：在 `draft_doc` artifact 上挂状态与任务，非通用 BPM、非纯对话内审批 |
| AI 与审批关系 | AI 产出默认 `draft`；**须人工点击「提交审核」**，不自动进待办 |

### 成功标准（合伙人）

所内任何对外文书，都能查出：**谁起草、谁审、哪一版、何时通过**。未 `approved` 的文书不得以「定稿」身份对外发出。

### 非目标（一期）

- 通用可配置 BPM / 会签或签引擎  
- 客户门户、法院电子送达、计费工时  
- AI 模拟审判产品化（可挂 P2）  
- 多租户 SaaS；一期按单所私有化单库  

---

## 现状与缺口

**可复用**

- 案级角色：`partner` / `lead_lawyer` / `assistant`（`server/rbac_store.py`）  
- 案件、材料、`case_context` 注入编排  
- `draft_doc` → Word `artifact`（`file_id` / preview / download）  
- 管理端案件/用户/权限页  

**缺口**

- 无审批状态机、待办队列、文书版本签核  
- 案件 `status` 仅为标签，无强制迁移与门禁  
- 无审计事件表  
- 会话与 `/api/files` 鉴权偏弱（私有化安全底线必须补）  

---

## 领域模型

### 1. CaseStage（案件阶段）

五阶段（逻辑名；实现可映射或替换现有 status 字段）：

| 阶段 | 说明 |
|------|------|
| `intake` | 收案/分案（成员已指定） |
| `materials_ready` | 材料完备（合同/证据清单达到所设门槛） |
| `strategy_docs` | 策略与文书（可发起/进行审批） |
| `litigation` | 诉讼推进（开庭前后等） |
| `closed` | 结案归档 |

**规则（一期）**

- 仅允许相邻前进（可配置是否允许 partner 回退一档）。  
- 推进权限：`lead_lawyer` / `partner` / 所级 `director`。  
- 进入 `strategy_docs`：默认要求已达 `materials_ready`；director/partner 可「豁免并留审计」。  
- AI 编排不自动改阶段；由人在案件台或工作台推进。  

### 2. DocArtifact（文书产物）

绑定：`case_id`、`file_id`、`version`、`title`、`doc_type`（如起诉状）、`created_by`、`source`（`ai_draft_doc` | `upload`）。

**审批状态**

`draft` → `pending_lead` → `pending_partner` → `approved`  
任意待审节点可 → `rejected`（回到 `draft`，保留意见与历史版本）。

**版本**

- 每次「提交审核」锁定当前 `file_id` 为该 version 的不可变快照引用（文件本身不改写；驳回后新编辑生成新 version / 新 file_id）。  
- `approved` 版本标记为定稿；同案同 `doc_type` 可允许多定稿（代理词修订）但 UI 默认展示最新 approved。  

### 3. ApprovalTask（待办）

字段：`artifact_id`、`case_id`、`assignee_user_id`、`step`（`lead` | `partner`）、`status`（`open` | `done` | `cancelled`）、`decision`（`approve` | `reject` | null）、`comment`、时间戳。

创建规则**

- 助理或主办在 `draft` 上「提交审核」→ 创建 `pending_lead` 任务，指派案的 `lead_lawyer`（若提交人已是 lead，可跳过 lead 步直接 `pending_partner`——**采用：lead 自提则跳过本级**）。  
- lead 通过 → `pending_partner`，指派案的 `partner`。  
- partner 通过 → `approved`。  
- 任一级驳回 → `rejected`/`draft`，写 comment，取消下游 open 任务。  

### 4. AuditEvent（审计）

最小事件：`actor_user_id`、`action`、`object_type`、`object_id`、`case_id`、`detail_json`、`created_at`。

一期必记：登录失败/成功（可选）、提交审批、通过、驳回、定稿下载、阶段推进、材料豁免、编排生成文书。

---

## 权限与角色

| 动作 | assistant | lead_lawyer | partner | director |
|------|-----------|-------------|---------|----------|
| AI 起草 / 保存 draft | ✓ | ✓ | ✓ | ✓（可关） |
| 提交主办审 | ✓ | ✓ | — | — |
| 主办通过/驳回 | — | ✓ | — | — |
| 合伙人终审 | — | — | ✓ | 可代审（配置项，默认开） |
| 推进案件阶段 | — | ✓ | ✓ | ✓ |
| 材料完备豁免 | — | — | ✓ | ✓ |
| 定稿下载（无水印） | 案内成员可读 | 同左 | 同左 | ✓ |
| 全所审计查询 | — | — | 案内 | ✓ |

新增能力码（建议）：`cap.doc_submit`、`cap.doc_approve_lead`、`cap.doc_approve_partner`、`cap.case_stage_advance`、`cap.audit_read`。

---

## 与智能体的挂接

1. `draft_doc` 成功且存在 `case_id` 时：写入 `DocArtifact(version=1, status=draft)`，聊天卡片增加「提交审核」。  
2. 无 `case_id`：仍可下载（现状行为），但提示「未绑定案件，无法进入所内审批」；不创建 ApprovalTask。  
3. 编排过程（SSE workflow）**不等于**业务审批流；UI 文案区分「执行过程」与「审批进度」。  
4. 定稿策略（已拍板默认）：  
   - **仅 `approved` 提供「定稿下载」主按钮**；  
   - `draft` / 在审版本可「预览 / 下载工作稿」，文件名或页眉带「未定稿」标识（实现可用文件名后缀 `_草稿`，docx 页眉二期再做）。  

---

## 用户旅程（薄切面）

1. 主任/主办分案（intake）→ 上传材料 → 勾选完备 → `materials_ready`。  
2. 助理在对话选中案件，生成要素式起诉状 → 得 Word 卡片（draft）。  
3. 助理点「提交审核」→ 主办待办 → 通过 → 合伙人待办 → 通过 → approved。  
4. 主办下载定稿对外；审计可查全链。  
5. 案件进入 `litigation` → 最终 `closed`。  

---

## 分期计划

### P0（约 6～10 周）— 必须交付

1. CaseStage 五阶段状态机 API + 案件台 UI  
2. DocArtifact + ApprovalTask 模型与 API  
3. 两级审批动作 + 「我的待办」页  
4. 聊天 artifact 卡片：状态、提交审核、定稿/工作稿下载分流  
5. AuditEvent 写入与主任只读查询（最小）  
6. 会话绑定 `user_id`；`/api/files` 按登录用户与案件权限校验  

### P1（+6～8 周）

1. 材料完备清单门禁与豁免审计  
2. 驳回意见在案件时间线/对话可见  
3. 站内通知（邮件可选）  
4. 权限码细化与管理端配置 director 代审开关  
5. 简单报表：在审时长、驳回率  
6. 私有化运维清单：备份、升级、日志轮转  

### P2（按所定制）

1. 多文书类型审批预设  
2. 会签/或签、加签  
3. AI 模拟审判模块产品化  
4. 多办公室分库、OA 对接  

---

## 数据与 API 草图（实现约束）

- 表：`case_stages` 或扩展 `cases.status` + `cases.stage_updated_at`；`doc_artifacts`；`approval_tasks`；`audit_events`。  
- API 前缀建议：`/api/cases/{id}/stage`、`/api/artifacts`、`/api/approvals/inbox`、`/api/approvals/{id}/decide`、`/api/audit`。  
- 所有写操作写审计；审批决定幂等（重复通过返回当前状态）。  

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 待办无人处理 | P1 通知；P0 UI 突出「我的待办」入口 |
| AI 频繁出稿刷待办 | 禁止自动提交；仅人工提交 |
| 无 partner 的案 | 创建案件已要求 partner；缺失时提交失败并提示分案 |
| 鉴权补强影响现网脚本 | 保留服务账号或 director 测试账号；发版说明 |
| 与模版填表并行开发冲突 | 审批挂 artifact 层，少改 `docx_form_fill` 内核 |

---

## 测试要点（设计层）

- 助理不能终审；lead 自提跳过 lead 步。  
- 驳回后版本可再提；旧 pending 任务取消。  
- 无 case_id 不产生审批任务。  
- 未 approved 不出现「定稿下载」主按钮。  
- 非案内用户无法下载该案文件。  
- 阶段不能从 intake 直接跳到 closed（除非 director 强制并审计——一期可不做强制跳，只禁止非法迁移）。  

---

## 开放配置项（实现时用开关，默认如下）

| 配置 | 默认 |
|------|------|
| director 可代合伙人终审 | 开 |
| lead 提交跳过本级 | 开 |
| 无案件时允许工作稿下载 | 开 |
| 材料门禁强制 | P0 可先不做强制，P1 开启；P0 阶段仍保留 `materials_ready` 供手工推进 |
