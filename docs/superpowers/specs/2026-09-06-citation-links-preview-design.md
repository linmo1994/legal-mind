# 多轮对话引用链接与法条预览设计

**日期：** 2026-09-06  
**状态：** 待审阅  
**范围：** `mcp_client` 多轮对话中，助手回答内的法规与类案引用：正文内联可点链接 + 底部引用列表；点击后预览源文件并尽量定位法条。

**相关：** 预览组件 `admin_kb_files.js`（`KbFilePreview.open(fileId, name, { article })`）；检索 citations 见 `server/http_api_extra.py` `hits_to_citations`。

---

## 1. 背景与目标

### 现状

- 编排成功后底部有「引用」按钮（`renderOrchestrateCitations`），有 `file_id` 时可打开预览并高亮 `article`。
- 缺 `file_id` 时按钮禁用。
- 回答正文为纯 `textContent`，文中「《法》第x条」/案号 **不是** 链接。
- 非编排多轮路径未必统一走同一套引用渲染。

### 目标

1. **正文内联链接 + 底部引用列表** 并存。  
2. 覆盖 **多轮对话中所有助手法律答**（编排 + 其它路径），不限 orchestrate。  
3. 支持 **法规 + 类案**。  
4. 点击后复用现有预览：打开法律/类案源文件；法规尽量高亮对应条款。

### 非目标

- 首页单轮会话。  
- 无 citations 时联网反查或正则瞎猜强链。  
- 后端直接返回 HTML 正文。  
- 改动 PnE 预算/工具语义（仅保证 citations 传到前端）。

---

## 2. 决策摘要

| 议题 | 决定 |
|------|------|
| 形态 | 内联 + 底部列表 |
| 范围 | 多轮全部助手法律答 |
| 类型 | 法规 + 类案 |
| 权威数据 | 结构化 `citations`（非自由猜测） |
| 预览 | `KbFilePreview.open(file_id, title, { article })` |

---

## 3. 数据

统一 citation 对象（兼容现有字段）：

```text
{
  file_id?, document_id?, title, article?,
  doc_type?: "law" | "case" | ...,
  snippet?
}
```

- **法规：** `title` = 法律名称；`article` = 条款（如「第六百六十七条」/「第667条」）。  
- **类案：** `title` 优先案号或案例名；`article` 可空。  
- 收集顺序：`data.citations` → 否则合并 `law_citations` + `case_citations`（含 `data.data.*`）。  
- **无 `file_id`：** 仍展示；点击提示「未关联源文件」，不调用预览。

后端：继续用 `hits_to_citations`；排查/保证编排与其它返回路径带上 `file_id`（知识库 meta 已有则不得丢失）。

---

## 4. 渲染

新增统一入口（名可微调）：

`renderAssistantAnswerWithCitations(container, plainText, citations)`

1. 清空/写入回答区（保留容器上其它子节点策略：回答节点与 cite-list 分离，与现 orchestrate shell 兼容）。  
2. **正文：** `escapeHtml(plainText)` 后，根据 citations 构建匹配串（较长优先、互不重叠），例如：  
   - `title + 可选空白 + article`  
   - 单独 `article`（仅当唯一对应某 citation 时，避免误伤）  
   - 类案：`title` / 案号  
   匹配处替换为 `<button type="button" class="cite-inline" data-...>`（或 `<a role="button">`），点击打开预览。  
3. **底部列表：** 升级现有 cite-list，法规与类案均列出；可点则预览。  
4. 未匹配片段保持纯文本。

样式：内联链可辨（下划线/主题色），与 `.cite-link` 视觉家族一致。

---

## 5. 接入点（`mcp_client.js`）

| 路径 | 行为 |
|------|------|
| `applyOrchestrateSuccess` | 用统一渲染替代纯 `textContent` + 现 `renderOrchestrateCitations` |
| 其它多轮助手写入（`addMessage`、流式结束、legacy 完成等） | 若消息/响应带 citations，同样调用 |
| 会话恢复 | `extra.citations`（或 law/case 分列）存盘；`restoreHistoryMessage` 再渲染链接 |

编排会话写入 history 时，assistant `extra` 增加 citations（与 resume_state 等并存）。

---

## 6. 验收

1. 编排答：正文中与 citation 一致的法条/案号可点，底部列表可点，预览打开并（法规）高亮。  
2. 非编排但带 citations 的多轮助手答：同上。  
3. 无 `file_id`：可见但点击有明确提示。  
4. 无 citations：正文纯文本，无错误。  
5. XSS：恶意正文不执行脚本（先 escape 再插链）。

---

## 7. 实现落点（预览）

| 文件 | 改动 |
|------|------|
| `mcp_client.js` | 统一渲染、收集、接入、history extra |
| `mcp_client.css` | `.cite-inline` 等 |
| `mcp_client.html` | cache-bust |
| 可选小测 | 纯函数匹配/escape 的轻量测试或手工冒烟 |

---

## 8. 测试建议

- 手工：检索类问题 → 点内联与底部 → 确认高亮。  
- 若抽 `buildCitePatterns(citations)` / `linkifyEscapedText(escaped, patterns)`，可对匹配优先级写 2–3 个单元断言（可选）。
