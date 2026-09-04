# LegalMind 智能体系统

基于 MCP（Model Context Protocol）协议的 LegalMind 智能体系统，支持法律文书生成、法律法规检索、类案检索和合同审查等功能。

## 系统架构

- **前端（MCP客户端）**：基于Web的MCP客户端，实现与MCP服务端和LLM的交互
- **后端（MCP服务端）**：Python实现的MCP服务端，提供资源和提示词模板
- **LLM**：DeepSeek大模型，用于智能分析和内容生成

## 功能特性

### MCP客户端功能
- ✅ 支持接收LLM思考数据和最终对话展示
- ✅ 实现MCP协议握手、能力发现、查询列表、通知变更
- ✅ 支持文件和文本输入
- ✅ 网络异常处理和提示
- ✅ 参数枚举值展示（当需要补充参数时显示可选列表）
- ✅ 工具调用批准/拒绝机制（支持自动批准配置）
- ✅ 会话管理（记录当前会话状态）
- ✅ 从配置文件读取系统提示词和LLM配置
- ✅ 思考内容和结论分离展示（使用分隔符）

### MCP服务端功能
- ✅ MCP协议握手
- ✅ 资源列表提供：
  - 法律文书模板检索
  - 法律法规检索
  - 类案检索
  - 合同审查规则检索
- ✅ 提示词模板列表提供：
  - 生成法律文书提示词指南
  - 合同审查提示词指南

## 快速开始

### 前置要求

- Python 3.7+
- 现代浏览器（Chrome、Firefox、Edge等）
- DeepSeek API Key（已配置在config.json中）

### 启动步骤

1. **启动MCP服务端**

   **Linux/macOS:**
   ```bash
   chmod +x start_server.sh
   ./start_server.sh
   ```
   
   **Windows:**
   ```cmd
   start_server.bat
   ```
   
   或者直接运行：
   ```bash
   python server/mcp_server.py
   ```

   服务端将在 `http://localhost:8000` 启动

2. **启动HTTP服务器（必需）**

   由于浏览器安全限制，直接打开HTML文件无法加载config.json。需要启动HTTP服务器：
   
   **Linux/macOS:**
   ```bash
   chmod +x start_http_server.sh
   ./start_http_server.sh
   ```
   
   **Windows:**
   ```cmd
   start_http_server.bat
   ```
   
   或者直接运行：
   ```bash
   python server/http_server.py 8888
   ```
   
   HTTP服务器将在 `http://localhost:8888` 启动

3. **打开前端页面**

   在浏览器中访问 `http://localhost:8888/index.html`
   
   或者直接访问 `http://localhost:8888/mcp_client.html`

3. **开始使用**

   - 在输入框中输入问题，例如："帮我生成民间借贷纠纷起诉状"
   - 系统会自动分析需求，如果需要参数，会显示参数选择界面
   - 选择参数后，系统会调用相应的资源并生成结果

## 配置说明

复制 `config.example.json` 为 `config.json`，并填入你的 DeepSeek API Key。`config.json` 含密钥，不会提交到仓库。

系统配置位于 `config.json` 文件中：

```json
{
  "mcp_server": {
    "host": "localhost",
    "port": 8000
  },
  "llm": {
    "api_url": "https://api.deepseek.com/v1/chat/completions",
    "api_key": "your-api-key-here",
    "model": "deepseek-chat",
    "timeout": 60000,
    "max_retries": 3,
    "temperature": 0.0,
    "max_tokens": 2048
  },
  "system_prompt": "..."
}
```

### 配置项说明

- **mcp_server**: MCP服务端配置
  - `host`: 服务端主机地址
  - `port`: 服务端端口号

- **llm**: LLM配置
  - `api_url`: DeepSeek API地址
  - `api_key`: API密钥（请替换为您的密钥）
  - `model`: 模型名称
  - `timeout`: 请求超时时间（毫秒）
  - `max_retries`: 最大重试次数
  - `temperature`: 温度参数
  - `max_tokens`: 最大token数

- **system_prompt**: 系统提示词，用于指导LLM的行为

## 使用示例

### 1. 生成法律文书

**输入：** "帮我生成民间借贷纠纷起诉状"

**流程：**
1. 系统识别需要生成法律文书
2. 提示选择模板名称（显示可选列表）
3. 用户选择"民间借贷纠纷起诉状"
4. 系统调用资源获取模板
5. 根据用户提供的具体信息生成完整文书

### 2. 检索法律法规

**输入：** "查询民法典311条"

**流程：**
1. 系统识别需要检索法律法规
2. 调用法律法规资源
3. 返回相关法规条文

### 3. 检索类案

**输入：** "查找民间借贷纠纷的相似案例"

**流程：**
1. 系统识别需要检索类案
2. 调用类案检索资源
3. 返回相似案例列表

### 4. 合同审查

**输入：** "帮我审查这份合同"（需要上传合同文件）

**流程：**
1. 系统识别需要合同审查
2. 调用合同审查规则资源
3. 根据规则审查合同条款
4. 生成审查意见和风险提示

## 技术实现

### MCP协议

系统遵循MCP（Model Context Protocol）标准协议，实现以下功能：

- **初始化握手**：客户端与服务端建立连接
- **能力发现**：客户端查询服务端提供的资源和工具
- **资源调用**：客户端调用服务端资源获取数据
- **提示词模板**：客户端获取提示词模板指导LLM生成

### 数据流

1. 用户输入 → 客户端
2. 客户端组装请求数据（包含系统提示词、资源列表、会话状态、历史对话等）
3. 客户端调用LLM API
4. LLM返回思考内容和JSON响应
5. 客户端解析响应，根据类型执行相应操作：
   - 参数不足 → 显示参数选择界面
   - 需要调用资源 → 调用MCP服务端资源
   - 生成结果 → 显示最终结果
6. 更新会话状态和历史记录

## 文件结构

```
LegalMind/
├── index.html              # 主页面
├── mcp_client.html         # MCP客户端页面
├── mcp_client.js          # MCP客户端逻辑
├── mcp_client.css         # MCP客户端样式
├── config.json            # 配置文件
├── start_server.sh        # 服务端启动脚本（Linux/macOS）
├── start_server.bat        # 服务端启动脚本（Windows）
├── server/
│   ├── mcp_server.py     # MCP服务端实现
│   └── requirements.txt   # Python依赖（当前使用标准库）
└── README.md              # 本文件
```

## 注意事项

1. **API密钥安全**：请妥善保管您的DeepSeek API密钥，不要将其提交到公共代码仓库
2. **服务端运行**：使用前请确保MCP服务端已启动
3. **网络连接**：确保能够访问DeepSeek API
4. **浏览器兼容性**：建议使用现代浏览器（Chrome 90+、Firefox 88+、Edge 90+）

## 故障排查

### 问题：无法连接到MCP服务

**解决方案：**
- 检查服务端是否已启动（运行 `python server/mcp_server.py`）
- 检查端口8000是否被占用
- 检查防火墙设置

### 问题：LLM API调用失败

**解决方案：**
- 检查config.json中的API密钥是否正确
- 检查网络连接是否正常
- 检查API配额是否充足

### 问题：参数选择界面不显示

**解决方案：**
- 检查浏览器控制台是否有错误
- 确认参数名称是否在PARAMETER_ENUMS中定义

## 开发计划

- [ ] 支持更多法律文书模板
- [ ] 支持更多法律法规检索
- [ ] 增强类案检索功能
- [ ] 支持数据库存储（替代模拟数据）
- [ ] 支持用户认证和权限管理
- [ ] 支持多语言界面

## 许可证

本项目仅供学习和研究使用。

## 联系方式

如有问题或建议，请提交Issue或联系开发团队。
