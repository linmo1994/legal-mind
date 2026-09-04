# 服务端LLM配置检查报告

**检查时间**：2025年1月  
**检查范围**：服务端LLM配置的加载和使用情况

---

## 一、配置加载机制

### 1. 配置加载函数

**位置**：`server/mcp_server.py` 第1526-1562行

```python
def load_llm_config():
    """加载LLM配置"""
    import os
    # 尝试多个可能的路径
    config_paths = [
        'config.json',  # 当前目录
        '../config.json',  # 上级目录
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')  # 项目根目录
    ]
    
    for config_path in config_paths:
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    llm_config = config.get('llm', {})
                    print(f"[LLM配置] 从 {config_path} 加载配置成功")
                    print(f"[LLM配置] API URL: {llm_config.get('api_url', '未配置')}")
                    print(f"[LLM配置] Model: {llm_config.get('model', '未配置')}")
                    print(f"[LLM配置] API Key: {'已配置' if llm_config.get('api_key') else '未配置'}")
                    return llm_config
        except Exception as e:
            print(f"[LLM配置] 尝试从 {config_path} 加载失败: {e}")
            continue
    
    # 如果所有路径都失败，返回默认配置
    print("[LLM配置] 警告：无法从任何路径加载config.json，使用默认配置")
    return {
        'api_url': 'https://api.deepseek.com/v1/chat/completions',
        'api_key': '',  # 需要用户配置
        'model': 'deepseek-chat',
        'timeout': 60,
        'temperature': 0.0,
        'max_tokens': 2048
    }

LLM_CONFIG = load_llm_config()  # 模块级别加载
```

### 2. 配置加载时机

- ✅ **模块导入时加载**：在模块级别执行 `LLM_CONFIG = load_llm_config()`
- ✅ **启动时打印配置信息**：加载成功后会打印配置状态
- ✅ **多路径尝试**：尝试从当前目录、上级目录、项目根目录加载

---

## 二、配置使用情况

### 1. 在 `_handle_llm_proxy()` 中的使用

**位置**：`server/mcp_server.py` 第1679-1935行

#### 1.1 API配置提取

```python
api_url = LLM_CONFIG.get('api_url', 'https://api.deepseek.com/v1/chat/completions')
api_key = LLM_CONFIG.get('api_key', '')
model = LLM_CONFIG.get('model', 'deepseek-chat')

if not api_key:
    raise ValueError("LLM API Key未配置，请检查config.json")
```

**状态**：✅ 已正确使用

#### 1.2 参数配置提取

```python
# 旧格式（messages数组）
temperature = request_data.get('temperature', LLM_CONFIG.get('temperature', 0.0))
max_tokens = request_data.get('max_tokens', LLM_CONFIG.get('max_tokens', 2048))

# 新格式（requestData）
config = request_data.get('config', {})
temperature = config.get('temperature', LLM_CONFIG.get('temperature', 0.0))
max_tokens = config.get('max_tokens', LLM_CONFIG.get('max_tokens', 2048))
```

**状态**：✅ 已正确使用，优先级：请求数据 > 配置文件 > 默认值

#### 1.3 超时配置使用

```python
# 流式输出
with urllib.request.urlopen(req, timeout=LLM_CONFIG.get('timeout', 60)) as llm_response:
    # ...

# 非流式输出
with urllib.request.urlopen(req, timeout=LLM_CONFIG.get('timeout', 60)) as response:
    # ...
```

**状态**：⚠️ **存在问题**（见下文）

---

## 三、配置文件内容

**文件**：`config.json`

```json
{
  "llm": {
    "api_url": "https://api.deepseek.com/v1/chat/completions",
    "api_key": "your-api-key-here",
    "model": "deepseek-chat",
    "timeout": 60000,        // ⚠️ 单位：毫秒
    "max_retries": 3,        // ⚠️ 未使用
    "temperature": 0.0,
    "max_tokens": 2048
  }
}
```

---

## 四、问题分析

### 问题1：timeout 单位不一致 ⚠️

**现状**：
- `config.json` 中 `timeout: 60000`（单位：毫秒）
- 代码中使用 `LLM_CONFIG.get('timeout', 60)`（单位：秒）
- `urllib.request.urlopen()` 的 `timeout` 参数单位是**秒**

**影响**：
- 如果使用配置文件的值，超时时间会是 60000 秒（约16.7小时），而不是预期的60秒
- 如果配置加载失败，使用默认值60秒，这是正确的

**修复建议**：
```python
# 方案1：在加载配置时转换单位
timeout_ms = llm_config.get('timeout', 60000)
timeout_seconds = timeout_ms / 1000 if timeout_ms > 100 else timeout_ms  # 如果大于100，认为是毫秒
llm_config['timeout'] = timeout_seconds

# 方案2：修改config.json，使用秒作为单位
"timeout": 60  // 改为秒

# 方案3：在代码中明确转换
timeout = LLM_CONFIG.get('timeout', 60)
if timeout > 100:  # 如果大于100，认为是毫秒，转换为秒
    timeout = timeout / 1000
```

### 问题2：max_retries 未使用 ⚠️

**现状**：
- `config.json` 中配置了 `max_retries: 3`
- 代码中**没有使用**这个配置
- 当前没有实现重试机制

**影响**：
- 如果LLM API调用失败，不会自动重试
- 用户体验可能受影响

**修复建议**：
```python
max_retries = LLM_CONFIG.get('max_retries', 3)
retry_count = 0
while retry_count < max_retries:
    try:
        # 调用LLM API
        response = urllib.request.urlopen(req, timeout=timeout)
        break
    except Exception as e:
        retry_count += 1
        if retry_count >= max_retries:
            raise
        time.sleep(1)  # 等待1秒后重试
```

---

## 五、配置使用总结

### ✅ 已正确使用的配置

| 配置项 | 配置文件值 | 代码使用 | 状态 |
|--------|-----------|---------|------|
| `api_url` | `https://api.deepseek.com/v1/chat/completions` | ✅ 已使用 | 正常 |
| `api_key` | `sk-...` | ✅ 已使用，有验证 | 正常 |
| `model` | `deepseek-chat` | ✅ 已使用 | 正常 |
| `temperature` | `0.0` | ✅ 已使用（可被请求覆盖） | 正常 |
| `max_tokens` | `2048` | ✅ 已使用（可被请求覆盖） | 正常 |

### ⚠️ 存在问题或未使用的配置

| 配置项 | 配置文件值 | 代码使用 | 问题 |
|--------|-----------|---------|------|
| `timeout` | `60000`（毫秒） | ⚠️ 单位不一致 | 如果使用配置值，超时时间过长 |
| `max_retries` | `3` | ❌ 未使用 | 没有实现重试机制 |

---

## 六、配置验证

### 1. 配置加载验证

**启动服务时应该看到**：
```
[LLM配置] 从 config.json 加载配置成功
[LLM配置] API URL: https://api.deepseek.com/v1/chat/completions
[LLM配置] Model: deepseek-chat
[LLM配置] API Key: 已配置
```

### 2. 配置使用验证

**调用LLM时应该看到**：
```
[DEBUG] API URL: https://api.deepseek.com/v1/chat/completions
[DEBUG] 模型: deepseek-chat
[DEBUG] 温度: 0.0
[DEBUG] 最大token数: 2048
[DEBUG] 超时设置: 60秒  // ⚠️ 注意：这里应该是60秒，但实际可能使用了60000秒
```

---

## 七、修复建议

### 修复1：timeout 单位转换（高优先级）

**位置**：`server/mcp_server.py` 第1526-1562行

```python
def load_llm_config():
    """加载LLM配置"""
    # ... 现有代码 ...
    
    llm_config = config.get('llm', {})
    
    # 修复timeout单位：如果大于100，认为是毫秒，转换为秒
    timeout = llm_config.get('timeout', 60)
    if timeout > 100:
        timeout = timeout / 1000
        llm_config['timeout'] = timeout
        print(f"[LLM配置] timeout已从毫秒转换为秒: {timeout}秒")
    
    return llm_config
```

### 修复2：实现重试机制（中优先级）

**位置**：`server/mcp_server.py` 第1933-1940行（流式）和第2141行（非流式）

```python
max_retries = LLM_CONFIG.get('max_retries', 3)
retry_count = 0
last_error = None

while retry_count < max_retries:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as llm_response:
            # 处理响应
            break
    except Exception as e:
        last_error = e
        retry_count += 1
        if retry_count < max_retries:
            print(f"[DEBUG] LLM API调用失败，{retry_count}/{max_retries}次重试...")
            time.sleep(1)  # 等待1秒后重试
        else:
            print(f"[ERROR] LLM API调用失败，已重试{max_retries}次")
            raise last_error
```

---

## 八、总结

### ✅ 已正确实现

1. **配置加载机制**：从 `config.json` 加载LLM配置
2. **多路径尝试**：尝试多个可能的配置文件路径
3. **配置使用**：API URL、API Key、Model、Temperature、Max Tokens 都已正确使用
4. **配置验证**：API Key 有验证，未配置时会抛出错误

### ⚠️ 需要修复

1. **timeout 单位不一致**：配置文件使用毫秒，代码使用秒
2. **max_retries 未使用**：配置了但未实现重试机制

### 📋 建议

1. **立即修复 timeout 单位问题**：避免超时时间过长
2. **实现重试机制**：提高系统稳定性
3. **添加配置验证**：启动时验证所有配置项的有效性
4. **统一配置单位**：建议在配置文件中使用秒作为单位，更直观

---

**报告结束**
