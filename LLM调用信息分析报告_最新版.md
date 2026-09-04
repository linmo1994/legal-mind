# LLM调用信息分析报告（最新版）

**生成时间**：2025年1月  
**分析范围**：客户端 → 服务端 → LLM API 的完整数据流

---

## 一、数据流概览

```
客户端 (mcp_client.js)
  ↓ buildRequestData()
  ↓ 构建 requestData
  ↓ POST /api/llm/proxy
服务端 (mcp_server.py)
  ↓ _handle_llm_proxy()
  ↓ 构建 messages 数组
  ↓ POST LLM API
LLM API (DeepSeek)
```

---

## 二、客户端发送的数据结构

### 1. buildRequestData() 函数位置
- **文件**：`mcp_client.js`
- **行号**：第1409-1458行

### 2. 完整的 requestData 结构

```javascript
const requestData = {
  // ========== 核心配置 ==========
  system_prompt: CONFIG.systemPrompt || '',  // 从config.json加载的静态系统提示词
  
  // ========== MCP能力信息 ==========
  tools: [],                                  // 工具列表（当前为空数组）
  resources: resources,                       // 资源列表（从mcpResources构建）
  prompts: prompts,                           // 提示词模版列表（从mcpPrompts构建）✅ 已修复
  
  // ========== 会话信息 ==========
  session: {
    session_id: currentSession.sessionId,
    status: currentSession.status,
    current_intent: currentSession.currentIntent,
    collected_parameters: currentSession.collectedParameters,
    missing_parameters: currentSession.missingParameters,
    stage: currentSession.stage,
    context_cache: currentSession.contextCache,
    created_at: currentSession.createdAt,
    updated_at: new Date().toISOString()
  },
  
  // ========== 对话内容 ==========
  conversation_history: currentSession.conversationHistory,  // 历史对话数组
  current_user_input: userInput,                             // 当前用户输入
  
  // ========== LLM配置 ==========
  config: {
    temperature: 0.0,
    max_tokens: 2048,
    response_format: 'text'
  },
  
  // ========== 文件信息 ==========
  file_ids: fileIds  // 文件ID列表（如果有上传文件）
};
```

### 3. 能力信息的构建方式

#### 3.1 资源列表 (resources)
```javascript
const resources = (mcpResources || []).map(r => ({
  uri: r.uri,                    // 资源URI，如 "legal://doc_template"
  description: r.description,    // 资源描述
  parameters: getResourceParameters(r.uri)  // 参数定义（从硬编码的paramMap获取）
}));
```

**参数来源**：`getResourceParameters()` 函数（第1454-1493行）从硬编码的 `paramMap` 获取，不是从MCP服务端动态获取。

#### 3.2 提示词模版列表 (prompts) ✅ 已修复
```javascript
const prompts = (mcpPrompts || []).map(p => ({
  name: p.name,                  // 模版名称，如 "judge_work_guide"
  description: p.description || ''  // 模版描述
}));
```

#### 3.3 工具列表 (tools)
```javascript
tools: []  // 当前为空数组，未实现
```

---

## 三、能力信息的发现与保存

### 1. 能力发现流程

#### 1.1 首次初始化（直接访问多轮对话页）
**位置**：`mcp_client.js` 第780-845行

```javascript
// 1. 获取资源列表
const resourcesResponse = await sendMCPRequest({
  method: 'resources/list'
});
mcpResources = resourcesResponse.result.resources || [];  // ✅ 保存到全局变量

// 2. 获取工具列表
const toolsResponse = await sendMCPRequest({
  method: 'tools/list'
});
// ⚠️ 注意：工具列表未保存到全局变量

// 3. 获取提示词模版列表
const promptsResponse = await sendMCPRequest({
  method: 'prompts/list'
});
mcpPrompts = promptsResponse.result.prompts || [];  // ✅ 保存到全局变量
```

#### 1.2 从首页跳转（复用连接）
**位置**：`mcp_client.js` 第610-638行

```javascript
// ⚠️ 问题：重置为空数组
mcpResources = [];   // ❌ 丢失已发现的能力信息
mcpPrompts = [];     // ❌ 丢失已发现的能力信息

// 跳过重复请求，但未恢复能力信息
// 1. resources/list - 已跳过
// 2. tools/list - 已跳过
// 3. prompts/list - 已跳过
```

**问题分析**：
- 首页已经通过 `resources/list`、`prompts/list` 发现了能力
- 但只保存了数量到 `sessionStorage`（`mcp_resources_count`、`mcp_prompts_count`）
- **没有保存实际的能力列表数据**
- 从首页跳转时，`mcpResources` 和 `mcpPrompts` 被重置为空数组

---

## 四、服务端处理流程

### 1. 接收请求
**位置**：`server/mcp_server.py` 第1656-1676行

```python
def _handle_llm_proxy(self):
    # 读取请求数据
    post_data = self.rfile.read(content_length)
    request_data = json.loads(post_data.decode('utf-8'))
    
    # 打印调试信息
    print(f"[DEBUG] 完整请求数据:")
    print(json.dumps(request_data, ensure_ascii=False, indent=2))
```

### 2. 提取关键字段
**位置**：`server/mcp_server.py` 第1704-1813行

```python
# 提取核心字段
system_prompt = request_data.get('system_prompt', '')
conversation_history = request_data.get('conversation_history', [])
current_user_input = request_data.get('current_user_input', '')
file_ids = request_data.get('file_ids', [])

# ⚠️ 提取能力信息，但未使用
resources = request_data.get('resources', [])  # 未使用
tools = request_data.get('tools', [])           # 未使用
prompts = request_data.get('prompts', [])       # 未使用

# 提取已调用的资源/工具/提示词模版（用于上下文）
resource_data = request_data.get('resource_data')
tool_result = request_data.get('tool_result')
prompt_template = request_data.get('prompt_template')
```

### 3. 构建 messages 数组
**位置**：`server/mcp_server.py` 第1716-1832行

```python
messages = []

# 1. 添加 system 消息（使用原始 system_prompt，未增强）
if system_prompt:
    messages.append({"role": "system", "content": system_prompt})
    # ⚠️ 问题：system_prompt 是静态的，没有包含动态发现的能力信息

# 2. 添加历史对话
for msg in conversation_history:
    messages.append({"role": msg['role'], "content": msg['content']})

# 3. 构建上下文（文件、已调用的资源/工具/提示词模版）
context_parts = []

# 3.1 文件内容
if file_ids:
    # 读取文件内容并添加到上下文
    file_context = "..."
    context_parts.append(file_context)

# 3.2 已调用的资源
if resource_data and resource_uri:
    resource_context = f"[资源已调用] 资源URI: {resource_uri}\n资源数据:\n{resource_data}"
    context_parts.append(resource_context)

# 3.3 已调用的工具
if tool_result and tool_name:
    tool_context = f"[工具已调用] 工具名称: {tool_name}\n工具结果:\n{tool_result}"
    context_parts.append(tool_context)

# 3.4 已调用的提示词模版
if prompt_template and prompt_name:
    prompt_context = f"[提示词模板已调用] 模板名称: {prompt_name}\n模板内容:\n{prompt_template}"
    context_parts.append(prompt_context)

# 4. 合并上下文到用户输入
if context_parts:
    combined_context = "\n\n".join(context_parts)
    current_user_input = combined_context + "\n\n用户问题: " + current_user_input

# 5. 添加当前用户输入
messages.append({"role": "user", "content": current_user_input})
```

### 4. 发送给 LLM API
**位置**：`server/mcp_server.py` 第1843-1849行

```python
llm_request = {
    "model": model,
    "messages": messages,  # 只包含 system、历史对话、用户输入
    "temperature": temperature,
    "max_tokens": max_tokens,
    "stream": stream
}

# 发送请求
response = requests.post(api_url, headers=headers, json=llm_request, stream=stream)
```

---

## 五、问题分析

### 问题1：能力信息未被传递 ✅ 部分修复

**现状**：
- ✅ 客户端已添加 `prompts` 字段到 `requestData`
- ❌ `mcpResources` 和 `mcpPrompts` 在从首页跳转时被重置为空数组
- ❌ 即使发送了 `resources` 和 `prompts` 字段，也可能为空数组

**影响**：
- 服务端收到的 `resources` 和 `prompts` 字段可能为空
- LLM 无法知道当前有哪些可用的资源、工具、提示词模版

### 问题2：服务端未使用能力信息 ❌ 未修复

**现状**：
- 服务端接收了 `resources`、`tools`、`prompts` 字段
- **但这些字段没有被用来增强 `system_prompt`**
- `system_prompt` 是静态的，直接来自 `config.json`

**影响**：
- LLM 只能依赖静态的 `system_prompt` 中的硬编码信息
- 无法根据实际发现的能力动态调整行为
- 如果 MCP 服务端新增了资源或提示词模版，LLM 无法自动感知

### 问题3：能力信息丢失 ❌ 未修复

**现状**：
- 首页通过 `resources/list`、`prompts/list` 发现了能力
- 但只保存了数量到 `sessionStorage`，没有保存实际数据
- 从首页跳转时，`mcpResources` 和 `mcpPrompts` 被重置为空数组

**影响**：
- 从首页跳转后，能力信息丢失
- `buildRequestData()` 构建的 `resources` 和 `prompts` 为空数组

---

## 六、实际发送给 LLM 的信息

### 1. messages 数组结构

```json
[
  {
    "role": "system",
    "content": "你是一名 AI 法律智能体，精通法律实务，可帮助用户完成：\n- 法律文书生成\n- 法律法规检索\n- 类案检索\n- 合同审查意见输出\n- 法官断案（通过提示词模版）\n\n你的工作分为三步：\n1. 理解用户核心需求，确定意图类别：{文书生成, 法规检索, 类案检索, 合同审查, 法官断案, 其他}。\n2. 判断能否用现有资源或提示词模版解决...\n\n--- 资源与必需参数 ---\n* legal://doc_template   → 参数: template_name（模板名，字符串）\n* legal://law_regulation → 参数: query（检索内容，字符串）\n* legal://similar_cases  → 参数: case_description（案情简述，字符串）\n* legal://contract_review_rules → 无需参数\n\n--- 提示词模版与调用规则 ---\n* judge_work_guide（法官工作指南）→ 无需参数，当用户请求\"作为法官帮我断案\"、\"帮我断案\"、\"法官断案\"等类似需求时调用\n\n..."
  },
  {
    "role": "user",
    "content": "用户的历史对话消息1"
  },
  {
    "role": "assistant",
    "content": "AI的历史回复1"
  },
  {
    "role": "user",
    "content": "[附件1]\n文件名称: xxx.docx\n文件内容:\n...\n\n[资源已调用]\n资源URI: legal://doc_template\n资源数据:\n...\n\n用户问题: 请你作为法官帮我断案"
  }
]
```

### 2. 关键发现

**包含的信息**：
- ✅ `system_prompt`：静态的系统提示词（包含硬编码的资源列表和提示词模版说明）
- ✅ `conversation_history`：历史对话
- ✅ `current_user_input`：当前用户输入
- ✅ 文件内容（如果有上传文件）
- ✅ 已调用的资源/工具/提示词模版数据（作为上下文）

**缺失的信息**：
- ❌ 动态发现的资源列表（`resources` 字段未被使用）
- ❌ 动态发现的工具列表（`tools` 字段未被使用）
- ❌ 动态发现的提示词模版列表（`prompts` 字段未被使用）
- ❌ 能力信息的实时状态（哪些资源/工具/模版当前可用）

---

## 七、修复建议

### 修复1：保存能力信息 ✅ 需要实现

**位置**：`mcp_client.js` 第610-638行

**修复方案**：
```javascript
// 从 sessionStorage 恢复能力信息（如果首页已发现）
if (sessionStorage.getItem('mcp_initialized') === 'true') {
  try {
    // 尝试从 sessionStorage 恢复能力列表
    const savedResources = sessionStorage.getItem('mcp_resources');
    const savedPrompts = sessionStorage.getItem('mcp_prompts');
    
    if (savedResources) {
      mcpResources = JSON.parse(savedResources);
      console.log('✅ 从 sessionStorage 恢复资源列表:', mcpResources.length);
    }
    
    if (savedPrompts) {
      mcpPrompts = JSON.parse(savedPrompts);
      console.log('✅ 从 sessionStorage 恢复提示词模版列表:', mcpPrompts.length);
    }
  } catch (e) {
    console.warn('⚠️ 从 sessionStorage 恢复能力信息失败:', e);
    // 如果恢复失败，重新获取
    await fetchCapabilities();
  }
} else {
  // 首次初始化，正常获取
  await fetchCapabilities();
}
```

**在首页保存能力信息**：
```javascript
// 在 home.html 的能力发现后
sessionStorage.setItem('mcp_resources', JSON.stringify(resources));
sessionStorage.setItem('mcp_prompts', JSON.stringify(prompts));
```

### 修复2：服务端动态增强 system_prompt ✅ 需要实现

**位置**：`server/mcp_server.py` 第1704-1724行

**修复方案**：
```python
def build_capabilities_text(resources, tools, prompts):
    """构建能力描述文本"""
    parts = []
    
    if resources:
        parts.append("--- 可用资源（动态发现） ---")
        for r in resources:
            uri = r.get('uri', '')
            desc = r.get('description', '')
            params = r.get('parameters', {})
            parts.append(f"* {uri}")
            if desc:
                parts.append(f"  描述: {desc}")
            if params.get('properties'):
                param_names = list(params['properties'].keys())
                parts.append(f"  参数: {', '.join(param_names)}")
    
    if tools:
        parts.append("\n--- 可用工具（动态发现） ---")
        for t in tools:
            name = t.get('name', '')
            desc = t.get('description', '')
            parts.append(f"* {name}")
            if desc:
                parts.append(f"  描述: {desc}")
    
    if prompts:
        parts.append("\n--- 可用提示词模版（动态发现） ---")
        for p in prompts:
            name = p.get('name', '')
            desc = p.get('description', '')
            parts.append(f"* {name}")
            if desc:
                parts.append(f"  描述: {desc}")
    
    return "\n".join(parts) if parts else ""

# 在构建 messages 时
resources = request_data.get('resources', [])
tools = request_data.get('tools', [])
prompts = request_data.get('prompts', [])

# 动态构建能力描述
capabilities_text = build_capabilities_text(resources, tools, prompts)

# 增强 system_prompt
if capabilities_text:
    enhanced_system_prompt = system_prompt + "\n\n" + capabilities_text
    print(f"[DEBUG] 已增强 system_prompt，添加能力描述（长度: {len(capabilities_text)}）")
else:
    enhanced_system_prompt = system_prompt
    print(f"[DEBUG] 未发现能力信息，使用原始 system_prompt")

# 使用增强后的 system_prompt
if enhanced_system_prompt:
    messages.append({"role": "system", "content": enhanced_system_prompt})
```

### 修复3：工具列表保存 ✅ 需要实现

**位置**：`mcp_client.js` 第805-827行

**修复方案**：
```javascript
// 获取工具列表
let mcpTools = [];
try {
  const toolsResponse = await sendMCPRequest({
    method: 'tools/list'
  });
  
  if (toolsResponse.result) {
    mcpTools = toolsResponse.result.tools || [];  // ✅ 保存到全局变量
    console.log('✅ 已加载工具数量:', mcpTools.length);
  }
} catch (error) {
  console.warn('⚠️ 获取工具列表失败:', error.message);
}

// 在 buildRequestData 中添加工具列表
const tools = (mcpTools || []).map(t => ({
  name: t.name,
  description: t.description || '',
  parameters: t.inputSchema || {}
}));

const requestData = {
  // ...
  tools: tools,  // ✅ 添加工具列表
  // ...
};
```

---

## 八、修复优先级

### 高优先级（必须修复）
1. ✅ **修复1：保存能力信息** - 确保能力信息不丢失
2. ✅ **修复2：服务端动态增强 system_prompt** - 让 LLM 知道实际可用的能力

### 中优先级（建议修复）
3. ✅ **修复3：工具列表保存** - 完善工具支持

### 低优先级（可选）
4. 优化能力信息的缓存策略
5. 添加能力信息的版本管理
6. 支持能力信息的增量更新

---

## 九、总结

### 当前状态
- ✅ 客户端已添加 `prompts` 字段到 `requestData`
- ❌ 能力信息在页面跳转时丢失
- ❌ 服务端未使用能力信息增强 `system_prompt`
- ❌ LLM 只能依赖静态的 `system_prompt`

### 应该实现
- ✅ 客户端保存并传递完整的能力信息（resources、tools、prompts）
- ✅ 服务端动态增强 `system_prompt`，包含实际可用的能力
- ✅ LLM 能够根据实际能力做出决策

### 关键改进点
1. **保存能力信息**：在首页发现能力后保存到 `sessionStorage`，从首页跳转时恢复
2. **传递能力信息**：确保 `buildRequestData()` 包含完整的能力信息
3. **动态增强 system_prompt**：服务端根据实际能力动态构建能力描述并添加到 `system_prompt`

---

## 十、测试建议

### 测试场景1：直接访问多轮对话页
1. 直接打开 `mcp_client.html`
2. 检查控制台，确认 `mcpResources` 和 `mcpPrompts` 已加载
3. 发送一条消息
4. 检查服务端日志，确认 `resources` 和 `prompts` 字段不为空
5. 检查服务端是否增强了 `system_prompt`

### 测试场景2：从首页跳转
1. 打开首页 `home.html`
2. 等待 MCP 初始化完成
3. 点击"历史记录"跳转到多轮对话页
4. 检查控制台，确认 `mcpResources` 和 `mcpPrompts` 已恢复
5. 发送一条消息
6. 检查服务端日志，确认能力信息已传递

### 测试场景3：能力信息增强
1. 发送消息后，检查服务端日志
2. 确认 `enhanced_system_prompt` 包含了动态发现的能力信息
3. 确认 LLM 能够正确识别和使用这些能力

---

**报告结束**
