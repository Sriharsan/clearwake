// Clearwake console: buyer agent, merchant control room and receipt verifier. Same-origin only; no third party hosts.
import { verifyLog } from '/verdock/verify.js';

const L = window.ClearwakeConsole;
const $ = id => document.getElementById(id);
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
let csrf = '', data = null, logs = [], tampered = null, lastEntryCount = null, grids = {};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const child of children.flat()) if (child !== null && child !== undefined && child !== false) node.append(child);
  return node;
}

function showError(text) { $('server-error').textContent = text || ''; $('server-error').hidden = !text; }

async function call(path, body) {
  const options = body === undefined ? { credentials: 'same-origin' } : {
    method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Clearwake-CSRF': csrf }, body: JSON.stringify(body)
  };
  let response;
  try { response = await fetch(path, options); } catch (e) { throw new Error('The local server did not answer. Is it still running?'); }
  let value = {};
  try { value = await response.json(); } catch (e) { value = {}; }
  if (!response.ok) throw new Error(`Server refused (${response.status}): ${value.error || 'no reason given'}`);
  return value;
}

async function refresh() {
  data = await call('/console/api/state');
  render();
}

// Navigation -------------------------------------------------------------------------------------
const SCREENS = ['buyer', 'merchant', 'verify'];
function route() {
  const name = SCREENS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'buyer';
  for (const s of SCREENS) $('screen-' + s).hidden = s !== name;
  for (const tab of document.querySelectorAll('.tabs .tab')) {
    if (tab.dataset.screen === name) tab.setAttribute('aria-current', 'page'); else tab.removeAttribute('aria-current');
  }
  document.title = { buyer: 'Buyer agent', merchant: 'Merchant control room', verify: 'Receipt verifier' }[name] + ' · Clearwake console';
  if (name === 'verify' && logs.length === 0) loadReceipts().catch(e => showError(e.message));
}

// Tables: a plain accessible table. AG Grid was tried and dropped: its row templates use inline style
// attributes, which this page's Content Security Policy (style-src 'self') blocks.
function makeGrid(host, columns, emptyId, caption) {
  let rows = [], key = null, dir = 1;
  const draw = () => {
    const sorted = key ? rows.slice().sort((a, b) => String(a[key]).localeCompare(String(b[key]), undefined, { numeric: true }) * dir) : rows;
    const head = columns.map(c => {
      const sort = key === c.field ? (dir > 0 ? 'ascending' : 'descending') : 'none';
      return el('th', { scope: 'col', 'aria-sort': sort }, el('button', { type: 'button', class: 'sort', onclick: () => { dir = key === c.field ? -dir : 1; key = c.field; draw(); } },
        c.headerName, el('span', { class: 'cw-sort', 'aria-hidden': 'true', text: sort === 'ascending' ? ' ▲' : sort === 'descending' ? ' ▼' : '' })));
    });
    host.replaceChildren(el('table', { class: 'plain-table' }, el('caption', { class: 'sr-only', text: caption }),
      el('thead', {}, el('tr', {}, head)),
      el('tbody', {}, sorted.map(r => el('tr', {}, columns.map(c => el('td', { class: (c.cellClassFor?.(r) || '') + ' ' + (c.cellClass || ''), text: r[c.field] ?? '' })))))));
  };
  host.classList.add('plain-table-wrap'); host.tabIndex = 0;
  return { set(next) { rows = next; host.hidden = rows.length === 0; $(emptyId).hidden = rows.length > 0; draw(); } };
}

// AG Grid Community (vendored, MIT) for the dispute ledger. Its styles carry this page's CSP nonce.
// Without it the plain sortable table above is used, so the ledger still works.
function makeAgGrid(host, columns, emptyId, caption, extra = {}) {
  const ag = window.agGrid;
  if (!ag || !ag.createGrid) return makeGrid(host, columns, emptyId, caption);
  if (ag.ModuleRegistry && ag.AllCommunityModule) ag.ModuleRegistry.registerModules([ag.AllCommunityModule]);
  const css = getComputedStyle(document.documentElement), v = name => css.getPropertyValue(name).trim();
  const theme = ag.themeQuartz.withParams({
    backgroundColor: v('--cw-surface'), foregroundColor: v('--cw-text'), headerBackgroundColor: v('--cw-raised'),
    borderColor: v('--cw-line'), accentColor: v('--cw-accent'), oddRowBackgroundColor: v('--cw-bg'),
    fontFamily: v('--cw-text-font'), fontSize: 13, headerFontSize: 12, spacing: 6, wrapperBorderRadius: 10
  });
  const api = ag.createGrid(host, {
    theme, styleNonce: document.querySelector('meta[name="cw-style-nonce"]')?.content,
    columnDefs: columns.map(c => ({ sortable: true, resizable: true, ...c })), rowData: [],
    defaultColDef: { minWidth: 110 }, suppressCellFocus: false, ensureDomOrder: true, animateRows: false,
    loading: false, overlayNoRowsTemplate: '<span>No disputes at this stage.</span>', ...extra
  });
  return { api, set(rows) { host.hidden = rows.length === 0; $(emptyId).hidden = rows.length > 0; api.setGridOption('rowData', rows); } };
}

function countdown(due) {
  if (!due) return 'no deadline given';
  const left = Math.round((Date.parse(due) - Date.now()) / 1000);
  if (left <= 0) return 'lapsed';
  const d = Math.floor(left / 86400), h = Math.floor(left % 86400 / 3600), m = Math.floor(left % 3600 / 60);
  return d ? `${d} d ${h} h` : `${h} h ${m} min`;
}

function renderFees() {
  const f = data.fees;
  const rate = f.rate_percent === null ? null : Number(f.rate_percent);
  $('fee-rate').textContent = rate === null ? 'no sales yet' : `${f.rate_percent}%`;
  $('rate-fill').style.width = rate === null ? '0' : Math.min(100, rate / 3 * 100).toFixed(1) + '%';
  $('rate-fill').classList.toggle('over', rate !== null && rate >= 1.5);
  $('fee-sales').textContent = String(f.sales);
  $('fee-settled').textContent = String(f.settled_before_escalation);
  $('fee-escalated').textContent = `escalated to a claim: ${f.escalated}`;
  $('fee-avoided').textContent = `${f.currency} ${f.fee_avoided}`;
  $('rule-link').href = f.rule_source[1]; $('fee-link').href = f.fee_source[1];
  grids.disputes.set(grids.disputes.api ? allDisputeRows() : disputeRows());
  const shown = grids.disputes.api ? grids.disputes.api.getDisplayedRowCount() : disputeRows().length;
  $('ledger-count').textContent = data.disputes.length ? `${shown} of ${data.disputes.length} disputes` : '';
  if (selectedDispute) showDetail(data.disputes.find(r => r.dispute === selectedDispute));
}

// 1. Buyer agent ---------------------------------------------------------------------------------
function renderBuyer() {
  const m = data.mandate;
  $('mandate-owner').textContent = `${m.owner}. Budget for this data folder.`;
  $('mandate-remaining').textContent = `${m.currency} ${m.remaining}`;
  $('mandate-budget').textContent = `${m.currency} ${m.budget}`;
  $('mandate-spent').textContent = `${m.currency} ${m.spent}`;
  const share = Math.min(100, Number(m.spent) / Number(m.budget) * 100 || 0);
  $('budget-fill').style.width = share.toFixed(1) + '%';
  $('budget-meter').setAttribute('aria-valuemax', m.budget); $('budget-meter').setAttribute('aria-valuenow', m.spent);
  $('mandate-cap').textContent = `${m.currency} ${m.per_item_cap}`;
  $('mandate-merchant').textContent = `${data.merchant.name}`;
  $('mandate-categories').textContent = m.categories.join(', ');
  $('mandate-currency').textContent = m.currency;
  $('catalog').replaceChildren(...data.catalog.map(p => {
    const inside = m.categories.includes(p.category);
    return el('li', {}, el('span', { class: 'name', text: p.name }), el('span', { class: 'price', text: `USD ${p.price}` }),
      el('span', { class: 'cat' + (inside ? '' : ' out'), text: inside ? p.category : `${p.category}, outside the mandate` }));
  }));
  const purchases = data.purchases;
  $('buy-history').replaceChildren(...purchases.slice().reverse().map(p => el('li', {},
    el('span', { class: 'when', text: p.at.replace('T', ' ').replace('Z', ' UTC') }),
    el('span', { class: 'what', text: `"${p.request}" → ${p.product ? p.product.name : 'no product'}` }),
    el('span', { class: 'status-chip ' + (p.allowed ? 'ok' : 'bad'), text: p.allowed ? 'Allowed, signed' : 'Refused' }))));
  $('buy-history-empty').hidden = purchases.length > 0;
  const last = purchases[purchases.length - 1];
  $('buy-empty').hidden = !!last; $('buy-result').hidden = !last; $('receipt-card').hidden = !(last && last.receipt);
  if (!last) return;
  $('proposal-model').textContent = last.model;
  $('proposal-product').textContent = last.product ? `${last.product.name}, USD ${L.money(last.product.price_minor)}` : 'No product matched';
  $('proposal-request').textContent = `Request: "${last.request}". Proposed id: ${last.proposed || 'none'}${last.note ? '. ' + last.note : ''}.`;
  $('decision-verdict').textContent = last.allowed ? 'Inside the mandate' : last.reason;
  $('decision-verdict').className = 'verdict ' + (last.allowed ? 'ok' : 'bad');
  const checks = Object.entries(last.checks || {});
  $('decision-checks').replaceChildren(...(checks.length ? checks : [['product found in this store', false]]).map(([name, ok]) =>
    el('li', {}, el('span', { text: name[0].toUpperCase() + name.slice(1) }), el('span', { class: 'mark ' + (ok ? 'pass' : 'fail'), text: ok ? 'Passed' : 'Failed' }))));
  if (last.receipt) {
    $('receipt-order').textContent = last.receipt.order_id;
    $('receipt-digest').textContent = last.receipt.digest;
    $('receipt-key').textContent = last.receipt.public_key;
    $('receipt-status').textContent = last.receipt.log_ok ? `Log checks out, ${last.receipt.log_lines} line${last.receipt.log_lines === 1 ? '' : 's'}` : 'Log check failed';
    $('receipt-status').className = 'status-chip ' + (last.receipt.log_ok ? 'ok' : 'bad');
  }
}

// 2. Merchant control room -----------------------------------------------------------------------
let pickerBuilt = false;
function buildPicker() {
  if (pickerBuilt) return; pickerBuilt = true;
  const legend = $('case-picker').querySelector('legend');
  $('case-picker').replaceChildren(legend, ...data.cases.map((c, i) => el('label', { class: 'case-option' },
    el('input', { type: 'radio', name: 'case', value: c.key, checked: i === 0 }),
    el('span', { class: 'key', text: c.key }),
    el('span', { class: 'label' }, c.title, el('small', { text: c.scope === 'outside' ? 'recorded case outside the product scope' : c.dispute ? 'PayPal dispute shape' : 'refund' })))));
}

function setGauge() {
  const g = data.gauge;
  const share = L.gaugeShare(g.amount_minor, g.cap);
  $('gauge-fill').setAttribute('stroke-dasharray', `${share.toFixed(1)} 100`);
  $('gauge-fill').classList.toggle('over', g.amount_minor > Number(g.cap) * 100);
  $('gauge-amount').textContent = `USD ${L.money(g.amount_minor)}`;
  $('gauge-limit').textContent = g.amount_minor > Number(g.cap) * 100 ? `above the USD ${g.cap} cap, refused` : `of the USD ${g.cap} cap`;
}

function animateMoney(entry) {
  const coin = $('coin');
  coin.className = 'coin';
  if (!entry) { $('flow-label').textContent = 'No money has moved yet.'; return; }
  void coin.offsetWidth;  // restart the animation
  const amount = `USD ${L.money(entry.amount_minor)}`;
  const moves = ['refund', 'accept_and_refund'].includes(entry.action);
  if (entry.state === 'UNKNOWN') { coin.classList.add('held'); $('flow-label').textContent = `${amount} held as UNKNOWN. Not retried; reconcile from the record.`; }
  else if (entry.state === 'refused') { coin.classList.add('stopped'); $('flow-label').textContent = `${amount} stopped at the merchant. Nothing was sent.`; }
  else if (entry.state === 'VERIFIED' && moves) { coin.classList.add('to-buyer'); $('flow-label').textContent = `${amount} moved merchant to buyer. Matches the local record.`; }
  else if (entry.state === 'awaiting approval') { $('flow-label').textContent = `${amount} waits for a person in the approval inbox.`; }
  else { $('flow-label').textContent = 'No money moved on this case.'; }
}

function lightAgents(entry) {
  const order = ['intake', 'evidence', 'decider', 'policy', 'checker'];
  const items = Object.fromEntries([...document.querySelectorAll('#agents li')].map(li => [li.dataset.agent, li]));
  for (const li of Object.values(items)) li.className = '';
  if (!entry) return;
  const reach = entry.state === 'refused' || entry.state === 'awaiting approval' || entry.state === 'approved, answer by hand' ? 3 : 4;
  order.forEach((name, i) => { if (i <= reach) items[name].className = 'lit'; });
  if (entry.state === 'refused' || entry.state === 'awaiting approval') items.policy.className = 'stop';
  if (entry.state === 'UNKNOWN' || entry.state === 'MISMATCH') items.checker.className = 'stop';
}

function caseItem(e) {
  const rehearsal = data.mode === 'rehearsal';
  const o = L.outcome(e.state, rehearsal);
  const nodes = L.track(e, rehearsal);
  const p = e.policy || {};
  const policyText = p.reason === 'escalated to a person' ? 'Escalated to a person'
    : `${p.allowed ? 'Allowed' : 'Not allowed'}: ${p.reason}${p.limit ? `, cap USD ${p.limit}` : ''}`;
  const amount = e.amount_minor !== undefined ? `USD ${L.money(e.amount_minor)}` : '';
  const actions = [];
  if (e.state === 'UNKNOWN' && e.kind === 'buyer complaint') {
    actions.push(el('button', { class: 'button small', type: 'button', onclick: () => act('/console/api/reconcile', { case_id: e.id }, `Reconciled ${e.id}.`) }, 'Reconcile from the record'));
  }
  return el('li', { class: 'case-item', id: 'case-' + e.id },
    el('div', { class: 'case-top' },
      el('div', {}, el('span', { class: 'case-id', text: `${e.key}. ${e.kind === 'PayPal dispute' ? e.dispute_id : e.id}${e.agent ? ' · ' + e.agent : ''}` }),
        el('p', { class: 'case-title', text: `${e.title}${amount ? ' · ' + amount : ''}` })),
      el('span', { class: 'status-chip ' + (o.cls === 'settled' ? 'ok' : o.cls === 'reversed' ? 'bad' : o.cls === 'unknown' ? 'ok' : 'wait'), text: o.label })),
    el('ol', { class: 'case-track', 'aria-label': 'Case progress' }, nodes.map(n => el('li', {}, el('span', { class: 'node ' + n.cls }),
      el('span', { class: n.cls === 'unknown' ? 'unknown-label' : '', text: n.label })))),
    el('div', { class: 'pair' },
      el('div', {}, el('span', { class: 'k', text: 'Model proposal' }), el('strong', { text: L.readable(e.proposed || e.action) || 'none' }), el('br'), el('span', { class: 'case-id', text: e.model || '' })),
      el('div', {}, el('span', { class: 'k', text: 'Policy decision' }), el('strong', { text: policyText }))),
    el('p', { class: 'case-detail', text: e.history.map(h => h.note ? `${h.note}: ${h.detail}` : h.detail).join(' ') }),
    actions.length ? el('div', { class: 'case-actions' }, actions) : null);
}

function inboxItem(a) {
  const pending = a.status === 'PENDING' && !a.expired;
  const when = new Date(a.requested_at * 1000).toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  return el('li', { class: 'inbox-item' + (pending ? '' : ' done') },
    el('dl', {},
      el('dt', { text: 'Action' }), el('dd', { text: a.action }),
      el('dt', { text: 'Amount' }), el('dd', { class: 'mono', text: `${a.currency} ${a.amount}` }),
      el('dt', { text: 'Limit' }), el('dd', { class: 'mono', text: a.limit ? `${a.currency} ${a.limit}` : 'none' }),
      el('dt', { text: 'Case' }), el('dd', { class: 'mono', text: a.subject }),
      el('dt', { text: 'Requested' }), el('dd', { text: `${when} by ${a.requested_by}` }),
      el('dt', { text: 'Status' }), el('dd', { text: a.expired && a.status === 'PENDING' ? 'expired' : a.status.toLowerCase() + (a.approver ? ` by ${a.approver}` : '') })),
    pending ? el('button', { class: 'button primary small', type: 'button', onclick: () => {
      const approver = $('approver').value.trim();
      act('/console/api/approve', { approval_id: a.id, approver }, `Approved by ${approver}.`);
    } }, `Approve ${a.currency} ${a.amount}`) : null);
}

function disputeItem(e) {
  const o = L.outcome(e.state, data.mode === 'rehearsal');
  const c = L.countdown(e.due, Date.now());
  return el('li', { class: 'dispute-item' },
    el('div', { class: 'case-top' }, el('span', { class: 'case-id', text: e.dispute_id }), el('span', { class: 'status-chip ' + (o.cls === 'settled' ? 'ok' : o.cls === 'reversed' ? 'bad' : 'wait'), text: o.label })),
    el('div', {}, el('span', { class: 'countdown ' + c.state, 'data-due': e.due, text: c.text }), el('span', { class: 'card-sub', text: ' until seller_response_due_date' })),
    el('dl', {},
      el('dt', { text: 'Reason' }), el('dd', { text: L.readable(e.reason) }),
      el('dt', { text: 'Amount' }), el('dd', { class: 'mono', text: `USD ${L.money(e.amount_minor)}` }),
      el('dt', { text: 'Action' }), el('dd', { text: L.readable(e.action) })),
    e.sources && e.sources.length ? el('ul', { class: 'sources', 'aria-label': 'Evidence sources' }, e.sources.map(s => el('li', { text: s }))) : el('p', { class: 'card-sub', text: 'No evidence record answers this reason.' }));
}

function renderMerchant() {
  buildPicker();
  setGauge();
  const entries = data.entries;
  $('cases-empty').hidden = entries.length > 0;
  $('case-list').replaceChildren(...entries.slice().reverse().map(caseItem));
  const pending = data.inbox.filter(a => a.status === 'PENDING' && !a.expired);
  const shown = data.inbox.slice().reverse().filter(a => a.status === 'PENDING' || a.status === 'APPROVED' || a.status === 'CONSUMED').slice(0, 8);
  $('inbox-list').replaceChildren(...shown.map(inboxItem));
  $('inbox-empty').hidden = shown.length > 0;
  $('inbox-title').textContent = pending.length ? `Approval inbox (${pending.length} waiting)` : 'Approval inbox';
  const disputes = entries.filter(e => e.kind === 'PayPal dispute').slice().reverse().slice(0, 12);
  $('dispute-list').replaceChildren(...disputes.map(disputeItem));
  $('disputes-empty').hidden = disputes.length > 0;
  const latest = entries[entries.length - 1];
  const fresh = lastEntryCount !== null && entries.length !== lastEntryCount;
  lastEntryCount = entries.length;
  const money = entries.slice().reverse().find(e => e.kind === 'buyer complaint' || e.action === 'accept_and_refund');
  if (fresh || !$('coin').dataset.drawn) { animateMoney(latest && (latest.kind === 'buyer complaint' || latest.action === 'accept_and_refund') ? latest : money); $('coin').dataset.drawn = '1'; }
  lightAgents(latest);
  $('side-buyer').replaceChildren(...(latest ? [el('div', { class: 'bubble appear' }, el('span', { class: 'who', text: latest.kind }),
    latest.message || L.readable(latest.reason) || '', ' ', el('span', { class: 'amount', text: `USD ${L.money(latest.amount_minor)}` }))] : [el('p', { class: 'card-sub', text: 'Waiting for a case.' })]));
  grids.ledger.set(data.ledger.rows.map(r => ({ ...r, state: r.state === 'VERIFIED' ? L.outcome('VERIFIED', data.mode === 'rehearsal').label.toLowerCase() : r.state })));
  renderFees();
}

// 3. Receipt verifier ----------------------------------------------------------------------------
async function loadReceipts() {
  const value = await call('/console/api/receipts');
  logs = value.logs.map(l => ({ ...l, original: l.text, report: null }));
  tampered = null; $('restore').disabled = true; $('tamper-note').textContent = '';
  drawLogs();
}

function drawLogs() {
  $('log-cards').replaceChildren(...logs.map(l => {
    const lines = l.text ? l.text.replace(/\n$/, '').split('\n').length : 0;
    const state = l.report ? (l.report.ok ? 'ok' : 'bad') : '';
    return el('article', { class: 'log-card ' + state },
      el('h3', { text: l.title }),
      el('span', { class: 'card-sub', text: lines ? `${lines} line${lines === 1 ? '' : 's'}${tampered && tampered.log === l.name ? ', one changed in memory' : ''}` : 'No receipts yet' }),
      el('span', { class: 'key', text: 'Public key ' + l.public_key }),
      el('span', { class: 'result', text: !l.report ? 'Not checked yet' : l.report.ok ? `Pass: all ${l.report.count} lines` : `Fail: ${l.report.failures.length} problem${l.report.failures.length === 1 ? '' : 's'}` }),
      l.report && !l.report.ok ? el('ul', { class: 'fails' }, l.report.failures.slice(0, 4).map(f => el('li', { text: `line ${f.line}: ${f.reason}` }))) : null);
  }));
  const rows = logs.flatMap(l => L.receiptRows(l.name, l.text, l.report));
  grids.receipts.set(rows);
  const checked = logs.filter(l => l.report);
  if (!checked.length) { $('verify-summary').textContent = ''; $('verify-summary').className = 'verify-summary'; return; }
  const failures = checked.flatMap(l => l.report.failures.map(f => `${l.name} line ${f.line}: ${f.reason}`));
  $('verify-summary').textContent = failures.length ? `Verification failed at ${failures[0]}` + (failures.length > 1 ? ` and ${failures.length - 1} more` : '') : `All ${checked.reduce((n, l) => n + l.report.count, 0)} lines pass`;
  $('verify-summary').className = 'verify-summary ' + (failures.length ? 'bad' : 'ok');
}

async function verifyAll() {
  if (!crypto?.subtle) throw new Error('This browser has no WebCrypto here. Open the page on 127.0.0.1.');
  for (const l of logs) l.report = await verifyLog(l.text, l.public_key);
  drawLogs();
}

async function doTamper() {
  const target = logs.find(l => l.text && l.text.trim());
  if (!target) { $('tamper-note').textContent = 'No receipts to change yet. Run a case first.'; return; }
  for (const l of logs) l.text = l.original;
  const lines = target.text.trim().split('\n').length;
  const pick = Math.min(2, lines);
  const t = L.tamper(target.text, pick);
  target.text = t.text; tampered = { log: target.name, line: t.line };
  $('restore').disabled = false;
  $('tamper-note').textContent = `Changed line ${t.line} of the ${target.name} log in memory only (the file on disk is untouched).`;
  await verifyAll();
}

// Actions ----------------------------------------------------------------------------------------
async function act(path, body, okText) {
  showError('');
  $('runner-status').textContent = 'Working...';
  try {
    await call(path, body);
    $('runner-status').textContent = okText || '';
    logs = []; await refresh();
  } catch (e) {
    $('runner-status').textContent = '';
    showError(e.message);
  }
}

function wire() {
  window.addEventListener('hashchange', route);
  $('buy-form').addEventListener('submit', async event => {
    event.preventDefault();
    $('buy-error').hidden = true; $('buy-send').disabled = true;
    try { await call('/console/api/buy', { request: $('buy-request').value }); logs = []; await refresh(); $('buy-result').classList.remove('appear'); void $('buy-result').offsetWidth; $('buy-result').classList.add('appear'); }
    catch (e) { $('buy-error').textContent = e.message; $('buy-error').hidden = false; }
    finally { $('buy-send').disabled = false; }
  });
  for (const chip of document.querySelectorAll('.chip')) chip.addEventListener('click', () => { $('buy-request').value = chip.dataset.request; $('buy-request').focus(); });
  $('case-form').addEventListener('submit', async event => {
    event.preventDefault();
    const key = new FormData($('case-form')).get('case');
    $('case-run').disabled = true;
    await act('/console/api/case', { case: key }, `Case ${key} ran. Newest case is at the top of the list.`);
    $('case-run').disabled = false;
  });
  $('reset').addEventListener('click', () => act('/console/api/reset', {}, 'Started a new local folder. Earlier folders stay on disk.').then(() => { lastEntryCount = null; }));
  $('verify-all').addEventListener('click', () => verifyAll().catch(e => showError(e.message)));
  $('tamper').addEventListener('click', () => doTamper().catch(e => showError(e.message)));
  $('restore').addEventListener('click', () => { for (const l of logs) l.text = l.original; tampered = null; $('restore').disabled = true; $('tamper-note').textContent = 'Original logs restored.'; verifyAll().catch(e => showError(e.message)); });
  $('own-file').addEventListener('change', async () => { const file = $('own-file').files[0]; if (file) $('own-text').value = await file.text(); });
  $('own-form').addEventListener('submit', async event => {
    event.preventDefault();
    $('own-error').hidden = true;
    const text = $('own-text').value, key = $('own-key').value.trim();
    if (!text.trim()) { $('own-error').textContent = 'Paste a log or choose a file.'; $('own-error').hidden = false; return; }
    if (!L.isHexKey(key)) { $('own-error').textContent = 'The public key must be 64 hex characters.'; $('own-error').hidden = false; return; }
    const own = { name: 'pasted', title: 'Pasted or loaded log', public_key: key.toLowerCase(), text: text.endsWith('\n') ? text : text + '\n', original: text, report: null };
    logs = logs.filter(l => l.name !== 'pasted').concat(own);
    try { own.report = await verifyLog(own.text, own.public_key); } catch (e) { $('own-error').textContent = e.message; $('own-error').hidden = false; }
    drawLogs();
  });
  setInterval(() => {
    for (const node of document.querySelectorAll('.countdown[data-due]')) {
      const c = L.countdown(node.dataset.due, Date.now());
      node.textContent = c.text; node.className = 'countdown ' + c.state;
    }
  }, 1000);
}

let stageFilter = 'all', selectedDispute = null;
const DISPUTE_COLUMNS = [
  { field: 'dispute', headerName: 'Dispute', minWidth: 170, cellClass: 'cell-mono', pinned: 'left' },
  { field: 'reason', headerName: 'Reason', minWidth: 170, valueFormatter: p => L.readable(p.value) },
  { field: 'amount', headerName: 'Amount USD', minWidth: 110, cellClass: 'cell-mono' },
  { field: 'stage', headerName: 'Stage', minWidth: 120 },
  { colId: 'countdown', field: 'countdown', headerName: 'Deadline', minWidth: 160, cellClass: 'cell-mono',
    valueGetter: p => L.deadlineOf(p.data, Date.now()),
    cellClassRules: { 'cw-late': p => p.value === 'Deadline passed', 'cw-soon': p => !!(p.data && p.data.due && p.value !== 'closed' && L.countdown(p.data.due, Date.now()).state === 'soon') } },
  { field: 'due', headerName: 'Due (UTC)', minWidth: 190, cellClass: 'cell-mono', hide: true },
  { field: 'proposal_text', headerName: 'Model proposal', minWidth: 160, tooltipField: 'model' },
  { field: 'decided', headerName: 'Policy decision', minWidth: 170, valueFormatter: p => L.readable(p.value) || L.DASH },
  { field: 'model', headerName: 'Proposed by', minWidth: 170 },
  { field: 'paypal_status', headerName: 'PayPal record', minWidth: 150 },
  { field: 'state', headerName: 'Checked', minWidth: 140, cellClassRules: { 'cell-ok': p => p.value === 'VERIFIED', 'cell-wait': p => p.value === 'UNKNOWN' || p.value === 'PENDING' } },
  { field: 'settled', headerName: 'Settled before escalation', minWidth: 190, cellClassRules: { 'cw-yes': p => p.value === 'yes, no fee' } },
  { field: 'fee_avoided', headerName: 'Fee avoided USD', minWidth: 140, cellClass: 'cell-mono' },
  { field: 'dispatch', headerName: 'Dispatch proof', minWidth: 300, tooltipField: 'dispatch', cellClassRules: { 'cw-yes': p => /counted, sealed/.test(p.value || ''), 'cw-late': p => /^weak/.test(p.value || '') } }
];

function allDisputeRows() {
  return data.disputes.map(r => ({ ...r, countdown: L.deadlineOf(r, Date.now()), proposal_text: L.proposalOf(r), model: r.model || L.DASH,
    settled: r.settled_before_escalation ? 'yes, no fee' : 'no' }));
}
function disputeRows() { return allDisputeRows().filter(r => L.stagePasses(r, stageFilter)); }

function showDetail(row) {
  $('dispute-detail').hidden = !row; $('detail-hint').hidden = !!row;
  if (!row) return;
  const facts = [['Dispute', row.dispute], ['Case', row.case], ['Reason', L.readable(row.reason)], ['Amount', `USD ${row.amount}`], ['Stage', row.stage],
    ['PayPal status', row.paypal_status], ['Deadline', row.due ? `${row.due} (${L.deadlineOf(row, Date.now())})` : L.DASH],
    ['Model proposal', `${L.proposalOf(row)}${row.model ? ' (' + row.model + ')' : ''}`], ['Policy decision', L.readable(row.decided) || L.DASH],
    ['Checked', row.state], ['Why', row.policy_reason || L.DASH]];
  $('detail-facts').replaceChildren(...facts.map(([k, v]) => el('div', {}, el('dt', { text: k }), el('dd', { class: 'mono', text: String(v) }))));
  $('detail-message').textContent = row.message ? `Buyer wrote: "${row.message}"` : '';
  $('detail-raw').textContent = JSON.stringify(row.record || {}, null, 2);
}

function download(name, text) {
  const link = el('a', { href: URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' })), download: name });
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function exportCsv() {
  const name = `clearwake-disputes-${new Date().toISOString().slice(0, 10)}.csv`;
  const api = grids.disputes.api;
  // getDataAsCsv hands back the text; the grid's own download helper shows a spinner icon that this page's img-src would block.
  if (api) { download(name, api.getDataAsCsv({ allColumns: true, processCellCallback: p => L.csvSafe(p.formatValue ? p.formatValue(p.value) : p.value) })); return; }
  const heads = DISPUTE_COLUMNS.map(c => ({ headerName: c.headerName, get: r => c.field === 'reason' ? L.readable(r.reason) : r[c.field] ?? '' }));
  download(name, L.toCsv(heads, disputeRows()));
}

// The counted tally is already in the page. This reads the shipped file (web/batch-tally.json) and keeps the page equal to it.
// The extra tile is this console's own state: the signed logs it holds, checked in this browser with WebCrypto.
async function loadTotals() {
  try {
    const t = await (await fetch('/batch-tally.json', { credentials: 'same-origin' })).json();
    if (t.batch && Array.isArray(t.batch.items) && t.batch.items.length) {
      $('tally-batch-tag').textContent = t.batch.tag;
      $('tally-batch-src').textContent = t.batch.source;
      $('tally-batch').replaceChildren(...t.batch.items.map((n, i) => el('div', i ? {} : { class: 'lead' }, el('dd', { class: 'num', text: String(n.value) }), el('dt', { text: String(n.label) }))));
    }
    if (t.baseline && t.baseline.value) {
      $('tally-base-tag').textContent = t.baseline.tag;
      $('tally-base-value').textContent = t.baseline.value;
      $('tally-base-label').textContent = t.baseline.label;
      $('tally-base-src').textContent = t.baseline.source;
    }
  } catch (e) { /* the tally in the page stays */ }
  const tiles = [];
  try {
    const held = (await call('/console/api/receipts')).logs.filter(l => l.text && l.text.trim());
    if (held.length && crypto?.subtle) {
      const reports = [];
      for (const l of held) reports.push(await verifyLog(l.text, l.public_key));
      const ok = reports.filter(r => r.ok).length;
      tiles.push(el('div', {}, el('dd', { class: 'num', text: `${ok} of ${held.length}` }), el('dt', { text: 'signed logs in this console verify in your browser' }), el('dd', { class: 'src', text: 'Verified in your browser, the logs held by this console' })));
    }
  } catch (e) { /* no number rather than an invented one */ }
  if (!tiles.length) return;
  $('lead-numbers').replaceChildren(...tiles);
  $('lead-numbers').hidden = false;
}

// One negotiation per click. The log is the signed merchant receipt log, polled while the run goes.
let negTimer = null;
function drawSteps(log) {
  $('neg-log').replaceChildren(...log.steps.map(s => el('li', { class: s.ok ? 'ok' : 'bad' }, el('span', { class: 'mono', text: s.at }), el('span', { text: L.plain(s.action.replace('clearwake.', '').replaceAll('.', ': ')) }), el('span', { class: 'mono dim', text: s.step }), el('span', { class: 'mark ' + (s.ok ? 'pass' : 'fail'), text: s.ok ? 'done' : 'not done' }))));
}
async function pollNegotiation() {
  try {
    const log = await call('/console/api/negotiation');
    drawSteps(log);
    if (log.running) { negTimer = setTimeout(pollNegotiation, 600); return; }
    $('neg-run').disabled = false;
    $('neg-status').textContent = log.error ? `The run stopped: ${log.error}` : `Done: ${log.steps.length} signed steps, dispute ${log.case || ''}. The ledger below has the row.`;
    logs = []; await refresh();
  } catch (e) { $('neg-run').disabled = false; showError(e.message); }
}
async function runNegotiation() {
  showError(''); $('neg-run').disabled = true; $('neg-status').textContent = 'Running...'; $('neg-log').replaceChildren();
  try { await call('/console/api/negotiate', {}); pollNegotiation(); }
  catch (e) { $('neg-run').disabled = false; $('neg-status').textContent = ''; showError(e.message); }
}

async function start() {
  grids.ledger = makeGrid($('ledger-grid'), [
    { field: 'at', headerName: 'Time (UTC)', minWidth: 170, cellClass: 'cell-mono' },
    { field: 'case', headerName: 'Case or order', minWidth: 150, cellClass: 'cell-mono' },
    { field: 'movement', headerName: 'Movement', flex: 2, minWidth: 220 },
    { field: 'amount', headerName: 'Amount USD', minWidth: 120, cellClass: 'cell-mono' },
    { field: 'record', headerName: 'Provider record', minWidth: 170, cellClass: 'cell-mono' },
    { field: 'state', headerName: 'State', minWidth: 140, cellClassFor: r => /^(VERIFIED|matches|verified)/.test(r.state) ? 'cell-ok' : r.state === 'UNKNOWN' ? 'cell-wait' : '' }
  ], 'ledger-empty', 'Ledger of money movements');
  grids.disputes = makeAgGrid($('dispute-grid'), DISPUTE_COLUMNS, 'dispute-ledger-empty', 'Dispute ledger', {
    getRowId: p => p.data.dispute,
    rowSelection: { mode: 'singleRow', checkboxes: false, enableClickSelection: true },
    onSelectionChanged: e => { const row = e.api.getSelectedRows()[0]; selectedDispute = row ? row.dispute : null; showDetail(row); },
    isExternalFilterPresent: () => stageFilter !== 'all',
    doesExternalFilterPass: node => L.stagePasses(node.data, stageFilter)
  });
  $('stage-filter').addEventListener('change', () => {
    stageFilter = $('stage-filter').value;
    if (grids.disputes.api) grids.disputes.api.onFilterChanged();
    if (data) renderFees();
  });
  $('export-csv').addEventListener('click', exportCsv);
  setInterval(() => { if (grids.disputes.api) grids.disputes.api.refreshCells({ columns: ['countdown'], force: true }); }, 1000);
  setInterval(() => { if (data) renderFees(); }, 30000);
  grids.receipts = makeGrid($('receipt-grid'), [
    { field: 'log', headerName: 'Log', minWidth: 100 },
    { field: 'line', headerName: 'Line', minWidth: 80, flex: 0.5, cellClass: 'cell-mono' },
    { field: 'step', headerName: 'Step', flex: 2, minWidth: 190, cellClass: 'cell-mono', tooltip: true },
    { field: 'action', headerName: 'Action', flex: 2, minWidth: 210, cellClass: 'cell-mono', tooltip: true },
    { field: 'success', headerName: 'Success', minWidth: 90, flex: 0.6 },
    { field: 'time', headerName: 'Signed at (UTC)', minWidth: 170, cellClass: 'cell-mono' },
    { field: 'result', headerName: 'Result', flex: 2, minWidth: 200, tooltip: true, cellClassFor: r => r.result === 'pass' ? 'cell-ok' : r.result.startsWith('FAIL') ? 'cell-bad' : '' }
  ], 'receipts-empty', 'Receipt lines and verification results');
  $('neg-run').addEventListener('click', runNegotiation);
  wire();
  route();
  try {
    csrf = (await call('/console/api/session')).csrf;
    await refresh(); loadTotals();
    $('model-pill').textContent = 'Agents: ' + data.model;
    if (location.hash === '#verify') await loadReceipts();
  } catch (e) { showError(e.message); }
}

function render() {
  if (!data) return;
  renderRulesLast();
  $('hosted-line').hidden = !data.hosted;
  $('model-pill').textContent = 'Agents: ' + data.model;
  renderBuyer();
  renderMerchant();
  if (!$('screen-verify').hidden && logs.length === 0) loadReceipts().catch(e => showError(e.message));
}

// Say your rules: the sentence goes to the server, the readback comes from code, Confirm signs it.
let pendingRules = null;
function renderRulesLast() {
  const last = (data && data.rules && data.rules.last) || {};
  const parts = Object.entries(last).map(([role, r]) => `${role}: ${r.rules_hash} (${r.source})`);
  $('rules-last').textContent = 'Last signed rule hash: ' + (parts.length ? parts.join('; ') : 'none yet.');
}
function showRules(view) {
  pendingRules = view.ok ? view : null;
  $('rules-label').textContent = view.label ? `Read by: ${view.label}` + (view.latency_ms >= 0 ? `, ${view.latency_ms} ms` : '') : '';
  $('rules-question').hidden = !view.question; $('rules-question').textContent = view.question || '';
  $('rules-result').hidden = !view.ok;
  const readback = $('rules-readback'), diff = $('rules-diff');
  readback.replaceChildren(...view.readback.map(t => el('li', { text: t })));
  diff.replaceChildren(...view.diff.map(d => el('li', { class: d.changed ? '' : 'same', text: `${d.field}: ${d.before} to ${d.after}${d.changed ? '' : ' (unchanged)'}` })));
  $('rules-changes').textContent = [...view.changes, ...view.rejected].join(' ');
  if (!view.ok && !view.question) $('rules-question').hidden = false, $('rules-question').textContent = (view.rejected || []).join(' ') || 'These rules were not accepted. Please write them again.';
}
$('rules-propose').addEventListener('click', async () => {
  showError('');
  const button = $('rules-propose'), started = Date.now();
  button.disabled = true; $('rules-result').hidden = true; $('rules-question').hidden = true;
  const tick = setInterval(() => { $('rules-label').textContent = `Reading your sentence on this machine... ${Math.round((Date.now() - started) / 1000)} s. The local model can take up to a minute.`; }, 500);
  $('rules-label').textContent = 'Reading your sentence on this machine...';
  try { showRules(await call('/console/api/rules/propose', { text: $('rules-text').value, role: $('rules-role').value })); }
  catch (e) { $('rules-label').textContent = ''; showError(e.message); }
  finally { clearInterval(tick); button.disabled = false; }
});
$('rules-confirm').addEventListener('click', async () => {
  if (!pendingRules) return;
  showError('');
  try { await call('/console/api/rules/confirm', { role: pendingRules.role, rules_hash: pendingRules.rules_hash }); $('rules-result').hidden = true; pendingRules = null; logs = []; await refresh(); }
  catch (e) { showError(e.message); }
});

start();
