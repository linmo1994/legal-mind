'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { liveFlowRecent } = require('../orchestrate_live_flow.js');

function createElement(tag) {
  const node = {
    tagName: String(tag).toUpperCase(),
    className: '',
    hidden: false,
    textContent: '',
    childNodes: [],
    attributes: {},
    _listeners: {},
    classList: {
      add: function () {
        for (let i = 0; i < arguments.length; i++) {
          const c = arguments[i];
          if (!c) continue;
          const parts = node.className ? node.className.split(/\s+/) : [];
          if (parts.indexOf(c) < 0) parts.push(c);
          node.className = parts.join(' ').trim();
        }
      },
      remove: function () {
        for (let i = 0; i < arguments.length; i++) {
          const c = arguments[i];
          const parts = (node.className ? node.className.split(/\s+/) : []).filter(function (x) {
            return x && x !== c;
          });
          node.className = parts.join(' ').trim();
        }
      },
      contains: function (c) {
        return (node.className ? node.className.split(/\s+/) : []).indexOf(c) >= 0;
      },
    },
    appendChild(child) {
      this.childNodes.push(child);
      child.parentNode = this;
      return child;
    },
    setAttribute(key, value) {
      this.attributes[key] = String(value);
    },
    getAttribute(key) {
      return Object.prototype.hasOwnProperty.call(this.attributes, key)
        ? this.attributes[key]
        : null;
    },
    addEventListener(type, fn) {
      this._listeners[type] = this._listeners[type] || [];
      this._listeners[type].push(fn);
    },
  };
  Object.defineProperty(node, 'innerHTML', {
    configurable: true,
    get() {
      return '';
    },
    set() {
      node.childNodes.length = 0;
    },
  });
  return node;
}

function collectClasses(node, out) {
  if (node.className) out.push(node.className);
  (node.childNodes || []).forEach(function (child) {
    collectClasses(child, out);
  });
}

const src = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.js'), 'utf8');
const fnBlock = src.slice(
  src.indexOf('function kindBadgeClass'),
  src.indexOf('function orchestrateToolMeta')
);
const sandbox = {
  document: { createElement: createElement },
  liveFlowRecent: liveFlowRecent,
};
vm.runInNewContext(fnBlock, sandbox);

const render = sandbox.renderOrchestrateLiveStrip;
const settle = sandbox.settleOrchestrateLiveStrip;
assert.strictEqual(typeof render, 'function');
assert.strictEqual(typeof settle, 'function');

const flow = [
  { kind: 'tool', id: 'retrieve_law', name: '法规', status: 'done' },
  { kind: 'tool', id: 'draft_doc', name: '起草', status: 'running' },
];

const slot = createElement('div');
render(slot, flow, { collapsed: false, limit: 5 });
assert.strictEqual(slot.hidden, false);
assert.strictEqual(slot.attributes['aria-live'], 'polite');
const expandedClasses = [];
collectClasses(slot, expandedClasses);
assert.ok(expandedClasses.includes('orchestrate-live-strip'));
assert.ok(expandedClasses.includes('orchestrate-live-strip-item'));
assert.ok(expandedClasses.includes('orchestrate-live-strip-spinner'));
assert.ok(expandedClasses.includes('orchestrate-wb-badge kind-tool'));

settle(slot);
assert.ok(slot.className.includes('orchestrate-process-panel'));
const settleClasses = [];
collectClasses(slot, settleClasses);
assert.ok(settleClasses.includes('orchestrate-process-toggle'));
const toggle = slot.childNodes.find
  ? slot.childNodes.find(function (n) { return n.className === 'orchestrate-process-toggle'; })
  : slot.childNodes[0];
assert.ok(toggle);
assert.strictEqual(toggle.className, 'orchestrate-process-toggle');
const titleEl = (toggle.childNodes || []).find
  ? toggle.childNodes.find(function (n) { return n.className === 'orchestrate-process-title'; })
  : toggle.childNodes[1];
assert.ok(titleEl);
assert.ok(titleEl.textContent.includes('执行过程'));
assert.ok(titleEl.textContent.includes('2 步'));
assert.strictEqual(toggle.getAttribute('aria-expanded'), 'false');

render(slot, liveFlowRecent(Array.from({ length: 7 }, function (_, i) {
  return { kind: 'tool', id: 't' + i, name: 'step' + i, status: 'done' };
}), 5), { collapsed: false, limit: 5 });
const stripNode = slot.childNodes.find
  ? slot.childNodes.find(function (n) { return n.className === 'orchestrate-live-strip'; })
  : slot.childNodes[1];
const itemCount = stripNode.childNodes.filter(function (n) {
  return n.className === 'orchestrate-live-strip-item';
}).length;
assert.strictEqual(itemCount, 5);

console.log('orchestrate live strip smoke OK');
