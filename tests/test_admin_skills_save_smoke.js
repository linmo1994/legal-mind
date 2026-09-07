'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'admin_skills.html'), 'utf8');

assert.ok(html.includes('id="skillBody"'), 'body textarea');
assert.ok(html.includes('form.addEventListener("submit", saveSkill)'), 'form submit wired to save');
assert.ok(html.includes('ev.preventDefault'), 'preventDefault on save/submit');
assert.ok(html.includes('正文未正确写回'), 'body round-trip check');
assert.ok(html.includes('JSON.stringify(payload)'), 'sends full payload');
assert.ok(/body:\s*bodyEl\s*\?\s*bodyEl\.value/.test(html) || html.includes('body: bodyEl ? bodyEl.value'), 'reads textarea value');

console.log('ok: admin skills save smoke');
