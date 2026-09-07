# 编排入口：气泡底 Tab + 底部抽屉

**日期：** 2026-09-06  
**状态：** 待审阅  
**取代：** `docs/superpowers/specs/2026-09-06-orchestrate-workbench-layout-design.md`（双栏右栏方案）中「宽屏常驻右栏 / 浮动编排钮」的布局决策；工作台**内部三块内容**与 `OrchestrateTurnView` 数据模型仍沿用，不另造一套。

**分支建议：** 在 `feat/agent-orchestration-loop` 上继续，或另开 `feat/orchestrate-drawer-tab`  
**范围：** `mcp_client` 多轮对话页布局与入口；不改 PnE / 检索 / 引用语义。

**相关：**  
- Plan-and-Execute：`docs/superpowers/specs/2026-09-05-plan-and-execute-design.md`  
- 原双栏布局（历史）：`docs/superpowers/specs/2026-09-06-orchestrate-workbench-layout-design.md`

---

## 1. 背景与目标

### 现状

- 宽屏：主栏 + 右栏常驻「编排工作台」（约 420px）。
- 窄屏：右下角浮动「编排」+ 侧滑抽屉。
- 助手气泡可带「查看编排」胶囊，用于切换右栏轮次。

### 问题

- 右栏挤占正文阅读宽度；过程信息默认可见，干扰「先看回答」。
- 宽/窄入口不一致（右栏 vs 浮动钮）。

### 目标

1. **主栏全宽**，取消宽屏常驻右栏。
2. 有编排数据时，在助手气泡**顶端**展示「本轮过程」面板（等待展开 / 定稿收起）；**不再**在气泡底部放置过程 Tab。
3. 完整计划/时间线仍可由工作台抽屉展示（无底栏 Tab 入口时，依赖顶端摘要展开短条；抽屉可后续另开入口）。
4. 去掉浮动「编排」按钮；宽窄屏同一套入口与抽屉。
5. 新一轮完成**不自动弹抽屉**；仅更新 Tab / 缓存。

### 非目标

- 改 PnE 预算、工具、检索、引用对齐逻辑。
- 抽屉内编辑计划、单步重跑。
- SSE 逐步刷新工作台（仍整轮返回后更新）。
- 首页单轮会话单独布局。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 布局 | 主栏全宽；无常驻右栏 |
| 入口 | 气泡底「编排」Tab（无数据不展示） |
| 展示 | 全断点底部抽屉 + 遮罩 |
| 关闭 | 关闭钮 / 遮罩 / Esc；同 Tab 再点可关 |
| 轮次 | Tab 绑定 `turnId`；点另一条切换内容并保持打开 |
| 新一轮 | 更新视图，不自动打开抽屉；等待中在气泡**顶端**展开「本轮过程」，正式回答后顶端自动收起为摘要 |
| Tab 文案 | 「本轮过程」（原「编排」） |
| 工作台内容 | 沿用现有三块分区与 `renderOrchestrateWorkbench` |
| DOM | 保留 `#orchestrateWorkbench`，改定位与入口 |

---

## 3. 页面骨架

```text
┌─────────────────────────────────────────────┐
│ 顶栏 / 案件选择（保持现有）                    │
├─────────────────────────────────────────────┤
│ 主栏 · 消息列表（全宽）                        │
│   助手气泡：                                  │
│     回答正文                                  │
│     引用列表（如有）                           │
│     [ 编排 ]  ← Tab，仅有编排数据时显示        │
│     重试等操作（在 Tab 下方，顺序：正文→引用→编排→重试）│
│ 输入区                                        │
└─────────────────────────────────────────────┘

抽屉打开时：
┌─────────────────────────────────────────────┐
│ 遮罩（半透明）                                 │
│ ┌─────────────────────────────────────────┐ │
│ │ 编排工作台                          [×]  │ │
│ │ 1. 执行计划（含 Replan 提示）             │ │
│ │ 2. 执行时间线                             │ │
│ │ 3. 观察摘要（默认折叠）                   │ │
│ └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

- 抽屉：自底部滑入；高度建议约 `min(70vh, 560px)`，内部滚动；宽屏可略高但不回到侧栏。
- 仅多轮对话视图启用；其它页不强制。

---

## 4. 交互与轮次绑定

| 操作 | 行为 |
|------|------|
| 点某条「编排」Tab | `selectedTurnId = turnId` → `renderOrchestrateWorkbench()` → 打开抽屉；该 Tab `aria-pressed=true` |
| 再点**同一条**且抽屉已开 | 关闭抽屉 |
| 点**另一条**「编排」 | 切换 `selectedTurnId`、重绘内容，抽屉保持打开 |
| 新一轮编排完成 | 写入 `orchestrateTurnViews`、挂上/更新该条 Tab；**不** `openDrawer`；可选短暂高亮 Tab |
| 关闭钮 / 遮罩 / Esc | `closeOrchestrateWorkbenchDrawer()` |
| 切换会话 / 清空 | `clearOrchestrateWorkbenchState()`（已有） |

- 气泡整卡点击不再作为打开抽屉的主路径（避免误触）；选中描边可减弱或去掉，以 Tab 选中态为准。
- 无 `turnId` / 无缓存视图：不渲染 Tab。

---

## 5. 数据模型与工作台内容

沿用既有：

```ts
OrchestrateTurnView = {
  turnId: string,
  plan: string[],
  past_steps: { step, observation?, tool? }[],
  status: "complete" | "awaiting_user" | "error" | string,
  pending_question?: string,
  flow: { kind, id, name, status? }[],
  observations: { step, excerpt }[],
  resume_state?: object,
}
```

- 全局：`orchestrateTurnViews`、`selectedOrchestrateTurnId`（现有命名可保留）。
- 抽屉内三块：计划 / 执行时间线 / 观察摘要 — 逻辑与现 `renderOrchestrateWorkbench` 一致。
- 引用仍在主栏气泡，不进抽屉。

---

## 6. 气泡与 DOM 迁移

| 保留 / 新增 | 移除或降级 |
|-------------|------------|
| 回答、引用、docx、重试 | 宽屏右栏 grid 占位 |
| 「编排」Tab（替代「查看编排」胶囊文案） | 右下角浮动 `#orchestrateWorkbenchToggle` |
| `#orchestrateWorkbench` + backdrop（改底部定位） | 常驻 `display` 的侧栏样式 |

- `attachOrchestrateTurnBadge` → 改为挂载 Tab（或同函数改文案/样式为 Tab）。
- 历史消息重载：session extra 含 plan/past_steps/flow 时重建 `turnViews` 并挂 Tab（行为与现一致，仅入口样式变）。

---

## 7. 实现落点

| 区域 | 预期 |
|------|------|
| `mcp_client.html` | 聊天区去双栏包裹（或 CSS 改回单列）；去掉浮动 toggle（或 `hidden`）；保留 workbench + backdrop |
| `mcp_client.css` | 主栏全宽；底部抽屉 + 遮罩全断点；`.orchestrate-turn-tab`；删除/停用宽屏右栏与浮动钮规则 |
| `mcp_client.js` | Tab 点击开关抽屉；弱化整卡选中开抽屉；新一轮不自动 open；缓存 bust `?v=` |
| 文档 | 本 spec；旧双栏 spec 标记为已取代 |

后端无字段变更。

---

## 8. 验收

1. 宽屏法律问：主栏全宽；气泡底有「编排」；默认无抽屉、无右栏。  
2. 点「编排」：底部抽屉出现，见计划与时间线；再点同 Tab 或遮罩关闭。  
3. 两轮编排后：点上一轮 Tab，抽屉内容切到上一轮。  
4. 窄屏：无浮动钮；行为与宽屏一致。  
5. 非编排闲聊：无「编排」Tab；开抽屉空态不报错（若无入口则无法打开即可）。  
6. 新一轮完成：抽屉不自动弹出。

---

## 9. 测试建议

- 手工冒烟上述验收。  
- 无强制 E2E；纯函数若已有可保持不动。
