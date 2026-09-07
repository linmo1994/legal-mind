# 编排 SSE 逐步刷新 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 编排路径用 SSE 实时推送 `emit_step`，前端同步刷新 Busy 阶段、编排工作台与气泡短过程条；`done` 后落完整答案/引用/docx。

**Architecture:** 复用后端已有 `stream:true` SSE；前端 `fetch` + 行缓冲解析；维护 `liveFlow[]` 一份数据驱动三处 UI；`done.result` 走现有 `applyOrchestrateSuccess` 全量覆盖。

**Tech Stack:** `mcp_server.py` BaseHTTPRequestHandler SSE、`WorkflowTracer.on_event`、`mcp_client.js/css/html`（无新框架）

**Spec:** `docs/superpowers/specs/2026-09-06-orchestrate-sse-design.md`

## Global Constraints

- 范围 B：Busy + 工作台 + 气泡短过程条（最近最多 5 条）。
- 产品 UI 默认 `stream: true`；保留非 stream JSON 兼容。
- 不改 PnE 工具语义/预算；不做 reasoning token 流；不做 WebSocket。
- Abort 使用现有 `BusyController` AbortController。
- 提交仅当用户明确要求时执行；计划中的 Commit 步骤可跳过。
- cache-bust：`?v=20260906sse1`

## File map

| File | Responsibility |
|------|----------------|
| `server/orchestrate_sse.py`（新建，可选）或 `server/mcp_server.py` | SSE error 写入；格式化 `data:` 行（若抽纯函数） |
| `tests/test_orchestrate_sse.py` | `merge` 逻辑若在 Python 测格式；或测 `format_sse_data` + error 路径 |
| `mcp_client.js` | `mergeLiveFlow`、`readOrchestrateSse`、短条渲染、改 `tryHandleOrchestrate` |
| `mcp_client.css` | `.orchestrate-live-strip` 样式 |
| `mcp_client.html` | cache-bust |
| `docs/superpowers/specs/2026-09-06-orchestrate-sse-design.md` | 已批准，实施中可标「实现中」 |

---

### Task 1: `mergeLiveFlow` 纯函数 + 单测（前端可测部分用 Node 或抽到小模块）

因主逻辑在浏览器 `mcp_client.js`，把可测合并规则放在 **Python 镜像测试不合适**。改为：

**方案：** 在 `mcp_client.js` 顶部附近实现纯函数；用 **Node 跑最小 assert 脚本** `tests/test_orchestrate_sse_merge.js`（无构建器，直接 `node`）。

**Files:**
- Modify: `mcp_client.js`（在 `BusyController` / orchestrate 附近）
- Create: `tests/test_orchestrate_sse_merge.js`

**Interfaces:**
- Produces:
  - `mergeLiveFlow(prev, event) -> newArray`  
    - `event` 形如 `{ kind, id, name, status, detail? }`（无 `type` 字段亦可）  
    - 同 `kind`+`id`：更新该条 `status`/`detail`/`name`，不重复追加  
    - 不同 id：追加  
  - `liveFlowToBusyStages(flow) -> stages|null` — 委托/复用 `buildBusyStagesFromOrchestrate({ capabilities: { flow } })`
  - `liveFlowRecent(flow, limit=5) -> flow.slice(-limit)`

- [ ] **Step 1: 写失败测试**

```js
// tests/test_orchestrate_sse_merge.js
const assert = require('assert');
// Load by evaluating the functions — copy-test or require if exported on global.
// Prefer: define mergeLiveFlow in a tiny shared file OR duplicate test against
// functions assigned to globalThis in mcp_client (hard). Simplest for this repo:
// put mergeLiveFlow in server-less file `orchestrate_live_flow.js` next to mcp_client
// and script-tag it — OR keep functions in mcp_client.js and duplicate minimal
// implementation in the test file that imports via vm.

// Practical approach for this codebase (no bundler):
// Create `orchestrate_live_flow.js` with ONLY pure functions (no DOM),
// include it in mcp_client.html before mcp_client.js, and require it in Node test.
```

改用独立纯文件更干净：

**Files (revised):**
- Create: `orchestrate_live_flow.js`
- Create: `tests/test_orchestrate_sse_merge.js`
- Modify: `mcp_client.html` — `<script src="orchestrate_live_flow.js?v=20260906sse1"></script>` before `mcp_client.js`

```js
// orchestrate_live_flow.js
(function (root) {
  function flowKey(e) {
    return String(e.kind || '') + '\0' + String(e.id || '');
  }
  function mergeLiveFlow(prev, event) {
    const list = Array.isArray(prev) ? prev.slice() : [];
    if (!event || typeof event !== 'object') return list;
    const key = flowKey(event);
    if (!event.id && !event.kind) {
      list.push(Object.assign({}, event));
      return list;
    }
    const idx = list.findIndex(function (x) { return flowKey(x) === key; });
    if (idx >= 0) {
      list[idx] = Object.assign({}, list[idx], event);
    } else {
      list.push(Object.assign({}, event));
    }
    return list;
  }
  function liveFlowRecent(flow, limit) {
    const n = typeof limit === 'number' ? limit : 5;
    const arr = Array.isArray(flow) ? flow : [];
    return arr.slice(Math.max(0, arr.length - n));
  }
  root.mergeLiveFlow = mergeLiveFlow;
  root.liveFlowRecent = liveFlowRecent;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { mergeLiveFlow: mergeLiveFlow, liveFlowRecent: liveFlowRecent };
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
```

```js
// tests/test_orchestrate_sse_merge.js
const assert = require('assert');
const { mergeLiveFlow, liveFlowRecent } = require('../orchestrate_live_flow.js');

let f = [];
f = mergeLiveFlow(f, { kind: 'tool', id: 'retrieve_law', name: '法规', status: 'running' });
f = mergeLiveFlow(f, { kind: 'tool', id: 'retrieve_law', name: '法规', status: 'done' });
assert.strictEqual(f.length, 1);
assert.strictEqual(f[0].status, 'done');
f = mergeLiveFlow(f, { kind: 'tool', id: 'draft_doc', name: '起草', status: 'running' });
assert.strictEqual(f.length, 2);
assert.strictEqual(liveFlowRecent(f, 1)[0].id, 'draft_doc');
console.log('ok');
```

- [ ] **Step 2: 跑测确认失败（文件尚不存在）**

Run: `node tests/test_orchestrate_sse_merge.js`  
Expected: FAIL cannot find module

- [ ] **Step 3: 实现 `orchestrate_live_flow.js` + 通过测试**

Run: `node tests/test_orchestrate_sse_merge.js`  
Expected: `ok`

- [ ] **Step 4: html 引入脚本（cache-bust 可先写 sse1）**

---

### Task 2: SSE 行缓冲解析器（纯函数）

**Files:**
- Modify: `orchestrate_live_flow.js`（或新建同文件追加）
- Modify: `tests/test_orchestrate_sse_merge.js`

**Interfaces:**
- Produces:
  - `parseSseChunk(buffer, chunkText) -> { buffer, events: object[] }`  
    - 拼接 buffer+chunk，按 `\n` 拆行，完整 `data: ...` 行 JSON.parse 推入 events；不完整行留在 buffer  
  - 忽略非 `data:` 行与空行；parse 失败的行跳过

- [ ] **Step 1: 失败测试**

```js
const { parseSseChunk } = require('../orchestrate_live_flow.js');
let st = parseSseChunk('', 'data: {"type":"step","id":"a"}\n\n');
assert.strictEqual(st.events.length, 1);
assert.strictEqual(st.events[0].type, 'step');
st = parseSseChunk('data: {"type":"do', 'ne","result":{}}\n\n');
assert.strictEqual(st.events[0].type, 'done');
```

- [ ] **Step 2: 实现 `parseSseChunk` 使测试通过**

```js
function parseSseChunk(buffer, chunkText) {
  const buf = String(buffer || '') + String(chunkText || '');
  const parts = buf.split('\n');
  const rest = parts.pop();
  const events = [];
  for (let i = 0; i < parts.length; i++) {
    const line = parts[i].replace(/\r$/, '');
    if (!line.startsWith('data:')) continue;
    const raw = line.slice(5).trim();
    if (!raw) continue;
    try { events.push(JSON.parse(raw)); } catch (e) {}
  }
  return { buffer: rest, events: events };
}
```

---

### Task 3: 后端 SSE error 事件

**Files:**
- Modify: `server/mcp_server.py` — `_handle_orchestrate_api`
- Create: `tests/test_orchestrate_sse.py`（测纯函数更好：抽 `format_sse_json(obj) -> bytes`）

**Interfaces:**
- 若 `want_stream` 且 headers 已 `end_headers`，异常时写：  
  `data: {"type":"error","error":"任务编排失败","detail":"..."}\n\n`  
  然后 return，**不要**再 `_write_json`（会破坏流）。

- [ ] **Step 1: 抽小函数并测**

```python
# server/orchestrate_sse_util.py
import json
def sse_data_line(obj: dict) -> bytes:
    return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")
```

```python
# tests/test_orchestrate_sse.py
from orchestrate_sse_util import sse_data_line
def test_sse_error_line():
    b = sse_data_line({"type": "error", "error": "任务编排失败", "detail": "x"})
    assert b.startswith(b"data: ")
    assert b"error" in b
```

- [ ] **Step 2: `_handle_orchestrate_api` 使用 `sse_data_line`；stream 分支 try/except 在已 flush headers 后写 error**

用标志位 `headers_sent = False`，`end_headers` 后置 `True`。

---

### Task 4: 气泡短过程条 UI

**Files:**
- Modify: `mcp_client.js` — `renderOrchestrateLiveStrip(slotEl, flow, opts)`
- Modify: `mcp_client.css`

**Interfaces:**
- `renderOrchestrateLiveStrip(containerEl, flow, { collapsed, limit })`  
  - 未折叠：渲染 `.orchestrate-live-strip` 列表，`liveFlowRecent(flow, 5)`  
  - `status===running|current`：小 spinner  
  - 折叠：单行「本轮调用 N 步」可点击展开  
- `settleOrchestrateLiveStrip(containerEl)` — done 后设 collapsed

CSS 要点：

```css
.orchestrate-live-strip { font-size: 12px; color: #475569; margin: 4px 0 8px; }
.orchestrate-live-strip-item { display: flex; align-items: center; gap: 6px; padding: 2px 0; }
.orchestrate-live-strip-spinner { /* 复用 busy-stage-spinner 尺寸略小 */ }
.orchestrate-live-strip-summary { cursor: pointer; color: #1a4a6e; }
```

- [ ] **Step 1: 实现渲染函数并用临时 DOM（CDP 或手工）验证 class 存在**  
- [ ] **Step 2: 加 CSS**

---

### Task 5: `tryHandleOrchestrate` 改走 SSE + 三处刷新

**Files:**
- Modify: `mcp_client.js` — `doRequest` / 主路径 / 重试路径

**Interfaces:**
- Consumes: `mergeLiveFlow`, `parseSseChunk`, `liveFlowRecent`, `renderOrchestrateLiveStrip`, `BusyController`, `registerOrchestrateTurn` / workbench render helpers

- [ ] **Step 1: `doRequest` body 增加 `stream: true`，header 可加 `Accept: text/event-stream`**

- [ ] **Step 2: 实现 `async function consumeOrchestrateSse(resp, handlers)`**

```js
async function consumeOrchestrateSse(resp, handlers) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let sawDone = false;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    const parsed = parseSseChunk(buffer, decoder.decode(value, { stream: true }));
    buffer = parsed.buffer;
    for (let i = 0; i < parsed.events.length; i++) {
      const ev = parsed.events[i];
      if (ev.type === 'step') {
        if (handlers.onStep) handlers.onStep(ev);
      } else if (ev.type === 'done') {
        sawDone = true;
        if (handlers.onDone) handlers.onDone(ev.result);
      } else if (ev.type === 'error') {
        if (handlers.onError) handlers.onError(ev);
      }
    }
  }
  if (!sawDone && handlers.onError) {
    handlers.onError({ error: '编排流意外结束' });
  }
}
```

- [ ] **Step 3: 主路径与重试**

伪代码：

```js
let liveFlow = [];
const turnId = /* after shell created */;
// onStep:
liveFlow = mergeLiveFlow(liveFlow, ev);
BusyController.updateStages(buildBusyStagesFromOrchestrate({ capabilities: { flow: liveFlow } }) || buildPlaceholderBusyStages());
// patch workbench view for current turn with live flow + re-render
renderOrchestrateLiveStrip(shell.flowSlot, liveFlow, { collapsed: false });
// onDone:
BusyController.end({ reason: 'success' });
settleOrchestrateLiveStrip(shell.flowSlot);
await applyOrchestrateSuccess(shell, result, fullUserMessage);
```

工作台增量：若已有 `registerOrchestrateTurn` / `orchestrateTurnViews`，在 onStep 时更新该 turn 的 `capabilities.flow = liveFlow` 并调用现有 `renderOrchestrateWorkbenchForTurn(turnId)`（若函数名不同，找到 `renderOrchestrateWorkbench` / `bindWorkbench` 等价物复用）。

- [ ] **Step 4: Content-Type 检测** — 若响应不是 event-stream（旧代理），fallback `resp.json()` 一次（防御）。

- [ ] **Step 5: 401 / !ok 处理保持与现逻辑一致（读 text/json error）**

---

### Task 6: 冒烟与 cache-bust

**Files:**
- Modify: `mcp_client.html` — `?v=20260906sse1` for css/js/live_flow

- [ ] **Step 1: 重启 MCP；硬刷新页面**  
- [ ] **Step 2: 发「检索劳动合同法第64条」类编排问题**  
  - 断言：结束前 DOM 出现 `.orchestrate-live-strip-item` 或工作台 timeline `li`  
  - Busy 阶段非仅占位  
- [ ] **Step 3: 点停止** — spinner 消失，无卡死  
- [ ] **Step 4: 成功轮** — 答案/引用正常；短条折叠为「本轮调用 N 步」

- [ ] **Step 5: 更新 spec 状态为「已实现」摘要（可选一句）**

---

## Spec coverage check

| Spec 项 | Task |
|---------|------|
| stream:true 默认 | Task 5 |
| step → Busy/工作台/短条 | Task 4–5 |
| done → applyOrchestrateSuccess | Task 5 |
| merge running→done | Task 1 |
| SSE 解析半包 | Task 2 |
| error 事件 | Task 3 |
| 短条最多 5 / 折叠 | Task 4 |
| Abort | Task 5（现有 BusyController） |
| 非目标未纳入 | — |

## Placeholder scan

无 TBD；Commit 步骤按仓库惯例可跳过。
