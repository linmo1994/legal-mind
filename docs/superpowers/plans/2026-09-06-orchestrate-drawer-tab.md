# 编排 Tab + 底部抽屉 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 多轮对话主栏全宽；助手气泡在正文与引用下方提供「编排」Tab；点击打开底部抽屉展示工作台；去掉常驻右栏与浮动按钮。

**Architecture:** 保留 `#orchestrateWorkbench` + `orchestrateTurnViews` / `renderOrchestrateWorkbench`；CSS 改为全断点底部抽屉；入口从「查看编排」胶囊与浮动钮改为气泡底 Tab；`registerOrchestrateTurn` 成功后不自动开抽屉，Tab 点击负责开关。

**Tech Stack:** 现有 `mcp_client.html` / `mcp_client.css` / `mcp_client.js`（无新框架）

**Spec:** `docs/superpowers/specs/2026-09-06-orchestrate-drawer-tab-design.md`

## Global Constraints

- 不改 PnE / 检索 / 引用后端语义。
- 气泡内顺序：正文 → 引用 → 编排 Tab →（失败时）重试。
- 新一轮编排完成不自动打开抽屉。
- 提交仅当用户明确要求时执行（本仓库惯例）。

## File map

| File | Responsibility |
|------|----------------|
| `mcp_client.html` | 去掉浮动 `#orchestrateWorkbenchToggle`；cache-bust |
| `mcp_client.css` | 主栏全宽；底部抽屉 + 遮罩；Tab 样式；删除宽屏右栏/浮动钮 |
| `mcp_client.js` | Tab 挂载与开关；Esc；弱化整卡点击；成功路径不 openDrawer；Tab 在引用之后 |

---

### Task 1: HTML — 去掉浮动入口 + cache-bust

**Files:**
- Modify: `mcp_client.html`

**Interfaces:**
- Produces: DOM 仍含 `#orchestrateWorkbench`、`#orchestrateWorkbenchClose`、`#orchestrateWorkbenchBody`、`#orchestrateWorkbenchBackdrop`；**不再**含 `#orchestrateWorkbenchToggle`

- [ ] **Step 1: 删除浮动按钮**

在 `mcp_client.html` 的 `chat-area` 内删除：

```html
<button type="button" id="orchestrateWorkbenchToggle" class="orchestrate-workbench-toggle" title="编排" aria-expanded="false">编排</button>
```

保留 `aside#orchestrateWorkbench` 与 `#orchestrateWorkbenchBackdrop`。

- [ ] **Step 2: 更新 cache-bust**

```html
<link rel="stylesheet" href="mcp_client.css?v=20260906drawer1">
...
<script src="mcp_client.js?v=20260906drawer1"></script>
```

（若 css 行仍是旧 `v=`，一并改成 `20260906drawer1`。）

- [ ] **Step 3: 自检**

确认 HTML 中无 `orchestrateWorkbenchToggle`；有 `orchestrateWorkbench` 与 backdrop。

---

### Task 2: CSS — 全宽主栏 + 底部抽屉 + Tab

**Files:**
- Modify: `mcp_client.css`（约 `.chat-area` / `.orchestrate-workbench` / `@media (max-width: 1099px)` / `.orchestrate-turn-badge`）

**Interfaces:**
- Consumes: Task 1 DOM（无 toggle）
- Produces: `.orchestrate-turn-tab` 样式；`.orchestrate-workbench.is-open` 为底部抽拉

- [ ] **Step 1: 主栏全宽**

将 `.chat-main-column` 的 `min-width: 520px` 改为 `min-width: 0`（或删除 min-width），保证无右栏时不强制宽屏。

`.chat-area` 可保持 `flex-direction: row`（抽屉 `position: fixed` 不占 flex），或改为 `column`；推荐保持 row，抽屉 fixed 不参与布局。

- [ ] **Step 2: 用底部抽屉样式替换右栏**

把现有 `.orchestrate-workbench { width: 420px; ... }` 及 `@media (max-width: 1099px)` 内抽屉规则，统一为**全断点**底部抽屉，例如：

```css
.orchestrate-workbench {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  max-width: none;
  height: min(70vh, 560px);
  flex-shrink: 0;
  border-left: none;
  border-top: 1px solid #e2e8f0;
  border-radius: 12px 12px 0 0;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  min-height: 0;
  z-index: 20;
  transform: translateY(100%);
  transition: transform 0.2s ease;
  box-shadow: 0 -8px 24px rgba(15, 23, 42, 0.12);
}

.orchestrate-workbench.is-open {
  transform: translateY(0);
}

.orchestrate-workbench-close {
  display: inline-block;
}

.orchestrate-workbench-backdrop {
  display: block;
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  z-index: 19;
}

.orchestrate-workbench-backdrop[hidden] {
  display: none;
}

/* 浮动钮已删除；若有残留规则则 display:none 或删除整块 */
.orchestrate-workbench-toggle {
  display: none !important;
}
```

删除或清空 `@media (max-width: 1099px)` 里专门为「侧滑 + 浮动钮」写的重复规则（避免冲突）；窄屏不再需要单独一套。

- [ ] **Step 3: Tab 样式（替换胶囊）**

```css
.orchestrate-turn-tab {
  display: inline-flex;
  align-items: center;
  margin-top: 10px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 600;
  color: #1a4a6e;
  background: #fff;
  border: 1px solid #c5d9e8;
  border-radius: 8px 8px 0 0;
  border-bottom-color: transparent;
  cursor: pointer;
}

.orchestrate-turn-tab[aria-pressed="true"] {
  background: #e8f1f8;
  border-color: #93c5fd;
}

.orchestrate-turn-badge {
  /* 兼容旧 class：与 tab 同视觉，或仅作别名 */
  display: inline-flex;
  /* 同上关键属性，或 @extend 等价复制 */
}

.orchestrate-turn.is-selected-turn {
  outline: none; /* 减弱整卡描边，选中以 Tab 为准 */
}
```

- [ ] **Step 4: 视觉自检**

硬刷新多轮页：无右栏、无浮动钮；可临时给 `#orchestrateWorkbench` 加 `is-open` 看底部抽屉。

---

### Task 3: JS — Tab 开关、Esc、成功不自动开抽屉、顺序

**Files:**
- Modify: `mcp_client.js`（`elements`、`attachOrchestrateTurnBadge`、`registerOrchestrateTurn`、`selectOrchestrateTurn`、`initOrchestrateWorkbenchUi`、`applyOrchestrateSuccess`、`open/closeOrchestrateWorkbenchDrawer`）

**Interfaces:**
- Consumes: 现有 `orchestrateTurnViews`、`buildOrchestrateTurnView`、`renderOrchestrateWorkbench`、`selectOrchestrateTurn(turnId, opts)`
- Produces:
  - `attachOrchestrateTurnTab(shell, turnId)`（可重命名自 badge；class `orchestrate-turn-tab`；文案「编排」）
  - Tab 点击：同轮已开则关，否则 `selectOrchestrateTurn(turnId, { openDrawer: true })`
  - `registerOrchestrateTurn`：**不**传 `openDrawer`；在引用渲染后再挂 Tab
  - Esc → `closeOrchestrateWorkbenchDrawer`
  - `elements.orchestrateWorkbenchToggle` 可保留为 null 安全访问

- [ ] **Step 1: 改 `attachOrchestrateTurnBadge` → Tab 行为**

```javascript
function attachOrchestrateTurnTab(shell, turnId) {
  if (!shell || !shell.content) return;
  let tab = shell.content.querySelector('.orchestrate-turn-tab, .orchestrate-turn-badge');
  if (!tab) {
    tab = document.createElement('button');
    tab.type = 'button';
    shell.content.appendChild(tab);
  }
  tab.className = 'orchestrate-turn-tab';
  tab.textContent = '编排';
  tab.setAttribute('aria-pressed', selectedOrchestrateTurnId === turnId && isOrchestrateWorkbenchOpen() ? 'true' : 'false');
  tab.onclick = function (e) {
    e.preventDefault();
    e.stopPropagation();
    const panel = elements.orchestrateWorkbench || document.getElementById('orchestrateWorkbench');
    const open = panel && panel.classList.contains('is-open');
    if (open && selectedOrchestrateTurnId === turnId) {
      closeOrchestrateWorkbenchDrawer();
      tab.setAttribute('aria-pressed', 'false');
      return;
    }
    selectOrchestrateTurn(turnId, { openDrawer: true });
  };
  // 保证在 cite-list 之后：再 append 一次移到末尾
  shell.content.appendChild(tab);
}

function isOrchestrateWorkbenchOpen() {
  const panel = elements.orchestrateWorkbench || document.getElementById('orchestrateWorkbench');
  return !!(panel && panel.classList.contains('is-open'));
}
```

将所有 `attachOrchestrateTurnBadge` 调用改为 `attachOrchestrateTurnTab`（或让旧名调用新函数）。

- [ ] **Step 2: `registerOrchestrateTurn` 不自动开抽屉；延迟挂 Tab**

```javascript
function registerOrchestrateTurn(shell, data) {
  // ... 现有 turnId / view / hide slots ...
  // 不要在这里 attachTab（引用尚未渲染）
  selectOrchestrateTurn(turnId); // 无 openDrawer
  return turnId;
}
```

在 `applyOrchestrateSuccess` 里，`renderAssistantAnswerWithCitations(...)` **之后**调用：

```javascript
attachOrchestrateTurnTab(targetShell, targetShell.wrap.getAttribute('data-turn-id'));
```

（`registerOrchestrateTurn` 已写好 `data-turn-id`。）

- [ ] **Step 3: `selectOrchestrateTurn` 同步 Tab `aria-pressed`**

在现有选中逻辑后增加：更新所有 `.orchestrate-turn-tab` 的 `aria-pressed`（仅当前 `turnId` 且抽屉开时为 true；若仅选中未开抽屉，可用 `false`，或 `true` 表示「当前轮」——按 spec：**打开抽屉时** pressed；实现：

```javascript
function syncOrchestrateTabPressed() {
  const open = isOrchestrateWorkbenchOpen();
  document.querySelectorAll('.orchestrate-turn-tab').forEach(function (tab) {
    const turn = tab.closest('.orchestrate-turn');
    const id = turn && turn.getAttribute('data-turn-id');
    tab.setAttribute('aria-pressed', open && id === selectedOrchestrateTurnId ? 'true' : 'false');
  });
}
```

在 `openOrchestrateWorkbenchDrawer` / `closeOrchestrateWorkbenchDrawer` / `selectOrchestrateTurn` 末尾调用 `syncOrchestrateTabPressed()`。

`open/close` 中对 `toggle` 的 `aria-expanded` 保留 null 安全即可。

- [ ] **Step 4: `initOrchestrateWorkbenchUi`**

- 删除或跳过对 `#orchestrateWorkbenchToggle` 的 click 绑定（元素已不存在）。
- 保留 close + backdrop。
- **Esc：**

```javascript
if (!window._orchestrateWbEsc) {
  window._orchestrateWbEsc = true;
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeOrchestrateWorkbenchDrawer();
  });
}
```

- **弱化整卡点击：** 去掉 `chatMessages` 上「点击 `.orchestrate-turn` 就 `selectOrchestrateTurn`」的委托（避免误触抢焦点）；仅 Tab 负责选轮 + 开抽屉。

- [ ] **Step 5: 语法检查**

Run: `node --check mcp_client.js`  
Expected: 无输出、exit 0

---

### Task 4: 手工验收（对照 spec §8）

**Files:** 无代码；依赖 MCP `:8001` + 静态 `:8888`（或现有端口）

- [ ] **Step 1:** 硬刷新多轮对话页  
  Expected: 无右栏、无右下角浮动「编排」

- [ ] **Step 2:** 发一条会走编排的法律问  
  Expected: 回答下方有「编排」Tab；抽屉**未**自动打开；有引用时 Tab 在引用下方

- [ ] **Step 3:** 点「编排」  
  Expected: 底部抽屉滑出，可见计划/时间线；再点同 Tab 或遮罩或 Esc → 关闭

- [ ] **Step 4:** 再发一轮后点上一轮「编排」  
  Expected: 抽屉内容切到上一轮

- [ ] **Step 5:** 缩窗口到手机宽  
  Expected: 仍无浮动钮；Tab + 底部抽屉行为一致

---

## Spec coverage (self-review)

| Spec 要求 | Task |
|-----------|------|
| 取消宽屏右栏 / 主栏全宽 | T2 |
| 气泡底「编排」Tab | T3 |
| 底部抽屉 + 遮罩 / 关闭钮 / Esc | T2 + T3 |
| 去掉浮动钮 | T1 + T2 |
| 同 Tab 再点关闭；另条切换保持开 | T3 |
| 新一轮不自动弹抽屉 | T3 `register`/`select` 无 openDrawer |
| 顺序 正文→引用→编排 | T3 attach 在 citations 之后 |
| 工作台三块内容不变 | 无改 `renderOrchestrateWorkbench` 分区逻辑 |
| 不改 PnE/引用后端 | 无服务端任务 |

无 TBD/占位符；函数名与现有 `selectOrchestrateTurn` / `openOrchestrateWorkbenchDrawer` 一致。
