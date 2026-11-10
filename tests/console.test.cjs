'use strict';
// Pure console helpers, plus the tamper flow against the real verdock-core browser verifier. Offline.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const path = require('node:path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');
const L = require(path.join(__dirname, '..', 'web', 'console-lib.js'));
const verifierUrl = pathToFileURL(path.join(__dirname, '..', 'vendor', 'verdock-core', 'js', 'verify.js')).href;

async function signedLog(count) {
  const { canonicalBytes } = await import(verifierUrl);
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519');
  const pub = Buffer.from(publicKey.export({ format: 'jwk' }).x, 'base64url').toString('hex');
  const lines = [];
  for (let i = 0; i < count; i++) {
    const r = { step_id: `case-${i}:check`, action_id: 'clearwake.refund.checked', params: { amount_minor: 150 + i, state: 'VERIFIED' },
      success: true, ts_ms: 1790000000000 + i, actor: { agent: 'clearwake-merchant', user: 'merchant' } };
    if (i > 0) r.prev_hash = crypto.createHash('sha256').update(lines[i - 1]).digest('hex');
    r.public_key = pub;
    r.signature = crypto.sign(null, Buffer.from(canonicalBytes(r)), privateKey).toString('hex');
    lines.push(JSON.stringify(r));
  }
  return { text: lines.join('\n') + '\n', pub };
}

test('money formats minor units without floating point drift', () => {
  assert.equal(L.money(150), '1.50');
  assert.equal(L.money(500000), '5000.00');
  assert.equal(L.money(7), '0.07');
  assert.equal(L.money(0), '0.00');
});

test('gauge share is clamped to the cap', () => {
  assert.equal(L.gaugeShare(250, '5.00'), 50);
  assert.equal(L.gaugeShare(500000, '5.00'), 100);
  assert.equal(L.gaugeShare(-5, '5.00'), 0);
  assert.equal(L.gaugeShare(100, '0'), 0);
});

test('countdown follows seller_response_due_date with the 24 hour escalation window', () => {
  const now = Date.parse('2026-10-31T12:00:00Z');
  assert.equal(L.countdown('2026-11-03T12:00:00Z', now).state, 'ok');
  const soon = L.countdown('2026-10-31T17:00:00Z', now);
  assert.equal(soon.state, 'soon'); assert.equal(soon.text, '5 h 00 min 00 s');
  assert.equal(L.countdown('2026-10-31T11:00:00Z', now).state, 'lapsed');
  assert.equal(L.countdown('', now).state, 'no deadline given');
});

test('rehearsal outcomes never claim verification against PayPal', () => {
  assert.equal(L.outcome('VERIFIED', true).label, 'Matches rehearsal record');
  assert.doesNotMatch(L.outcome('VERIFIED', true).label, /verified/i);
  assert.equal(L.outcome('VERIFIED', false).label, 'Verified against PayPal');
  assert.equal(L.outcome('UNKNOWN', true).cls, 'unknown');
  assert.equal(L.outcome('refused', true).cls, 'reversed');
});

test('case track shows UNKNOWN as its own node and refusals send nothing', () => {
  const unknown = L.track({ state: 'UNKNOWN', action: 'refund', proposed: 'refund', policy: { allowed: true } }, true);
  assert.equal(unknown.length, 4);
  assert.deepEqual(unknown[3], { cls: 'unknown', label: 'UNKNOWN' });
  const refused = L.track({ state: 'refused', action: 'refund', proposed: 'refund', policy: { allowed: false } }, true);
  assert.equal(refused[2].label, 'Nothing sent'); assert.equal(refused[3].cls, 'reversed');
  const settled = L.track({ state: 'VERIFIED', action: 'refund', proposed: 'refund', policy: { allowed: true, needs_approval: true } }, true);
  assert.equal(settled[1].label, 'Approved'); assert.equal(settled[3].label, 'Matches record');
});

test('tamper changes exactly one line and reports its position', () => {
  const text = '{"step_id":"a","success":true}\n{"step_id":"b","success":true}\n';
  const t = L.tamper(text, 2);
  assert.equal(t.line, 2);
  assert.equal(t.text.split('\n')[0], '{"step_id":"a","success":true}');
  assert.equal(t.text.split('\n')[1], '{"step_id":"b","success":false}');
  assert.equal(L.tamper(text, 99).line, 2);
});

test('a tampered line fails the real verifier at that line, and the chain breaks after it', async () => {
  const { verifyLog } = await import(verifierUrl);
  const { text, pub } = await signedLog(3);
  const clean = await verifyLog(text, pub);
  assert.equal(clean.ok, true); assert.equal(clean.count, 3);
  const t = L.tamper(text, 2);
  const report = await verifyLog(t.text, pub);
  assert.equal(report.ok, false);
  assert.deepEqual(report.failures.map(f => [f.line, f.reason]), [[2, 'signature invalid'], [3, 'chain break']]);
  const rows = L.receiptRows('merchant', t.text, report);
  assert.equal(rows.length, 3);
  assert.equal(rows[0].result, 'pass');
  assert.equal(rows[1].result, 'FAIL: signature invalid');
  assert.equal(rows[2].result, 'FAIL: chain break');
  assert.equal(rows[1].success, 'no');
});

test('receipt rows survive unreadable lines and unchecked logs', () => {
  const rows = L.receiptRows('pasted', 'not json\n', null);
  assert.deepEqual(rows, [{ log: 'pasted', line: 1, step: '', action: '', success: '', time: '', result: 'not checked' }]);
  assert.deepEqual(L.receiptRows('empty', '', null), []);
  assert.equal(L.isHexKey('ab'.repeat(32)), true);
  assert.equal(L.isHexKey('xyz'), false);
});

test('dispute ledger helpers: stage filter, proposal column with a dash, live deadline cell', () => {
  const rows = [{ stage: 'INQUIRY', proposed: 'settle_by_offer', paypal_status: 'RESOLVED', settled_before_escalation: true },
    { stage: 'CHARGEBACK', proposed: '', due: '2026-11-10T12:00:00Z', paypal_status: 'UNDER_REVIEW' },
    { stage: 'inquiry', proposed: 'no usable proposal', due: '2026-11-09T12:00:00Z' }];
  assert.deepEqual(rows.filter(r => L.stagePasses(r, 'INQUIRY')).length, 2);   // stage compare ignores case
  assert.deepEqual(rows.filter(r => L.stagePasses(r, 'CHARGEBACK')).length, 1);
  assert.equal(rows.filter(r => L.stagePasses(r, 'all')).length, 3);
  assert.equal(L.proposalOf(rows[0]), 'settle by offer');
  assert.equal(L.proposalOf(rows[1]), L.DASH);   // absent: a dash
  assert.equal(L.proposalOf(rows[2]), L.DASH);   // the model gave nothing usable: a dash
  const now = Date.parse('2026-11-09T09:00:00Z');
  assert.equal(L.deadlineOf(rows[0], now), 'closed');
  assert.equal(L.deadlineOf(rows[2], now), '3 h 00 min 00 s');
  assert.equal(L.deadlineOf(rows[2], now + 1000), '2 h 59 min 59 s');   // the cell ticks
  assert.equal(L.deadlineOf({ stage: 'INQUIRY' }, now), L.DASH);
  assert.equal(L.deadlineOf(rows[2], Date.parse('2026-11-09T13:00:00Z')), 'Deadline passed');
});

test('CSV export neutralises formulas and quotes commas, quotes and line breaks', () => {
  assert.equal(L.csvSafe('=HYPERLINK("x")'), '\'=HYPERLINK("x")');
  assert.equal(L.csvSafe('@sum'), '\'@sum');
  assert.equal(L.csvSafe('-2.50'), '-2.50');   // a plain negative number stays a number
  assert.equal(L.csvSafe(null), '');
  const csv = L.toCsv([{ headerName: 'Dispute', get: r => r.id }, { headerName: 'Buyer wrote', get: r => r.m }],
    [{ id: 'PP-1', m: 'He said "no", twice' }, { id: 'PP-2', m: '=1+1' }]);
  assert.equal(csv, 'Dispute,Buyer wrote\r\nPP-1,"He said ""no"", twice"\r\nPP-2,\'=1+1\r\n');
});
