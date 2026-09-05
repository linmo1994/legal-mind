# 多轮编排失败「重试」按钮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 多轮对话编排失败时在助手气泡内显示错误与「重试」按钮，用原句再次调用 `/api/orchestrate`；除 401 外均提供；失败不再静默回退单智能体。

**Architecture:** 在 `tryHandleOrchestrate` 集中处理错误壳；抽取 `showOrchestrateFailure(shell, userMessage, errText)` 与 `bindOrchestrateRetry`；成功路径复用现有 paint/answer/citations；失败时 `return true`。

**Tech Stack:** 现有 `mcp_client.js` / `mcp_client.css`（无新依赖）。

**Spec:** `docs/superpowers/specs/2026-09-05-orchestrate-retry-design.md`

## Global Constraints

- 不自动 commit（除非用户要求）
- 401 → 登录，无重试
- `legacy` → 仍 `return false`
- 本期仅 `mcp_client`

## File map

| File | Responsibility |
|------|----------------|
| `mcp_client.js` | 失败 UI、重试绑定、改 catch/HTTP 分支 |
| `mcp_client.css` | `.orchestrate-retry-btn` 等 |

---

### Task 1: 失败壳 + 重试按钮渲染

**Files:**
- Modify: `mcp_client.js`（靠近 `addOrchestrateProgressShell` / `tryHandleOrchestrate`）
- Modify: `mcp_client.css`

- [ ] **Step 1: 增加 helper**

```javascript
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
```

- [ ] **Step 2: CSS** — 与现有按钮风格一致（主色/ghost），留白与 cite-list 协调。

- [ ] **Step 3: 手工或目视** — 在控制台对假 shell 调用 `showOrchestrateFailure`（可选）。

---

### Task 2: 接入 `tryHandleOrchestrate` 全失败路径

**Files:**
- Modify: `mcp_client.js` → `tryHandleOrchestrate`

- [ ] **Step 1: 抽取内部 `runOnce` 或在失败处统一调用**

逻辑纲要：

```javascript
function tryHandleOrchestrate(fullUserMessage) {
  return (async function () {
    ...
    async function applySuccess(data, shell) { /* 现有成功逻辑 */ }

    async function doRequest() {
      return fetch(... body: { user_text: fullUserMessage, ... });
    }

    function attachRetry(shell, errText) {
      const btn = showOrchestrateFailure(shell, errText);
      if (!btn) return;
      btn.onclick = async function () {
        btn.disabled = true;
        btn.textContent = '重试中…';
        try {
          const resp = await doRequest();
          if (resp.status === 401) { ...; return; }
          if (!resp.ok) {
            const errBody = await resp.json().catch(() => ({}));
            attachRetry(shell, errBody.error || ('请求失败 ' + resp.status));
            return;
          }
          const data = await resp.json();
          if (data && data.legacy) { shell.wrap.remove(); /* 无法在此 return false 给外层 */ 
            // 重试若 legacy：显示提示「请刷新后再试」或再次 attachRetry
            attachRetry(shell, '当前请求需走旧路径，请刷新页面后重发。');
            return;
          }
          clearOrchestrateRetry(shell);
          await applySuccess(data, shell); // sync success UI + history
        } catch (e) {
          attachRetry(shell, e.message || '服务暂时不可用，请稍后重试。');
        }
      };
    }

    try {
      shell = addOrchestrateProgressShell();
      ...
      const resp = await doRequest();
      if (401) { ... return true; }
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        attachRetry(shell, errBody.error || ('请求失败 ' + resp.status));
        return true; // 不再 fallback
      }
      const data = await resp.json();
      if (data && data.legacy) { shell.wrap.remove(); return false; }
      ... success ...
      return true;
    } catch (err) {
      if (!shell) shell = addOrchestrateProgressShell();
      attachRetry(shell, err.message || '服务暂时不可用，请稍后重试。');
      return true; // 关键：不再 return false 静默 fallback
    }
  })();
}
```

注意：

- 原先 `400/403` 专用分支并入 `!resp.ok`。
- `catch` **必须 `return true`** 并展示重试（spec）。
- 重试成功时复用与首次成功相同的 history/citations 逻辑（抽 `applyOrchestrateSuccess(shell, data, fullUserMessage)` 避免复制粘贴错误）。

- [ ] **Step 2: 自测清单**
  1. 停 MCP → 发问 → 见错误+重试，且无单智能体长答  
  2. 启 MCP → 点重试 → 正常回答  
  3. 模拟 403（可选）→ 有重试  

---

### Task 3: 验收收尾

- [ ] 确认 `mcp_client.html` 无需改脚本引用（同文件）  
- [ ] 强刷页面冒烟  
- [ ] Commit only if user asks  

---

## Spec coverage

| Spec | Task |
|------|------|
| 失败 UI + 按钮 | 1 |
| 全失败路径 + return true | 2 |
| 401 / legacy | 2 |
| 重试原句 | 2 |

## Self-review

- 避免失败仍 `return false` 导致双路径。  
- 重试中防连点。  
- 成功清除 `.orchestrate-retry-row`。
