/**
 * MCP客户端实现
 * 实现MCP协议通信、LLM交互、会话管理等功能
 */

const MCP_CLIENT_VERSION = '2026.09.04-workflow';
console.log(`[MCP] mcp_client.js loaded, version=${MCP_CLIENT_VERSION}`);

// ============================================
// 立即添加消息监听器，避免浏览器扩展通信错误
// 必须在脚本开始时就添加，确保在扩展尝试通信时监听器已存在
// ============================================
(function() {
  'use strict';
  
  // 添加消息监听器，避免浏览器扩展通信错误
  // 当页面在iframe中加载时，某些扩展会尝试通信，如果没有监听器会导致错误
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
  
  // 如果是在iframe中，记录日志
  if (window.parent !== window) {
    console.log('✅ 检测到页面在iframe中加载，消息监听器已添加');
  }
  
  console.log('✅ 消息监听器已提前添加（避免浏览器扩展通信错误）');
})();

// 配置（将从config.json加载）
let CONFIG = {
  mcpServerUrl: 'http://localhost:8000',
  llmApiUrl: 'https://api.deepseek.com/v1/chat/completions',
  llmApiKey: '',
  llmModel: 'deepseek-chat',
  timeout: 60000,
  maxRetries: 3,
  systemPrompt: ''
};

// 全局变量：用于控制流式请求的取消
let currentAbortController = null;
let isGenerating = false;
let isProcessingInput = false; // 防止重复处理输入

// 提前定义 handleUserInput 函数，避免在HTML解析时出现 "is not defined" 错误
// 这个函数会在 init() 完成后被重新定义，但先定义一个占位符可以避免错误
window.handleUserInput = async function() {
  console.warn('⚠️ handleUserInput 在初始化完成前被调用，等待初始化...');
  // 如果初始化未完成，等待一下再重试
  if (!window._mcpInitialized) {
    console.log('等待初始化完成...');
    let retries = 0;
    const maxRetries = 50; // 最多等待5秒
    while (!window._mcpInitialized && retries < maxRetries) {
      await new Promise(resolve => setTimeout(resolve, 100));
      retries++;
    }
    if (window._mcpInitialized && window.handleUserInput) {
      console.log('初始化完成，重新调用 handleUserInput');
      // 重新调用正式版本的handleUserInput
      return window.handleUserInput();
    }
  }
  console.error('❌ 初始化未完成，无法处理用户输入');
  // 注意：这里不显示alert，因为正式版本的handleUserInput会处理输入检查
  // 如果初始化未完成，正式版本会正确处理
};

// 关闭本地埋点请求（避免127.0.0.1:7242连接失败刷错）
const AGENT_LOG_ENDPOINT = 'http://127.0.0.1:7242/ingest/';
const ENABLE_AGENT_LOG = false;
if (!ENABLE_AGENT_LOG && typeof window !== 'undefined' && window.fetch && !window.__agentLogDisabled) {
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : input?.url;
    if (url && url.startsWith(AGENT_LOG_ENDPOINT)) {
      return Promise.resolve({
        ok: true,
        status: 204,
        statusText: 'No Content',
        text: async () => '',
        json: async () => ({})
      });
    }
    return originalFetch(input, init);
  };
  window.__agentLogDisabled = true;
}

// 参数枚举值定义（用于参数选择）
const PARAMETER_ENUMS = {
  'template_name': [
    '民间借贷纠纷起诉状',
    '离婚协议书',
    '劳动合同',
    '房屋租赁合同',
    '买卖合同',
    '借款合同',
    '保证合同',
    '委托合同'
  ]
};

// 全局状态
let currentSession = null;
let mcpTools = []; // MCP工具列表
let mcpResources = []; // MCP资源列表
let mcpPrompts = []; // MCP提示词模板列表
let requestIdCounter = 0;

// DOM元素（延迟获取，确保DOM已加载）
let elements = {};

// 待发送的文件列表（存储在预览区域的文件）
let pendingFiles = [];

// 初始化DOM元素引用
function initElements() {
  elements = {
  chatMessages: document.getElementById('chatMessages'),
  userInput: document.getElementById('userInput'),
  sendBtn: document.getElementById('sendBtn'),
  fileInput: document.getElementById('fileInput'),
  fileUploadBtn: document.getElementById('fileUploadBtn'),
  filePreviewArea: document.getElementById('filePreviewArea'),
  filePreviewList: document.getElementById('filePreviewList'),
  filePreviewContainer: document.getElementById('filePreviewContainer'),
  filePreviewListInline: document.getElementById('filePreviewListInline'),
  clearFilesBtn: document.getElementById('clearFilesBtn'),
  connectionStatus: document.getElementById('connectionStatus'),
  statusText: document.getElementById('statusText'),
  newSessionBtn: document.getElementById('newSessionBtn'),
  clearHistoryBtn: document.getElementById('clearHistoryBtn'),
  sessionList: document.getElementById('sessionList'),
  parameterModal: document.getElementById('parameterModal'),
  parameterOptions: document.getElementById('parameterOptions'),
  confirmParameterBtn: document.getElementById('confirmParameterBtn'),
  cancelParameterBtn: document.getElementById('cancelParameterBtn'),
  toolApprovalModal: document.getElementById('toolApprovalModal'),
  toolApprovalInfo: document.getElementById('toolApprovalInfo'),
  approveToolBtn: document.getElementById('approveToolBtn'),
  rejectToolBtn: document.getElementById('rejectToolBtn')
};
  
  // 验证关键元素是否存在
  console.log('验证DOM元素...');
  console.log('sendBtn:', elements.sendBtn);
  console.log('userInput:', elements.userInput);
  console.log('chatMessages:', elements.chatMessages);
  console.log('fileInput:', elements.fileInput);
  console.log('fileUploadBtn:', elements.fileUploadBtn);
  console.log('sessionList:', elements.sessionList);
  console.log('connectionStatus:', elements.connectionStatus);
  console.log('statusText:', elements.statusText);
  
  if (!elements.sendBtn) {
    console.error('❌ 错误：找不到sendBtn元素');
    console.error('尝试查找所有按钮:', document.querySelectorAll('button'));
    return false;
  }
  if (!elements.userInput) {
    console.error('❌ 错误：找不到userInput元素');
    return false;
  }
  if (!elements.chatMessages) {
    console.error('❌ 错误：找不到chatMessages元素');
    return false;
  }
  if (!elements.fileInput) {
    console.warn('⚠️ 警告：找不到fileInput元素，文件上传功能可能不可用');
  }
  if (!elements.sessionList) {
    console.error('❌ 错误：找不到sessionList元素，会话列表将无法显示');
  }
  if (!elements.connectionStatus) {
    console.error('❌ 错误：找不到connectionStatus元素，连接状态将无法显示');
  }
  if (!elements.statusText) {
    console.error('❌ 错误：找不到statusText元素，状态文本将无法显示');
  }
  if (!elements.fileUploadBtn) {
    console.warn('⚠️ 警告：找不到fileUploadBtn元素，文件上传按钮可能不可用');
  }
  
  console.log('✅ DOM元素初始化成功');
  return true;
}

/** 多轮对话页左上角低调「首页」入口：在 iframe 内则父窗口切回 home，否则直接跳转 */
function setupHomeBackTab() {
  const tab = document.getElementById('homeBackTab');
  if (!tab) return;
  tab.addEventListener('click', function () {
    const url = 'home.html';
    if (window.parent !== window && typeof window.parent.loadPage === 'function') {
      window.parent.loadPage(url);
    } else {
      window.location.href = url;
    }
  });
}

// 配置缓存（减少重复请求 config.json）
const CONFIG_CACHE_KEY = 'config_cache_v1';
let configLoadPromise = null;

function applyConfig(configData) {
  if (!configData) return;
  CONFIG.mcpServerUrl = `http://${configData.mcp_server.host}:${configData.mcp_server.port}`;
  CONFIG.llmApiUrl = configData.llm.api_url;
  CONFIG.llmApiKey = configData.llm.api_key;
  CONFIG.llmModel = configData.llm.model;
  CONFIG.timeout = configData.llm.timeout;
  CONFIG.maxRetries = configData.llm.max_retries;
  CONFIG.systemPrompt = configData.system_prompt;
}

function updateMcpServerUrl(url) {
  if (!url || typeof url !== 'string') {
    return;
  }
  CONFIG.mcpServerUrl = url;
  sessionStorage.setItem('mcp_server_url', url);
  console.log('✅ MCP服务端URL已更新:', url);
}

async function loadConfigCached() {
  if (configLoadPromise) {
    return configLoadPromise;
  }
  if (window.__configLoadPromise) {
    return window.__configLoadPromise;
  }
  if (window.__configCacheData) {
    console.log('✅ 使用全局配置缓存（window.__configCacheData）');
    applyConfig(window.__configCacheData);
    return window.__configCacheData;
  }
  const cached = sessionStorage.getItem(CONFIG_CACHE_KEY);
  if (cached) {
    try {
      const parsed = JSON.parse(cached);
      console.log('✅ 使用sessionStorage配置缓存');
      window.__configCacheData = parsed;
      applyConfig(parsed);
      return parsed;
    } catch (e) {
      sessionStorage.removeItem(CONFIG_CACHE_KEY);
    }
  }
  configLoadPromise = (async () => {
    console.log('⚠️ 未命中配置缓存，开始加载config.json');
    const configData = await loadConfig();
    window.__configCacheData = configData;
    sessionStorage.setItem(CONFIG_CACHE_KEY, JSON.stringify(configData));
    return configData;
  })();
  window.__configLoadPromise = configLoadPromise;
  return configLoadPromise;
}

window.loadConfigCached = loadConfigCached;

// 加载配置
async function loadConfig() {
  try {
    console.log('=== 步骤1: 加载配置文件 ===');
    console.log('当前URL:', window.location.href);
    console.log('协议:', window.location.protocol);
    
    // 检测是否使用file://协议
    if (window.location.protocol === 'file:') {
      const errorMsg = `检测到使用file://协议打开页面，这会导致CORS错误。\n\n请使用HTTP服务器访问：\n1. 运行命令: python server/http_server.py 8888\n2. 在浏览器访问: http://localhost:8888/index.html\n\n或者直接访问: http://localhost:8888/mcp_client.html`;
      console.error('❌', errorMsg);
      alert(errorMsg);
      throw new Error('请使用HTTP服务器访问，不要直接打开HTML文件');
    }
    
    console.log('尝试加载config.json...');
    
    // 尝试多个可能的路径
    let configUrl = 'config.json';
    let response = null;
    let lastError = null;
    
    // 尝试1: 相对路径
    try {
      response = await fetch(configUrl);
      if (response.ok) {
        console.log('✅ 从相对路径加载配置成功');
      }
    } catch (e) {
      lastError = e;
      console.warn('相对路径加载失败，尝试其他路径...');
    }
    
    // 尝试2: 从根路径
    if (!response || !response.ok) {
      try {
        configUrl = '/config.json';
        response = await fetch(configUrl);
        if (response.ok) {
          console.log('✅ 从根路径加载配置成功');
        }
      } catch (e) {
        lastError = e;
        console.warn('根路径加载失败...');
      }
    }
    
    // 尝试3: 从当前目录
    if (!response || !response.ok) {
      try {
        const baseUrl = window.location.href.substring(0, window.location.href.lastIndexOf('/') + 1);
        configUrl = baseUrl + 'config.json';
        response = await fetch(configUrl);
        if (response.ok) {
          console.log('✅ 从当前目录加载配置成功');
        }
      } catch (e) {
        lastError = e;
      }
    }
    
    if (!response || !response.ok) {
      const errorMsg = lastError ? lastError.message : `HTTP ${response?.status || 'unknown'}`;
      const helpMsg = `\n\n解决方案：\n1. 运行: python server/http_server.py 8888\n2. 访问: http://localhost:8888/index.html`;
      throw new Error(`加载配置失败: ${errorMsg}${helpMsg}`);
    }
    
    const configData = await response.json();
    
    console.log('配置文件内容:', {
      mcp_server: configData.mcp_server,
      llm_api_url: configData.llm?.api_url,
      llm_model: configData.llm?.model,
      has_api_key: !!configData.llm?.api_key,
      api_key_length: configData.llm?.api_key?.length || 0
    });
    
    // 更新配置
    applyConfig(configData);
    
    console.log('✅ 配置加载成功');
    console.log('MCP服务端URL:', CONFIG.mcpServerUrl);
    console.log('LLM API URL:', CONFIG.llmApiUrl);
    console.log('LLM Model:', CONFIG.llmModel);
    console.log('System Prompt长度:', CONFIG.systemPrompt?.length || 0);
    
    // 验证配置完整性
    if (!CONFIG.llmApiKey) {
      throw new Error('LLM API Key未配置');
    }
    if (!CONFIG.mcpServerUrl) {
      throw new Error('MCP服务端URL未配置');
    }
    
  } catch (error) {
    console.error('❌ 加载配置失败:', error);
    showError('加载配置文件失败: ' + error.message);
    updateStatus('配置加载失败', 'disconnected');
    throw error;
  }
}

// 初始化
// 清空临时变量（页面刷新时调用）
// 注意：如果是从首页跳转过来（带文件/文本），不要在handleHomePageInput处理前清掉sessionStorage里的传递数据
function clearTemporaryData(options = {}) {
  const { preserveHomeTransfer = false } = options;
  console.log('🔄 清空多轮对话页临时变量数据', { preserveHomeTransfer });
  
  // 清空全局变量
  pendingFiles = [];
  if (window._pendingInputText) {
    delete window._pendingInputText;
  }
  if (window.uploadedFileIds) {
    window.uploadedFileIds = [];
  }
  
  // 重置状态标志（这些会在初始化时重新设置）
  isGenerating = false;
  isProcessingInput = false;
  if (currentAbortController) {
    currentAbortController.abort();
    currentAbortController = null;
  }
  
  // 清空 sessionStorage 中的临时数据（但保留 MCP 初始化状态）
  // 关键：从首页跳转过来时，uploadedFileIds/createdSessionId/pendingFiles 需要先给 handleHomePageInput 消费
  try {
    if (!preserveHomeTransfer) {
      sessionStorage.removeItem('uploadedFileIds');
      sessionStorage.removeItem('pendingFiles');
      sessionStorage.removeItem('createdSessionId');
      console.log('✅ 已清空 sessionStorage 中的临时数据（保留 MCP 初始化状态）');
    } else {
      console.log('⏭️ 检测到首页跳转，暂不清除 uploadedFileIds/pendingFiles/createdSessionId（等待 handleHomePageInput 消费）');
    }
  } catch (e) {
    console.warn('清空 sessionStorage 失败:', e);
  }
}

async function init() {
  try {
  // 页面刷新时清空临时变量
  // 如果检测到从首页跳转（可能携带文件/文本），先保留传递数据，避免被提前清空
  let preserveHomeTransfer = false;
  try {
    const urlParams = new URLSearchParams(window.location.search);
    const hasInputParam = urlParams.has('input');
    const hasUploadedFileIds = sessionStorage.getItem('uploadedFileIds') !== null;
    const hasPendingFiles = sessionStorage.getItem('pendingFiles') !== null;
    const hasCreatedSessionId = sessionStorage.getItem('createdSessionId') !== null;
    preserveHomeTransfer = hasInputParam || hasUploadedFileIds || hasPendingFiles || hasCreatedSessionId;
  } catch (e) {
    // 忽略检测失败，按默认行为清理
  }
  clearTemporaryData({ preserveHomeTransfer });
  
  // 设置标记：表示用户在多轮对话页
  // 当用户返回首页时，首页会检测到这个标记并清空输入内容
  try {
    sessionStorage.setItem('from_multi_turn_page', 'true');
    console.log('✅ 已设置多轮对话页标记');
  } catch (e) {
    console.warn('设置多轮对话页标记失败:', e);
  }
    
    console.log('========================================');
    console.log('=== 开始客户端初始化 ===');
    console.log('========================================');
    
    // 注意：消息监听器已在文件开头提前添加（使用IIFE）
    // 这里不再重复添加，避免重复监听
    if (window.parent !== window) {
      console.log('✅ 确认页面在iframe中加载，消息监听器已存在');
    }
    
    // 初始化DOM元素引用
    console.log('=== 步骤0: 初始化DOM元素 ===');
    if (!initElements()) {
      throw new Error('DOM元素初始化失败，请检查HTML结构');
    }
    console.log('✅ DOM元素初始化成功');
    setupHomeBackTab();
    
    // 加载配置（使用缓存）
    await loadConfigCached();

    if (typeof LegalMindAuth !== 'undefined') {
      if (!LegalMindAuth.getToken()) {
        LegalMindAuth.requireLogin('login.html?next=mcp_client.html');
        return;
      }
      try {
        await loadActiveCaseOptions();
      } catch (e) {
        console.warn('加载案件列表失败', e);
      }
    }
    
  // 不在这里创建会话，等用户第一次发送消息时再创建
    console.log('=== 跳过创建会话（等用户发送消息时再创建） ===');
    // 初始化一个临时的会话对象，但不保存到服务端
    currentSession = {
      sessionId: null, // 标记为未创建
      status: 'active',
      currentIntent: null,
      collectedParameters: {},
      missingParameters: [],
      stage: 'idle',
      contextCache: {},
      conversationHistory: []
    };
    console.log('✅ 临时会话对象已初始化（未保存到服务端）');
  
    // 初始化MCP连接（包含连接测试）
  await initializeMCP();
  
  // 绑定事件
    console.log('=== 步骤4: 绑定事件 ===');
  bindEvents();
    console.log('✅ 事件绑定完成');
  
  // 加载会话列表
    console.log('=== 步骤5: 加载会话列表 ===');
    try {
    await loadSessionList();
    console.log('✅ 会话列表加载完成');
    } catch (error) {
      console.error('❌ 会话列表加载失败:', error);
      // 不抛出错误，允许初始化继续
      // 会话列表加载失败不应该阻止整个应用初始化
      if (elements.sessionList) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'session-error';
        errorDiv.textContent = '加载失败，请刷新重试';
        errorDiv.style.cssText = 'text-align: center; color: #f44336; padding: 20px; font-size: 0.9rem; cursor: pointer;';
        errorDiv.onclick = async () => await loadSessionList();
        elements.sessionList.innerHTML = '';
        elements.sessionList.appendChild(errorDiv);
      }
    }
    
    console.log('========================================');
    console.log('✅ 客户端初始化完成！');
    console.log('========================================');
    
    // 标记初始化完成
    window._mcpInitialized = true;
    
    // 只在首次初始化时显示成功消息（检查是否已有消息或已显示过）
    if (elements.chatMessages) {
      const hasMessages = elements.chatMessages.children.length > 0;
      const hasShownInitMessage = localStorage.getItem('mcp_init_message_shown') === 'true';
      
      // 如果聊天区域为空且未显示过初始化消息，则显示
      if (!hasMessages && !hasShownInitMessage) {
        addMessage('assistant', '✅ 系统初始化成功！\n- MCP服务端已连接\n- LLM API已就绪\n\n您可以开始提问了。', 'normal');
        localStorage.setItem('mcp_init_message_shown', 'true');
      }
    }
    
    // 检查是否从首页跳转过来，如果有输入内容则自动填充并发送
    console.log('=== 步骤6: 检查首页传递的内容 ===');
    await handleHomePageInput();
    
  } catch (error) {
    console.error('========================================');
    console.error('❌ 初始化失败');
    console.error('========================================');
    console.error('错误详情:', error);
    console.error('错误堆栈:', error.stack);
    
    if (elements.statusText) {
      showError('系统初始化失败: ' + error.message + '\n\n请检查：\n1. MCP服务端是否启动\n2. 配置文件是否正确\n3. 网络连接是否正常');
    } else {
      alert('系统初始化失败: ' + error.message);
    }
  }
}

// 创建新会话（使用服务端API）
async function createNewSession() {
  const sessionId = `sess_${Date.now()}`;
  
  // 先创建本地会话对象，确保即使服务端失败也有会话可用
  const fallbackSession = {
    sessionId: sessionId,
    status: 'active',
    currentIntent: null,
    collectedParameters: {},
    missingParameters: [],
    stage: 'idle',
    contextCache: {},
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    conversationHistory: []
  };
  
  try {
    const response = await fetch(`${CONFIG.mcpServerUrl}/api/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        session_id: sessionId,
        title: ''
      })
    });
    
    if (!response.ok) {
      // ⚠️ 不抛出异常，直接降级到本地存储
      console.warn(`服务端创建会话失败 (HTTP ${response.status})，使用本地会话`);
      currentSession = fallbackSession;
      updateStatus('就绪', 'connected');
      return currentSession;
    }
    
    try {
    const session = await response.json();
  currentSession = {
      sessionId: session.session_id,
      status: session.status || 'active',
      currentIntent: session.current_intent || null,
      collectedParameters: session.collected_parameters || {},
      missingParameters: session.missing_parameters || [],
      stage: session.stage || 'idle',
      contextCache: session.context_cache || {},
      createdAt: session.created_at,
      updatedAt: session.updated_at,
      conversationHistory: session.conversation_history || [],
      title: session.title || '',
      lastUserInput: session.last_user_input || ''
    };
    updateStatus('就绪', 'connected');
    return currentSession;
    } catch (parseError) {
      // JSON解析失败，使用降级方案
      console.warn('解析服务端响应失败，使用本地会话:', parseError);
      currentSession = fallbackSession;
      updateStatus('就绪', 'connected');
      return currentSession;
    }
  } catch (error) {
    // 网络错误或其他异常，使用降级方案
    console.error('创建会话失败，使用本地会话:', error);
    currentSession = fallbackSession;
  updateStatus('就绪', 'connected');
    return currentSession;
  }
}

// 测试MCP服务端连接
async function testMCPConnection(retries = 5, delayMs = 500) {
  console.log('=== 测试MCP服务端连接 ===');
  let lastError = null;
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const primaryHealthUrl = `${CONFIG.mcpServerUrl}/health`;
      const healthUrls = [primaryHealthUrl];

      try {
        const parsedUrl = new URL(primaryHealthUrl);
        if (parsedUrl.hostname === 'localhost') {
          const fallbackUrl = `${parsedUrl.protocol}//127.0.0.1${parsedUrl.port ? `:${parsedUrl.port}` : ''}/health`;
          healthUrls.push(fallbackUrl);
        }
      } catch (urlError) {
        console.warn('⚠️ 健康检查URL解析失败:', urlError);
      }

      let lastHealthError = null;
      for (const healthUrl of healthUrls) {
        window.__lastMcpHealthCheckUrl = healthUrl;
        try {
          const controller = new AbortController();
          const timeoutMs = 3000;
          const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
          const startTime = performance.now();
          const healthResponse = await fetch(healthUrl, { signal: controller.signal });
          const durationMs = Math.round(performance.now() - startTime);
          clearTimeout(timeoutId);
          console.log('🔎 MCP健康检查响应耗时(ms):', durationMs, 'URL:', healthUrl);
          if (!healthResponse.ok) {
            throw new Error(`健康检查失败: HTTP ${healthResponse.status}`);
          }
          const healthData = await healthResponse.json();
          console.log('✅ MCP服务端健康检查通过:', healthData);
          if (healthUrl !== primaryHealthUrl) {
            updateMcpServerUrl(healthUrl.replace(/\/health$/, ''));
          }
          return true;
        } catch (healthError) {
          lastHealthError = healthError;
          window.__lastMcpHealthError = healthError?.message || String(healthError);
          console.warn('⚠️ MCP健康检查失败:', healthUrl, window.__lastMcpHealthError);
          console.warn('环境信息:', {
            location: window.location.href,
            protocol: window.location.protocol,
            mcpServerUrl: CONFIG.mcpServerUrl
          });
        }
      }
      throw lastHealthError || new Error('健康检查失败');
    } catch (error) {
      lastError = error;
      window.__lastMcpHealthError = error?.message || String(error);
      console.warn(`⚠️ MCP服务端连接测试失败（第${attempt}/${retries}次）:`, error.message);
      if (attempt < retries) {
        await new Promise(resolve => setTimeout(resolve, delayMs));
      }
    }
  }
  console.error('❌ MCP服务端连接测试失败，已耗尽重试次数:', lastError);
  return false;
}

// 测试LLM API连接
async function testLLMConnection() {
  console.log('=== 测试LLM API连接 ===');
  try {
    // 检查配置
    if (!CONFIG.mcpServerUrl) {
      throw new Error('MCP服务端URL未配置');
    }
    if (!CONFIG.llmModel) {
      throw new Error('LLM模型未配置');
    }
    
    const proxyUrl = `${CONFIG.mcpServerUrl}/api/llm/chat`;
    console.log('测试URL:', proxyUrl);
    console.log('使用模型:', CONFIG.llmModel);
    
    const requestBody = {
      model: CONFIG.llmModel,
      messages: [{ role: 'user', content: '测试连接，请回复"连接成功"' }],
      max_tokens: 10
    };
    
    console.log('发送测试请求...');
    const testResponse = await fetch(proxyUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(requestBody)
    });
    
    console.log('LLM测试响应状态:', testResponse.status, testResponse.statusText);
    
    if (!testResponse.ok) {
      const errorData = await testResponse.json().catch(() => ({}));
      console.error('响应错误数据:', errorData);
      
      if (testResponse.status === 500 && errorData.error) {
        // 检查是否是API Key问题
        if (errorData.error.message && errorData.error.message.includes('Key')) {
          throw new Error('API Key配置错误或无效');
        }
      }
      
      throw new Error(`LLM API测试失败: HTTP ${testResponse.status} - ${JSON.stringify(errorData)}`);
    }
    
    const testData = await testResponse.json();
    console.log('响应数据结构:', {
      hasChoices: !!testData.choices,
      choicesCount: testData.choices?.length || 0
    });
    
    if (testData.choices && testData.choices[0]) {
      const responseContent = testData.choices[0].message.content;
      console.log('✅ LLM API连接测试成功');
      console.log('测试响应内容:', responseContent);
      console.log('完整响应:', JSON.stringify(testData, null, 2));
      return true;
    } else {
      console.error('响应格式错误，完整响应:', JSON.stringify(testData, null, 2));
      throw new Error('LLM API响应格式错误：缺少choices或message');
    }
  } catch (error) {
    console.error('❌ LLM API连接测试失败');
    console.error('错误类型:', error.name);
    console.error('错误消息:', error.message);
    console.error('错误堆栈:', error.stack);
    return false;
  }
}

// 初始化MCP连接
async function initializeMCP() {
  try {
    // 检查sessionStorage中是否有已初始化的MCP状态（从首页传递过来）
    const mcpInitialized = sessionStorage.getItem('mcp_initialized');
    const mcpServerUrl = sessionStorage.getItem('mcp_server_url');
    const mcpInitTimestamp = sessionStorage.getItem('mcp_init_timestamp');
    
    // 如果MCP已在首页初始化，且时间戳在5分钟内（避免过期状态），则跳过重复初始化
    if (mcpInitialized === 'true' && mcpServerUrl && mcpInitTimestamp) {
      const initTime = parseInt(mcpInitTimestamp);
      const now = Date.now();
      const timeDiff = now - initTime;
      const fiveMinutes = 5 * 60 * 1000; // 5分钟
      
      if (timeDiff < fiveMinutes && mcpServerUrl === CONFIG.mcpServerUrl) {
        console.log('=== 步骤2: 检测到MCP已在首页初始化，跳过重复初始化和能力发现 ===');
        console.log('MCP服务端URL:', CONFIG.mcpServerUrl);
        console.log('初始化时间:', new Date(initTime).toLocaleString());
        console.log('时间差:', Math.round(timeDiff / 1000), '秒');
        
        // 从sessionStorage读取能力统计
        const resourcesCount = parseInt(sessionStorage.getItem('mcp_resources_count') || '0');
        const toolsCount = parseInt(sessionStorage.getItem('mcp_tools_count') || '0');
        const promptsCount = parseInt(sessionStorage.getItem('mcp_prompts_count') || '0');
        
        console.log('✅ 使用首页已初始化的MCP连接，尝试从sessionStorage恢复能力列表');
        console.log(`能力统计（来自首页）: ${resourcesCount}个资源, ${toolsCount}个工具, ${promptsCount}个提示词模板`);
        
        // 尝试从sessionStorage恢复完整的能力列表
        let needRediscover = false;
        try {
          const savedResources = sessionStorage.getItem('mcp_resources');
          const savedTools = sessionStorage.getItem('mcp_tools');
          const savedPrompts = sessionStorage.getItem('mcp_prompts');
          
          if (savedResources) {
            mcpResources = JSON.parse(savedResources);
            console.log('✅ 从sessionStorage恢复资源列表:', mcpResources.length, '个');
          } else {
            console.warn('⚠️ sessionStorage中没有资源列表，需要重新发现');
            mcpResources = [];
            needRediscover = true;
          }
          
          if (savedTools) {
            mcpTools = JSON.parse(savedTools);
            console.log('✅ 从sessionStorage恢复工具列表:', mcpTools.length, '个');
          } else {
            console.warn('⚠️ sessionStorage中没有工具列表，需要重新发现');
            mcpTools = [];
            needRediscover = true;
          }
          
          if (savedPrompts) {
            mcpPrompts = JSON.parse(savedPrompts);
            console.log('✅ 从sessionStorage恢复提示词模板列表:', mcpPrompts.length, '个');
          } else {
            console.warn('⚠️ sessionStorage中没有提示词模板列表，需要重新发现');
            mcpPrompts = [];
            needRediscover = true;
          }
        } catch (error) {
          console.error('❌ 从sessionStorage恢复能力列表失败:', error);
          mcpResources = [];
          mcpTools = [];
          mcpPrompts = [];
          needRediscover = true;
        }
        
        // 如果能力列表已完整恢复，跳过能力发现请求
        if (!needRediscover) {
          console.log('✅ 所有能力列表已从sessionStorage恢复，跳过能力发现请求');
          console.log('   - 跳过了 resources/list 请求');
          console.log('   - 跳过了 tools/list 请求');
          console.log('   - 跳过了 prompts/list 请求');
          
          // 跳过LLM连接测试（首页已经测试过了，不需要重复测试）
          console.log('✅ 跳过LLM连接测试（使用首页已验证的连接）');
          updateStatus('MCP服务已连接', 'connected');
          
          console.log('========================================');
          console.log('✅ MCP连接初始化完成（完全复用首页已初始化的连接）');
          console.log('   - 跳过了 initialize 请求');
          console.log('   - 跳过了 initialized 通知');
          console.log('   - 跳过了 resources/list 请求');
          console.log('   - 跳过了 tools/list 请求');
          console.log('   - 跳过了 prompts/list 请求');
          console.log('   - 跳过了 LLM 连接测试');
          console.log('   - 能力列表已从sessionStorage恢复');
          console.log('========================================');
          
          // 重要：设置初始化完成标志，让handleHomePageInput知道可以继续了
          window._mcpInitialized = true;
          console.log('✅ 已设置 window._mcpInitialized = true');
          
          return; // 提前返回，跳过下面的完整初始化流程
        } else {
          console.log('⚠️ 检测到能力列表不完整，需要重新发现能力');
          // 不提前返回，继续执行完整的能力发现流程
        }
      } else {
        console.log('⚠️ MCP初始化状态已过期或URL不匹配，重新初始化');
        // 清除过期状态和完整能力列表
        sessionStorage.removeItem('mcp_initialized');
        sessionStorage.removeItem('mcp_server_url');
        sessionStorage.removeItem('mcp_init_timestamp');
        sessionStorage.removeItem('mcp_resources_count');
        sessionStorage.removeItem('mcp_tools_count');
        sessionStorage.removeItem('mcp_prompts_count');
        sessionStorage.removeItem('mcp_resources');
        sessionStorage.removeItem('mcp_tools');
        sessionStorage.removeItem('mcp_prompts');
      }
    }
    
    // 如果没有已初始化的状态，执行完整的初始化流程
    updateStatus('正在连接MCP服务...', 'connecting');
    console.log('=== 步骤2: 初始化MCP连接 ===');
    console.log('MCP服务端URL:', CONFIG.mcpServerUrl);
    
    // 先测试连接
    const mcpConnected = await testMCPConnection();
    if (!mcpConnected) {
      const lastHealthUrl = window.__lastMcpHealthCheckUrl || `${CONFIG.mcpServerUrl}/health`;
      const lastHealthError = window.__lastMcpHealthError || '未知错误';
      throw new Error(`MCP服务端连接测试失败: ${lastHealthError} (${lastHealthUrl})`);
    }
    
    // 发送初始化请求
    console.log('发送MCP初始化请求...');
    const initResponse = await sendMCPRequest({
      method: 'initialize',
      params: {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: {
          name: 'ai-judge-client',
          version: '1.0.0'
        }
      }
    });
    
    console.log('MCP初始化响应:', initResponse);
    
    if (initResponse.error) {
      throw new Error(initResponse.error.message);
    }
    
    if (!initResponse.result) {
      throw new Error('MCP初始化响应格式错误');
    }
    
    console.log('✅ MCP协议初始化成功');
    console.log('协议版本:', initResponse.result.protocolVersion);
    
    // 详细显示服务端能力声明
    const capabilities = initResponse.result.capabilities || {};
    console.log('========================================');
    console.log('📋 服务端能力声明 (Capabilities):');
    console.log('========================================');
    console.log('完整能力对象:', JSON.stringify(capabilities, null, 2));
    
    // 逐个分析每个能力
    console.log('\n📊 能力详细分析:');
    if (capabilities.resources !== undefined) {
      console.log(`  ✅ Resources: ${capabilities.resources ? '支持' : '不支持'}`);
      if (capabilities.resources) {
        console.log('     - 可以调用 resources/list');
        console.log('     - 可以调用 resources/read');
      }
    } else {
      console.log('  ⚠️  Resources: 未声明');
    }
    
    if (capabilities.prompts !== undefined) {
      console.log(`  ✅ Prompts: ${capabilities.prompts ? '支持' : '不支持'}`);
      if (capabilities.prompts) {
        console.log('     - 可以调用 prompts/list');
        console.log('     - 可以调用 prompts/get');
      }
    } else {
      console.log('  ⚠️  Prompts: 未声明');
    }
    
    if (capabilities.tools !== undefined) {
      console.log(`  ✅ Tools: ${capabilities.tools ? '支持' : '不支持'}`);
      if (capabilities.tools) {
        console.log('     - 可以调用 tools/list');
        console.log('     - 可以调用 tools/call');
      } else {
        console.log('     - 服务端不支持工具调用（符合需求：暂无工具）');
      }
    } else {
      console.log('  ⚠️  Tools: 未声明');
    }
    
    // 其他能力
    const otherCaps = Object.keys(capabilities).filter(k => !['resources', 'prompts', 'tools'].includes(k));
    if (otherCaps.length > 0) {
      console.log('\n📦 其他能力:');
      otherCaps.forEach(key => {
        console.log(`  - ${key}: ${capabilities[key]}`);
      });
    }
    
    // 服务端信息
    if (initResponse.result.serverInfo) {
      console.log('\n📝 服务端信息:');
      console.log(`  名称: ${initResponse.result.serverInfo.name || 'N/A'}`);
      console.log(`  版本: ${initResponse.result.serverInfo.version || 'N/A'}`);
    }
    
    console.log('========================================');
    
    // 发送初始化通知（可能返回null，这是正常的）
    try {
      const notifyResponse = await sendMCPRequest({
      method: 'notifications/initialized'
    });
      // 通知方法可能返回null或空响应，这是正常的
      if (notifyResponse === null || notifyResponse === undefined) {
        console.log('✅ MCP初始化通知已发送（服务端返回空响应，正常）');
      } else {
        console.log('✅ MCP初始化通知已发送，响应:', notifyResponse);
      }
    } catch (error) {
      // 通知失败不应该阻止初始化流程
      console.warn('⚠️ 初始化通知发送失败（不影响功能）:', error.message);
    }
    
    // 获取资源列表
    console.log('获取资源列表...');
    const resourcesResponse = await sendMCPRequest({
      method: 'resources/list'
    });
    
    console.log('资源列表响应:', resourcesResponse);
    console.log('响应类型:', typeof resourcesResponse);
    console.log('是否有result:', !!resourcesResponse.result);
    console.log('result内容:', resourcesResponse.result);
    
    if (resourcesResponse.error) {
      console.error('❌ 获取资源列表失败:', resourcesResponse.error);
      throw new Error(`获取资源列表失败: ${resourcesResponse.error.message}`);
    }
    
    if (resourcesResponse.result) {
      mcpResources = resourcesResponse.result.resources || [];
      console.log('✅ 已加载资源数量:', mcpResources.length);
      
      if (mcpResources.length === 0) {
        console.warn('⚠️ 警告：资源列表为空！');
        console.warn('服务端返回的result:', resourcesResponse.result);
      } else {
        mcpResources.forEach((r, i) => {
          console.log(`  资源${i+1}: ${r.uri} - ${r.name}`);
        });
      }
    } else {
      console.error('❌ 资源列表响应格式错误');
      console.error('完整响应:', JSON.stringify(resourcesResponse, null, 2));
      throw new Error('资源列表响应格式错误：缺少result字段');
    }
    
    // 获取工具列表（虽然当前为空，但也要获取）
    console.log('获取工具列表...');
    try {
      const toolsResponse = await sendMCPRequest({
        method: 'tools/list'
      });
      
      console.log('工具列表响应:', toolsResponse);
      
      if (toolsResponse.result) {
        mcpTools = toolsResponse.result.tools || [];
        console.log('✅ 已加载工具数量:', mcpTools.length);
        if (mcpTools.length > 0) {
          mcpTools.forEach((t, i) => {
            console.log(`  工具${i+1}: ${t.name || t.uri || 'unknown'}`);
          });
        } else {
          console.log('  工具列表为空（符合需求：暂无工具）');
        }
      }
    } catch (error) {
      console.warn('⚠️ 获取工具列表失败（可能服务端未实现）:', error.message);
      mcpTools = [];
    }
    
    // 获取提示词模板列表
    console.log('获取提示词模板列表...');
    const promptsResponse = await sendMCPRequest({
      method: 'prompts/list'
    });
    
    console.log('提示词模板响应:', promptsResponse);
    
    if (promptsResponse.result) {
      mcpPrompts = promptsResponse.result.prompts || [];
      console.log('✅ 已加载提示词模板数量:', mcpPrompts.length);
      mcpPrompts.forEach((p, i) => {
        console.log(`  模板${i+1}: ${p.name} - ${p.description}`);
      });
    } else {
      console.warn('⚠️ 未获取到提示词模板列表');
    }
    
    // 测试LLM连接
    console.log('=== 步骤3: 测试LLM API连接 ===');
    const llmConnected = await testLLMConnection();
    if (!llmConnected) {
      console.error('❌ LLM API连接测试失败');
      console.error('请检查：');
      console.error('1. MCP服务端是否正常运行');
      console.error('2. config.json中的API Key是否正确');
      console.error('3. 网络连接是否正常');
      updateStatus('MCP已连接，LLM测试失败', 'disconnected');
      
      // 显示错误提示
      if (elements.chatMessages) {
        addMessage('assistant', 
          '⚠️ LLM API连接测试失败\n\n' +
          '可能的原因：\n' +
          '1. API Key配置错误\n' +
          '2. 网络连接问题\n' +
          '3. DeepSeek API服务异常\n\n' +
          '请检查配置和网络连接。',
          'error'
        );
      }
    } else {
      console.log('✅ LLM API连接测试成功，可以使用');
    updateStatus('MCP服务已连接', 'connected');
    }
    
    // 保存MCP初始化状态和完整能力列表到sessionStorage
    try {
      sessionStorage.setItem('mcp_initialized', 'true');
      sessionStorage.setItem('mcp_server_url', CONFIG.mcpServerUrl);
      sessionStorage.setItem('mcp_resources_count', mcpResources.length.toString());
      sessionStorage.setItem('mcp_tools_count', mcpTools.length.toString());
      sessionStorage.setItem('mcp_prompts_count', mcpPrompts.length.toString());
      sessionStorage.setItem('mcp_init_timestamp', Date.now().toString());
      
      // 保存完整的能力列表（不仅仅是数量）
      sessionStorage.setItem('mcp_resources', JSON.stringify(mcpResources));
      sessionStorage.setItem('mcp_tools', JSON.stringify(mcpTools));
      sessionStorage.setItem('mcp_prompts', JSON.stringify(mcpPrompts));
      
      console.log('✅ MCP状态和完整能力列表已保存到sessionStorage');
      console.log(`   - 资源: ${mcpResources.length}个`);
      console.log(`   - 工具: ${mcpTools.length}个`);
      console.log(`   - 提示词模板: ${mcpPrompts.length}个`);
    } catch (error) {
      console.warn('⚠️ 保存MCP状态到sessionStorage失败:', error.message);
    }
    
    console.log('✅ MCP连接初始化完成');
  } catch (error) {
    console.error('❌ MCP初始化失败:', error);
    console.error('错误堆栈:', error.stack);
    let errorMessage = error.message;
    
    if (errorMessage.includes('无法连接') || errorMessage.includes('Failed to fetch')) {
      errorMessage = '无法连接到MCP服务，请确保服务已启动（运行 python server/mcp_server.py）';
    }
    
    updateStatus('MCP连接失败', 'disconnected');
    showError('MCP服务连接失败: ' + errorMessage);
    throw error; // 重新抛出错误，让调用者知道初始化失败
  }
}

// 发送MCP请求
async function sendMCPRequest(request, retries = 0) {
  const requestId = ++requestIdCounter;
  const mcpRequest = {
    jsonrpc: '2.0',
    id: requestId,
    ...request
  };
  
  console.log('=== MCP请求详情 ===');
  console.log('请求URL:', CONFIG.mcpServerUrl);
  console.log('请求方法:', request.method);
  console.log('请求ID:', requestId);
  console.log('请求参数:', JSON.stringify(request.params || {}, null, 2));
  console.log('完整请求体:', JSON.stringify(mcpRequest, null, 2));
  
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), CONFIG.timeout);
    
    console.log('🚀 发送MCP请求到:', CONFIG.mcpServerUrl);
    const response = await fetch(CONFIG.mcpServerUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(mcpRequest),
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    
    console.log('📥 收到MCP响应 - 状态码:', response.status, response.statusText);
    console.log('响应头:', {
      'Content-Type': response.headers.get('Content-Type'),
      'Content-Length': response.headers.get('Content-Length')
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error('❌ MCP请求失败 - HTTP状态码:', response.status);
      console.error('错误响应:', errorText);
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    // 检查响应体是否为空（某些通知方法可能返回空响应）
    const contentType = response.headers.get('content-type') || '';
    const contentLength = response.headers.get('content-length');
    
    // 如果是notifications/initialized，可能返回空响应
    if (request.method === 'notifications/initialized') {
      // 尝试读取响应体，如果为空则返回null
      const text = await response.text();
      if (!text || text.trim() === '') {
        console.log('通知方法返回空响应（正常）');
        return null;
      }
      // 如果有内容，尝试解析JSON
      try {
        return JSON.parse(text);
      } catch (e) {
        console.warn('通知响应不是有效JSON，返回null');
        return null;
      }
    }
    
    // 对于其他请求，正常解析JSON
    const text = await response.text();
    console.log('📄 MCP响应体长度:', text.length);
    console.log('📄 MCP响应体预览（前500字符）:', text.substring(0, 500));
    
    if (!text || text.trim() === '') {
      console.warn('⚠️ 响应体为空，返回空对象');
      return {};
    }
    
    try {
      const data = JSON.parse(text);
      console.log('✅ MCP响应解析成功');
      console.log('响应数据:', {
        hasResult: !!data.result,
        hasError: !!data.error,
        resultType: data.result ? typeof data.result : 'N/A',
        errorMessage: data.error ? data.error.message : 'N/A'
      });
      if (data.result && data.result.contents) {
        console.log('响应内容数量:', data.result.contents.length);
      }
    return data;
    } catch (e) {
      console.error('❌ JSON解析失败:', e);
      console.error('响应文本:', text.substring(0, 500));
      throw new Error(`响应不是有效的JSON: ${e.message}`);
    }
  } catch (error) {
    // 网络错误处理
    if (error.name === 'AbortError') {
      if (retries < CONFIG.maxRetries) {
        console.log(`MCP请求超时，重试 ${retries + 1}/${CONFIG.maxRetries}`);
        await new Promise(resolve => setTimeout(resolve, 1000 * (retries + 1)));
        return sendMCPRequest(request, retries + 1);
      }
      throw new Error('MCP服务请求超时，请检查服务是否正常运行');
    }
    
    if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
      if (retries < CONFIG.maxRetries) {
        console.log(`网络错误，重试 ${retries + 1}/${CONFIG.maxRetries}`);
        await new Promise(resolve => setTimeout(resolve, 1000 * (retries + 1)));
        return sendMCPRequest(request, retries + 1);
      }
      throw new Error('无法连接到MCP服务，请检查服务是否启动（端口8000）');
    }
    
    // 处理JSON解析错误
    if (error.message.includes('Unexpected end of JSON input') || 
        error.message.includes('Failed to execute') && error.message.includes('json')) {
      // 如果是通知方法，空响应是正常的
      if (request.method === 'notifications/initialized') {
        console.log('通知方法返回空响应（正常）');
        return null;
      }
      // 其他方法的空响应可能是错误
      console.error('MCP请求返回空响应:', request);
      throw new Error('MCP服务返回空响应，可能是服务端错误');
    }
    
    console.error('MCP请求失败:', error);
    throw error;
  }
}

// 调用LLM（通过服务端代理，支持流式输出）
// 现在直接接受requestData，由服务端负责构建messages数组
async function callLLM(requestData, onStreamChunk = null, retries = 0) {
  // 将timeoutId提升到函数作用域，确保在catch块中也能访问
  let timeoutId = null;
  
  try {
    // 验证 requestData 是否存在且不为空
    if (!requestData) {
      throw new Error('requestData 为空或未定义，无法发送请求');
    }
    
    // 验证 requestData 是否为有效对象
    if (typeof requestData !== 'object' || Array.isArray(requestData)) {
      throw new Error(`requestData 类型错误: ${typeof requestData}，期望为对象`);
    }
    
    // 验证必要的字段是否存在
    if (!requestData.system_prompt && (!requestData.conversation_history || requestData.conversation_history.length === 0) && !requestData.user_input) {
      console.warn('⚠️ 警告：requestData 缺少必要字段（system_prompt、conversation_history 和 user_input 都为空）');
      console.warn('requestData 内容:', JSON.stringify(requestData, null, 2));
    }
    
    updateStatus('正在思考...', 'connecting');
    
    const controller = new AbortController();
    // 保存到全局变量，以便停止生成时使用
    currentAbortController = controller;
    isGenerating = true;
    setStopButtonState(true); // 切换到"停止生成"按钮
    timeoutId = setTimeout(() => {
      console.warn('⚠️ LLM请求超时，中止请求');
      controller.abort();
    }, CONFIG.timeout);
    
    // 通过MCP服务端代理调用LLM API，避免CORS问题
    const proxyUrl = `${CONFIG.mcpServerUrl}/api/llm/chat`;
    
    // 如果提供了onStreamChunk回调，则启用流式输出
    const stream = !!onStreamChunk;
    
    // 直接使用requestData，添加stream标志
    const requestBody = {
      ...requestData,
      stream: stream
    };
    
    // 验证 requestBody 是否为空对象
    const requestBodyKeys = Object.keys(requestBody);
    if (requestBodyKeys.length === 0 || (requestBodyKeys.length === 1 && requestBodyKeys[0] === 'stream')) {
      console.error('❌ 错误：requestBody 为空或只包含 stream 字段');
      console.error('requestData 内容:', JSON.stringify(requestData, null, 2));
      throw new Error('请求体为空，无法发送请求');
    }
    
    console.log('========== 客户端发送给代理服务的请求数据 ==========');
    console.log('代理服务URL:', proxyUrl);
    console.log('请求模式:', stream ? '(流式)' : '(非流式)');
    console.log('请求体结构:', {
      hasSystemPrompt: !!requestBody.system_prompt,
      inputType: requestBody.input_type || '未设置',
      conversationHistoryCount: requestBody.conversation_history?.length || 0,
      hasUserInput: !!requestBody.user_input,
      userInputType: requestBody.user_input ? (requestBody.user_input.role || 'text') : 'none',
      userInputPreview: requestBody.user_input ? (
        requestBody.user_input.role === 'system' 
          ? `[system] ${requestBody.user_input.content?.substring(0, 50)}...`
          : requestBody.user_input.text?.substring(0, 50) || ''
      ) : '无',
      stream: stream
    });
    console.log('完整请求体JSON:');
    console.log(JSON.stringify(requestBody, null, 2));
    console.log('================================================');
    
    // 验证请求体大小
    const requestBodyStr = JSON.stringify(requestBody);
    const requestBodySize = requestBodyStr.length;
    
    if (requestBodySize === 0 || requestBodySize < 10) {
      console.error('❌ 错误：请求体大小异常，可能为空');
      console.error('请求体字符串:', requestBodyStr);
      console.error('请求体对象:', requestBody);
      console.error('requestData 原始内容:', JSON.stringify(requestData, null, 2));
      throw new Error('请求体为空或异常，无法发送请求');
    }
    
    console.log('🚀 开始发送fetch请求到:', proxyUrl);
    console.log('请求方法: POST');
    console.log('请求体大小:', requestBodySize, '字节');
    console.log('流式模式:', stream);
    
    // 构建请求头
    const headers = {
      'Content-Type': 'application/json'
    };
    
    // 如果启用流式输出，添加Accept头声明期望接收text/event-stream
    if (stream) {
      headers['Accept'] = 'text/event-stream';
      console.log('✅ 已设置Accept: text/event-stream 请求头');
    }
    
    console.log('请求头:', headers);
    
    // 最终验证：确保请求体字符串不为空
    const finalRequestBodyStr = JSON.stringify(requestBody);
    if (!finalRequestBodyStr || finalRequestBodyStr.length === 0 || finalRequestBodyStr === '{}' || finalRequestBodyStr === '{"stream":false}' || finalRequestBodyStr === '{"stream":true}') {
      console.error('❌ 错误：最终请求体为空或无效');
      console.error('请求体字符串:', finalRequestBodyStr);
      console.error('requestBody 对象:', requestBody);
      console.error('requestData 原始内容:', JSON.stringify(requestData, null, 2));
      throw new Error('请求体为空，无法发送请求');
    }
    
    console.log('✅ 请求体验证通过，大小:', finalRequestBodyStr.length, '字节');
    
    const response = await fetch(proxyUrl, {
      method: 'POST',
      headers: headers,
      body: finalRequestBodyStr,
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    
    console.log('收到响应，状态码:', response.status, response.statusText);
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const errorMsg = errorData.error?.message || `HTTP ${response.status}`;
      
      console.error('LLM请求失败: [LLM_PROXY_RESPONSE_ERROR]', {
        status: response.status,
        error: errorMsg,
        errorData: errorData
      });
      
      // 如果是认证错误，不重试
      if (response.status === 401 || response.status === 403) {
        throw new Error(`LLM API认证失败: ${errorMsg}，请检查API Key配置`);
      }
      
      // 其他错误可以重试
      if (retries < CONFIG.maxRetries && (response.status >= 500 || response.status === 429)) {
        console.log(`LLM请求失败，重试 ${retries + 1}/${CONFIG.maxRetries}`);
        await new Promise(resolve => setTimeout(resolve, 1000 * (retries + 1)));
        return callLLM(requestData, onStreamChunk, retries + 1);
      }
      
      throw new Error(`LLM API错误: ${errorMsg}`);
    }
    
    if (stream) {
      // 流式处理
      console.log('开始流式处理响应...');
      console.log('响应Content-Type:', response.headers.get('Content-Type'));
      console.log('响应body是否存在:', !!response.body);
      
      if (!response.body) {
        console.error('错误：响应body为空，无法进行流式处理');
        throw new Error('响应body为空，无法进行流式处理');
      }
      
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let fullContent = '';
      let buffer = '';
      let chunkCount = 0;
      
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            console.log('流式读取完成，总块数:', chunkCount, '内容长度:', fullContent.length);
            // 流式读取完成，恢复发送按钮
            isGenerating = false;
            currentAbortController = null;
            setStopButtonState(false);
            break;
          }
          
          chunkCount++;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || ''; // 保留最后不完整的行
          
          for (const line of lines) {
            const trimmedLine = line.trim();
            if (!trimmedLine) continue; // 跳过空行
            
            if (trimmedLine.startsWith('data: ')) {
              const data = trimmedLine.slice(6).trim();
              if (data === '[DONE]') {
                console.log('收到流式结束标记');
                updateStatus('就绪', 'connected');
                console.log('流式内容总长度:', fullContent.length);
                // 流式读取完成，恢复发送按钮
                isGenerating = false;
                currentAbortController = null;
                setStopButtonState(false);
                return fullContent;
              }
              
              try {
                const json = JSON.parse(data);
                
                // 检查是否是新的格式（type: 7，包含reasoningQaText和lawQaText）
                if (json.type === 7 && json.data) {
                  const reasoningText = json.data.reasoningQaText || '';
                  let lawText = json.data.lawQaText || '';
                  
                  // 首先检查是否是invoke_tool_or_resource类型
                  // 注意：在流式响应中，JSON可能不完整，需要传递isStreaming=true
                  if (lawText) {
                    const invokeInfo = parseInvokeToolOrResource(lawText, true); // 传递isStreaming=true
                    if (invokeInfo) {
                      console.log('🔧 [流式] 检测到invoke_tool_or_resource类型，保留原始lawText用于后续处理');
                      // 保留原始lawText，不进行提取，等待完整响应后在parseAndHandleResponse中处理
                      // lawText保持原样，不提取结论
                    } else {
                      // 从lawQaText中提取prompt_to_user或conclusion字段
                      // 注意：在流式过程中，如果lawText是JSON字符串但无法提取，应该等待完整JSON
                      const extracted = extractConclusionFromLawQaText(lawText);
                      // 如果返回null，说明是invoke_tool_or_resource类型（已在上面处理）
                      if (extracted === null) {
                        // 已经是invoke_tool_or_resource类型，保持原样
                        console.log('🔧 [流式] extractConclusionFromLawQaText返回null，确认是invoke_tool_or_resource类型');
                      } else if (!extracted && lawText.trim().startsWith('{')) {
                        // 可能是JSON字符串但无法提取，在流式过程中不显示，等待完整JSON
                        lawText = '';  // 清空，等待完整JSON
                      } else {
                        lawText = extracted;
                      }
                    }
                  }
                  
                  // 更新累积内容（用于最终返回）
                  // 注意：新格式中，reasoningText和lawText已经是完整内容，不需要累积
                  if (reasoningText || lawText) {
                    if (reasoningText && lawText) {
                      fullContent = reasoningText + '\n==JSON==\n' + lawText;
                    } else if (reasoningText) {
                      fullContent = reasoningText;
                    } else if (lawText) {
                      fullContent = lawText;
                    }
                  }
                  
                  // 调用回调函数，传递思考内容和结论内容
                  if (onStreamChunk) {
                    console.log('[流式] 收到新格式数据，思考内容长度:', reasoningText.length, '结论长度:', lawText?.length || 0);
                    onStreamChunk(fullContent, reasoningText, lawText);
                  }
                } else {
                  // 兼容旧格式（DeepSeek原始格式）
                  const delta = json.choices?.[0]?.delta?.content;
                  if (delta) {
                    fullContent += delta;
                    if (onStreamChunk) {
                      onStreamChunk(fullContent);
                    }
                  }
                }
              } catch (e) {
                console.warn('流式数据JSON解析失败:', e, '数据:', data.substring(0, 100));
                // 忽略JSON解析错误
              }
            } else {
              // 如果不是data:开头，可能是其他格式，尝试直接解析
              console.warn('流式数据格式异常，不是data:开头:', trimmedLine.substring(0, 100));
            }
          }
        }
        
        // 处理最后剩余的buffer
        if (buffer.trim()) {
          console.log('处理剩余buffer:', buffer.substring(0, 100));
          const trimmedBuffer = buffer.trim();
          if (trimmedBuffer.startsWith('data: ')) {
            const data = trimmedBuffer.slice(6).trim();
            if (data !== '[DONE]') {
              try {
                const json = JSON.parse(data);
                
                // 检查是否是新的格式
                if (json.type === 7 && json.data) {
                  const reasoningText = json.data.reasoningQaText || '';
                  let lawText = json.data.lawQaText || '';
                  
                  // 首先检查是否是invoke_tool_or_resource类型
                  // 注意：在流式响应中，JSON可能不完整，需要传递isStreaming=true
                  if (lawText) {
                    const invokeInfo = parseInvokeToolOrResource(lawText, true); // 传递isStreaming=true
                    if (invokeInfo) {
                      console.log('🔧 [流式buffer] 检测到invoke_tool_or_resource类型，保留原始lawText用于后续处理');
                      // 保留原始lawText，不进行提取，等待完整响应后在parseAndHandleResponse中处理
                      // lawText保持原样，不提取结论
                    } else {
                      // 从lawQaText中提取prompt_to_user或conclusion字段
                      // 注意：在流式过程中，如果lawText是JSON字符串但无法提取，应该等待完整JSON
                      const extracted = extractConclusionFromLawQaText(lawText);
                      // 如果返回null，说明是invoke_tool_or_resource类型（已在上面处理）
                      if (extracted === null) {
                        // 已经是invoke_tool_or_resource类型，保持原样
                        console.log('🔧 [流式buffer] extractConclusionFromLawQaText返回null，确认是invoke_tool_or_resource类型');
                      } else if (!extracted && lawText.trim().startsWith('{')) {
                        // 可能是JSON字符串但无法提取，在流式过程中不显示，等待完整JSON
                        lawText = '';  // 清空，等待完整JSON
                      } else {
                        lawText = extracted;
                      }
                    }
                  }
                  
                  if (reasoningText) {
                    fullContent = reasoningText;
                    if (lawText) {
                      fullContent += '\n==JSON==\n' + lawText;
                    }
                  } else if (lawText) {
                    fullContent = lawText;
                  }
                  
                  if (onStreamChunk) {
                    onStreamChunk(fullContent, reasoningText, lawText);
                  }
                } else {
                  // 兼容旧格式
                  const delta = json.choices?.[0]?.delta?.content;
                  if (delta) {
                    fullContent += delta;
                    if (onStreamChunk) {
                      onStreamChunk(fullContent);
                    }
                  }
                }
              } catch (e) {
                console.warn('最后buffer JSON解析失败:', e);
              }
            }
          }
        }
        
        updateStatus('就绪', 'connected');
        console.log('流式处理完成，最终内容长度:', fullContent.length);
        if (fullContent.length === 0) {
          console.error('警告：流式响应内容为空！');
        }
        // 确保发送按钮可用（如果之前没有在[DONE]或done时调用）
        isGenerating = false;
        currentAbortController = null;
        setStopButtonState(false);
        return fullContent;
      } catch (streamError) {
        console.error('流式处理错误:', streamError);
        // 确保清理超时定时器
        if (typeof timeoutId !== 'undefined') {
          clearTimeout(timeoutId);
        }
        // 流式处理出错时也要重置按钮
        isGenerating = false;
        currentAbortController = null;
        setStopButtonState(false);
        throw streamError;
      } finally {
        reader.releaseLock();
      }
    } else {
      // 非流式处理（原有逻辑）
    const data = await response.json();
      console.log('LLM响应解析成功，包含choices:', data.choices?.length || 0);
      
      if (!data.choices || !data.choices[0] || !data.choices[0].message) {
        throw new Error('LLM响应格式错误：缺少choices或message');
      }
      
    updateStatus('就绪', 'connected');
    // 非流式处理完成，重置按钮
    isGenerating = false;
    currentAbortController = null;
    setStopButtonState(false);
    return data.choices[0].message.content;
    }
  } catch (error) {
    // 确保清理超时定时器（如果还存在）
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
    
    console.error('callLLM错误:', error);
    
    // 在清空currentAbortController之前，先检查是否是用户主动停止
    // 用户主动停止：stopGeneration()会先清空currentAbortController，然后调用abort()
    // 超时停止：超时定时器直接调用abort()，此时currentAbortController还未被清空
    const wasUserStopped = !currentAbortController;
    
    // 错误时也要重置按钮状态
    isGenerating = false;
    currentAbortController = null;
    setStopButtonState(false);
    
    if (error.name === 'AbortError') {
      // 检查是否是用户主动停止
      // 如果currentAbortController在abort之前就已经是null，说明是用户主动停止
      if (wasUserStopped) {
        console.log('用户主动停止生成，不进行重试');
        throw new Error('生成已停止');
      }
      
      // 否则是超时或其他原因导致的abort，可以重试
      console.log('请求被中止（可能是超时），检查是否需要重试');
      if (retries < CONFIG.maxRetries) {
        console.log(`LLM请求超时，重试 ${retries + 1}/${CONFIG.maxRetries}`);
        await new Promise(resolve => setTimeout(resolve, 1000 * (retries + 1)));
        return callLLM(requestData, onStreamChunk, retries + 1);
      }
      throw new Error('LLM请求超时，已重试3次，请检查网络连接或稍后重试');
    }
    
    // 网络错误
    if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
      console.error('LLM请求失败: [LLM_PROXY_NETWORK_ERROR]', {
        url: `${CONFIG?.mcpServerUrl}/api/llm/chat`,
        error: error.message
      });
      if (retries < CONFIG.maxRetries) {
        console.log(`网络错误，重试 ${retries + 1}/${CONFIG.maxRetries}`);
        await new Promise(resolve => setTimeout(resolve, 1000 * (retries + 1)));
        return callLLM(requestData, null, retries + 1);
      }
      throw new Error('无法连接到LLM服务，请检查MCP服务端是否正常运行');
    }
    
    throw error;
  }
}

// 组装请求数据
function buildRequestData(userInput, options = {}) {
  // options 参数：
  // - afterInvocation: 是否在调用资源/工具/提示词模版后调用
  // - invocationType: 'prompt' | 'resource' | 'tool'
  // - invocationName: 调用的名称（提示词模版名称、资源URI或工具名称）
  // - systemMessage: 自定义 system 消息内容（可选）
  
  const { afterInvocation = false, invocationType = null, invocationName = null, systemMessage = null } = options;
  
  // 收集所有文件ID
  const fileIds = [];
  const fileIdSet = new Set(); // 用于去重
  
  // 1. 从首页上传的文件ID（存储在window.uploadedFileIds）
  if (window.uploadedFileIds && Array.isArray(window.uploadedFileIds)) {
    window.uploadedFileIds.forEach(id => {
      if (!fileIdSet.has(id)) {
        fileIds.push(id);
        fileIdSet.add(id);
      }
    });
    console.log('从首页添加文件ID:', window.uploadedFileIds);
  }
  
  // 2. 从pendingFiles中获取已上传的文件ID
  for (const fileData of pendingFiles) {
    if (fileData.fileInfo && fileData.fileInfo.file_id) {
      const fileId = fileData.fileInfo.file_id;
      // 只添加已上传到服务端的文件ID（不是临时ID）
      if (!fileId.startsWith('temp_') && !fileIdSet.has(fileId)) {
        fileIds.push(fileId);
        fileIdSet.add(fileId);
        console.log('从pendingFiles添加文件ID:', fileId);
      }
    }
  }
  
  // 3. 从历史对话中提取文件ID（重要：确保历史对话中的文件也能被包含）
  if (currentSession.conversationHistory && Array.isArray(currentSession.conversationHistory)) {
    for (const msg of currentSession.conversationHistory) {
      // 检查消息是否包含文件ID
      if (msg.file_ids && Array.isArray(msg.file_ids)) {
        msg.file_ids.forEach(id => {
          if (!fileIdSet.has(id)) {
            fileIds.push(id);
            fileIdSet.add(id);
            console.log('从历史对话中提取文件ID:', id);
          }
        });
      }
    }
    console.log(`✅ 已从历史对话中提取文件ID，当前总文件数: ${fileIds.length}`);
  }
  
  // 检查CONFIG是否已初始化
  if (!CONFIG || !CONFIG.mcpServerUrl) {
    throw new Error('CONFIG未初始化，请确保已调用loadConfig()');
  }
  
  // 确保mcpTools是数组（可能是undefined或null）
  const tools = (mcpTools || []).map(t => ({
    name: t.name,
    description: t.description || '',
    inputSchema: t.inputSchema || {}
  }));
  
  // 确保mcpResources是数组（可能是undefined或null）
  const resources = (mcpResources || []).map(r => ({
    uri: r.uri,
    description: r.description,
    parameters: getResourceParameters(r.uri)
  }));
  
  // 确保mcpPrompts是数组（可能是undefined或null）
  const prompts = (mcpPrompts || []).map(p => ({
    name: p.name,
    description: p.description || ''
  }));
  
  console.log('📦 构建请求数据 - 能力列表:');
  console.log(`   - 工具: ${tools.length}个`);
  console.log(`   - 资源: ${resources.length}个`);
  console.log(`   - 提示词模板: ${prompts.length}个`);
  
  // 构建历史对话（如果需要将用户输入添加到历史中）
  let conversationHistory = [...(currentSession.conversationHistory || [])];
  
  // 如果在调用后，需要将相关信息添加到历史对话中
  if (afterInvocation) {
    // 构建 system 消息
    let systemContent = systemMessage;
    if (!systemContent) {
      // 根据调用类型生成默认消息
      if (invocationType === 'prompt') {
        systemContent = `你已成功加载 '${invocationName}' 提示词指南。请严格按照该指南的第一步开始执行：向用户提问以收集案情信息。不要再次请求调用 ${invocationName}。当前工作模式为 workflow。`;
      } else if (invocationType === 'resource') {
        systemContent = `你已成功获取资源 '${invocationName}' 的内容。请根据资源内容继续处理用户请求。不要再次请求调用该资源。`;
      } else if (invocationType === 'tool') {
        systemContent = `你已成功调用工具 '${invocationName}'。请根据工具执行结果继续处理用户请求。不要再次请求调用该工具。`;
      } else {
        systemContent = `资源/工具/提示词模版已成功调用。请继续处理用户请求，不要重复调用。`;
      }
    }
    
    // 将 system 消息添加到历史对话中
    conversationHistory.push({
      role: 'system',
      content: systemContent
    });
    
    // 如果有用户输入（包含资源响应JSON），也添加到历史对话中
    if (userInput) {
      conversationHistory.push({
        role: 'user',
        content: userInput
      });
    }
    
    console.log('✅ 已将 system 消息和用户输入添加到历史对话中');
    console.log('✅ System 消息内容:', systemContent);
  }
  
  // 重构后的数据结构：更清晰的分组
  const requestData = {
    system_prompt: CONFIG.systemPrompt || '',
    
    // 统一的服务端能力字段
    server_ability: {
      tools: tools,
      resources: resources,
      prompts: prompts
    },
    
    // 输入类型：区分用户直接输入和系统自动行为
    input_type: afterInvocation ? 'auto' : 'user',
    
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
    
    conversation_history: conversationHistory
  };
  
  // 如果在调用后，不设置 user_input 字段（这是系统行为）
  if (afterInvocation) {
    // 系统行为：不设置 user_input 字段
    console.log('✅ 系统行为：已移除 user_input 字段');
    // 确保 user_input 字段不存在
    if (requestData.user_input) {
      delete requestData.user_input;
      console.log('⚠️ 检测到 user_input 字段，已删除');
    }
  } else {
    // 正常情况：使用用户输入
    requestData.user_input = {
      text: userInput,
      file_ids: fileIds.length > 0 ? fileIds : undefined
    };
    
    // 如果有文件ID，记录详细信息
    if (fileIds.length > 0) {
      console.log(`📎 请求包含 ${fileIds.length} 个文件ID:`, fileIds);
      console.log('📎 文件ID来源: 当前请求 + 历史对话');
    }
    
    // 移除 undefined 的 file_ids，保持数据结构简洁
    if (!requestData.user_input.file_ids) {
      delete requestData.user_input.file_ids;
    }
  }
  
  // 最终验证：确保 afterInvocation 时 user_input 不存在
  if (afterInvocation && requestData.user_input) {
    console.error('❌ 错误：afterInvocation=true 但 user_input 字段仍然存在！');
    delete requestData.user_input;
  }
  
  // 如果是在工作流模式下，自动添加 mode 和 current_prompt 字段
  if (currentSession.workflow && currentSession.workflow.mode === 'workflow') {
    requestData.mode = 'workflow';
    // 如果已保存提示词模版内容，则自动携带
    if (currentSession.workflow.current_prompt) {
      requestData.current_prompt = currentSession.workflow.current_prompt;
      console.log('✅ 工作流模式：已添加 mode 和 current_prompt 字段，提示词长度:', currentSession.workflow.current_prompt.length);
    } else {
      console.log('✅ 工作流模式：已添加 mode 字段，但 current_prompt 尚未设置（提示词模版尚未调用）');
    }
  }
  
  console.log('✅ 已构建请求数据（新结构）:', {
    hasSystemPrompt: !!requestData.system_prompt,
    inputType: requestData.input_type,
    mode: requestData.mode || '未设置',
    hasCurrentPrompt: !!requestData.current_prompt,
    currentPromptLength: requestData.current_prompt?.length || 0,
    serverAbility: {
      tools: requestData.server_ability.tools.length,
      resources: requestData.server_ability.resources.length,
      prompts: requestData.server_ability.prompts.length
    },
    hasUserInput: !!requestData.user_input,
    userInput: afterInvocation ? '系统行为：已移除user_input字段' : {
      textLength: requestData.user_input?.text?.length || 0,
      fileIdsCount: requestData.user_input?.file_ids?.length || 0
    },
    conversationHistoryLength: requestData.conversation_history?.length || 0
  });
  
  // 验证返回的 requestData 是否有效
  if (!requestData || typeof requestData !== 'object') {
    console.error('❌ 错误：buildRequestData 返回了无效数据');
    throw new Error('构建请求数据失败：返回了无效数据');
  }
  
  // 验证至少有一个必要字段存在
  const hasSystemPrompt = !!requestData.system_prompt;
  const hasConversationHistory = requestData.conversation_history && requestData.conversation_history.length > 0;
  const hasUserInput = !!requestData.user_input;
  
  if (!hasSystemPrompt && !hasConversationHistory && !hasUserInput) {
    console.error('❌ 错误：buildRequestData 返回的数据缺少所有必要字段');
    console.error('requestData 内容:', JSON.stringify(requestData, null, 2));
    throw new Error('构建请求数据失败：缺少必要字段（system_prompt、conversation_history 和 user_input 都为空）');
  }
  
  return requestData;
}

// 获取资源参数定义
function getResourceParameters(uri) {
  const paramMap = {
    'legal://doc_template': {
      type: 'object',
      properties: {
        template_name: {
          type: 'string',
          description: '必填，知识库要素文书名称（含案由全称），例如 \'民间借贷纠纷起诉状\'。'
        }
      },
      required: ['template_name']
    },
    'legal://law_regulation': {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: '必填，用户输入的法规检索关键词或条文编号，例如 \'民法典311条\'、\'合同法第52条\'。'
        }
      },
      required: ['query']
    },
    'legal://similar_cases': {
      type: 'object',
      properties: {
        case_description: {
          type: 'string',
          description: '必填，用户描述的案情内容，用于匹配相似案例。'
        }
      },
      required: ['case_description']
    },
    'legal://contract_review_rules': {
      type: 'object',
      properties: {}
    }
  };
  return paramMap[uri] || { type: 'object', properties: {} };
}

// 处理用户输入 - 确保全局可访问
// 注意：这个函数会覆盖之前定义的占位符函数
window.handleUserInput = async function(userInputText = null) {
  console.log('========================================');
  console.log('=== handleUserInput函数被调用（正式版本） ===');
  console.log('========================================');
  console.log('调用时间:', new Date().toISOString());
  console.log('调用堆栈:', new Error().stack);
  console.log('传入的文本参数:', userInputText);
  console.log('elements对象:', {
    userInput: !!elements.userInput,
    sendBtn: !!elements.sendBtn,
    chatMessages: !!elements.chatMessages
  });
  console.log('sendBtn状态:', {
    disabled: elements.sendBtn?.disabled,
    innerHTML: elements.sendBtn?.innerHTML?.substring(0, 100)
  });
  console.log('处理状态:', {
    isProcessingInput: isProcessingInput,
    isGenerating: isGenerating
  });
  
  // 防止重复处理：如果正在处理输入，直接返回
  if (isProcessingInput) {
    console.warn('⚠️ 正在处理输入，忽略重复调用');
    return;
  }
  
  // 检查是否正在生成中
  if (isGenerating) {
    console.warn('⚠️ 正在生成中，忽略本次调用');
    return;
  }
  
  // 注意：不再检查按钮disabled状态，因为按钮的onclick已经检查过了
  // 如果按钮被禁用，onclick不会被触发，所以这里不需要再次检查
  // 这样可以避免因为按钮状态更新时序问题导致的误判
  
  // 设置处理标记
  isProcessingInput = true;
  
  if (!elements.userInput) {
    console.error('userInput元素不存在，尝试重新获取');
    elements.userInput = document.getElementById('userInput');
    if (!elements.userInput) {
      alert('错误：找不到输入框元素');
      isProcessingInput = false; // 重置处理标记
      return;
    }
  }
  
  // 优先使用传入的文本参数（从首页跳转过来时使用）
  // 如果没有传入参数，则从输入框读取
  let userInput = '';
  let inputElement = null;
  let rawValue = '';
  
  if (userInputText !== null && userInputText !== undefined) {
    // 使用传入的文本参数（从首页跳转过来时）
    userInput = String(userInputText).trim();
    console.log('使用传入的文本参数（不填充到输入框）:', userInput);
    // 获取输入框元素引用（用于后续日志，但不使用其值）
    inputElement = elements.userInput;
  } else {
    // 从输入框读取（正常情况）
    inputElement = elements.userInput;
    if (!inputElement) {
      console.error('输入框元素不存在');
      isProcessingInput = false; // 重置处理标记
      return;
    }
    
    // 直接获取value，避免可能的异步问题
    // 使用多种方式获取，确保能正确获取到值
    try {
      rawValue = inputElement.value || '';
      // 如果value为空，尝试从textContent获取（某些情况下可能有用）
      if (!rawValue && inputElement.textContent) {
        rawValue = inputElement.textContent.trim();
      }
    } catch (e) {
      console.error('获取输入框值失败:', e);
      rawValue = '';
    }
    
    // 确保 rawValue 是字符串类型，然后进行 trim
    if (rawValue != null) {
      // 转换为字符串（处理数字、对象等特殊情况）
      const strValue = String(rawValue);
      userInput = strValue.trim();
    } else {
      userInput = '';
    }
    
    console.log('=== trim 操作检查 ===');
    console.log('rawValue (trim前):', rawValue, '类型:', typeof rawValue);
    console.log('userInput (trim后):', userInput, '类型:', typeof userInput);
    
    // 如果输入框为空，检查URL参数或全局变量中是否有输入（从首页跳转过来的情况）
    if (!userInput) {
      let inputTextToUse = null;
      
      // 首先检查全局变量（handleHomePageInput保存的）
      if (window._pendingInputText) {
        inputTextToUse = window._pendingInputText;
        console.log('从全局变量获取inputText:', inputTextToUse);
      } else {
        // 如果没有全局变量，检查URL参数
        try {
          const urlParams = new URLSearchParams(window.location.search);
          const urlInputText = urlParams.get('input');
          if (urlInputText) {
            inputTextToUse = urlInputText;
            console.log('从URL参数获取inputText:', urlInputText);
          }
        } catch (e) {
          console.error('从URL参数获取输入失败:', e);
        }
      }
      
      // 如果有输入文本，使用它（但不填充到输入框，因为是从首页跳转过来的）
      if (inputTextToUse) {
        try {
          const decodedInput = decodeURIComponent(inputTextToUse).trim();
          if (decodedInput) {
            // 如果URL参数或全局变量中有输入，使用它但不填充到输入框
            userInput = decodedInput;
            console.log('从保存的文本获取输入（不填充到输入框）:', decodedInput);
          }
        } catch (e) {
          console.error('解码输入文本失败:', e);
        }
      }
    }
  }
  
  // 检查是否有输入内容或待发送的文件
  // 同时检查是否有已上传的文件ID（从sessionStorage或全局变量）
  let uploadedFileIds = [];
  try {
    // 首先检查全局变量（handleHomePageInput设置的）
    if (window.uploadedFileIds && Array.isArray(window.uploadedFileIds)) {
      uploadedFileIds = window.uploadedFileIds;
      console.log('从全局变量获取uploadedFileIds:', uploadedFileIds);
    } else {
      // 如果没有全局变量，从sessionStorage获取
      const uploadedFileIdsStr = sessionStorage.getItem('uploadedFileIds');
      if (uploadedFileIdsStr) {
        uploadedFileIds = JSON.parse(uploadedFileIdsStr);
        console.log('从sessionStorage获取uploadedFileIds:', uploadedFileIds);
      }
    }
  } catch (e) {
    console.error('获取uploadedFileIds失败:', e);
    uploadedFileIds = [];
  }
  
  const hasFiles = (pendingFiles && pendingFiles.length > 0) || (uploadedFileIds && uploadedFileIds.length > 0);
  
  // 详细日志，用于调试
  console.log('=== 输入检查（详细） ===');
  console.log('输入框元素:', inputElement);
  console.log('输入框元素类型:', typeof inputElement);
  if (inputElement) {
    console.log('输入框value属性:', inputElement.value);
    console.log('输入框value类型:', typeof inputElement.value);
    console.log('输入框value长度:', inputElement.value ? inputElement.value.length : 0);
  }
  console.log('原始输入值 (rawValue):', rawValue);
  console.log('rawValue类型:', typeof rawValue);
  console.log('rawValue长度:', rawValue ? rawValue.length : 0);
  console.log('trim后输入值 (userInput):', userInput);
  console.log('userInput类型:', typeof userInput);
  console.log('userInput长度:', userInput ? userInput.length : 0);
  console.log('userInput是否为字符串:', typeof userInput === 'string');
  console.log('userInput是否为空字符串:', userInput === '');
  console.log('userInput是否为null:', userInput === null);
  console.log('userInput是否为undefined:', userInput === undefined);
  console.log('userInput的JSON表示:', JSON.stringify(userInput));
  console.log('pendingFiles:', pendingFiles);
  console.log('pendingFiles数量:', pendingFiles ? pendingFiles.length : 0);
  console.log('uploadedFileIds:', uploadedFileIds);
  console.log('uploadedFileIds数量:', uploadedFileIds ? uploadedFileIds.length : 0);
  console.log('hasFiles:', hasFiles);
  
  // 只有当既没有文本输入（包括只有空格的情况），也没有任何文件时，才提示
  // 使用更严格的检查：userInput必须是非空字符串
  // 检查逻辑分解，便于调试
  const check1 = !!userInput; // 检查是否存在（非null、非undefined、非空字符串）
  const check2 = typeof userInput === 'string';
  const check3 = userInput && userInput.length > 0;
  
  console.log('=== hasTextInput 检查分解 ===');
  console.log('check1 (!!userInput):', check1);
  console.log('check2 (typeof userInput === "string"):', check2);
  console.log('check3 (userInput && userInput.length > 0):', check3);
  
  const hasTextInput = check1 && check2 && check3;
  
  console.log('hasTextInput (最终结果):', hasTextInput);
  console.log('最终判断 - hasTextInput:', hasTextInput, 'hasFiles:', hasFiles);
  
  if (!hasTextInput && !hasFiles) {
    console.error('❌ 输入检查失败 - 既没有文本输入，也没有文件');
    console.error('调试信息:', {
      userInput: userInput,
      userInputType: typeof userInput,
      userInputLength: userInput ? userInput.length : 0,
      pendingFilesLength: pendingFiles ? pendingFiles.length : 0,
      uploadedFileIdsLength: uploadedFileIds ? uploadedFileIds.length : 0
    });
    alert('请输入内容或上传文件');
    isProcessingInput = false; // 重置处理标记
    return;
  }
  
  // 如果有输入或文件，继续处理
  if (hasTextInput) {
    console.log('✅ 检测到文本输入，长度:', userInput.length, '内容预览:', userInput.substring(0, 50));
  }
  if (hasFiles) {
    console.log('✅ 检测到文件，pendingFiles:', pendingFiles ? pendingFiles.length : 0, 'uploadedFileIds:', uploadedFileIds ? uploadedFileIds.length : 0);
  }
  
  console.log('=== 开始处理用户输入 ===');
  console.log('用户输入:', userInput);
  
  // 注意：按钮状态由callLLM函数内部管理，这里不需要设置
  
  // 处理待发送的文件：先显示文件卡片，再构建文件消息文本（用于发送给LLM）
  // 使用Set来跟踪已显示的文件ID，避免重复显示
  const displayedFileIds = new Set();
  
  // 检查聊天消息区域中是否已经存在文件卡片
  if (elements.chatMessages) {
    const existingFileCards = elements.chatMessages.querySelectorAll('.file-message-card');
    existingFileCards.forEach(card => {
      // 从卡片中提取文件ID（通过data-file-id属性）
      const fileIdAttr = card.getAttribute('data-file-id');
      if (fileIdAttr) {
        displayedFileIds.add(fileIdAttr);
        console.log(`检测到已存在的文件卡片: ${fileIdAttr}`);
      }
    });
  }
  
  const fileMessages = [];
  for (const fileData of pendingFiles) {
    const fileInfo = fileData.fileInfo;
    const fileId = fileInfo.file_id;
    
    // 检查是否已经显示过这个文件卡片，避免重复显示
    if (!displayedFileIds.has(fileId)) {
      // 在界面上显示文件卡片
      addFileMessageCard(fileInfo);
      displayedFileIds.add(fileId); // 标记为已显示
      console.log(`✅ 显示文件卡片: ${fileInfo.original_name} (${fileId})`);
    } else {
      console.log(`⚠️ 文件卡片已存在，跳过重复显示: ${fileInfo.original_name} (${fileId})`);
    }
    
    // 构建文件消息文本（用于发送给LLM）
    const fileMessage = `📎 文件已上传: ${fileInfo.original_name}\n文件ID: ${fileInfo.file_id}\n大小: ${(fileInfo.file_size / 1024).toFixed(2)}KB`;
    fileMessages.push(fileMessage);
    
    // 如果是文本文件且有内容，也添加文件内容
    if (fileData.isTextFile && fileData.fileContent) {
      fileMessages.push(fileData.fileContent);
    }
  }
  
  // 确保 userInput 已定义
  if (typeof userInput === 'undefined') {
    console.error('错误：userInput 未定义');
    // 重置按钮状态
    isGenerating = false;
    currentAbortController = null;
    setStopButtonState(false);
    showError('处理失败: 用户输入未定义');
    isProcessingInput = false; // 重置处理标记
    return;
  }
  
  // 构建完整的用户消息（包含文本和文件）
  // 提前声明变量，避免TDZ（Temporal Dead Zone）问题
  let fullUserMessage;
  try {
    // 使用立即执行的函数表达式确保变量在作用域内正确初始化
    fullUserMessage = (() => {
      let message = userInput || '';
      if (fileMessages.length > 0) {
        if (userInput) {
          message = userInput + '\n\n' + fileMessages.join('\n\n');
        } else {
          message = fileMessages.join('\n\n');
        }
      }
      return message;
    })();
  } catch (error) {
    console.error('构建用户消息失败:', error);
    console.error('错误堆栈:', error.stack);
    setLoadingState(false);
    showError('处理失败: 构建用户消息时出错');
    isProcessingInput = false; // 重置处理标记
    return;
  }
  
  // 验证 fullUserMessage 已正确初始化
  if (!fullUserMessage || typeof fullUserMessage !== 'string' || fullUserMessage.trim() === '') {
    console.error('错误：fullUserMessage 未正确初始化', {
      fullUserMessage,
      type: typeof fullUserMessage,
      userInput,
      fileMessagesLength: fileMessages.length
    });
    setLoadingState(false);
    showError('处理失败: 用户消息未正确初始化，请检查输入内容');
    isProcessingInput = false; // 重置处理标记
    return;
  }
  
  console.log('✅ fullUserMessage 已初始化，长度:', fullUserMessage.length);
  
  // 检查是否有会话，如果没有则创建（延迟创建会话，仅在确认有有效对话内容后）
  // 注意：只有在确认对话内容不为空时才创建会话，避免创建空会话
  if (!currentSession || !currentSession.sessionId) {
    console.log('=== 首次发送消息，创建新会话（已确认有有效对话内容）===');
    try {
      await createNewSession();
      console.log('✅ 会话已创建:', currentSession.sessionId);
    } catch (error) {
      console.error('创建会话失败:', error);
      // ⚠️ 不提前返回，允许继续执行
      // 即使会话创建失败，也尝试使用本地会话继续
      if (!currentSession || !currentSession.sessionId) {
        // 如果连本地会话都没有，创建一个临时会话
        const tempSessionId = `sess_${Date.now()}`;
        currentSession = {
          sessionId: tempSessionId,
          status: 'active',
          currentIntent: null,
          collectedParameters: {},
          missingParameters: [],
          stage: 'idle',
          contextCache: {},
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          conversationHistory: []
        };
        console.warn('⚠️ 使用临时会话继续执行，会话ID:', tempSessionId);
      }
      // 不显示错误提示，静默处理，允许继续执行到chat接口
      // 注意：即使会话创建失败，也不应该阻止用户与LLM交互
    }
  }
  
  // 如果有文本输入，添加文本消息到界面
  if (userInput && userInput.trim()) {
    addMessage('user', userInput);
  }
  
  // 清空输入框和文件预览
  elements.userInput.value = '';
  clearAllFiles();
  
  // 更新发送按钮状态（发送后清空输入和文件，应该禁用按钮）
  if (typeof updateSendButtonState === 'function') {
    updateSendButtonState();
  }
  
  // 注意：不在此时将用户输入添加到conversationHistory
  // 因为buildRequestData需要使用不包含当前输入的conversation_history
  // 用户输入会在收到响应后和助手响应一起添加到历史中
  
  console.log('✅ 准备使用 fullUserMessage，长度:', fullUserMessage.length);

  const orchestrated = await tryHandleOrchestrate(fullUserMessage);
  if (orchestrated) {
    isGenerating = false;
    currentAbortController = null;
    if (typeof setStopButtonState === 'function') setStopButtonState(false);
    isProcessingInput = false;
    return;
  }

  // 初始化流式消息容器
  const streamingMsg = addStreamingMessage();
  let accumulatedContent = '';
  let thinkingContent = '';
  let conclusionContent = '';
  
  try {
    console.log('步骤1: 组装请求数据');
    console.log('当前会话历史长度:', currentSession.conversationHistory?.length || 0);
    console.log('当前会话历史内容:', JSON.stringify(currentSession.conversationHistory, null, 2));
    
    // 组装请求数据（使用包含文件的完整输入）
    // 注意：fullUserMessage 已在try块外定义，可以直接使用
    console.log('准备调用 buildRequestData，fullUserMessage 类型:', typeof fullUserMessage, '长度:', fullUserMessage?.length);
    
    let requestData;
    try {
      requestData = buildRequestData(fullUserMessage);
      console.log('✅ buildRequestData 调用成功');
    } catch (error) {
      console.error('❌ buildRequestData 调用失败:', error);
      console.error('错误堆栈:', error.stack);
      throw new Error(`组装请求数据失败: ${error.message}`);
    }
    
    console.log('请求数据已组装:', {
      hasSystemPrompt: !!requestData.system_prompt,
      resourcesCount: requestData.resources?.length || 0,
      sessionId: requestData.session?.session_id,
      conversationHistoryCount: requestData.conversation_history?.length || 0,
      currentUserInput: requestData.current_user_input?.substring(0, 50) || '(空)',
      fileIdsCount: requestData.file_ids?.length || 0
    });
    console.log('请求数据中的conversation_history:', JSON.stringify(requestData.conversation_history, null, 2));
    
    console.log('步骤2: 准备调用LLM（流式）');
    console.log('MCP服务端URL:', CONFIG?.mcpServerUrl);
    console.log('LLM代理URL:', `${CONFIG?.mcpServerUrl}/api/llm/chat`);
    
    // 验证CONFIG是否已初始化
    if (!CONFIG || !CONFIG.mcpServerUrl) {
      throw new Error('CONFIG未初始化或MCP服务端URL未配置，请确保已调用loadConfig()');
    }
    
    // 流式回调函数
    // 支持新格式：onStreamChunk(fullContent, reasoningText, lawText)
    // 兼容旧格式：onStreamChunk(fullContent)
    const onStreamChunk = (content, reasoningText = null, lawText = null) => {
      accumulatedContent = content;
      
        // 如果提供了新格式的参数，直接使用
        if (reasoningText !== null || lawText !== null) {
          thinkingContent = reasoningText || '';
          // 如果lawText存在，确保提取可读内容（因为lawText可能是JSON字符串）
          if (lawText) {
            // 首先检查是否是invoke_tool_or_resource类型
            // 注意：在流式响应中，JSON可能不完整，需要传递isStreaming=true
            const invokeInfo = parseInvokeToolOrResource(lawText, true); // 流式响应，传递isStreaming=true
            if (invokeInfo) {
              console.log('🔧 流式过程中检测到invoke_tool_or_resource类型，标记需要调用工具/资源');
              // 在流式过程中，暂时不显示结论内容，等待完整响应后再处理
              conclusionContent = '';
              // 注意：实际的工具/资源调用会在parseAndHandleResponse中处理
          } else {
              // 尝试从lawText中提取可读内容（如果它是JSON字符串）
              const extracted = extractConclusionFromLawQaText(lawText);
              // 如果返回null，说明是invoke_tool_or_resource类型（已在上面处理）
              if (extracted === null) {
                conclusionContent = '';
              } else if (extracted === lawText && lawText.trim().startsWith('{')) {
                // JSON字符串但无法提取，可能是JSON不完整，等待完整JSON后再显示
                conclusionContent = '';  // 不显示JSON原始文本
              } else {
                conclusionContent = extracted;
              }
            }
          } else {
            conclusionContent = '';
          }
          console.log('流式回调收到新格式数据，思考内容长度:', thinkingContent.length, 
                      '结论内容长度:', conclusionContent.length);
      } else {
        // 旧格式：从完整内容中解析
        console.log('流式回调收到内容，长度:', content.length, '预览:', content.substring(0, 100));
        
        // 查找分隔符（使用 "==JSON==" 区分思考内容和结论内容）
        const separator = '==JSON==';
        const separatorIndex = content.indexOf(separator);
        
        if (separatorIndex !== -1) {
          thinkingContent = content.substring(0, separatorIndex).trim();
          const jsonContent = content.substring(separatorIndex + separator.length).trim();
          // 尝试解析JSON并提取可读内容，而不是显示JSON字符串
          const extractedConclusion = parseJsonAndExtractConclusion(jsonContent);
          if (extractedConclusion) {
            conclusionContent = extractedConclusion;
            console.log('找到分隔符，已解析JSON并提取结论，思考内容长度:', thinkingContent.length, '结论长度:', conclusionContent.length);
          } else {
            // 如果无法解析，检查是否是完整的JSON对象
            // 如果是完整JSON但无法提取，显示提示；如果是JSON片段，等待完整JSON
            try {
              const parsed = JSON.parse(jsonContent);
              // JSON完整但无法提取可读内容，显示提示而不是JSON字符串
              conclusionContent = '正在处理响应...';
              console.log('找到分隔符，JSON完整但无法提取可读内容，显示等待提示');
            } catch (e) {
              // JSON不完整，显示等待提示而不是JSON片段
              conclusionContent = '正在接收响应...';
              console.log('找到分隔符，JSON不完整，显示等待提示');
            }
          }
        } else {
          // 没有分隔符，整个内容作为思考内容
          thinkingContent = content;
          conclusionContent = '';
          console.log('未找到分隔符，整个内容作为思考内容，长度:', thinkingContent.length);
        }
      }
      
      console.log('更新流式消息，思考内容:', thinkingContent ? '有(' + thinkingContent.length + '字符)' : '无', 
                  '结论内容:', conclusionContent ? '有(' + conclusionContent.length + '字符)' : '无');
      updateStreamingMessage(thinkingContent, conclusionContent);
    };
    
    console.log('步骤2.5: 准备调用callLLM函数');
    console.log('requestData已准备，开始调用LLM API...');
    console.log('CONFIG状态检查:', {
      mcpServerUrl: CONFIG?.mcpServerUrl,
      systemPrompt: CONFIG?.systemPrompt ? `存在(${CONFIG.systemPrompt.length}字符)` : '不存在',
      llmApiUrl: CONFIG?.llmApiUrl,
      llmModel: CONFIG?.llmModel
    });
    
    // 验证CONFIG是否已初始化
    if (!CONFIG || !CONFIG.mcpServerUrl) {
      throw new Error('CONFIG未初始化或MCP服务端URL未配置');
    }
    
    console.log('✅ CONFIG验证通过，开始调用callLLM...');
    const llmResponse = await callLLM(requestData, onStreamChunk);
    console.log('✅ callLLM调用完成，返回值类型:', typeof llmResponse, '长度:', llmResponse?.length || 0);
    
    console.log('步骤3: LLM响应流式接收完成，长度:', llmResponse?.length || 0);
    console.log('LLM响应内容预览（前200字符）:', llmResponse?.substring(0, 200) || '(空)');
    
    if (!llmResponse || llmResponse.trim() === '') {
      console.error('错误：LLM响应为空！');
      finalizeStreamingMessage();
      showError('LLM返回空响应，请重试或检查服务状态');
      // 确保发送按钮可用（虽然finally块也会执行，但这里明确调用更安全）
      isGenerating = false;
      currentAbortController = null;
      setStopButtonState(false);
      return;
    }
    
    // 保存流式过程中累积的思考内容和结论内容，以便在最终解析时使用
    const finalThinkingContent = thinkingContent;
    const finalConclusionContent = conclusionContent;
    
    // 在收到响应后，将用户输入和文件信息添加到历史中（此时请求已完成）
    // 注意：fullUserMessage 已在try块外定义，直接使用即可
    // 添加完整的用户消息到历史
    if (fullUserMessage) {
      // 收集当前请求中的文件ID
      const currentFileIds = [];
      
      // 从首页上传的文件ID
      if (window.uploadedFileIds && Array.isArray(window.uploadedFileIds)) {
        currentFileIds.push(...window.uploadedFileIds);
      }
      
      // 从pendingFiles中获取已上传的文件ID
      for (const fileData of pendingFiles) {
        if (fileData.fileInfo && fileData.fileInfo.file_id) {
          if (!fileData.fileInfo.file_id.startsWith('temp_')) {
            currentFileIds.push(fileData.fileInfo.file_id);
          }
        }
      }
      
      // 构建用户消息对象，包含文件ID
      const userMessage = {
        role: 'user',
        content: fullUserMessage
      };
      
      // 如果有文件ID，添加到消息对象中
      if (currentFileIds.length > 0) {
        userMessage.file_ids = currentFileIds;
        console.log('📤 用户消息包含文件ID:', currentFileIds);
      }
      
      currentSession.conversationHistory.push(userMessage);
      
      // 同时保存到服务端（后台执行，不阻塞）
      // 注意：服务端可能不支持file_ids字段，所以只保存content
      addMessageToServer(currentSession.sessionId, 'user', fullUserMessage).catch(err => {
        console.error('⚠️ 保存用户消息到服务端失败（后台执行）:', err);
      });
      console.log('📤 用户输入和文件信息已添加到历史（请求完成后）');
    }
    
    console.log('步骤4: 解析和处理响应');
    console.log('保存的思考内容长度:', finalThinkingContent.length);
    console.log('保存的结论内容长度:', finalConclusionContent.length);
    
    // 解析响应（传入流式过程中提取的思考内容和结论内容）
    // 注意：finalizeStreamingMessage会在parseAndHandleResponse内部适当的时候调用
    await parseAndHandleResponse(llmResponse, true, finalThinkingContent, finalConclusionContent);
    
    console.log('=== 处理完成 ===');
    // 确保发送按钮可用（虽然finally块也会执行，但这里明确调用更安全）
    isGenerating = false;
    currentAbortController = null;
    setStopButtonState(false);
    
  } catch (error) {
    console.error('=== 处理用户输入失败 ===');
    console.error('错误详情:', error);
    console.error('错误堆栈:', error.stack);
    console.error('错误类型:', error.name);
    console.error('错误消息:', error.message);
    
    // 错误时重置按钮状态
    isGenerating = false;
    currentAbortController = null;
    setStopButtonState(false);
    
    // 移除流式消息（如果存在）
    finalizeStreamingMessage();
    
    let errorMessage = error.message;
    
    // 根据错误类型提供更友好的提示
    if (errorMessage.includes('无法连接')) {
      errorMessage = '网络连接失败，请检查：\n1. MCP服务是否已启动（端口8000）\n2. 网络连接是否正常\n3. 防火墙设置';
    } else if (errorMessage.includes('API认证失败') || errorMessage.includes('API Key')) {
      errorMessage = 'LLM API配置错误，请检查config.json中的api_key配置';
    } else if (errorMessage.includes('超时')) {
      errorMessage = '请求超时，请稍后重试或检查服务状态';
    }
    
    showError('处理失败: ' + errorMessage);
    updateStatus('错误', 'disconnected');
  } finally {
    // 重置处理标记，确保无论函数如何退出，标记都会被重置
    isProcessingInput = false;
    console.log('✅ handleUserInput处理完成，已重置isProcessingInput标记');
    
    // 恢复加载状态（setLoadingState会在内部调用updateSendButtonState来根据输入状态更新按钮）
    setLoadingState(false);
    
    currentSession.updatedAt = new Date().toISOString();
    await saveSession(currentSession);
  }
};

// 注意：handleUserInput已经在第1150行通过 window.handleUserInput = async function() 定义
// 不需要再次赋值

// 设置加载状态
function setLoadingState(loading) {
  console.log('setLoadingState被调用，loading:', loading);
  
  if (!elements.sendBtn) {
    console.error('setLoadingState: sendBtn元素不存在');
    return;
  }
  
  try {
    if (loading) {
      // 加载中：禁用按钮并显示加载状态
      elements.sendBtn.disabled = true;
      elements.sendBtn.innerHTML = '<span class="loading-spinner"></span> 发送中...';
      elements.sendBtn.classList.add('loading');
      console.log('加载状态已设置：发送中...');
    } else {
      // 加载完成：恢复为发送按钮（图标样式），但根据输入状态决定是否禁用
      elements.sendBtn.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M2 21L23 12L2 3V10L17 12L2 14V21Z" fill="currentColor"/>
        </svg>
      `;
      elements.sendBtn.classList.remove('loading');
      console.log('加载状态已重置：发送');
      
      // 根据当前输入状态更新按钮禁用状态
      // 使用setTimeout确保在状态重置后执行
      setTimeout(() => {
        if (typeof window.updateSendButtonState === 'function') {
          window.updateSendButtonState();
        }
      }, 0);
    }
  } catch (error) {
    console.error('setLoadingState错误:', error);
  }
}

// 设置停止生成按钮状态
function setStopButtonState(isStopping) {
  console.log('setStopButtonState被调用，isStopping:', isStopping);
  
  if (!elements.sendBtn) {
    console.error('setStopButtonState: sendBtn元素不存在');
    return;
  }
  
  try {
    if (isStopping) {
      // 切换到"停止生成"按钮样式
      elements.sendBtn.innerHTML = `
        <span class="stop-button-text">停止生成</span>
        <svg class="stop-button-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>
        </svg>
      `;
      elements.sendBtn.classList.add('stop-generating');
      elements.sendBtn.classList.remove('loading');
      elements.sendBtn.disabled = false; // 允许点击停止
      elements.sendBtn.onclick = stopGeneration;
      console.log('按钮已切换为：停止生成');
    } else {
      // 恢复为发送按钮（图标样式）
      elements.sendBtn.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M2 21L23 12L2 3V10L17 12L2 14V21Z" fill="currentColor"/>
        </svg>
      `;
      elements.sendBtn.classList.remove('stop-generating');
      elements.sendBtn.onclick = () => {
        // 使用箭头函数包装，避免事件对象被传递给handleUserInput
        if (typeof handleUserInput === 'function') {
          handleUserInput();
        } else if (typeof window.handleUserInput === 'function') {
          window.handleUserInput();
        }
      };
      console.log('按钮已恢复为：发送');
      
      // 根据当前输入状态更新按钮禁用状态
      // 使用setTimeout确保在状态重置后执行
      setTimeout(() => {
        if (typeof window.updateSendButtonState === 'function') {
          window.updateSendButtonState();
        } else {
          // 如果函数不存在，至少启用按钮（由后续的updateSendButtonState更新）
          elements.sendBtn.disabled = false;
        }
      }, 0);
    }
  } catch (error) {
    console.error('setStopButtonState错误:', error);
  }
}

// 停止生成函数（全局可访问）
window.stopGeneration = function stopGeneration() {
  console.log('停止生成被调用');
  
  if (currentAbortController) {
    console.log('正在取消请求...');
    // 先清空currentAbortController，标记为用户主动停止
    // 这样在callLLM的catch块中就能正确判断是用户主动停止还是超时
    const controller = currentAbortController;
    currentAbortController = null;
    controller.abort();
    isGenerating = false;
    isProcessingInput = false; // 重置处理标记
    
    // 恢复发送按钮（会调用updateSendButtonState更新状态）
    setStopButtonState(false);
    
    // 更新状态
    updateStatus('已停止生成', 'connected');
    
    // 如果当前有流式消息，标记为已停止
    const messages = document.querySelectorAll('.message.assistant.streaming');
    messages.forEach(msg => {
      msg.classList.remove('streaming');
      msg.classList.add('stopped');
    });
    
    console.log('✅ 生成已停止');
  } else {
    console.warn('没有活动的请求可以停止');
  }
}

// 显示加载消息
function showLoadingMessage() {
  const loadingId = 'loading_' + Date.now();
  const loadingDiv = document.createElement('div');
  loadingDiv.id = loadingId;
  loadingDiv.className = 'message assistant loading-message';
  
  const headerDiv = document.createElement('div');
  headerDiv.className = 'message-header';
  headerDiv.innerHTML = '⚖️ LegalMind';
  
  const contentDiv = document.createElement('div');
  contentDiv.className = 'message-content loading-content';
  contentDiv.innerHTML = '<span class="loading-dots"><span>.</span><span>.</span><span>.</span></span> 正在思考中';
  
  loadingDiv.appendChild(headerDiv);
  loadingDiv.appendChild(contentDiv);
  
  elements.chatMessages.appendChild(loadingDiv);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  
  return loadingId;
}

// 移除加载消息
function removeLoadingMessage(loadingId) {
  const loadingElement = document.getElementById(loadingId);
  if (loadingElement) {
    loadingElement.remove();
  }
}

// 解析和处理响应
async function parseAndHandleResponse(response, isStreamingComplete = false, preservedThinkingContent = '', preservedConclusionContent = '', skipToolInvocation = false) {
  console.log('=== 开始解析响应 ===');
  console.log('响应长度:', response?.length || 0);
  console.log('响应前200字符:', response?.substring(0, 200));
  console.log('保留的思考内容长度:', preservedThinkingContent?.length || 0);
  console.log('保留的结论内容长度:', preservedConclusionContent?.length || 0);
  console.log('跳过工具/资源调用:', skipToolInvocation);
  
  if (!response || !response.trim()) {
    console.error('响应为空');
    // 如果流式过程中有思考内容，显示它
    if (preservedThinkingContent && preservedThinkingContent.trim()) {
      if (currentStreamingMessage) {
      finalizeStreamingMessage();
      }
      addCombinedMessage(preservedThinkingContent, '响应为空');
    } else {
      if (currentStreamingMessage) {
        finalizeStreamingMessage();
      }
      addMessage('assistant', '收到空响应，请重试', 'error');
    }
    return;
  }
  
  // 如果流式过程中已经提取了思考内容和结论内容，优先使用它们
  let thinkingContent = preservedThinkingContent || '';
  let conclusionContent = preservedConclusionContent || '';
  let jsonContent = '';
  let hasSeparator = false;
  
  // 查找分隔符（如果之前没有找到，再试一次）
  // 使用 "==JSON==" 作为分隔符来区分思考内容和结论内容
  const separator = '==JSON==';
  const separatorIndex = response.indexOf(separator);
  
  if (separatorIndex !== -1) {
    hasSeparator = true;
    // 如果之前没有提取到思考内容，现在提取
    if (!thinkingContent) {
    thinkingContent = response.substring(0, separatorIndex).trim();
    }
    jsonContent = response.substring(separatorIndex + separator.length).trim();
    console.log('找到分隔符，思考内容长度:', thinkingContent.length);
    console.log('JSON内容长度:', jsonContent.length);
  } else {
    // 没有分隔符，整个响应可能是JSON或纯文本
    jsonContent = response.trim();
    console.log('未找到分隔符，直接使用整个响应');
    // 如果之前没有思考内容，且没有分隔符，说明整个响应可能就是结论
    if (!thinkingContent) {
      console.log('没有找到分隔符，也没有保留的思考内容，整个响应作为结论');
    } else if (thinkingContent.trim() === response.trim()) {
      // 避免思考与结论重复显示
      console.log('⚠️ 思考内容与完整响应一致，避免重复显示结论');
    }
  }
  
  // 尝试解析JSON
  let responseData = null;
  try {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1759',message:'开始解析JSON',data:{jsonContentLength:jsonContent.length,hasSeparator,thinkingContentLength:thinkingContent.length},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'A'})}).catch(()=>{});
    // #endregion
    // 尝试从响应中提取JSON
    const jsonMatch = jsonContent.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      console.log('找到JSON，尝试解析...');
      responseData = JSON.parse(jsonMatch[0]);
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1764',message:'JSON解析成功',data:{type:responseData.type,Type:responseData.Type,hasResourceUri:!!responseData.resource_uri,hasToolName:!!responseData.tool_name,responseDataKeys:Object.keys(responseData)},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'A'})}).catch(()=>{});
      // #endregion
      console.log('JSON解析成功，type:', responseData.type, 'Type:', responseData.Type);
    } else {
      console.log('未找到JSON，直接显示响应');
      // 如果没有JSON，直接显示为合并消息（可能是直接回答）
      let finalContent = hasSeparator && thinkingContent ? jsonContent : response;
      if (!hasSeparator && thinkingContent && thinkingContent.trim() === response.trim()) {
        finalContent = '';
      }
      // 移除流式消息，显示最终消息
      finalizeStreamingMessage();
      addCombinedMessage(thinkingContent, finalContent || (thinkingContent ? '' : '无结论内容'));
      
      // 保存到服务端和本地历史
      const fullContent = hasSeparator ? `${thinkingContent}\n\n${finalContent}` : finalContent;
      await addMessageToServer(currentSession.sessionId, 'assistant', fullContent);
      currentSession.conversationHistory.push({
        role: 'assistant',
        content: fullContent
      });
      return;
    }
  } catch (e) {
    console.error('JSON解析失败:', e);
    console.error('尝试解析的内容:', jsonContent.substring(0, 500));
    // 解析失败，直接显示为合并消息
    let finalContent = hasSeparator && thinkingContent ? jsonContent : response;
    if (!hasSeparator && thinkingContent && thinkingContent.trim() === response.trim()) {
      finalContent = '';
    }
    // 移除流式消息，显示最终消息（addCombinedMessage内部也会检查并移除）
    if (currentStreamingMessage) {
    finalizeStreamingMessage();
    }
    addCombinedMessage(thinkingContent, finalContent || (thinkingContent ? '' : '响应解析失败'));
    
    // 保存到服务端和本地历史
    const fullContent = hasSeparator ? `${thinkingContent}\n\n${finalContent}` : finalContent;
    await addMessageToServer(currentSession.sessionId, 'assistant', fullContent);
    currentSession.conversationHistory.push({
      role: 'assistant',
      content: fullContent
    });
    return;
  }
  
  // 移除流式消息，准备显示最终消息（只移除一次，确保不会重复移除）
  if (currentStreamingMessage) {
  finalizeStreamingMessage();
  }
  
  // 检查响应类型，如果是需要调用资源/工具/提示词模板的类型，先调用，不直接显示结论
  // 支持多种格式：
  // 格式1: responseData.type === 'invoke_tool_or_resource'
  // 格式2: responseData.Type === 'invoke_tool_or_resource' (大小写变体)
  // 格式3: responseData.type === 7 且 lawQaText 包含 Type: 'invoke_tool_or_resource'
  const responseType = responseData.type || responseData.Type;
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1813',message:'检查响应类型',data:{responseType,skipToolInvocation,type:responseData.type,Type:responseData.Type,hasLawQaText:!!(responseData.data&&responseData.data.lawQaText)},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'A'})}).catch(()=>{});
  // #endregion
  
  // 如果skipToolInvocation为true，说明已经在资源/工具调用流程中，不再重复调用
  if (!skipToolInvocation) {
    // 首先检查格式1和格式2（直接格式）
  if (responseType === 'invoke_tool_or_resource' || responseType === 'invoke_tool' || responseType === 'invoke_prompt') {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1818',message:'检测到invoke_tool_or_resource类型（直接格式）',data:{responseType},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'A'})}).catch(()=>{});
      // #endregion
      console.log('🔧 检测到需要调用资源/工具/提示词模板（直接格式），不直接显示结论，先调用相关资源');
      // 构建标准格式的responseData
      const invokeResponseData = {
        type: 'invoke_tool_or_resource',
        action: responseData.action || null,
        resource_uri: responseData.resource_uri || responseData.resourceUri || null,
        tool_name: responseData.tool_name || responseData.toolName || null,
        prompt_template: responseData.prompt_template || responseData.promptTemplate || responseData.prompt_name || responseData.promptName || null,
        prompt_name: responseData.prompt_name || responseData.promptName || null,
        parameters: responseData.parameters || responseData.params || {}
      };
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1828',message:'构建invokeResponseData',data:{resource_uri:invokeResponseData.resource_uri,tool_name:invokeResponseData.tool_name,hasParameters:Object.keys(invokeResponseData.parameters).length>0},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'B'})}).catch(()=>{});
      // #endregion
      console.log('🔧 解析后的调用参数:', invokeResponseData);
    // 不显示结论内容，直接调用资源
      await handleResponseByType(invokeResponseData, thinkingContent, conclusionContent);
    return;
  }
    
    // 检查格式3: 如果解析的JSON中包含Type字段（可能是分隔符格式）
    if (responseData.Type === 'invoke_tool_or_resource' || responseData.type === 'invoke_tool_or_resource') {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1835',message:'检测到Type字段格式的invoke_tool_or_resource',data:{},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'A'})}).catch(()=>{});
      // #endregion
      console.log('🔧 检测到需要调用资源/工具/提示词模板（Type字段格式），不直接显示结论，先调用相关资源');
      // 尝试从jsonContent中解析（可能是完整的JSON字符串）
      const invokeInfo = parseInvokeToolOrResource(jsonContent);
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1838',message:'parseInvokeToolOrResource结果',data:{hasInvokeInfo:!!invokeInfo,resource_uri:invokeInfo?.resource_uri,tool_name:invokeInfo?.tool_name},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'B'})}).catch(()=>{});
      // #endregion
      if (invokeInfo) {
        const invokeResponseData = {
          type: 'invoke_tool_or_resource',
          action: invokeInfo.action || null,
          resource_uri: invokeInfo.resource_uri,
          tool_name: invokeInfo.tool_name,
          prompt_template: invokeInfo.prompt_template || invokeInfo.prompt_name,
          prompt_name: invokeInfo.prompt_name || null,
          parameters: invokeInfo.parameters
        };
        console.log('🔧 解析后的调用参数:', invokeResponseData);
        await handleResponseByType(invokeResponseData, thinkingContent, conclusionContent);
        return;
      }
  }
  
  // 对于type: 7格式，优先使用流式提取的结论内容（因为流式过程中已经收到了完整的lawQaText）
  if ((responseData.type === 7 || responseData.type === '7') && responseData.data && responseData.data.lawQaText) {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1854',message:'检测到type:7格式',data:{hasLawQaText:!!responseData.data.lawQaText,lawQaTextLength:responseData.data.lawQaText.length},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'A'})}).catch(()=>{});
      // #endregion
      // 检查lawQaText中的Type字段，如果是invoke_tool_or_resource，需要调用工具/资源
      const invokeInfo = parseInvokeToolOrResource(responseData.data.lawQaText);
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1856',message:'parseInvokeToolOrResource结果（type:7）',data:{hasInvokeInfo:!!invokeInfo,resource_uri:invokeInfo?.resource_uri,tool_name:invokeInfo?.tool_name},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'B'})}).catch(()=>{});
      // #endregion
      if (invokeInfo) {
        console.log('🔧 检测到invoke_tool_or_resource类型（type:7格式），准备调用工具/资源');
        // 构建responseData对象，用于调用handleResourceInvocation或handleToolInvocation
        const invokeResponseData = {
          type: 'invoke_tool_or_resource',
          action: invokeInfo.action || null,
          resource_uri: invokeInfo.resource_uri,
          tool_name: invokeInfo.tool_name,
          prompt_template: invokeInfo.prompt_template || invokeInfo.prompt_name,
          prompt_name: invokeInfo.prompt_name || null,
          parameters: invokeInfo.parameters
        };
        console.log('🔧 解析后的调用参数:', invokeResponseData);
        // 调用资源/工具处理函数
        await handleResponseByType(invokeResponseData, thinkingContent, '');
        return;
      }
    }
  } else {
    console.log('⚠️ 已在资源/工具调用流程中，跳过重复的资源/工具调用检测');
  }
  
    // 如果流式提取的结论内容为空，使用responseData中的结论
    if (!conclusionContent || !conclusionContent.trim()) {
      // 从lawQaText中提取prompt_to_user或conclusion字段
    // 检查responseData.data是否存在，避免访问undefined的属性
    try {
      if (responseData && responseData.data && responseData.data.lawQaText) {
        const extracted = extractConclusionFromLawQaText(responseData.data.lawQaText);
        // 如果返回null，说明是invoke_tool_or_resource类型（已在上面处理）
        if (extracted === null) {
          return;
        }
        conclusionContent = extracted;
      console.log('从responseData.data.lawQaText中提取结论内容，长度:', conclusionContent.length);
      } else {
        // 如果没有lawQaText，尝试从其他字段提取结论
        console.log('⚠️ responseData.data或lawQaText不存在，尝试从其他字段提取结论');
        const readableConclusion = extractReadableConclusion(responseData);
        if (readableConclusion) {
          conclusionContent = readableConclusion;
        }
      }
    } catch (error) {
      console.error('访问lawQaText时出错:', error);
      console.error('responseData:', responseData);
      console.error('responseData.data:', responseData?.data);
      // 尝试从其他字段提取结论
      const readableConclusion = extractReadableConclusion(responseData);
      if (readableConclusion) {
        conclusionContent = readableConclusion;
      }
    }
    } else {
      // 流式提取的内容已经处理过了，直接使用
      console.log('使用流式提取的结论内容（type:7格式），长度:', conclusionContent.length);
  }
  
  // 如果流式过程中已经提取了结论内容，优先使用它，直接显示合并消息
  if (conclusionContent && conclusionContent.trim()) {
    console.log('✅ 使用流式提取的结论内容显示最终消息，思考内容长度:', thinkingContent.length, '结论长度:', conclusionContent.length);
    addCombinedMessage(thinkingContent, conclusionContent);
    const fullContent = thinkingContent && thinkingContent.trim() 
      ? `${thinkingContent}\n\n${conclusionContent}` 
      : conclusionContent;
    await addMessageToServer(currentSession.sessionId, 'assistant', fullContent);
    currentSession.conversationHistory.push({
      role: 'assistant',
      content: fullContent
    });
    console.log('✅ 最终消息已添加到DOM');
    return; // 确保return，不会继续执行下面的代码
  }
  
  // 如果没有流式提取的结论内容，根据类型处理响应，传入thinkingContent以便合并显示
  console.log('⚠️ 没有流式提取的结论内容，调用handleResponseByType，type:', responseData.type, '思考内容长度:', thinkingContent.length);
  await handleResponseByType(responseData, thinkingContent, conclusionContent);
  console.log('响应处理完成');
}

// 根据类型处理响应
async function handleResponseByType(responseData, thinkingContent = '', conclusionContent = '') {
  console.log('=== handleResponseByType 被调用 ===');
  console.log('响应类型:', responseData.type);
  console.log('思考内容长度:', thinkingContent.length);
  console.log('结论内容长度:', conclusionContent.length);
  console.log('响应数据预览:', JSON.stringify(responseData, null, 2).substring(0, 500));
  
  const type = responseData.type;
  console.log('处理响应类型:', type);
  
  switch (type) {
    case 'error_intent_unknown':
      addCombinedMessage(thinkingContent, responseData.prompt_to_user || responseData.error);
      await addMessageToServer(currentSession.sessionId, 'assistant', responseData.prompt_to_user || responseData.error);
      currentSession.conversationHistory.push({
        role: 'assistant',
        content: responseData.prompt_to_user || responseData.error
      });
      break;
      
    case 'missing_parameters':
      currentSession.missingParameters = responseData.missing_parameters || [];
      currentSession.currentIntent = responseData.intent;
      addCombinedMessage(thinkingContent, responseData.prompt_to_user);
      await addMessageToServer(currentSession.sessionId, 'assistant', responseData.prompt_to_user);
      currentSession.conversationHistory.push({
        role: 'assistant',
        content: responseData.prompt_to_user
      });
      // 显示参数选择（如果有枚举值）
      await showParameterSelection(responseData.missing_parameters, responseData.intent);
      break;
      
    case 'direct_answer':
      // 如果有流式提取的结论内容，优先使用它；否则使用responseData中的结论
      const directConclusion = conclusionContent && conclusionContent.trim()
        ? conclusionContent
        : (responseData.conclusion || '');
      addCombinedMessage(thinkingContent, directConclusion);
      const directFullContent = thinkingContent && thinkingContent.trim()
        ? `${thinkingContent}\n\n${directConclusion}`
        : directConclusion;
      await addMessageToServer(currentSession.sessionId, 'assistant', directFullContent);
      currentSession.conversationHistory.push({
        role: 'assistant',
        content: directFullContent
      });
      break;
      
    case 'invoke_tool_or_resource':
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1964',message:'进入invoke_tool_or_resource case',data:{resource_uri:responseData.resource_uri,tool_name:responseData.tool_name,prompt_template:responseData.prompt_template,hasParameters:!!responseData.parameters},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'B'})}).catch(()=>{});
      // #endregion
      // 不显示结论内容，直接调用资源或工具
      console.log('🔧 invoke_tool_or_resource: 调用资源/工具，不显示中间结论');
      console.log('资源URI:', responseData.resource_uri);
      console.log('工具名称:', responseData.tool_name);
      console.log('提示词模板:', responseData.prompt_template);
      console.log('参数:', responseData.parameters);
      
      // 如果明确是提示词模板调用，优先处理
      if (responseData.action === 'invoke_prompt' || responseData.prompt_template || responseData.prompt_name) {
        // ✅ 如果是提示词模板，应该调用 prompts/get 方法，而不是 resources/read
        console.log('🔧 检测到提示词模板，调用 handlePromptInvocation');
        await handlePromptInvocation({
          ...responseData,
          prompt_name: responseData.prompt_name || responseData.prompt_template,
          prompt_template: responseData.prompt_template
        }, thinkingContent, conclusionContent);
      } else if (responseData.resource_uri) {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1973',message:'准备调用handleResourceInvocation',data:{resource_uri:responseData.resource_uri},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'C'})}).catch(()=>{});
      // #endregion
      await handleResourceInvocation(responseData, thinkingContent, conclusionContent);
      } else if (responseData.tool_name) {
        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1975',message:'准备调用handleToolInvocation',data:{tool_name:responseData.tool_name},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'C'})}).catch(()=>{});
        // #endregion
        await handleToolInvocation(responseData, thinkingContent, conclusionContent);
      } else {
        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:1984',message:'缺少必要参数',data:{hasResourceUri:!!responseData.resource_uri,hasToolName:!!responseData.tool_name,hasPromptTemplate:!!responseData.prompt_template},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'C'})}).catch(()=>{});
        // #endregion
        console.error('invoke_tool_or_resource类型缺少必要的参数（resource_uri、tool_name或prompt_template）');
        addCombinedMessage(thinkingContent, '错误：缺少调用资源/工具的必要参数');
        await addMessageToServer(currentSession.sessionId, 'assistant', '错误：缺少调用资源/工具的必要参数');
        currentSession.conversationHistory.push({
          role: 'assistant',
          content: '错误：缺少调用资源/工具的必要参数'
        });
      }
      break;

    case 'start_workflow':
      console.log('🔧 start_workflow: 执行工作流步骤');
      await executeWorkflowSteps(responseData, thinkingContent, conclusionContent);
      break;
      
    case 'resource_response':
      // 资源已返回，继续处理
      currentSession.contextCache[responseData.resource_uri] = responseData.data;
      break;
      
    case 'llm_generated_result':
      // 如果有流式提取的结论内容，优先使用它；否则使用responseData中的结论
      const finalConclusion = conclusionContent && conclusionContent.trim()
        ? conclusionContent
        : (responseData.conclusion || '');
      addCombinedMessage(thinkingContent, finalConclusion);
      const fullContent = thinkingContent && thinkingContent.trim()
        ? `${thinkingContent}\n\n${finalConclusion}`
        : finalConclusion;
      await addMessageToServer(currentSession.sessionId, 'assistant', fullContent);
      currentSession.conversationHistory.push({
        role: 'assistant',
        content: fullContent
      });
      currentSession.stage = 'completed';
      break;
      
    case 'session_end':
      currentSession.status = responseData.status;
      addCombinedMessage(thinkingContent, responseData.message);
      await addMessageToServer(currentSession.sessionId, 'assistant', responseData.message);
      currentSession.conversationHistory.push({
        role: 'assistant',
        content: responseData.message
      });
      break;
      
    default:
      // 尝试从responseData中提取可读的结论内容，而不是直接显示JSON
      const readableConclusion = extractReadableConclusion(responseData);
      if (readableConclusion) {
        addCombinedMessage(thinkingContent, readableConclusion);
        const fullContent = thinkingContent && thinkingContent.trim()
          ? `${thinkingContent}\n\n${readableConclusion}`
          : readableConclusion;
        await addMessageToServer(currentSession.sessionId, 'assistant', fullContent);
      currentSession.conversationHistory.push({
        role: 'assistant',
          content: fullContent
        });
      } else {
        // 如果无法提取可读内容，显示一个友好的提示而不是JSON
        const fallbackMessage = `收到未知类型的响应（类型: ${responseData.type || 'unknown'}），无法解析内容。`;
        addCombinedMessage(thinkingContent, fallbackMessage);
        const fullContent = thinkingContent && thinkingContent.trim()
          ? `${thinkingContent}\n\n${fallbackMessage}`
          : fallbackMessage;
        await addMessageToServer(currentSession.sessionId, 'assistant', fullContent);
        currentSession.conversationHistory.push({
          role: 'assistant',
          content: fullContent
        });
      }
  }
}

// 添加工具/资源调用信息展示
function addToolInvocationMessage(type, name, parameters, status = 'calling', result = null) {
  if (!elements.chatMessages) {
    console.error('chatMessages元素不存在，无法添加调用信息');
    return null;
  }
  
  const messageWrapper = document.createElement('div');
  messageWrapper.className = 'message assistant tool-invocation-message';
  messageWrapper.id = 'tool-invocation-' + Date.now();
  
  const headerDiv = document.createElement('div');
  headerDiv.className = 'message-header';
  
  const headerText = document.createElement('span');
  const typeLabel = type === 'resource' ? '📚 资源调用' : type === 'tool' ? '🔧 工具调用' : '📝 提示词调用';
  headerText.textContent = typeLabel;
  headerDiv.appendChild(headerText);
  
  messageWrapper.appendChild(headerDiv);
  
  // 调用信息卡片
  const infoCard = document.createElement('div');
  infoCard.className = 'tool-invocation-card';
  
  // 调用名称/URI
  const nameDiv = document.createElement('div');
  nameDiv.className = 'tool-invocation-name';
  nameDiv.innerHTML = `<strong>${type === 'resource' ? '资源URI' : type === 'tool' ? '工具名称' : '提示词'}:</strong> <code>${name}</code>`;
  infoCard.appendChild(nameDiv);
  
  // 调用参数
  if (parameters && Object.keys(parameters).length > 0) {
    const paramsDiv = document.createElement('div');
    paramsDiv.className = 'tool-invocation-params';
    paramsDiv.innerHTML = `<strong>调用参数:</strong>`;
    const paramsPre = document.createElement('pre');
    paramsPre.className = 'tool-invocation-params-content';
    paramsPre.textContent = JSON.stringify(parameters, null, 2);
    paramsDiv.appendChild(paramsPre);
    infoCard.appendChild(paramsDiv);
  }
  
  // 调用状态/结果
  const resultDiv = document.createElement('div');
  resultDiv.className = 'tool-invocation-result';
  
  if (status === 'calling') {
    resultDiv.innerHTML = '<strong>状态:</strong> <span class="status-calling">正在调用...</span>';
  } else if (status === 'success') {
    resultDiv.innerHTML = '<strong>调用结果:</strong>';
    const resultPre = document.createElement('pre');
    resultPre.className = 'tool-invocation-result-content';
    // 如果结果是对象，格式化显示；否则直接显示
    if (typeof result === 'object') {
      resultPre.textContent = JSON.stringify(result, null, 2);
    } else {
      resultPre.textContent = result || '(空)';
    }
    resultDiv.appendChild(resultPre);
  } else if (status === 'error') {
    resultDiv.innerHTML = `<strong>调用失败:</strong> <span class="status-error">${result || '未知错误'}</span>`;
  }
  
  infoCard.appendChild(resultDiv);
  messageWrapper.appendChild(infoCard);
  
  elements.chatMessages.appendChild(messageWrapper);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  
  return messageWrapper;
}

// 更新工具/资源调用信息（用于更新状态和结果）
function updateToolInvocationMessage(messageWrapper, status, result = null) {
  if (!messageWrapper) return;
  
  const resultDiv = messageWrapper.querySelector('.tool-invocation-result');
  if (!resultDiv) return;
  
  if (status === 'success') {
    resultDiv.innerHTML = '<strong>调用结果:</strong>';
    const resultPre = document.createElement('pre');
    resultPre.className = 'tool-invocation-result-content';
    if (typeof result === 'object') {
      resultPre.textContent = JSON.stringify(result, null, 2);
    } else {
      resultPre.textContent = result || '(空)';
    }
    resultDiv.appendChild(resultPre);
  } else if (status === 'error') {
    resultDiv.innerHTML = `<strong>调用失败:</strong> <span class="status-error">${result || '未知错误'}</span>`;
  }
  
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

// 处理资源调用
async function handleResourceInvocation(responseData, thinkingContent = '', conclusionContent = '') {
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:2153',message:'handleResourceInvocation被调用',data:{resource_uri:responseData.resource_uri,hasParameters:!!responseData.parameters},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'C'})}).catch(()=>{});
  // #endregion
  console.log('=== handleResourceInvocation 被调用 ===');
  const resourceUri = responseData.resource_uri;
  const parameters = responseData.parameters || {};
  
  console.log('资源URI:', resourceUri);
  console.log('参数:', parameters);
  
  // 检查参数是否齐全
  if (!resourceUri) {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:2162',message:'资源URI缺失',data:{resource_uri:resourceUri},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'C'})}).catch(()=>{});
    // #endregion
    console.error('资源URI缺失，无法调用');
    addCombinedMessage(thinkingContent, '错误：缺少资源URI，无法调用资源');
    return;
  }
  
  // 在调用前展示参数
  const invocationMessage = addToolInvocationMessage('resource', resourceUri, parameters, 'calling');
  rememberMcpCapability(resourceUri, MCP_CAPABILITY_LABELS[resourceUri], 'resource');
  
  // 默认自动批准工具调用
  const autoApprove = true;
  
  if (!autoApprove) {
    // 显示批准弹窗
    const approved = await showToolApproval(resourceUri, parameters);
    if (!approved) {
      if (invocationMessage) {
        updateToolInvocationMessage(invocationMessage, 'error', '用户拒绝了资源调用请求');
      }
      addCombinedMessage(thinkingContent, '用户拒绝了资源调用请求');
      await addMessageToServer(currentSession.sessionId, 'assistant', '用户拒绝了资源调用请求');
      currentSession.conversationHistory.push({
        role: 'assistant',
        content: '用户拒绝了资源调用请求'
      });
      return;
    }
  }
  
  try {
    // 显示加载状态
    updateStatus('正在调用资源...', 'connecting');
    
    // 调用MCP资源
    console.log('调用MCP资源:', resourceUri);
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:2196',message:'准备发送MCP请求',data:{resourceUri,parameters:Object.keys(parameters)},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'D'})}).catch(()=>{});
    // #endregion
    const resourceResponse = await sendMCPRequest({
      method: 'resources/read',
      params: {
        uri: resourceUri,
        arguments: parameters
      }
    });
    
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:2204',message:'MCP请求返回',data:{hasError:!!resourceResponse.error,hasResult:!!resourceResponse.result,errorMessage:resourceResponse.error?.message},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'D'})}).catch(()=>{});
    // #endregion
    
    if (resourceResponse.error) {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:2206',message:'MCP请求返回错误',data:{errorMessage:resourceResponse.error.message},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'D'})}).catch(()=>{});
      // #endregion
      throw new Error(resourceResponse.error.message);
    }
    
    const resourceData = resourceResponse.result.contents[0].text;
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:2210',message:'资源调用成功',data:{resourceDataLength:resourceData.length},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'D'})}).catch(()=>{});
    // #endregion
    console.log('✅ 资源调用成功，数据长度:', resourceData.length);
    
    // 更新调用信息，展示结果
    if (invocationMessage) {
      updateToolInvocationMessage(invocationMessage, 'success', resourceData);
    }
    
    // 缓存资源数据
    currentSession.contextCache[resourceUri] = resourceData;
    
    // 更新状态机：标记资源已调用，进入生成阶段
    currentSession.stage = 'generate_with_llm';
    currentSession.currentIntent = responseData.intent || currentSession.currentIntent;
    console.log('✅ 状态机已更新: stage = generate_with_llm, resource_uri =', resourceUri);
    
    // 获取用户原始输入
    const lastUserMessage = currentSession.conversationHistory
      .filter(m => m.role === 'user')
      .pop()?.content || '';
    
    // 构建 resource_response 格式的 JSON
    const resourceResponseData = {
      type: 'resource_response',
      intent: responseData.intent || currentSession.currentIntent || '法规检索',
      resource_uri: resourceUri,
      data: resourceData,
      next_stage: 'generate_with_llm'
    };
    
    // 如果存在工作流信息，添加到 resource_response 中
    if (responseData.workflow_id) {
      resourceResponseData.workflow_id = responseData.workflow_id;
    }
    if (responseData.current_step !== undefined) {
      resourceResponseData.step = responseData.current_step + 1;
    }
    if (responseData.workflow_intent) {
      resourceResponseData.workflow_intent = responseData.workflow_intent;
    }
    
    // 将 resource_response 格式的 JSON 追加到用户输入中，让 LLM 识别为工作流延续
    const resourceResponseJson = JSON.stringify(resourceResponseData, null, 2);
    const enhancedUserMessage = lastUserMessage 
      ? `${lastUserMessage}\n\n[资源响应]\n${resourceResponseJson}`
      : `[资源响应]\n${resourceResponseJson}`;
    
    console.log('📦 将资源调用结果包装为 resource_response 格式:', resourceResponseJson);
    
    // 继续调用LLM生成最终结果（使用流式输出）
    console.log('🔄 资源已获取，继续调用LLM生成最终结果...');
    updateStatus('正在生成最终结论...', 'connecting');
    
    // 构建 system 消息，提示模型当前阶段
    const systemMessage = `你已成功获取资源 '${resourceUri}' 的内容。请根据资源内容继续处理用户请求。不要再次请求调用该资源。`;
    
    // 使用 afterInvocation 模式：将用户输入添加到历史对话，使用 system 消息替代 user_input
    const requestData = buildRequestData(enhancedUserMessage, {
      afterInvocation: true,
      invocationType: 'resource',
      invocationName: resourceUri,
      systemMessage: systemMessage
    });
    
    // 同时保留 invokeDetail 以兼容服务端逻辑
    requestData.invokeDetail = {
      type: 'resource',
      name: resourceUri,
      parameters: parameters,
      result: resourceData,
      completed: true
    };
    
    // 初始化流式消息容器
    const streamingMsg = addStreamingMessage();
    let accumulatedContent = '';
    let finalThinkingContent = thinkingContent || '';
    let finalConclusionContent = '';
    
    // 流式回调函数
    const onStreamChunk = (content, reasoningText = null, lawText = null) => {
      accumulatedContent = content;
      
      if (reasoningText !== null || lawText !== null) {
        finalThinkingContent = reasoningText || finalThinkingContent || '';
        if (lawText) {
          // 提取可读内容，避免显示JSON原始文本
          const extracted = extractConclusionFromLawQaText(lawText);
          // 如果提取失败且是JSON字符串，不显示JSON原始文本
          if (extracted === lawText && lawText.trim().startsWith('{')) {
            finalConclusionContent = '';  // 不显示JSON原始文本
          } else {
            finalConclusionContent = extracted;
          }
        }
      } else {
        // 旧格式：从完整内容中解析（使用 ==JSON== 分隔符）
        const separator = '==JSON==';
        const separatorIndex = content.indexOf(separator);
        if (separatorIndex !== -1) {
          finalThinkingContent = content.substring(0, separatorIndex).trim();
          const rawConclusion = content.substring(separatorIndex + separator.length).trim();
          // 尝试解析JSON并提取可读内容，而不是直接显示JSON字符串
          finalConclusionContent = parseJsonAndExtractConclusion(rawConclusion) || rawConclusion;
        } else {
          finalThinkingContent = content;
          finalConclusionContent = '';
        }
      }
      
      updateStreamingMessage(finalThinkingContent, finalConclusionContent);
    };
    
    const llmResponse = await callLLM(requestData, onStreamChunk);
    
    // 解析并处理响应（传入skipToolInvocation=true，避免重复调用资源/工具）
    await parseAndHandleResponse(llmResponse, true, finalThinkingContent, finalConclusionContent, true);
    
  } catch (error) {
    console.error('资源调用失败:', error);
    updateStatus('资源调用失败', 'disconnected');
    
    // 更新调用信息，展示错误
    if (invocationMessage) {
      updateToolInvocationMessage(invocationMessage, 'error', error.message);
    }
    
    addCombinedMessage(thinkingContent, '资源调用失败: ' + error.message);
    await addMessageToServer(currentSession.sessionId, 'assistant', '资源调用失败: ' + error.message);
    currentSession.conversationHistory.push({
      role: 'assistant',
      content: '资源调用失败: ' + error.message
    });
  }
}

// 处理工具调用
async function handleToolInvocation(responseData, thinkingContent = '', conclusionContent = '') {
  console.log('=== handleToolInvocation 被调用 ===');
  const toolName = responseData.tool_name || responseData.name;
  const parameters = responseData.parameters || responseData.arguments || {};
  
  console.log('工具名称:', toolName);
  console.log('参数:', parameters);
  
  // 检查参数是否齐全
  if (!toolName) {
    console.error('工具名称缺失，无法调用');
    addCombinedMessage(thinkingContent, '错误：缺少工具名称，无法调用工具');
    return;
  }
  
  // 在调用前展示参数
  const invocationMessage = addToolInvocationMessage('tool', toolName, parameters, 'calling');
  rememberMcpCapability(toolName, toolName, 'tool');
  
  // 默认自动批准工具调用
  const autoApprove = true;
  
  if (!autoApprove) {
    const approved = await showToolApproval(`tool:${toolName}`, parameters);
    if (!approved) {
      if (invocationMessage) {
        updateToolInvocationMessage(invocationMessage, 'error', '用户拒绝了工具调用请求');
      }
      addCombinedMessage(thinkingContent, '用户拒绝了工具调用请求');
      await addMessageToServer(currentSession.sessionId, 'assistant', '用户拒绝了工具调用请求');
      currentSession.conversationHistory.push({
        role: 'assistant',
        content: '用户拒绝了工具调用请求'
      });
      return;
    }
  }
  
  try {
    updateStatus('正在调用工具...', 'connecting');
    
    // 调用MCP工具
    console.log('调用MCP工具:', toolName);
    const toolResponse = await sendMCPRequest({
      method: 'tools/call',
      params: {
        name: toolName,
        arguments: parameters
      }
    });
    
    if (toolResponse.error) {
      throw new Error(toolResponse.error.message);
    }
    
    const toolResult = toolResponse.result;
    console.log('✅ 工具调用成功');
    
    // 更新调用信息，展示结果
    if (invocationMessage) {
      updateToolInvocationMessage(invocationMessage, 'success', toolResult);
    }
    
    // 更新状态机：标记工具已调用，进入生成阶段
    currentSession.stage = 'generate_with_llm';
    currentSession.currentIntent = responseData.intent || currentSession.currentIntent;
    console.log('✅ 状态机已更新: stage = generate_with_llm, tool_name =', toolName);
    
    // 获取用户原始输入
    const lastUserMessage = currentSession.conversationHistory
      .filter(m => m.role === 'user')
      .pop()?.content || '';
    
    // 构建 resource_response 格式的 JSON（工具调用结果也使用相同格式）
    const resourceResponseData = {
      type: 'resource_response',
      intent: responseData.intent || currentSession.currentIntent || '其他',
      data: {
        tool_result: toolResult,
        tool_name: toolName,
        tool_parameters: parameters
      },
      next_stage: 'generate_with_llm'
    };
    
    // 如果存在工作流信息，添加到 resource_response 中
    if (responseData.workflow_id) {
      resourceResponseData.workflow_id = responseData.workflow_id;
    }
    if (responseData.current_step !== undefined) {
      resourceResponseData.step = responseData.current_step + 1;
    }
    if (responseData.workflow_intent) {
      resourceResponseData.workflow_intent = responseData.workflow_intent;
    }
    
    // 将 resource_response 格式的 JSON 追加到用户输入中，让 LLM 识别为工作流延续
    const resourceResponseJson = JSON.stringify(resourceResponseData, null, 2);
    const enhancedUserMessage = lastUserMessage 
      ? `${lastUserMessage}\n\n[资源响应]\n${resourceResponseJson}`
      : `[资源响应]\n${resourceResponseJson}`;
    
    console.log('📦 将工具调用结果包装为 resource_response 格式:', resourceResponseJson);
    
    // 继续调用LLM生成最终结果（使用流式输出）
    console.log('🔄 工具已调用，继续调用LLM生成最终结果...');
    updateStatus('正在生成最终结论...', 'connecting');
    
    // 构建 system 消息，提示模型当前阶段
    const systemMessage = `你已成功调用工具 '${toolName}'。请根据工具执行结果继续处理用户请求。不要再次请求调用该工具。`;
    
    // 使用 afterInvocation 模式：将用户输入添加到历史对话，使用 system 消息替代 user_input
    const requestData = buildRequestData(enhancedUserMessage, {
      afterInvocation: true,
      invocationType: 'tool',
      invocationName: toolName,
      systemMessage: systemMessage
    });
    
    // 同时保留 invokeDetail 以兼容服务端逻辑
    requestData.invokeDetail = {
      type: 'tool',
      name: toolName,
      parameters: parameters,
      result: toolResult,
      completed: true
    };
    
    // 初始化流式消息容器
    const streamingMsg = addStreamingMessage();
    let accumulatedContent = '';
    let finalThinkingContent = thinkingContent || '';
    let finalConclusionContent = '';
    
    // 流式回调函数
    const onStreamChunk = (content, reasoningText = null, lawText = null) => {
      accumulatedContent = content;
      
      if (reasoningText !== null || lawText !== null) {
        finalThinkingContent = reasoningText || finalThinkingContent || '';
        if (lawText) {
          // 提取可读内容，避免显示JSON原始文本
          const extracted = extractConclusionFromLawQaText(lawText);
          // 如果提取失败且是JSON字符串，不显示JSON原始文本
          if (extracted === lawText && lawText.trim().startsWith('{')) {
            finalConclusionContent = '';  // 不显示JSON原始文本
          } else {
            finalConclusionContent = extracted;
          }
        }
      } else {
        const separator = '==JSON==';
        const separatorIndex = content.indexOf(separator);
        if (separatorIndex !== -1) {
          finalThinkingContent = content.substring(0, separatorIndex).trim();
          const rawConclusion = content.substring(separatorIndex + separator.length).trim();
          // 尝试解析JSON并提取可读内容，而不是直接显示JSON字符串
          finalConclusionContent = parseJsonAndExtractConclusion(rawConclusion) || rawConclusion;
        } else {
          finalThinkingContent = content;
          finalConclusionContent = '';
        }
      }
      
      updateStreamingMessage(finalThinkingContent, finalConclusionContent);
    };
    
    const llmResponse = await callLLM(requestData, onStreamChunk);
    
    // 解析并处理响应（传入skipToolInvocation=true，避免重复调用资源/工具）
    await parseAndHandleResponse(llmResponse, true, finalThinkingContent, finalConclusionContent, true);
    
  } catch (error) {
    console.error('工具调用失败:', error);
    updateStatus('工具调用失败', 'disconnected');
    
    // 更新调用信息，展示错误
    if (invocationMessage) {
      updateToolInvocationMessage(invocationMessage, 'error', error.message);
    }
    
    addCombinedMessage(thinkingContent, '工具调用失败: ' + error.message);
    await addMessageToServer(currentSession.sessionId, 'assistant', '工具调用失败: ' + error.message);
    currentSession.conversationHistory.push({
      role: 'assistant',
      content: '工具调用失败: ' + error.message
    });
  }
}

// 处理提示词模板调用
async function handlePromptInvocation(responseData, thinkingContent = '', conclusionContent = '') {
  console.log('=== handlePromptInvocation 被调用 ===');
  const promptName = responseData.prompt_name || responseData.name;
  const parameters = responseData.parameters || responseData.arguments || {};
  
  console.log('提示词模板名称:', promptName);
  console.log('参数:', parameters);
  rememberMcpCapability(promptName, MCP_CAPABILITY_LABELS[promptName] || promptName, 'prompt');
  
  try {
    updateStatus('正在获取提示词模板...', 'connecting');
    
    // 调用MCP提示词模板
    console.log('调用MCP提示词模板:', promptName);
    const promptResponse = await sendMCPRequest({
      method: 'prompts/get',
      params: {
        name: promptName,
        arguments: parameters
      }
    });
    
    if (promptResponse.error) {
      throw new Error(promptResponse.error.message);
    }
    
    const promptData = promptResponse.result;
    console.log('✅ 提示词模板获取成功');
    
    // 如果是在工作流模式下，保存提示词模版内容
    if (currentSession.workflow && currentSession.workflow.mode === 'workflow') {
      // 提取提示词模版的实际内容
      let promptContent = '';
      if (typeof promptData === 'string') {
        promptContent = promptData;
      } else if (promptData && typeof promptData === 'object') {
        // 尝试从不同格式中提取内容
        if (promptData.messages && Array.isArray(promptData.messages) && promptData.messages.length > 0) {
          const firstMessage = promptData.messages[0];
          if (firstMessage && typeof firstMessage === 'object') {
            const content = firstMessage.content;
            if (typeof content === 'string') {
              promptContent = content;
            } else if (content && typeof content === 'object' && content.text) {
              promptContent = content.text;
            }
          }
        } else if (promptData.text) {
          promptContent = promptData.text;
        } else {
          promptContent = JSON.stringify(promptData);
        }
      }
      
      currentSession.workflow.current_prompt = promptContent;
      console.log('✅ 工作流模式下已保存提示词模版内容，长度:', promptContent.length);
    }
    
    // 更新状态机：标记提示词模板已调用，进入生成阶段
    currentSession.stage = 'generate_with_llm';
    currentSession.currentIntent = responseData.intent || currentSession.currentIntent;
    console.log('✅ 状态机已更新: stage = generate_with_llm, prompt_name =', promptName);
    
    // 获取用户原始输入
    const lastUserMessage = currentSession.conversationHistory
      .filter(m => m.role === 'user')
      .pop()?.content || '';
    
    // 构建 resource_response 格式的 JSON，包含工作流信息
    const resourceResponseData = {
      type: 'resource_response',
      intent: responseData.intent || currentSession.currentIntent || '法官断案',
      data: {
        prompt_content: promptData,
        prompt_name: promptName,
        prompt_parameters: parameters
      },
      next_stage: 'wait_for_llm_process'
    };
    
    // 如果存在工作流信息，添加到 resource_response 中
    if (responseData.workflow_id) {
      resourceResponseData.workflow_id = responseData.workflow_id;
    }
    if (responseData.current_step !== undefined) {
      resourceResponseData.step = responseData.current_step + 1; // 步骤从0开始，所以+1
    }
    if (responseData.workflow_intent) {
      resourceResponseData.workflow_intent = responseData.workflow_intent;
    }
    
    // 将 resource_response 格式的 JSON 追加到用户输入中，让 LLM 识别为工作流延续
    const resourceResponseJson = JSON.stringify(resourceResponseData, null, 2);
    const enhancedUserMessage = lastUserMessage 
      ? `${lastUserMessage}\n\n[资源响应]\n${resourceResponseJson}`
      : `[资源响应]\n${resourceResponseJson}`;
    
    console.log('📦 将提示词模板结果包装为 resource_response 格式:', resourceResponseJson);
    
    // 继续调用LLM生成最终结果（使用流式输出）
    console.log('🔄 提示词模板已获取，继续调用LLM生成最终结果...');
    updateStatus('正在生成最终结论...', 'connecting');
    
    // 构建 system 消息，提示模型当前阶段
    const systemMessage = `你已成功加载 '${promptName}' 提示词指南。请严格按照该指南的第一步开始执行：向用户提问以收集案情信息。不要再次请求调用 ${promptName}。当前工作模式为 workflow。`;
    
    // 使用 afterInvocation 模式：将用户输入添加到历史对话，使用 system 消息替代 user_input
    const requestData = buildRequestData(enhancedUserMessage, {
      afterInvocation: true,
      invocationType: 'prompt',
      invocationName: promptName,
      systemMessage: systemMessage
    });
    
    // 同时保留 invokeDetail 以兼容服务端逻辑
    requestData.invokeDetail = {
      type: 'prompt',
      name: promptName,
      parameters: parameters,
      result: promptData,
      completed: true
    };
    
    // 初始化流式消息容器
    const streamingMsg = addStreamingMessage();
    let accumulatedContent = '';
    let finalThinkingContent = thinkingContent || '';
    let finalConclusionContent = '';
    
    // 流式回调函数
    const onStreamChunk = (content, reasoningText = null, lawText = null) => {
      accumulatedContent = content;
      
      if (reasoningText !== null || lawText !== null) {
        finalThinkingContent = reasoningText || finalThinkingContent || '';
        if (lawText) {
          // 提取可读内容，避免显示JSON原始文本
          const extracted = extractConclusionFromLawQaText(lawText);
          // 如果提取失败且是JSON字符串，不显示JSON原始文本
          if (extracted === lawText && lawText.trim().startsWith('{')) {
            finalConclusionContent = '';  // 不显示JSON原始文本
          } else {
            finalConclusionContent = extracted;
          }
        }
      } else {
        const separator = '==JSON==';
        const separatorIndex = content.indexOf(separator);
        if (separatorIndex !== -1) {
          finalThinkingContent = content.substring(0, separatorIndex).trim();
          const rawConclusion = content.substring(separatorIndex + separator.length).trim();
          // 尝试解析JSON并提取可读内容，而不是直接显示JSON字符串
          finalConclusionContent = parseJsonAndExtractConclusion(rawConclusion) || rawConclusion;
        } else {
          finalThinkingContent = content;
          finalConclusionContent = '';
        }
      }
      
      updateStreamingMessage(finalThinkingContent, finalConclusionContent);
    };
    
    const llmResponse = await callLLM(requestData, onStreamChunk);
    
    // 解析并处理响应
    await parseAndHandleResponse(llmResponse, true, finalThinkingContent, finalConclusionContent);
    
  } catch (error) {
    console.error('提示词模板调用失败:', error);
    updateStatus('提示词模板调用失败', 'disconnected');
    addCombinedMessage(thinkingContent, '提示词模板调用失败: ' + error.message);
    await addMessageToServer(currentSession.sessionId, 'assistant', '提示词模板调用失败: ' + error.message);
    currentSession.conversationHistory.push({
      role: 'assistant',
      content: '提示词模板调用失败: ' + error.message
    });
  }
}

// 执行工作流步骤
async function executeWorkflowSteps(responseData, thinkingContent = '', conclusionContent = '') {
  if (!responseData) {
    console.error('❌ executeWorkflowSteps: responseData 为空');
    return;
  }
  
  console.log('🔧 executeWorkflowSteps 被调用');
  console.log('responseData 内容:', JSON.stringify(responseData, null, 2));
  console.log('responseData 类型:', responseData.type);
  console.log('responseData 是否包含 prompt_to_user:', !!responseData.prompt_to_user);
  console.log('prompt_to_user 内容:', responseData.prompt_to_user || '(未设置)');
  
  if (currentSession?.workflow?.active) {
    console.warn('⚠️ 工作流已在执行中，忽略新的 start_workflow');
    return;
  }

  const steps = responseData.recommended_steps || responseData.steps || [];
  if (!Array.isArray(steps) || steps.length === 0) {
    console.warn('⚠️ start_workflow 未包含有效步骤');
    addCombinedMessage(thinkingContent, '工作流步骤为空，无法执行。');
    return;
  }

  // 如果有 prompt_to_user 字段，显示给用户
  if (responseData.prompt_to_user) {
    console.log('📢 显示工作流提示信息:', responseData.prompt_to_user);
    // 将思考内容和提示信息组合显示
    const displayContent = thinkingContent && thinkingContent.trim()
      ? `${thinkingContent}\n\n${responseData.prompt_to_user}`
      : responseData.prompt_to_user;
    addCombinedMessage(thinkingContent, responseData.prompt_to_user);
    // 添加到会话历史
    await addMessageToServer(currentSession.sessionId, 'assistant', displayContent);
    currentSession.conversationHistory.push({
      role: 'assistant',
      content: displayContent
    });
  } else {
    // 如果没有 prompt_to_user，记录警告
    console.warn('⚠️ start_workflow 响应中缺少 prompt_to_user 字段');
    console.warn('responseData 的所有字段:', Object.keys(responseData));
    if (thinkingContent && thinkingContent.trim()) {
      // 如果有思考内容，也显示思考内容
      addCombinedMessage(thinkingContent, '');
      await addMessageToServer(currentSession.sessionId, 'assistant', thinkingContent);
      currentSession.conversationHistory.push({
        role: 'assistant',
        content: thinkingContent
      });
    }
  }

  currentSession.stage = 'workflow';
  currentSession.workflow = {
    active: true,
    currentIndex: 0,
    steps: steps,
    mode: 'workflow',  // 设置工作流模式
    current_prompt: null  // 提示词模版内容，将在调用提示词模版后设置
  };

  const lastUserMessage = currentSession.conversationHistory
    .filter(m => m.role === 'user')
    .pop()?.content || '';

  // 跟踪是否刚刚调用了资源/工具/提示词模版
  let justInvoked = false;
  
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i] || {};
    currentSession.workflow.currentIndex = i;
    console.log(`🔧 执行工作流步骤 ${i + 1}/${steps.length}:`, step);

    const stepType = step.type || '';
    const stepAction = step.action || '';
    const isInvoke =
      stepType === 'invoke_tool_or_resource' ||
      stepType === 'invoke_tool' ||
      stepType === 'invoke_prompt' ||
      stepAction === 'access_resource' ||
      stepAction === 'invoke_tool' ||
      stepAction === 'invoke_prompt';

    if (isInvoke) {
      const invokeResponseData = {
        type: 'invoke_tool_or_resource',
        action: stepAction || null,
        intent: step.intent || responseData.intent || null,
        resource_uri: step.resource_uri || step.resourceUri || null,
        tool_name: step.tool_name || step.toolName || null,
        prompt_template: step.prompt_template || step.promptTemplate || step.prompt_name || step.promptName || null,
        prompt_name: step.prompt_name || step.promptName || null,
        parameters: step.parameters || step.params || {},
        next_stage: step.next_stage || step.nextStage || null
      };
      await handleResponseByType(invokeResponseData, thinkingContent, conclusionContent);
      justInvoked = true; // 标记刚刚调用了资源/工具/提示词模版
      continue;
    }

    // 其他类型：提交给模型处理
    const workflowInstructionParts = [];
    if (step.description) {
      workflowInstructionParts.push(`步骤说明：${step.description}`);
    }
    if (step.required_input) {
      workflowInstructionParts.push(`所需输入：${step.required_input}`);
    }
    if (step.output_format) {
      workflowInstructionParts.push(`输出格式：${step.output_format}`);
    }
    if (!workflowInstructionParts.length) {
      workflowInstructionParts.push('请执行当前工作流步骤并输出结果。');
    }

    const workflowInstruction = `[Workflow Step ${step.id || i + 1}]\n${workflowInstructionParts.join('\n')}`;
    const workflowInput = [lastUserMessage, workflowInstruction].filter(Boolean).join('\n\n');
    
    // 如果刚刚调用了资源/工具/提示词模版，则移除 user_input 字段
    const requestData = buildRequestData(workflowInput, {
      afterInvocation: justInvoked,
      invocationType: justInvoked ? 'workflow' : null,
      invocationName: justInvoked ? 'workflow_step' : null,
      systemMessage: justInvoked ? '这是工作流步骤，请根据上一步的资源/工具/提示词模版调用结果继续处理。' : null
    });
    
    requestData.workflow_step = {
      id: step.id || null,
      type: step.type || null,
      description: step.description || null,
      required_input: step.required_input || null,
      output_format: step.output_format || null
    };

    const llmResponse = await callLLM(requestData);
    await parseAndHandleResponse(llmResponse);
    
    // 重置标记，因为这一步已经处理完成
    justInvoked = false;
  }

  currentSession.workflow.active = false;
  currentSession.stage = 'idle';
}

// 显示参数选择
async function showParameterSelection(missingParameters, intent) {
  // 检查是否有参数有枚举值
  const paramsWithEnums = missingParameters.filter(param => PARAMETER_ENUMS[param]);
  
  if (paramsWithEnums.length > 0) {
    // 显示参数选择弹窗
    const selectedParams = await showParameterModal(paramsWithEnums, missingParameters);
    if (selectedParams) {
      // 用户选择了参数，更新会话并继续处理
      Object.assign(currentSession.collectedParameters, selectedParams);
      currentSession.missingParameters = currentSession.missingParameters.filter(
        p => !Object.keys(selectedParams).includes(p)
      );
      
      // 重新调用LLM处理
      const lastUserInput = currentSession.conversationHistory
        .filter(m => m.role === 'user')
        .pop()?.content || '';
      
      if (lastUserInput) {
        const requestData = buildRequestData(lastUserInput);
        
        try {
          const llmResponse = await callLLM(requestData);
          await parseAndHandleResponse(llmResponse);
        } catch (error) {
          console.error('处理失败:', error);
          showError('处理失败: ' + error.message);
        }
      }
    }
  } else {
    // 没有枚举值，只显示提示
  const message = `请提供以下参数：${missingParameters.join(', ')}`;
  addMessage('assistant', message);
  }
}

// 显示参数选择模态框
function showParameterModal(paramsWithEnums, allMissingParams) {
  return new Promise((resolve) => {
    elements.parameterOptions.innerHTML = '';
    
    const selectedValues = {};
    
    paramsWithEnums.forEach(paramName => {
      const paramDiv = document.createElement('div');
      paramDiv.className = 'parameter-group';
      paramDiv.innerHTML = `<label class="parameter-label">${paramName}:</label>`;
      
      const optionsDiv = document.createElement('div');
      optionsDiv.className = 'parameter-options-list';
      
      PARAMETER_ENUMS[paramName].forEach(option => {
        const optionDiv = document.createElement('div');
        optionDiv.className = 'parameter-option';
        optionDiv.textContent = option;
        optionDiv.onclick = () => {
          // 切换选择状态
          document.querySelectorAll(`.parameter-group:has(.parameter-option) .parameter-option`).forEach(el => {
            if (el.parentElement === optionsDiv) {
              el.classList.remove('selected');
            }
          });
          optionDiv.classList.add('selected');
          selectedValues[paramName] = option;
        };
        optionsDiv.appendChild(optionDiv);
      });
      
      paramDiv.appendChild(optionsDiv);
      elements.parameterOptions.appendChild(paramDiv);
    });
    
    // 处理没有枚举值的参数
    const paramsWithoutEnums = allMissingParams.filter(p => !paramsWithEnums.includes(p));
    if (paramsWithoutEnums.length > 0) {
      const textInputDiv = document.createElement('div');
      textInputDiv.className = 'parameter-group';
      textInputDiv.innerHTML = `<label class="parameter-label">其他参数（用逗号分隔）：</label>`;
      
      const textInput = document.createElement('input');
      textInput.type = 'text';
      textInput.className = 'parameter-text-input';
      textInput.placeholder = paramsWithoutEnums.join(', ');
      textInput.onchange = () => {
        const values = textInput.value.split(',').map(v => v.trim());
        paramsWithoutEnums.forEach((param, index) => {
          if (values[index]) {
            selectedValues[param] = values[index];
          }
        });
      };
      
      textInputDiv.appendChild(textInput);
      elements.parameterOptions.appendChild(textInputDiv);
    }
    
    elements.parameterModal.style.display = 'flex';
    
    elements.confirmParameterBtn.onclick = () => {
      elements.parameterModal.style.display = 'none';
      if (Object.keys(selectedValues).length > 0) {
        resolve(selectedValues);
      } else {
        resolve(null);
      }
    };
    
    elements.cancelParameterBtn.onclick = () => {
      elements.parameterModal.style.display = 'none';
      resolve(null);
    };
  });
}

// 显示工具批准弹窗
function showToolApproval(resourceUri, parameters) {
  return new Promise((resolve) => {
    elements.toolApprovalInfo.innerHTML = `
      <p><strong>资源URI:</strong> ${resourceUri}</p>
      <p><strong>参数:</strong></p>
      <pre>${JSON.stringify(parameters, null, 2)}</pre>
    `;
    
    elements.toolApprovalModal.style.display = 'flex';
    
    elements.approveToolBtn.onclick = () => {
      elements.toolApprovalModal.style.display = 'none';
      resolve(true);
    };
    
    elements.rejectToolBtn.onclick = () => {
      elements.toolApprovalModal.style.display = 'none';
      resolve(false);
    };
  });
}

// 添加消息
async function loadActiveCaseOptions() {
  const sel = document.getElementById('activeCaseSelect');
  if (!sel || !CONFIG || !CONFIG.mcpServerUrl || typeof LegalMindAuth === 'undefined') return;
  const resp = await fetch(`${CONFIG.mcpServerUrl}/api/admin/cases`, {
    headers: LegalMindAuth.authHeaders()
  });
  if (resp.status === 401) {
    LegalMindAuth.requireLogin('login.html?next=mcp_client.html');
    return;
  }
  if (!resp.ok) throw new Error('cases HTTP ' + resp.status);
  const data = await resp.json();
  sel.innerHTML = '<option value="">请选择案件…</option>';
  (data.cases || []).forEach(function (c) {
    const opt = document.createElement('option');
    opt.value = String(c.id);
    opt.textContent = (c.case_no || '') + ' · ' + (c.title || '') +
      (c.status_label ? ('（' + c.status_label + '）') : '');
    sel.appendChild(opt);
  });
  // 默认不选中任何案件，需用户主动下拉选择
  sel.value = '';
  LegalMindAuth.setCaseId(null);
  sel.onchange = function () {
    const v = sel.value ? parseInt(sel.value, 10) : null;
    LegalMindAuth.setCaseId(v);
  };
}

function tryHandleOrchestrate(fullUserMessage) {
  return (async function() {
    if (!CONFIG || !CONFIG.mcpServerUrl) return false;
    let shell = null;

    async function applyOrchestrateSuccess(targetShell, data, userMessage) {
      const flow = (data.capabilities && data.capabilities.flow) || data.flow || [];
      if (typeof currentStreamingMessage !== 'undefined' && currentStreamingMessage) {
        try { currentStreamingMessage.remove(); } catch (e) {}
        currentStreamingMessage = null;
      }
      paintOrchestrateFlow(targetShell.flowSlot, flow, flow.length, -1);
      const answer = ((data.visible_text || '') + (data.pending_question ? '\n\n' + data.pending_question : '')).trim();
      if (!answer && !flow.length) {
        return false;
      }
      if (targetShell.answer) {
        targetShell.answer.hidden = !answer;
        targetShell.answer.textContent = answer;
      } else {
        targetShell.content.hidden = false;
        targetShell.content.textContent = answer;
      }
      const citations = collectOrchestrateCitations(data);
      if (citations.length && targetShell.content) {
        renderOrchestrateCitations(targetShell.content, citations);
      }
      if (data.artifact && data.artifact.file_id) {
        addOrchestrateDownload(data.artifact);
      }
      if (currentSession) {
        currentSession.conversationHistory.push({ role: 'user', content: userMessage });
        currentSession.conversationHistory.push({
          role: 'assistant',
          content: data.visible_text,
          artifact: data.artifact || undefined,
          capabilities: data.capabilities || undefined
        });
        if (currentSession.sessionId && typeof addMessageToServer === 'function' && !data.saved_to_session) {
          addMessageToServer(currentSession.sessionId, 'user', userMessage).catch(() => {});
          const extra = {};
          if (data.artifact) extra.artifact = data.artifact;
          if (data.capabilities) extra.capabilities = data.capabilities;
          addMessageToServer(currentSession.sessionId, 'assistant', data.visible_text, Object.keys(extra).length ? extra : null).catch(() => {});
        }
        if (typeof saveSession === 'function') {
          saveSession(currentSession).catch(() => {});
        }
      }
      console.log('✅ orchestrate handled', data.agent || '');
      return true;
    }

    function doRequest() {
      return fetch(`${CONFIG.mcpServerUrl}/api/orchestrate`, {
        method: 'POST',
        headers: (typeof LegalMindAuth !== 'undefined' && LegalMindAuth.authHeaders)
          ? LegalMindAuth.authHeaders()
          : { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_text: fullUserMessage,
          session_id: currentSession && currentSession.sessionId,
          messages: (currentSession && currentSession.conversationHistory) || [],
          case_id: (typeof LegalMindAuth !== 'undefined' && LegalMindAuth.getCaseId)
            ? LegalMindAuth.getCaseId()
            : null
        })
      });
    }

    function attachRetry(targetShell, errText) {
      const btn = showOrchestrateFailure(targetShell, errText);
      if (!btn) return;
      btn.onclick = async function () {
        btn.disabled = true;
        btn.textContent = '重试中…';
        try {
          const resp = await doRequest();
          if (resp.status === 401) {
            if (typeof LegalMindAuth !== 'undefined') LegalMindAuth.requireLogin('login.html?next=mcp_client.html');
            if (targetShell && targetShell.wrap) targetShell.wrap.remove();
            return;
          }
          if (!resp.ok) {
            const errBody = await resp.json().catch(function () { return {}; });
            attachRetry(targetShell, errBody.error || ('请求失败 ' + resp.status));
            return;
          }
          const data = await resp.json();
          if (data && data.legacy) {
            attachRetry(targetShell, '当前请求需走旧路径，请刷新页面后重发。');
            return;
          }
          if (!data) {
            attachRetry(targetShell, '服务暂时不可用，请稍后重试。');
            return;
          }
          clearOrchestrateRetry(targetShell);
          const ok = await applyOrchestrateSuccess(targetShell, data, fullUserMessage);
          if (!ok) {
            attachRetry(targetShell, '服务暂时不可用，请稍后重试。');
          }
        } catch (e) {
          attachRetry(targetShell, e.message || '服务暂时不可用，请稍后重试。');
        }
      };
    }

    try {
      shell = addOrchestrateProgressShell();
      paintOrchestrateFlow(shell.flowSlot, [], 0, -1);
      const resp = await doRequest();
      if (resp.status === 401) {
        if (typeof LegalMindAuth !== 'undefined') LegalMindAuth.requireLogin('login.html?next=mcp_client.html');
        if (shell && shell.wrap) shell.wrap.remove();
        return true;
      }
      if (!resp.ok) {
        const errBody = await resp.json().catch(function () { return {}; });
        attachRetry(shell, errBody.error || ('请求失败 ' + resp.status));
        return true;
      }
      const data = await resp.json();
      if (data && data.legacy) {
        if (shell && shell.wrap) shell.wrap.remove();
        return false;
      }
      if (!data) {
        attachRetry(shell, '服务暂时不可用，请稍后重试。');
        return true;
      }
      const ok = await applyOrchestrateSuccess(shell, data, fullUserMessage);
      if (!ok) {
        attachRetry(shell, '服务暂时不可用，请稍后重试。');
        return true;
      }
      return true;
    } catch (err) {
      console.warn('orchestrate failed; showing retry:', err);
      if (!shell) shell = addOrchestrateProgressShell();
      attachRetry(shell, err.message || '服务暂时不可用，请稍后重试。');
      return true;
    }
  })();
}

function addOrchestrateDownload(artifact) {
  if (!elements.chatMessages || !artifact) return;
  const wrap = document.createElement('div');
  wrap.className = 'message assistant';
  const header = document.createElement('div');
  header.className = 'message-header';
  header.textContent = '⚖️ LegalMind';
  const content = document.createElement('div');
  content.className = 'message-content generated-doc-wrap';

  const card = document.createElement('div');
  card.className = 'generated-doc-card';

  const top = document.createElement('div');
  top.className = 'generated-doc-main';
  const icon = document.createElement('div');
  icon.className = 'file-icon-container docx';
  icon.textContent = 'W';
  const info = document.createElement('div');
  info.className = 'file-info';
  const name = document.createElement('div');
  name.className = 'file-name';
  name.textContent = artifact.filename || '法律文书.docx';
  const meta = document.createElement('div');
  meta.className = 'file-size';
  meta.textContent = (artifact.title || 'Word 文书') + ' · 可下载核阅';
  info.appendChild(name);
  info.appendChild(meta);
  top.appendChild(icon);
  top.appendChild(info);

  const preview = document.createElement('div');
  preview.className = 'generated-doc-preview';
  preview.hidden = true;
  preview.textContent = artifact.preview || '暂无预览，请下载 Word 查看全文。';

  const tabs = document.createElement('div');
  tabs.className = 'generated-doc-tabs';
  const tabPreview = document.createElement('button');
  tabPreview.type = 'button';
  tabPreview.className = 'generated-doc-tab';
  tabPreview.textContent = '预览';
  const tabDownload = document.createElement('button');
  tabDownload.type = 'button';
  tabDownload.className = 'generated-doc-tab';
  tabDownload.textContent = '下载';
  tabs.appendChild(tabPreview);
  tabs.appendChild(tabDownload);

  tabPreview.onclick = () => {
    preview.hidden = !preview.hidden;
    tabPreview.classList.toggle('active', !preview.hidden);
  };
  tabDownload.onclick = () => {
    tabDownload.classList.add('active');
    tabPreview.classList.remove('active');
    preview.hidden = true;
    downloadFileFromCard(artifact.file_id, artifact.filename || '法律文书.docx');
  };

  card.appendChild(top);
  card.appendChild(preview);
  card.appendChild(tabs);
  content.appendChild(card);
  wrap.appendChild(header);
  wrap.appendChild(content);
  elements.chatMessages.appendChild(wrap);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

const MCP_CAPABILITY_LABELS = {
  'legal://law_regulation': '法律法规',
  'legal://similar_cases': '类案检索',
  'legal://doc_template': '文书模板',
  'legal://contract_review_rules': '合同审查规则',
  gen_legal_doc_guide: '生成法律文书提示词',
  contract_review_guide: '合同审查提示词',
  judge_work_guide: '法官工作指南'
};

function emptyCapabilities() {
  return { agents: [], skills: [], mcp: [], trace: [] };
}

function hasCapabilities(caps) {
  if (!caps) return false;
  if (caps.flow && caps.flow.length) return true;
  if (caps.trace && caps.trace.length) return true;
  return !!((caps.agents && caps.agents.length) || (caps.skills && caps.skills.length) || (caps.mcp && caps.mcp.length));
}

function rememberMcpCapability(id, name, mcpKind) {
  if (!currentSession || !id) return;
  currentSession.turnCapabilities = currentSession.turnCapabilities || emptyCapabilities();
  const list = currentSession.turnCapabilities.mcp;
  if (list.some(function (item) { return item.id === id; })) return;
  list.push({
    kind: 'mcp',
    mcp_kind: mcpKind || 'resource',
    id: id,
    name: name || MCP_CAPABILITY_LABELS[id] || id
  });
}

function consumeTurnCapabilities() {
  if (!currentSession) return null;
  const caps = currentSession.turnCapabilities;
  currentSession.turnCapabilities = emptyCapabilities();
  if (!hasCapabilities(caps)) return null;
  currentSession._pendingCapabilities = caps;
  return caps;
}

function kindLabel(kind) {
  if (kind === 'skill') return 'Skill';
  if (kind === 'agent') return 'Agent';
  if (kind === 'result') return '结果';
  return 'MCP';
}

function renderCapabilityFlow(flow, opts) {
  opts = opts || {};
  const visible = opts.visibleCount == null ? flow.length : opts.visibleCount;
  const running = opts.runningIndex == null ? -1 : opts.runningIndex;
  const wrap = document.createElement('div');
  wrap.className = 'capability-trace capability-flow-wrap';
  wrap.setAttribute('aria-label', '调用流程');
  const title = document.createElement('div');
  title.className = 'capability-trace-title';
  title.textContent = '实际工作流';
  wrap.appendChild(title);
  const list = document.createElement('div');
  list.className = 'capability-flow';
  if (!flow || !flow.length) {
    const wait = document.createElement('div');
    wait.className = 'capability-flow-wait';
    wait.textContent = '正在编排，完成后会列出本次实际调用的 Agent / Skill / MCP';
    wrap.appendChild(wait);
    return wrap;
  }
  flow.forEach(function (item, index) {
    const row = document.createElement('div');
    row.className = 'capability-flow-item';
    if (index > 0) {
      const arrow = document.createElement('div');
      arrow.className = 'capability-flow-arrow' + (index < visible ? ' on' : '');
      arrow.textContent = '↓';
      row.appendChild(arrow);
    }
    const step = document.createElement('div');
    const on = index < visible;
    const isRun = index === running;
    step.className = 'capability-flow-step capability-chip ' + (item.kind || 'mcp')
      + (on ? ' on' : '')
      + (isRun ? ' running' : '')
      + (on && !isRun ? ' done' : '');
    const kindEl = document.createElement('span');
    kindEl.className = 'capability-kind';
    kindEl.textContent = kindLabel(item.kind);
    const label = document.createElement('span');
    label.textContent = item.name || item.id;
    step.appendChild(kindEl);
    step.appendChild(label);
    if (item.id && item.id !== item.name) {
      const idEl = document.createElement('code');
      idEl.className = 'capability-id';
      idEl.textContent = item.id;
      step.appendChild(idEl);
    }
    step.title = (kindLabel(item.kind) + ' ' + (item.name || '') + ' ' + (item.id || '')).trim();
    row.appendChild(step);
    list.appendChild(row);
  });
  wrap.appendChild(list);
  return wrap;
}

function renderCapabilityTrace(caps) {
  if (!caps) return null;
  if (caps.flow && caps.flow.length) {
    return renderCapabilityFlow(caps.flow, { visibleCount: caps.flow.length, runningIndex: -1 });
  }
  if (!hasCapabilities(caps)) return null;
  const wrap = document.createElement('div');
  wrap.className = 'capability-trace';
  wrap.setAttribute('aria-label', '本次调用的 Agent、Skill 与 MCP');
  const title = document.createElement('div');
  title.className = 'capability-trace-title';
  title.textContent = '本次调用（Agent / Skill / MCP）';
  wrap.appendChild(title);
  const row = document.createElement('div');
  row.className = 'capability-trace-row';
  const items = (caps.trace && caps.trace.length)
    ? caps.trace
    : [].concat(caps.agents || []).concat(caps.skills || []).concat(caps.mcp || []);
  items.forEach(function (item) {
    const chip = document.createElement('span');
    const kind = item.kind || 'mcp';
    chip.className = 'capability-chip ' + kind;
    const kindText = kindLabel(kind);
    chip.title = kindText + ' ' + (item.id || item.name || '');
    const kindEl = document.createElement('span');
    kindEl.className = 'capability-kind';
    kindEl.textContent = kindText;
    const label = document.createElement('span');
    label.textContent = item.name || item.id;
    chip.appendChild(kindEl);
    chip.appendChild(label);
    row.appendChild(chip);
  });
  wrap.appendChild(row);
  return wrap;
}

function previewOrchestrateFlow(text) {
  const t = text || '';
  const steps = [{ kind: 'agent', id: 'orchestrator', name: '任务编排' }];
  if (/起诉状|生成文书|写一份|起草|导出文书|判决书|协议书/.test(t)) {
    steps.push({ kind: 'agent', id: 'doc_writing', name: '文书写作' });
  } else if (/检索|法条|类案|法规/.test(t) && t.indexOf('分析') < 0) {
    steps.push({ kind: 'agent', id: 'legal_retrieval', name: '法规类案检索' });
  } else {
    steps.push({ kind: 'agent', id: 'text_analysis', name: '文本分析' });
  }
  steps.push({ kind: 'skill', id: 'skill', name: '调用 Skill' });
  steps.push({ kind: 'mcp', id: 'mcp', name: '调用 MCP' });
  const resultName = /起诉状|生成文书|写一份|起草|导出文书/.test(t) ? '返回文书结果' : '返回分析结果';
  steps.push({ kind: 'result', id: 'return', name: resultName });
  return steps;
}

function clearOrchestrateRetry(shell) {
  if (!shell || !shell.content) return;
  const old = shell.content.querySelector('.orchestrate-retry-row');
  if (old) old.remove();
}

function showOrchestrateFailure(shell, errText) {
  if (!shell) return;
  clearOrchestrateRetry(shell);
  const msg = (errText || '服务暂时不可用，请稍后重试。').trim();
  if (shell.answer) {
    shell.answer.hidden = false;
    shell.answer.textContent = msg;
  } else if (shell.content) {
    shell.content.hidden = false;
    // keep structure: prefer answer child
  }
  const row = document.createElement('div');
  row.className = 'orchestrate-retry-row';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'orchestrate-retry-btn';
  btn.textContent = '重试';
  row.appendChild(btn);
  (shell.content || shell.wrap).appendChild(row);
  return btn;
}

function addOrchestrateProgressShell() {
  const messageDiv = document.createElement('div');
  messageDiv.className = 'message assistant orchestrate-turn';
  const headerDiv = document.createElement('div');
  headerDiv.className = 'message-header';
  headerDiv.textContent = '⚖️ LegalMind';
  const contentDiv = document.createElement('div');
  contentDiv.className = 'message-content';
  const flowSlot = document.createElement('div');
  flowSlot.className = 'orchestrate-flow-slot';
  const answerEl = document.createElement('div');
  answerEl.className = 'orchestrate-answer';
  answerEl.hidden = true;
  contentDiv.appendChild(flowSlot);
  contentDiv.appendChild(answerEl);
  messageDiv.appendChild(headerDiv);
  messageDiv.appendChild(contentDiv);
  if (elements.chatMessages) {
    elements.chatMessages.appendChild(messageDiv);
    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  }
  return { wrap: messageDiv, flowSlot: flowSlot, content: contentDiv, answer: answerEl };
}

function collectOrchestrateCitations(data) {
  if (!data || typeof data !== 'object') return [];
  if (Array.isArray(data.citations) && data.citations.length) return data.citations;
  const nested = data.data && typeof data.data === 'object' ? data.data : null;
  if (nested) {
    const fromNested = []
      .concat(Array.isArray(nested.law_citations) ? nested.law_citations : [])
      .concat(Array.isArray(nested.case_citations) ? nested.case_citations : []);
    if (fromNested.length) return fromNested;
  }
  const top = []
    .concat(Array.isArray(data.law_citations) ? data.law_citations : [])
    .concat(Array.isArray(data.case_citations) ? data.case_citations : []);
  return top;
}

function renderOrchestrateCitations(container, citations) {
  if (!container || !citations || !citations.length) return;
  const prev = container.querySelector('.cite-list');
  if (prev) prev.remove();
  const list = document.createElement('div');
  list.className = 'cite-list';
  const label = document.createElement('div');
  label.className = 'cite-list-label';
  label.textContent = '引用';
  list.appendChild(label);
  const seen = {};
  citations.forEach(function (c) {
    if (!c || typeof c !== 'object') return;
    const title = (c.title || '文献').trim() || '文献';
    const article = (c.article || '').trim();
    const fileId = c.file_id || '';
    const docId = c.document_id || '';
    const dedupeKey = [fileId, docId, title, article].join('|');
    if (seen[dedupeKey]) return;
    seen[dedupeKey] = true;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'cite-link';
    btn.textContent = article ? (title + ' ' + article) : title;
    if (!fileId) {
      btn.disabled = true;
      btn.title = '未关联源文件';
    } else {
      btn.onclick = function () {
        try {
          getChatFilePreview()
            .open(fileId, title, { article: article })
            .catch(function (err) {
              console.warn('citation preview failed', err);
              if (typeof updateStatus === 'function') {
                updateStatus(err && err.message ? err.message : '预览失败', 'error');
              }
            });
        } catch (err) {
          console.warn('citation preview unavailable', err);
        }
      };
    }
    list.appendChild(btn);
  });
  if (list.children.length <= 1) return;
  container.appendChild(list);
  if (elements.chatMessages) {
    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  }
}

function paintOrchestrateFlow(slot, flow, visibleCount, runningIndex) {
  if (!slot) return;
  slot.innerHTML = '';
  slot.appendChild(renderCapabilityFlow(flow, {
    visibleCount: visibleCount,
    runningIndex: runningIndex
  }));
}

function sleepMs(ms) {
  return new Promise(function (resolve) { setTimeout(resolve, ms); });
}

async function consumeOrchestrateSSE(resp, onStep) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let result = null;
  while (true) {
    const read = await reader.read();
    if (read.done) break;
    buf += decoder.decode(read.value, { stream: true });
    const chunks = buf.split('\n\n');
    buf = chunks.pop() || '';
    chunks.forEach(function (chunk) {
      const lines = chunk.split('\n');
      let payload = '';
      lines.forEach(function (line) {
        if (line.indexOf('data:') === 0) {
          payload += line.replace(/^data:\s?/, '');
        }
      });
      if (!payload) return;
      try {
        const msg = JSON.parse(payload);
        if (msg.type === 'step' && typeof onStep === 'function') onStep(msg);
        if (msg.type === 'done') result = msg.result;
      } catch (e) {
        console.warn('orchestrate SSE chunk parse skipped', e);
      }
    });
  }
  if (buf.trim()) {
    try {
      const leftover = buf.split('\n').filter(function (line) {
        return line.indexOf('data:') === 0;
      }).map(function (line) {
        return line.replace(/^data:\s?/, '');
      }).join('');
      if (leftover) {
        const msg = JSON.parse(leftover);
        if (msg.type === 'done') result = msg.result;
      }
    } catch (e) {}
  }
  return result;
}

async function playOrchestrateFlow(slot, flow) {
  if (!slot || !flow || !flow.length) return;
  for (let i = 0; i < flow.length; i++) {
    paintOrchestrateFlow(slot, flow, i + 1, i);
    if (elements.chatMessages) {
      elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
    }
    await sleepMs(320);
  }
  paintOrchestrateFlow(slot, flow, flow.length, -1);
}

function appendCapabilityTrace(host, caps) {
  if (!host) return;
  const bar = renderCapabilityTrace(caps);
  if (bar) host.appendChild(bar);
}

function addMessage(role, content, type = 'normal', capabilities = null) {
  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${role}`;
  
  const headerDiv = document.createElement('div');
  headerDiv.className = 'message-header';
  headerDiv.textContent = role === 'user' ? '👤 您' : '⚖️ LegalMind';
  
  const contentDiv = document.createElement('div');
  contentDiv.className = `message-content ${type === 'error' ? 'error-message' : ''}`;
  
  // 如果内容包含HTML，使用innerHTML，否则使用textContent
  if (type === 'html' || (typeof content === 'string' && content.includes('<'))) {
    contentDiv.innerHTML = content;
  } else {
    contentDiv.textContent = content;
  }
  
  messageDiv.appendChild(headerDiv);
  if (role === 'assistant' && capabilities && capabilities.flow && capabilities.flow.length) {
    appendCapabilityTrace(messageDiv, capabilities);
  }
  messageDiv.appendChild(contentDiv);
  if (role === 'assistant' && !(capabilities && capabilities.flow && capabilities.flow.length)) {
    appendCapabilityTrace(messageDiv, capabilities);
  }
  
  elements.chatMessages.appendChild(messageDiv);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

// 添加文件消息卡片
function addFileMessageCard(fileInfo) {
  const messageDiv = document.createElement('div');
  messageDiv.className = 'message user';
  
  const headerDiv = document.createElement('div');
  headerDiv.className = 'message-header';
  headerDiv.textContent = '👤 您';
  
  const contentDiv = document.createElement('div');
  contentDiv.className = 'message-content';
  contentDiv.style.background = 'transparent';
  contentDiv.style.padding = '0';
  
  // 创建文件卡片
  const fileCard = document.createElement('div');
  fileCard.className = 'file-message-card';
  // 添加data-file-id属性，用于检查重复显示
  fileCard.setAttribute('data-file-id', fileInfo.file_id);
  
  // 文件图标容器
  const iconContainer = document.createElement('div');
  iconContainer.className = 'file-icon-container';
  
  // 根据文件类型设置图标和颜色
  const fileExtension = fileInfo.original_name.split('.').pop()?.toLowerCase() || 'default';
  iconContainer.classList.add(fileExtension);
  
  // 根据文件类型显示不同的图标文字
  let iconText = '📄';
  if (fileExtension === 'docx' || fileExtension === 'doc') {
    iconText = 'W';
  } else if (fileExtension === 'pdf') {
    iconText = 'P';
  } else if (fileExtension === 'txt') {
    iconText = 'T';
  } else if (['png', 'jpg', 'jpeg', 'gif'].includes(fileExtension)) {
    iconText = '🖼';
  }
  iconContainer.textContent = iconText;
  
  // 文件信息
  const fileInfoDiv = document.createElement('div');
  fileInfoDiv.className = 'file-info';
  
  const fileName = document.createElement('div');
  fileName.className = 'file-name';
  fileName.textContent = fileInfo.original_name;
  
  const fileSize = document.createElement('div');
  fileSize.className = 'file-size';
  fileSize.textContent = `(${(fileInfo.file_size / 1024).toFixed(2)}KB)`;
  
  fileInfoDiv.appendChild(fileName);
  fileInfoDiv.appendChild(fileSize);
  
  // 文件操作按钮
  const actionsDiv = document.createElement('div');
  actionsDiv.className = 'file-actions';
  
  // 在线预览按钮 → 页内浮层
  const previewBtn = document.createElement('button');
  previewBtn.className = 'file-action-btn preview-btn';
  previewBtn.type = 'button';
  previewBtn.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
      <circle cx="12" cy="12" r="3"></circle>
    </svg>
    查看预览
  `;
  previewBtn.onclick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    previewFile(fileInfo.file_id, fileInfo.original_name);
  };
  
  // 下载按钮
  const downloadBtn = document.createElement('button');
  downloadBtn.className = 'file-action-btn download-btn';
  downloadBtn.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
      <polyline points="7 10 12 15 17 10"></polyline>
      <line x1="12" y1="15" x2="12" y2="3"></line>
    </svg>
    下载
  `;
  downloadBtn.onclick = () => {
    downloadFileFromCard(fileInfo.file_id, fileInfo.original_name);
  };
  
  actionsDiv.appendChild(previewBtn);
  actionsDiv.appendChild(downloadBtn);
  
  // 组装文件卡片
  fileCard.appendChild(iconContainer);
  fileCard.appendChild(fileInfoDiv);
  fileCard.appendChild(actionsDiv);
  
  contentDiv.appendChild(fileCard);
  messageDiv.appendChild(headerDiv);
  messageDiv.appendChild(contentDiv);
  
  elements.chatMessages.appendChild(messageDiv);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

// 对话页文件预览浮层（复用知识库 KbFilePreview）
let chatFilePreview = null;

function getChatFilePreview() {
  if (chatFilePreview) return chatFilePreview;
  if (!window.KbFilePreview || typeof window.KbFilePreview.create !== 'function') {
    throw new Error('预览组件未加载');
  }
  chatFilePreview = window.KbFilePreview.create({
    rootId: 'chatFileViewer',
    getBase: function () {
      return (CONFIG && CONFIG.mcpServerUrl) || 'http://localhost:8001';
    },
    authHeaders: function () {
      if (typeof LegalMindAuth !== 'undefined' && LegalMindAuth.authHeaders) {
        return LegalMindAuth.authHeaders();
      }
      return {};
    },
    esc: function (v) {
      return typeof escapeHtml === 'function' ? escapeHtml(v) : String(v == null ? '' : v);
    },
    api: async function (path) {
      const base = (CONFIG && CONFIG.mcpServerUrl) || 'http://localhost:8001';
      const headers =
        typeof LegalMindAuth !== 'undefined' && LegalMindAuth.authHeaders
          ? LegalMindAuth.authHeaders()
          : {};
      const resp = await fetch(base + path, { headers });
      const data = await resp.json().catch(function () { return {}; });
      if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
      return data;
    }
  });
  return chatFilePreview;
}

// 预览文件：页内浮层（不再新开标签 / 悬停下拉气泡）
async function previewFile(fileId, fileName) {
  try {
    updateStatus('正在加载文件预览...', 'connecting');
    // 关掉可能残留的旧气泡
    const tip = document.querySelector('.file-preview-tooltip');
    if (tip) tip.remove();
    await getChatFilePreview().open(fileId, fileName);
    updateStatus('文件预览已打开', 'connected');
  } catch (error) {
    console.error('预览文件失败:', error);
    updateStatus('预览失败', 'disconnected');
    let errorMessage = '预览文件失败';
    if (error && error.message) {
      if (String(error.message).includes('404')) {
        errorMessage = '文件不存在，可能已被删除';
      } else if (String(error.message).includes('网络') || String(error.message).includes('fetch')) {
        errorMessage = '网络连接失败，请检查网络设置';
      } else {
        errorMessage = '预览失败: ' + error.message;
      }
    }
    showError(errorMessage);
  }
}

// 下载文件（用于文件消息卡片）
async function downloadFileFromCard(fileId, fileName) {
  try {
    console.log(`开始下载文件: ${fileName} (${fileId})`);
    
    const mcpServerUrl = CONFIG.mcpServerUrl || 'http://localhost:8000';
    const downloadUrl = `${mcpServerUrl}/api/files/${fileId}/download`;
    
    console.log('下载URL:', downloadUrl);
    
    // 显示下载提示
    updateStatus('正在下载文件...', 'connecting');
    
    // 发起下载请求，确保获取原始二进制数据（不进行任何转换）
    const response = await fetch(downloadUrl, {
      method: 'GET',
      // 确保获取原始二进制数据，不被转换为文本
      headers: {
        'Accept': '*/*' // 接受任何类型的响应
      }
    });
    
    if (!response.ok) {
      const errorText = await response.text().catch(() => '');
      let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
      
      // 尝试解析错误信息
      try {
        const errorData = JSON.parse(errorText);
        if (errorData.error) {
          errorMessage = errorData.error;
        }
      } catch (e) {
        // 忽略JSON解析错误
      }
      
      throw new Error(errorMessage);
    }
    
    // 获取文件大小（用于显示进度）
    const contentLength = response.headers.get('content-length');
    const fileSize = contentLength ? parseInt(contentLength, 10) : null;
    const contentType = response.headers.get('content-type') || 'application/octet-stream';
    
    console.log('响应头信息:', {
      contentLength: fileSize ? `${(fileSize / 1024).toFixed(2)} KB` : '未知',
      contentType: contentType,
      contentDisposition: response.headers.get('content-disposition') || '未设置'
    });
    
    // 优先从响应头中提取文件名（服务端返回的原始文件名）
    let downloadFileName = fileName; // 默认使用传入的文件名
    const contentDisposition = response.headers.get('content-disposition');
    if (contentDisposition) {
      // 尝试从 Content-Disposition 头中提取文件名
      // 格式可能是: attachment; filename="xxx"; filename*=UTF-8''xxx
      const filenameMatch = contentDisposition.match(/filename\*?=['"]?([^'";]+)['"]?/i);
      if (filenameMatch && filenameMatch[1]) {
        let extractedName = filenameMatch[1];
        // 如果是 filename*=UTF-8''xxx 格式，需要解码
        if (extractedName.startsWith("UTF-8''")) {
          try {
            extractedName = decodeURIComponent(extractedName.substring(7));
          } catch (e) {
            console.warn('文件名解码失败，使用原始值:', e);
          }
        } else {
          // 尝试解码 URL 编码的文件名
          try {
            extractedName = decodeURIComponent(extractedName);
          } catch (e) {
            // 如果解码失败，使用原始值
          }
        }
        if (extractedName && extractedName.trim()) {
          downloadFileName = extractedName.trim();
          console.log('从响应头提取的文件名:', downloadFileName);
        }
      }
    }
    
    // 获取文件数据（确保是原始二进制数据，不被转换）
    // 使用 response.blob() 确保获取原始二进制数据，不进行任何文本转换
    const blob = await response.blob();
    const receivedSize = blob.size;
    
    console.log('文件数据已接收（原文件）:', {
      大小: `${(receivedSize / 1024).toFixed(2)} KB`,
      类型: blob.type || contentType,
      原始大小: fileSize ? `${(fileSize / 1024).toFixed(2)} KB` : '未知',
      大小匹配: fileSize ? (receivedSize === fileSize ? '✓ 匹配' : '✗ 不匹配') : '未知',
      数据完整性: fileSize ? (receivedSize === fileSize ? '✓ 完整' : '✗ 不完整') : '未知'
    });
    
    // 验证文件大小是否匹配（确保下载的是完整的原文件）
    if (fileSize && receivedSize !== fileSize) {
      console.warn(`⚠️ 文件大小不匹配: 期望 ${fileSize} 字节，实际 ${receivedSize} 字节`);
      console.warn('这可能表示文件在传输过程中被修改或损坏');
    } else if (fileSize && receivedSize === fileSize) {
      console.log('✓ 文件大小验证通过，确保是完整的原文件');
    }
    
    // 创建下载链接
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    
    // 使用从服务端提取的文件名（优先）或传入的文件名
    link.download = downloadFileName;
    link.setAttribute('download', downloadFileName);
    
    link.style.display = 'none';
    document.body.appendChild(link);
    
    // 触发下载
    link.click();
    
    // 延迟清理，确保下载开始
    setTimeout(() => {
      try {
        if (link.parentNode) {
          document.body.removeChild(link);
        }
        window.URL.revokeObjectURL(url);
      } catch (err) {
        console.warn('清理下载链接失败:', err);
      }
    }, 100);
    
    // 恢复状态
    updateStatus('文件下载已开始', 'connected');
    
    console.log(`✅ 文件下载已触发: ${downloadFileName} (原始文件，${(receivedSize / 1024).toFixed(2)} KB)`);
    
  } catch (error) {
    console.error('下载文件失败:', error);
    console.error('错误详情:', {
      fileId: fileId,
      fileName: fileName,
      error: error.message,
      stack: error.stack
    });
    
    // 恢复状态
    updateStatus('下载失败', 'disconnected');
    
    // 显示错误提示
    let errorMessage = '下载文件失败';
    if (error.message.includes('404')) {
      errorMessage = '文件不存在，可能已被删除';
    } else if (error.message.includes('网络') || error.message.includes('fetch')) {
      errorMessage = '网络连接失败，请检查网络设置';
    } else if (error.message) {
      errorMessage = `下载失败: ${error.message}`;
    }
    
    showError(errorMessage);
  }
}

// 获取文件内容用于预览
async function getFileContentForPreview(fileId) {
  try {
    const mcpServerUrl = CONFIG.mcpServerUrl || 'http://localhost:8000';
    const url = `${mcpServerUrl}/api/files/${fileId}`;
    console.log('请求文件内容，URL:', url);
    
    const response = await fetch(url);
    console.log('文件内容API响应状态:', response.status, response.statusText);
    
    if (!response.ok) {
      console.warn('文件内容API响应失败:', response.status);
      return null;
    }
    
    const fileInfo = await response.json();
    console.log('文件信息:', {
      file_id: fileInfo.file_id,
      original_name: fileInfo.original_name,
      has_text_content: !!fileInfo.text_content,
      text_content_length: fileInfo.text_content ? fileInfo.text_content.length : 0
    });
    
    return fileInfo.text_content || null;
  } catch (error) {
    console.error('❌ 获取文件内容失败:', error);
    return null;
  }
}

// 显示文件预览气泡
function showFilePreviewTooltip(button, content, fileName) {
  console.log('showFilePreviewTooltip 被调用，fileName:', fileName, 'content长度:', content.length);
  
  // 如果已存在气泡，先移除
  const existingTooltip = document.querySelector('.file-preview-tooltip');
  if (existingTooltip) {
    existingTooltip.remove();
  }
  
  // 创建气泡元素
  const tooltip = document.createElement('div');
  tooltip.className = 'file-preview-tooltip';
  tooltip.id = 'file-preview-tooltip';
  
  // 限制内容长度（最多显示2000字符）
  const maxLength = 2000;
  const displayContent = content.length > maxLength 
    ? content.substring(0, maxLength) + '\n\n...(内容过长，已截断)'
    : content;
  
  // 创建气泡内容
  tooltip.innerHTML = `
    <div class="tooltip-header">
      <span class="tooltip-title">${escapeHtml(fileName)}</span>
      <button class="tooltip-close" onclick="this.closest('.file-preview-tooltip')?.remove()">×</button>
    </div>
    <div class="tooltip-content">${escapeHtml(displayContent).replace(/\n/g, '<br>')}</div>
  `;
  
  document.body.appendChild(tooltip);
  console.log('气泡元素已添加到DOM');

  // 关键：强制气泡宽度不超过视窗（避免出现 tooltipRect.width > window.innerWidth 导致 left 为负数、气泡跑到屏幕外）
  try {
    const viewportW = window.innerWidth || 0;
    const safeMaxW = Math.max(260, Math.min(520, viewportW - 20)); // 预留左右边距，且给一个最小宽度
    tooltip.style.maxWidth = `${safeMaxW}px`;
    tooltip.style.width = 'auto';
  } catch (e) {}
  
  // 计算位置（优先在按钮上方显示；上方空间不足时自动显示在下方）
  // 使用“两次测量”：先应用 maxWidth，再在下一帧读取最终尺寸，保证定位准确
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      const buttonRect = button.getBoundingClientRect();
      let tooltipRect = tooltip.getBoundingClientRect();

      const viewportW = window.innerWidth || 0;
      const viewportH = window.innerHeight || 0;
      const margin = 10;

      // 如果仍然比视窗宽，强制设置宽度为可用宽度（再测一次）
      const availableW = Math.max(260, viewportW - margin * 2);
      if (tooltipRect.width > availableW) {
        tooltip.style.width = `${availableW}px`;
        tooltipRect = tooltip.getBoundingClientRect();
      }

      let left = buttonRect.left + (buttonRect.width / 2) - (tooltipRect.width / 2);
      // 优先放在按钮上方
      let top = buttonRect.top - tooltipRect.height - margin;

      // 确保气泡不超出视窗（如果气泡宽度 >= 视窗可用宽度，则固定贴边）
      if (tooltipRect.width >= availableW) {
        left = margin;
      } else {
        if (left < margin) left = margin;
        if (left + tooltipRect.width > viewportW - margin) {
          left = Math.max(margin, viewportW - tooltipRect.width - margin);
        }
      }

      // 如果上方空间不够（top太小），则放到按钮下方
      if (top < margin) {
        top = buttonRect.bottom + margin;
      }

      // 如果下方也超出视窗，则尽量贴近底部
      if (top + tooltipRect.height > viewportH - margin) {
        top = Math.max(margin, viewportH - tooltipRect.height - margin);
      }

      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
      console.log('气泡位置已设置:', { left, top, width: tooltipRect.width, height: tooltipRect.height, viewportW, viewportH });
    });
  });
  
  // 添加鼠标进入/离开事件，保持气泡显示
  tooltip.addEventListener('mouseenter', () => {
    console.log('鼠标进入气泡，保持显示');
    // 进入气泡时，取消任何即将发生的隐藏
    try {
      // 如果外层作用域有 hideTooltipTimer（来自按钮绑定），这里无法直接访问；
      // 所以用“只要气泡 hovered，就不隐藏”的策略兜底，隐藏逻辑里已判断 :hover
    } catch (e) {}
  });
  
  tooltip.addEventListener('mouseleave', () => {
    console.log('鼠标离开气泡，隐藏');
    hideFilePreviewTooltip(tooltip);
  });
  
  return tooltip;
}

// 隐藏文件预览气泡
function hideFilePreviewTooltip(tooltip) {
  if (tooltip && tooltip.parentNode) {
    tooltip.remove();
  }
}

// HTML转义函数
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// 添加合并的消息（包含思考内容和结论）
let currentStreamingMessage = null;

function addStreamingMessage() {
  // 如果已存在流式消息，先移除并清空引用
  if (currentStreamingMessage) {
    try {
      if (currentStreamingMessage.parentNode) {
    currentStreamingMessage.remove();
      }
    } catch (e) {
      console.warn('移除旧流式消息时出错:', e);
    }
    currentStreamingMessage = null;
  }
  
  const messageWrapper = document.createElement('div');
  messageWrapper.className = 'message assistant streaming-message';
  messageWrapper.id = 'streaming-message-' + Date.now();
  
  const headerDiv = document.createElement('div');
  headerDiv.className = 'message-header';
  
  const headerText = document.createElement('span');
  headerText.textContent = '⚖️ LegalMind';
  headerDiv.appendChild(headerText);
  
  // 折叠按钮（流式消息中，会在有思考内容时动态添加）
  const toggleBtn = document.createElement('button');
  toggleBtn.className = 'thinking-toggle-btn';
  toggleBtn.style.display = 'none'; // 初始隐藏，有思考内容时显示
  toggleBtn.innerHTML = '<span class="thinking-toggle-text">思考过程</span><span class="thinking-toggle-icon">▼</span>';
  toggleBtn.title = '点击折叠/展开思考过程';
  headerDiv.appendChild(toggleBtn);
  
  const thinkingDiv = document.createElement('div');
  thinkingDiv.className = 'thinking-content';
  thinkingDiv.style.display = 'none'; // 初始隐藏，有内容时显示
  
  const separatorDiv = document.createElement('div');
  separatorDiv.className = 'separator';
  separatorDiv.style.display = 'none'; // 初始隐藏
  
  const conclusionDiv = document.createElement('div');
  conclusionDiv.className = 'conclusion-content';
  conclusionDiv.style.display = 'none'; // 初始隐藏，有内容时显示
  
  messageWrapper.appendChild(headerDiv);
  messageWrapper.appendChild(thinkingDiv);
  messageWrapper.appendChild(separatorDiv);
  messageWrapper.appendChild(conclusionDiv);
  
  elements.chatMessages.appendChild(messageWrapper);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  
  currentStreamingMessage = messageWrapper;
  return {
    messageWrapper,
    thinkingDiv,
    separatorDiv,
    conclusionDiv
  };
}

function updateStreamingMessage(thinkingContent, conclusionContent) {
  if (!currentStreamingMessage) {
    console.log('updateStreamingMessage: 当前没有流式消息，创建新的');
    const msg = addStreamingMessage();
    currentStreamingMessage = msg.messageWrapper;
  }
  
  const thinkingDiv = currentStreamingMessage.querySelector('.thinking-content');
  const separatorDiv = currentStreamingMessage.querySelector('.separator');
  const conclusionDiv = currentStreamingMessage.querySelector('.conclusion-content');
  
  if (!thinkingDiv || !separatorDiv || !conclusionDiv) {
    console.error('updateStreamingMessage: 找不到DOM元素', {
      thinkingDiv: !!thinkingDiv,
      separatorDiv: !!separatorDiv,
      conclusionDiv: !!conclusionDiv
    });
    return;
  }
  
  // 更新思考内容
  if (thinkingContent && thinkingContent.trim()) {
    // 清理思考内容：移除可能包含的分隔符和结论内容
    let cleanedThinkingContent = thinkingContent.trim();
    
    // 如果思考内容中包含分隔符，只保留分隔符之前的部分
    const separator = '==JSON==';
    const separatorIndex = cleanedThinkingContent.indexOf(separator);
    if (separatorIndex !== -1) {
      cleanedThinkingContent = cleanedThinkingContent.substring(0, separatorIndex).trim();
      console.log('⚠️ [流式] 检测到思考内容中包含分隔符，已清理');
    }
    
    // 确保思考内容不为空
    if (cleanedThinkingContent) {
      thinkingDiv.textContent = cleanedThinkingContent;
    thinkingDiv.style.display = 'block';
      // 显示折叠按钮
      const toggleBtn = currentStreamingMessage.querySelector('.thinking-toggle-btn');
      if (toggleBtn) {
        toggleBtn.style.display = 'flex';
        // 确保按钮有点击事件
        if (!toggleBtn.onclick) {
          toggleBtn.onclick = function() {
            toggleThinkingContent(currentStreamingMessage, toggleBtn);
          };
        }
      }
      console.log('更新思考内容显示，长度:', cleanedThinkingContent.length);
  } else {
    thinkingDiv.style.display = 'none';
      // 隐藏折叠按钮
      const toggleBtn = currentStreamingMessage.querySelector('.thinking-toggle-btn');
      if (toggleBtn) {
        toggleBtn.style.display = 'none';
      }
      console.log('清理后的思考内容为空，隐藏');
    }
  } else {
    thinkingDiv.style.display = 'none';
    // 隐藏折叠按钮
    const toggleBtn = currentStreamingMessage.querySelector('.thinking-toggle-btn');
    if (toggleBtn) {
      toggleBtn.style.display = 'none';
    }
    console.log('思考内容为空，隐藏');
  }
  
  // 更新结论内容
  if (conclusionContent && conclusionContent.trim()) {
    conclusionDiv.textContent = conclusionContent;
    conclusionDiv.style.display = 'block';
    // 如果有思考内容和结论内容，显示分隔符（不显示文本，只显示边框线）
    if (thinkingContent && thinkingContent.trim()) {
      separatorDiv.textContent = '';  // 不显示文本，避免留白
      separatorDiv.style.display = 'block';
      console.log('显示分隔符');
    } else {
      separatorDiv.style.display = 'none';
    }
    console.log('更新结论内容显示，长度:', conclusionContent.length);
  } else {
    conclusionDiv.style.display = 'none';
    separatorDiv.style.display = 'none';
    console.log('结论内容为空，隐藏');
  }
  
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

function finalizeStreamingMessage() {
  if (currentStreamingMessage) {
    console.log('=== finalizeStreamingMessage 被调用 ===');
    console.log('移除流式消息，消息ID:', currentStreamingMessage.id);
    
    // 检查流式消息是否有内容（用于调试）
    const thinkingDiv = currentStreamingMessage.querySelector('.thinking-content');
    const conclusionDiv = currentStreamingMessage.querySelector('.conclusion-content');
    const thinkingText = thinkingDiv ? thinkingDiv.textContent : '';
    const conclusionText = conclusionDiv ? conclusionDiv.textContent : '';
    console.log('流式消息内容 - 思考长度:', thinkingText.length, '结论长度:', conclusionText.length);
    
    // 移除DOM元素（使用更安全的方式）
    try {
    if (currentStreamingMessage.parentNode) {
      currentStreamingMessage.remove();
      console.log('✅ 流式消息已从DOM中移除');
    } else {
      console.warn('⚠️ 流式消息的parentNode为null，可能已经被移除');
    }
    } catch (e) {
      console.error('移除流式消息时出错:', e);
    }
    
    // 无论是否成功移除，都清空引用，避免重复处理
    currentStreamingMessage = null;
  } else {
    console.log('finalizeStreamingMessage: 没有流式消息需要移除');
  }
}

// 切换思考内容的折叠/展开状态
function toggleThinkingContent(messageWrapper, toggleBtn) {
  const thinkingDiv = messageWrapper.querySelector('.thinking-content');
  const separatorDiv = messageWrapper.querySelector('.separator');
  
  if (!thinkingDiv) {
    return;
  }
  
  const isCollapsed = thinkingDiv.classList.contains('collapsed');
  
  if (isCollapsed) {
    // 展开
    thinkingDiv.classList.remove('collapsed');
    if (separatorDiv) {
      separatorDiv.classList.remove('collapsed');
    }
    toggleBtn.classList.remove('collapsed');
    const icon = toggleBtn.querySelector('.thinking-toggle-icon');
    if (icon) {
      icon.textContent = '▼';
    }
    console.log('展开思考内容');
  } else {
    // 折叠
    thinkingDiv.classList.add('collapsed');
    if (separatorDiv) {
      separatorDiv.classList.add('collapsed');
    }
    toggleBtn.classList.add('collapsed');
    const icon = toggleBtn.querySelector('.thinking-toggle-icon');
    if (icon) {
      icon.textContent = '▶';
    }
    console.log('折叠思考内容');
  }
}

// 从lawQaText中提取prompt_to_user或conclusion字段的内容
// 返回值：如果成功提取，返回提取的内容；如果无法提取，返回空字符串（不返回JSON原始文本）
// 如果Type为invoke_tool_or_resource，返回null（表示需要调用工具/资源）
function extractConclusionFromLawQaText(lawQaText) {
  if (!lawQaText || !lawQaText.trim()) {
    return '';
  }
  
  try {
    // 尝试解析为JSON
    const parsed = JSON.parse(lawQaText);
    
    // 检查Type字段，如果是invoke_tool_or_resource，返回null（特殊标记）
    if (parsed.Type === 'invoke_tool_or_resource' || parsed.type === 'invoke_tool_or_resource') {
      console.log('🔧 检测到Type为invoke_tool_or_resource，需要调用工具/资源');
      // 返回null作为特殊标记，表示需要调用工具/资源
      return null;
    }
    
    // 优先提取prompt_to_user，如果没有则提取conclusion
    if (parsed.prompt_to_user) {
      console.log('从lawQaText中提取prompt_to_user字段');
      return parsed.prompt_to_user;
    } else if (parsed.conclusion) {
      console.log('从lawQaText中提取conclusion字段');
      return parsed.conclusion;
    } else {
      // 如果都没有，检查是否有其他可读字段
      // 尝试提取message字段
      if (parsed.message) {
        console.log('从lawQaText中提取message字段');
        return parsed.message;
      }
      // 如果都没有可读字段，返回空字符串（不返回JSON原始文本）
      console.log('lawQaText中没有可读字段（prompt_to_user/conclusion/message），返回空字符串');
      return '';
    }
  } catch (e) {
    // 如果不是JSON格式，检查是否是纯文本
    // 如果是纯文本，直接返回；如果是JSON格式但解析失败，返回空字符串
    if (lawQaText.trim().startsWith('{') || lawQaText.trim().startsWith('[')) {
      // 看起来像JSON但解析失败，可能是JSON不完整，返回空字符串
      console.log('lawQaText看起来像JSON但解析失败，可能是JSON不完整，返回空字符串');
      return '';
    } else {
      // 纯文本，直接返回
      console.log('lawQaText不是JSON格式，是纯文本，返回原始内容');
    return lawQaText;
    }
  }
}

// 从lawQaText中解析invoke_tool_or_resource类型的参数
// 返回值：如果成功解析，返回包含resource_uri、parameters等字段的对象；否则返回null
// 参数 isStreaming: 是否为流式响应（如果是，则对不完整的JSON更宽容）
function parseInvokeToolOrResource(lawQaText, isStreaming = false) {
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:2947',message:'parseInvokeToolOrResource开始',data:{lawQaTextLength:lawQaText?.length||0,hasLawQaText:!!lawQaText,isStreaming},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'B'})}).catch(()=>{});
  // #endregion
  if (!lawQaText) {
    return null;
  }

  // 如果已经是对象，直接按对象处理（避免对非字符串调用trim）
  if (typeof lawQaText === 'object') {
    const parsedType = lawQaText.Type || lawQaText.type;
    if (parsedType === 'invoke_tool_or_resource' || parsedType === 'invoke_prompt' || parsedType === 'invoke_tool') {
      return {
        type: parsedType,
        action: lawQaText.action || null,
        resource_uri: lawQaText.resource_uri || lawQaText.resourceUri || null,
        tool_name: lawQaText.tool_name || lawQaText.toolName || null,
        prompt_template: lawQaText.prompt_template || lawQaText.promptTemplate || lawQaText.prompt_name || lawQaText.promptName || null,
        prompt_name: lawQaText.prompt_name || lawQaText.promptName || null,
        parameters: lawQaText.parameters || lawQaText.params || {}
      };
    }
    return null;
  }

  if (!lawQaText.trim()) {
    return null;
  }
  
  // 在流式响应中，检查JSON是否可能不完整
  if (isStreaming) {
    const trimmed = lawQaText.trim();
    if (trimmed.startsWith('{')) {
      const openBraces = (trimmed.match(/{/g) || []).length;
      const closeBraces = (trimmed.match(/}/g) || []).length;
      const endsWithBrace = trimmed.endsWith('}');
      const endsWithEscape = trimmed.endsWith('\\');
      const hasUnbalancedQuotes = (() => {
        let count = 0;
        for (let i = 0; i < trimmed.length; i++) {
          if (trimmed[i] !== '"') continue;
          let backslashCount = 0;
          let j = i - 1;
          while (j >= 0 && trimmed[j] === '\\') {
            backslashCount += 1;
            j -= 1;
          }
          if (backslashCount % 2 === 0) {
            count += 1;
          }
        }
        return count % 2 === 1;
      })();

      // 只要括号不匹配、结尾不是}、结尾转义、或引号不平衡，都视为不完整
      if (openBraces !== closeBraces || !endsWithBrace || endsWithEscape || hasUnbalancedQuotes) {
        console.log('🔧 [流式] JSON可能不完整，等待完整JSON后再解析', {
          openBraces,
          closeBraces,
          endsWithBrace,
          endsWithEscape,
          hasUnbalancedQuotes
        });
        return null;
      }
    }
  }
  
  try {
    let parsed = JSON.parse(lawQaText);
    
    // 检查Type字段（兼容 invoke_prompt / invoke_tool）
    const parsedType = parsed.Type || parsed.type;
    if (parsedType === 'invoke_tool_or_resource' || parsedType === 'invoke_prompt' || parsedType === 'invoke_tool') {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:2956',message:'parseInvokeToolOrResource检测到类型',data:{Type:parsed.Type,type:parsed.type,hasResourceUri:!!(parsed.resource_uri||parsed.resourceUri),hasToolName:!!(parsed.tool_name||parsed.toolName)},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'B'})}).catch(()=>{});
      // #endregion
      console.log('🔧 解析invoke_tool_or_resource参数');
      
      // 提取资源URI、工具名称、参数等信息
      const result = {
        type: parsedType,
        action: parsed.action || null,
        resource_uri: parsed.resource_uri || parsed.resourceUri || null,
        tool_name: parsed.tool_name || parsed.toolName || null,
        prompt_template: parsed.prompt_template || parsed.promptTemplate || parsed.prompt_name || parsed.promptName || null,
        prompt_name: parsed.prompt_name || parsed.promptName || null,
        parameters: parsed.parameters || parsed.params || {}
      };
      
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:2968',message:'parseInvokeToolOrResource返回结果',data:{resource_uri:result.resource_uri,tool_name:result.tool_name,hasParameters:Object.keys(result.parameters).length>0},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'B'})}).catch(()=>{});
      // #endregion
      console.log('解析结果:', result);
      return result;
    }
    
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:2972',message:'parseInvokeToolOrResource类型不匹配',data:{Type:parsed.Type,type:parsed.type},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'B'})}).catch(()=>{});
    // #endregion
    return null;
  } catch (e) {
    // 尝试从字符串中提取JSON片段再解析（适配有多余文本的情况）
    try {
      const jsonMatch = lawQaText.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        const parsed = JSON.parse(jsonMatch[0]);
        const parsedType = parsed.Type || parsed.type;
        if (parsedType === 'invoke_tool_or_resource' || parsedType === 'invoke_prompt' || parsedType === 'invoke_tool') {
          return {
            type: parsedType,
            action: parsed.action || null,
            resource_uri: parsed.resource_uri || parsed.resourceUri || null,
            tool_name: parsed.tool_name || parsed.toolName || null,
            prompt_template: parsed.prompt_template || parsed.promptTemplate || parsed.prompt_name || parsed.promptName || null,
            prompt_name: parsed.prompt_name || parsed.promptName || null,
            parameters: parsed.parameters || parsed.params || {}
          };
        }
      }
    } catch (nestedError) {
      // 保持原有处理逻辑
    }
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/0859865c-64b0-4653-a1d6-ebd1db64b092',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'mcp_client.js:2974',message:'parseInvokeToolOrResource解析失败',data:{errorMessage:e.message},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'B'})}).catch(()=>{});
    // #endregion
    if (isStreaming) {
      console.debug('🔧 [流式] JSON解析失败，等待后续完整数据:', e.message);
      return null;
    }
    console.error('解析invoke_tool_or_resource失败: [PARSE_INVOKE_JSON_FAILED]', e);
    return null;
  }
}

// 从responseData对象中提取可读的结论内容（而不是显示JSON字符串）
function extractReadableConclusion(responseData) {
  if (!responseData || typeof responseData !== 'object') {
    return '';
  }
  
  // 按优先级提取可读内容
  if (responseData.conclusion) {
    return responseData.conclusion;
  } else if (responseData.prompt_to_user) {
    return responseData.prompt_to_user;
  } else if (responseData.message) {
    return responseData.message;
  } else if (responseData.error) {
    return `错误: ${responseData.error}`;
  } else if (responseData.data && typeof responseData.data === 'object') {
    // 如果data是对象，尝试从中提取
    if (responseData.data.conclusion) {
      return responseData.data.conclusion;
    } else if (responseData.data.prompt_to_user) {
      return responseData.data.prompt_to_user;
    } else if (responseData.data.message) {
      return responseData.data.message;
    }
  }
  
  // 如果都没有，返回空字符串（不显示JSON）
  console.warn('无法从responseData中提取可读内容，响应类型:', responseData.type);
  return '';
}

// 从JSON字符串中解析并提取可读内容
function parseJsonAndExtractConclusion(jsonString) {
  if (!jsonString || !jsonString.trim()) {
    return '';
  }
  
  try {
    // 尝试提取JSON对象
    const jsonMatch = jsonString.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      return extractReadableConclusion(parsed);
    }
  } catch (e) {
    console.warn('解析JSON字符串失败:', e);
  }
  
  return '';
}

// 添加完整的合并消息（非流式）
function addCombinedMessage(thinkingContent, conclusionContent, capabilities) {
  console.log('=== addCombinedMessage 被调用 ===');
  console.log('思考内容长度:', thinkingContent ? thinkingContent.length : 0);
  console.log('结论内容长度:', conclusionContent ? conclusionContent.length : 0);
  console.log('思考内容预览:', thinkingContent ? thinkingContent.substring(0, 100) : '(空)');
  console.log('结论内容预览:', conclusionContent ? conclusionContent.substring(0, 100) : '(空)');
  
  // 确保流式消息已被移除，避免重复显示
  if (currentStreamingMessage) {
    console.warn('⚠️ 检测到流式消息仍存在，先移除它');
    finalizeStreamingMessage();
  }
  
  if (!elements.chatMessages) {
    console.error('❌ chatMessages元素不存在，无法添加消息');
    return null;
  }
  
  const messageWrapper = document.createElement('div');
  messageWrapper.className = 'message assistant combined-message';
  messageWrapper.id = 'final-message-' + Date.now(); // 添加唯一ID便于调试
  
  const headerDiv = document.createElement('div');
  headerDiv.className = 'message-header';
  
  const headerText = document.createElement('span');
  headerText.textContent = '⚖️ LegalMind';
  headerDiv.appendChild(headerText);
  
  // 如果有思考内容，添加折叠按钮
  if (thinkingContent && thinkingContent.trim()) {
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'thinking-toggle-btn';
    toggleBtn.innerHTML = '<span class="thinking-toggle-text">思考过程</span><span class="thinking-toggle-icon">▼</span>';
    toggleBtn.title = '点击折叠/展开思考过程';
    toggleBtn.onclick = function() {
      toggleThinkingContent(messageWrapper, toggleBtn);
    };
    headerDiv.appendChild(toggleBtn);
  }
  
  messageWrapper.appendChild(headerDiv);
  
  if (thinkingContent && thinkingContent.trim()) {
    // 清理思考内容：移除可能包含的分隔符和结论内容
    let cleanedThinkingContent = thinkingContent.trim();
    
    // 如果思考内容中包含分隔符，只保留分隔符之前的部分
    const separator = '==JSON==';
    const separatorIndex = cleanedThinkingContent.indexOf(separator);
    if (separatorIndex !== -1) {
      cleanedThinkingContent = cleanedThinkingContent.substring(0, separatorIndex).trim();
      console.log('⚠️ 检测到思考内容中包含分隔符，已清理');
    }
    
    // 确保思考内容不为空
    if (cleanedThinkingContent) {
    const thinkingDiv = document.createElement('div');
    thinkingDiv.className = 'thinking-content';
      thinkingDiv.textContent = cleanedThinkingContent;
    messageWrapper.appendChild(thinkingDiv);
      console.log('✅ 思考内容已添加到消息（已清理）');
    } else {
      console.log('⚠️ 清理后的思考内容为空，跳过');
    }
  } else {
    console.log('⚠️ 思考内容为空，跳过');
  }
  
  if (conclusionContent && conclusionContent.trim()) {
    if (thinkingContent && thinkingContent.trim()) {
      const separatorDiv = document.createElement('div');
      separatorDiv.className = 'separator';
      separatorDiv.textContent = '';  // 不显示文本，避免留白
      messageWrapper.appendChild(separatorDiv);
      console.log('✅ 分隔符已添加');
    }
    
    const conclusionDiv = document.createElement('div');
    conclusionDiv.className = 'conclusion-content';
    conclusionDiv.textContent = conclusionContent;
    messageWrapper.appendChild(conclusionDiv);
    console.log('✅ 结论内容已添加到消息');
  } else {
    console.log('⚠️ 结论内容为空，跳过');
  }
  
  // 验证消息元素是否包含内容
  const hasContent = messageWrapper.querySelector('.thinking-content') || messageWrapper.querySelector('.conclusion-content');
  if (!hasContent) {
    console.error('❌ 警告：消息元素中没有任何内容！');
    console.error('思考内容:', thinkingContent);
    console.error('结论内容:', conclusionContent);
  }

  const caps = capabilities === undefined ? consumeTurnCapabilities() : capabilities;
  appendCapabilityTrace(messageWrapper, caps);
  
  elements.chatMessages.appendChild(messageWrapper);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  
  console.log('✅ 最终消息已添加到DOM，消息ID:', messageWrapper.id);
  console.log('当前聊天消息数量:', elements.chatMessages.children.length);
  
  // 验证消息是否真的在DOM中
  setTimeout(() => {
    const addedMessage = document.getElementById(messageWrapper.id);
    if (!addedMessage) {
      console.error('❌ 严重错误：消息添加到DOM后立即丢失！');
    } else {
      console.log('✅ 验证：消息仍在DOM中');
    }
  }, 100);
  
  return messageWrapper;
}

// 废弃的函数（保持向后兼容，但内部调用新函数）
function addThinkingContent(content) {
  if (!currentStreamingMessage) {
    addStreamingMessage();
  }
  updateStreamingMessage(content, null);
}

function addConclusionContent(content) {
  if (!currentStreamingMessage) {
    addStreamingMessage();
  }
  const thinkingDiv = currentStreamingMessage.querySelector('.thinking-content');
  const thinkingContent = thinkingDiv ? thinkingDiv.textContent : '';
  updateStreamingMessage(thinkingContent, content);
}

// 显示错误
function showError(message) {
  addMessage('assistant', message, 'error');
  updateStatus('错误', 'disconnected');
}

// 更新状态
function updateStatus(text, status) {
  if (!elements.statusText) {
    console.warn('⚠️ updateStatus: statusText元素不存在');
    return;
  }
  if (!elements.connectionStatus) {
    console.warn('⚠️ updateStatus: connectionStatus元素不存在');
    return;
  }
  console.log(`📊 更新状态: ${text} (${status})`);
  elements.statusText.textContent = text;
  elements.connectionStatus.className = `status-indicator ${status}`;
}

// 保存会话
// 保存会话到服务端
async function saveSession(session) {
  try {
    // 构建更新对象，只包含有值的字段（避免发送空值）
    const updates = {};
    
    // status 总是保存（即使可能没有变化）
    if (session.status) {
      updates.status = session.status;
    }
    
    // 只在有值时才保存这些字段
    if (session.currentIntent) {
      updates.current_intent = session.currentIntent;
    }
    if (session.collectedParameters && Object.keys(session.collectedParameters).length > 0) {
      updates.collected_parameters = session.collectedParameters;
    }
    if (session.missingParameters && session.missingParameters.length > 0) {
      updates.missing_parameters = session.missingParameters;
    }
    if (session.stage && session.stage !== 'idle') {
      updates.stage = session.stage;
    }
    if (session.contextCache && Object.keys(session.contextCache).length > 0) {
      updates.context_cache = session.contextCache;
    }
    
    // 如果没有需要更新的字段，跳过保存（减少不必要的网络请求）
    if (Object.keys(updates).length === 0) {
      console.log('📤 会话状态无变化，跳过保存');
      return;
    }
    
    console.log('📤 保存会话状态:', {
      sessionId: session.sessionId,
      updates: updates,
      hasIntent: !!updates.current_intent,
      hasCollectedParams: Object.keys(updates.collected_parameters || {}).length > 0,
      hasMissingParams: (updates.missing_parameters || []).length > 0,
      hasContextCache: Object.keys(updates.context_cache || {}).length > 0
    });
    
    // 更新会话信息
    const response = await fetch(`${CONFIG.mcpServerUrl}/api/sessions/${session.sessionId}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(updates)
    });
    
    if (!response.ok) {
      throw new Error(`保存会话失败: HTTP ${response.status}`);
    }
  } catch (error) {
    console.error('保存会话失败:', error);
    // 降级到本地存储
  const sessions = JSON.parse(localStorage.getItem('mcp_sessions') || '[]');
  const index = sessions.findIndex(s => s.sessionId === session.sessionId);
  if (index >= 0) {
    sessions[index] = session;
  } else {
    sessions.push(session);
  }
  localStorage.setItem('mcp_sessions', JSON.stringify(sessions));
  }
}

// 添加消息到服务端（带超时机制，不阻塞主流程）
async function addMessageToServer(sessionId, role, content, extra) {
  // 如果sessionId为null或undefined，跳过保存到服务端（只保存到本地历史）
  if (!sessionId) {
    console.warn('⚠️ sessionId为空，跳过保存消息到服务端（仅保存到本地历史）');
    return;
  }

  if (role === 'assistant' && currentSession && currentSession._pendingCapabilities) {
    extra = extra || {};
    if (!extra.capabilities) extra.capabilities = currentSession._pendingCapabilities;
    currentSession._pendingCapabilities = null;
  }

  if (content == null) {
    console.warn('⚠️ content为空，跳过保存消息到服务端');
    return;
  }
  if (typeof content === 'string' && !content.trim()) {
    console.warn('⚠️ content为空字符串，跳过保存消息到服务端');
    return;
  }
  
  const url = `${CONFIG.mcpServerUrl}/api/sessions/${sessionId}/messages`;
  console.log('📤 准备保存消息到服务端:', url, 'role:', role, 'content长度:', content?.length || 0);
  
  try {
    // 创建超时控制器，5秒超时
    const controller = new AbortController();
    const timeoutId = setTimeout(() => {
      controller.abort();
      console.warn('⚠️ 保存消息到服务端超时（5秒），继续执行主流程');
    }, 5000);
    
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        role: role,
        content: content,
        extra: extra || undefined
      }),
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      throw new Error(`添加消息失败: HTTP ${response.status}`);
    }
    
    const result = await response.json();
    console.log('✅ 消息已保存到服务端:', result);
  } catch (error) {
    if (error.name === 'AbortError') {
      console.warn('⚠️ 保存消息到服务端超时，但不影响主流程');
    } else {
      console.error('⚠️ 添加消息到服务端失败，但不影响主流程:', error);
    }
    // 不抛出错误，避免阻塞主流程
  }
}

// 加载会话列表（从服务端）
async function loadSessionList() {
  if (!elements.sessionList) {
    console.error('❌ loadSessionList: sessionList元素不存在，无法加载会话列表');
    return;
  }
  
  try {
    console.log('📋 开始加载会话列表...');
    const response = await fetch(`${CONFIG.mcpServerUrl}/api/sessions`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      }
    });
    
    if (!response.ok) {
      throw new Error(`获取会话列表失败: HTTP ${response.status}`);
    }
    
    const sessions = await response.json();
    console.log(`📋 获取到 ${sessions.length} 个会话`);
    elements.sessionList.innerHTML = '';
    
    if (sessions.length === 0) {
      console.log('📋 会话列表为空，显示空状态');
      const emptyDiv = document.createElement('div');
      emptyDiv.className = 'session-empty';
      emptyDiv.textContent = '暂无会话';
      emptyDiv.style.cssText = 'text-align: center; color: #999; padding: 20px; font-size: 0.9rem;';
      elements.sessionList.appendChild(emptyDiv);
      return;
    }
    
    sessions.forEach(session => {
      const sessionDiv = document.createElement('div');
      sessionDiv.className = 'session-item';
      if (session.session_id === currentSession.sessionId) {
        sessionDiv.classList.add('active');
      }
      
      // 使用最后用户输入作为标题，如果没有则使用默认标题
      const title = session.title || session.last_user_input || `会话 ${new Date(session.created_at).toLocaleString()}`;
      // 只显示前12个字符，后续用"···"代替
      const titleText = title.length > 12 ? title.substring(0, 12) + '···' : title;
      
      // 格式化创建时间显示（使用created_at）
      let timeText = '';
      if (session.created_at) {
        const time = new Date(session.created_at);
        timeText = time.toLocaleDateString('zh-CN', { 
          month: 'short', 
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit'
        });
      }
      
      // 创建标题和时间容器
      const titleSpan = document.createElement('span');
      titleSpan.className = 'session-title';
      titleSpan.textContent = titleText;
      
      const timeSpan = document.createElement('span');
      timeSpan.className = 'session-time';
      timeSpan.textContent = timeText;
      
      // 创建操作按钮容器
      const actionsDiv = document.createElement('div');
      actionsDiv.className = 'session-actions';
      
      // 创建编辑按钮
      const editBtn = document.createElement('button');
      editBtn.className = 'session-edit-btn';
      editBtn.innerHTML = '✎';
      editBtn.title = '编辑会话名称';
      editBtn.onclick = async (e) => {
        e.stopPropagation();
        await editSessionName(session.session_id, titleSpan, session);
      };
      
      // 创建删除按钮
      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'session-delete-btn';
      deleteBtn.innerHTML = '×';
      deleteBtn.title = '删除会话';
      deleteBtn.onclick = async (e) => {
        e.stopPropagation();
        const confirmed = await showDeleteConfirm(titleText);
        if (confirmed) {
          await deleteSession(session.session_id);
        }
      };
      
      actionsDiv.appendChild(editBtn);
      actionsDiv.appendChild(deleteBtn);
      
      sessionDiv.appendChild(titleSpan);
      if (timeText) {
        sessionDiv.appendChild(timeSpan);
      }
      sessionDiv.appendChild(actionsDiv);
      
      sessionDiv.onclick = async () => await loadSession(session.session_id);
      elements.sessionList.appendChild(sessionDiv);
    });
  } catch (error) {
    console.error('❌ 加载会话列表失败:', error);
    console.error('错误详情:', error.message);
    console.error('错误堆栈:', error.stack);
    
    if (!elements.sessionList) {
      console.error('sessionList元素不存在，无法显示错误信息');
      return;
    }
    
    // 显示错误信息
    elements.sessionList.innerHTML = '';
    const errorDiv = document.createElement('div');
    errorDiv.className = 'session-error';
    errorDiv.innerHTML = `
      <div style="text-align: center; color: #f44336; padding: 20px;">
        <div style="font-size: 0.9rem; margin-bottom: 8px;">加载失败</div>
        <div style="font-size: 0.8rem; color: #999; margin-bottom: 12px;">${error.message || '未知错误'}</div>
        <button onclick="location.reload()" style="background: #1a4a6e; color: #fff; border: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; font-size: 0.85rem;">刷新重试</button>
      </div>
    `;
    elements.sessionList.appendChild(errorDiv);
    
    // 降级到本地存储
    try {
  const sessions = JSON.parse(localStorage.getItem('mcp_sessions') || '[]');
      console.log('📋 尝试从本地存储加载会话，找到', sessions.length, '个会话');
      
      if (sessions.length > 0) {
        // 清空错误信息，显示本地会话
  elements.sessionList.innerHTML = '';
  
  sessions.forEach(session => {
    const sessionDiv = document.createElement('div');
    sessionDiv.className = 'session-item';
    if (session.sessionId === currentSession.sessionId) {
      sessionDiv.classList.add('active');
    }
      
      const title = session.title || session.lastUserInput || `会话 ${new Date(session.createdAt).toLocaleString()}`;
      // 只显示前12个字符，后续用"···"代替
      const titleText = title.length > 12 ? title.substring(0, 12) + '···' : title;
      
      // 格式化创建时间显示
      let timeText = '';
      if (session.createdAt) {
        const time = new Date(session.createdAt);
        timeText = time.toLocaleDateString('zh-CN', { 
          month: 'short', 
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit'
        });
      }
      
      // 创建标题和时间容器
      const titleSpan = document.createElement('span');
      titleSpan.className = 'session-title';
      titleSpan.textContent = titleText;
      
      const timeSpan = document.createElement('span');
      timeSpan.className = 'session-time';
      timeSpan.textContent = timeText;
          
          // 创建操作按钮容器
          const actionsDiv = document.createElement('div');
          actionsDiv.className = 'session-actions';
          
          // 创建编辑按钮
          const editBtn = document.createElement('button');
          editBtn.className = 'session-edit-btn';
          editBtn.innerHTML = '✎';
          editBtn.title = '编辑会话名称';
          editBtn.onclick = async (e) => {
            e.stopPropagation();
            await editSessionName(session.sessionId, titleSpan, session);
          };
      
      // 创建删除按钮（本地存储模式）
      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'session-delete-btn';
      deleteBtn.innerHTML = '×';
      deleteBtn.title = '删除会话';
      deleteBtn.onclick = async (e) => {
        e.stopPropagation();
        const confirmed = await showDeleteConfirm(titleText);
        if (confirmed) {
          // 尝试从服务端删除（如果服务端可用）
          try {
            await deleteSession(session.sessionId);
          } catch (error) {
            // 如果服务端删除失败，从本地存储中删除
            console.warn('服务端删除失败，使用本地存储:', error);
            const updatedSessions = sessions.filter(s => s.sessionId !== session.sessionId);
            localStorage.setItem('mcp_sessions', JSON.stringify(updatedSessions));
            
            // 如果删除的是当前会话，创建新会话
            if (currentSession && currentSession.sessionId === session.sessionId) {
              await createNewSession();
              elements.chatMessages.innerHTML = '';
            }
            
            // 刷新会话列表
            await loadSessionList();
          }
        }
      };
          
          actionsDiv.appendChild(editBtn);
          actionsDiv.appendChild(deleteBtn);
      
      sessionDiv.appendChild(titleSpan);
      if (timeText) {
        sessionDiv.appendChild(timeSpan);
      }
          sessionDiv.appendChild(actionsDiv);
      
          sessionDiv.onclick = async () => await loadSession(session);
    elements.sessionList.appendChild(sessionDiv);
  });
        console.log('✅ 从本地存储加载会话列表完成，已显示', sessions.length, '个会话');
      } else {
        console.log('📋 本地存储也没有会话，保持错误提示');
      }
    } catch (localError) {
      console.error('❌ 从本地存储加载会话也失败:', localError);
      // 保持错误提示
    }
  }
}

// 显示删除确认弹窗
function showDeleteConfirm(sessionTitle) {
  return new Promise((resolve) => {
    const modal = document.getElementById('deleteConfirmModal');
    const messageEl = document.getElementById('deleteConfirmMessage');
    const confirmBtn = document.getElementById('confirmDeleteBtn');
    const cancelBtn = document.getElementById('cancelDeleteBtn');
    
    if (!modal || !messageEl || !confirmBtn || !cancelBtn) {
      // 如果弹窗元素不存在，降级使用原生confirm
      resolve(confirm(`确定删除该对话吗?删除后将无法查看`));
      return;
    }
    
    // 消息内容已在HTML中设置，不需要动态修改
    // messageEl.textContent = `确定删除该对话吗?删除后将无法查看`;
    
    // 显示弹窗
    modal.style.display = 'flex';
    
    // 确认删除
    const handleConfirm = () => {
      modal.style.display = 'none';
      confirmBtn.onclick = null;
      cancelBtn.onclick = null;
      modal.onclick = null;
      resolve(true);
    };
    
    // 取消删除
    const handleCancel = () => {
      modal.style.display = 'none';
      confirmBtn.onclick = null;
      cancelBtn.onclick = null;
      modal.onclick = null;
      resolve(false);
    };
    
    // 绑定事件（移除旧的事件监听器）
    confirmBtn.onclick = handleConfirm;
    cancelBtn.onclick = handleCancel;
    
    // 点击背景关闭
    modal.onclick = (e) => {
      if (e.target === modal) {
        handleCancel();
      }
    };
  });
}

// 处理从首页跳转过来的输入内容
async function handleHomePageInput() {
  try {
    // 检查URL参数
    const urlParams = new URLSearchParams(window.location.search);
    const inputText = urlParams.get('input');
    
    console.log('=== handleHomePageInput 开始 ===');
    console.log('URL参数input:', inputText);
    console.log('完整URL:', window.location.href);
    console.log('URL search:', window.location.search);
    
    // 检查sessionStorage中的文件
    const pendingFilesData = sessionStorage.getItem('pendingFiles');
    const createdSessionId = sessionStorage.getItem('createdSessionId');
    
    console.log('pendingFilesData:', pendingFilesData);
    console.log('createdSessionId:', createdSessionId);
    
    // 只要有inputText、pendingFilesData或createdSessionId任何一个，就认为是从首页跳转过来的
    // 即使只有inputText为空字符串，也应该检查是否有其他数据
    const hasInputText = inputText && inputText.trim().length > 0;
    const hasPendingFiles = pendingFilesData !== null;
    const hasCreatedSession = createdSessionId !== null;
    
    console.log('判断条件:', {
      hasInputText,
      hasPendingFiles,
      hasCreatedSession,
      shouldProcess: hasInputText || hasPendingFiles || hasCreatedSession
    });
    
    if (hasInputText || hasPendingFiles || hasCreatedSession) {
      console.log('✅ 检测到从首页跳转，准备自动填充内容');
      
      // 从首页跳转时，使用已创建的会话或创建新会话
      if (createdSessionId) {
        console.log('=== 从首页跳转，使用已创建的会话 ===');
        console.log('会话ID:', createdSessionId);
        
        // 使用已创建的会话ID
        if (currentSession && currentSession.sessionId !== createdSessionId) {
          console.log('切换会话ID到已创建的会话');
          currentSession.sessionId = createdSessionId;
          // 清空聊天消息
          if (elements.chatMessages) {
            elements.chatMessages.innerHTML = '';
          }
        } else if (!currentSession) {
          // 如果当前没有会话，创建一个使用已创建会话ID的会话对象
          currentSession = {
            sessionId: createdSessionId,
            status: 'active',
            currentIntent: null,
            collectedParameters: {},
            missingParameters: [],
            stage: 'idle',
            contextCache: {},
            createdAt: new Date().toISOString(),
            conversationHistory: []
          };
        }
        
        // 清除sessionStorage中的会话ID
        sessionStorage.removeItem('createdSessionId');
      } else {
        console.log('=== 从首页跳转，创建新会话 ===');
        if (currentSession && currentSession.sessionId) {
          console.log('当前已有会话，清除并创建新会话');
          // 清空聊天消息
          if (elements.chatMessages) {
            elements.chatMessages.innerHTML = '';
          }
        }
        
        // 创建新会话
        try {
          await createNewSession();
          console.log('✅ 新会话已创建:', currentSession.sessionId);
        } catch (error) {
          console.error('创建新会话失败:', error);
          // 即使创建失败，也继续处理输入
        }
      }
      
      // 从首页跳转过来时，不填充文本到输入框，直接发送
      // 保存inputText到全局变量，供后续自动发送使用
      let decodedInputText = '';
      if (inputText) {
        try {
          decodedInputText = decodeURIComponent(inputText);
          console.log('解码后的文本:', decodedInputText);
        } catch (e) {
          console.error('解码URL参数失败:', e);
          decodedInputText = inputText;
        }
        console.log('✅ 已保存首页输入文本（不填充到输入框）:', decodedInputText);
      } else {
        console.log('没有inputText参数，跳过文本处理');
      }
      
      // 处理已上传的文件ID（从首页上传的文件）
      const uploadedFileIdsData = sessionStorage.getItem('uploadedFileIds');
      let uploadedFileIdsForAutoSend = [];
      if (uploadedFileIdsData) {
        try {
          uploadedFileIdsForAutoSend = JSON.parse(uploadedFileIdsData);
          console.log('检测到已上传的文件ID:', uploadedFileIdsForAutoSend);
          // 将文件ID存储到全局变量，供后续LLM请求使用
          window.uploadedFileIds = uploadedFileIdsForAutoSend;
          
          // 从服务端获取文件信息并显示在预览区域
          if (uploadedFileIdsForAutoSend && uploadedFileIdsForAutoSend.length > 0) {
            console.log('开始从服务端获取文件信息并显示预览...');
            try {
              // 获取MCP服务器地址（CONFIG在init()中已加载）
              let mcpServerUrl = 'http://localhost:8000';
              if (typeof CONFIG !== 'undefined' && CONFIG.mcpServerUrl) {
                mcpServerUrl = CONFIG.mcpServerUrl;
              } else {
                // 如果CONFIG未加载，尝试从sessionStorage获取
                const mcpServerUrlFromStorage = sessionStorage.getItem('mcp_server_url');
                if (mcpServerUrlFromStorage) {
                  mcpServerUrl = mcpServerUrlFromStorage;
                }
              }
              console.log('使用MCP服务器地址:', mcpServerUrl);
              
              // 并行获取所有文件信息
              const fileInfoPromises = uploadedFileIdsForAutoSend.map(async (fileId) => {
                try {
                  const response = await fetch(`${mcpServerUrl}/api/files/${fileId}`);
                  if (response.ok) {
                    const fileInfo = await response.json();
                    console.log(`✅ 获取文件信息成功: ${fileId}`, fileInfo);
                    return fileInfo;
                  } else {
                    console.error(`❌ 获取文件信息失败: ${fileId}`, response.status);
                    return null;
                  }
                } catch (error) {
                  console.error(`❌ 获取文件信息出错: ${fileId}`, error);
                  return null;
                }
              });
              
              const fileInfos = await Promise.all(fileInfoPromises);
              
              // 过滤掉失败的文件，创建fileData对象并添加到pendingFiles
              const validFiles = [];
              for (const fileInfo of fileInfos) {
                if (fileInfo) {
                  const fileData = {
                    fileInfo: {
                      file_id: fileInfo.file_id,
                      original_name: fileInfo.original_name,
                      file_size: fileInfo.file_size,
                      file_type: fileInfo.file_type || fileInfo.mime_type || 'application/octet-stream'
                    },
                    file: null, // 从首页上传的文件，不需要File对象
                    isTextFile: false,
                    fileContent: fileInfo.text_content || null // 如果有提取的文本内容，使用它
                  };
                  
                  // 添加到pendingFiles和validFiles数组
                  pendingFiles.push(fileData);
                  validFiles.push(fileData);
                  console.log(`✅ 已添加文件到pendingFiles: ${fileInfo.original_name} (fileId: ${fileInfo.file_id})`);
                }
              }
              
              console.log(`✅ 文件信息获取完成，共 ${validFiles.length} 个有效文件`);
              
              // 显示文件预览卡片的函数（使用闭包捕获validFiles）
              const displayFilePreviews = (filesToDisplay) => {
                if (!filesToDisplay || filesToDisplay.length === 0) {
                  console.log('⚠️ 没有文件需要显示预览，validFiles为空');
                  return;
                }
                
                console.log(`📋 准备显示 ${filesToDisplay.length} 个文件的预览卡片`);
                
                // 延迟显示所有文件预览卡片（确保DOM已完全初始化）
                // 使用重试机制，确保文件预览卡片能够显示
                let retryCount = 0;
                const maxRetries = 30; // 增加重试次数到30次（最多3秒）
              
                const tryDisplayFilePreviews = () => {
                  // 重新检查DOM元素（可能在异步过程中已初始化）
                  if (!elements.filePreviewContainer) {
                    elements.filePreviewContainer = document.getElementById('filePreviewContainer');
                  }
                  if (!elements.filePreviewListInline) {
                    elements.filePreviewListInline = document.getElementById('filePreviewListInline');
                  }
                  
                  console.log(`尝试显示文件预览卡片 (重试 ${retryCount}/${maxRetries})`, {
                    filePreviewContainer: !!elements.filePreviewContainer,
                    filePreviewListInline: !!elements.filePreviewListInline,
                    filesToDisplayCount: filesToDisplay.length,
                    pendingFilesCount: pendingFiles.length
                  });
                  
                  // 如果DOM元素已就绪，显示所有文件预览卡片
                  if (elements.filePreviewContainer && elements.filePreviewListInline) {
                    console.log(`✅ DOM元素已就绪，开始显示文件预览卡片 (待显示文件数量: ${filesToDisplay.length})`);
                    
                    // 遍历待显示的文件，确保所有文件都显示预览
                    let displayedCount = 0;
                    for (const fileData of filesToDisplay) {
                      // 检查是否已显示（避免重复显示）
                      const fileId = fileData.fileInfo?.file_id;
                      if (fileId) {
                        const existingCard = document.getElementById(`file-card-${fileId}`);
                        if (!existingCard) {
                          try {
                            addFileToPreview(fileData);
                            displayedCount++;
                            console.log(`✅ 已显示文件预览卡片: ${fileData.fileInfo?.original_name}`);
                          } catch (error) {
                            console.error(`❌ 显示文件预览卡片失败: ${fileData.fileInfo?.original_name}`, error);
                            console.error('错误堆栈:', error.stack);
                          }
                        } else {
                          console.log(`文件预览卡片已存在，跳过: ${fileData.fileInfo?.original_name}`);
                        }
                      } else {
                        console.warn('⚠️ 文件数据缺少file_id:', fileData);
                      }
                    }
                    console.log(`✅ 已显示 ${displayedCount} 个文件的预览卡片 (总共 ${filesToDisplay.length} 个文件)`);
                    
                    // 更新发送按钮状态
                    if (typeof window.updateSendButtonState === 'function') {
                      window.updateSendButtonState();
                    }
                  } else {
                    // DOM元素未就绪，重试
                    retryCount++;
                    if (retryCount < maxRetries) {
                      console.log(`⚠️ DOM元素未就绪，重试显示文件预览 (${retryCount}/${maxRetries})`, {
                        filePreviewContainer: !!elements.filePreviewContainer,
                        filePreviewListInline: !!elements.filePreviewListInline,
                        filePreviewContainerId: elements.filePreviewContainer ? elements.filePreviewContainer.id : 'null',
                        filePreviewListInlineId: elements.filePreviewListInline ? elements.filePreviewListInline.id : 'null'
                      });
                      setTimeout(tryDisplayFilePreviews, 100); // 延迟100ms后重试
                    } else {
                      console.error('❌ DOM元素仍未就绪，无法显示文件预览卡片（已重试30次）');
                      console.error('filePreviewContainer:', elements.filePreviewContainer);
                      console.error('filePreviewListInline:', elements.filePreviewListInline);
                      console.error('filesToDisplay:', filesToDisplay);
                      console.error('pendingFiles:', pendingFiles);
                      console.error('尝试直接通过DOM查找元素...');
                      // 最后尝试：直接通过DOM查找元素
                      const container = document.getElementById('filePreviewContainer');
                      const list = document.getElementById('filePreviewListInline');
                      if (container && list) {
                        console.log('✅ 直接通过DOM找到元素，开始显示文件预览卡片');
                        // 更新elements引用
                        elements.filePreviewContainer = container;
                        elements.filePreviewListInline = list;
                        // 显示文件预览卡片
                        for (const fileData of filesToDisplay) {
                          const fileId = fileData.fileInfo?.file_id;
                          if (fileId) {
                            try {
                              addFileToPreview(fileData);
                              console.log(`✅ 已显示文件预览卡片: ${fileData.fileInfo?.original_name}`);
                            } catch (error) {
                              console.error(`❌ 显示文件预览卡片失败: ${fileData.fileInfo?.original_name}`, error);
                              console.error('错误详情:', error.message, error.stack);
                            }
                          }
                        }
                        // 更新发送按钮状态
                        if (typeof window.updateSendButtonState === 'function') {
                          window.updateSendButtonState();
                        }
                      } else {
                        console.error('❌ 即使直接通过DOM也无法找到元素');
                        console.error('尝试查找的元素ID: filePreviewContainer, filePreviewListInline');
                        // 尝试查找其他可能的元素
                        const allContainers = document.querySelectorAll('[id*="filePreview"]');
                        console.log('找到的所有包含filePreview的元素:', Array.from(allContainers).map(el => el.id));
                      }
                    }
                  }
                };
                
                // 首次尝试（延迟300ms，确保DOM已完全初始化）
                setTimeout(tryDisplayFilePreviews, 300);
              };
              
              // 立即调用显示函数（传入获取到的有效文件列表）
              console.log(`📋 调用displayFilePreviews，文件数量: ${validFiles.length}`);
              displayFilePreviews(validFiles);
            } catch (error) {
              console.error('获取文件信息失败:', error);
              // 即使获取文件信息失败，也继续处理，因为文件ID已经存储，可以在发送时使用
            }
          }
          
          // 注意：不要立即删除，等handleUserInput处理完后再删除
        } catch (error) {
          console.error('处理已上传文件ID失败:', error);
          sessionStorage.removeItem('uploadedFileIds');
        }
      }
      
      // 处理文件（兼容旧的方式，如果还有pendingFiles）
      if (pendingFilesData) {
        try {
          const fileDataArray = JSON.parse(pendingFilesData);
          console.log('检测到待发送文件:', fileDataArray.length, '个');
          
          // 将文件数据转换为File对象并添加到pendingFiles
          for (const fileData of fileDataArray) {
            // 从DataURL恢复文件
            const response = await fetch(fileData.data);
            const blob = await response.blob();
            const file = new File([blob], fileData.name, { type: fileData.type });
            
            // 生成文件ID
            const fileId = `temp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            
            // 添加到待发送文件列表
            pendingFiles.push({
              fileInfo: {
                file_id: fileId,
                original_name: fileData.name,
                file_size: fileData.size,
                file_type: fileData.type || 'application/octet-stream'
              },
              file: file,
              isTextFile: false,
              fileContent: null
            });
          }
          
          // 清除sessionStorage
          sessionStorage.removeItem('pendingFiles');
          
          // 显示文件预览卡片（从首页跳转过来时也需要显示）
          if (pendingFiles.length > 0) {
            console.log(`显示 ${pendingFiles.length} 个文件的预览卡片`);
            // 更新文件预览区域
            for (const fileData of pendingFiles) {
              addFileToPreview(fileData);
            }
          }
        } catch (error) {
          console.error('处理文件数据失败:', error);
          sessionStorage.removeItem('pendingFiles');
        }
      }
      
      // 保存解码后的文本到全局变量，供自动发送使用（不填充到输入框）
      // 即使decodedInputText为空字符串，也要保存，以便后续判断
      window._pendingInputText = decodedInputText || '';
      console.log('保存解码后的文本到全局变量:', decodedInputText || '(空)');
      
      // 保存文件ID数组到全局变量，供自动发送使用
      window._pendingFileIds = uploadedFileIdsForAutoSend || [];
      console.log('保存文件ID数组到全局变量:', window._pendingFileIds);
      
      // 自动发送（延迟一下，确保页面完全加载和MCP初始化完成）
      setTimeout(async () => {
        // 确保DOM元素已初始化（文件预览容器）
        if (!elements.filePreviewContainer || !elements.filePreviewListInline) {
          console.log('等待DOM元素初始化...');
          // 重新初始化elements（如果还未初始化）
          if (!elements.userInput) {
            initElements();
          }
          // 如果仍然不存在，等待一下
          let retries = 0;
          const maxRetries = 20; // 最多等待2秒
          while ((!elements.filePreviewContainer || !elements.filePreviewListInline) && retries < maxRetries) {
            await new Promise(resolve => setTimeout(resolve, 100));
            // 重新获取元素引用
            if (!elements.filePreviewContainer) {
              elements.filePreviewContainer = document.getElementById('filePreviewContainer');
            }
            if (!elements.filePreviewListInline) {
              elements.filePreviewListInline = document.getElementById('filePreviewListInline');
            }
            retries++;
          }
        }
        
        // 在DOM元素就绪后，显示文件预览卡片（如果之前没有显示）
        if (pendingFiles.length > 0 && elements.filePreviewContainer && elements.filePreviewListInline) {
          console.log(`在DOM就绪后显示 ${pendingFiles.length} 个文件的预览卡片`);
          for (const fileData of pendingFiles) {
            // 检查是否已显示（避免重复显示）
            const fileId = fileData.fileInfo?.file_id;
            if (fileId) {
              const existingCard = document.getElementById(`file-card-${fileId}`);
              if (!existingCard) {
                addFileToPreview(fileData);
              }
            }
          }
        }
        
        // 确保MCP初始化已完成
        if (!window._mcpInitialized) {
          console.log('等待MCP初始化完成...');
          let retries = 0;
          const maxRetries = 50; // 最多等待5秒
          while (!window._mcpInitialized && retries < maxRetries) {
            await new Promise(resolve => setTimeout(resolve, 100));
            retries++;
          }
          if (!window._mcpInitialized) {
            console.error('❌ MCP初始化超时，跳过自动发送');
            delete window._pendingInputText;
            delete window._pendingFileIds;
            return;
          }
          console.log('✅ MCP初始化已完成');
        }
        
        // 从首页跳转过来时，不填充输入框，直接使用保存的文本发送
        // 从全局变量获取保存的文本（已经是解码后的）
        const textToSend = window._pendingInputText || '';
        console.log('准备发送的文本（不填充到输入框）:', textToSend);
        
        // 从全局变量获取文件ID数组
        const fileIdsForSend = window._pendingFileIds || [];
        const finalHasFiles = pendingFiles.length > 0 || fileIdsForSend.length > 0;
        
        console.log('=== 自动发送检查 ===');
        console.log('textToSend (从首页获取，不填充到输入框):', textToSend);
        console.log('pendingFiles数量:', pendingFiles.length);
        console.log('fileIdsForSend数量:', fileIdsForSend.length);
        console.log('finalHasFiles:', finalHasFiles);
        console.log('window._mcpInitialized:', window._mcpInitialized);
        console.log('isProcessingInput:', isProcessingInput);
        console.log('isGenerating:', isGenerating);
        
        // 检查是否有有效的输入（文本或文件）
        // 从首页跳转过来时，不填充输入框，直接使用保存的文本
        const hasValidText = textToSend && textToSend.trim().length > 0;
        const hasValidFiles = finalHasFiles && (pendingFiles.length > 0 || fileIdsForSend.length > 0);
        const shouldAutoSend = hasValidText || hasValidFiles;
        
        console.log('自动发送判断:', {
          hasValidText,
          hasValidFiles,
          shouldAutoSend,
          textToSend: textToSend,
          textToSendLength: textToSend ? textToSend.length : 0,
          mcpInitialized: window._mcpInitialized
        });
        
        if (shouldAutoSend) {
          console.log('✅ 自动发送条件满足，准备发送（不填充到输入框）...');
          
          // 检查是否已经在处理中（防止重复发送）
          if (isProcessingInput || isGenerating) {
            console.warn('⚠️ 正在处理中，跳过自动发送');
            delete window._pendingInputText;
            return;
          }
          
          // 从首页跳转过来时，不填充输入框，直接使用保存的文本发送
          // 不需要检查输入框的值，因为我们已经有了要发送的文本
          
          // 清除URL参数，避免刷新时重复发送（在调用handleUserInput之前）
          if (window.history && window.history.replaceState) {
            window.history.replaceState({}, document.title, window.location.pathname);
            console.log('已清除URL参数');
          }
          
          // 等待一小段时间，确保DOM更新完成
          await new Promise(resolve => setTimeout(resolve, 200));
          
          // 确保MCP初始化已完成（如果还在初始化，等待一下）
          if (!window._mcpInitialized) {
            console.log('等待MCP初始化完成...');
            let retries = 0;
            const maxRetries = 50; // 最多等待5秒
            while (!window._mcpInitialized && retries < maxRetries) {
              await new Promise(resolve => setTimeout(resolve, 100));
              retries++;
            }
            if (!window._mcpInitialized) {
              console.error('❌ MCP初始化超时，跳过自动发送');
              delete window._pendingInputText;
              return;
            }
            console.log('✅ MCP初始化已完成，继续自动发送');
          }
          
          // 再次检查是否已经在处理中（防止在等待期间被其他操作占用）
          if (isProcessingInput || isGenerating) {
            console.warn('⚠️ 在等待期间，发现正在处理中，跳过自动发送');
            delete window._pendingInputText;
            return;
          }
          
          console.log('开始调用handleUserInput进行自动发送...');
          console.log('调用前状态检查:');
          console.log('  - isProcessingInput:', isProcessingInput);
          console.log('  - isGenerating:', isGenerating);
          console.log('  - window._mcpInitialized:', window._mcpInitialized);
          console.log('  - textToSend:', textToSend);
          console.log('  - finalHasFiles:', finalHasFiles);
          
          // 调用handleUserInput，传入保存的文本（不填充到输入框）
          try {
            await handleUserInput(textToSend);
            console.log('✅ handleUserInput 调用完成（使用传入的文本，不填充到输入框）');
          } catch (error) {
            console.error('❌ handleUserInput 调用失败:', error);
            // 重置状态，允许后续重试
            isProcessingInput = false;
            isGenerating = false;
          }
          
          // 清除全局变量
          delete window._pendingInputText;
          delete window._pendingFileIds;
        } else {
          console.warn('⚠️ 自动发送条件不满足，跳过自动发送');
          console.warn('原因:', {
            hasValidText,
            hasValidFiles,
            textToSend: textToSend,
            textToSendLength: textToSend ? textToSend.length : 0,
            pendingFilesCount: pendingFiles.length,
            fileIdsForSendCount: fileIdsForSend.length,
            finalHasFiles
          });
          // 清除全局变量
          delete window._pendingInputText;
          delete window._pendingFileIds;
        }
      }, 800); // 增加延迟到800ms，确保页面完全加载
    } else {
      console.log('未检测到从首页跳转，跳过自动填充和发送');
    }
  } catch (error) {
    console.error('处理首页输入失败:', error);
    console.error('错误堆栈:', error.stack);
  }
}

// 显示清空历史确认弹窗
function showClearHistoryConfirm() {
  return new Promise((resolve) => {
    const modal = document.getElementById('deleteConfirmModal');
    const messageEl = document.getElementById('deleteConfirmMessage');
    const confirmBtn = document.getElementById('confirmDeleteBtn');
    const cancelBtn = document.getElementById('cancelDeleteBtn');
    const titleEl = modal?.querySelector('.delete-modal-title');
    
    if (!modal || !messageEl || !confirmBtn || !cancelBtn) {
      // 如果弹窗元素不存在，降级使用原生confirm
      resolve(confirm('确定要清空所有会话历史吗？删除后将无法查看'));
      return;
    }
    
    // 更新标题和消息内容
    if (titleEl) {
      titleEl.textContent = '删除确认';
    }
    messageEl.textContent = '确定要清空所有会话历史吗?删除后将无法查看';
    
    // 更新确认按钮文字
    const originalConfirmText = confirmBtn.textContent;
    confirmBtn.textContent = '删除';
    
    // 显示弹窗
    modal.style.display = 'flex';
    
    // 确认删除
    const handleConfirm = () => {
      modal.style.display = 'none';
      confirmBtn.textContent = originalConfirmText; // 恢复原始文字
      confirmBtn.onclick = null;
      cancelBtn.onclick = null;
      modal.onclick = null;
      resolve(true);
    };
    
    // 取消删除
    const handleCancel = () => {
      modal.style.display = 'none';
      confirmBtn.textContent = originalConfirmText; // 恢复原始文字
      confirmBtn.onclick = null;
      cancelBtn.onclick = null;
      modal.onclick = null;
      resolve(false);
    };
    
    // 绑定事件（移除旧的事件监听器）
    confirmBtn.onclick = handleConfirm;
    cancelBtn.onclick = handleCancel;
    
    // 点击背景关闭
    modal.onclick = (e) => {
      if (e.target === modal) {
        handleCancel();
      }
    };
  });
}

// 编辑会话名称
async function editSessionName(sessionId, titleSpan, session) {
  // 获取当前会话标题
  const currentTitle = session.title || session.lastUserInput || 
    (session.createdAt ? `会话 ${new Date(session.createdAt).toLocaleString()}` : '新会话');
  
  const newTitle = prompt('请输入新的会话名称:', currentTitle);
  
  if (newTitle === null || newTitle.trim() === '') {
    return; // 用户取消或输入为空
  }
  
  const trimmedTitle = newTitle.trim();
  
  try {
    console.log('开始更新会话名称:', { sessionId, newTitle: trimmedTitle });
    
    // 调用服务端API更新会话名称
    const response = await fetch(`${CONFIG.mcpServerUrl}/api/sessions/${sessionId}`, {
      method: 'POST',  // 服务端使用POST方法更新会话
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ title: trimmedTitle })
    });
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const errorMsg = errorData.error || `HTTP ${response.status}`;
      throw new Error(errorMsg);
    }
    
    // 解析响应
    const updatedSession = await response.json();
    console.log('✅ 会话名称已更新到服务端:', updatedSession);
    
    // 更新当前会话对象
    if (currentSession && (currentSession.sessionId === sessionId || currentSession.session_id === sessionId)) {
      currentSession.title = trimmedTitle;
      // 如果服务端返回了完整的会话对象，同步更新
      if (updatedSession && updatedSession.title) {
        currentSession.title = updatedSession.title;
      }
    }
    
    // 更新显示
    const displayTitle = trimmedTitle.length > 12 ? trimmedTitle.substring(0, 12) + '···' : trimmedTitle;
    titleSpan.textContent = displayTitle;
    
    // 刷新会话列表以同步显示
    await loadSessionList();
    
    console.log('✅ 会话名称更新完成');
    
  } catch (error) {
    console.error('❌ 更新会话名称失败:', error);
    
    // 如果服务端更新失败，尝试更新本地存储（降级方案）
    try {
      const sessions = JSON.parse(localStorage.getItem('mcp_sessions') || '[]');
      const sessionIndex = sessions.findIndex(s => 
        (s.sessionId === sessionId || s.session_id === sessionId)
      );
      
      if (sessionIndex !== -1) {
        sessions[sessionIndex].title = trimmedTitle;
        localStorage.setItem('mcp_sessions', JSON.stringify(sessions));
        console.log('✅ 已更新本地存储中的会话名称');
        
        // 更新显示
        const displayTitle = trimmedTitle.length > 12 ? trimmedTitle.substring(0, 12) + '···' : trimmedTitle;
        titleSpan.textContent = displayTitle;
        
        // 更新当前会话对象
        if (currentSession && (currentSession.sessionId === sessionId || currentSession.session_id === sessionId)) {
          currentSession.title = trimmedTitle;
        }
        
        // 刷新会话列表
        await loadSessionList();
        
        alert('会话名称已更新到本地存储（服务端更新失败）');
      } else {
        throw new Error('本地存储中未找到该会话');
      }
    } catch (localError) {
      console.error('本地存储更新也失败:', localError);
      alert('更新会话名称失败: ' + error.message);
    }
  }
}

// 删除会话（从服务端数据库删除）
async function deleteSession(sessionId) {
  try {
    console.log('删除会话:', sessionId);
    console.log('调用服务端API删除数据库记录...');
    
    const response = await fetch(`${CONFIG.mcpServerUrl}/api/sessions/${sessionId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json'
      }
    });
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const errorMsg = errorData.error || `删除会话失败: HTTP ${response.status}`;
      console.error('服务端删除失败:', errorMsg);
      throw new Error(errorMsg);
    }
    
    const result = await response.json();
    console.log('✅ 会话已从数据库删除:', result);
    
    // 如果删除的是当前会话，创建新会话
    if (currentSession && currentSession.sessionId === sessionId) {
      console.log('删除的是当前会话，创建新会话');
      await createNewSession();
      elements.chatMessages.innerHTML = '';
    }
    
    // 刷新会话列表
    await loadSessionList();
    
    // 显示成功提示
    updateStatus('会话已删除', 'connected');
    setTimeout(() => {
      updateStatus('就绪', 'connected');
    }, 2000);
    
  } catch (error) {
    console.error('删除会话失败:', error);
    alert('删除会话失败: ' + error.message);
  }
}

function restoreHistoryMessage(msg) {
  if (msg.role === 'user') {
    addMessage(msg.role, msg.content);
    return;
  }
  if (msg.role === 'assistant') {
    const content = msg.content || '';
    const separator = '==JSON==';
    const separatorIndex = content.indexOf(separator);
    if (separatorIndex !== -1) {
      const thinkingContent = content.substring(0, separatorIndex).trim();
      const conclusionContent = content.substring(separatorIndex + separator.length).trim();
      addCombinedMessage(thinkingContent, conclusionContent, msg.capabilities);
    } else {
      const doubleLineBreakIndex = content.indexOf('\n\n');
      if (doubleLineBreakIndex !== -1 && doubleLineBreakIndex < content.length / 3 && !msg.artifact) {
        const thinkingContent = content.substring(0, doubleLineBreakIndex).trim();
        const conclusionContent = content.substring(doubleLineBreakIndex + 2).trim();
        addCombinedMessage(thinkingContent, conclusionContent, msg.capabilities);
      } else if (content) {
        addMessage(msg.role, content, 'normal', msg.capabilities);
      }
    }
    if (msg.artifact && msg.artifact.file_id) {
      addOrchestrateDownload(msg.artifact);
    }
    return;
  }
  addMessage(msg.role, msg.content);
}

async function restoreGeneratedFilesForSession(sessionId, history) {
  if (!sessionId || !CONFIG || !CONFIG.mcpServerUrl) return;
  const known = new Set();
  (history || []).forEach(msg => {
    if (msg.artifact && msg.artifact.file_id) known.add(msg.artifact.file_id);
  });
  try {
    const resp = await fetch(`${CONFIG.mcpServerUrl}/api/files?session_id=${encodeURIComponent(sessionId)}`);
    if (!resp.ok) return;
    const files = await resp.json();
    (files || []).forEach(file => {
      if (!file.file_id || known.has(file.file_id)) return;
      if (file.description !== 'orchestrator doc_writing') return;
      addOrchestrateDownload({
        file_id: file.file_id,
        filename: file.original_name,
        title: 'Word 文书',
        download_url: `/api/files/${file.file_id}/download`
      });
    });
  } catch (err) {
    console.warn('恢复会话生成文件失败:', err);
  }
}

// 加载会话（从服务端）
async function loadSession(sessionId) {
  try {
    const response = await fetch(`${CONFIG.mcpServerUrl}/api/sessions/${sessionId}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      }
    });
    
    if (!response.ok) {
      throw new Error(`加载会话失败: HTTP ${response.status}`);
    }
    
    const session = await response.json();
    currentSession = {
      sessionId: session.session_id,
      status: session.status || 'active',
      currentIntent: session.current_intent || null,
      collectedParameters: session.collected_parameters || {},
      missingParameters: session.missing_parameters || [],
      stage: session.stage || 'idle',
      contextCache: session.context_cache || {},
      createdAt: session.created_at,
      updatedAt: session.updated_at,
      conversationHistory: session.conversation_history || [],
      title: session.title || '',
      lastUserInput: session.last_user_input || ''
    };
    
  elements.chatMessages.innerHTML = '';
  console.log('恢复对话历史，消息数量:', currentSession.conversationHistory.length);
  currentSession.conversationHistory.forEach(restoreHistoryMessage);
  await restoreGeneratedFilesForSession(currentSession.sessionId, currentSession.conversationHistory);
  
  console.log('✅ 对话历史恢复完成');
  loadSessionList();
  } catch (error) {
    console.error('加载会话失败:', error);
    // 降级处理：如果session是对象（本地存储格式），直接使用
    if (typeof sessionId === 'object') {
      currentSession = sessionId;
      elements.chatMessages.innerHTML = '';
      // 使用相同的逻辑恢复对话历史
      currentSession.conversationHistory.forEach(restoreHistoryMessage);
      restoreGeneratedFilesForSession(currentSession.sessionId, currentSession.conversationHistory).catch(() => {});
      loadSessionList();
    }
  }
}

// 绑定事件
function bindEvents() {
  console.log('开始绑定事件...');
  console.log('elements对象:', elements);
  console.log('sendBtn元素:', elements.sendBtn);
  
  // 绑定发送按钮点击事件 - 只使用一种方式，避免重复触发
  if (elements.sendBtn) {
    // 移除所有旧的事件监听器（通过克隆节点）
    const newBtn = elements.sendBtn.cloneNode(true);
    elements.sendBtn.parentNode.replaceChild(newBtn, elements.sendBtn);
    elements.sendBtn = newBtn;
    
    // 只使用onclick属性绑定，避免重复触发
    elements.sendBtn.onclick = function(e) {
      e.preventDefault();
      e.stopPropagation();
      console.log('=== 发送按钮被点击 ===');
      console.log('按钮状态:', {
        disabled: elements.sendBtn.disabled,
        isProcessingInput: isProcessingInput,
        isGenerating: isGenerating
      });
      
      // 防止重复处理
      if (isProcessingInput || isGenerating) {
        console.warn('⚠️ 正在处理中，忽略重复点击');
        return false;
      }
      
      // 检查是否有输入（文本或文件），而不是依赖按钮的disabled状态
      // 这样可以避免按钮状态更新时序问题导致的无法发送
      const hasText = (elements.userInput?.value || '').trim().length > 0;
      let hasFiles = false;
      if (pendingFiles && pendingFiles.length > 0) {
        hasFiles = true;
      } else if (window.uploadedFileIds && Array.isArray(window.uploadedFileIds) && window.uploadedFileIds.length > 0) {
        hasFiles = true;
      } else {
        try {
          const uploadedFileIdsStr = sessionStorage.getItem('uploadedFileIds');
          if (uploadedFileIdsStr) {
            const uploadedFileIds = JSON.parse(uploadedFileIdsStr);
            if (uploadedFileIds && uploadedFileIds.length > 0) {
              hasFiles = true;
            }
          }
        } catch (e) {
          // 忽略错误
        }
      }
      
      const hasInput = hasText || hasFiles;
      
      if (!hasInput) {
        console.warn('⚠️ 没有输入内容，忽略点击');
        alert('请输入内容或上传文件');
        return false;
      }
      
      // 如果有输入，直接调用handleUserInput，不依赖按钮的disabled状态
      // 这样可以避免按钮状态更新时序问题导致的无法发送
      console.log('✅ 检测到输入内容，开始处理');
      console.log('准备调用handleUserInput函数...');
      console.log('handleUserInput类型:', typeof handleUserInput);
      console.log('window.handleUserInput类型:', typeof window.handleUserInput);
      
      // 确保使用正确的函数引用
      const handleInputFn = handleUserInput || window.handleUserInput;
      if (typeof handleInputFn !== 'function') {
        console.error('❌ handleUserInput不是一个函数！');
        alert('发送功能未初始化，请刷新页面重试');
        return false;
      }
      
      console.log('✅ handleUserInput函数可用，开始调用...');
      try {
        handleInputFn().catch(error => {
          console.error('❌ handleUserInput调用失败:', error);
          console.error('错误堆栈:', error.stack);
          alert('发送失败: ' + error.message);
        });
      } catch (error) {
        console.error('❌ 调用handleUserInput时发生同步错误:', error);
        console.error('错误堆栈:', error.stack);
        alert('发送失败: ' + error.message);
      }
      
      return false;
    };
    
    console.log('✅ 发送按钮事件已绑定（单一方式）');
    console.log('按钮onclick属性:', elements.sendBtn.onclick);
    console.log('按钮disabled状态:', elements.sendBtn.disabled);
  } else {
    console.error('❌ 无法绑定发送按钮事件：元素不存在');
    console.error('尝试重新查找元素...');
    const sendBtn = document.getElementById('sendBtn');
    if (sendBtn) {
      console.log('找到sendBtn元素，更新引用');
      elements.sendBtn = sendBtn;
      bindEvents(); // 递归调用
    } else {
      console.error('仍然找不到sendBtn元素');
      console.error('当前页面所有按钮:', document.querySelectorAll('button'));
    }
  }
  
  // 检查输入状态并更新发送按钮
  function updateSendButtonState() {
    if (!elements.userInput || !elements.sendBtn) {
      return;
    }
    
    const hasText = (elements.userInput.value || '').trim().length > 0;
    
    // 检查是否有文件（pendingFiles和uploadedFileIds）
    let hasFiles = false;
    if (pendingFiles && pendingFiles.length > 0) {
      hasFiles = true;
    } else {
      // 检查全局变量
      if (window.uploadedFileIds && Array.isArray(window.uploadedFileIds) && window.uploadedFileIds.length > 0) {
        hasFiles = true;
      } else {
        // 检查sessionStorage
        try {
          const uploadedFileIdsStr = sessionStorage.getItem('uploadedFileIds');
          if (uploadedFileIdsStr) {
            const uploadedFileIds = JSON.parse(uploadedFileIdsStr);
            if (uploadedFileIds && uploadedFileIds.length > 0) {
              hasFiles = true;
            }
          }
        } catch (e) {
          console.error('从sessionStorage获取uploadedFileIds失败:', e);
        }
      }
    }
    
    const hasInput = hasText || hasFiles;
    
    // 核心逻辑：当有输入（文本或文件）时，按钮应该可用
    // 特殊情况处理：
    // 1. 如果正在生成中，按钮状态由setStopButtonState管理（显示"停止生成"），不在这里修改
    // 2. 如果正在处理输入中（发送中），按钮状态由setLoadingState管理（显示"发送中..."），不在这里修改
    // 3. 其他情况：有输入则可用，无输入则禁用
    
    if (isGenerating || isProcessingInput) {
      // 如果正在生成或处理中，不更新按钮状态（由其他函数管理）
      console.log('正在生成或处理中，跳过按钮状态更新（由其他函数管理）');
      return;
    }
    
    // 正常情况：根据是否有输入来决定按钮状态
    // 有输入（文本或文件）时，按钮应该可用
    // 没有输入时，按钮应该禁用
    elements.sendBtn.disabled = !hasInput;
    
    console.log('更新发送按钮状态:', {
      hasText,
      hasFiles,
      pendingFilesCount: pendingFiles ? pendingFiles.length : 0,
      uploadedFileIdsCount: window.uploadedFileIds ? window.uploadedFileIds.length : 0,
      hasInput,
      isGenerating,
      isProcessingInput,
      disabled: elements.sendBtn.disabled
    });
  }
  
  // 将updateSendButtonState暴露到全局作用域，供其他函数调用
  window.updateSendButtonState = updateSendButtonState;
  
  // 初始化按钮状态
  updateSendButtonState();
  
  // 支持回车发送，Shift+Enter换行
  if (elements.userInput) {
    elements.userInput.onkeydown = (e) => {
      // Enter键发送（不是Shift+Enter）
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        console.log('Enter键被按下（发送）');
        // 检查输入框是否有内容且发送按钮未禁用
        const inputValue = (elements.userInput.value || '').trim();
        
        // 检查是否有文件
        let hasFiles = false;
        if (pendingFiles && pendingFiles.length > 0) {
          hasFiles = true;
        } else {
          if (window.uploadedFileIds && Array.isArray(window.uploadedFileIds) && window.uploadedFileIds.length > 0) {
            hasFiles = true;
          } else {
            try {
              const uploadedFileIdsStr = sessionStorage.getItem('uploadedFileIds');
              if (uploadedFileIdsStr) {
                const uploadedFileIds = JSON.parse(uploadedFileIdsStr);
                if (uploadedFileIds && uploadedFileIds.length > 0) {
                  hasFiles = true;
                }
              }
            } catch (e) {
              // 忽略错误
            }
          }
        }
        
        const hasInput = inputValue.length > 0 || hasFiles;
        
        // 只有当有输入且按钮未禁用且不在生成中时才发送
        if (hasInput && !elements.sendBtn.disabled && !isGenerating && !isProcessingInput) {
          handleUserInput();
        }
      }
      // Ctrl+Enter 或 Cmd+Enter 也可以发送（Mac系统）
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        console.log('Ctrl/Cmd+Enter键被按下（发送）');
        const inputValue = (elements.userInput.value || '').trim();
        
        // 检查是否有文件
        let hasFiles = false;
        if (pendingFiles && pendingFiles.length > 0) {
          hasFiles = true;
        } else {
          if (window.uploadedFileIds && Array.isArray(window.uploadedFileIds) && window.uploadedFileIds.length > 0) {
            hasFiles = true;
          } else {
            try {
              const uploadedFileIdsStr = sessionStorage.getItem('uploadedFileIds');
              if (uploadedFileIdsStr) {
                const uploadedFileIds = JSON.parse(uploadedFileIdsStr);
                if (uploadedFileIds && uploadedFileIds.length > 0) {
                  hasFiles = true;
                }
              }
            } catch (e) {
              // 忽略错误
            }
          }
        }
        
        const hasInput = inputValue.length > 0 || hasFiles;
        
        if (hasInput && !elements.sendBtn.disabled && !isGenerating && !isProcessingInput) {
          handleUserInput();
        }
      }
    };
    console.log('输入框键盘事件已绑定');
    
    // 监听输入框变化，实时更新按钮状态
    elements.userInput.addEventListener('input', () => {
      console.log('输入框内容变化，更新按钮状态');
      updateSendButtonState();
      autoResizeTextarea(elements.userInput);
    });
    
    elements.userInput.addEventListener('paste', () => {
      setTimeout(() => {
        console.log('粘贴完成，更新按钮状态');
        updateSendButtonState();
        autoResizeTextarea(elements.userInput);
      }, 10);
    });
    
    // 监听输入框获得焦点时，也更新一次按钮状态
    elements.userInput.addEventListener('focus', () => {
      console.log('输入框获得焦点，更新按钮状态');
      updateSendButtonState();
    });
  } else {
    console.error('无法绑定输入框事件：元素不存在');
  }
  
  // 支持粘贴时自动调整高度（已在上面处理）
  
  // 输入时自动调整高度（已在上面处理）
  
  // 文件上传按钮点击事件
  if (elements.fileUploadBtn) {
  elements.fileUploadBtn.onclick = () => {
      console.log('文件上传按钮被点击');
      if (elements.fileInput) {
    elements.fileInput.click();
      } else {
        console.error('fileInput 元素不存在');
        alert('文件输入框未找到，请刷新页面重试');
      }
  };
    console.log('✅ 文件上传按钮事件已绑定');
  } else {
    console.error('❌ fileUploadBtn 元素不存在');
  }
  
  // 文件选择事件
  if (elements.fileInput) {
  elements.fileInput.onchange = (e) => {
      console.log('文件选择事件触发');
    const files = Array.from(e.target.files);
      console.log(`选择了 ${files.length} 个文件`);
      
      if (files.length === 0) {
        console.warn('未选择任何文件');
        return;
      }
      
      files.forEach(async (file, index) => {
        console.log(`处理文件 ${index + 1}/${files.length}: ${file.name} (${file.size} 字节)`);
        
        // 检查文件大小（限制为1MB，与首页一致）
        const maxSize = 1 * 1024 * 1024; // 1MB
        if (file.size > maxSize) {
          console.error(`文件 ${file.name} 太大 (${file.size} 字节)，超过限制 (${maxSize} 字节)`);
          addMessage('assistant', `文件 ${file.name} 太大（${(file.size / 1024 / 1024).toFixed(2)}MB），请选择小于1MB的文件`, 'error');
          return;
        }
        
        // 先创建临时文件信息，用于显示上传中的文件卡片
        const tempFileId = `temp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        const tempFileData = {
          file: file,
          fileInfo: {
            file_id: tempFileId,
            original_name: file.name,
            file_size: file.size,
            file_type: file.type || 'application/octet-stream'
          },
          fileContent: null,
          isTextFile: false
        };
        
        // 立即显示文件卡片（上传中状态）
        addFileToPreview(tempFileData);
        updateFileCardStatus(tempFileId, 'uploading');
        
        try {
          // 上传文件到服务器
          const fileInfo = await uploadFileToServer(file, currentSession?.sessionId);
          
          if (fileInfo && fileInfo.file_id) {
            console.log(`✅ 文件 ${file.name} 上传成功，文件ID: ${fileInfo.file_id}`);
            
            // 更新文件数据，使用服务端返回的真实文件ID
            const fileData = {
              file: file,
              fileInfo: fileInfo,
              fileContent: null,  // 文本文件内容稍后读取
              isTextFile: false
            };
            
            // 如果是文本文件，读取内容
            const textExtensions = ['.txt', '.md', '.json', '.csv', '.log'];
            const fileExt = '.' + (fileInfo.file_type || file.name.split('.').pop() || '').toLowerCase();
            if (textExtensions.includes(fileExt)) {
              fileData.isTextFile = true;
              // 异步读取文件内容
              readFileWithEncoding(file, (text, encoding) => {
                if (text && text.trim()) {
                  const encodingInfo = encoding && encoding !== 'UTF-8' && !encoding.includes('可能不正确') 
                    ? ` (编码: ${encoding})` 
                    : '';
                  fileData.fileContent = `[文件内容] ${file.name}${encodingInfo}\n${text}`;
                  // 更新预览项显示（如果已创建）
                  updateFilePreviewItem(fileInfo.file_id, fileData);
                }
              });
            }
            
            // 无论文件ID是否相同，都先移除临时文件卡片，然后创建新卡片
            // 这样可以确保不会出现重复的卡片
            const tempCard = document.getElementById(`file-card-${tempFileId}`);
            if (tempCard) {
              tempCard.remove();
              console.log(`✅ 已移除临时文件卡片: ${tempFileId}`);
            }
            
            // 等待DOM更新后再创建新卡片，确保临时卡片已完全移除
            setTimeout(() => {
              // 再次检查是否已存在（防止重复）- 双重检查
              const existingCardById = document.getElementById(`file-card-${fileInfo.file_id}`);
              const existingCardByData = elements.filePreviewListInline?.querySelector(`[data-file-id="${fileInfo.file_id}"]`);
              
              if (!existingCardById && !existingCardByData) {
                addFileToPreview(fileData);
                updateFileCardStatus(fileInfo.file_id, 'success');
                console.log(`✅ 已创建新文件卡片: ${fileInfo.file_id}`);
              } else {
                console.log(`⚠️ 文件卡片已存在，跳过创建: ${fileInfo.file_id}`, {
                  byId: !!existingCardById,
                  byData: !!existingCardByData
                });
                // 如果卡片已存在，直接更新状态
                updateFileCardStatus(fileInfo.file_id, 'success');
              }
            }, 100);
            
            // 添加到待发送文件列表
            pendingFiles.push(fileData);
            
            // 更新发送按钮状态
            updateSendButtonState();
            
          } else {
            throw new Error('文件上传失败：未返回文件信息');
          }
        } catch (error) {
          console.error(`文件 ${file.name} 上传失败:`, error);
          
          // 更新文件卡片状态为失败
          updateFileCardStatus(tempFileId, 'error');
          
          // 3秒后自动移除失败的文件卡片
          setTimeout(() => {
            removeFileFromPreview(tempFileId);
          }, 3000);
          
          addMessage('assistant', `文件 ${file.name} 上传失败: ${error.message}`, 'error');
          // 即使上传失败，也要更新按钮状态（可能之前有文件）
          updateSendButtonState();
        }
      });
      
      // 清空文件选择，允许重复选择同一文件
      e.target.value = '';
    };
    console.log('✅ 文件选择事件已绑定');
  } else {
    console.error('❌ fileInput 元素不存在');
  }
  
  // 清除所有文件按钮事件
  if (elements.clearFilesBtn) {
    elements.clearFilesBtn.onclick = () => {
      console.log('清除所有文件按钮被点击');
      clearAllFiles();
    };
    console.log('✅ 清除文件按钮事件已绑定');
  } else {
    console.error('❌ clearFilesBtn 元素不存在');
  }
  
  elements.newSessionBtn.onclick = async () => {
    await createNewSession();
    elements.chatMessages.innerHTML = '';
    await loadSessionList();
  };
  
  elements.clearHistoryBtn.onclick = async () => {
    const confirmed = await showClearHistoryConfirm();
    if (!confirmed) {
      return;
    }
    
      try {
        const response = await fetch(`${CONFIG.mcpServerUrl}/api/sessions/all`, {
          method: 'DELETE'
        });
        if (response.ok) {
          localStorage.removeItem('mcp_init_message_shown'); // 重置初始化消息标记
          await createNewSession();
          elements.chatMessages.innerHTML = '';
          await loadSessionList();
        } else {
          throw new Error('删除会话失败');
        }
      } catch (error) {
        console.error('清空会话历史失败:', error);
        // 降级到本地存储
      localStorage.removeItem('mcp_sessions');
        localStorage.removeItem('mcp_init_message_shown');
        await createNewSession();
      elements.chatMessages.innerHTML = '';
        await loadSessionList();
    }
  };
}

// 自动调整文本框高度
function autoResizeTextarea(textarea) {
  textarea.style.height = 'auto';
  const maxHeight = 200; // 最大高度（约6-7行）
  const newHeight = Math.min(textarea.scrollHeight, maxHeight);
  textarea.style.height = newHeight + 'px';
  textarea.style.overflowY = newHeight >= maxHeight ? 'auto' : 'hidden';
}

// 检测文本是否包含乱码
function detectGarbledText(text) {
  if (!text || text.length === 0) return false;
  
  // 1. 检查是否包含大量替换字符（），这是编码错误的典型特征
  const replacementCharCount = (text.match(/\uFFFD/g) || []).length;
  const replacementRatio = replacementCharCount / text.length;
  if (replacementRatio > 0.01) { // 超过1%的替换字符
    console.log(`检测到 ${replacementCharCount} 个替换字符 (比例: ${(replacementRatio * 100).toFixed(2)}%)`);
    return true;
  }
  
  // 2. 检查是否包含大量不可打印字符（排除常见的中文、英文、标点、换行等）
  // 允许的字符范围：ASCII可打印字符、中文、日文、韩文、常见标点、换行符等
  const allowedChars = /[\x20-\x7E\u4E00-\u9FFF\u3000-\u303F\uFF00-\uFFEF\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF\n\r\t]/g;
  const allowedCount = (text.match(allowedChars) || []).length;
  const allowedRatio = allowedCount / text.length;
  
  // 如果允许的字符比例低于85%，可能是乱码
  if (allowedRatio < 0.85) {
    console.log(`允许字符比例: ${(allowedRatio * 100).toFixed(2)}%，可能包含乱码`);
    return true;
  }
  
  // 3. 检查是否包含连续的乱码模式（如连续的不可打印字符）
  const suspiciousPattern = /[^\x20-\x7E\u4E00-\u9FFF\u3000-\u303F\uFF00-\uFFEF\n\r\t]{3,}/g;
  if (suspiciousPattern.test(text)) {
    console.log('检测到可疑的乱码模式');
    return true;
  }
  
  return false;
}

// 读取文件并尝试多种编码
function readFileWithEncoding(file, callback) {
  console.log(`开始读取文件: ${file.name} (${file.size} 字节, 类型: ${file.type})`);
  
  // 首先尝试使用ArrayBuffer读取，这样可以尝试多种编码
  const arrayReader = new FileReader();
  
  arrayReader.onload = (e) => {
    const arrayBuffer = e.target.result;
    const uint8Array = new Uint8Array(arrayBuffer);
    
    // 尝试的编码列表（按优先级排序）
    const encodings = [
      { name: 'UTF-8', decoder: null }, // UTF-8使用FileReader直接读取
      { name: 'GBK', decoder: 'gbk' },
      { name: 'GB18030', decoder: 'gb18030' }, // GB18030是GBK的超集，支持更多字符
      { name: 'GB2312', decoder: 'gb2312' },
      { name: 'Big5', decoder: 'big5' }
    ];
    
    let currentIndex = 0;
    
    function tryNextEncoding() {
      if (currentIndex >= encodings.length) {
        // 所有编码都失败，使用UTF-8作为最后尝试
        console.warn('所有编码尝试失败，使用UTF-8作为最后尝试');
        const reader = new FileReader();
        reader.onload = (event) => {
          const text = event.target.result;
          console.log('使用UTF-8读取文件完成（可能不正确）');
          callback(text, 'UTF-8 (可能不正确)');
        };
        reader.onerror = (error) => {
          console.error('文件读取失败:', error);
          callback('文件读取失败: ' + (error.message || '未知错误'), 'unknown');
        };
        reader.readAsText(file, 'UTF-8');
        return;
      }
      
      const encoding = encodings[currentIndex];
      console.log(`尝试编码: ${encoding.name}`);
      
      if (encoding.name === 'UTF-8') {
        // UTF-8使用FileReader直接读取
        const reader = new FileReader();
        reader.onload = (event) => {
          const text = event.target.result;
          console.log(`使用UTF-8读取，内容长度: ${text.length} 字符`);
          
          // 检测是否乱码
          if (detectGarbledText(text) && currentIndex < encodings.length - 1) {
            console.log('UTF-8读取结果可能包含乱码，尝试下一个编码...');
            currentIndex++;
            tryNextEncoding();
          } else {
            console.log(`✅ 使用编码 ${encoding.name} 读取文件成功`);
            callback(text, encoding.name);
          }
        };
        reader.onerror = (error) => {
          console.warn(`UTF-8读取失败:`, error);
          currentIndex++;
          tryNextEncoding();
        };
        reader.readAsText(file, 'UTF-8');
      } else {
        // 其他编码使用TextDecoder
        try {
          const decoder = new TextDecoder(encoding.decoder, { fatal: false });
          const decodedText = decoder.decode(uint8Array);
          
          console.log(`使用${encoding.name}解码，内容长度: ${decodedText.length} 字符`);
          
          // 检测是否乱码
          if (detectGarbledText(decodedText) && currentIndex < encodings.length - 1) {
            console.log(`${encoding.name}解码结果可能包含乱码，尝试下一个编码...`);
            currentIndex++;
            tryNextEncoding();
          } else {
            console.log(`✅ 使用编码 ${encoding.name} 读取文件成功`);
            callback(decodedText, encoding.name);
          }
        } catch (err) {
          console.warn(`TextDecoder不支持${encoding.name}或解码失败:`, err);
          currentIndex++;
          tryNextEncoding();
        }
      }
    }
    
    // 开始尝试第一个编码
    tryNextEncoding();
  };
  
  arrayReader.onerror = (error) => {
    console.error('读取文件为ArrayBuffer失败:', error);
    // 降级到直接使用UTF-8读取
    const reader = new FileReader();
    reader.onload = (event) => {
      callback(event.target.result, 'UTF-8');
    };
    reader.onerror = () => {
      callback('文件读取失败', 'unknown');
    };
    reader.readAsText(file, 'UTF-8');
  };
  
  // 读取为ArrayBuffer
  arrayReader.readAsArrayBuffer(file);
}

// 页面加载时初始化 - 使用多种方式确保执行
function startInit() {
  console.log('=== 开始初始化流程 ===');
  console.log('document.readyState:', document.readyState);
  console.log('当前URL:', window.location.href);
  
  // 延迟一点确保DOM完全加载
  setTimeout(() => {
    console.log('执行初始化...');
    init().catch(error => {
      console.error('初始化失败:', error);
      alert('初始化失败: ' + error.message);
    });
  }, 100);
}

// 方式1: DOMContentLoaded
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startInit);
  console.log('等待DOMContentLoaded事件...');
} else {
  // DOM已经加载完成
  console.log('DOM已加载，立即初始化');
  startInit();
}

// 方式2: window.onload（备用）
window.addEventListener('load', function() {
  console.log('window.load事件触发');
  // 如果还没有初始化，再次尝试
  if (!window._mcpInitialized) {
    console.log('通过window.load事件初始化');
    startInit();
  }
});

// 方式3: 立即执行（如果DOM已准备好）
if (document.body) {
  console.log('document.body已存在，尝试立即初始化');
  startInit();
}

// ========== 文件上传和查询功能 ==========

// 上传文件到服务器
async function uploadFileToServer(file, sessionId = null, description = null) {
  const formData = new FormData();
  formData.append('file', file);
  if (sessionId) {
    formData.append('session_id', sessionId);
  }
  if (description) {
    formData.append('description', description);
  }
  
  const response = await fetch(`${CONFIG.mcpServerUrl}/api/files/upload`, {
    method: 'POST',
    body: formData
  });
  
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
  }
  
  const fileInfo = await response.json();
  return fileInfo;
}

// 获取文件列表
async function getFileList(sessionId = null, limit = 100, offset = 0) {
  let url = `${CONFIG.mcpServerUrl}/api/files?limit=${limit}&offset=${offset}`;
  if (sessionId) {
    url += `&session_id=${encodeURIComponent(sessionId)}`;
  }
  
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  
  const files = await response.json();
  return files;
}

// 获取文件信息
async function getFileInfo(fileId) {
  const response = await fetch(`${CONFIG.mcpServerUrl}/api/files/${fileId}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  
  const fileInfo = await response.json();
  return fileInfo;
}

// 下载文件（统一使用 downloadFileFromCard 实现）
async function downloadFile(fileId, originalName) {
  // 直接调用优化后的下载函数，保持代码一致性
  return downloadFileFromCard(fileId, originalName);
}

// 删除文件
async function deleteFile(fileId) {
  const response = await fetch(`${CONFIG.mcpServerUrl}/api/files/${fileId}`, {
    method: 'DELETE'
  });
  
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
  }
  
  const result = await response.json();
  return result;
}

// ========== 文件预览功能 ==========

// 辅助函数：获取文件类型
function getFileType(fileName) {
  const ext = fileName.split('.').pop()?.toUpperCase() || 'FILE';
  const typeMap = {
    'DOC': 'DOC',
    'DOCX': 'DOCX',
    'PDF': 'PDF',
    'TXT': 'TXT',
    'XLS': 'XLS',
    'XLSX': 'XLSX',
    'PPT': 'PPT',
    'PPTX': 'PPTX',
    'PNG': 'PNG',
    'JPG': 'JPG',
    'JPEG': 'JPEG'
  };
  return typeMap[ext] || ext;
}

// 辅助函数：格式化文件大小
function formatFileSize(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// 创建文件卡片（与首页相同效果）
function createFileCardInline(fileData, fileId) {
  const fileInfo = fileData.fileInfo;
  const fileName = fileInfo.original_name || '未命名文件';
  const fileType = getFileType(fileName);
  const fileSize = formatFileSize(fileInfo.file_size || 0);
  
  const card = document.createElement('div');
  card.className = 'file-card';
  card.id = `file-card-${fileId}`;
  card.dataset.fileId = fileId;
  
  // 设置文件完整信息用于tooltip
  const fullInfo = `${fileName}\n${fileType} ${fileSize}`;
  card.setAttribute('data-file-info', fullInfo);
  card.setAttribute('title', '');
  
  // 文件图标
  const icon = document.createElement('div');
  icon.className = 'file-icon';
  icon.innerHTML = '📄';
  
  // 文件信息
  const info = document.createElement('div');
  info.className = 'file-info';
  
  const name = document.createElement('div');
  name.className = 'file-name';
  // 限制显示为12个字符，超过部分用"···"表示
  const maxDisplayLength = 12;
  if (fileName.length > maxDisplayLength) {
    name.textContent = fileName.substring(0, maxDisplayLength) + '···';
  } else {
    name.textContent = fileName;
  }
  
  const meta = document.createElement('div');
  meta.className = 'file-meta';
  meta.textContent = `${fileType} ${fileSize}`;
  
  info.appendChild(name);
  info.appendChild(meta);
  
  // 删除按钮
  const removeBtn = document.createElement('button');
  removeBtn.className = 'file-remove';
  removeBtn.innerHTML = '×';
  removeBtn.onclick = (e) => {
    e.stopPropagation();
    removeFileFromPreview(fileId);
  };
  
  card.appendChild(icon);
  card.appendChild(info);
  card.appendChild(removeBtn);
  
  return card;
}

// 添加文件到预览区域（使用与首页相同的文件卡片效果）
function addFileToPreview(fileData) {
  const fileInfo = fileData.fileInfo;
  const fileId = fileInfo.file_id;
  
  // 优先使用内联预览容器（输入框内部左上角）
  if (elements.filePreviewContainer && elements.filePreviewListInline) {
    // 检查是否已存在（通过ID和data-file-id属性双重检查）
    const existingCardById = document.getElementById(`file-card-${fileId}`);
    const existingCardByData = elements.filePreviewListInline.querySelector(`[data-file-id="${fileId}"]`);
    
    if (existingCardById || existingCardByData) {
      console.log('文件卡片已存在，跳过:', fileId, {
        byId: !!existingCardById,
        byData: !!existingCardByData
      });
      return;
    }
    
    // 创建文件卡片
    const fileCard = createFileCardInline(fileData, fileId);
    elements.filePreviewListInline.appendChild(fileCard);
    
    // 显示预览容器
    elements.filePreviewContainer.style.display = 'block';
    
    // 调整输入框padding-top，为文件预览留出空间（与首页一致）
    if (elements.userInput) {
      const fileListHeight = elements.filePreviewListInline.scrollHeight;
      const totalHeight = fileListHeight + 20; // 额外20px间距（与首页一致）
      elements.userInput.style.paddingTop = `${totalHeight}px`;
      console.log(`调整输入框padding-top: ${totalHeight}px (文件列表高度: ${fileListHeight}px + 20px间距)`);
    }
    
    console.log(`✅ 已添加文件卡片到内联预览: ${fileInfo.original_name}`);
    return;
  }
  
  // 降级方案：使用原有的预览区域（如果内联容器不存在）
  // 注意：如果内联容器存在，不应该同时使用这个区域，避免重复显示
  if (!elements.filePreviewContainer && !elements.filePreviewListInline) {
    if (elements.filePreviewArea && elements.filePreviewList) {
      // 检查是否已存在（通过ID和文件名双重检查）
      const existingItemById = document.getElementById(`file-preview-${fileId}`);
      const existingItemByName = Array.from(elements.filePreviewList.children).find(item => {
        const nameDiv = item.querySelector('.file-preview-name');
        return nameDiv && nameDiv.textContent.includes(fileInfo.original_name);
      });
      
      if (existingItemById || existingItemByName) {
        console.log('文件预览项已存在，跳过:', fileId, {
          byId: !!existingItemById,
          byName: !!existingItemByName
        });
        return;
      }
      
      // 创建预览项
      const previewItem = document.createElement('div');
      previewItem.className = 'file-preview-item';
      previewItem.id = `file-preview-${fileId}`;
      
      const fileSize = (fileInfo.file_size / 1024).toFixed(2);
      const fileName = fileInfo.original_name || '未命名文件';
      
      previewItem.innerHTML = `
        <div class="file-preview-info">
          <span class="file-preview-icon">📎</span>
          <div class="file-preview-details">
            <div class="file-preview-name" title="${fileName}">${fileName}</div>
            <div class="file-preview-size">${fileSize} KB</div>
          </div>
        </div>
        <button class="file-preview-remove" onclick="removeFileFromPreview('${fileId}')" title="移除">✕</button>
      `;
      
      elements.filePreviewList.appendChild(previewItem);
      elements.filePreviewArea.style.display = 'block';
      
      console.log(`✅ 已添加文件到预览区域: ${fileName}`);
    } else {
      console.error('文件预览区域元素不存在');
    }
  } else {
    // 如果内联容器存在，不应该使用原有的预览区域
    console.log('内联预览容器已存在，跳过原有预览区域');
  }
}

// 创建内联文件卡片（用于输入框内的文件预览）
function createFileCardInline(fileData, fileId) {
  const fileInfo = fileData.fileInfo;
  const fileName = fileInfo.original_name || '未命名文件';
  const fileSize = fileInfo.file_size || 0;
  const fileType = fileInfo.file_type || 'application/octet-stream';
  
  // 获取文件扩展名
  const fileExtension = fileName.split('.').pop()?.toUpperCase() || 'FILE';
  const typeMap = {
    'DOC': 'DOC',
    'DOCX': 'DOCX',
    'PDF': 'PDF',
    'TXT': 'TXT',
    'XLS': 'XLS',
    'XLSX': 'XLSX',
    'PPT': 'PPT',
    'PPTX': 'PPTX'
  };
  const displayType = typeMap[fileExtension] || fileExtension;
  
  // 格式化文件大小
  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + sizes[i];
  };
  const displaySize = formatFileSize(fileSize);
  
  // 创建文件卡片
  const card = document.createElement('div');
  card.className = 'file-card';
  card.id = `file-card-${fileId}`;
  card.setAttribute('data-file-id', fileId);
  
  // 设置文件完整信息用于tooltip
  const fullInfo = `${fileName}\n${displayType} ${displaySize}`;
  card.setAttribute('data-file-info', fullInfo);
  card.setAttribute('title', '');
  
  // 文件图标
  const icon = document.createElement('div');
  icon.className = 'file-icon';
  icon.innerHTML = '📄';
  
  // 文件信息
  const info = document.createElement('div');
  info.className = 'file-info';
  
  const name = document.createElement('div');
  name.className = 'file-name';
  // 限制显示为12个字符，超过部分用"···"表示
  const maxDisplayLength = 12;
  if (fileName.length > maxDisplayLength) {
    name.textContent = fileName.substring(0, maxDisplayLength) + '···';
  } else {
    name.textContent = fileName;
  }
  
  const meta = document.createElement('div');
  meta.className = 'file-meta';
  meta.textContent = `${displayType} ${displaySize}`;
  
  info.appendChild(name);
  info.appendChild(meta);
  
  // 删除按钮
  const removeBtn = document.createElement('button');
  removeBtn.className = 'file-remove';
  removeBtn.innerHTML = '×';
  removeBtn.onclick = (e) => {
    e.stopPropagation();
    removeFileFromPreview(fileId);
  };
  
  card.appendChild(icon);
  card.appendChild(info);
  card.appendChild(removeBtn);
  
  return card;
}

// 更新文件卡片状态（上传中、成功、失败）
function updateFileCardStatus(fileId, status) {
  const fileCard = document.getElementById(`file-card-${fileId}`);
  if (fileCard) {
    fileCard.classList.remove('uploading', 'success', 'error');
    fileCard.classList.add(status);
    
    // 添加或更新状态图标
    let statusIcon = fileCard.querySelector('.file-status-icon');
    if (!statusIcon) {
      statusIcon = document.createElement('div');
      statusIcon.className = 'file-status-icon';
      const fileIcon = fileCard.querySelector('.file-icon');
      if (fileIcon) {
        fileIcon.appendChild(statusIcon);
      }
    }
    
    // 设置状态图标内容（与首页一致）
    if (status === 'uploading') {
      statusIcon.innerHTML = '⏳';
      statusIcon.title = '上传中...';
      statusIcon.style.display = 'flex';
    } else if (status === 'success') {
      statusIcon.innerHTML = '✓';
      statusIcon.title = '上传成功';
      statusIcon.style.display = 'flex';
    } else if (status === 'error') {
      statusIcon.innerHTML = '✗';
      statusIcon.title = '上传失败';
      statusIcon.style.display = 'flex';
    } else {
      statusIcon.style.display = 'none';
    }
  }
}

// 更新文件预览项（用于更新文本文件内容）
function updateFilePreviewItem(fileId, fileData) {
  // 预览项已经创建，这里可以更新显示状态（如显示"已读取内容"）
  const previewItem = document.getElementById(`file-preview-${fileId}`);
  if (previewItem && fileData.fileContent) {
    const detailsDiv = previewItem.querySelector('.file-preview-details');
    if (detailsDiv) {
      const sizeDiv = detailsDiv.querySelector('.file-preview-size');
      if (sizeDiv) {
        const fileSize = (fileData.fileInfo.file_size / 1024).toFixed(2);
        sizeDiv.textContent = `${fileSize} KB (已读取内容)`;
      }
    }
  }
}

// 从预览区域移除文件
function removeFileFromPreview(fileId) {
  // 从pendingFiles中移除
  pendingFiles = pendingFiles.filter(f => f.fileInfo.file_id !== fileId);
  
  // 从全局变量中移除（如果存在）
  if (window.uploadedFileIds && Array.isArray(window.uploadedFileIds)) {
    window.uploadedFileIds = window.uploadedFileIds.filter(id => id !== fileId);
    // 更新sessionStorage
    if (window.uploadedFileIds.length > 0) {
      sessionStorage.setItem('uploadedFileIds', JSON.stringify(window.uploadedFileIds));
    } else {
      sessionStorage.removeItem('uploadedFileIds');
    }
    console.log('已从全局变量和sessionStorage移除文件ID:', fileId);
  }
  
  // 从内联预览容器中移除（优先）
  const fileCard = document.getElementById(`file-card-${fileId}`);
  if (fileCard) {
    fileCard.remove();
    
    // 如果没有文件了，隐藏预览容器并恢复输入框padding
    if (pendingFiles.length === 0) {
      if (elements.filePreviewContainer) {
        elements.filePreviewContainer.style.display = 'none';
      }
      if (elements.userInput) {
        elements.userInput.style.paddingTop = '12px';
      }
    } else {
      // 调整输入框padding-top
      if (elements.userInput && elements.filePreviewListInline) {
        const fileListHeight = elements.filePreviewListInline.scrollHeight;
        const totalHeight = fileListHeight + 20;
        elements.userInput.style.paddingTop = `${totalHeight}px`;
      }
    }
  }
  
  // 从原有的预览区域中移除（降级方案）
  const previewItem = document.getElementById(`file-preview-${fileId}`);
  if (previewItem) {
    previewItem.remove();
    
    // 如果没有文件了，隐藏预览区域
    if (pendingFiles.length === 0) {
      if (elements.filePreviewArea) {
        elements.filePreviewArea.style.display = 'none';
      }
    }
  }
  
  // 更新发送按钮状态
  if (typeof window.updateSendButtonState === 'function') {
    window.updateSendButtonState();
  }
}

// 清除所有文件
function clearAllFiles() {
  pendingFiles = [];
  
  // 清除内联预览容器
  if (elements.filePreviewListInline) {
    elements.filePreviewListInline.innerHTML = '';
  }
  if (elements.filePreviewContainer) {
    elements.filePreviewContainer.style.display = 'none';
  }
  
  // 清除原有的预览区域
  if (elements.filePreviewList) {
    elements.filePreviewList.innerHTML = '';
  }
  if (elements.filePreviewArea) {
    elements.filePreviewArea.style.display = 'none';
  }
  
  // 恢复输入框padding
  if (elements.userInput) {
    elements.userInput.style.paddingTop = '12px';
  }
  
  // 更新发送按钮状态
  if (typeof window.updateSendButtonState === 'function') {
    window.updateSendButtonState();
  }
}

// 确保文件预览相关函数在全局作用域可访问（用于内联onclick）
if (typeof window !== 'undefined') {
  window.removeFileFromPreview = removeFileFromPreview;
  window.clearAllFiles = clearAllFiles;
}

