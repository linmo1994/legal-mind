# 多轮对话：单次 LLM 法律/非法律门闸设计

**日期：** 2026-09-05  
**状态：** 已定稿  
**范围：** 多轮编排（`/api/orchestrate` / `run_orchestrate`）入口增加一次短调用分类；法律问题走现有法律工作流，非法律直接回答并提示更擅长法律。

---

## 1. 背景与目标

### 现状

- 编排依赖关键词 `classify_intent` 细分意图（闲聊、法规检索、类案、文书、合同审查、法律分析）。
- 闲聊有短路径；法律路径走知识库检索 / 文书 specialist。
- 尚无「先模型判断是否法律问题」的统一门闸。

### 目标

1. **一次**短 LLM 调用完成分类：非法律 **或** 法律 + 细意图（不再二次调模型细分）。
2. 非法律：直接调用模型回答用户，并在末尾明确「更擅长法律相关问题」。
3. 法律：用返回的细意图映射现有 `heuristic_plan` / 编排与知识库路径。
4. 分类失败：回退现有关键词 `classify_intent`（稳妥兜底）。

### 非目标

- 独立「小模型」配置档（本期复用主模型短 prompt）。
- 改造首页非 orchestrate 会话协议（二期）。
- 改变 RBAC / case_id 规则。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 分类实现 | 复用主模型，极短 system + 严格 JSON |
| 调用次数 | **单次**：同时给出 domain 与（若法律）intent |
| 非法律 | 通用回答 + 固定擅长法律收尾句；不跑 KB/文书 specialist |
| 法律 | intent → 现有 plan（retrieval_scopes / steps） |
| 失败兜底 | 关键词 `classify_intent` + `heuristic_plan` |

---

## 3. 分类契约

### 3.1 输出 JSON

非法律：

```json
{"domain":"non_legal"}
```

法律：

```json
{"domain":"legal","intent":"law_search"}
```

`intent` 枚举（与现网一致）：

- `law_search`
- `case_search`
- `doc_writing`
- `contract_review`
- `legal_analysis`

说明：

- 若模型输出 `domain=legal` 但缺少合法 `intent` → 对该句再跑关键词 `classify_intent` 补全（不额外 LLM）。
- 若模型把闲聊标成 `domain=legal` 且 intent 乱 → 解析层校验；非法则整单回退关键词。
- 允许模型输出 `domain=non_legal` 覆盖「今天天气」等；也可输出 `{"domain":"legal","intent":"legal_analysis"}` 等。

### 3.2 Prompt 约束

- System：你是分类器，只输出 JSON，不要解释；legal 表示法律法规、类案、诉讼文书、合同审查、案情分析等；non_legal 为其他。
- User：当前用户输入（可选附带上一轮用户句，最长截断）。
- `max_tokens` 小（如 64）；温度低。

### 3.3 解析

- 从回复中截取首个 `{...}`；`json.loads`。
- `domain` 必须为 `legal` | `non_legal`。
- `intent` 仅在 `legal` 时校验枚举。

---

## 4. 路径行为

### 4.1 `non_legal`

1. `write_llm(non_legal_system, user_text, messages)` 生成正文。  
2. 若模型未自带收尾，**追加**固定句（可配置文案）：  
   「另外说明：我更擅长解答法律法规、类案检索与法律文书相关问题，有这类需求随时问我。」  
3. 结果：`agent=general` 或 `text_analysis`，`intent=non_legal`，`subcalls_used=[]`，无 citations / 无检索 MCP。  
4. flow：`orchestrator` →（可选）`return`，可标一步 `classify`。

### 4.2 `legal`

1. `intent` → 与 `heuristic_plan` 相同的 steps / `retrieval_scopes`。  
2. 进入现有 LangGraph / specialist（知识库检索、文书等）。  
3. 不再调用第二次分类 LLM。

### 4.3 兜底

任一情况触发关键词路径：

- 分类 LLM 异常 / 超时 / 空响应  
- JSON 解析失败  
- `domain` 非法  

则：`intent = classify_intent(user_text)`，`plan = heuristic_plan(user_text)`，与改前行为对齐。

---

## 5. 实现落点

| 位置 | 职责 |
|------|------|
| `server/agents/orchestrator.py` 或 `server/agents/intent_gate.py`（新建） | `classify_with_llm(llm_fn, text, messages) -> dict`；解析与兜底 |
| `run_orchestrate` | 在 LLM 计划/启发式之前先跑门闸；`non_legal` 短路径返回 |
| `server/http_api_extra.py` | 传入已有 `write_llm` / 分类用同一 complete 封装（可共用） |
| 测试 | 假 LLM：非法律无 retrieve；法律 law_search 带 scopes；坏 JSON 回退关键词 |

---

## 6. 验收标准

1. 「今天天气怎么样」→ 不调知识库；回答末含擅长法律提示。  
2. 「检索劳动合同法第64条」→ `law_search`（或等价），走法规检索与 KB。  
3. 分类函数抛错 → 行为与纯关键词路径一致（回归现有 orchestrate 测例可插桩）。  
4. 全程法律路径仅 **一次** 分类 LLM 调用（可用假 LLM 计数断言）。

---

## 7. 风险

| 风险 | 缓解 |
|------|------|
| 主模型偶发多说话 | 强约束 + 截取 JSON；失败兜底 |
| 延迟 +1 次短调用 | tokens 限制；可接受 |
| 边界案（法律八卦） | 宁可 legal + analysis；关键词兜底纠偏 |
