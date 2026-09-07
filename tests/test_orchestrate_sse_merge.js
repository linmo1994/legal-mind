const assert = require('assert');
const {
  mergeLiveFlow,
  liveFlowRecent,
  parseSseChunk,
  shouldReportUnexpectedOrchestrateEnd
} = require('../orchestrate_live_flow.js');

let f = [];
f = mergeLiveFlow(f, { kind: 'tool', id: 'retrieve_law', name: '法规', status: 'running' });
f = mergeLiveFlow(f, { kind: 'tool', id: 'retrieve_law', name: '法规', status: 'done' });
assert.strictEqual(f.length, 1);
assert.strictEqual(f[0].status, 'done');
f = mergeLiveFlow(f, { kind: 'tool', id: 'draft_doc', name: '起草', status: 'running' });
assert.strictEqual(f.length, 2);
assert.strictEqual(liveFlowRecent(f, 1)[0].id, 'draft_doc');

let st = parseSseChunk('', 'data: {"type":"step","id":"a"}\n\n');
assert.strictEqual(st.events.length, 1);
assert.strictEqual(st.events[0].type, 'step');
st = parseSseChunk('data: {"type":"do', 'ne","result":{}}\n\n');
assert.strictEqual(st.events[0].type, 'done');

assert.strictEqual(shouldReportUnexpectedOrchestrateEnd(false, false), true);
assert.strictEqual(shouldReportUnexpectedOrchestrateEnd(true, false), false);
assert.strictEqual(shouldReportUnexpectedOrchestrateEnd(false, true), false);
assert.strictEqual(shouldReportUnexpectedOrchestrateEnd(true, true), false);

console.log('ok');
