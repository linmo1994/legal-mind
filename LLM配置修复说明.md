# LLM配置修复说明

**修复时间**：2025年1月  
**修复内容**：服务端LLM配置的timeout单位转换和重试机制实现

---

## 一、修复内容

### 修复1：timeout 单位转换 ✅

**问题**：
- `config.json` 中 `timeout: 60000`（单位：毫秒）
- 代码中使用 `LLM_CONFIG.get('timeout', 60)`（单位：秒）
- 如果使用配置值，超时时间会是 60000 秒（约16.7小时），而不是预期的60秒

**修复位置**：`server/mcp_server.py` 第1543-1548行

**修复代码**：
```python
# 修复timeout单位：如果大于100，认为是毫秒，转换为秒
timeout = llm_config.get('timeout', 60)
if timeout > 100:
    timeout_seconds = timeout / 1000
    llm_config['timeout'] = timeout_seconds
    print(f"[LLM配置] timeout已从毫秒转换为秒: {timeout}ms -> {timeout_seconds}s")
```

**效果**：
- 自动检测timeout单位（如果>100，认为是毫秒）
- 自动转换为秒
- 打印转换日志，便于调试

---

### 修复2：流式输出重试机制 ✅

**问题**：
- `config.json` 中配置了 `max_retries: 3`
- 代码中未使用，没有实现重试机制
- 如果LLM API调用失败，不会自动重试

**修复位置**：`server/mcp_server.py` 第1941-1968行

**修复代码**：
```python
timeout = LLM_CONFIG.get('timeout', 60)
max_retries = LLM_CONFIG.get('max_retries', 3)
print(f"[DEBUG] 超时设置: {timeout}秒")
print(f"[DEBUG] 最大重试次数: {max_retries}")

# 实现重试机制
retry_count = 0
last_error = None
llm_response = None

while retry_count < max_retries:
    try:
        print(f"[DEBUG] 开始urllib.request.urlopen调用... (尝试 {retry_count + 1}/{max_retries})")
        llm_response = urllib.request.urlopen(req, timeout=timeout)
        print(f"[DEBUG] ✅ DeepSeek API连接成功")
        break
    except Exception as e:
        last_error = e
        retry_count += 1
        if retry_count < max_retries:
            wait_time = retry_count  # 递增等待时间：1秒、2秒、3秒...
            print(f"[DEBUG] ⚠️ LLM API调用失败，{retry_count}/{max_retries}次重试，等待{wait_time}秒后重试...")
            print(f"[DEBUG] 错误信息: {str(e)[:200]}")
            import time
            time.sleep(wait_time)
        else:
            print(f"[ERROR] LLM API调用失败，已重试{max_retries}次，放弃重试")
            raise last_error
```

**效果**：
- 自动重试最多3次（可配置）
- 递增等待时间（1秒、2秒、3秒...）
- 详细的日志输出，便于调试

---

### 修复3：非流式输出重试机制 ✅

**问题**：
- 非流式输出也没有实现重试机制

**修复位置**：`server/mcp_server.py` 第2179-2205行

**修复代码**：
```python
timeout = LLM_CONFIG.get('timeout', 60)
max_retries = LLM_CONFIG.get('max_retries', 3)
print(f"[DEBUG] 非流式输出 - 超时设置: {timeout}秒，最大重试次数: {max_retries}")

# 实现重试机制
retry_count = 0
last_error = None
response = None

while retry_count < max_retries:
    try:
        print(f"[DEBUG] 开始urllib.request.urlopen调用（非流式）... (尝试 {retry_count + 1}/{max_retries})")
        response = urllib.request.urlopen(req, timeout=timeout)
        print(f"[DEBUG] ✅ DeepSeek API连接成功（非流式）")
        break
    except Exception as e:
        last_error = e
        retry_count += 1
        if retry_count < max_retries:
            wait_time = retry_count  # 递增等待时间：1秒、2秒、3秒...
            print(f"[DEBUG] ⚠️ LLM API调用失败，{retry_count}/{max_retries}次重试，等待{wait_time}秒后重试...")
            print(f"[DEBUG] 错误信息: {str(e)[:200]}")
            import time
            time.sleep(wait_time)
        else:
            print(f"[ERROR] LLM API调用失败，已重试{max_retries}次，放弃重试")
            raise last_error

# 如果成功获取响应，读取数据
if response:
    with response:
        response_data = response.read().decode('utf-8')
        # ... 发送响应
```

**效果**：
- 非流式输出也支持重试
- 与流式输出使用相同的重试策略

---

## 二、修复验证

### 1. 语法检查 ✅
```bash
python3 -m py_compile server/mcp_server.py
# 结果：无错误
```

### 2. 配置加载验证

**启动服务时应该看到**：
```
[LLM配置] 从 config.json 加载配置成功
[LLM配置] API URL: https://api.deepseek.com/v1/chat/completions
[LLM配置] Model: deepseek-chat
[LLM配置] API Key: 已配置
[LLM配置] timeout已从毫秒转换为秒: 60000ms -> 60.0s
[LLM配置] Timeout: 60.0秒
[LLM配置] Max Retries: 3
```

### 3. 重试机制验证

**调用LLM时应该看到**：
```
[DEBUG] 超时设置: 60.0秒
[DEBUG] 最大重试次数: 3
[DEBUG] 开始urllib.request.urlopen调用... (尝试 1/3)
[DEBUG] ✅ DeepSeek API连接成功
```

**如果失败，应该看到**：
```
[DEBUG] ⚠️ LLM API调用失败，1/3次重试，等待1秒后重试...
[DEBUG] 错误信息: ...
[DEBUG] 开始urllib.request.urlopen调用... (尝试 2/3)
```

---

## 三、配置说明

### config.json 配置项

```json
{
  "llm": {
    "api_url": "https://api.deepseek.com/v1/chat/completions",
    "api_key": "sk-...",
    "model": "deepseek-chat",
    "timeout": 60000,        // 单位：毫秒（会自动转换为秒）
    "max_retries": 3,        // 最大重试次数
    "temperature": 0.0,
    "max_tokens": 2048
  }
}
```

### 配置项说明

| 配置项 | 类型 | 单位 | 说明 | 默认值 |
|--------|------|------|------|--------|
| `api_url` | string | - | LLM API地址 | `https://api.deepseek.com/v1/chat/completions` |
| `api_key` | string | - | API密钥（必填） | - |
| `model` | string | - | 模型名称 | `deepseek-chat` |
| `timeout` | number | 毫秒 | 请求超时时间（>100认为是毫秒，会自动转换） | 60秒 |
| `max_retries` | number | - | 最大重试次数 | 3 |
| `temperature` | number | - | 温度参数 | 0.0 |
| `max_tokens` | number | - | 最大token数 | 2048 |

---

## 四、重试策略

### 重试条件
- 网络错误（连接失败、超时等）
- HTTP错误（5xx服务器错误）
- 其他可重试的异常

### 重试策略
- **最大重试次数**：3次（可配置）
- **等待时间**：递增策略（1秒、2秒、3秒...）
- **重试间隔**：`wait_time = retry_count` 秒

### 重试流程
```
尝试1 → 失败 → 等待1秒 → 尝试2 → 失败 → 等待2秒 → 尝试3 → 失败 → 抛出异常
```

---

## 五、测试建议

### 测试1：timeout单位转换
1. 确保 `config.json` 中 `timeout: 60000`（毫秒）
2. 启动服务
3. 检查日志，确认看到：`timeout已从毫秒转换为秒: 60000ms -> 60.0s`
4. 调用LLM，确认超时时间为60秒

### 测试2：重试机制（流式）
1. 临时修改API URL为错误地址
2. 发送一条消息
3. 检查日志，确认看到重试日志
4. 确认重试3次后抛出异常

### 测试3：重试机制（非流式）
1. 临时修改API URL为错误地址
2. 发送一条消息（非流式）
3. 检查日志，确认看到重试日志
4. 确认重试3次后抛出异常

---

## 六、修复总结

### ✅ 已修复
1. **timeout单位转换**：自动检测并转换毫秒到秒
2. **流式输出重试机制**：实现自动重试，最多3次
3. **非流式输出重试机制**：实现自动重试，最多3次
4. **配置加载增强**：打印更多配置信息，便于调试

### 📋 改进点
- 自动单位转换，兼容毫秒和秒两种格式
- 递增等待时间，避免频繁重试
- 详细的日志输出，便于问题诊断
- 统一的错误处理，提高系统稳定性

---

**修复完成**
