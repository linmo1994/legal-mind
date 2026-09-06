# PnE draft_doc 挂载文书 Skill

**日期：** 2026-09-06  
**状态：** 已批准  
**范围：** `pe_tools.draft_doc` 注入匹配到的文书类 Skill，指导模型按技能生成完整文书（含文书式落款）。

## 原因

`skills` 已 match 并进入 `tool_ctx`，但 `draft_doc` 未读取，仅用薄系统提示。

## 行为

1. `draft_doc` 从 `ctx["skills"]` 取 Skill；若空且有 `objective`，可再 `SkillService.match(objective, limit=3)`（测试可注入假 match）。  
2. 选用 `applies_to` 含 `doc_writing` 或 `orchestrator` 的条目，拼入系统提示「【内部技能，禁止写入文书正文】」。  
3. 基础系统提示要求：完整文书正文、不编造、缺项【待补充】、结尾文书式落款。  
4. 单测：断言 `write_llm` 的 system 含技能名与落款相关约束。
