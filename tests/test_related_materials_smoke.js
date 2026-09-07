'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.html'), 'utf8');
const js = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'mcp_client.css'), 'utf8');
assert.ok(html.includes('id="relatedMaterials"'));
assert.ok(html.includes('id="relatedMaterialsBackdrop"'));
assert.ok(html.includes('id="relatedMaterialsClose"'));
assert.ok(html.includes('id="relatedMaterialsBody"'));
assert.ok(html.includes('mcp_client.css?v=20260907rel1'));
assert.ok(html.includes('mcp_client.js?v=20260907rel1'));
assert.ok(js.includes("relatedMaterials: document.getElementById('relatedMaterials')"));
assert.ok(js.includes("relatedMaterialsBody: document.getElementById('relatedMaterialsBody')"));
assert.ok(js.includes('function openRelatedMaterials'));
assert.ok(js.includes('function closeRelatedMaterials'));
assert.ok(js.includes('function initRelatedMaterialsUi'));
assert.ok(js.includes('initRelatedMaterialsUi()'));
assert.ok(js.includes('clearRelatedMaterialsState'));
assert.ok(js.includes('function appendRelatedMaterialsTab'));
assert.ok(js.includes('appendRelatedMaterialsTab(targetShell.wrap'));
assert.ok(
  !/renderAssistantAnswerWithCitations[\s\S]{0,400}renderCitationList\(host/.test(js) ||
    js.includes('// Spec: do not render inline')
);
assert.ok(js.includes('.related-materials-tab'));
assert.ok(html.includes('20260907rel1'));
assert.ok(css.includes('.related-materials-tab'));
assert.ok(css.includes('chat-area.is-related-open'));
assert.ok(css.includes('@media (max-width: 899px)'));
console.log('ok: related materials smoke (html shell)');
