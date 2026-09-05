# 法规精检索与引用预览设计

**日期：** 2026-09-05  
**状态：** 已定稿  
**范围：**（1）法名+条号检索纠偏；（2）对话与管理端试检索的可点引用；（3）页内预览并尽量定位到条文（提取文本优先）。

**关联：** `docs/superpowers/specs/2026-09-05-hybrid-retrieval-design.md`（混合检索已定稿）

---

## 1. 背景与目标

### 问题

- 查询「检索劳动合同法第64条」时，FTS 以 `OR` 拼接 token，任意含「第六十四条」的法规（如食品安全法）可进候选并因 BM25/RRF 靠前。
- 未强制「法名与条号同现」，也未对 `title`/`law_name` 做硬提权。
- 检索结果仅为纯文本，无法打开知识库原文件预览。

### 目标

1. **精检索**：法名 + 条号同时出现时，优先召回同名法规下的对应条文。
2. **结构化引用**：检索结果携带可点击所需元数据（至少 `file_id`、`title`、条号线索）。
3. **预览定位**：点击后打开页内预览；对已提取文本高亮并滚动到目标条；PDF 等弱定位格式打开全文并提示查找条号。
4. **入口一致**：多轮对话、管理端知识库试检索；（首页单轮若未走 orchestrate，本版不挂链。）

### 非目标

- PDF.js 页内跳页/高亮。
- Cross-encoder / LLM rerank。
- 更换 embedding 模型。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 检索纠偏 | 法名∧条号（AND/强同现）+ 标题元数据加权 |
| 预览形态 | 整份文件预览；提取文本路径高亮条号并滚动（用户选 B + 落地 1） |
| 引用传递 | 结构化 `citations[]`，非仅 Markdown 字符串 |
| UI 范围 | `mcp_client` + `home` + 管理端试检索 |
| PDF | iframe 全文；顶栏提示查找第 X 条 |

---

## 3. 检索纠偏

### 3.1 查询解析

从用户 query 抽取：

- **条号**：`第[一二三四五六七八九十百千零〇\d]+条`，并规范化同义（如 `第64条` ↔ `第六十四条`）用于匹配。
- **法名线索**：去「检索/帮我/查找」等动词后，保留含「法/条例/规定/办法」的连续片段，或与已知 `title`/`law_name` 最长公共匹配（首期：启发式 + metadata 比对即可）。

### 3.2 FTS 查询构造

当同时存在法名线索与条号时：

- MATCH 使用 **AND** 连接（至少：法名相关 token **AND** 条号 token），禁止「仅条号 OR 其它词」捞全库。
- 仅有条号、无法名：保持现有行为，但融合后若有多部法律，按向量/标题多样性展示并标注不确定性（可选，首期可只靠排序）。

仅有法名、无条号：可对标题命中加权，不强制 AND。

### 3.3 标题索引与加权

- 写入 FTS 时：`body_idx`（或等价字段）包含 **`title`/`law_name` + 正文**（标题前置），便于法名命中。
- 融合后重排：`metadata.title` 或 `law_name` 包含解析出的法名 → 提高 `rrf_score` 或插入置顶档。
- 明确不匹配法名且查询含法名时：降权（不直接丢弃，以免法名抽取失误导致空结果）。

### 3.4 与 hybrid 的关系

- 继续走 `VectorService.search` 统一入口。
- `hybrid=True` 时：向量路 **默认关闭或显著弱化** 仅针对数字/条号的 keyword boost，避免与 FTS 双重偏置；法名字符串 boost 可保留。

### 3.5 回归用例（检索）

- 「劳动合同法第六十四条」/「第64条」：top 结果标题应含劳动合同法（在库内存在该法时）。
- 库内另有「食品安全法第六十四条」时，不得仅因条号相同排在劳动合同法之前（同库有劳动合同法前提下）。

---

## 4. 结构化引用

### 4.1 Citation 字段

每条命中：

```text
{
  "id": "<chunk_id>",
  "doc_type": "law" | "case" | ...,
  "document_id": "...",
  "file_id": "..." | null,
  "title": "...",
  "article": "第六十四条" | null,
  "snippet": "...",
  "rrf_score": number | null
}
```

- `file_id` 来自 chunk/`kb_documents` metadata；缺失则链接禁用或仅展示文本。
- `article`：优先取自查询解析；若 snippet 内匹配到条号可回填。

### 4.2 API / 编排

| 路径 | 行为 |
|------|------|
| `make_kb_retrieve_fn` | 除 `laws`/`cases` 可读字符串外，增加 `law_citations` / `case_citations`（或统一 `citations`） |
| `legal_retrieval` 结果 | `data` 携带 citations；`visible_text` 仍可读，供无链前端降级 |
| `POST` 知识库试检索 | `results[]` 已有 metadata；保证含 `file_id`/`title`，前端可点 |

可读文本中可用轻量标记（可选）：如 `《标题》§第六十四条` 便于前端正则挂链；**权威数据以 citations 数组为准**。

---

## 5. 前端预览与定位

### 5.1 `KbFilePreview` 扩展

```text
open(fileId, fallbackName, options?: { article?: string, highlightTexts?: string[] })
```

- **有 `text_content` 或文本类预览**：将正文放入可滚动容器；对 `article` 及规范化同义做高亮（`<mark>`）；`scrollIntoView({ block: "center" })`。
- **PDF / 图片**：维持现有 iframe/img；header 增加提示：「请在文内查找：第X条」（有 `article` 时）。
- **无 file_id**：toast/文案「该条未关联源文件」。

### 5.2 挂载点

| 页面 | 行为 |
|------|------|
| `mcp_client.js` | 编排回答渲染时，用 `citations` 把法规标题做成按钮/链接，点击 `open` |
| `home.js` | 同上（若走 orchestrate） |
| `admin_kb_laws.html` / `admin_kb_cases.html`（及 templates 若试检索同类） | 试检索结果行：标题可点预览；传入解析出的条号（若 query 含条号） |

复用现有 `admin_kb_files.js`，避免三套预览实现。

### 5.3 权限

预览仍走 `/api/files/:id` 与现有鉴权；无权限时展示错误，不静默失败。

---

## 6. 实现落点（供后续 plan）

- `server/kb_fts.py`：AND 构造、标题写入 `body_idx`、条号规范化 helper。
- `server/vector_service.py`：融合后标题加权；hybrid 下弱化条号 boost。
- `server/http_api_extra.py`：`format_kb_hits` / retrieve 输出 citations。
- `server/agents/orchestrator.py`：透传 citations。
- `admin_kb_files.js`：`open` 选项与高亮滚动。
- `mcp_client.js` / `home.js` / 管理端试检索 JS：挂链。
- 测试：`tests/test_kb_fts.py`、`tests/test_hybrid_search.py`、检索/citations 单测；前端以手工冒烟为主。

---

## 7. 验收标准

1. 在库内同时存在劳动合同法与食品安全法且均含第 64 条时，查询「劳动合同法第64条」首条引用标题为劳动合同法（或并列时劳动合同法不低于对方）。
2. 对话与试检索结果中法规标题可点；有 `file_id` 时打开预览。
3. 提取文本预览下，目标「第X条」可见高亮并进入视口。
4. PDF 预览可打开，并显示查找条号提示。
5. 无 file_id / 无权限时有明确提示，不导致编排崩溃。

---

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 法名抽取不准导致 AND 过严、空结果 | 降权不丢弃；空结果时回退宽松查询并标注 |
| 元数据缺 file_id | 链接灰显；提示在知识库补关联 |
| CJK FTS 仍弱 | 标题前置写入；条号 spacing 已有 `prepare_body_for_fts` |
