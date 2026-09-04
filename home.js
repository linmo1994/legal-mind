// 首页功能实现
const HOME_JS_VERSION = '2026.01.16-1';
console.log(`[HOME] home.js loaded, version=${HOME_JS_VERSION}`);
let selectedFiles = [];
let uploadedFileIds = []; // 存储已上传的文件ID映射 {fileIndex: fileId}

// 配置缓存（减少重复请求 config.json）
const CONFIG_CACHE_KEY = 'config_cache_v1';
let configLoadPromise = null;

async function loadConfigCached() {
  if (configLoadPromise) {
    return configLoadPromise;
  }
  if (window.__configLoadPromise) {
    return window.__configLoadPromise;
  }
  if (window.__configCacheData) {
    return window.__configCacheData;
  }
  const cached = sessionStorage.getItem(CONFIG_CACHE_KEY);
  if (cached) {
    try {
      const parsed = JSON.parse(cached);
      window.__configCacheData = parsed;
      return parsed;
    } catch (e) {
      sessionStorage.removeItem(CONFIG_CACHE_KEY);
    }
  }
  configLoadPromise = (async () => {
    const response = await fetch('config.json');
    if (!response.ok) {
      throw new Error(`加载配置失败: HTTP ${response.status}`);
    }
    const configData = await response.json();
    window.__configCacheData = configData;
    sessionStorage.setItem(CONFIG_CACHE_KEY, JSON.stringify(configData));
    return configData;
  })();
  window.__configLoadPromise = configLoadPromise;
  return configLoadPromise;
}

window.loadConfigCached = loadConfigCached;

// 清空临时变量和UI（页面刷新或从多轮对话页返回时调用）
function clearTemporaryData(clearUI = true) {
  console.log('🔄 清空首页临时变量数据', clearUI ? '（包括UI）' : '（仅变量）');
  selectedFiles = [];
  uploadedFileIds = [];
  
  // 清空 sessionStorage 中的临时数据
  try {
    sessionStorage.removeItem('uploadedFileIds');
    sessionStorage.removeItem('pendingFiles');
    sessionStorage.removeItem('createdSessionId');
    console.log('✅ 已清空 sessionStorage 中的临时数据');
  } catch (e) {
    console.warn('清空 sessionStorage 失败:', e);
  }
  
  // 如果clearUI为true，清空输入框和文件预览
  if (clearUI) {
    const userInput = document.getElementById('homeUserInput');
    const filePreviewContainer = document.getElementById('homeFilePreviewContainer');
    const filePreviewList = document.getElementById('homeFilePreviewList');
    const fileInput = document.getElementById('homeFileInput');
    
    // 清空输入框
    if (userInput) {
      userInput.value = '';
      console.log('✅ 已清空输入框');
    }
    
    // 清空文件预览
    if (filePreviewList) {
      filePreviewList.innerHTML = '';
    }
    if (filePreviewContainer) {
      filePreviewContainer.style.display = 'none';
    }
    
    // 清空文件选择
    if (fileInput) {
      fileInput.value = '';
    }
    
    // 恢复输入框的padding-top
    if (userInput) {
      userInput.style.paddingTop = '18px';
    }
    
    console.log('✅ 已清空UI（输入框和文件预览）');
  }
}

// 初始化
document.addEventListener('DOMContentLoaded', function() {
  // 检测是否从多轮对话页返回
  // 检查sessionStorage中是否有标记（多轮对话页加载时会设置）
  const fromMultiTurnPage = sessionStorage.getItem('from_multi_turn_page') === 'true';
  
  // 如果是从多轮对话页返回，清空所有输入内容（包括UI）
  if (fromMultiTurnPage) {
    console.log('✅ 检测到从多轮对话页返回，清空首页输入内容');
    clearTemporaryData(true); // 清空变量和UI
    // 清除标记，避免下次加载时误判
    sessionStorage.removeItem('from_multi_turn_page');
  } else {
    // 如果不是从多轮对话页返回，只清空变量（不清空UI，保留用户可能正在输入的内容）
    // 注意：首次加载时，用户可能还没有输入，所以这里只清空变量
    clearTemporaryData(false); // 只清空变量，不清空UI
  }
  const userInput = document.getElementById('homeUserInput');
  const fileInput = document.getElementById('homeFileInput');
  const fileUploadBtn = document.getElementById('homeFileUploadBtn');
  const sendBtn = document.getElementById('homeSendBtn');
  const filePreviewContainer = document.getElementById('homeFilePreviewContainer');
  const filePreviewList = document.getElementById('homeFilePreviewList');
  const exampleCards = document.querySelectorAll('.example-card');
  const historyTab = document.getElementById('historyTab');

  // 历史记录Tab点击 - 跳转到多轮对话页
  if (historyTab) {
    historyTab.onclick = () => {
      console.log('点击历史记录Tab，跳转到多轮对话页');
      const url = 'mcp_client.html';
      
      // 如果在iframe中，通过父窗口跳转；否则直接跳转
      if (window.parent !== window && window.parent.loadPage) {
        console.log('通过父窗口跳转:', url);
        window.parent.loadPage(url);
      } else {
        console.log('直接跳转:', url);
        window.location.href = url;
      }
    };
  }

  // 文件上传按钮点击
  fileUploadBtn.onclick = () => {
    fileInput.click();
  };

  // 文件选择 - 立即上传
  fileInput.onchange = async (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
      // 检查文件大小（1MB限制）
      const maxSize = 1 * 1024 * 1024; // 1MB
      const oversizedFiles = files.filter(file => file.size > maxSize);
      
      if (oversizedFiles.length > 0) {
        // 显示错误提示
        showFileSizeError();
        // 只保留符合大小要求的文件
        selectedFiles = files.filter(file => file.size <= maxSize);
      } else {
        selectedFiles = files;
      }
      
      // 更新文件预览（显示上传中状态）
      updateFilePreview();
      
      // 更新发送按钮状态
      updateSendButtonState();
      
      // 立即上传文件到服务端
      await uploadFilesImmediately();
    }
  };
  
  // 立即上传文件到服务端
  async function uploadFilesImmediately() {
    if (selectedFiles.length === 0) return;
    
    // 加载配置获取MCP服务器地址（使用缓存）
    let mcpServerUrl = 'http://localhost:8000';
    try {
      const configData = await loadConfigCached();
      mcpServerUrl = `http://${configData.mcp_server.host}:${configData.mcp_server.port}`;
    } catch (error) {
      console.warn('配置加载失败，使用默认地址:', error);
    }
    
    // 显示上传Loading状态
    showUploadLoading(selectedFiles.length);
    
    // 重置已上传文件ID数组
    uploadedFileIds = [];
    
    try {
      // 逐个上传文件
      for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];
        updateUploadProgress(i + 1, selectedFiles.length, file.name);
        
        // 更新文件卡片状态为上传中
        updateFileCardStatus(i, 'uploading');
        
        try {
          // 上传文件到服务端
          const formData = new FormData();
          formData.append('file', file);
          
          const uploadResponse = await fetch(`${mcpServerUrl}/api/files/upload`, {
            method: 'POST',
            body: formData
          });
          
          if (!uploadResponse.ok) {
            const errorData = await uploadResponse.json().catch(() => ({}));
            throw new Error(errorData.error || `文件上传失败: ${file.name}`);
          }
          
          const fileInfo = await uploadResponse.json();
          if (fileInfo && fileInfo.file_id) {
            uploadedFileIds.push(fileInfo.file_id);
            console.log(`✅ 文件 ${file.name} 上传成功，文件ID: ${fileInfo.file_id}`);
            // 更新文件卡片状态为成功
            updateFileCardStatus(i, 'success');
          } else {
            throw new Error('服务器未返回文件ID');
          }
        } catch (error) {
          console.error(`文件 ${file.name} 上传失败:`, error);
          // 更新文件卡片状态为失败
          updateFileCardStatus(i, 'error');
          showToast(`文件 ${file.name} 上传失败: ${error.message}`);
        }
      }
      
      // 隐藏上传Loading
      hideUploadLoading();
      
      // 将上传成功的文件ID存储到sessionStorage
      if (uploadedFileIds.length > 0) {
        sessionStorage.setItem('uploadedFileIds', JSON.stringify(uploadedFileIds));
        console.log('✅ 已上传文件ID已保存:', uploadedFileIds);
      }
      
      // 更新发送按钮状态
      updateSendButtonState();
    } catch (error) {
      hideUploadLoading();
      console.error('文件上传过程出错:', error);
      showToast('文件上传失败，请重试');
      // 即使上传失败，也更新按钮状态（可能还有文本输入）
      updateSendButtonState();
    }
  }
  
  // 更新文件卡片状态
  function updateFileCardStatus(index, status) {
    const fileCards = filePreviewList.querySelectorAll('.file-card');
    if (fileCards[index]) {
      const card = fileCards[index];
      card.classList.remove('uploading', 'success', 'error');
      card.classList.add(status);
      
      // 添加或更新状态图标
      let statusIcon = card.querySelector('.file-status-icon');
      if (!statusIcon) {
        statusIcon = document.createElement('div');
        statusIcon.className = 'file-status-icon';
        const fileIcon = card.querySelector('.file-icon');
        if (fileIcon) {
          fileIcon.appendChild(statusIcon);
        }
      }
      
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
  
  // 显示Toast提示
  function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'toast-message';
    toast.textContent = message;
    toast.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      background: rgba(0, 0, 0, 0.8);
      color: #fff;
      padding: 12px 20px;
      border-radius: 8px;
      z-index: 10001;
      animation: slideIn 0.3s ease-out;
    `;
    document.body.appendChild(toast);
    
    setTimeout(() => {
      toast.style.animation = 'slideOut 0.3s ease-out';
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }
  
  // 显示文件大小错误提示
  function showFileSizeError() {
    // 创建错误提示弹窗
    const errorModal = document.createElement('div');
    errorModal.className = 'file-error-modal';
    errorModal.innerHTML = `
      <div class="file-error-content">
        <div class="file-error-icon">⚠️</div>
        <div class="file-error-text">文件超出最大限制1MB</div>
        <button class="file-error-btn" onclick="this.closest('.file-error-modal').remove()">确定</button>
      </div>
    `;
    document.body.appendChild(errorModal);
    
    // 3秒后自动关闭
    setTimeout(() => {
      if (errorModal.parentNode) {
        errorModal.remove();
      }
    }, 3000);
  }

  // 更新文件预览
  function updateFilePreview() {
    if (selectedFiles.length > 0) {
      filePreviewList.innerHTML = '';
      selectedFiles.forEach((file, index) => {
        const fileCard = createFileCard(file, index);
        filePreviewList.appendChild(fileCard);
      });
      filePreviewContainer.style.display = 'block';
      // 有文件时，调整输入框的padding-top，为文件预览留出空间
      adjustInputPadding(true);
    } else {
      filePreviewContainer.style.display = 'none';
      // 没有文件时，恢复输入框的padding-top
      adjustInputPadding(false);
    }
  }

  // 调整输入框的padding-top
  function adjustInputPadding(hasFiles) {
    const input = document.getElementById('homeUserInput');
    if (hasFiles) {
      // 计算文件预览区域的高度（文件列表）
      const fileListHeight = filePreviewList.scrollHeight;
      const totalHeight = fileListHeight + 20; // 额外20px间距
      input.style.paddingTop = `${totalHeight}px`;
    } else {
      // 没有文件时，提示文字靠近上边沿
      input.style.paddingTop = '18px';
    }
  }

  // 创建文件卡片
  function createFileCard(file, index) {
    const card = document.createElement('div');
    card.className = 'file-card';
    card.dataset.index = index;
    
    // 设置文件完整信息用于tooltip
    const fileType = getFileType(file.name);
    const fileSize = formatFileSize(file.size);
    const fullInfo = `${file.name}\n${fileType} ${fileSize}`;
    card.setAttribute('data-file-info', fullInfo);
    // 设置title为空，避免显示浏览器默认提示
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
    if (file.name.length > maxDisplayLength) {
      name.textContent = file.name.substring(0, maxDisplayLength) + '···';
    } else {
      name.textContent = file.name;
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
      removeFile(index);
    };
    
    card.appendChild(icon);
    card.appendChild(info);
    card.appendChild(removeBtn);
    
    return card;
  }

  // 移除文件
  function removeFile(index) {
    selectedFiles.splice(index, 1);
    // 同时移除对应的已上传文件ID
    if (uploadedFileIds[index]) {
      uploadedFileIds.splice(index, 1);
    }
    fileInput.value = '';
    // 重新设置文件输入（因为不能直接修改files）
    if (selectedFiles.length > 0) {
      const dataTransfer = new DataTransfer();
      selectedFiles.forEach(file => dataTransfer.items.add(file));
      fileInput.files = dataTransfer.files;
    }
    updateFilePreview();
    // 更新发送按钮状态
    updateSendButtonState();
  }

  // 获取文件类型
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
      'PPTX': 'PPTX'
    };
    return typeMap[ext] || ext;
  }

  // 格式化文件大小
  function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + sizes[i];
  }

  // 示例卡片点击
  console.log('📋 开始绑定示例卡片点击事件，找到', exampleCards.length, '个示例卡片');
  exampleCards.forEach((card, index) => {
    const exampleText = card.getAttribute('data-example');
    console.log(`  示例卡片${index + 1}:`, exampleText);
    
    card.onclick = () => {
      console.log('🖱️ 示例卡片被点击:', exampleText);
      const cardExampleText = card.getAttribute('data-example');
      if (cardExampleText) {
        // 特殊处理"请你作为裁判者帮我断案"示例，填充完整案情描述
        let textToFill = cardExampleText;
        if (cardExampleText === '请你作为裁判者帮我断案') {
          textToFill = '请你作为裁判者帮我断案，案情描述：张三在2023年1月15日从李四处借款2万元整，借款期限6个月，借款到期后李四通过短信等方式催收未果。双方未约定利息及违约责任，张三有向李四出具借条，李四通过电子银行转账方式完成出借。';
          console.log('✅ 检测到\"请你作为裁判者帮我断案\"示例，填充完整案情描述');
        }
        
        if (userInput) {
          userInput.value = textToFill;
          userInput.focus();
          console.log('✅ 已填充文本到输入框，长度:', textToFill.length);
          
          // 手动触发input事件，确保updateSendButtonState被调用
          const inputEvent = new Event('input', { bubbles: true });
          userInput.dispatchEvent(inputEvent);
          
          // 或者直接调用updateSendButtonState来更新按钮状态
          if (typeof updateSendButtonState === 'function') {
            updateSendButtonState();
          }
          
          console.log('✅ 示例卡片点击处理完成，已填充内容并更新按钮状态:', cardExampleText);
        } else {
          console.error('❌ userInput元素不存在，无法填充文本');
        }
      } else {
        console.warn('⚠️ 示例卡片没有data-example属性');
      }
    };
  });
  console.log('✅ 示例卡片点击事件绑定完成');

  // 发送按钮点击
  sendBtn.onclick = async () => {
    const userText = userInput.value.trim();
    
    // 检查是否有已上传的文件ID（从sessionStorage）
    let uploadedFileIdsFromStorage = [];
    try {
      const uploadedFileIdsStr = sessionStorage.getItem('uploadedFileIds');
      if (uploadedFileIdsStr) {
        uploadedFileIdsFromStorage = JSON.parse(uploadedFileIdsStr);
      }
    } catch (e) {
      console.error('从sessionStorage获取uploadedFileIds失败:', e);
    }
    
    // 检查是否有文件（包括待上传的文件和已上传的文件）
    const hasFiles = selectedFiles.length > 0 || uploadedFileIds.length > 0 || uploadedFileIdsFromStorage.length > 0;
    
    // 详细日志
    console.log('=== 首页发送检查 ===');
    console.log('userText:', userText);
    console.log('userText长度:', userText.length);
    console.log('selectedFiles数量:', selectedFiles.length);
    console.log('uploadedFileIds数量:', uploadedFileIds.length);
    console.log('uploadedFileIdsFromStorage数量:', uploadedFileIdsFromStorage.length);
    console.log('hasFiles:', hasFiles);
    
    // 只有当既没有文本输入，也没有任何文件时，才提示
    if (!userText && !hasFiles) {
      console.log('输入为空且没有文件，显示提示');
      alert('请输入问题或上传文件');
      return;
    }
    
    // 如果有输入或文件，继续处理
    if (userText) {
      console.log('✅ 检测到文本输入，长度:', userText.length);
    }
    if (hasFiles) {
      console.log('✅ 检测到文件，selectedFiles:', selectedFiles.length, 'uploadedFileIds:', uploadedFileIds.length, 'uploadedFileIdsFromStorage:', uploadedFileIdsFromStorage.length);
    }

    // 禁用按钮并显示加载状态
    sendBtn.disabled = true;
    sendBtn.classList.add('loading');

    try {
      // 加载配置获取MCP服务器地址（使用缓存，避免重复请求）
      let mcpServerUrl = 'http://localhost:8000';
      try {
        const configData = await loadConfigCached();
        mcpServerUrl = `http://${configData.mcp_server.host}:${configData.mcp_server.port}`;
      } catch (error) {
        console.warn('配置加载失败，使用默认地址:', error);
      }

      // 检查是否有文件需要上传（如果文件还未上传完成，等待上传完成）
      if (selectedFiles.length > 0) {
        // 检查是否所有文件都已上传成功
        const allUploaded = uploadedFileIds.length === selectedFiles.length;
        if (!allUploaded) {
          alert('请等待文件上传完成');
          sendBtn.disabled = false;
          sendBtn.classList.remove('loading');
          return;
        }
        
        // 创建新会话（用于关联文件）
        let sessionId = null;
        try {
          const sessionResponse = await fetch(`${mcpServerUrl}/api/sessions`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({
              title: userText || '新会话'
            })
          });
          
          if (sessionResponse.ok) {
            const sessionData = await sessionResponse.json();
            sessionId = sessionData.session_id;
            console.log('✅ 已创建会话用于关联文件:', sessionId);
            
            // 将文件关联到会话（如果需要）
            if (uploadedFileIds.length > 0 && sessionId) {
              // 这里可以调用API将文件关联到会话，如果服务端需要的话
              // 目前文件上传时没有session_id，所以这里可能需要额外的关联操作
              // 但根据现有代码，文件上传时没有session_id也能工作
            }
          }
        } catch (error) {
          console.warn('创建会话失败，继续处理:', error);
        }
        
        // 将上传成功的文件ID和会话ID存储到sessionStorage
        sessionStorage.setItem('uploadedFileIds', JSON.stringify(uploadedFileIds));
        if (sessionId) {
          sessionStorage.setItem('createdSessionId', sessionId);
        }
      }

      // 跳转到mcp_client.html（保持loading状态）
      const params = new URLSearchParams();
      if (userText) {
        // 使用encodeURIComponent确保特殊字符正确编码
        params.set('input', encodeURIComponent(userText));
        console.log('准备跳转，URL参数input:', userText);
        console.log('编码后的URL参数:', params.get('input'));
      }
      const url = 'mcp_client.html' + (params.toString() ? '?' + params.toString() : '');
      console.log('完整跳转URL:', url);
      
      // 如果在iframe中，通过父窗口跳转；否则直接跳转
      if (window.parent !== window && window.parent.loadPage) {
        // 在index.html的iframe中，通过父窗口的loadPage函数跳转
        console.log('通过父窗口跳转:', url);
        window.parent.loadPage(url);
      } else {
        // 直接访问时，直接跳转
        console.log('直接跳转:', url);
        window.location.href = url;
      }
    } catch (error) {
      console.error('处理失败:', error);
      hideUploadLoading();
      alert('处理失败，请重试');
      sendBtn.disabled = false;
      sendBtn.classList.remove('loading');
      // 发送完成后更新按钮状态（根据当前输入状态）
      updateSendButtonState();
    }
  };
  
  // 显示上传Loading状态
  function showUploadLoading(totalFiles) {
    // 移除已存在的Loading
    hideUploadLoading();
    
    const loadingModal = document.createElement('div');
    loadingModal.id = 'uploadLoadingModal';
    loadingModal.className = 'upload-loading-modal';
    loadingModal.innerHTML = `
      <div class="upload-loading-content">
        <div class="upload-loading-spinner"></div>
        <div class="upload-loading-text">正在上传文件...</div>
        <div class="upload-loading-progress" id="uploadProgress">0 / ${totalFiles}</div>
      </div>
    `;
    document.body.appendChild(loadingModal);
  }
  
  // 更新上传进度
  function updateUploadProgress(current, total, fileName) {
    const progressEl = document.getElementById('uploadProgress');
    if (progressEl) {
      progressEl.textContent = `${current} / ${total} - ${fileName.length > 20 ? fileName.substring(0, 20) + '...' : fileName}`;
    }
  }
  
  // 隐藏上传Loading
  function hideUploadLoading() {
    const loadingModal = document.getElementById('uploadLoadingModal');
    if (loadingModal) {
      loadingModal.remove();
    }
  }

  // 检查输入状态并更新发送按钮
  function updateSendButtonState() {
    const hasText = (userInput.value || '').trim().length > 0;
    
    // 检查是否有已上传的文件ID（从sessionStorage）
    let uploadedFileIdsFromStorage = [];
    try {
      const uploadedFileIdsStr = sessionStorage.getItem('uploadedFileIds');
      if (uploadedFileIdsStr) {
        uploadedFileIdsFromStorage = JSON.parse(uploadedFileIdsStr);
      }
    } catch (e) {
      console.error('从sessionStorage获取uploadedFileIds失败:', e);
    }
    
    const hasFiles = selectedFiles.length > 0 || uploadedFileIds.length > 0 || uploadedFileIdsFromStorage.length > 0;
    const hasInput = hasText || hasFiles;
    
    // 更新按钮状态：只有当没有文本且没有文件时，才禁用按钮
    sendBtn.disabled = !hasInput;
    
    console.log('更新发送按钮状态:', {
      hasText,
      hasFiles,
      selectedFilesCount: selectedFiles.length,
      uploadedFileIdsCount: uploadedFileIds.length,
      uploadedFileIdsFromStorageCount: uploadedFileIdsFromStorage.length,
      hasInput,
      disabled: !hasInput
    });
  }
  
  // 初始化按钮状态
  updateSendButtonState();
  
  // 监听输入框变化
  userInput.addEventListener('input', updateSendButtonState);
  userInput.addEventListener('paste', () => {
    // 延迟一下，等待粘贴内容填充完成
    setTimeout(updateSendButtonState, 10);
  });
  
  // 监听文件变化（通过监听selectedFiles和uploadedFileIds的变化）
  // 注意：由于selectedFiles是数组，我们需要在修改它的地方调用updateSendButtonState
  // 这里我们在文件选择、文件上传完成、文件移除等地方调用
  
  // 回车键发送（Enter键，Shift+Enter换行）
  userInput.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      // 检查是否有输入且按钮未禁用
      const hasText = (userInput.value || '').trim().length > 0;
      
      // 检查是否有已上传的文件ID
      let uploadedFileIdsFromStorage = [];
      try {
        const uploadedFileIdsStr = sessionStorage.getItem('uploadedFileIds');
        if (uploadedFileIdsStr) {
          uploadedFileIdsFromStorage = JSON.parse(uploadedFileIdsStr);
        }
      } catch (e) {
        console.error('从sessionStorage获取uploadedFileIds失败:', e);
      }
      
      const hasFiles = selectedFiles.length > 0 || uploadedFileIds.length > 0 || uploadedFileIdsFromStorage.length > 0;
      const hasInput = hasText || hasFiles;
      
      // 只有当有输入且按钮未禁用时才发送
      if (hasInput && !sendBtn.disabled && !sendBtn.classList.contains('loading')) {
        sendBtn.onclick();
      }
    }
    // Shift+Enter 换行（不发送）
  };
});

// 读取文件为DataURL
function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => resolve(e.target.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

