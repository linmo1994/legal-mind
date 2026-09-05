# 多轮对话编排失败「重试」按钮设计

**日期：** 2026-09-05  
**状态：** 已定稿  
**范围：** `mcp_client` 多轮对话中 `/api/orchestrate` 失败后的可重试 UI。

---

## 1. 背景与目标

### 现状

- `tryHandleOrchestrate`：400/403 在进度壳内写错误文案，无重试。
- 网络异常等会 `catch` 后移除壳并 `return false`，静默回退单智能体路径，用户不易感知「服务挂了，修好后可再试」。
- 401 跳转登录。

### 目标

1. 编排调用失败时，在该轮助手气泡内展示错误说明 + **「重试」按钮**。
2. 点击重试：用**同一句用户问题**再次请求 `/api/orchestrate`，不重复插入用户消息。
3. 除 **401** 外，各类编排失败均提供重试（含 4xx/5xx、超时、网络错误、响应解析失败等）。
4. 明确失败时**不再**静默落入单智能体 fallback（`legacy` 除外）。

### 非目标

- 首页单轮会话重试。
- 自动轮询重试（仅用户点击）。
- 改变后端错误码语义。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 交互 | 失败气泡下「重试」按钮（非页签） |
| 覆盖 | 除 401 外所有编排失败 |
| 重试载荷 | 缓存的 `fullUserMessage` + 当前 session/case |
| 失败与 fallback | 明确失败保留壳+重试；仅 `legacy` 回退旧路径 |

---

## 3. 行为细节

### 3.1 失败判定

在 `tryHandleOrchestrate` 中视为失败并展示重试：

- `fetch` 抛错（网络、CORS、断连）
- 超时 / Abort（非用户主动停止，若可区分）
- HTTP 状态非 2xx 且非 401（含 400/403/404/5xx）
- 响应体非 JSON 或缺少可用内容且非 `legacy`
- 其它未捕获异常

**401：** 移除壳 → 登录页；不显示重试。

**`data.legacy === true`：** 移除壳 → `return false` 走旧路径（保持兼容）。

### 3.2 UI

- 复用 `addOrchestrateProgressShell` 产生的助手消息壳。
- `answer`（或专用 `error` 区）显示：`errBody.error` 或友好文案（如「服务暂时不可用，请稍后重试。」）。
- 其下按钮：`重试`（class 如 `orchestrate-retry-btn`）。
- 重试进行中：按钮 `disabled`，文案「重试中…」；可清空/保留错误区。
- 可选：工作流槽显示「调用失败」状态（不强制完整 flow）。

### 3.3 重试逻辑

```text
onRetry:
  disable button
  POST /api/orchestrate { user_text: cachedMessage, session_id, messages, case_id }
  success → paint flow + answer + citations（与成功路径相同）；去掉重试按钮
  fail again → 更新错误文案；恢复「重试」按钮
```

- 闭包保存 `fullUserMessage`；`messages` 取点击时的 `conversationHistory`（未写入本轮失败助手消息为佳）。
- 成功后再写入 session history（与现成功路径一致）；失败不写助手成功内容。

### 3.4 与 `handleUserMessage` 的关系

- `tryHandleOrchestrate` 在失败展示重试后应 **`return true`**，避免再走单智能体。
- 仅 `legacy` / 明确「不处理」时 `return false`。

---

## 4. 实现落点

| 文件 | 改动 |
|------|------|
| `mcp_client.js` | `tryHandleOrchestrate` 错误分支；`renderOrchestrateRetry(shell, message, errText)` |
| `mcp_client.css` | 重试按钮样式（贴合现有 cite/ghost 按钮） |

---

## 5. 验收

1. 停掉 MCP 后发问 → 见错误 +「重试」，不出现「假成功」单智能体长答（除非 legacy）。  
2. 恢复 MCP 后点「重试」→ 正常编排回答，用户侧不出现重复气泡。  
3. 400/403 同样有重试；401 进登录。  
4. 重试中按钮不可连点。

---

## 6. 风险

| 风险 | 缓解 |
|------|------|
| 失败仍 fallback 造成双路径 | 失败统一 `return true` |
| 历史写入时机 | 仅成功写入 assistant |
