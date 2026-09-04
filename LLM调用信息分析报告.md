# LLM调用信息分析报告

## 一、当前实现分析

### 1. 客户端发送给服务端的信息

在 `buildRequestData()` 函数中（`mcp_client.js` 第1409-1451行），客户端构建的请求数据包含：

```javascript
const requestData = {
  system_prompt: CONFIG.systemPrompt || '',  // 从config.json加载的系统提示词
  tools: [],                                  // 工具列表（当前为空）
  resources: resources,                       // 资源列表（从mcpResources构建）
  prompts: prompts,                           // 提示词模版列表（从mcpPrompts构建）✅ 已修复
  session: { ... },                          // 会话信息
  conversation_history: [...],               // 对话历史
  current_user_input: userInput,             // 当前用户输入
  config: { ... },                            // LLM配置
  file_ids: [...]                            // 文件ID列表（如果有）
};
```

### 2. 资源列表的构建方式

```javascript
const resources = (mcpResources || []).map(r => ({
  uri: r.uri,
  description: r.description,
  parameters: getResourceParameters(r.uri)  // 从硬编码的paramMap获取
}));
```

**关键问题**：
- `mcpResources` 数组在从首页跳转过来时被设置为空数组 `[]`（第616行）
- 虽然客户端在初始化时通过 `resources/list` 发现了MCP服务端的能力，但这些信息没有被保存和传递

### 3. 服务端处理方式

在 `server/mcp_server.py` 的 `_handle_llm_proxy()` 方法中（第1656-1849行）：

1. **提取system_prompt**：直接从请求数据中提取，不做任何增强
2. **构建messages数组**：
   - 添加system消息（使用原始的system_prompt）
   - 添加历史对话
   - 添加当前用户输入
   - **没有使用resources、tools、prompts字段来增强system_prompt**

3. **发送给LLM**：
   ```python
   llm_request = {
       "model": model,
       "messages": messages,  # 只包含system、历史对话、用户输入
       "temperature": temperature,
       "max_tokens": max_tokens,
       "stream": stream
   }
   ```

## 二、问题分析

### 问题1：能力信息未被传递

**现状**：
- 客户端通过 `resources/list`、`tools/list`、`prompts/list` 发现了MCP服务端的能力
- 但这些信息没有被保存到 `mcpResources`、`mcpTools`、`mcpPrompts` 变量中
- 从首页跳转过来时，这些变量被重置为空数组

**影响**：
- `buildRequestData()` 中的 `resources` 字段为空数组
- `buildRequestData()` 中的 `prompts` 字段缺失（✅ 已修复：已添加prompts字段）
- 服务端收到的 `resources` 和 `prompts` 字段不包含任何实际信息

### 问题2：服务端未使用能力信息

**现状**：
- 服务端虽然接收了 `resources`、`tools`、`prompts` 字段
- 但这些字段没有被用来增强 `system_prompt`
- `system_prompt` 是静态的，写死在 `config.json` 中

**影响**：
- LLM不知道当前有哪些可用的资源、工具、提示词模版
- 只能依赖静态的system_prompt中的硬编码信息

## 三、用户理解 vs 实际实现

### 用户的理解（正确方向）：
> "客户端会将发现的MCP服务端的能力一起发给大模型，而不是提前写死在系统提示词中"

### 实际实现（当前状态）：
1. ✅ 客户端确实发现了MCP服务端的能力（通过 `resources/list` 等）
2. ❌ 但这些能力信息没有被保存和传递（`mcpResources` 为空）
3. ❌ 服务端没有使用这些能力信息来增强system_prompt
4. ❌ system_prompt是静态的，写死在config.json中

## 四、应该实现的正确流程

### 理想实现：

1. **客户端发现能力**：
   ```javascript
   // 在initializeMCP()中
   mcpResources = await getResourcesList();  // 保存资源列表
   mcpTools = await getToolsList();          // 保存工具列表
   mcpPrompts = await getPromptsList();      // 保存提示词模版列表
   ```

2. **构建请求时包含能力信息**：
   ```javascript
   const requestData = {
     system_prompt: CONFIG.systemPrompt,
     resources: mcpResources.map(r => ({
       uri: r.uri,
       name: r.name,
       description: r.description,
       parameters: getResourceParameters(r.uri)
     })),
     tools: mcpTools.map(t => ({
       name: t.name,
       description: t.description,
       parameters: t.inputSchema
     })),
     prompts: mcpPrompts.map(p => ({
       name: p.name,
       description: p.description
     })),  // ✅ 已修复：已添加prompts字段
     // ... 其他字段
   };
   ```

3. **服务端动态增强system_prompt**：
   ```python
   # 在_handle_llm_proxy()中
   resources = request_data.get('resources', [])
   tools = request_data.get('tools', [])
   prompts = request_data.get('prompts', [])
   
   # 动态构建能力描述
   capabilities_text = buildCapabilitiesText(resources, tools, prompts)
   
   # 增强system_prompt
   enhanced_system_prompt = system_prompt + "\n\n" + capabilities_text
   
   # 使用增强后的system_prompt
   messages.append({"role": "system", "content": enhanced_system_prompt})
   ```

## 五、修复建议

### 修复1：保存能力信息
在 `mcp_client.js` 的 `initializeMCP()` 函数中，确保保存发现的能力：
```javascript
// 不要重置为空数组，而是保存实际发现的能力
mcpResources = resourcesData.result.resources || [];
mcpTools = toolsData.result.tools || [];
mcpPrompts = promptsData.result.prompts || [];
```

### 修复2：服务端动态增强system_prompt
在 `server/mcp_server.py` 的 `_handle_llm_proxy()` 方法中：
```python
def build_capabilities_text(resources, tools, prompts):
    """构建能力描述文本"""
    parts = []
    
    if resources:
        parts.append("--- 可用资源 ---")
        for r in resources:
            parts.append(f"* {r.get('uri')} - {r.get('description', '')}")
            params = r.get('parameters', {})
            if params.get('properties'):
                parts.append(f"  参数: {', '.join(params['properties'].keys())}")
    
    if tools:
        parts.append("\n--- 可用工具 ---")
        for t in tools:
            parts.append(f"* {t.get('name')} - {t.get('description', '')}")
    
    if prompts:
        parts.append("\n--- 可用提示词模版 ---")
        for p in prompts:
            parts.append(f"* {p.get('name')} - {p.get('description', '')}")
    
    return "\n".join(parts) if parts else ""

# 在构建messages时
resources = request_data.get('resources', [])
tools = request_data.get('tools', [])
prompts = request_data.get('prompts', [])

capabilities_text = build_capabilities_text(resources, tools, prompts)
if capabilities_text:
    system_prompt = system_prompt + "\n\n" + capabilities_text
```

## 六、总结

### 当前状态：
- ❌ 能力信息未被保存和传递
- ❌ system_prompt是静态的，写死在config.json中
- ❌ LLM不知道动态发现的能力

### 应该实现：
- ✅ 客户端保存发现的能力信息
- ✅ 客户端将能力信息发送给服务端
- ✅ 服务端动态增强system_prompt，包含实际可用的资源、工具、提示词模版
- ✅ LLM能够根据实际能力做出决策

### 关键改进点：
1. 修复 `mcpResources`、`mcpTools`、`mcpPrompts` 的保存逻辑
2. 在 `buildRequestData()` 中包含完整的能力信息
3. 在服务端动态构建能力描述并增强system_prompt
