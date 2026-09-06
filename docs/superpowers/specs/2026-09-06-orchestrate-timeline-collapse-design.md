# 编排时间线：调用结果默认折叠

**日期：** 2026-09-06  
**状态：** 已批准  
**范围：** `mcp_client` 编排工作台「执行时间线」——知识库 / MCP / 技能 / 工具 / 外源调用结果默认收起，按需展开。

**相关：**  
- 抽屉入口：`docs/superpowers/specs/2026-09-06-orchestrate-drawer-tab-design.md`  
- 外源导引：`docs/superpowers/specs/2026-09-06-kb-external-fallback-hint-design.md`

---

## 1. 背景与目标

### 现状

- 时间线只显示徽章 + 名称；完整 observation 在底部「观察摘要」整块 `<details>` 里。
- 用户希望在时间线行上直接看到各调用（知识库 / MCP / 技能等）的返回结果，但默认隐藏，需要时再展开。

### 目标

1. 时间线每一行：有结果则可展开；**默认收起**。
2. 展开后显示该步结果摘录（非无限全文）。
3. 无结果的行保持普通列表项，不可展开。
4. 底部「观察摘要」整块行为不变（本期不改为逐条折叠）。

### 非目标

- 展开区无限滚动全文、编辑/重跑、SSE 写入折叠态动画。
- 改 PnE 工具语义或预算。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 交互 | 方案 A + 实现 1：行内 `<details>`，默认不 `open` |
| 适用范围 | `kb` / `mcp` / `skill` / `tool` / `external` 等带结果的时间线项 |
| 摘录长度 | 约 200–400 字，与现 `excerptObservation` 同量级 |
| 观察摘要区 | 保持现有整块 details |

---

## 3. UI 行为

```text
▼ 知识库  本地知识库 · 法规 — 检索劳动合同法…
    （收起：仅见徽章+名称）

▶ 知识库  本地知识库 · 法规 — 检索劳动合同法…
    ┌ 结果摘录 ─────────────────────
    │ 第六十四条　被派遣劳动者有权……
    └────────────────────────────────
```

- `<summary>`：徽章 + 名称（与现视觉一致）。  
- `<div class="orchestrate-wb-result">`：摘录纯文本（`escapeHtml`）；外源可含已转义的 note + 检索词（链接若需可在摘录下保留简单 `<a>`，与外源 hint 同安全属性）。  
- 无 `excerpt` / 空结果：渲染为普通 `<li>`，无三角。

---

## 4. 数据

`buildWorkbenchTimeline(view)` 产出项扩展：

```ts
TimelineItem = {
  kind: string,
  id: string,
  name: string,
  excerpt?: string   // 有则 details；无则普通 li
}
```

**摘录来源优先级**

1. 对应 `past_steps[].observation`（与 tool/step 对齐）。  
2. flow 项 `detail.observation` 或 `detail.note`（外源）。  
3. 仍无则不设 `excerpt`。

去重：同一调用若 past_steps 与 flow 皆有，时间线以 past_steps 行为主（现逻辑已偏 past_steps 优先）；flow 补充项仅在无重复时加入，并带 detail 摘录。

复用或抽取 `excerptObservation(text, limit)`（现约 200）。

---

## 5. 实现落点

| 文件 | 改动 |
|------|------|
| `mcp_client.js` | `buildWorkbenchTimeline` 填 `excerpt`；`renderOrchestrateWorkbench` 时间线用 details |
| `mcp_client.css` | `.orchestrate-wb-timeline details` / `summary` / `.orchestrate-wb-result` |
| `mcp_client.html` | cache-bust |

后端可选：无强制字段变更；若 flow `detail` 已含 observation 则足够。

---

## 6. 验收

1. 有 `retrieve_law` 的一轮：时间线知识库行默认可展开且收起；展开见法规片段。  
2. 外源导引行：可展开见「未自动抓取」类说明。  
3. 无结果行：无折叠控件。  
4. 刷新抽屉后默认仍全部收起。  
5. 观察摘要整块行为与改前一致。

---

## 7. 测试建议

- 手工冒烟上述验收（注入 turn view 或真实编排）。  
- 无强制单测；若抽纯函数拼 timeline，可对「有/无 excerpt」断言 1–2 条（可选）。
