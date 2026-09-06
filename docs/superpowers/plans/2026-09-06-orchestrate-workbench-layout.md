# 编排工作台双栏布局 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 多轮对话页主栏专注回答，右侧 ~420px 编排工作台展示计划（含 Replan）、执行时间线、观察摘要；窄屏同一 DOM 收成抽屉。

**Architecture:** `chat-area` 改为左右结构：左 `chat-main-column`（消息+输入），右 `#orchestrateWorkbench`。用 `Map` 缓存每轮 `OrchestrateTurnView`，选中轮次驱动 `renderOrchestrateWorkbench`。气泡内停画长 plan/flow，改「查看编排」徽标。

**Tech Stack:** 现有 `mcp_client.html/css/js`（无新框架）

**Spec:** `docs/superpowers/specs/2026-09-06-orchestrate-workbench-layout-design.md`

---

### Task 1: HTML 骨架

**Files:** Modify `mcp_client.html`

- [x] 将 `#chatMessages`、弹窗、file preview、`input-area` 包进 `.chat-main-column`
- [x] 在 `chat-area` 内加 `#orchestrateWorkbench`（三块空壳）、`#orchestrateWorkbenchToggle`、`#orchestrateWorkbenchBackdrop`
- [x] cache-bust `mcp_client.js?v=20260906wb1`

### Task 2: CSS 双栏 + 抽屉

**Files:** Modify `mcp_client.css`

- [x] `.chat-area` 横向 flex；主栏 `min-width: 520px`；右栏 `width: 420px`
- [x] 工作台分区样式；`@media (max-width: 1099px)` 固定抽屉 + toggle/backdrop
- [x] `.orchestrate-turn-badge` 气泡徽标

### Task 3: JS 数据与渲染

**Files:** Modify `mcp_client.js`

- [x] `orchestrateTurnViews` Map + `selectedOrchestrateTurnId`
- [x] `buildOrchestrateTurnView(turnId, data)` / `renderOrchestrateWorkbench()`
- [x] `applyOrchestrateSuccess`：写缓存、选中、渲染工作台；气泡隐藏 plan/flow，加徽标
- [x] 点击 `.orchestrate-turn` 切换；toggle/backdrop 开关抽屉
- [x] 空态文案

### Task 4: 验收

- [x] `node --check mcp_client.js`
- [ ] 手工：宽屏双栏、点气泡切换、窄屏抽屉（可用开发者工具缩窗口）

**Commits:** 仅当用户要求时提交。
