# MCP服务连接问题诊断报告

## 检查时间
2024年（当前时间）

## 服务状态检查

### ✅ MCP服务器基础状态

1. **进程状态**
   - 进程ID：49503
   - 状态：正在运行
   - 运行时间：约3小时

2. **端口监听**
   - 端口：8000
   - 状态：正常监听（`*:irdmi`）
   - 协议：TCP

3. **健康检查**
   - URL：`http://localhost:8000/health`
   - 响应：`{"status": "ok"}`
   - 状态：✅ 正常

4. **API测试**
   - 会话API：✅ 正常（返回会话列表）
   - 文件API：✅ 正常（返回文件列表）
   - 静态文件：✅ 正常

### ✅ MCP协议端点测试

**测试结果**：
- POST请求到 `http://localhost:8000/mcp`：✅ 正常响应
- 返回正确的初始化响应：
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {
      "resources": true,
      "prompts": true,
      "tools": true
    },
    "serverInfo": {
      "name": "ai-judge-mcp-server",
      "version": "1.0.0"
    }
  }
}
```

### ✅ CORS配置

**检查结果**：
- `Access-Control-Allow-Origin: *`
- `Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS`
- `Access-Control-Allow-Headers: Content-Type, Authorization`
- 状态：✅ 配置正确

## 客户端配置检查

### 客户端URL配置

**位置**：`mcp_client.js`

1. **默认配置**（第8行）：
   ```javascript
   mcpServerUrl: 'http://localhost:8000',
   ```

2. **从config.json加载**（第180行）：
   ```javascript
   CONFIG.mcpServerUrl = `http://${configData.mcp_server.host}:${configData.mcp_server.port}`;
   ```

3. **config.json配置**：
   ```json
   {
     "mcp_server": {
       "host": "localhost",
       "port": 8000
     }
   }
   ```

**检查结果**：✅ 配置正确

### 客户端请求方式

**位置**：`mcp_client.js` 第685行

```javascript
const response = await fetch(CONFIG.mcpServerUrl, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify(mcpRequest),
  signal: controller.signal
});
```

**问题发现**：
- 客户端直接请求 `http://localhost:8000`（根路径）
- 服务端会处理根路径的POST请求作为MCP协议请求
- 这应该是正常的行为

## 可能的问题原因

### 1. 浏览器控制台错误

**建议检查**：
- 打开浏览器开发者工具（F12）
- 查看Console标签页的错误信息
- 查看Network标签页的请求详情

### 2. 网络连接问题

**可能原因**：
- 浏览器被防火墙阻止
- 代理设置问题
- 本地网络配置问题

### 3. 客户端初始化时机

**可能原因**：
- 客户端在服务端完全启动前尝试连接
- 配置文件加载失败
- JavaScript执行错误

### 4. CORS预检请求失败

**虽然CORS配置正确，但可能**：
- 浏览器缓存了旧的CORS策略
- 预检请求处理有问题

## 诊断步骤

### 步骤1：检查浏览器控制台

1. 打开 `http://localhost:8888/mcp_client.html`
2. 按F12打开开发者工具
3. 查看Console标签页的错误信息
4. 查看Network标签页，找到失败的请求

### 步骤2：检查网络请求

在Network标签页中：
1. 查找对 `localhost:8000` 的请求
2. 检查请求状态码
3. 查看请求和响应详情
4. 检查是否有CORS错误

### 步骤3：手动测试连接

在浏览器控制台执行：
```javascript
fetch('http://localhost:8000/health')
  .then(r => r.json())
  .then(d => console.log('健康检查:', d))
  .catch(e => console.error('错误:', e));
```

### 步骤4：检查服务端日志

查看 `mcp_server.log` 文件，查找：
- 是否有客户端请求记录
- 是否有错误信息
- 请求路径和处理结果

## 服务端处理逻辑

### MCP请求处理流程

1. **接收POST请求**
   - 路径：`/`（根路径）或 `/mcp`
   - Content-Type: `application/json`

2. **路径判断**
   - `/api/llm/chat` → LLM代理
   - `/api/sessions` → 会话管理
   - `/api/files/upload` → 文件上传
   - 其他 → MCP协议请求

3. **MCP协议处理**
   - 解析JSON请求
   - 调用 `server_instance.handle_request(request)`
   - 返回JSON-RPC响应

### 当前状态

- ✅ 服务端代码逻辑正确
- ✅ 端口监听正常
- ✅ API响应正常
- ✅ CORS配置正确

## 建议的解决方案

### 方案1：检查浏览器控制台

**最重要**：查看浏览器控制台的具体错误信息，这是诊断问题的关键。

### 方案2：重启服务

如果怀疑服务状态异常：
```bash
# 停止服务
pkill -f mcp_server.py

# 启动服务
cd "/Users/kanglinlin/Documents/cursor/AI法官"
python3 server/mcp_server.py > mcp_server.log 2>&1 &
```

### 方案3：清除浏览器缓存

清除浏览器缓存和Cookie，然后重新访问。

### 方案4：检查防火墙

确保本地防火墙没有阻止8000端口。

## 总结

### 服务端状态：✅ 正常

- 进程运行正常
- 端口监听正常
- 健康检查正常
- API响应正常
- MCP协议端点正常
- CORS配置正确

### 需要进一步检查

1. **浏览器控制台错误**：这是最关键的诊断信息
2. **网络请求详情**：查看实际发送的请求和收到的响应
3. **客户端初始化流程**：检查是否有JavaScript错误

### 下一步

请提供：
1. 浏览器控制台的错误信息
2. Network标签页中失败的请求详情
3. 客户端初始化时的日志输出

这些信息将帮助精确定位问题。






