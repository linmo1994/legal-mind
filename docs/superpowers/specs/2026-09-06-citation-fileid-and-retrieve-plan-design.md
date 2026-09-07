# 引用可点链接 + 计划纳入法规/类案检索

**日期：** 2026-09-06  
**状态：** 已批准  
**做法：** 做法 2（补全 `file_id` + Prompt 引导 + 计划启发式注入）  
**相关：** `docs/superpowers/specs/2026-09-06-citation-links-preview-design.md`（前端内联/列表已实现；缺 `file_id` 时禁用）

---

## 1. 背景与目标

### 现状

- Plan-and-Execute 可调用 `retrieve_law` / `retrieve_case`，并将 `citations` 返回前端。
- 前端已对正文做 citation linkify，并渲染底部「引用」列表；**无 `file_id` 时按钮 disabled**（提示「未关联源文件」）。
- 实测：检索与 citations 常有标题/条款，但 **`file_id` 为空**，用户感觉「没有带链接的法律/案例」。
- 根因：
  1. FTS-only 命中合并进向量结果时，metadata 未带 `file_id`（`kb_documents` 里其实有）。
  2. 旧 Chroma chunk 仅有 `document_id`（甚至是法律名字符串），无 `file_id` / `title` / `doc_type`。
  3. Planner/Replan/Executor 提示词未明确要求「需要法源时先检索」；漏检时回答无结构化 citations，无法出链。

### 目标

1. **有检索命中且知识库有源文件时**，citations 带上可用的 `file_id`，正文与列表可点开预览。
2. **规划与执行**在需要法条/类案依据时，倾向安排并执行 `retrieve_law` / `retrieve_case`。
3. **轻量计划注入**：目标像法条/类案问答且计划尚未含对应检索时，自动插入检索步骤（类似现有自动 `draft_doc`）。

### 非目标

- 全量重嵌 Chroma / 强制用户重新入库。
- 无 citations 时在前端用正则瞎猜强链。
- 收口硬门闩「无 citations 禁止 response」（做法 3，留作后续）。
- 改动预览组件本身（继续 `KbFilePreview.open(file_id, …)`）。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 链接修复位置 | 后端在 citations 出口统一补全 `file_id` |
| 查找顺序 | hit.`file_id` → `kb_documents.id = document_id` → 按 title / 旧 document_id 文本匹配未删除文档 |
| 规划 | Prompt 明确法规/类案检索义务 |
| 漏检兜底 | 启发式向计划前部注入检索步骤（非硬拦最终答复） |
| 前端 | 不改交互语义；有 `file_id` 即自动可点 |

---

## 3. `file_id` 补全

### 3.1 入口

在 `hits_to_citations`（或紧随其后的 enrich）完成补全，保证 `make_kb_retrieve_fn` → PnE `citations` → API 响应路径一致受益。

可选：`make_kb_retrieve_fn` 构造时注入可调用的 `kb_store`（或 `resolve_file_id(document_id, title, doc_type)`），避免在 `hits_to_citations` 里硬编码全局路径。

### 3.2 解析规则

对每条 citation / hit：

1. 若已有非空 `file_id` → 保留。
2. 若有 `document_id`，且 `kb_store.get_document(document_id)` 存在且未删除 → 取该行 `file_id`；若 citation 缺 `title`/`doc_type` 可一并回填。
3. 否则用 `title`（或旧式 `document_id` 当标题用）在同 `doc_type`（已知则限定 law/case，未知则先 law 再 case）下查找 **status ≠ deleted** 且 title 相等或互相包含的文档；多条时优先 title 完全相等，其次 `updated_at` 更新者。
4. 仍无 → 保持 `file_id` 为空（前端继续禁用，行为与现网一致）。

### 3.3 FTS 合并（可选加固）

`vector_service` FTS-only 分支拼 metadata 时，可不在此直接查库；统一依赖 3.2 即可。若实现方便，也可在合并时把 `document_id` 写全（已有），勿丢 `title`。

### 3.4 测试

- 单元：hit 无 `file_id`、有 `document_id=kb_law_…`，mock store 返回 file_id → citation 含该 id。
- 单元：仅有 title / 旧 document_id=法律名 → 按 title 命中 store。
- 单元：store 无记录 → `file_id` 仍为 null，其余字段不变。
- 既有 `hits_to_citations` 字段/去重/条款解析用例保持通过。

---

## 4. Prompt 引导

在 `server/agents/plan_execute.py`：

**PLANNER_SYSTEM**（要点，非逐字锁定）：

- 用户问题需要法律依据或明确要求检索法规时，计划中应包含法规检索步骤（对应工具 `retrieve_law`）。
- 需要类案/判例参考或明确要求检索案例时，应包含类案检索（`retrieve_case`）。
- 纯闲聊、纯流程确认、或仅收集当事人信息且不涉及实体法结论时，可不检索。

**EXECUTOR_SYSTEM**：

- 当前步骤为检索法规/类案时，分别选择 `retrieve_law` / `retrieve_case`，query 尽量保留用户提到的法名、条款、案由关键词。

**REPLAN_SYSTEM**：

- 若目标仍需法源而过去步骤尚未成功检索，优先 `continue` 并保留/补上检索步骤，再 `response`。
- 最终答复应写明所依据的法规名称与条款（及类案标识），与检索结果一致，便于前端链接匹配。

不改变 JSON 协议与工具白名单。

---

## 5. 计划启发式注入

### 5.1 触发条件（同时满足才注入）

1. 目标文本（含本轮用户补充）像「需要权威依据」的问答，例如含：`第…条`、`法条`、`法规`、`检索`、`依据`、`类案`、`案例`、`判例`，或明显「某法 + 条款」形态；**排除**已由其它闸门主导的纯文书占位流程时可仍允许检索（不互斥）。
2. 当前 `plan` + 已执行 `past_steps` 中，尚未出现对应意图：
   - 需要法规且未见 `retrieve_law` / 步骤文案不含「检索…法/法规」类信号 → 注入法规检索步；
   - 需要类案且未见 `retrieve_case` / 「类案|案例」检索信号 → 注入类案检索步。

### 5.2 注入方式

- 在计划 **前部** 插入自然语言步骤（与现有 plan 元素同形），例如：
  - `检索相关法规并整理可引用条文`
  - `检索相关类案并整理可引用案例`
- 在 `_plan_llm` 返回后、以及 replan `continue` 得到新 plan 后各跑一次归一化（或单一 `_ensure_retrieve_steps(objective, plan, past_steps)`），避免重复插入。
- 遵守 `MAX_PLAN_STEPS`：注入后截断尾部，优先保留检索步 + 原计划前缀。

### 5.3 不触发

- 目标仅为打招呼、改密码、选案件、与法律结论无关的系统操作。
- 已执行过对应 retrieve 工具（即使 citation 为空也不再强插同类型；避免死循环）。

---

## 6. 数据流（验收视角）

```text
用户问法条/类案
  → plan（Prompt + 启发式保证含检索步）
  → executor 选 retrieve_law / retrieve_case
  → hits_to_citations + file_id 补全
  → 最终 response 正文含法名/条款
  → 前端 linkify + 底部引用可点 → KbFilePreview
```

---

## 7. 实现落点

| 文件 | 改动 |
|------|------|
| `server/http_api_extra.py` | `hits_to_citations` 或 enrich；`make_kb_retrieve_fn` 接入 store |
| `server/kb_store.py`（可选） | `find_by_title(doc_type, title)` 若尚无便捷查询 |
| `server/agents/plan_execute.py` | Prompt；`_ensure_retrieve_steps`；plan/replan 后调用 |
| `tests/test_kb_retrieve.py` | file_id 补全用例 |
| `tests/`（PnE） | 注入与「已检索不重复」用例（mock LLM） |
| 前端 | 原则上不改；若需 cache-bust 仅版本号 |

---

## 8. 验收标准

1. 对「请检索劳动合同法第64条并引用法条回答…」：响应 `citations[].file_id` 非空（库中有对应 law 源文件时）；UI 内联与列表可点，预览打开。
2. 故意让 planner 返回不含检索的短计划时，注入后首步仍为法规/类案检索（按目标信号）。
3. 已执行 `retrieve_law` 后不再重复注入法规检索步。
4. 无匹配文档时行为与现网一致（可见引用但不可预览），不报错。
5. 既有 PnE / kb retrieve 单测通过。

---

## 9. 风险与后续

- **Title 模糊匹配**可能链到同名旧版法规：优先 exact title；必要时后续加颁布年份 meta。
- **Prompt 仍可能漏检**：依赖启发式；若线上仍高，再考虑做法 3 收口硬门闩。
- 旧向量库与 kb 双源并存：补全依赖 `kb.db`；未入 kb 的纯 chroma 文档仍可能无 `file_id`。
