(function (root) {
  function flowKey(e) {
    return String(e.kind || '') + '\0' + String(e.id || '');
  }
  function mergeLiveFlow(prev, event) {
    const list = Array.isArray(prev) ? prev.slice() : [];
    if (!event || typeof event !== 'object') return list;
    const key = flowKey(event);
    if (!event.id && !event.kind) {
      list.push(Object.assign({}, event));
      return list;
    }
    const idx = list.findIndex(function (x) { return flowKey(x) === key; });
    if (idx >= 0) {
      list[idx] = Object.assign({}, list[idx], event);
    } else {
      list.push(Object.assign({}, event));
    }
    return list;
  }
  function liveFlowRecent(flow, limit) {
    const n = typeof limit === 'number' ? limit : 5;
    const arr = Array.isArray(flow) ? flow : [];
    return arr.slice(Math.max(0, arr.length - n));
  }
  function parseSseChunk(buffer, chunkText) {
    const buf = String(buffer || '') + String(chunkText || '');
    const parts = buf.split('\n');
    const rest = parts.pop();
    const events = [];
    for (let i = 0; i < parts.length; i++) {
      const line = parts[i].replace(/\r$/, '');
      if (!line.startsWith('data:')) continue;
      const raw = line.slice(5).trim();
      if (!raw) continue;
      try { events.push(JSON.parse(raw)); } catch (e) {}
    }
    return { buffer: rest, events: events };
  }
  function shouldReportUnexpectedOrchestrateEnd(sawDone, sawError) {
    return !sawDone && !sawError;
  }
  root.mergeLiveFlow = mergeLiveFlow;
  root.liveFlowRecent = liveFlowRecent;
  root.parseSseChunk = parseSseChunk;
  root.shouldReportUnexpectedOrchestrateEnd = shouldReportUnexpectedOrchestrateEnd;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      mergeLiveFlow: mergeLiveFlow,
      liveFlowRecent: liveFlowRecent,
      parseSseChunk: parseSseChunk,
      shouldReportUnexpectedOrchestrateEnd: shouldReportUnexpectedOrchestrateEnd
    };
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
