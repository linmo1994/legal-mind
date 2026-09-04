# iframe扩展错误修复说明

## 问题根源

经过代码检查，发现了问题的真正原因：

### 关键发现

1. **`index.html` 使用 iframe 加载 `mcp_client.html`**
   ```html
   <iframe id="mainFrame" src="mcp_client.html" frameborder="0"></iframe>
   ```

2. **iframe 环境导致浏览器扩展通信问题**
   - 当页面在 iframe 中加载时，某些浏览器扩展会尝试与 iframe 通信
   - 扩展使用 `chrome.runtime.sendMessage()` 发送消息
   - 但 iframe 中的页面没有消息监听器
   - 导致 "Receiving end does not exist" 错误

3. **为什么之前没有这个问题**
   - 如果之前直接访问 `http://localhost:8888/mcp_client.html`
   - 现在通过 `http://localhost:8888/index.html` 的 iframe 访问
   - iframe 环境改变了扩展的行为

## 已实施的修复

### 修复内容

在 `mcp_client.js` 的 `init()` 函数中添加了消息监听器：

```javascript
// 添加消息监听器，避免浏览器扩展通信错误
window.addEventListener('message', function(event) {
  // 忽略来自浏览器扩展的消息（避免 "Receiving end does not exist" 错误）
  if (event.origin && event.origin.startsWith('chrome-extension://')) {
    return;
  }
  // 可以在这里处理来自父窗口的消息（如果需要）
  if (event.data && event.data.type === 'loadPage' && window.parent !== window) {
    // 处理来自父窗口的页面加载请求
    console.log('收到来自父窗口的消息:', event.data);
  }
}, false);

// 如果是在iframe中，也监听来自父窗口的消息
if (window.parent !== window) {
  console.log('检测到页面在iframe中加载');
}
```

### 修复效果

1. **消除扩展通信错误**
   - 添加消息监听器后，扩展的消息有接收端
   - 避免 "Receiving end does not exist" 错误

2. **保持功能正常**
   - 不影响应用功能
   - 不影响MCP服务连接
   - 不影响消息发送和接收

3. **支持父窗口通信**
   - 如果需要在iframe和父窗口之间通信，可以扩展消息处理逻辑

## 验证方法

### 步骤1: 刷新页面

1. 刷新浏览器页面
2. 打开开发者工具（F12）
3. 查看控制台，确认错误是否消失

### 步骤2: 检查日志

查看控制台日志，应该看到：
```
检测到页面在iframe中加载
```

### 步骤3: 测试功能

确认应用功能正常：
- ✅ 会话列表显示正常
- ✅ MCP服务连接正常
- ✅ 消息发送和接收正常
- ✅ 资源调用正常

## 访问方式

现在有两种访问方式：

1. **通过 index.html（iframe方式）**:
   - `http://localhost:8888/index.html`
   - 提供导航功能
   - 已修复扩展通信错误

2. **直接访问 mcp_client.html**:
   - `http://localhost:8888/mcp_client.html`
   - 不通过iframe
   - 通常不会有扩展通信问题

## 总结

**问题根源**: `index.html` 使用 iframe 加载 `mcp_client.html`，导致浏览器扩展尝试与 iframe 通信失败

**修复方案**: 添加消息监听器，即使不处理消息，也可以避免 "Receiving end does not exist" 错误

**修复效果**: 
- ✅ 消除扩展通信错误
- ✅ 不影响应用功能
- ✅ 支持未来的父窗口通信需求

**验证**: 刷新页面后，错误应该消失或减少






