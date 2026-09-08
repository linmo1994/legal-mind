# 我的待办工作台 · 驳回感知 + 我的案件（设计）

**日期：** 2026-09-08  
**状态：** 待用户审阅 spec  
**前置：** `2026-09-07-law-firm-trial-approval-flow-design.md`（P0 审批流已落地）  
**分支建议：** `feat/approval-flow`（或后续 `feat/approvals-workbench`）

## 背景与目标

P0 已具备：文书审批链、右上角「我的待办」入口（`approvals.html`）、待我审批列表。缺口：

1. **驳回后发起人感知弱**：无通知、不进发起人待办，仅靠对话卡片偶然发现。  
2. **待办页缺少「我的案件」**：主办/助理无法在同一处看到与自己相关的案件及阶段。

本期把 `approvals.html` 升级为**办案工作台**，并补齐驳回强提醒（每条驳回仅强提醒一次）。

### 已确认决策

| 项 | 选择 |
|----|------|
| 实现路径 | 扩展「我的待办」+ `GET /api/approvals/workbench`（方案 1） |
| 驳回感知 | 列表 + 角标 + **进入系统弹窗一次/条**（确认后同条不再弹） |
| 已读存储 | 服务端 `rejection_acks`（跨设备） |
| 我的案件 | 只读列表 + **进入对话并自动绑案**；不在此推进阶段 |
| 入口 | 保持右上角账号下拉「我的待办」 |

### 成功标准

- 发起人在被驳回后，下次进入壳层必能看到一次明确弹窗，且待办页有「需我处理」与驳回意见。  
- 角标反映：待我审批数 + 尚未 ack 的被驳回数。  
- 任意案内成员可在「我的案件」看到案号、阶段、本人角色，并可一键进对话绑案。

### 非目标

- 邮件 / 微信 / 通用通知中心  
- 待办页内编辑 Word 或代点「提交审核」  
- 待办页推进案件阶段  
- AI 对话内审批  

---

## 用户流

### 驳回感知

1. 审批人驳回 → `doc_artifacts` 回 `draft`，写入 `reject_comment`；当前/下游 open 任务结束。  
2. 发起人打开壳层（已登录）：若存在 `created_by=自己` 且带 `reject_comment` 的草稿，且该 `artifact_id` **尚未 ack** → 弹窗一次（可汇总多条）。  
3. 「去处理」→ `approvals.html`（并 ack 所涉条目，或进入页后再 ack）；「知道了」→ 仅 ack，关闭弹窗。  
4. 角标：`pending_tasks` + 未 ack 的 `rejected_mine`。ack 后角标不再计该条；**列表仍显示**直至重提成功。  
5. 再次 `submit` 成功 → 离开 `rejected_mine`；若再次被驳回 → 清除该 artifact 的 ack，可再弹一次。

### 我的案件

- 列表展示成员案件；点击「进入对话」→ `mcp_client.html?case_id=` 并 `LegalMindAuth.setCaseId(caseId)`。

---

## 页面结构（`approvals.html`）

自上而下三块：

1. **待我审批** — 同现 inbox：通过 / 驳回 / 下载工作稿。  
2. **需我处理（被驳回）** — 案号、标题、驳回意见、时间；操作：打开对话（绑案）、下载工作稿。可选「我知道了」ack。  
3. **我的案件** — 案号、标题、`stage_label`、`my_role_label`；操作：进入对话。

无管理后台权限要求；仅需登录。

---

## API

### `GET /api/approvals/workbench`

需登录。响应：

```json
{
  "pending_tasks": [],
  "rejected_mine": [
    {
      "artifact_id": 1,
      "case_id": 2,
      "case_no": "…",
      "title": "…",
      "reject_comment": "…",
      "updated_at": "…",
      "file_id": "…",
      "ack": false
    }
  ],
  "my_cases": [
    {
      "id": 2,
      "case_no": "…",
      "title": "…",
      "stage": "strategy_docs",
      "stage_label": "策略与文书",
      "my_role": "assistant",
      "my_role_label": "助理"
    }
  ],
  "badge_count": 3
}
```

- `pending_tasks`：同 `list_open_tasks_for_user`（可含 `file_id`）。  
- `rejected_mine`：`created_by = 当前用户` AND `approval_status = draft` AND `reject_comment` 非空。  
- `my_cases`：`list_cases_for_user(mine)` + `enrich` 阶段/角色文案。  
- `badge_count` = `len(pending_tasks)` + 未 ack 的 `rejected_mine` 数。  
- 可选：`?badge_only=1` 仅返回 `{ "badge_count": N }` 供壳层轮询。

### `POST /api/approvals/rejects/{artifact_id}/ack`

- 校验：登录；artifact 存在；`created_by == 当前用户`；当前为被驳回草稿。  
- 写入/更新 `rejection_acks(user_id, artifact_id, acked_at)`。  
- 返回 `{ "ok": true }`。

### 兼容

保留 `GET /api/approvals/inbox`。壳层角标与工作台页改用 `workbench`。

---

## 数据模型

```text
rejection_acks (
  user_id INTEGER NOT NULL,
  artifact_id INTEGER NOT NULL,
  acked_at TEXT NOT NULL,
  PRIMARY KEY (user_id, artifact_id),
  FOREIGN KEY (artifact_id) REFERENCES doc_artifacts(id) ON DELETE CASCADE
)
```

二次驳回（`decide(reject)`）：删除该 `artifact_id` 上所有 ack（或至少发起人的），以便再次强提醒。

---

## 壳层（`index.html`）

- 登录后 `syncShellNav`：请求 workbench（或 badge_only）更新角标。  
- 若存在 `rejected_mine` 中 `ack === false`：弹窗列出摘要（标题 + 意见截断）；按钮「去处理」/「知道了」。  
- 对展示的每条调用 ack（或批量 ack API——一期可循环单条）。  
- 「去处理」：`loadPage('approvals.html')`。

---

## 测试要点

- 单元/API：workbench 字段；ack 权限；二次驳回清 ack；badge_count 计算。  
- 手动：§3 验收五步（见对话确认）。

---

## Spec 自检

- 无 TBD / 占位实现。  
- 与 P0 审批状态机一致（驳回 → draft + comment）。  
- 范围不含邮件与阶段推进。  
- 弹窗与列表职责清晰：弹窗管「首次感知」，列表管「持续处理直到重提」。
