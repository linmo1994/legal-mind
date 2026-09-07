# 编排 SSE 逐步刷新设计

**日期：** 2026-09-06  
**状态：** 已实现（2026-09-06 SSE 冒烟通过：stream step + Content-Type event-stream）  
**分支建议：** `feat/agent-orchestration-loop`  
**范围：** 编排路径用 SSE 推送 `emit_step` 事件；前端实时刷新 Busy 阶段、编排工作台、气泡内短过程条；最终 `done` 落完整结果。

**相关：**  
- Busy：`docs/superpowers/specs/2026-09-06-chat-busy-loading-design.md`  
- 工作台 / 抽屉：`docs/superpowers/specs/2026-09-06-orchestrate-drawer-tab-design.md`  
- 时间线折叠：`docs/superpowers/specs/2026-09-06-orchestrate-timeline-collapse-design.md`  
- PnE：`docs/superpowers/specs/2026-09-05-plan-and-execute-design.md`

---

## 1. 背景与目标

### 现状

- 后端 `_handle_orchestrate_api` 在 `stream: true`（或 query `stream=1`）时已返回 `text/event-stream`：  
  - `data: {"type":"step", …emit_step 字段}`  
  - 结束：`data: {"type":"done","result":{…现有 orchestrate JSON}}`  
- `WorkflowTracer(on_event=…)` 在每次 `emit_step` 时同步回调。  
- 前端 `tryHandleOrchestrate` 仍 `fetch` + `resp.json()`，长请求期间只有 Busy 占位，工作台/气泡过程要等整轮结束。

### 目标

1. 编排请求默认走 SSE（`stream: true`）。  
2. 收到 `step` 即更新：**Busy 阶段**、**编排工作台时间线/计划**、**气泡内短过程条**（同源 `liveFlow`）。  
3. 收到 `done` 后走现有 `applyOrchestrateSuccess`（答案、引用、docx、resume、外源 hint 等），再与最终 `capabilities.flow` 对齐一次。  
4. Abort 中断 fetch 流；失败可展示重试（与现编排失败一致）。

### 非目标

- 模型「思考 token」流式展示（reasoning）。  
- WebSocket / 另开 GET EventSource。  
- 单步重跑、改计划。  
- 改 PnE 工具语义或预算。  
- 非编排经典 LLM 流式路径改造。  
- 强制补齐所有 step 的入参/耗时字段（可用现有 `detail`；缺则不显示）。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 范围 | B：Busy + 工作台 + 气泡短过程条 |
| 实现 | 方案 1：POST + `stream:true` + fetch 读 SSE；复用现有后端 |
| 数据源 | 一份 `liveFlow[]` 三处派生 |
| 气泡短条 | 最近 3～5 条；徽章+名称；current/running 可转圈 |
| 收尾 | `done.result` 全量渲染；短条可收起/弱化，完整过程在工作台 |
| 兼容 | 保留非 stream JSON 路径（测试/旧客户端）；产品 UI 默认 stream |

---

## 3. 协议

### 3.1 请求

```http
POST /api/orchestrate
Content-Type: application/json
Authorization: Bearer …
Accept: text/event-stream   # 可选，便于代理识别

{
  "user_text": "...",
  "session_id": "...",
  "messages": [...],
  "case_id": "...",
  "stream": true,
  "resume_state": { ... }   // 可选
}
```

### 3.2 事件

**step**（与 `emit_step` / tracer 项对齐）：

```json
{
  "type": "step",
  "kind": "tool|kb|skill|mcp|plan|plan_step|agent|external|...",
  "id": "draft_doc",
  "name": "文书起草",
  "status": "running|done|...",
  "detail": { }
}
```

**done：**

```json
{
  "type": "done",
  "result": { /* 与今日非 stream 的 orchestrate 响应体相同 */ }
}
```

**error（本期补齐，推荐）：**

若编排抛错且已进入 SSE 头，写一条后关闭流：

```json
{ "type": "error", "error": "任务编排失败", "detail": "..." }
```

未进入 SSE 的鉴权失败仍返回普通 JSON（与现网一致）。

### 3.3 客户端解析

- 按行缓冲，识别 `data: ` 前缀，JSON.parse。  
- 忽略空行与未知 `type`（打日志即可）。  
- `AbortError` → Busy `end(abort)`，不弹重试（或与现 abort 行为一致）。  
- 流结束却无 `done` → 视为 error。

---

## 4. 前端架构

```text
tryHandleOrchestrate
  → BusyController.start
  → fetch(stream:true, signal)
  → readSseOrchestrate(reader)
       onStep(event) → mergeLiveFlow → refreshBusy + refreshWorkbench + refreshInlineStrip
       onDone(result) → applyOrchestrateSuccess + clear/settle strip
       onError → retry UI / Busy end(error)
```

### 4.1 `liveFlow` 合并规则

- 追加新事件；若同 `(kind, id)` 且先后为 `running`→`done`，更新同一条目的 `status`/`detail`（避免时间线刷出重复 running+done 两行，除非 id 不同）。  
- `kind===plan`：同时更新工作台计划区（`detail.steps` 若有）。  
- Busy：优先用 `buildBusyStagesFromOrchestrate({ capabilities: { flow: liveFlow } })`；若映射为空则保持占位三步。

### 4.2 气泡短过程条

- 挂在回答正文**之上**的 `orchestrate-flow-slot`。  
- **等待 / SSE 中：展开**为「本轮过程」面板（标题 + 最近最多 5 条；可含 waiting 态）。  
- **`done` 后：自动收起**为「本轮过程 · N 步」摘要（可点开气泡内展开）；**不**自动打开底部抽屉。  
- 完整计划/时间线由底部 Tab「本轮过程」打开抽屉查看。  
- 无障碍：`aria-live="polite"`。

### 4.3 工作台

- 有进行中的编排 turn 时，将 `liveFlow` 写入该 turn 的 view，调用现有 `renderOrchestrateWorkbench` / timeline builder。  
- `done` 后用 `result` 全量重建 view（plan、past_steps、citations、artifact、external_search），覆盖 live 态，避免双真相。

### 4.4 Busy

- `start` 时占位三步。  
- 每个 step 后 `BusyController.updateStages(...)`。  
- `done`/`error`/`abort` 时 `end`（成功路径在应用答案前或后移除阶段，与现行为一致）。

---

## 5. 后端小改（最小）

现有 stream 路径已基本可用。本期建议：

1. **SSE error 事件**：`_handle_orchestrate_api` 在 `want_stream` 分支的 `except` 中，若响应头已发送，写 `type:error` 而非再 `_write_json`。  
2. （可选）文档化 `stream` 字段；**不强制**改 `emit_step` 粒度。  
3. 非 stream JSON 行为保持不变，便于单测。

---

## 6. 测试与验收

### 自动化

- 后端：mock `handle_orchestrate` + 假 `on_event`，断言 stream 分支写出至少一条 `step` 与一条 `done`（可用 handler 级或抽纯函数测写入格式）。  
- 前端：纯函数测 `mergeLiveFlow`、短条截断 5 条（若抽到可测模块；否则用 CDP）。

### 手工 / CDP

1. 发编排问题：1s 内见 Busy；随后工作台/气泡短条出现真实 step（不必等整轮结束）。  
2. 停止生成：流中断，Busy 收尾，无卡死 spinner。  
3. 成功：答案、引用、docx（若有）与今日一致；工作台与最终 flow 一致。  
4. 硬刷新 `?v=` 后无旧缓存。

---

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 代理缓冲 SSE | `Cache-Control: no-cache` 已有；必要时 `X-Accel-Buffering: no` |
| BaseHTTPRequestHandler 阻塞 | 与现网一致；本期不换 ASGI |
| 半包 JSON | 行缓冲，仅完整 `data:` 行解析 |
| live 与 done 不一致 | `done` 全量覆盖 view |

---

## 8. 实现顺序建议

1. SSE 读流工具 + `mergeLiveFlow`（可测）  
2. `tryHandleOrchestrate` 改 stream，接 Busy / workbench  
3. 气泡短过程条 UI  
4. 后端 SSE error 补齐  
5. 冒烟 + cache-bust
