# 模版库匹配 + 要素式 Word 表格填充（设计）

**日期：** 2026-09-07  
**分支：** `feat/approval-flow`（能力独立；可与审批流后续衔接）  
**状态：** 已定稿待实现计划  

## 背景与目标

用户要写法律文书（如「民间借贷纠纷起诉状」）时，系统应：

1. 在模版库中自动匹配得分最高的模版；
2. 若为**要素式 Word（表格）**，在**保留原表格结构**的前提下，将当事人等要素填入单元格；
3. 填充数据来自**当前选中案件材料 + 用户本轮补充**；缺项标注【待补充】；
4. 匹配失败或分数过低时，**降级自由起草**，并在回复中说明未命中模版。

成功标准：

- 库中存在对应起诉状模版时，输出为基于该 docx 填表后的 Word，结构与源模版一致（表格不因「全文重写」丢失）；
- 无合适模版时仍能出文书，并标明「未命中模版库，已自由起草」；
- 回复中简要展示所用模版名称（自动选用，无需用户确认）。

## 已确认决策

| 项 | 选择 |
|----|------|
| 匹配后是否确认 | **A** 自动用最高分模版直接填充 |
| 案件信息来源 | **C** 选中案件卷宗 + 用户补充；缺项【待补充】 |
| 未命中模版 | **B** 降级自由起草并说明未命中 |
| 实现挂载点 | **方案 1** 在 PnE `draft_doc` 内完成「匹配 → 取模版 → 填充」 |
| 要素式形态 | Word 表格；支持 **占位符** 与 **左标签→右空白格**（C） |
| 要素抽取 | **允许**规则优先，不足时用轻量 LLM 补全要素字典（推荐已采纳） |

## 非目标（一期）

- 用户点选 Top-N 候选模版；
- 审批流（本能力可独立上线，审批另开设计）；
- 覆盖全部法院要素式变体的完美解析（靠标签词典与入库规范迭代）；
- 用「抽纯文本 → LLM 整篇重写 → 再生成 docx」作为要素式主路径（会破坏表格）。

## 现状与缺口

已有：

- 模版库：`doc_type=template`，admin 上传/检索，`kb_template_resolve` 名称模糊匹配，MCP `legal://doc_template`；
- 案件上下文：`case_materials` / `case_context`；
- PnE `draft_doc`：技能 + LLM 自由起草 + `build_docx_bytes`；
- 旧 orchestrator `doc_writing`：可注入模版正文，但仍非表格填槽。

缺口：

- 默认 PnE **不走模版库**；
- 无 **docx 表格槽位扫描与回写**；
- 无统一 **要素字典** 与槽位映射。

## 架构总览

```
用户：「写民间借贷纠纷起诉状」(+ 可选 case_id)
        │
        ▼
  PnE → draft_doc
        │
        ├─ match_template(query, kb) ──分数 < 阈值──► 自由起草 + 「未命中模版」提示
        │         │
        │         ▼ 最高分
        ├─ 加载源 docx (file_id)
        │
        ├─ detect_form_style
        │     ├─ 有表格槽位 ──► extract_slots → build_element_dict → fill_docx_tables → 保存产物
        │     └─ 无槽位/非要素 ──► 模版正文 + LLM 栏目填充 → build_docx_bytes（兼容长文模版）
        │
        └─ 返回 visible_text（含所用模版名）+ artifact 下载
```

## 模版匹配

### 查询串

拼接：用户目标原文 + 案件 meta（案由/类型若有）+ 文书类型线索词（起诉状/答辩状/申请书等）。

### 候选与计分

- 候选：`kb_store.list_documents(doc_type=template)`，排除 `deleted` 与 meta.`validity=失效`。
- 分数（在现有 `_score_match` 上扩展）：
  - 名称全等 / 互相包含（现有 100/80/70）；
  - 共有子串加分（现有）；
  - 用户意图文书类型与 meta.`document_type` 一致则加分；
  - 案由关键词命中 `template_name` 则加分。
- 取**最高分一条**；平分取稳定顺序第一条。
- **阈值**：默认 40（实现时可配置常量）；低于则未命中。

### API 形态（建议）

扩展 `kb_template_resolve`：

- `match_template(kb_store, query, *, file_service=None) -> {name, score, document_id, file_id, meta} | None`
- `load_template_docx_bytes(file_service, file_id) -> bytes`
- 保留现有 `resolve_template_text` 供非要素/兼容路径。

## 要素式表格填充

### 双模式槽位识别（`python-docx`）

遍历所有 table / row / cell：

1. **占位符模式**  
   单元格文本匹配例如：`{...}`、`{{...}}`、`【...】`、以及约定词典中的占位串。  
   槽位：`{ key, mode: "placeholder", table_i, row_i, cell_i, raw }`。

2. **标签→右格模式**  
   同行左格（或合并逻辑简化为「左邻格」）文本规范化后命中标签词典（原告、被告、法定代表人、身份证号、住所地、诉讼请求、事实与理由…），且右格为空或仅空白/下划线/占位。  
   槽位：`{ key, mode: "label_right", table_i, row_i, value_cell_i, label }`。

一期标签词典维护在代码常量（可后续迁配置）；未知标签可忽略或进入「待映射」列表不强制写入。

### 要素字典（element dict）

来源优先级：

1. **规则**：从 `case_context` / 用户文本中抽常见字段（正则/关键词段）；
2. **LLM 补全**：将案件材料摘要 + 用户补充 + **槽位 key 列表**交给短调用，输出 JSON 要素字典；禁止编造，未知填 `null`（落库时写【待补充】）。

写入规则：有值则写入单元格；`null`/空 → `【待补充】`。

### 回写与产物

- 在源模版 docx 副本上改单元格文本（尽量保留 run 样式：能替换整格文本即可，一期不追求复杂混排 run 级保留）；
- `file_service.save_file` 生成新 `file_id`，`artifact` 与现有 `draft_doc` 下载卡片一致；
- `visible_text` 示例：`已根据模版《民间借贷纠纷起诉状》填写要素式文书，请下载核阅。缺项已标【待补充】。`

## 非要素 / 无槽位降级（仍算「命中模版」）

若匹配成功但扫描不到任何槽位：

- 使用 `resolve_template_text` 取正文；
- LLM 按栏目填充（现有 doc_writing 思路）+ `build_docx_bytes`；
- 文案说明「已套用模版结构（非表格填槽）」。

## 未命中模版

- 不调用填表引擎；
- 现有 `draft_doc` 自由起草 + Word；
- 明确提示：`未命中模版库，已按说明自由起草。`

## PnE / 上下文接线

- `tool_ctx` 增加 `kb_store`（及已有 `file_service`、`case_context`、`write_llm`）；
- `draft_doc` 内执行匹配与填充；planner 无需强制拆成两步（执行过程可通过 observation 返回「已匹配《…》/未命中」）。
- 案件材料继续由上层注入的 `case_context` 提供；无案件时仅用用户文本，缺项【待补充】。

## 入库规范（配套，非代码阻断）

- 要素式模版尽量使用清晰左标签或单元格占位符；
- meta 建议：`document_type`、`template_name`、可选 `form_style=element`；
- 失效模版 `validity=失效` 不参与匹配。

## 测试计划（设计层）

- 单元：占位符单元格替换；标签→右格填充；阈值以下返回未命中；
- 单元：要素字典缺字段 → 【待补充】；
- 集成/工具：`draft_doc` 在假 kb + 假 docx 下产出 artifact；
- 回归：无 kb_store 时行为与现网自由起草兼容。

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 法院表格版式差异大 | 双模式 + 词典迭代；扫不到槽则走文本模版路径 |
| LLM 编造当事人 | 提示禁止编造；优先规则；空则【待补充】 |
| 复杂合并单元格 | 一期简化坐标；测真实样张后迭代 |
| 误匹配模版 | 阈值 + document_type 加权；回复展示模版名便于发现 |

## 实现落点（文件级预期）

- `server/kb_template_resolve.py` — 匹配 API 增强  
- 新建如 `server/docx_form_fill.py` — 扫槽、填表、保存 bytes  
- `server/agents/pe_tools.py` — `draft_doc` 接入  
- `server/agents/plan_execute.py` — ctx 下传 `kb_store`  
- `server/http_api_extra.py` / MCP — 编排注入 kb_store  
- `tests/test_docx_form_fill.py`、`tests/test_kb_template_resolve.py`、`tests/test_pe_tools.py`  

## 与审批流

本设计**不依赖**审批流。后续可在「已生成 artifact」后挂接审批；本规格仅覆盖匹配与填充。
