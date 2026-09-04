# lawQaText 类型解析实现说明

## 功能概述

实现了客户端对模型返回数据中 `lawQaText` 字段的反序列化解析，识别其中的 `Type` 字段值。当 `Type` 为 `invoke_tool_or_resource` 时，客户端会自动携带必要参数调用相应的工具、资源或提示词列表。

## 实现细节

### 1. 增强 `extractConclusionFromLawQaText` 函数

**位置**: `mcp_client.js` 第2515行

**功能增强**:
- 解析 `lawQaText` JSON 字符串
- 检查 `Type` 或 `type` 字段
- 如果 `Type` 为 `invoke_tool_or_resource`，返回 `null`（特殊标记）
- 否则，继续提取 `prompt_to_user`、`conclusion` 或 `message` 字段

**代码示例**:
```javascript
function extractConclusionFromLawQaText(lawQaText) {
  // ...
  const parsed = JSON.parse(lawQaText);
  
  // 检查Type字段
  if (parsed.Type === 'invoke_tool_or_resource' || parsed.type === 'invoke_tool_or_resource') {
    console.log('🔧 检测到Type为invoke_tool_or_resource，需要调用工具/资源');
    return null; // 特殊标记
  }
  
  // 继续提取其他字段...
}
```

### 2. 新增 `parseInvokeToolOrResource` 函数

**位置**: `mcp_client.js` 第2558行

**功能**:
- 解析 `lawQaText` 中的 `invoke_tool_or_resource` 类型参数
- 提取 `resource_uri`、`tool_name`、`prompt_template`、`parameters` 等字段
- 返回包含这些信息的对象

**返回值结构**:
```javascript
{
  type: 'invoke_tool_or_resource',
  resource_uri: string | null,
  tool_name: string | null,
  prompt_template: string | null,
  parameters: object
}
```

### 3. 更新流式响应处理逻辑

**位置**: `mcp_client.js` 第1359行（`onStreamChunk` 回调）

**功能**:
- 在流式过程中检测 `lawQaText` 是否为 `invoke_tool_or_resource` 类型
- 如果是，暂时不显示结论内容，等待完整响应后再处理

### 4. 更新 `parseAndHandleResponse` 函数

**位置**: `mcp_client.js` 第1671行

**功能**:
- 对于 `type: 7` 格式的响应，检查 `lawQaText` 中的 `Type` 字段
- 如果 `Type` 为 `invoke_tool_or_resource`，解析参数并调用相应的处理函数
- 构建 `invokeResponseData` 对象，传递给 `handleResponseByType`

### 5. 增强 `handleResponseByType` 函数

**位置**: `mcp_client.js` 第1788行

**功能**:
- 在 `invoke_tool_or_resource` case 中，根据参数类型决定调用资源还是工具
- 支持三种调用方式：
  1. **资源调用**: 如果存在 `resource_uri`，调用 `handleResourceInvocation`
  2. **工具调用**: 如果存在 `tool_name`，调用 `handleToolInvocation`
  3. **提示词模板**: 如果存在 `prompt_template`，将其作为资源URI调用

## 数据流

```
模型返回 lawQaText (JSON字符串)
    ↓
parseInvokeToolOrResource() 解析
    ↓
检查 Type 字段
    ↓
Type === 'invoke_tool_or_resource'?
    ↓
是 → 提取参数 (resource_uri/tool_name/prompt_template/parameters)
    ↓
根据参数类型调用相应函数
    ├─ resource_uri → handleResourceInvocation()
    ├─ tool_name → handleToolInvocation()
    └─ prompt_template → handleResourceInvocation() (作为资源URI)
```

## lawQaText JSON 格式示例

### invoke_tool_or_resource 类型

```json
{
  "Type": "invoke_tool_or_resource",
  "resource_uri": "legal://similar_cases",
  "parameters": {
    "case_description": "合同纠纷案件"
  }
}
```

或

```json
{
  "type": "invoke_tool_or_resource",
  "tool_name": "search_similar_cases",
  "parameters": {
    "query": "合同纠纷"
  }
}
```

或

```json
{
  "Type": "invoke_tool_or_resource",
  "prompt_template": "legal://contract_review_rules",
  "parameters": {}
}
```

### 普通响应类型

```json
{
  "prompt_to_user": "请提供更多信息",
  "conclusion": "根据相关法律..."
}
```

## 日志输出

实现中添加了详细的日志输出，便于调试：

- `🔧 检测到Type为invoke_tool_or_resource，需要调用工具/资源`
- `🔧 解析invoke_tool_or_resource参数`
- `🔧 invoke_tool_or_resource: 调用资源/工具，不显示中间结论`
- `资源URI: ...`
- `工具名称: ...`
- `提示词模板: ...`
- `参数: ...`

## 错误处理

如果 `invoke_tool_or_resource` 类型缺少必要的参数（`resource_uri`、`tool_name` 或 `prompt_template`），会显示错误消息：

```
错误：缺少调用资源/工具的必要参数
```

## 测试建议

1. **测试资源调用**:
   - 发送请求，模型返回包含 `resource_uri` 的 `invoke_tool_or_resource` 类型
   - 验证是否正确调用 `handleResourceInvocation`

2. **测试工具调用**:
   - 发送请求，模型返回包含 `tool_name` 的 `invoke_tool_or_resource` 类型
   - 验证是否正确调用 `handleToolInvocation`

3. **测试提示词模板**:
   - 发送请求，模型返回包含 `prompt_template` 的 `invoke_tool_or_resource` 类型
   - 验证是否正确作为资源URI调用

4. **测试普通响应**:
   - 发送请求，模型返回普通响应（不包含 `invoke_tool_or_resource`）
   - 验证是否正常提取和显示结论内容

## 相关文件

- `mcp_client.js`: 客户端主文件
- 修改位置:
  - 第2515行: `extractConclusionFromLawQaText` 函数
  - 第2558行: `parseInvokeToolOrResource` 函数（新增）
  - 第1359行: 流式响应处理逻辑
  - 第1671行: `parseAndHandleResponse` 函数
  - 第1788行: `handleResponseByType` 函数






