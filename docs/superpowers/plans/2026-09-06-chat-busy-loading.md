# 多轮对话 Busy / Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户发送后立刻看到分阶段 Loading，输入禁用、发送钮为「停止生成」可 Abort；编排 / 流式 / 重试全覆盖；结束无残留。

**Architecture:** 在 `mcp_client.js` 增加 `BusyController`（start / updateStages / end / abort）统一副作用；气泡内 `.busy-stages` 先占位三步，有 flow/past_steps 再替换；编排 `fetch` 与 LLM 共用可登记的 `AbortController`。

**Tech Stack:** 现有 `mcp_client.html` / `mcp_client.css` / `mcp_client.js`（无新框架）

**Spec:** `docs/superpowers/specs/2026-09-06-chat-busy-loading-design.md`

## Global Constraints

- 全覆盖：编排 + 流式 + 编排重试 + 按钮/输入/状态栏/气泡阶段。
- busy 时发送钮统一「停止生成」，可 Abort。
- 阶段视觉：分阶段进度；占位三步「理解问题 / 处理中 / 整理回答」；有真实步再替换，**禁止**无证据写具体工具名。
- 本期**不**为编排加后端 SSE。
- 不改 PnE 工具语义 / 预算 / 检索。
- 不做全页遮罩或骨架屏主样式。
- 默认仅 `mcp_client` 多轮页。
- 提交仅当用户明确要求时执行（本仓库惯例）；计划中的 Commit 步骤可跳过。

## File map

| File | Responsibility |
|------|----------------|
| `mcp_client.js` | 阶段纯函数、`BusyController`、编排/流式/重试/会话清理接入 |
| `mcp_client.css` | `.busy-stages` / `.busy-stage` |
| `mcp_client.html` | cache-bust `?v=20260906busy1` |

---

### Task 1: 阶段纯函数 + DOM 渲染 + CSS

**Files:**
- Modify: `mcp_client.js`（建议放在 `setLoadingState` / `addOrchestrateProgressShell` 附近）
- Modify: `mcp_client.css`

**Interfaces:**
- Produces:
  - `BUSY_PLACEHOLDER_STAGES = [{ id, label, status }]` 其中 status ∈ `'done'|'current'|'todo'`
  - `buildPlaceholderBusyStages() -> Stage[]` — 第1 done、第2 current、第3 todo
  - `buildBusyStagesFromOrchestrate(data) -> Stage[] | null` — 有可用 flow/past_steps 则返回，否则 `null`
  - `renderBusyStages(containerEl, stages) -> HTMLElement` — 写入/替换 `.busy-stages`
  - `removeBusyStages(containerEl) -> void`

- [ ] **Step 1: 加 CSS**

在 `mcp_client.css` 合适位置（如 `.loading-dots` 附近）追加：

```css
.busy-stages {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px 0 8px;
  font-size: 13px;
  color: #334155;
}

.busy-stages[aria-busy="true"] {
  /* marker for tests / a11y */
}

.busy-stage {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  line-height: 1.4;
}

.busy-stage-dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  margin-top: 5px;
  border-radius: 50%;
  background: #cbd5e1;
}

.busy-stage.is-done .busy-stage-dot {
  background: #22c55e;
}

.busy-stage.is-current .busy-stage-dot {
  background: #1a4a6e;
  box-shadow: 0 0 0 3px rgba(26, 74, 110, 0.25);
}

.busy-stage.is-done .busy-stage-label {
  color: #64748b;
  text-decoration: line-through;
}

.busy-stage.is-current .busy-stage-label {
  font-weight: 600;
  color: #0f172a;
}

.busy-stage.is-todo .busy-stage-label {
  color: #94a3b8;
}

.busy-aborted-note {
  font-size: 13px;
  color: #64748b;
  padding: 4px 0;
}
```

- [ ] **Step 2: 实现纯函数与渲染**

```javascript
const BUSY_PLACEHOLDER_LABELS = ['理解问题', '处理中', '整理回答'];

function buildPlaceholderBusyStages() {
  return [
    { id: 'p1', label: BUSY_PLACEHOLDER_LABELS[0], status: 'done' },
    { id: 'p2', label: BUSY_PLACEHOLDER_LABELS[1], status: 'current' },
    { id: 'p3', label: BUSY_PLACEHOLDER_LABELS[2], status: 'todo' }
  ];
}

function buildBusyStagesFromOrchestrate(data) {
  const stages = [];
  const flow = (data && data.capabilities && data.capabilities.flow) || (data && data.flow) || [];
  if (Array.isArray(flow) && flow.length) {
    flow.forEach(function (item, i) {
      if (!item || typeof item !== 'object') return;
      const kind = String(item.kind || '').toLowerCase();
      if (kind === 'plan_step' || kind === 'plan') return;
      const st = String(item.status || '').toLowerCase();
      let status = 'todo';
      if (st === 'done') status = 'done';
      else if (st === 'running') status = 'current';
      stages.push({
        id: String(item.id || kind || i),
        label: String(item.name || item.id || kind || '步骤'),
        status: status
      });
    });
  }
  if (!stages.length && data && Array.isArray(data.past_steps) && data.past_steps.length) {
    data.past_steps.forEach(function (p, i) {
      if (!p) return;
      const meta = typeof orchestrateToolMeta === 'function' && p.tool
        ? orchestrateToolMeta(p.tool)
        : { label: p.tool || '工具' };
      const step = String(p.step || '').trim();
      stages.push({
        id: 'past-' + i,
        label: step ? meta.label + ' — ' + step : meta.label,
        status: 'done'
      });
    });
    if (stages.length) {
      stages.push({ id: 'wrap', label: '整理回答', status: 'current' });
    }
  }
  if (!stages.length) return null;
  // Ensure at least one current if all done
  const hasCurrent = stages.some(function (s) { return s.status === 'current'; });
  if (!hasCurrent) {
    const last = stages[stages.length - 1];
    if (last && last.status === 'todo') last.status = 'current';
  }
  return stages;
}

function renderBusyStages(containerEl, stages) {
  if (!containerEl) return null;
  let root = containerEl.querySelector(':scope > .busy-stages');
  if (!root) {
    root = document.createElement('div');
    root.className = 'busy-stages';
    root.setAttribute('aria-live', 'polite');
    containerEl.insertBefore(root, containerEl.firstChild);
  }
  root.setAttribute('aria-busy', 'true');
  root.innerHTML = '';
  (stages || []).forEach(function (s) {
    const row = document.createElement('div');
    const st = (s && s.status) || 'todo';
    row.className = 'busy-stage is-' + st;
    const dot = document.createElement('span');
    dot.className = 'busy-stage-dot';
    const label = document.createElement('span');
    label.className = 'busy-stage-label';
    label.textContent = (s && s.label) || '';
    row.appendChild(dot);
    row.appendChild(label);
    root.appendChild(row);
  });
  return root;
}

function removeBusyStages(containerEl) {
  if (!containerEl) return;
  const root = containerEl.querySelector(':scope > .busy-stages');
  if (root) root.remove();
  containerEl.querySelectorAll('.busy-aborted-note').forEach(function (n) { n.remove(); });
}
```

注意：`buildBusyStagesFromOrchestrate` 若放在 `orchestrateToolMeta` **之前**，past_steps 分支先用 `p.tool` 字符串，或把该函数放在 `orchestrateToolMeta` 定义之后。

- [ ] **Step 3: Node 冒烟**

```bash
node -e '
function buildPlaceholderBusyStages() {
  return [
    { id: "p1", label: "理解问题", status: "done" },
    { id: "p2", label: "处理中", status: "current" },
    { id: "p3", label: "整理回答", status: "todo" }
  ];
}
function buildBusyStagesFromOrchestrate(data) {
  const stages = [];
  const flow = (data && data.flow) || [];
  flow.forEach(function (item, i) {
    const kind = String(item.kind || "").toLowerCase();
    if (kind === "plan_step" || kind === "plan") return;
    const st = String(item.status || "").toLowerCase();
    stages.push({
      id: String(item.id || i),
      label: String(item.name || item.id || kind),
      status: st === "done" ? "done" : (st === "running" ? "current" : "todo")
    });
  });
  return stages.length ? stages : null;
}
const p = buildPlaceholderBusyStages();
if (p[0].status !== "done" || p[1].status !== "current") throw new Error("placeholder");
const real = buildBusyStagesFromOrchestrate({
  flow: [
    { kind: "kb", id: "retrieve_law", name: "本地知识库 · 法规", status: "done" },
    { kind: "tool", id: "reason", name: "推理综合", status: "running" }
  ]
});
if (!real || real[1].status !== "current") throw new Error("flow");
if (buildBusyStagesFromOrchestrate({}) !== null) throw new Error("empty");
console.log("ok");
'
```

Expected: `ok`

- [ ] **Step 4: Commit（仅当用户要求）** — 跳过或按用户指示。

---

### Task 2: BusyController（start / updateStages / end / abort）

**Files:**
- Modify: `mcp_client.js`

**Interfaces:**
- Consumes: Task 1 渲染函数；现有 `setStopButtonState`、`updateStatus`、`elements.userInput`、`currentAbortController`、`isGenerating`、`isProcessingInput`
- Produces: 全局 `window.BusyController` 或同名对象：
  - `start({ mode, mountEl, abortController? })`
  - `updateStages(stages)`
  - `end({ reason, keepMount? })` — reason: `'success'|'error'|'abort'`
  - `abort()`
  - `isBusy()` → boolean
  - 内部字段：`_mode` (`'orchestrate'|'stream'`)、`_mountEl`、`_controller`

- [ ] **Step 1: 实现 BusyController**

```javascript
const BusyController = (function () {
  let busy = false;
  let mode = null;
  let mountEl = null;
  let ownedController = null;

  function setInputDisabled(disabled) {
    if (elements && elements.userInput) {
      elements.userInput.disabled = !!disabled;
    }
  }

  function start(opts) {
    opts = opts || {};
    busy = true;
    mode = opts.mode || 'orchestrate';
    mountEl = opts.mountEl || null;
    isGenerating = true;
    isProcessingInput = true;
    if (opts.abortController) {
      ownedController = opts.abortController;
      currentAbortController = ownedController;
    } else {
      ownedController = new AbortController();
      currentAbortController = ownedController;
    }
    setInputDisabled(true);
    if (typeof setStopButtonState === 'function') setStopButtonState(true);
    if (typeof updateStatus === 'function') updateStatus('正在处理…', 'connecting');
    if (mountEl) renderBusyStages(mountEl, buildPlaceholderBusyStages());
    // Bridge stop button to BusyController.abort
    if (elements && elements.sendBtn) {
      elements.sendBtn.onclick = function () {
        BusyController.abort();
      };
    }
    return ownedController;
  }

  function updateStages(stages) {
    if (!busy || !mountEl || !stages) return;
    renderBusyStages(mountEl, stages);
  }

  function end(opts) {
    opts = opts || {};
    const reason = opts.reason || 'success';
    busy = false;
    const el = mountEl;
    mountEl = null;
    mode = null;
    ownedController = null;
    // Do not null currentAbortController here if callLLM still owns lifecycle —
    // prefer: only clear if it is ours; safest for this plan: leave callLLM paths
    // to clear as today AFTER BusyController.end, or clear when reason is abort/error/success
    // uniformly here and let callLLM tolerate null:
    currentAbortController = null;
    isGenerating = false;
    isProcessingInput = false;
    setInputDisabled(false);
    if (typeof setStopButtonState === 'function') setStopButtonState(false);
    if (typeof updateStatus === 'function') {
      updateStatus(reason === 'abort' ? '已停止生成' : (reason === 'error' ? '请求失败' : '就绪'), 'connected');
    }
    if (el) {
      if (reason === 'abort') {
        removeBusyStages(el);
        const note = document.createElement('div');
        note.className = 'busy-aborted-note';
        note.textContent = '已停止生成';
        el.insertBefore(note, el.firstChild);
      } else if (reason === 'success') {
        removeBusyStages(el);
      } else {
        // error: leave mount for failure UI; still remove stages
        removeBusyStages(el);
      }
    }
    if (typeof window.updateSendButtonState === 'function') {
      setTimeout(function () { window.updateSendButtonState(); }, 0);
    }
  }

  function abort() {
    if (!busy) return;
    const c = ownedController || currentAbortController;
    // Match existing stopGeneration pattern: clear ref before abort for wasUserStopped
    ownedController = null;
    currentAbortController = null;
    if (c) {
      try { c.abort(); } catch (e) {}
    }
    end({ reason: 'abort' });
  }

  function isBusy() { return busy; }

  return { start: start, updateStages: updateStages, end: end, abort: abort, isBusy: isBusy };
})();
window.BusyController = BusyController;
```

- [ ] **Step 2: 桥接旧 `stopGeneration`**

将 `window.stopGeneration` 改为优先调用 `BusyController.abort()`（若 `isBusy()`），否则保留原 Abort 逻辑，避免双路径分裂：

```javascript
window.stopGeneration = function stopGeneration() {
  if (window.BusyController && BusyController.isBusy()) {
    BusyController.abort();
    return;
  }
  // ... existing body ...
};
```

- [ ] **Step 3: 自检**

在控制台（页面加载后）确认 `typeof BusyController.start === 'function'`。

- [ ] **Step 4: Commit** — 仅当用户要求。

---

### Task 3: 接入编排路径 + 重试 + AbortSignal

**Files:**
- Modify: `mcp_client.js` — `tryHandleOrchestrate` / `doRequest` / `attachRetry` / `handleUserInput` 编排返回分支

**Interfaces:**
- Consumes: `BusyController`、`addOrchestrateProgressShell`、`buildBusyStagesFromOrchestrate`
- Produces: 编排请求带 `signal`；busy 生命周期正确

- [ ] **Step 1: 改 `doRequest` 接受 signal**

```javascript
function doRequest(signal) {
  return fetch(`${CONFIG.mcpServerUrl}/api/orchestrate`, {
    method: 'POST',
    headers: (typeof LegalMindAuth !== 'undefined' && LegalMindAuth.authHeaders)
      ? LegalMindAuth.authHeaders()
      : { 'Content-Type': 'application/json' },
    signal: signal,
    body: JSON.stringify({
      user_text: fullUserMessage,
      session_id: currentSession && currentSession.sessionId,
      messages: (currentSession && currentSession.conversationHistory) || [],
      case_id: (typeof LegalMindAuth !== 'undefined' && LegalMindAuth.getCaseId)
        ? LegalMindAuth.getCaseId()
        : null,
      resume_state: (typeof window !== 'undefined' && window.__orchestrateResumeState) || undefined
    })
  });
}
```

- [ ] **Step 2: 主路径 start/end**

在 `try` 内：

```javascript
shell = addOrchestrateProgressShell();
const controller = BusyController.start({ mode: 'orchestrate', mountEl: shell.content });
paintOrchestrateFlow(shell.flowSlot, [], 0, -1);
const resp = await doRequest(controller.signal);
```

成功 `applyOrchestrateSuccess` 前：

```javascript
const realStages = buildBusyStagesFromOrchestrate(data);
if (realStages) BusyController.updateStages(realStages);
```

成功后：

```javascript
BusyController.end({ reason: 'success' });
```

（`applyOrchestrateSuccess` 内可 `removeBusyStages(targetShell.content)` 双保险。）

失败 `attachRetry` 前：

```javascript
BusyController.end({ reason: 'error' });
```

`legacy` 回退：

```javascript
BusyController.end({ reason: 'success' }); // or 'error' — 推荐 end 后移除壳
if (shell && shell.wrap) shell.wrap.remove();
return false; // handleUserInput 继续流式；流式 Task 4 再 start
```

捕获 `AbortError`：

```javascript
} catch (err) {
  if (err && (err.name === 'AbortError' || err.code === 20)) {
    // BusyController.abort already ended; ensure shell shows abort note
    return true;
  }
  ...
  BusyController.end({ reason: 'error' });
  attachRetry(...);
  return true;
}
```

- [ ] **Step 3: 重试按钮**

`attachRetry` 的 `onclick` 开头：

```javascript
const controller = BusyController.start({ mode: 'orchestrate', mountEl: targetShell.content });
clearOrchestrateRetry(targetShell);
// optional: clear previous answer text while retrying
...
const resp = await doRequest(controller.signal);
...
BusyController.end({ reason: 'success' }); // on ok
// on fail BusyController.end({ reason: 'error' }); attachRetry again
```

- [ ] **Step 4: 修正 `handleUserInput` 编排返回**

当前编排成功后直接 `setStopButtonState(false)`；改为依赖 `BusyController.end`（若尚未 end 则补 `end({reason:'success'})`），避免与 Controller 打架：

```javascript
const orchestrated = await tryHandleOrchestrate(fullUserMessage);
if (orchestrated) {
  if (BusyController.isBusy()) BusyController.end({ reason: 'success' });
  // flags already cleared by end; keep safety:
  isGenerating = false;
  isProcessingInput = false;
  return;
}
```

更好：确保 `tryHandleOrchestrate` **所有** return true 路径已 `end`，此处只做 `if (BusyController.isBusy()) BusyController.end(...)` 兜底。

- [ ] **Step 5: Commit** — 仅当用户要求。

---

### Task 4: 接入流式路径 + 会话清理 + cache-bust + 冒烟

**Files:**
- Modify: `mcp_client.js` — `handleUserInput` 流式分支、`callLLM` 的 Abort 登记
- Modify: `mcp_client.html` — `?v=20260906busy1`
- Modify: 会话清空路径（与 `clearOrchestrateWorkbenchState` 同级）调用 `BusyController.abort` 若 busy

**Interfaces:**
- Consumes: Task 2–3
- Produces: 流式首包前有阶段 UI；cache-bust

- [ ] **Step 1: 流式分支**

在 `addStreamingMessage()` 之后：

```javascript
const streamingMsg = addStreamingMessage();
const streamMount = streamingMsg.messageWrapper; // or content wrapper if you add a content div
BusyController.start({
  mode: 'stream',
  mountEl: streamMount,
  abortController: null // let start create; then assign into callLLM
});
// Pass BusyController's controller into callLLM OR set currentAbortController before callLLM
// Prefer: const ac = BusyController.start(...); and modify callLLM to reuse currentAbortController if already set.
```

**callLLM 调整（最小）：** 若 `currentAbortController` 已存在则复用，不再 `new AbortController()`；否则新建并赋值。`isGenerating` / `setStopButtonState(true)` 若已由 BusyController 设置可保留幂等调用。

流式**首个** `onStreamChunk` / `updateStreamingMessage` 有实质内容时：

```javascript
removeBusyStages(streamMount);
// optional: BusyController.updateStages([{id:'g', label:'生成回答', status:'current'}]);
```

流式正常结束 / catch：

```javascript
if (BusyController.isBusy()) {
  BusyController.end({ reason: wasUserStopped ? 'abort' : (error ? 'error' : 'success') });
}
```

注意与现有 `finally` 中 `setLoadingState(false)` / `setStopButtonState(false)` 协调：busy 路径以 `BusyController.end` 为准，避免 end 后再被旧逻辑改乱。

- [ ] **Step 2: 会话清空**

在清空会话 / `clearOrchestrateWorkbenchState` 调用处增加：

```javascript
if (window.BusyController && BusyController.isBusy()) BusyController.abort();
```

- [ ] **Step 3: cache-bust**

`mcp_client.html`：

```html
<link rel="stylesheet" href="mcp_client.css?v=20260906busy1">
...
<script src="mcp_client.js?v=20260906busy1"></script>
```

- [ ] **Step 4: 手工 / CDP 验收**

1. 硬刷新后发编排问题：1s 内见 `.busy-stages`；输入 disabled；钮为停止。  
2. 等待期间无空壳假死。  
3. 点停止：见「已停止生成」，可再发。  
4. 流式（若可触发 legacy 或非编排）：首包前有阶段。  
5. 成功后无残留 `.busy-stages`。  

CDP 可选注入：

```javascript
const shell = addOrchestrateProgressShell();
BusyController.start({ mode: 'orchestrate', mountEl: shell.content });
!!shell.content.querySelector('.busy-stages[aria-busy="true"]');
```

- [ ] **Step 5: Commit** — 仅当用户要求。

---

## Spec coverage (self-review)

| Spec | Task |
|------|------|
| BusyController API | Task 2 |
| 占位三步 + 真实步替换 | Task 1 + 3/4 |
| 编排 / 流式 / 重试挂载 | Task 3–4 |
| 停止 Abort + 文案 | Task 2–3 |
| 失败重试再 start | Task 3 |
| 输入禁用 + 状态栏 + 停止钮 | Task 2 |
| 会话清理 abort | Task 4 |
| 无 SSE / 不改 PnE | 全局约束 |
| cache-bust | Task 4 |
| 验收项 1–7 | Task 4 Step 4 |

无 TBD 占位步骤。`buildBusyStagesFromOrchestrate` 与 `orchestrateToolMeta` 顺序在 Task 1 已注明。
