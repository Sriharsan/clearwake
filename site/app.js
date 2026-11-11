// Home page behaviour. Static site, no inline styles: shapes move through SVG attributes, states through class names.
// verify.js is verdock-core's browser verifier, copied unchanged. Receipts are fetched from this site;
// a visitor's own file is read in the browser and never sent anywhere.
import { verifyLog } from './verify.js';

const $ = id => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const usd = n => 'USD ' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const svgEl = (tag, attrs = {}) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

/* ---- the 1.5% line: the rule and fees from clearwake/fees.py ---- */
const RATE_LINE = 0.015, SALES_LINE = 100, STANDARD_FEE = 15, HIGH_VOLUME_FEE = 30;
const TOP = 30, BOTTOM = 350, SPAN = BOTTOM - TOP;

function gaugeInputs() {
  const num = id => Math.max(0, parseFloat($(id).value) || 0);
  return { sales: num('g-sales'), net: Math.max(1, num('g-net')), count: num('g-count'), avg: num('g-avg'), more: parseInt($('g-n').value, 10) || 0 };
}

function gauge() {
  const { sales, net, count, avg, more } = gaugeInputs();
  const rate = ((count + more) * avg) / net;
  const high = sales > SALES_LINE && rate >= RATE_LINE;
  const h = Math.min(rate / 0.03, 1) * SPAN;
  $('g-n-out').textContent = String(more);
  $('g-rate').textContent = (rate * 100).toFixed(2) + '%';
  $('g-fill').setAttribute('y', String(BOTTOM - h)); $('g-fill').setAttribute('height', String(h));
  $('g-fill').classList.toggle('over', rate >= RATE_LINE);
  for (const c of $('g-handle').querySelectorAll('circle')) c.setAttribute('cy', String(Math.max(TOP, BOTTOM - h)));
  $('g-handle').setAttribute('aria-valuenow', String(more));
  $('g-handle').setAttribute('aria-valuetext', `${more} more, ${(rate * 100).toFixed(2)} percent`);
  const pill = $('g-state');
  pill.textContent = rate >= RATE_LINE ? 'At or over the line' : 'Under the line';
  pill.classList.toggle('over', rate >= RATE_LINE);
  const box = $('g-msg');
  box.classList.toggle('bad', high); box.classList.toggle('ok', !high);
  const room = avg > 0 ? Math.ceil((RATE_LINE * net) / avg - 1e-9) - count : null;
  const r = (rate * 100).toFixed(2);
  if (sales <= SALES_LINE) {
    box.textContent = `With ${sales} sales in 3 months the High Volume rule needs more than ${SALES_LINE}, so it does not apply at ${r}%. A case that escalates to a claim of ${usd(2 * STANDARD_FEE)} or more carries the Standard fee of ${usd(STANDARD_FEE)}.`;
  } else if (high) {
    box.textContent = `${more} more escalate: ${r}% is past the 1.5% line. Every dispute then carries ${usd(HIGH_VOLUME_FEE)} instead of ${usd(STANDARD_FEE)}.`;
  } else if (room !== null && room > 0) {
    box.textContent = `${more} more escalate: ${r}%, under the line. ${Math.max(room - more, 1)} more disputes on top of this would reach 1.5%.`;
  } else {
    box.textContent = `${more} more escalate: ${r}%, under the line.`;
  }
}
['g-sales', 'g-net', 'g-count', 'g-avg', 'g-n'].forEach(id => $(id).addEventListener('input', gauge));
$('g-form').addEventListener('submit', e => e.preventDefault());

(function thermometer() {
  const svg = $('thermo'); let drag = false;
  const move = e => {
    const { net, count, avg } = gaugeInputs();
    if (avg <= 0) return;
    const box = svg.getBoundingClientRect();
    const y = ((e.clientY - box.top) / box.height) * 380;
    const rate = clamp((BOTTOM - y) / SPAN, 0, 1) * 0.03;
    $('g-n').value = String(clamp(Math.round((rate * net) / avg - count), 0, 20));
    gauge();
  };
  svg.addEventListener('pointerdown', e => { drag = true; svg.setPointerCapture(e.pointerId); move(e); });
  svg.addEventListener('pointermove', e => { if (drag) move(e); });
  const end = () => { drag = false; };
  svg.addEventListener('pointerup', end); svg.addEventListener('pointercancel', end);
  $('g-handle').addEventListener('keydown', e => {
    const step = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1, PageUp: 5, PageDown: -5 }[e.key];
    const n = $('g-n');
    if (step) n.value = String(clamp((parseInt(n.value, 10) || 0) + step, 0, 20));
    else if (e.key === 'Home') n.value = '0'; else if (e.key === 'End') n.value = '20'; else return;
    e.preventDefault(); gauge();
  });
})();
gauge();

/* ---- pull the cable: case m, recorded real sandbox. Refund ids and amounts come from data/ledger.json, request ids from the signed receipts. ---- */
(function cable() {
  const svg = $('cable-svg'), plug = $('plug'), path = $('cable-path'), sec = $('cable');
  if (!svg || !plug) return;
  const CUT = -50, STAGE = [135, 130], GATE = [300, 130], RECORD_Y = 162;
  const OUTBOX = [null, [52, RECORD_Y], [90, RECORD_Y]], PAID = [[497, RECORD_Y], [533, RECORD_Y], [568, RECORD_Y]];
  const heldSlot = k => [67, 296 + 34 * k];
  let tx = 0, cut = false, drag = false, running = false, toks = [], held = [], unknown = -1, started = false;
  const wait = ms => new Promise(r => setTimeout(r, reduced ? Math.min(ms, 350) : ms));
  const place = (t, p) => { t.pos = p; t.g.setAttribute('transform', `translate(${p[0]} ${p[1]})`); };
  function tween(t, to, ms, abortAt) {
    const from = t.pos;
    if (reduced || !ms) { place(t, to); return Promise.resolve(false); }
    return new Promise(res => {
      const t0 = performance.now();
      const step = now => {
        const k = clamp((now - t0) / ms, 0, 1), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        const p = [from[0] + (to[0] - from[0]) * e, from[1] + (to[1] - from[1]) * e];
        place(t, p);
        if (abortAt && cut && p[0] >= abortAt) return res(true);
        if (k < 1) requestAnimationFrame(step); else res(false);
      };
      requestAnimationFrame(step);
    });
  }
  const setState = (t, s) => { t.state = s; t.g.setAttribute('class', 'cb-tok ' + ({ held: 'held', unk: 'unk', paid: 'paid' }[s] || '')); };
  const say = msg => { $('cable-msg').textContent = msg; };
  function render() {
    const paid = toks.filter(t => t.state === 'paid').length, nHeld = held.length;
    $('cb-paidn').textContent = `Paid ${paid}`; $('cb-heldn').textContent = `Held ${nHeld}`;
    $('cb-score').textContent = `Paid ${paid}, Held ${nHeld}`;
    const label = { ready: 'Ready', send: 'Sending', held: 'Held at the Agents side', unk: "UNKNOWN, reading PayPal's record first", paid: 'Paid once, same PayPal-Request-Id' };
    toks.forEach((t, i) => {
      t.li.classList.toggle('held', t.state === 'held' || t.state === 'unk'); t.li.classList.toggle('paid', t.state === 'paid');
      t.st.textContent = i === 0 ? 'Paid and verified before the cut' : (t.state === 'paid' && !t.wasHeld ? 'Paid once' : label[t.state]);
    });
    sec.classList.toggle('unknown', unknown >= 0);
    $('cb-rstate').textContent = unknown >= 0 ? 'UNKNOWN' : 'Clear';
    $('cable-final').hidden = !toks.length || paid < toks.length;
    $('cable-reset').hidden = !started;
    $('cable-send').disabled = !toks.some(t => t.state === 'ready');
  }
  const restack = () => held.forEach((h, k) => tween(h, heldSlot(k), 0));
  async function go(t) {
    if (t.state === 'held') held.splice(held.indexOf(t), 1);
    restack(); setState(t, 'send'); render();
    await tween(t, STAGE, 450);
    const back = cut || await tween(t, GATE, 650, 150);
    if (back) {
      await tween(t, STAGE, 250);
      held.push(t); setState(t, 'held'); t.wasHeld = true;
      await tween(t, heldSlot(held.length - 1), 450);
      say('Plug out. The refund stopped at the Agents side and is held. Nothing was sent, and nothing is lost.'); render(); return;
    }
    if (t.wasHeld) {
      unknown = t.i; setState(t, 'unk'); render();
      say(`UNKNOWN until PayPal's record is read. Capture status read first: ${t.capture}. Replaying with the same PayPal-Request-Id.`);
      await wait(1200); unknown = -1;
    }
    await tween(t, [465, 130], 600);
    await tween(t, PAID[t.i], 350);
    setState(t, 'paid'); render();
  }
  async function drive() {
    if (running) return; running = true;
    for (;;) {
      const next = toks.find(t => t.state === 'send') || (!cut && held[0]);
      if (!next) break;
      await go(next);
    }
    running = false;
    if (toks.length && toks.every(t => t.state === 'paid')) say('The network is up and every held refund has replayed. PayPal shows each refund once.');
    render();
  }
  function draw() {
    plug.setAttribute('transform', `translate(${tx} 0)`);
    const px = 192 + tx;
    path.setAttribute('d', `M125 130Q${(125 + px) / 2} ${130 - tx * 0.4} ${px} 130`);
  }
  function setCut(next) {
    if (next === cut) return;
    cut = next; tx = cut ? CUT : 0; draw(); started = true; sec.classList.add('used');
    sec.classList.toggle('cut', cut);
    plug.setAttribute('aria-valuenow', cut ? '0' : '1'); plug.setAttribute('aria-valuetext', cut ? 'Cut' : 'Connected');
    const pill = $('net-pill'); pill.textContent = cut ? 'Network cut' : 'Network up'; pill.classList.toggle('coral', cut);
    if (cut) {
      say('Plug out. Nothing leaves the Agents container. Refunds sent now stop at the Agents side and wait in the held queue.');
      toks.forEach(t => { if (t.state === 'ready') setState(t, 'send'); });
    } else if (held.length) say("Plug in. Each held refund is UNKNOWN until PayPal's record is read, then it replays with the same PayPal-Request-Id.");
    else say('Plug in. Network up.');
    render(); drive();
  }
  function reset() {
    if (running) return;
    cut = false; tx = 0; held = []; unknown = -1; started = false; sec.classList.remove('cut', 'used');
    plug.setAttribute('aria-valuenow', '1'); plug.setAttribute('aria-valuetext', 'Connected');
    $('net-pill').textContent = 'Network up'; $('net-pill').classList.remove('coral');
    toks.forEach((t, i) => { t.wasHeld = false; setState(t, i === 0 ? 'paid' : 'ready'); place(t, i === 0 ? PAID[0] : OUTBOX[i]); });
    draw(); say("Network up. Refund 1 is paid and verified against PayPal's record. Refunds 2 and 3 are ready."); render();
  }
  $('cable-send').addEventListener('click', () => {
    started = true; toks.forEach(t => { if (t.state === 'ready') setState(t, 'send'); });
    say(cut ? 'Sending with the plug out. Watch where the refunds stop.' : 'Network up. The refunds pass the gateway and PayPal records each once.');
    render(); drive();
  });
  $('cable-reset').addEventListener('click', reset);
  const at = e => { const b = svg.getBoundingClientRect(); return ((e.clientX - b.left) / b.width) * 600; };
  plug.addEventListener('pointerdown', e => { drag = true; svg.setPointerCapture(e.pointerId); e.preventDefault(); });
  svg.addEventListener('pointermove', e => { if (!drag) return; tx = clamp(at(e) - 210, CUT, 0); draw(); });
  const release = () => { if (!drag) return; drag = false; const want = tx < CUT / 2; tx = cut ? CUT : 0; setCut(want); tx = want ? CUT : 0; draw(); };
  svg.addEventListener('pointerup', release); svg.addEventListener('pointercancel', release);
  plug.addEventListener('keydown', e => {
    if (e.key === 'ArrowLeft' || e.key === 'Home') { setCut(true); e.preventDefault(); }
    else if (e.key === 'ArrowRight' || e.key === 'End') { setCut(false); e.preventDefault(); }
    else if (e.key === 'Enter' || e.key === ' ') { setCut(!cut); e.preventDefault(); }
  });
  draw();
  (async () => {
    const [ledger, text] = await Promise.all([fetch('data/ledger.json').then(r => r.json()), fetch('receipts/case-m-merchant.ndjson').then(r => r.text())]);
    const reqs = {};
    for (const line of text.split('\n').filter(Boolean)) {
      const j = JSON.parse(line);
      if (j.action_id === 'clearwake.offline.held') reqs[j.params.key.split(':')[1].slice(0, 2)] = j.params.request_id;
    }
    const rows = ledger.rows.filter(r => /^m[123]$/.test(r.case)).sort((a, b) => a.case.localeCompare(b.case));
    const list = $('queue'), layer = $('cb-tokens');
    rows.forEach((r, i) => {
      const g = svgEl('g'), c = svgEl('circle', { r: 14 }), n = svgEl('text', { y: 6 });
      n.textContent = String(i + 1); g.append(c, n); layer.append(g);
      const li = el('li', { 'data-q': i + 1 }, el('b', { text: String(i + 1) }),
        el('span', {}, el('span', { class: 'mono', text: r.record.refund_id }), ' ', el('span', { text: usd(parseFloat(r.amount)) })),
        el('span', { class: 'cb-st' }), reqs[r.case] ? el('span', { class: 'cb-rid', text: `PayPal-Request-Id ${reqs[r.case]}` }) : null);
      list.append(li);
      toks.push({ i, g, li, st: li.querySelector('.cb-st'), capture: r.record.capture_status_read_first || 'read first', state: i === 0 ? 'paid' : 'ready', pos: [0, 0], wasHeld: false });
    });
    toks.forEach((t, i) => { setState(t, t.state); place(t, i === 0 ? PAID[0] : OUTBOX[i]); });
    render();
  })().catch(() => say('The recorded run could not be loaded.'));
})();

/* ---- receipts ---- */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'text') node.textContent = value;
    else if (key === 'class') node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) if (child) node.append(child);
  return node;
}

const hex = buf => Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join('');
const sha = async s => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)));

async function loadReceipts() {
  const manifest = await (await fetch('receipts/manifest.json')).json();
  const get = async file => ({ log: manifest.logs.find(l => l.file === file), text: await (await fetch(file)).text() });
  const o = await get('receipts/case-o-dispatch.ndjson');
  $('proof-check').addEventListener('click', async () => {
    const report = await verifyLog(o.text.split('\n')[0] + '\n', o.log.public_key);
    const box = $('proof-result');
    box.classList.toggle('ok', report.ok); box.classList.toggle('bad', !report.ok);
    box.textContent = report.ok ? 'Pass: the signature on the dispatch receipt verifies against the published key.' : `Fail: ${report.failures[0].reason}`;
  });
  const hud = await (await fetch('data/hud-case.json')).json();
  await wake(await get(hud.merchant.file), await get(hud.buyer.file), hud);
}

function change(line) {
  const obj = JSON.parse(line);
  if (obj.params && typeof obj.params.offer_minor === 'number' && obj.params.offer_minor > 0) {
    const was = obj.params.offer_minor; obj.params.offer_minor = was * 10;
    return { text: JSON.stringify(obj), what: `offer_minor ${was} to ${was * 10}` };
  }
  const was = obj.success; obj.success = !was;
  return { text: JSON.stringify(obj), what: `success ${was} to ${!was}` };
}

async function wake(merchant, buyer, hud) {
  const all = merchant.text.replace(/\n$/, '').split('\n');
  const buyerCount = buyer.text.replace(/\n$/, '').split('\n').length;
  const idx = hud.merchant.wake_lines.map(n => n - 1);          // the five case 3 receipts inside the full merchant log
  const svg = $('wake-svg'), msg = $('chain-msg'), scene = $('wake-scene');
  const steps = [...document.querySelectorAll('#wake-steps .step')];
  $('chain-key').textContent = `Merchant agent public key ${merchant.log.public_key}`;
  const rings = idx.map((_, i) => {
    const r = 34 + i * 26;
    const c = svgEl('circle', { class: 'ring', cx: '150', cy: '150', r: String(r) });
    const t = svgEl('text', { class: 'ring-n', x: '150', y: String(150 - r + 4) }); t.textContent = String(i + 1);
    svg.append(c, t); return c;
  });
  const info = [];
  for (const at of idx) info.push({ hash: await sha(all[at]), rec: JSON.parse(all[at]), at });
  steps.filter(s => s.dataset.i !== '-1').forEach(s => {
    const i = Number(s.dataset.i), { hash, rec, at } = info[i];
    const time = new Date(rec.ts_ms).toISOString().slice(11, 19) + ' UTC';
    s.querySelector('.rec').textContent = `Log line ${at + 1} of ${all.length}, ${time}. Line hash ${hash.slice(0, 16)}. Links to ${rec.prev_hash.slice(0, 16)}. Signed ${rec.signature.slice(0, 16)}.`;
  });
  let picked = -1, current = -1;
  const paintCurrent = () => {
    steps.forEach(s => s.classList.toggle('now', Number(s.dataset.i) === current));
    rings.forEach((r, i) => { r.classList.toggle('on', i <= current || picked >= 0); r.classList.toggle('now', i === current); });
  };
  if (!reduced && 'IntersectionObserver' in window) {
    scene.classList.add('js-wake');
    document.documentElement.classList.add('js-wake');
    const io = new IntersectionObserver(entries => {
      for (const e of entries) if (e.isIntersecting) { current = Number(e.target.dataset.i); paintCurrent(); }
    }, { rootMargin: '-40% 0px -45% 0px' });
    steps.forEach(s => io.observe(s));
    paintCurrent();
  }
  const buyerReport = await verifyLog(buyer.text, buyer.log.public_key);
  async function run() {
    const body = all.slice(); let what = '';
    if (picked >= 0) { const c = change(all[idx[picked]]); body[idx[picked]] = c.text; what = c.what; }
    const report = await verifyLog(body.join('\n') + '\n', merchant.log.public_key);
    const bad = new Map();
    for (const f of report.failures) bad.set(f.line - 1, [...(bad.get(f.line - 1) || []), f.reason]);
    const firstBad = bad.size ? Math.min(...bad.keys()) : -1;
    rings.forEach((r, i) => {
      r.classList.toggle('broken', bad.has(idx[i]));
      r.classList.toggle('after', firstBad >= 0 && idx[i] > firstBad && !bad.has(idx[i]));
    });
    steps.forEach(s => {
      const i = Number(s.dataset.i); if (i < 0) return;
      s.classList.toggle('bad', bad.has(idx[i]));
      const b = s.querySelector('.hit'); b.textContent = i === picked ? 'Undo the change' : 'Change one value here';
      b.setAttribute('aria-pressed', i === picked ? 'true' : 'false');
    });
    paintCurrent();
    const ok = report.ok && buyerReport.ok;
    msg.classList.toggle('ok', ok); msg.classList.toggle('bad', !ok);
    if (ok) msg.textContent = `Pass: all ${report.count} merchant receipts and all ${buyerReport.count} buyer receipts verify, every hash links to the one before, each log signed by its published key.`;
    else if (!report.ok) {
      const where = [...bad.keys()].sort((a, b) => a - b).map(i => `log line ${i + 1} (${bad.get(i).join(', ')})`).join(' and ');
      msg.textContent = `Receipt ${picked + 1} changed (${what}). The wake breaks at ${where}. Rings after the break hang from a broken link.`;
    } else msg.textContent = `Fail: the buyer log has ${buyerReport.failures.length} problem${buyerReport.failures.length === 1 ? '' : 's'}, first at line ${buyerReport.failures[0].line}, ${buyerReport.failures[0].reason}.`;
  }
  steps.forEach(s => {
    const b = s.querySelector('.hit'); if (!b) return;
    b.addEventListener('click', () => { const i = Number(s.dataset.i); picked = picked === i ? -1 : i; run(); });
  });
  $('chain-reset').addEventListener('click', () => { picked = -1; run(); });
  await run();
}

$('own').addEventListener('submit', async event => {
  event.preventDefault();
  const result = $('own-result'), file = $('own-file').files[0], key = $('own-key').value.trim();
  result.classList.remove('ok', 'bad');
  if (!file) { result.textContent = 'Choose a file first.'; return; }
  if (!/^[0-9a-fA-F]{64}$/.test(key)) { result.textContent = 'The public key must be 64 hex characters.'; return; }
  if (file.size > 5 * 1024 * 1024) { result.textContent = 'Files up to 5 MB.'; return; }
  try {
    const report = await verifyLog(await file.text(), key);
    result.classList.toggle('ok', report.ok); result.classList.toggle('bad', !report.ok);
    result.textContent = report.ok ? `Pass: all ${report.count} lines, chain intact, signed by this key`
      : `Fail: ${report.failures.length} problem${report.failures.length === 1 ? '' : 's'} in ${report.count} lines. First: line ${report.failures[0].line}, ${report.failures[0].reason}`;
  } catch (error) {
    result.textContent = `Could not verify: ${error.message}`;
  }
});

loadReceipts().catch(() => { $('chain-msg').textContent = 'The recorded receipts could not be loaded.'; });
