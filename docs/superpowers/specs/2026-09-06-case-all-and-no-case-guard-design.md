# 无案件门禁 + 案件「全选」设计

**日期：** 2026-09-06  
**状态：** 已批准  
**范围：** 未选案件时避免 `read_evidence` 硬失败体验；案件下拉增加「全选」（有权限案件按需读取）。

**相关：** 编排 / PnE 工具 `server/agents/pe_tools.py`、`plan_execute.py`；鉴权 `http_rbac_api.check_orchestrate_access`；前端 `activeCaseSelect`。

---

## 1. 背景与目标

### 现状

- 未选案件时不注入案件材料（正确）。  
- 生成起诉状时规划器仍可能调用 `read_evidence`；缺 `case_id`/`file_id` 返回英文 observation，最终呈现「无法继续执行」类失败感。  
- 下拉无「全选」；鉴权把非 int 的 `case_id` 直接 400。

### 目标

1. **无案件（C）**：需要当事人/证据时先 `ask_user`（选案件、全选，或粘贴当事人信息）；用户坚持无案件后再允许无证据起草（占位，不谎称已读卷宗）。  
2. **全选（B）**：哨兵 `case_id: "*"`；不整包注入全部材料；`read_evidence` 可在用户有权限的案件集合内按需读。  
3. 下拉增加「全选（我有权限的案件）」选项。

### 非目标

- 全选不等于预注入所有案件全文。  
- 不改 PnE 预算上限、法规检索排序。  
- 不做多选 checkbox UI（仅「单案 / 全选 / 未选」三态）。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 全选语义 | B：按需读有权限案件 |
| 无案件文书 | C：先追问，坚持则无案件起草 |
| 实现 | 方案 1：前端哨兵 + 后端工具门禁 |
| 哨兵值 | 字符串 `"*"` |

---

## 3. 协议与 UI

| 下拉 | `case_id` | 说明 |
|------|-----------|------|
| 请选择案件… | `null` / 省略 | 未选 |
| 某案件 | number | 单案 |
| 全选（我有权限的案件） | `"*"` | 权限范围 = 与下拉同源的可见案件 |

前端：`loadActiveCaseOptions` 在占位 option 后插入全选；`LegalMindAuth` 允许存 `"*"`；编排 / LLM 请求原样传递。

---

## 4. 鉴权

`check_orchestrate_access`：

- `case_id === "*"`：合法；**不要** `int("*")`；按无单案 id 做 `cap.chat` / 文案触发的 `cap.doc_write` 等律所级校验；响应可带 `case_scope: "all_permitted"`。  
- 其他非空非数字：仍 400。  
- `null`：保持现有「案件可选」。

`allow_case_material_access` / 单案材料注入：

- `"*"` → **不**走单案 `build_case_material_context`（避免整包注入）。  
- 数字 id → 不变。

---

## 5. 编排与工具

### 5.1 上下文

编排入口解析：

```text
case_id null     → ctx.case_id=None, case_scope=none
case_id int      → ctx.case_id=int,  case_scope=single
case_id "*"      → ctx.case_id=None, case_scope=all_permitted,
                   ctx.permitted_case_ids=[...]  # 当前用户可见案件 id 列表
```

### 5.2 `read_evidence`

| 条件 | 行为 |
|------|------|
| `case_scope=none` 且无可用 file 定位 | 返回**中文** observation：说明缺少案件；请选择案件或「全选」，或补充当事人信息后再继续；`citations=[]`。不抛未捕获异常。 |
| `case_scope=single` | 现逻辑（需 case_id + file_id + store + file_service） |
| `case_scope=all_permitted` | 若 args 含 `case_id`：校验 ∈ permitted 后再读；仅 `file_id`：在 permitted 案件中解析归属（文件元数据/案件文件索引），唯一命中则读，0/多命中则中文 observation 请用户指定案件或 file |

### 5.3 规划 / 重规划提示（最小改动）

在 planner / replan / executor 系统提示中增加要点：

- 无案件时不要假设能读卷宗；缺当事人信息应 `ask_user`。  
- 用户已明确表示不绑定案件、并提供或同意占位时，可用 `draft_doc`/`reason` 起草并标明信息待补。

「用户坚持」判定（务实）：resume 后用户消息含「不选案件 / 先起草 / 没有案件 / 占位」等，或已补充完整原被告信息 → 允许无 `read_evidence` 继续。不强制新状态机字段；以提示 + 工具门禁为主。

### 5.4 `draft_doc`

系统提示已有「不要编造未提供的当事人信息」——保持；无案件起草时 observation/正文对缺失项用「【待补充】」类占位。

---

## 6. 实现落点

| 文件 | 改动 |
|------|------|
| `mcp_client.js` / `.html` | 全选 option；`setCaseId`/`getCaseId` 支持 `"*"`；cache-bust |
| `auth.js` | 存取 `"*"` 不强制 number |
| `server/http_rbac_api.py` | `check_orchestrate_access` 接受 `"*"` |
| `server/http_api_extra.py`（编排入口） | 解析 scope、填充 `permitted_case_ids`、跳过 `"*"` 整包注入 |
| `server/agents/pe_tools.py` | `read_evidence` 门禁与全选解析 |
| `server/agents/plan_execute.py` | ctx 传 scope；提示词补丁 |
| `tests/` | 鉴权 `"*"`；`read_evidence` 无案/全选；可选前端不必单测 |

---

## 7. 验收

1. 未选案件生成起诉状：不再出现生硬「缺少 case_id…」英文堆砌；表现为追问选案/全选/补信息，或可继续的中文说明。  
2. 用户回复坚持无案件并要求先起草：能产出带【待补充】的草稿，而非工具硬失败死局。  
3. 选「全选」：请求 `case_id` 为 `"*"`；鉴权 200；不注入巨型全案上下文。  
4. 全选 + 合法 `file_id`（能唯一归属有权限案件）：`read_evidence` 可读。  
5. 单案行为与改前一致。  
6. 无权限案件 id 在全选下不可读。

---

## 8. 测试建议

- `tests/test_orchestrate_auth.py`：`case_id="*"` 通过；非法字符串仍 400。  
- `tests/test_pe_tools.py`：无案 read_evidence 中文 observation；全选 + mock store 命中/未命中。  
- 手工：下拉全选 → 发编排请求看网络面板 `case_id`。
