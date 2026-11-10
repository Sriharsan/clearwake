/* Pure helpers for the Clearwake console. No DOM, no network: tested with node --test. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ClearwakeConsole = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function money(minor) {
    const n = Number(minor) || 0;
    const sign = n < 0 ? '-' : '';
    const abs = Math.abs(Math.round(n));
    return sign + Math.floor(abs / 100) + '.' + String(abs % 100).padStart(2, '0');
  }

  // Share of the cap, 0 to 100, for an arc drawn with pathLength 100.
  function gaugeShare(amountMinor, capText) {
    const cap = Math.round(Number(capText) * 100);
    if (!(cap > 0)) return 0;
    return Math.max(0, Math.min(100, (Number(amountMinor) || 0) / cap * 100));
  }

  // Countdown to PayPal's seller_response_due_date. "soon" is inside 24 hours, as in clearwake/evidence.py.
  function countdown(dueIso, nowMs) {
    const due = Date.parse(dueIso || '');
    if (Number.isNaN(due)) return { seconds: null, state: 'no deadline given', text: 'No deadline given' };
    const seconds = Math.floor((due - nowMs) / 1000);
    if (seconds <= 0) return { seconds, state: 'lapsed', text: 'Deadline passed' };
    const d = Math.floor(seconds / 86400), h = Math.floor(seconds % 86400 / 3600), m = Math.floor(seconds % 3600 / 60), s = seconds % 60;
    const text = d > 0 ? `${d} d ${h} h ${String(m).padStart(2, '0')} min` : `${h} h ${String(m).padStart(2, '0')} min ${String(s).padStart(2, '0')} s`;
    return { seconds, state: seconds <= 86400 ? 'soon' : 'ok', text };
  }

  // One word per swarm state, used for node classes and plain labels. "Verified" is kept for PayPal records only.
  function outcome(state, rehearsal) {
    switch (state) {
      case 'VERIFIED': return { cls: 'settled', label: rehearsal ? 'Matches rehearsal record' : 'Verified against PayPal' };
      case 'UNKNOWN': return { cls: 'unknown', label: 'UNKNOWN, held' };
      case 'MISMATCH': return { cls: 'reversed', label: 'Record does not match' };
      case 'PENDING': return { cls: 'held', label: 'Pending at provider' };
      case 'refused': return { cls: 'reversed', label: 'Refused before any call' };
      case 'awaiting approval': return { cls: 'held', label: 'Waiting for a person' };
      case 'approved, answer by hand': return { cls: 'held', label: 'Approved, answer by hand' };
      case 'escalated': return { cls: 'held', label: 'Escalated' };
      case 'busy': return { cls: 'held', label: 'Held by another agent' };
      case 'done': return { cls: 'done', label: 'Done, no money moved' };
      default: return { cls: 'done', label: String(state || 'Not started') };
    }
  }

  // Four nodes per case: proposal, policy, sent, provider record. UNKNOWN is its own node state.
  function track(entry, rehearsal) {
    const state = entry.state, proposed = entry.proposed || entry.action;
    const money = ['refund', 'accept_and_refund'].includes(entry.action);
    const policy = entry.policy || {};
    const proposal = { cls: proposed ? 'done' : '', label: proposed ? 'Proposed: ' + String(proposed).replaceAll('_', ' ') : 'Proposal' };
    let gate, sent, record;
    if (state === 'refused') {
      gate = { cls: 'reversed', label: 'Stopped' };
      sent = { cls: '', label: 'Nothing sent' };
      record = { cls: 'reversed', label: 'Refused' };
    } else if (state === 'awaiting approval' || state === 'approved, answer by hand') {
      gate = { cls: 'held', label: state === 'awaiting approval' ? 'Needs approval' : 'Approved' };
      sent = { cls: '', label: 'Not sent' };
      record = { cls: '', label: 'No record' };
    } else if (state === 'UNKNOWN') {
      gate = { cls: 'done', label: 'Allowed' };
      sent = { cls: 'done', label: 'Sent once' };
      record = { cls: 'unknown', label: 'UNKNOWN' };
    } else {
      gate = { cls: 'done', label: policy.needs_approval ? 'Approved' : 'Allowed' };
      sent = { cls: money || entry.action === 'provide_evidence' ? 'done' : '', label: money ? 'Sent once' : entry.action === 'provide_evidence' ? 'Evidence sent' : 'No call' };
      const o = outcome(state, rehearsal);
      record = { cls: o.cls, label: state === 'VERIFIED' ? (rehearsal ? 'Matches record' : 'Verified') : o.label };
    }
    return [proposal, gate, sent, record];
  }

  // Tamper with one receipt line in memory: flip success, or change one character of the step id.
  function tamper(text, lineNumber) {
    const lines = String(text).replace(/\n$/, '').split('\n');
    const index = Math.max(1, Math.min(lines.length, lineNumber || 1)) - 1;
    const line = lines[index] || '';
    let changed;
    if (line.includes('"success":true')) changed = line.replace('"success":true', '"success":false');
    else if (line.includes('"success":false')) changed = line.replace('"success":false', '"success":true');
    else changed = line.replace(/"step_id":"(.)/, (m, c) => `"step_id":"${c === 'x' ? 'y' : 'x'}`);
    if (changed === line) changed = line + ' ';
    lines[index] = changed;
    return { text: lines.join('\n') + '\n', line: index + 1, before: line, after: changed };
  }

  // Rows for the receipts table: one per line, pass or the list of failure reasons.
  function receiptRows(logName, text, report) {
    const body = String(text).endsWith('\n') ? String(text).slice(0, -1) : String(text);
    const lines = body === '' ? [] : body.split('\n');
    const reasons = new Map();
    for (const f of (report && report.failures) || []) reasons.set(f.line, (reasons.get(f.line) || []).concat(f.reason));
    return lines.map((raw, i) => {
      let r = {};
      try { r = JSON.parse(raw); } catch (e) { r = {}; }
      const failed = reasons.get(i + 1) || [];
      return {
        log: logName, line: i + 1, step: typeof r.step_id === 'string' ? r.step_id : '', action: typeof r.action_id === 'string' ? r.action_id : '',
        success: typeof r.success === 'boolean' ? (r.success ? 'yes' : 'no') : '',
        time: Number.isInteger(r.ts_ms) ? new Date(r.ts_ms).toISOString().replace('T', ' ').slice(0, 19) : '',
        result: report ? (failed.length ? 'FAIL: ' + failed.join(', ') : 'pass') : 'not checked'
      };
    });
  }

  function isHexKey(value) { return /^[0-9a-fA-F]{64}$/.test(String(value || '').trim()); }

  // Words as written, with underscores of PayPal codes turned into spaces (readable() also lowercases).
  function plain(value) { return String(value || '').replaceAll('_', ' '); }

  function readable(value) { return String(value || '').replaceAll('_', ' ').toLowerCase(); }

  // CSV export for the accountant. A cell that starts with = + - @ tab or CR would run as a formula in a spreadsheet,
  // so it gets a leading apostrophe. Quoting itself is done by the grid's CSV writer.
  function csvSafe(value) {
    const text = value === null || value === undefined ? '' : String(value);
    return /^[=+\-@\t\r]/.test(text) && !/^-?\d+(\.\d+)?$/.test(text) ? "'" + text : text;
  }

  // Ledger helpers shared by the grid columns. A dash means the record does not hold the value.
  const DASH = '–';
  function stageOf(row) { return String((row && row.stage) || '').toUpperCase(); }
  function stagePasses(row, filter) { return !filter || filter === 'all' || stageOf(row) === filter; }
  function proposalOf(row) { return row && row.proposed && row.proposed !== 'no usable proposal' ? readable(row.proposed) : DASH; }
  function deadlineOf(row, nowMs) {
    if (!row || row.settled_before_escalation || row.paypal_status === 'RESOLVED') return 'closed';
    if (!row.due) return DASH;
    return countdown(row.due, nowMs).text;
  }

  // Whole table as CSV text (CRLF rows, quoted when needed). Used when the grid is not available; the grid's own writer is used otherwise.
  function toCsv(headers, rows) {
    const cell = v => { const t = csvSafe(v); return /[",\r\n]/.test(t) ? '"' + t.replaceAll('"', '""') + '"' : t; };
    return [headers.map(h => cell(h.headerName)).join(',')].concat(rows.map(r => headers.map(h => cell(h.get(r))).join(','))).join('\r\n') + '\r\n';
  }

  return { plain, toCsv, money, gaugeShare, countdown, outcome, track, tamper, receiptRows, isHexKey, readable, csvSafe, stageOf, stagePasses, proposalOf, deadlineOf, DASH };
});
