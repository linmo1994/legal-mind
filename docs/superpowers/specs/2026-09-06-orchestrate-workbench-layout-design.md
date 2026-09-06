# 多轮对话编排工作台布局设计

**日期：** 2026-09-06  
**状态：** 已取代 — 布局入口改由 `docs/superpowers/specs/2026-09-06-orchestrate-drawer-tab-design.md`（气泡底 Tab + 底部抽屉）；本文保留作双栏期决策与三块内容溯源。  

**分支建议：** 可在 `feat/agent-orchestration-loop` 上继续，或另开 `feat/orchestrate-workbench-layout`  
**范围：** `mcp_client` 多轮对话页：将执行计划（含 Replan）、执行、Skill、MCP 过程信息迁入右侧编排工作台；主栏专注回答。

**相关：** Plan-and-Execute 行为见 `docs/superpowers/specs/2026-09-05-plan-and-execute-design.md`（本设计偏 **UI 布局与信息架构**，不改 PnE 预算/工具语义）。

---

## 1. 背景与目标

### 现状

- 助手气泡内纵向堆叠：`orchestrate-flow-slot`（能力轨迹）→ `orchestrate-plan-slot`（执行计划）→ 回答正文。
- 计划、Skill、MCP、回答挤在同一列，层次不清；宽屏未利用横向空间。
- PnE 已返回 `plan` / `past_steps` / `status`，workflow 可发 `plan` / `plan_step` 事件，但客户端多为整轮 JSON 后一次性绘制。

### 目标

1. **双栏布局**：主栏对话与回答；右栏固定「编排工作台」。
2. 右栏 **三块分区**：计划（含 Replan）→ 执行时间线（tool / skill / MCP）→ 观察摘要（可折叠）。
3. 默认展示 **最新一轮** 编排；点击带编排数据的助手气泡可 **切换** 右栏到该轮。
4. **窄屏**：同一工作台 DOM 收成「编排」抽屉，不另做第三套 UI。
5. 气泡内 **去掉长计划/长轨迹**（可保留「查看编排」入口）。

### 非目标（本期）

- 首页单轮会话双栏。
- 右栏内编辑计划、手动重跑单步。
- MCP/检索全文大屏（摘要 + 现有引用即可）。
- 强制上线 SSE 逐步刷新（预留接口，首期整轮返回后刷新）。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 布局目标 | 双栏并存（过程与回答同时可见） |
| 右栏结构 | 三块纵向分区（非 Tab、非单一混杂日志） |
| 轮次绑定 | 默认最新；点击助手气泡切换 |
| 窄屏 | 抽屉（同一 DOM） |
| 实现路径 | 聊天区 CSS grid + `#orchestrate-workbench` 组件 |
| 右栏宽度 | 约 **420px**（原 320–380 加宽；主栏保留 `min-width`） |
| 实时 | 首期整轮刷新；SSE 预留 |

---

## 3. 页面骨架

### 3.1 宽屏（建议断点 ~1100px+）

```text
┌──────────────────────────────────────────────────────────┐
│ 顶栏 / 案件选择（保持现有）                               │
├────────────────────────────┬─────────────────────────────┤
│ 主栏 · 消息列表 + 输入     │ 右栏 · 编排工作台            │
│ 气泡：回答 / 引用 / 重试   │  1. 计划（含 Replan）        │
│ （无长 plan/flow）         │  2. 执行时间线               │
│                            │  3. 观察摘要（默认折叠）     │
└────────────────────────────┴─────────────────────────────┘
```

- 右栏建议固定宽度约 **420px**（`width` / `flex-basis`），内部可滚动；主栏设 `min-width`（建议 ≥520px）以免对话被挤扁。
- 视口不足以同时满足「右栏 420 + 主栏 min-width」时，走窄屏抽屉，不强制挤双栏。
- 仅在「多轮对话」视图启用；其它 tab/页不强制双栏。

### 3.2 窄屏

- 主栏全宽。
- 浮动或顶栏旁 **「编排」** 按钮；打开侧滑或底部抽屉，内容为同一 `#orchestrate-workbench`。
- 无编排数据时按钮可禁用或角标为 0。

---

## 4. 数据模型

客户端为每一轮成功的（或 `awaiting_user` 的）orchestrate 缓存：

```ts
OrchestrateTurnView = {
  turnId: string,           // 与助手气泡关联
  plan: string[],           // 剩余或最后快照
  past_steps: { step, observation?, tool? }[],
  status: "complete" | "awaiting_user" | "error" | string,
  pending_question?: string,
  flow: { kind, id, name, status? }[],  // capabilities.flow
  observations: { step, excerpt }[],    // 从 past_steps.observation 截断
  resume_state?: object,                // 已有续跑逻辑可并存
}
```

- 全局：`turnViews: Map<turnId, OrchestrateTurnView>`，`selectedTurnId`。
- 新一轮写入后 `selectedTurnId = turnId` 并 `renderWorkbench()`。
- 点击气泡：若有 `turnId` 对应视图则切换；否则空态。

**Replan：** 以响应中的最新 `plan` + `past_steps` 重绘计划区（已完成来自 past，剩余来自 plan）；不在气泡内维护第二份列表。

---

## 5. 右栏三块内容

### 5.1 计划

- 列表：past_steps → 已完成样式；plan → 待做；首项在非 complete 时可标「当前」。
- `status === "awaiting_user"`：显示「等待你的补充」（与现文案一致）。
- 标题可注明「执行计划」；若发生过 Replan，可用副文案「已根据执行结果更新」仅在有 replan_count>0 或检测 plan 变更时显示（可选，不强制）。

### 5.2 执行时间线

- 数据源优先 `flow`（agent / skill / mcp）；若有逐步 tool 信息可插入（来自 past_steps.tool 或未来 SSE `plan_step`）。
- 每项展示：类型徽标 + 名称；按数组顺序（即发生顺序）。
- 与计划区分工：计划 =「要做什么」；时间线 =「实际调用了什么」。

### 5.3 观察摘要

- 默认折叠；展开后每步一行短摘录（建议 ≤160–240 字 + 截断标记）。
- 不替代引用列表；法条/类案仍走主栏 cite UI。

---

## 6. 气泡迁移

| 保留在气泡 | 迁出到工作台 |
|------------|--------------|
| `visible_text` / pending 提问并入回答 | 长 `paintOrchestratePlan` |
| 引用、docx 下载、重试 | 长 `paintOrchestrateFlow` |
| 可选「查看编排」徽标/链接 | — |

- `addOrchestrateProgressShell`：可保留极薄进度占位（如「编排中…」），成功后清除长槽或不再插入 plan/flow 槽。
- 历史消息重载：若 session extra 含 `plan` / `past_steps` / `capabilities.flow`，重建 `turnViews` 以便回看。

---

## 7. 实时策略

| 阶段 | 行为 |
|------|------|
| 本期 | `POST /api/orchestrate` 整包 JSON → 更新 `turnViews` → 刷新工作台 |
| 预留 | `stream=1` 时消费 `plan` / `plan_step` / flow 类事件，增量 `renderWorkbench` |

不阻塞双栏上线。

---

## 8. 实现落点（预览）

| 区域 | 预期 |
|------|------|
| `mcp_client.html` | 多轮主区域包裹 grid；加入 `#orchestrate-workbench` 与窄屏触发按钮 |
| `mcp_client.css` | 双栏、工作台分区、抽屉、徽标 |
| `mcp_client.js` | `turnViews` / `selectedTurnId`；`renderOrchestrateWorkbench`；气泡点击委托；弱化 bubble 内 plan/flow |
| 缓存 bust | `mcp_client.js?v=…` |

后端接口字段以现有 PnE 响应为准；若历史消息缺 `past_steps`，工作台计划区可仅显示 flow。

---

## 9. 验收

1. 宽屏法律问：左见答，右见计划与时间线分区，不在气泡内刷长列表。  
2. 模拟/真实 Replan 后，右栏剩余步骤变化可见。  
3. 连续两轮编排后，点击上一轮助手气泡，右栏切回上一轮过程。  
4. 窄屏：抽屉开关正常，内容与宽屏一致。  
5. 非编排闲聊：右栏空态或「本轮无编排过程」，不报错。

---

## 10. 测试建议

- 无强制 E2E：至少手工冒烟上述验收。  
- 可选：对 `buildTurnView(data)` / `mergeFlowAndTools(flow, past_steps)` 抽纯函数做 2–3 个单元级断言（若引入模块化；保持与现有 IIFE 风格兼容亦可内联测试困难则跳过）。
