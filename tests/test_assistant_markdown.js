'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const js = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.html'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.css'), 'utf8');

assert.ok(js.includes('function formatAssistantMarkdown'), 'markdown formatter present');
assert.ok(js.includes('function formatInlineMarkdown'), 'inline markdown present');
assert.ok(js.includes('class="md-h"'), 'heading class');
assert.ok(css.includes('.md-body'), 'md-body CSS');
assert.ok(css.includes('.md-body .md-h'), 'heading CSS');
assert.ok(html.includes('mcp_client.js?v=20260907sess1'), 'cache-bust js');
assert.ok(html.includes('mcp_client.css?v=20260907sess1'), 'cache-bust css');

const esc = js.match(/function escapeHtml\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert.ok(esc, 'escapeHtml extractable');
const start = js.indexOf('function formatAssistantMarkdown');
const end = js.indexOf('function bindInlineCitationClicks');
assert.ok(start > 0 && end > start, 'function range');

const code =
  esc[0] +
  '\n' +
  js.slice(start, end) +
  '\n;({ formatAssistantMarkdown, formatInlineMarkdown, linkifyPlainTextWithCitations });';

const sandbox = {
  document: {
    createElement: function () {
      return {
        _t: '',
        set textContent(v) {
          this._t = String(v == null ? '' : v);
        },
        get textContent() {
          return this._t;
        },
        get innerHTML() {
          return this._t
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
        }
      };
    }
  },
  findCitationLinkRanges: function () {
    return [];
  }
};
const exported = vm.runInNewContext(code, sandbox);
const { formatAssistantMarkdown, linkifyPlainTextWithCitations } = exported;

const h2 = formatAssistantMarkdown('## 案情概述\n\n本案系民间借贷纠纷。');
assert.ok(h2.includes('<h2 class="md-h">案情概述</h2>'), '## becomes h2: ' + h2);
assert.ok(!h2.includes('## 案情'), 'raw ## hidden');
assert.ok(h2.includes('<p>') && h2.includes('民间借贷'), 'paragraph rendered');

const noSpace = formatAssistantMarkdown('##案情要点');
assert.ok(noSpace.includes('<h2 class="md-h">案情要点</h2>'), '## without space');

const bold = formatAssistantMarkdown('结论：**胜诉概率较高**');
assert.ok(bold.includes('<strong>胜诉概率较高</strong>'), 'bold works');

const list = formatAssistantMarkdown('- 甲项\n- 乙项');
assert.ok(list.includes('<ul class="md-list">'), 'ul list');
assert.ok(list.includes('<li>甲项</li>'), 'list item');

const xss = formatAssistantMarkdown('## <script>alert(1)</script>');
assert.ok(!xss.includes('<script>'), 'script escaped');
assert.ok(xss.includes('&lt;script&gt;'), 'escaped entities');

const wrapped = linkifyPlainTextWithCitations('## 标题\n正文', []);
assert.ok(wrapped.startsWith('<div class="md-body">'), 'md-body wrap');
assert.ok(wrapped.includes('<h2'), 'linkify path renders heading');

console.log('ok: assistant markdown');
