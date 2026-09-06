# 编排时间线结果折叠 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 编排工作台「执行时间线」每行可带默认收起的结果摘录；有 `excerpt` 用 `<details>`，无则普通 `<li>`；底部「观察摘要」不变。

**Architecture:** 扩展 `buildWorkbenchTimeline` 为每项填可选 `excerpt`（优先 `past_steps[].observation`，其次 flow `detail.observation` / `detail.note`，外源再回退 `view.external_search`）；`renderOrchestrateWorkbench` 按有无 `excerpt` 分支渲染；CSS 对齐现有徽章行视觉。

**Tech Stack:** 现有 `mcp_client.html` / `mcp_client.css` / `mcp_client.js`（无新框架）

**Spec:** `docs/superpowers/specs/2026-09-06-orchestrate-timeline-collapse-design.md`

## Global Constraints

- 行内 `<details>` **默认不** `open`；刷新/重渲后仍全部收起。
- 摘录约 200–400 字，复用 `excerptObservation`（默认 200）。
- 无 `excerpt` / 空结果：普通 `<li>`，无三角。
- 底部「观察摘要」整块 `<details>` **不改**。
- 不改 PnE / 工具语义 / 预算。
- 提交仅当用户明确要求时执行。

## File map

| File | Responsibility |
|------|----------------|
| `mcp_client.js` | `timelineExcerptFromPast` / `timelineExcerptFromFlow`；`buildWorkbenchTimeline` 填 `excerpt`；时间线渲染 details |
| `mcp_client.css` | timeline `details` / `summary` / `.orchestrate-wb-result` |
| `mcp_client.html` | cache-bust `?v=20260906tl1` |
| `docs/superpowers/specs/2026-09-06-orchestrate-timeline-collapse-design.md` | 状态改为已批准 |

---

### Task 1: `buildWorkbenchTimeline` 填充 `excerpt`

**Files:**
- Modify: `mcp_client.js`（`excerptObservation` 附近、`buildWorkbenchTimeline`）
- Modify: `docs/superpowers/specs/2026-09-06-orchestrate-timeline-collapse-design.md`（状态行）

**Interfaces:**
- Consumes: `excerptObservation(text, limit?)`；`view.past_steps`；`view.flow`；`view.external_search`
- Produces: `TimelineItem = { kind, id, name, excerpt?: string }`；有非空摘录才设 `excerpt`

- [ ] **Step 1: 规格状态改为已批准**

将 spec 顶部 `**状态：** 待审阅` 改为 `**状态：** 已批准`。

- [ ] **Step 2: 增加摘录辅助函数**

在 `buildWorkbenchTimeline` 之前加入（紧挨 `orchestrateToolMeta` 之后亦可）：

```javascript
function timelineExcerptFromPast(p) {
  return excerptObservation(p && p.observation);
}

function timelineExcerptFromFlow(item, view) {
  const d = (item && item.detail) || null;
  if (d && d.observation) return excerptObservation(d.observation);
  if (d && d.note) return excerptObservation(d.note);
  const kind = String((item && item.kind) || '').toLowerCase();
  if (kind === 'external') {
    const es = (view && view.external_search) || {};
    const note = String(es.note || '本地知识库未命中；未自动抓取外网正文，请打开官网核对。');
    const q = String((d && d.query) || es.query || '').trim();
    return excerptObservation(q ? note + ' 检索词：' + q : note);
  }
  return '';
}
```

- [ ] **Step 3: 改 `buildWorkbenchTimeline` 写入 `excerpt`**

将函数改为接收并使用 `view`（已有），在 `pushItem` 时带上摘录：

```javascript
function buildWorkbenchTimeline(view) {
  const items = [];
  const seen = {};
  function pushItem(item) {
    if (!item) return;
    const key = [item.kind, item.id, item.name].join('|');
    if (seen[key]) return;
    seen[key] = true;
    if (item.excerpt) item.excerpt = String(item.excerpt);
    else delete item.excerpt;
    items.push(item);
  }

  (view.past_steps || []).forEach(function (p) {
    if (!p || !p.tool) return;
    const meta = orchestrateToolMeta(p.tool);
    const step = String(p.step || '').trim();
    const excerpt = timelineExcerptFromPast(p);
    const row = {
      kind: meta.kind,
      id: p.tool,
      name: step ? meta.label + ' — ' + step : meta.label
    };
    if (excerpt) row.excerpt = excerpt;
    pushItem(row);
  });

  (view.flow || []).forEach(function (item) {
    if (!item || typeof item !== 'object') return;
    const kind = String(item.kind || '').toLowerCase();
    if (kind === 'plan_step' || kind === 'plan') return;
    if (item.status === 'running') return;
    const excerpt = timelineExcerptFromFlow(item, view);
    const row = {
      kind: kind || 'step',
      id: item.id || '',
      name: item.name || item.id || kind
    };
    if (excerpt) row.excerpt = excerpt;
    pushItem(row);
  });

  return items;
}
```

说明：去重仍以 past_steps 优先；flow 补充项仅在无重复 key 时加入，并可带 detail / 外源摘录。

- [ ] **Step 4: Node 冒烟断言（可选但推荐）**

在仓库根目录执行（一次性内联，不新增测试文件亦可）：

```bash
node -e '
const excerptObservation = (text, limit) => {
  const s = String(text || "").replace(/\s+/g, " ").trim();
  if (!s) return "";
  const max = limit || 200;
  return s.length <= max ? s : s.slice(0, max - 1) + "…";
};
function timelineExcerptFromPast(p) { return excerptObservation(p && p.observation); }
function timelineExcerptFromFlow(item, view) {
  const d = (item && item.detail) || null;
  if (d && d.observation) return excerptObservation(d.observation);
  if (d && d.note) return excerptObservation(d.note);
  const kind = String((item && item.kind) || "").toLowerCase();
  if (kind === "external") {
    const es = (view && view.external_search) || {};
    const note = String(es.note || "本地知识库未命中；未自动抓取外网正文，请打开官网核对。");
    const q = String((d && d.query) || es.query || "").trim();
    return excerptObservation(q ? note + " 检索词：" + q : note);
  }
  return "";
}
const a = timelineExcerptFromPast({ observation: "第六十四条　被派遣劳动者有权……" });
if (!a.includes("第六十四条")) throw new Error("past excerpt");
const b = timelineExcerptFromFlow(
  { kind: "external", detail: { query: "劳动合同法第六十四条" } },
  { external_search: { note: "未自动抓取" } }
);
if (!b.includes("未自动抓取") || !b.includes("检索词")) throw new Error("ext excerpt: " + b);
const c = timelineExcerptFromPast({ observation: "" });
if (c) throw new Error("empty should be empty");
console.log("ok");
'
```

Expected: 打印 `ok`。

---

### Task 2: 渲染 `<details>` + CSS + cache-bust

**Files:**
- Modify: `mcp_client.js`（`renderOrchestrateWorkbench` 时间线循环）
- Modify: `mcp_client.css`（`.orchestrate-wb-timeline` 相关）
- Modify: `mcp_client.html`（`?v=20260906tl1`）

**Interfaces:**
- Consumes: Task 1 的 `TimelineItem.excerpt?`
- Produces: 有 `excerpt` → `<li><details><summary>徽章+名</summary><div class="orchestrate-wb-result">…</div></details></li>`；外源可在结果区追加安全 `<a>`（若能从 `view.external_search.url` 或 flow detail 取到）

- [ ] **Step 1: 改时间线 HTML 分支**

替换 `renderOrchestrateWorkbench` 内时间线 `forEach`（约现 4906–4912 行）为：

```javascript
    timeline.forEach(function (item) {
      const kind = (item && item.kind) || 'step';
      const badge = kind === 'kb' ? '知识库' : (kind === 'external' ? '外源' : kind);
      const name = (item && (item.name || item.id)) || kind;
      const badgeHtml = '<span class="orchestrate-wb-badge ' + kindBadgeClass(kind) + '">' +
        escapeHtml(String(badge)) + '</span>';
      const nameHtml = '<span class="orchestrate-wb-name">' + escapeHtml(String(name)) + '</span>';
      const excerpt = item && item.excerpt ? String(item.excerpt) : '';
      if (excerpt) {
        let resultHtml = '<div class="orchestrate-wb-result">' + escapeHtml(excerpt);
        if (kind === 'external' && view.external_search && view.external_search.url) {
          const u = String(view.external_search.url);
          const label = String(view.external_search.label || '打开官网');
          resultHtml += '<div class="orchestrate-wb-result-link"><a href="' +
            escapeHtml(u) + '" target="_blank" rel="noopener noreferrer">' +
            escapeHtml(label) + '</a></div>';
        }
        resultHtml += '</div>';
        html += '<li class="has-result"><details><summary>' + badgeHtml + nameHtml +
          '</summary>' + resultHtml + '</details></li>';
      } else {
        html += '<li>' + badgeHtml + nameHtml + '</li>';
      }
    });
```

注意：外链只用 `escapeHtml` 转义进属性（与现 `renderExternalSearchHint` 一致）；**不要** `open` 属性。

- [ ] **Step 2: CSS**

在 `.orchestrate-wb-timeline li` 规则后追加（可微调现有 `li` 的 flex，使 details 行仍对齐）：

```css
.orchestrate-wb-timeline li.has-result {
  display: block;
  padding: 0;
}

.orchestrate-wb-timeline details {
  margin: 0;
}

.orchestrate-wb-timeline summary {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 8px 12px;
  cursor: pointer;
  list-style: none;
}

.orchestrate-wb-timeline summary::-webkit-details-marker {
  display: none;
}

.orchestrate-wb-timeline summary::before {
  content: '▶';
  flex-shrink: 0;
  font-size: 10px;
  line-height: 1.6;
  color: #94a3b8;
}

.orchestrate-wb-timeline details[open] > summary::before {
  content: '▼';
}

.orchestrate-wb-name {
  flex: 1;
  min-width: 0;
}

.orchestrate-wb-result {
  margin: 0 12px 10px 28px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.5;
  color: #475569;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
}

.orchestrate-wb-result-link {
  margin-top: 6px;
}

.orchestrate-wb-result-link a {
  color: #3730a3;
  text-decoration: underline;
}
```

无 `has-result` 的普通 `li` 保持原 `display: flex`。

- [ ] **Step 3: cache-bust**

`mcp_client.html`：

```html
<link rel="stylesheet" href="mcp_client.css?v=20260906tl1">
...
<script src="mcp_client.js?v=20260906tl1"></script>
```

- [ ] **Step 4: 手工验收**

1. 有 `retrieve_law` 且有 observation：时间线知识库行默认可展开且收起；展开见法规片段。  
2. 有外源导引：外源行可展开见「未自动抓取」类说明（及链接若有）。  
3. 无 observation 的行：无折叠三角。  
4. 关抽屉再开 / 切回合再渲：默认仍全部收起。  
5. 「观察摘要」整块行为与改前一致。

可用控制台注入假 view 快速验（打开页面后）：

```javascript
// 仅当已有选中 turn 时：改 map 后 render
const id = selectedOrchestrateTurnId;
const v = orchestrateTurnViews.get(id);
if (v) {
  v.past_steps = [{ tool: 'retrieve_law', step: '检索劳动合同法第六十四条', observation: '第六十四条　被派遣劳动者有权……' }];
  v.flow = [{ kind: 'external', id: 'npc_flk', name: '国家法律法规数据库（未自动抓取）', status: 'done', detail: { query: '劳动合同法第六十四条' } }];
  v.external_search = { needed: true, label: '国家法律法规数据库', url: 'https://flk.npc.gov.cn/', note: '本地知识库未命中；未自动抓取外网正文，请打开官网核对。', query: '劳动合同法第六十四条' };
  renderOrchestrateWorkbench();
}
```

---

## Spec coverage (self-review)

| Spec | Task |
|------|------|
| 行内 details 默认收起 | Task 2 |
| excerpt 200–400 / excerptObservation | Task 1 |
| 无 excerpt → 普通 li | Task 1+2 |
| past_steps 优先，flow 补 | Task 1 |
| 外源 note/query | Task 1+2 |
| 观察摘要不变 | Task 2 不改该块 |
| cache-bust | Task 2 |

无 TBD / 占位步骤。
