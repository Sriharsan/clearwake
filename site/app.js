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

/* ---- pull the cable: case m, recorded real sandbox ---- */
(function cable() {
  const svg = $('cable-svg'), plug = $('plug'), path = $('cable-path'), sec = $('cable');
  const OUT = 490, CUT = 140;
  let x = OUT, cut = false, retried = false, drag = false, everCut = false;
  const queue = [...$('queue').children];
  const rows = (states, labels) => queue.forEach((li, i) => {
    li.classList.toggle('verified', states[i] === 'v'); li.classList.toggle('held', states[i] === 'h');
    li.querySelector('.qs').textContent = labels[i];
  });
  function draw() {
    plug.setAttribute('transform', `translate(${x} 0)`);
    path.setAttribute('d', `M30 74 C ${30 + (x - 30) * 0.3} ${x < 300 ? 126 : 118} ${30 + (x - 30) * 0.7} ${x < 300 ? 126 : 118} ${x} 74`);
  }
  function setCut(next) {
    if (next === cut) return;
    cut = next; x = cut ? CUT : OUT; draw();
    sec.classList.toggle('cut', cut);
    plug.setAttribute('aria-valuenow', cut ? '0' : '1'); plug.setAttribute('aria-valuetext', cut ? 'Cut' : 'Connected');
    const pill = $('net-pill'); pill.textContent = cut ? 'Network cut' : 'Network up'; pill.classList.toggle('coral', cut);
    $('cable-retry').hidden = !cut;
    if (cut) {
      everCut = true; retried = false;
      rows('vhh', ['Verified', 'Held, offline', 'Held, offline']);
      $('cable-msg').textContent = '22:37:01. The gateway is disconnected. Two refunds are held, offline. Nothing is sent.';
    } else if (everCut) {
      rows('vvv', ['Verified', 'Verified after reconnect', 'Verified after reconnect']);
      $('cable-msg').textContent = "22:37:17. The network is restored. PayPal's capture is read first, then both refunds are verified. Running it again opened no new tunnel.";
    }
  }
  $('cable-retry').addEventListener('click', () => {
    retried = true; rows('vhh', ['Verified', 'Still held', 'Still held']);
    $('cable-msg').textContent = 'A retry while offline sends nothing. Both refunds are still held.';
  });
  const at = e => { const b = svg.getBoundingClientRect(); return ((e.clientX - b.left) / b.width) * 640; };
  plug.addEventListener('pointerdown', e => { drag = true; svg.setPointerCapture(e.pointerId); e.preventDefault(); });
  svg.addEventListener('pointermove', e => { if (!drag) return; x = clamp(at(e) - 24, CUT, OUT); draw(); });
  const release = () => { if (!drag) return; drag = false; const want = x < 380; x = cut ? CUT : OUT; setCut(want); x = want ? CUT : OUT; draw(); };
  svg.addEventListener('pointerup', release); svg.addEventListener('pointercancel', release);
  plug.addEventListener('keydown', e => {
    if (e.key === 'ArrowLeft' || e.key === 'Home') { setCut(true); e.preventDefault(); }
    else if (e.key === 'ArrowRight' || e.key === 'End') { setCut(false); e.preventDefault(); }
  });
  draw();
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
