# 本地知识库未命中 → 外源导引（国家法律法规数据库）

**日期：** 2026-09-06  
**状态：** 待审阅  
**分支建议：** `feat/agent-orchestration-loop` 或 `feat/kb-external-fallback-hint`  
**范围：** 法规检索本地未命中时，提示并给出国家法律法规数据库外链；不自动抓取外网正文。

**相关：**  
- Plan-and-Execute：`docs/superpowers/specs/2026-09-05-plan-and-execute-design.md`  
- 引用对齐 / 法律名+条文召回：既有 `retrieve_law` + KB 路径  
- 编排 UI：`docs/superpowers/specs/2026-09-06-orchestrate-drawer-tab-design.md`

---

## 1. 背景与目标

### 现状

- 法律问走 PnE，`retrieve_law` → 本地知识库（向量 + FTS）。
- 编排时间线已可标「本地知识库」；本地未命中时模型仍可能空答或臆测，用户不知如何去官网核对。

### 目标

1. 本地法规检索按规则判定 **未命中** 后，返回结构化 **外源导引**（文案 + 可点链接）。
2. **不**自动抓取 / 调用 flk API / MCP 外源工具拉取正文（本期方案 C）。
3. 回答区与编排时间线均可见该导引；本地命中时不出现。
4. 引用列表仍只含本地 KB 命中；外链不当作 `citations`。

### 非目标

- 爬取或入库「国家法律法规数据库」全文。
- 类案 / 证据的外源导引（可后续对称扩展）。
- 多外源择优、付费库、浏览器自动化。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 外源形态 | C：提示 + 官网链接，不抓正文 |
| 未命中规则 | A：结果空，或点名法律/条文与 Top 结果不对齐 |
| 实现路径 | 方案 1：后端判定 + `external_search` 结构，前后端一致展示 |
| 官网 | `https://flk.npc.gov.cn/`（全国人大国家法律法规数据库） |
| 时间线 | `kind=external`（展示「外源」），名称含「国家法律法规数据库」 |

---

## 3. 未命中判定（规则 A）

在 `retrieve_law` 返回的命中（格式化后的 laws / law_citations / 原始 hits）上判定：

| 条件 | `reason` |
|------|----------|
| 无法规命中（空 laws / 空 law_citations / 空 hits） | `empty` |
| 查询含法律名 hint，但 Top-K 无标题匹配该法律 | `law_mismatch` |
| 查询含条文，标题法律匹配（或未要求法律名）但正文均不含目标条文形式 | `article_mismatch` |

- 法律名 / 条文解析复用 `extract_law_name_hint`、`extract_articles`、`doc_has_article`、既有 title 匹配逻辑。
- **命中：** 不生成 `external_search`。
- 仅 `retrieve_case` / 其他工具：本期不触发（YAGNI）。

---

## 4. 数据模型

```ts
LawMissReason = "empty" | "law_mismatch" | "article_mismatch"

ExternalSearchHint = {
  needed: true,
  reason: LawMissReason,
  query: string,           // 建议检索词，如「劳动合同法 第六十四条」
  provider: "npc_flk",
  label: "国家法律法规数据库",
  url: string,             // 可点击；优先深链，否则官网首页
  note: string             // 固定说明：本地未命中；未自动抓取，请打开官网核对
}
```

- 挂载位置（择一为主、可同时出现）：
  - `retrieve_law` / `run_tool` 返回值字段 `external_search`
  - PnE 顶层结果 `external_search`（若本轮任一次法规检索未命中则合并最后一次或列表；**首期取最后一次未命中**即可）
- `past_steps[]` 对应步可含 `channel: "local_kb"`；未命中后再 `emit_step` 外源导引。
- **不**写入 `citations`。

### URL 拼法

1. 构造 `query`：法律名 hint（若有）+ 条文规范形式（若有），空格连接。  
2. `url`：若存在文档化、稳定的官网检索深链，则带上编码后的 `query`；否则 `https://flk.npc.gov.cn/`，`note` / 回答文案中写明「请使用检索词：…」。  
3. 禁止把非官方镜像当作默认 provider。

---

## 5. 编排事件与 UI

### 5.1 后端事件

未命中时：

```text
emit_step("external", "npc_flk", "国家法律法规数据库（未自动抓取）",
          status="done",
          detail={ reason, query, url })
```

本地检索仍先发 `kb` 事件（已有「本地知识库 · 法规」）。

### 5.2 回答区

- 条件：`external_search.needed === true`。  
- 位置：正文下方、引用列表附近（有引用则引用后；无引用则正文后）。  
- 内容：简短说明 + 建议检索词 + 按钮/链接「打开国家法律法规数据库」（`target=_blank`，`rel=noopener`）。  
- 不替代「库内无条文」的诚实说明；可与模型 visible_text 并存，避免假装已引用官网正文。

### 5.3 编排工作台

- 时间线：徽章「外源」，文案同 emit name。  
- 观察摘要：可选一行 miss reason（中文映射：`empty`→无结果，`law_mismatch`→法律名不匹配，`article_mismatch`→条文未命中）。

---

## 6. 实现落点（预览）

| 区域 | 预期 |
|------|------|
| `server/kb_query_parse.py` 或小模块 | `assess_law_retrieve_miss(query, hits/citations) -> Optional[hint]` |
| `server/agents/pe_tools.py` | `retrieve_law` 调用判定，填充 `external_search` |
| `server/agents/plan_execute.py` | 上提字段；`emit_step` external |
| `mcp_client.js/css` | 渲染提示块；时间线 `kind=external`；cache-bust |
| 测试 | miss 三分支单测；命中不生成 hint；URL/query 拼装 |

后端接口字段向后兼容：旧客户端忽略未知字段即可。

---

## 7. 验收

1. 本地能命中劳动合同法某条：无外源块；时间线仅有知识库。  
2. 查询不存在的法/条或库内无对齐命中：出现提示块 + 可打开 flk 链接；时间线有「外源」。  
3. 外链不当作引用按钮，不打开 KbFilePreview。  
4. 文案明确「未自动抓取」。  
5. 类案-only 查询不误触发（本期）。

---

## 8. 测试建议

- 单元：`assess_law_retrieve_miss` 对 empty / law_mismatch / article_mismatch / 命中。  
- `retrieve_law` 返回结构含/不含 `external_search`。  
- 手工：硬刷新后问一条库内有的、一条故意没有的。

---

## 9. 后续（不在本期）

- MCP 工具 / HTTP API 自动检索 flk 并可选入库。  
- 类案外源对称导引。  
- 稳定深链若官方变更则配置化。
