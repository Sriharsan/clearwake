'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '..', 'web', 'payment.js'), 'utf8');
const response = (data, status = 200) => ({ ok: status < 400, json: async () => data });
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
function fixture(role = 'owner', grant = 'NOT_GRANTED') {
  return { room: { revision: 1 }, member: { role }, artifact: { revision: 1 }, payment: {
    mode: 'rehearsal', case: { capture: 'SYNTHETIC-CAPTURE', amount: '1.00', currency: 'USD' },
    grant: { id: grant === 'NOT_GRANTED' ? null : 'synthetic-grant', status: grant, expires: 1700000000 }, operation: null
  } };
}
function harness() {
  const nodes = new Map(), events = new Map(), requests = [], routes = new Map();
  function element() { return { textContent: '', value: '', hidden: false, disabled: false, checked: false, open: false, readOnly: false, children: [], listeners: {},
    addEventListener(type, callback) { this.listeners[type] = callback; }, append(...values) { this.children.push(...values); }, replaceChildren(...values) { this.children = values; },
    reportValidity() { return true; }, querySelector() { return this.submit || (this.submit = element()); } }; }
  const get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
  get('create-form').elements = { brief: element() };
  routes.set('/api/session', () => response({ signed_in: false }));
  routes.set('/api/state', () => response(fixture()));
  const document = { getElementById: get, createElement: element, addEventListener(type, callback) { events.set(type, callback); } };
  vm.runInNewContext(code, { document, fetch: async (url, options = {}) => {
    requests.push({ url, options }); const handler = routes.get(url); if (!handler) throw new Error('Unexpected offline test request'); return handler(options);
  } });
  return { get, nodes, requests, routes, emit(type, detail) { events.get(type)?.({ detail }); },
    click(id) { return get(id).listeners.click?.(); }, async settled() { for (let i = 0; i < 5; i++) await new Promise(setImmediate); } };
}

test('exact effect is visible and owner acknowledgement is needed before granting', async () => {
  const app = harness(); await app.settled(); app.emit('clearwake:session', { csrf: 'synthetic-csrf' }); app.emit('clearwake:state', fixture());
  assert.match(app.get('payment-effect').textContent, /local refund of USD 1.00 for capture SYNTHETIC-CAPTURE, revision 1/);
  assert.equal(app.get('payment-grant-button').disabled, true);
  app.get('payment-ack').checked = true; app.get('payment-ack').listeners.change();
  assert.equal(app.get('payment-grant-button').disabled, false);
  app.routes.set('/api/refund-grant', () => response({ ok: true })); app.routes.set('/api/state', () => response(fixture('owner', 'ACTIVE')));
  app.click('payment-grant-button'); await app.settled();
  const request = app.requests.find(value => value.url === '/api/refund-grant');
  assert.equal(request.options.headers['X-Relayloom-CSRF'], 'synthetic-csrf');
  assert.deepEqual(JSON.parse(request.options.body), { revision: 1, grant_id: null, allow: true, capture: 'SYNTHETIC-CAPTURE', amount: '1.00', currency: 'USD' });
  assert.equal(app.get('payment-send').disabled, false);
});

test('late grant response after sign out cannot restore private data or authority', async () => {
  const app = harness(); await app.settled(); app.emit('clearwake:session', { csrf: 'synthetic-csrf' }); app.emit('clearwake:state', fixture());
  app.get('payment-ack').checked = true;
  const pending = deferred(); app.routes.set('/api/refund-grant', () => pending.promise);
  app.click('payment-grant-button'); app.emit('clearwake:clear');
  pending.resolve(response({ ok: true })); await app.settled();
  assert.equal(app.get('payment-panel').hidden, true);
  assert.equal(app.get('payment-send').disabled, true);
  assert.equal(app.get('payment-capture').textContent, '');
  assert.equal(app.get('payment-evidence').textContent, '');
  assert.equal(app.requests.filter(value => value.url === '/api/state').length, 0);
});

test('revocation remains available while a refund action waits; it sends no second refund', async () => {
  const app = harness(); await app.settled(); app.emit('clearwake:session', { csrf: 'synthetic-csrf' }); app.emit('clearwake:state', fixture('owner', 'ACTIVE'));
  const pending = deferred(); app.routes.set('/api/refund', () => pending.promise);
  app.click('payment-send');
  assert.equal(app.get('payment-send').disabled, true);
  assert.equal(app.get('payment-revoke').disabled, false);
  app.routes.set('/api/refund-grant', () => response({ ok: true }));
  app.routes.set('/api/state', () => response(fixture('owner', 'REVOKED')));
  app.click('payment-revoke'); await app.settled();
  const revoke = app.requests.find(value => value.url === '/api/refund-grant');
  assert.equal(JSON.parse(revoke.options.body).allow, false);
  pending.resolve(response({ ok: true })); await app.settled();
  assert.equal(app.requests.filter(value => value.url === '/api/refund').length, 1);
  assert.equal(app.get('payment-send').disabled, true);
});

test('viewer cannot initiate effects and a changed revision resets acknowledgement', async () => {
  const app = harness(); await app.settled(); app.emit('clearwake:session', { csrf: 'synthetic-csrf' }); app.emit('clearwake:state', fixture('viewer'));
  assert.equal(app.get('payment-owner').hidden, true);
  app.get('payment-ack').checked = true; app.click('payment-grant-button'); app.click('payment-send'); await app.settled();
  assert.equal(app.requests.filter(value => value.options.method === 'POST').length, 0);
  const current = fixture(); app.emit('clearwake:state', current); app.get('payment-ack').checked = true;
  current.room.revision = 2; app.emit('clearwake:state', current);
  assert.equal(app.get('payment-ack').checked, false);
  assert.equal(app.get('payment-grant-button').disabled, true);
});
