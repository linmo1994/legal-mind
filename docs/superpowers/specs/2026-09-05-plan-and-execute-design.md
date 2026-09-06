# Plan-and-Execute 编排环设计

**日期：** 2026-09-05  
**状态：** 待审阅  
**分支：** `feat/agent-orchestration-loop`  
**范围：** 法律问题路径引入显式 Plan-and-Execute（含有限 Replan）；前端计划面板；缺信息时 ask_user 续跑。

---

## 1. 背景与目标

### 现状

- `/api/orchestrate`：intent gate → `plan_for_intent` **查表**得到固定 `steps` → LangGraph 按 `step_index` 执行 specialist → END。
- 计划形状显式，但内容多为模板；**无**根据执行观察改写计划的闭环。
- 工作流可展示已调用节点，**无**「待办计划清单」面板。

### 目标

1. 法律问题走 **Plan-and-Execute**：LLM 产出自然语言步骤 → 逐步执行 → Replan（改剩余计划 / 最终答 / 问用户）。
2. Executor 使用 **白名单工具**，**一步一动**（本期不做步内 ReAct）。
3. 前端 **显式计划面板**（步骤状态 + Replan 整表更新）。
4. 缺关键信息时 **ask_user 中断**，保留状态，用户补充后同会话续跑。
5. 保留 intent gate 与 `non_legal` 短路径；旧 LangGraph specialist 路径作 **可选 fallback**。

### 非目标（本期）

- 步内开放 ReAct 多轮 tool（选项 C）；可预留开关，默认关。
- 删除查表计划 / 旧 LangGraph（不全量替换）。
- 首页非 orchestrate 会话协议改造。
- 多模型分流（planner/executor 仍可用同一 DeepSeek 端点）。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 范式 | Plan-and-Execute + 有限 Replan |
| 步骤形态 | 自然语言字符串列表（非绑死 specialist 流水线） |
| 执行器 | 通用 executor + **工具白名单**；一步最多一个 tool |
| 预算 | ≤8 计划步骤 · ≤5 次 Replan · ≤15 次 tool / 请求 |
| UI | 显式计划面板 |
| 缺信息 | `ask_user` 暂停并续跑 |
| 落点 | **外层新环**；旧 LangGraph 作 fallback（路径 A） |
| 门闸 | 保留；仅 `legal` 进入 PnE |

---

## 3. 架构

```text
POST /api/orchestrate
  → intent gate（保留）
       ├─ non_legal → 现有短答
       └─ legal → Plan-and-Execute
              planner
                → loop: execute(plan[0]) → replan
                     ├─ response     → 最终可见答 + citations
                     ├─ ask_user     → 暂停，返回 pending_question + 状态快照
                     └─ new plan     → 继续（受预算约束）
              超预算 / 不可恢复失败
                → 尽力用 past_steps 收口；仍失败则可选旧 LangGraph fallback
```

### 状态（一等公民）

| 字段 | 含义 |
|------|------|
| `objective` | 用户目标（本轮 user_text，可含续跑上下文摘要） |
| `plan` | `string[]`，**剩余**步骤 |
| `past_steps` | `{step: str, observation: str, tool?: str}[]` |
| `tool_calls_used` | int |
| `replan_count` | int |
| `response` | 可选最终答 |
| `ask_user` / `pending_question` | 可选对用户问题 |
| `citations` | 检索/证据产生的引用（合并） |

---

## 4. 组件

### 4.1 Planner

- 输入：`objective`、messages、可选 case materials 摘要、可用 tool 名说明。
- 输出：严格 JSON `{ "plan": ["...", ...] }`，长度 1–8。
- 失败：重试 1 次 → heuristic 短计划（例如单步 `reason` 或「检索相关法规」+ `reason`）→ 仍失败则旧路径 fallback。

### 4.2 Executor

- 取 `plan[0]`；由 LLM **选择恰好一个** tool 及参数（或 `reason`）。
- 执行 tool，得到 `observation`（截断到合理长度，避免撑爆上下文）。
- 将该步从 `plan` 弹出，追加到 `past_steps`；`tool_calls_used += 1`（`reason` 是否计入 tool：计入，占预算）。
- **禁止**步内连续多 tool（不做选项 C）。

### 4.3 Replanner

- 输入：`objective`、`past_steps`、当前剩余 `plan`、预算余量。
- 输出（互斥之一）：
  - `{ "action": "continue", "plan": ["..."] }` — 仅含**尚未做**的步骤；
  - `{ "action": "response", "response": "..." }`；
  - `{ "action": "ask_user", "question": "..." }`。
- 每次成功 Replan：`replan_count += 1`。
- 达预算：强制走收口（用 past_steps 生成 response）；禁止无限 continue。

### 4.4 工具白名单

| Tool | 行为 | 依赖 |
|------|------|------|
| `retrieve_law` | 法规知识库检索 | 现有 `retrieve_fn` / law scope |
| `retrieve_case` | 类案检索 | case scope |
| `read_evidence` | 按 file_id 读案件证据全文 | `case_id` + case_store + file_service |
| `draft_doc` | 文书起草 / 模板填充，可触发 docx | 现有 doc_writing 能力薄封装 |
| `reason` | 纯 LLM，无外部 IO | `write_llm` |

参数由 executor 的结构化输出给出（如 `query`、`file_id`、`template_hint`）。非法 tool 名 → observation 记错误，交 Replan。

### 4.5 与旧代码关系

- 新建模块（建议）：`server/agents/plan_execute.py`（环）+ `server/agents/pe_tools.py`（工具适配）。
- `run_orchestrate`：legal 默认走 PnE；环境变量 `PLAN_EXECUTE=0` 可关回旧 LangGraph。Fallback 仅用于 PnE 不可恢复失败，不作为日常双轨。
- 现有 specialist **不删除**；`draft_doc` / 检索可内部调用其逻辑，但编排控制权在 PnE，不在查表 steps。

---

## 5. API 与事件

### 5.1 请求

- 既有字段保留：`user_text`、`messages`、`session_id`、`case_id` 等。
- 新增可选：`resume_state`：`{ plan, past_steps, tool_calls_used, replan_count, objective }`  
  - 用户回答 `ask_user` 后，客户端带上服务端上次返回的快照（或 session 服务端缓存；**首期以响应回传 + 客户端回传为准**，避免强依赖新 session 表）。

### 5.2 响应

在现有 `visible_text` / `citations` / `call_flow` 基础上增加：

- `orchestration_mode`: `"plan_execute"` | `"legacy_graph"` | `"non_legal"` …
- `plan`: 当前剩余或最后一轮计划（ask_user / 完成时便于面板展示）
- `past_steps`
- `pending_question`（ask_user 时）
- `status`: `complete` | `awaiting_user` | `error`

### 5.3 SSE / on_event

新增（或扩展）事件：

| kind | 含义 |
|------|------|
| `plan` | 初始或 Replan 后的完整剩余计划 |
| `plan_step` | 开始/完成某一步（含 tool 名） |
| `ask_user` | 进入等待用户 |

前端据此刷新计划面板；兼容现有 agent/mcp/skill 轨迹事件。

---

## 6. 前端计划面板

- 位置：多轮对话工作流区域下方或并列（贴合现有 orchestrate 进度壳，不新开整页）。
- 展示：有序列表；已完成（来自 past_steps）、当前步、剩余 plan。
- Replan：用最新 `plan` 事件 **整表替换**剩余项（已完成项保留在「已完成」区）。
- `awaiting_user`：面板冻结 + 文案「等待你的补充」；用户发送下一条消息时带 `resume_state` 再请求 orchestrate。

---

## 7. 错误与 fallback

| 情况 | 行为 |
|------|------|
| 超预算 | 强制 response 收口；收口失败 → 可选旧 LangGraph；再失败 → 错误 + 现有重试 UI |
| 单步 tool 失败 | observation 记录错误；Replan 换步或 ask_user；不立即 500 |
| Planner/Replanner JSON 坏 | 各重试 1 次 → heuristic / fallback |
| `read_evidence` 无 case_id | observation 说明缺案件；Replan 宜 ask_user 或改步 |

---

## 8. 测试（最小集）

1. 假 LLM：固定 plan → fake `retrieve_law` → replan `response`；断言 past_steps 与可见答。
2. 假 LLM：replan `ask_user`；再带 `resume_state` 续跑至 complete。
3. 人为压低预算：断言停机且不无限循环。
4. `non_legal`：不进入 PnE，无 plan 面板必要字段（或 mode 非 plan_execute）。
5. 回归：现有 intent gate / orchestrate 关键用例仍通过（fallback 路径可单测 mock）。

---

## 9. 验收标准

1. 法律复杂问：面板先出现多步计划，再逐步勾选/更新，最终给出带引用的答。
2. Replan 后剩余步骤列表变化可见。
3. 缺关键事实时出现提问且不假装已结案；用户补充后能续跑完成。
4. 闲聊/非法律仍走短路径，不出现冗长计划空转。
5. 预算内结束；不出现失控连续 tool 风暴。

---

## 10. 实现落点（预览，计划阶段细化）

| 区域 | 文件（预期） |
|------|----------------|
| PnE 环 | `server/agents/plan_execute.py` |
| Tools | `server/agents/pe_tools.py` |
| 接入 | `server/agents/orchestrator.py`、`server/http_api_extra.py` |
| 事件 | `server/agents/workflow.py`（如需扩展 emit） |
| 前端 | `mcp_client.js` / `mcp_client.html` / CSS |
| 测试 | `tests/test_plan_execute.py` 等 |
