'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const js = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.html'), 'utf8');

assert.ok(js.includes('function restoreOrchestrateHistoryMessage'), 'history restore helper');
assert.ok(js.includes('function buildFlowFromHistoryData'), 'history flow builder');
assert.ok(js.includes('function hydrateOrchestrateDataFromHistoryMessage'), 'hydrate helper');
assert.ok(js.includes('restoreOrchestrateHistoryMessage(msg, msgOpts)'), 'wired from restoreHistoryMessage');
assert.ok(js.includes('renderOrchestrateLiveStrip(shell.flowSlot, flow'), 'settled process panel');
assert.ok(js.includes("collapsed: true"), 'collapsed like live settle');
assert.ok(js.includes('appendRelatedMaterialsTab(shell.wrap'), 'related tab on shell');
assert.ok(js.includes('appendAssistantMessageActions(shell.wrap'), 'actions on shell');
assert.ok(html.includes('mcp_client.js?v=20260907sess1'), 'cache-bust js');
assert.ok(html.includes('mcp_client.css?v=20260907sess1'), 'cache-bust css');

console.log('ok: history orchestrate layout smoke');
