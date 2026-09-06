# 多轮对话 Loading / Busy 反馈设计

**日期：** 2026-09-06  
**状态：** 已批准  
**范围：** `mcp_client` 发送后至响应完成/失败/停止期间的全覆盖 Loading 与可取消交互。

**相关：**  
- 编排抽屉：`docs/superpowers/specs/2026-09-06-orchestrate-drawer-tab-design.md`  
- 时间线折叠：`docs/superpowers/specs/2026-09-06-orchestrate-timeline-collapse-design.md`

---

## 1. 背景与目标

### 现状问题

| 路径 | 现象 |
|------|------|
| `/api/orchestrate` | `addOrchestrateProgressShell` 各槽位默认 `hidden`，长请求期间助手区近似空白 |
| 流式 LLM | `addStreamingMessage` 首包前气泡空；状态栏有「正在思考…」，但不统一 |
| 发送钮 | `setLoadingState(true)` 几乎未接入主发送路径；编排路径结束时不保证与停止钮一致 |
| 已有资产 | `loading-dots` / `addLoadingMessage` / `setStopButtonState` 零散存在，未统一 |

用户发送后若长时间无反馈，易误判为卡死或故障。

### 目标

1. **全覆盖**：编排、流式 LLM、编排重试均有明确 busy 反馈。  
2. **可停止**：busy 期间发送钮统一为「停止生成」，可 Abort。  
3. **分阶段进度**：气泡内阶段列表；先占位，有真实步骤再替换（不假扮未发生的工具调用）。  
4. **收尾干净**：成功 / 失败 / 停止后恢复输入与发送态，无残留 busy UI。

### 非目标

- 本期不为编排加后端 SSE / 流式进度推送。  
- 不改 PnE 工具语义、预算、检索排序。  
- 不做全局全页遮罩、骨架屏主样式（已否决为默认视觉）。  
- 不改首页独立发送流（除非复用同一控制器且成本极低；默认仅 `mcp_client` 多轮页）。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 覆盖范围 | C：按钮 + 输入禁用 + 状态栏 + 气泡阶段 + 重试 |
| 发送区 | B：统一「停止生成」可取消 |
| 气泡视觉 | C：分阶段进度 |
| 阶段数据 | B：占位三步；有真实 flow / past_steps / 流式进展则替换 |
| 实现结构 | 方案 1：统一 `BusyController` |

---

## 3. 架构：BusyController

前端（`mcp_client.js`）集中模块（可为同文件内一组函数，不必拆包）：

```text
BusyController
  start({ mode, shell? })   → idle → busy
  updateStages(stages)      → 刷新气泡阶段列表
  end({ reason })           → busy → idle（success | error | abort）
  abort()                   → AbortController.abort + end(abort)
```

**busy 副作用（必须同时成立）：**

1. 输入框 `disabled`（或等效只读）  
2. 发送钮 → `setStopButtonState(true)`，点击调用 `BusyController.abort`  
3. 状态栏：`正在处理…`（可随当前阶段微调文案）；busy 期间文案前显示转圈 spinner，结束移除  
4. 气泡内挂载/更新阶段 UI（见 §4）；**当前阶段**左侧为转圈，done/todo 仍为圆点  
5. `isProcessingInput` / `isGenerating` 与现有防重入标志对齐，busy 中忽略重复发送与回车

**挂载点：**

| 场景 | start | end |
|------|-------|-----|
| 编排 `tryHandleOrchestrate` | 用户气泡入列后、请求发出前；创建/复用 progress shell | 成功应用答案 / 失败挂重试 / abort |
| 流式 `callLLM` / `handleUserInput` 非编排分支 | 创建流式消息前或同时 | 流结束 / 错 / abort |
| 编排「重试」 | 点击重试时 | 同编排 |

编排若最终 `legacy` 回退流式：先 `end` 编排壳（或转换），再按流式 `start`，避免双 busy。

---

## 4. UI 行为

### 4.1 占位阶段（无真实步时）

固定三步（文案可微调，语义不变）：

1. 理解问题  
2. 处理中  
3. 整理回答  

规则：进入 busy 后尽快把第 1 步标完成、第 2 步为当前（可用短延时或立即），避免「三步全灰」；**不得**在无证据时把第 2 步写成具体工具名。

### 4.2 真实阶段

来源优先级（有则替换占位列表）：

1. 编排 `flow` 中非 `plan_step` 的 done/running 项（名称用现有展示名）  
2. `past_steps` 映射的工具标签（与工作台 `orchestrateToolMeta` 一致）  
3. 流式：若已有思考区内容，可将当前步改为「生成回答」类文案  

当前步：`running` 或列表最后未完成项高亮；已完成划线或绿点。

> 本期编排一次返回：真实步可能主要在结束瞬间出现。长等待仍依赖占位阶段，这是可接受的。

### 4.3 完成

- 成功：移除阶段块（或隐藏），展示正式答案 / 流式定稿；`BusyController.end('success')`  
- 观察摘要、编排 Tab、引用、外源 hint：**行为不变**

### 4.4 DOM 建议

```html
<div class="busy-stages" aria-live="polite" aria-busy="true">
  <div class="busy-stage is-done">…</div>
  <div class="busy-stage is-current">…</div>
  <div class="busy-stage is-todo">…</div>
</div>
```

挂在编排 shell 的 `content` 顶部，或流式消息容器内；答案出现后移除该节点。

---

## 5. 停止 / 失败 / 边界

| 事件 | 行为 |
|------|------|
| 停止生成 | `abort()`：中止 fetch/流；气泡显示「已停止生成」；恢复输入与发送钮；不自动重试 |
| 失败 | 错误文案 + 现有重试行；`end('error')`；重试再 `start` |
| 重复发送 | busy 时忽略 |
| 401 | 现有登录跳转；清理 shell / busy |
| 会话切换/清空 | 若 busy，先 abort 再清状态（与 `clearOrchestrateWorkbenchState` 等同级清理） |

Abort 实现：编排 `doRequest` 与 LLM `fetch` 共用或分别持有 `AbortController`，由 `BusyController` 在 `start` 时登记、在 `abort`/`end` 时释放。

---

## 6. 实现落点

| 文件 | 改动 |
|------|------|
| `mcp_client.js` | `BusyController`；编排/流式/重试接入；停用或桥接旧 `setLoadingState` |
| `mcp_client.css` | `.busy-stages` / `.busy-stage` 状态样式 |
| `mcp_client.html` | cache-bust |

后端：无强制变更。

---

## 7. 验收

1. 发编排类问题：用户气泡后 **1s 内** 见阶段 Loading；输入禁用；钮为停止。  
2. 等待期间无「空助手头像气泡」假死感。  
3. 点停止：请求中止，见「已停止生成」，可再发。  
4. 故意失败/断网：错误 + 重试；重试再次出现 Loading。  
5. 流式路径首包前同样有阶段 Loading；有内容后阶段让位于正文。  
6. 成功后无残留 `busy-stages`；发送钮恢复。  
7. 编排 Tab / 引用 / 外源 hint 与改前一致。

---

## 8. 测试建议

- 手工：编排长请求、停止、重试、流式短问。  
- 可选：对 `BusyController` 阶段合并纯函数做 1–2 条 Node/单测（有/无 flow）。  
- CDP：注入慢 fetch 或 mock，断言 DOM 存在 `.busy-stages` 且 `aria-busy`。
