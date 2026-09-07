'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const js = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.css'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.html'), 'utf8');

assert.ok(js.includes('function appendAssistantMessageActions'), 'actions helper present');
assert.ok(js.includes("data-action', 'like'") || js.includes('data-action", "like"') || js.includes("makeBtn('like'"), 'like button');
assert.ok(js.includes("makeBtn('dislike'"), 'dislike button');
assert.ok(js.includes("makeBtn('copy'"), 'copy button');
assert.ok(js.includes('appendAssistantMessageActions(messageDiv)'), 'wired in addMessage');
assert.ok(js.includes('appendAssistantMessageActions(messageWrapper)'), 'wired in addCombinedMessage');
assert.ok(js.includes('appendAssistantMessageActions(targetShell.wrap)'), 'wired in orchestrate success');
assert.ok(css.includes('.assistant-msg-actions'), 'actions CSS present');
assert.ok(css.includes('.assistant-msg-action-btn.is-active'), 'active state CSS');
assert.ok(html.includes('mcp_client.js?v=20260907rel1'), 'cache-bust js');
assert.ok(html.includes('mcp_client.css?v=20260907rel1'), 'cache-bust css');
assert.ok(js.includes('showPageToast'), 'toast helper present');
assert.ok(js.includes("showPageToast('已复制成功', 2000)"), 'copy success toast');
assert.ok(css.includes('.page-toast'), 'toast CSS present');

console.log('ok: assistant message actions smoke');
