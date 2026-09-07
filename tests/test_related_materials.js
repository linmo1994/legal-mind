'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.js'), 'utf8');
assert.ok(src.indexOf('function partitionCitations') >= 0, 'partitionCitations missing');
const blockStart = src.indexOf('function normalizeCitationsList');
const blockEnd = src.indexOf('function openCitationPreview');
assert.ok(blockStart >= 0 && blockEnd > blockStart, 'slice bounds');
const sandbox = { console: console };
vm.runInNewContext(src.slice(blockStart, blockEnd), sandbox);

const partition = sandbox.partitionCitations;
const format = sandbox.formatRelatedMaterialsTabLabel;
const defSeg = sandbox.defaultRelatedMaterialsSegment;
assert.ok(typeof partition === 'function');
assert.ok(typeof format === 'function');
assert.ok(typeof defSeg === 'function');

const mixed = [
  { doc_type: 'law', title: '食品安全法', article: '第148条' },
  { doc_type: 'case', title: '(2025)最高法民再142号' },
  { doc_type: 'law', title: '民法典' },
  { title: '无名法规' },
];
const parts = partition(mixed);
assert.strictEqual(parts.laws.length, 3);
assert.strictEqual(parts.cases.length, 1);
assert.strictEqual(format(parts), '已阅读3条法规，1个案例');
assert.strictEqual(defSeg(parts), 'law');
assert.strictEqual(defSeg({ laws: [], cases: [{ title: 'c' }] }), 'case');
assert.strictEqual(format({ laws: [], cases: [{ title: 'c' }] }), '已阅读0条法规，1个案例');
console.log('ok: related materials pure helpers');
