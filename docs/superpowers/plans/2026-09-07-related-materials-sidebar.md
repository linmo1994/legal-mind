# 相关资料侧栏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 多轮对话页去掉气泡内联引用列表，改为「已阅读 X 条法规，Y 个案例」Tab；点击打开右侧「相关资料」（法规/案例分段）。

**Architecture:** 新建独立 `#relatedMaterials` 侧栏（不复用执行过程抽屉）。纯函数负责分类/计数/文案；消息宿主挂 `.related-materials-tab`；宽屏 `.chat-area.is-related-open` 推开右栏，窄屏浮层+遮罩。内联 `.cite-inline` 仍走 `openCitationPreview`。

**Tech Stack:** 静态 `mcp_client.html/css/js`；Node assert smoke（与现有前端测试一致）

**Spec:** `docs/superpowers/specs/2026-09-07-related-materials-sidebar-design.md`

## Global Constraints

- 不改后端检索 / `hits_to_citations` / PnE。
- 不扩展 citation 元数据字段（有效、发文机关等）。
- 提交仅当用户明确要求；计划中的 Commit 步骤可跳过。
- cache-bust：`?v=20260907rel1`

## File map

| File | Responsibility |
|------|----------------|
| `mcp_client.html` | `#relatedMaterials` / backdrop DOM；cache-bust |
| `mcp_client.css` | 推开布局、浮层、胶囊 Tab、侧栏分段与列表 |
| `mcp_client.js` | 分类/文案/Tab/侧栏 open·close·render；停挂 `.cite-list`；接线与清理 |
| `tests/test_related_materials.js` | 纯函数：分类、计数文案、默认分段 |
| `tests/test_related_materials_smoke.js` | 源码接线与 CSS/HTML 标记存在性 |

---

### Task 1: 纯函数 `partitionCitations` / `formatRelatedMaterialsTabLabel` + 测试

**Files:**
- Create: `tests/test_related_materials.js`
- Modify: `mcp_client.js`（在 `normalizeCitationsList` 附近新增纯函数）

- [ ] **Step 1: Write the failing test**

```javascript
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.js'), 'utf8');
const start = src.indexOf('function partitionCitations');
const end = src.indexOf('function formatRelatedMaterialsTabLabel');
assert.ok(start >= 0, 'partitionCitations missing');
// Load both functions + helpers they need by slicing a larger window, or eval named fns after normalizeCitationsList.
const blockStart = src.indexOf('function normalizeCitationsList');
const blockEnd = src.indexOf('function findCitationLinkRanges');
assert.ok(blockStart >= 0 && blockEnd > blockStart);
const sandbox = { console, module: { exports: {} }, exports: {} };
vm.runInNewContext(src.slice(blockStart, blockEnd), sandbox);

const { partitionCitations, formatRelatedMaterialsTabLabel, defaultRelatedMaterialsSegment } = sandbox;
// If not exported on sandbox, they are global in context:
const partition = sandbox.partitionCitations || partitionCitations;
const format = sandbox.formatRelatedMaterialsTabLabel || formatRelatedMaterialsTabLabel;
const defSeg = sandbox.defaultRelatedMaterialsSegment || defaultRelatedMaterialsSegment;

const mixed = [
  { doc_type: 'law', title: '食品安全法', article: '第148条' },
  { doc_type: 'case', title: '(2025)最高法民再142号' },
  { doc_type: 'law', title: '民法典' },
  { title: '无名法规' }, // default → law
];
const parts = partition(mixed);
assert.strictEqual(parts.laws.length, 3);
assert.strictEqual(parts.cases.length, 1);
assert.strictEqual(format(parts), '已阅读3条法规，1个案例');
assert.strictEqual(defSeg(parts), 'law');
assert.strictEqual(defSeg({ laws: [], cases: [{ title: 'c' }] }), 'case');
assert.strictEqual(format({ laws: [], cases: [{ title: 'c' }] }), '已阅读0条法规，1个案例');
console.log('ok: related materials pure helpers');
```

> 实现时按 `vm` 实际作用域微调：若函数未挂到 sandbox，在切片末尾追加 `module.exports = { partitionCitations, formatRelatedMaterialsTabLabel, defaultRelatedMaterialsSegment };` 仅用于测试不可行（会污染浏览器）。优先：`vm.runInNewContext` 后从 sandbox 全局读取（非严格下 function 声明会成为 sandbox 属性）。

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/test_related_materials.js`  
Expected: FAIL（`partitionCitations missing` 或 ReferenceError）

- [ ] **Step 3: Write minimal implementation**

在 `mcp_client.js` 的 `normalizeCitationsList` 之后插入：

```javascript
function partitionCitations(citations) {
  const list = normalizeCitationsList(citations);
  const laws = [];
  const cases = [];
  list.forEach(function (c) {
    if (!c || typeof c !== 'object') return;
    if (String(c.doc_type || '').toLowerCase() === 'case') cases.push(c);
    else laws.push(c);
  });
  return { laws: laws, cases: cases };
}

function formatRelatedMaterialsTabLabel(parts) {
  const nLaw = (parts && parts.laws && parts.laws.length) || 0;
  const nCase = (parts && parts.cases && parts.cases.length) || 0;
  return '已阅读' + nLaw + '条法规，' + nCase + '个案例';
}

function defaultRelatedMaterialsSegment(parts) {
  if (parts && parts.laws && parts.laws.length) return 'law';
  return 'case';
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/test_related_materials.js`  
Expected: `ok: related materials pure helpers`

- [ ] **Step 5: Commit（仅当用户要求）**

```bash
git add mcp_client.js tests/test_related_materials.js
git commit -m "$(cat <<'EOF'
feat: add citation partition helpers for related materials tab

EOF
)"
```

---

### Task 2: HTML 侧栏壳

**Files:**
- Modify: `mcp_client.html`（在 `#orchestrateWorkbench` 旁、`</div>` of `.chat-area` 内）

- [ ] **Step 1: Add markup**

在 `orchestrateWorkbenchBackdrop` 之后、`.chat-area` 闭合前插入：

```html
<aside id="relatedMaterials" class="related-materials" aria-label="相关资料" hidden>
  <div class="related-materials-header">
    <span class="related-materials-title">相关资料</span>
    <button type="button" id="relatedMaterialsClose" class="related-materials-close" title="关闭" aria-label="关闭相关资料">×</button>
  </div>
  <div class="related-materials-segments" role="tablist" aria-label="资料类型">
    <button type="button" class="related-materials-segment is-active" data-segment="law" role="tab" aria-selected="true">法规</button>
    <button type="button" class="related-materials-segment" data-segment="case" role="tab" aria-selected="false">案例</button>
  </div>
  <div id="relatedMaterialsBody" class="related-materials-body" role="tabpanel"></div>
</aside>
<div id="relatedMaterialsBackdrop" class="related-materials-backdrop" hidden></div>
```

- [ ] **Step 2: Wire elements + cache-bust**

在 `mcp_client.js` 的 `elements` 对象增加：

```javascript
relatedMaterials: document.getElementById('relatedMaterials'),
relatedMaterialsBody: document.getElementById('relatedMaterialsBody'),
relatedMaterialsClose: document.getElementById('relatedMaterialsClose'),
relatedMaterialsBackdrop: document.getElementById('relatedMaterialsBackdrop'),
```

`mcp_client.html`：`mcp_client.css?v=20260907rel1`、`mcp_client.js?v=20260907rel1`

- [ ] **Step 3: Smoke assert HTML ids exist in file**

在 `tests/test_related_materials_smoke.js` 先写：

```javascript
assert.ok(html.includes('id="relatedMaterials"'));
assert.ok(html.includes('id="relatedMaterialsBackdrop"'));
```

Run: `node tests/test_related_materials_smoke.js`（可先只 assert HTML，其它断言后续任务补齐）

- [ ] **Step 4: Commit（可选）**

---

### Task 3: CSS — 推开 / 浮层 / Tab / 列表

**Files:**
- Modify: `mcp_client.css`

- [ ] **Step 1: Add styles**（紧接 `.chat-main-column` / workbench 样式附近）

```css
/* 相关资料侧栏 */
.related-materials {
  display: none;
  flex-direction: column;
  width: 380px;
  max-width: 42vw;
  flex-shrink: 0;
  border-left: 1px solid #e2e8f0;
  background: #fff;
  min-height: 0;
  z-index: 18;
}
.chat-area.is-related-open .related-materials {
  display: flex;
}
.related-materials-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid #e2e8f0;
}
.related-materials-title {
  font-size: 15px;
  font-weight: 600;
  color: #1a1a2e;
}
.related-materials-close {
  border: none;
  background: transparent;
  font-size: 22px;
  line-height: 1;
  color: #64748b;
  cursor: pointer;
  padding: 0 4px;
}
.related-materials-segments {
  display: flex;
  gap: 0;
  margin: 12px 14px 0;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}
.related-materials-segment {
  flex: 1;
  border: none;
  background: #fff;
  color: #334155;
  padding: 8px 12px;
  font-size: 13px;
  cursor: pointer;
}
.related-materials-segment.is-active {
  background: #1a1a2e;
  color: #fff;
}
.related-materials-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px 20px;
}
.related-materials-item {
  display: flex;
  gap: 10px;
  padding: 12px 0;
  border-bottom: 1px solid #f1f5f9;
  text-align: left;
  width: 100%;
  border-left: none;
  border-right: none;
  border-top: none;
  background: transparent;
  cursor: pointer;
  font: inherit;
  color: inherit;
}
.related-materials-item:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}
.related-materials-item-index {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #f1f5f9;
  color: #64748b;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.related-materials-item-title {
  font-size: 14px;
  font-weight: 600;
  color: #1a1a2e;
  margin-bottom: 4px;
}
.related-materials-item-snippet {
  font-size: 12px;
  color: #64748b;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.related-materials-empty {
  margin: 24px 0;
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
}
.related-materials-backdrop {
  display: none;
}
.related-materials-tab {
  display: inline-flex;
  align-items: center;
  margin-top: 10px;
  padding: 6px 12px;
  border: none;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
  cursor: pointer;
  font: inherit;
}
.related-materials-tab:hover {
  background: #e2e8f0;
  color: #1a4a6e;
}
.related-materials-tab[aria-pressed="true"] {
  background: #e8eef3;
  color: #1a4a6e;
}

@media (max-width: 899px) {
  .chat-area.is-related-open .related-materials {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(380px, 92vw);
    max-width: none;
    box-shadow: -8px 0 24px rgba(15, 23, 42, 0.12);
    z-index: 30;
  }
  .related-materials-backdrop:not([hidden]) {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 42, 0.35);
    z-index: 25;
  }
}
```

- [ ] **Step 2: Smoke assert CSS classes**

```javascript
assert.ok(css.includes('.related-materials-tab'));
assert.ok(css.includes('chat-area.is-related-open'));
assert.ok(css.includes('@media (max-width: 899px)'));
```

- [ ] **Step 3: Commit（可选）**

---

### Task 4: 侧栏 open / close / render + 事件绑定

**Files:**
- Modify: `mcp_client.js`

- [ ] **Step 1: State + render/open/close**

```javascript
let relatedMaterialsSourceId = null;
let relatedMaterialsParts = { laws: [], cases: [] };
let relatedMaterialsSegment = 'law';

function isRelatedMaterialsOpen() {
  const area = document.querySelector('.chat-area');
  return !!(area && area.classList.contains('is-related-open'));
}

function renderRelatedMaterialsBody() {
  const body = (elements && elements.relatedMaterialsBody) || document.getElementById('relatedMaterialsBody');
  if (!body) return;
  const list = relatedMaterialsSegment === 'case' ? relatedMaterialsParts.cases : relatedMaterialsParts.laws;
  body.innerHTML = '';
  if (!list || !list.length) {
    const empty = document.createElement('p');
    empty.className = 'related-materials-empty';
    empty.textContent = relatedMaterialsSegment === 'case' ? '暂无案例' : '暂无法规';
    body.appendChild(empty);
    return;
  }
  list.forEach(function (c, i) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'related-materials-item';
    const title = (c.title || '文献').trim() || '文献';
    const article = (c.article || '').trim();
    const head = article ? title + ' ' + article : title;
    const snippet = (c.snippet || '').trim();
    btn.innerHTML =
      '<span class="related-materials-item-index">' +
      (i + 1) +
      '</span><span class="related-materials-item-main"><div class="related-materials-item-title"></div><div class="related-materials-item-snippet"></div></span>';
    btn.querySelector('.related-materials-item-title').textContent = head;
    btn.querySelector('.related-materials-item-snippet').textContent = snippet;
    if (!c.file_id) {
      btn.disabled = true;
      btn.title = '未关联源文件';
    } else {
      btn.onclick = function () {
        openCitationPreview(c);
      };
    }
    body.appendChild(btn);
  });
}

function syncRelatedMaterialsSegmentUi() {
  const root = (elements && elements.relatedMaterials) || document.getElementById('relatedMaterials');
  if (!root) return;
  root.querySelectorAll('.related-materials-segment').forEach(function (btn) {
    const on = btn.getAttribute('data-segment') === relatedMaterialsSegment;
    btn.classList.toggle('is-active', on);
    btn.setAttribute('aria-selected', on ? 'true' : 'false');
  });
}

function openRelatedMaterials(sourceId, citations) {
  relatedMaterialsSourceId = sourceId || null;
  relatedMaterialsParts = partitionCitations(citations);
  relatedMaterialsSegment = defaultRelatedMaterialsSegment(relatedMaterialsParts);
  const panel = (elements && elements.relatedMaterials) || document.getElementById('relatedMaterials');
  const backdrop = (elements && elements.relatedMaterialsBackdrop) || document.getElementById('relatedMaterialsBackdrop');
  const area = document.querySelector('.chat-area');
  if (panel) {
    panel.hidden = false;
  }
  if (area) area.classList.add('is-related-open');
  if (backdrop) {
    if (window.matchMedia && window.matchMedia('(max-width: 899px)').matches) {
      backdrop.hidden = false;
    } else {
      backdrop.hidden = true;
    }
  }
  syncRelatedMaterialsSegmentUi();
  renderRelatedMaterialsBody();
  document.querySelectorAll('.related-materials-tab').forEach(function (tab) {
    const on = tab.getAttribute('data-cite-source-id') === relatedMaterialsSourceId;
    tab.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
}

function closeRelatedMaterials() {
  relatedMaterialsSourceId = null;
  const panel = (elements && elements.relatedMaterials) || document.getElementById('relatedMaterials');
  const backdrop = (elements && elements.relatedMaterialsBackdrop) || document.getElementById('relatedMaterialsBackdrop');
  const area = document.querySelector('.chat-area');
  if (panel) panel.hidden = true;
  if (area) area.classList.remove('is-related-open');
  if (backdrop) backdrop.hidden = true;
  document.querySelectorAll('.related-materials-tab').forEach(function (tab) {
    tab.setAttribute('aria-pressed', 'false');
  });
}

function clearRelatedMaterialsState() {
  closeRelatedMaterials();
  relatedMaterialsParts = { laws: [], cases: [] };
}

function toggleRelatedMaterialsFromTab(sourceId, citations) {
  if (isRelatedMaterialsOpen() && relatedMaterialsSourceId === sourceId) {
    closeRelatedMaterials();
    return;
  }
  openRelatedMaterials(sourceId, citations);
}

function initRelatedMaterialsUi() {
  const closeBtn = (elements && elements.relatedMaterialsClose) || document.getElementById('relatedMaterialsClose');
  const backdrop = (elements && elements.relatedMaterialsBackdrop) || document.getElementById('relatedMaterialsBackdrop');
  const panel = (elements && elements.relatedMaterials) || document.getElementById('relatedMaterials');
  if (closeBtn && !closeBtn._rmBound) {
    closeBtn._rmBound = true;
    closeBtn.addEventListener('click', closeRelatedMaterials);
  }
  if (backdrop && !backdrop._rmBound) {
    backdrop._rmBound = true;
    backdrop.addEventListener('click', closeRelatedMaterials);
  }
  if (panel && !panel._rmSegBound) {
    panel._rmSegBound = true;
    panel.querySelectorAll('.related-materials-segment').forEach(function (btn) {
      btn.addEventListener('click', function () {
        relatedMaterialsSegment = btn.getAttribute('data-segment') === 'case' ? 'case' : 'law';
        syncRelatedMaterialsSegmentUi();
        renderRelatedMaterialsBody();
      });
    });
  }
  if (!window._rmEscBound) {
    window._rmEscBound = true;
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && isRelatedMaterialsOpen()) closeRelatedMaterials();
    });
  }
}
```

在现有 `initOrchestrateWorkbenchUi()` 调用处（或 `DOMContentLoaded` / init 成功路径）同样调用 `initRelatedMaterialsUi()`。

在所有 `clearOrchestrateWorkbenchState()` 调用旁增加 `clearRelatedMaterialsState()`（至少：`loadSession`、新建会话、删除当前会话、清空聊天）。

- [ ] **Step 2: Manual sanity** — 打开页面控制台调用 `openRelatedMaterials('t1', [{doc_type:'law',title:'测试',snippet:'摘要'}])` 应出现侧栏。

- [ ] **Step 3: Commit（可选）**

---

### Task 5: 挂载 Tab；停止渲染 `.cite-list`

**Files:**
- Modify: `mcp_client.js`（`renderAssistantAnswerWithCitations`、新增 `appendRelatedMaterialsTab`）

- [ ] **Step 1: `appendRelatedMaterialsTab`**

```javascript
function ensureCiteSourceId(messageEl) {
  if (!messageEl) return null;
  let id = messageEl.getAttribute('data-cite-source-id');
  if (!id) {
    id = messageEl.getAttribute('data-turn-id') || ('cite-src-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8));
    messageEl.setAttribute('data-cite-source-id', id);
  }
  return id;
}

function appendRelatedMaterialsTab(messageEl, citations) {
  if (!messageEl) return null;
  const parts = partitionCitations(citations);
  if (!parts.laws.length && !parts.cases.length) {
    const old = messageEl.querySelector('.related-materials-tab');
    if (old) old.remove();
    return null;
  }
  const sourceId = ensureCiteSourceId(messageEl);
  let tab = messageEl.querySelector('.related-materials-tab');
  if (!tab) {
    tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'related-materials-tab';
    tab.setAttribute('aria-pressed', 'false');
    const host =
      messageEl.querySelector('.message-content') ||
      messageEl.querySelector('.conclusion-content') ||
      messageEl;
    const actions = host.querySelector('.assistant-msg-actions');
    if (actions) host.insertBefore(tab, actions);
    else host.appendChild(tab);
  }
  tab.setAttribute('data-cite-source-id', sourceId);
  tab.textContent = formatRelatedMaterialsTabLabel(parts) + ' >';
  tab.onclick = function (e) {
    e.preventDefault();
    e.stopPropagation();
    toggleRelatedMaterialsFromTab(sourceId, citations);
  };
  return tab;
}
```

- [ ] **Step 2: Change `renderAssistantAnswerWithCitations`**

```javascript
function renderAssistantAnswerWithCitations(answerEl, plainText, citations, listHost) {
  const list = normalizeCitationsList(citations);
  const text = plainText || '';
  if (answerEl) {
    if (!text) {
      answerEl.hidden = true;
      answerEl.innerHTML = '';
    } else {
      answerEl.hidden = false;
      answerEl.innerHTML = linkifyPlainTextWithCitations(text, list);
      bindInlineCitationClicks(answerEl, list);
    }
  }
  // Spec: do not render inline .cite-list
  const msg =
    (listHost && listHost.closest && listHost.closest('.message.assistant')) ||
    (answerEl && answerEl.closest && answerEl.closest('.message.assistant')) ||
    null;
  if (msg) appendRelatedMaterialsTab(msg, list);
}
```

编排路径若 `listHost` 是 `content` 而 `wrap` 是 message：`closest('.message.assistant')` 应命中 `wrap`。

- [ ] **Step 3: 显式接线兜底**

在 `applyOrchestrateSuccess` 于 `appendAssistantMessageActions` 之前或之后：

```javascript
appendRelatedMaterialsTab(targetShell.wrap, collectOrchestrateCitations(data));
```

在 `addMessage` / `addCombinedMessage` 于 actions 前：

```javascript
if (role === 'assistant' && citeList.length) appendRelatedMaterialsTab(messageDiv, citeList);
// combined:
appendRelatedMaterialsTab(messageWrapper, citeList);
```

（若 `renderAssistantAnswerWithCitations` 已挂 Tab，注意 `appendRelatedMaterialsTab` 幂等更新同一按钮，勿重复插入。）

- [ ] **Step 4: Copy 排除 Tab**

`getAssistantMessagePlainText` 的 selector 增加 `.related-materials-tab`：

```javascript
clone.querySelectorAll('.cite-list, .related-materials-tab, .assistant-msg-actions, ...')
```

- [ ] **Step 5: Run tests**

```bash
node tests/test_related_materials.js
node tests/test_related_materials_smoke.js
```

Smoke 应断言：

```javascript
assert.ok(js.includes('function appendRelatedMaterialsTab'));
assert.ok(js.includes('appendRelatedMaterialsTab(targetShell.wrap'));
assert.ok(!/renderAssistantAnswerWithCitations[\s\S]{0,400}renderCitationList\(host/.test(js) ||
  js.includes('// Spec: do not render inline'));
assert.ok(js.includes('.related-materials-tab'));
assert.ok(html.includes('20260907rel1'));
```

- [ ] **Step 6: Commit（可选）**

---

### Task 6: 手工验收清单（实现者勾选）

- [ ] 有法规+案例的编排回答：无「引用」列表；有「已阅读N条法规，M个案例 >」
- [ ] 点 Tab：宽屏主栏变窄、右栏「相关资料」；法规/案例可切换；条目可预览
- [ ] 仅案例：Tab 含「0条法规」；法规档「暂无法规」
- [ ] 无引用：无 Tab
- [ ] 窄屏（DevTools &lt;900px）：浮层+遮罩；点遮罩/×/Esc 关闭
- [ ] 同 Tab 再点关闭；另一消息 Tab 切换内容
- [ ] 正文内联链接仍打开预览
- [ ] 复制 → toast「已复制成功」；剪贴板无 Tab 文案
- [ ] 「执行过程」抽屉仍可用

---

## Spec coverage check

| Spec 要求 | Task |
|-----------|------|
| 移除 `.cite-list` | Task 5 |
| 已阅读 Tab 文案与计数 | Task 1 + 5 |
| `#relatedMaterials` 独立侧栏 | Task 2–4 |
| 宽屏推开 / 窄屏浮层 | Task 3–4 |
| 法规/案例分段 | Task 4 |
| 内联预览不变 | Task 5（未改 bindInline） |
| 不自动打开 | Task 4–5（无 open 于 success） |
| 会话清理 | Task 4 |
| 复制排除 Tab | Task 5 |
| 测试 | Task 1 + 5 smoke + Task 6 |

## Placeholder scan

无 TBD / 「类似 Task N」占位；Commit 标明可选。
