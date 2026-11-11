// Developers page: a hash chain drawn from the page's own text, copy buttons, cURL/Python tabs, replay of recorded
// responses, search, error explorer, checklist, command palette, and a receipt check that reuses verify.js unchanged.
import { verifyLog } from './verify.js';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const sections = $$('.sec');
const links = $$('.chain a');

// 1. Capture the text of each section before anything on the page changes.
const texts = sections.map(s => s.textContent.replace(/\s+/g, ' ').trim());
const enc = new TextEncoder();
async function sha(str) {
  const buf = await crypto.subtle.digest('SHA-256', enc.encode(str));
  return Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join('');
}
async function chainFor(tamperAt) {
  const out = []; let prev = '';
  for (let i = 0; i < sections.length; i++) {
    const text = i === tamperAt ? texts[i] + '.' : texts[i];
    const line = JSON.stringify({ step_id: sections[i].id, text_sha256: await sha(text), prev_hash: prev });
    prev = await sha(line); out.push({ prev: out.length ? out[out.length - 1].hash : '', hash: prev });
  }
  return out;
}
let sealed = null, live = null, tamperAt = null, cur = 0;
const ro = { s: $('.rs'), p: $('.rp'), h: $('.rh'), st: $('.rst'), btn: $('.tamper') };
function paint() {
  if (!sealed) return;
  links.forEach((a, i) => {
    const broken = live[i].hash !== sealed[i].hash;
    a.classList.toggle('broken', broken);
    a.classList.toggle('seen', i < cur && !broken);
    if (i === cur) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
  });
  const r = live[cur], broken = r.hash !== sealed[cur].hash;
  const num = String(cur + 1).padStart(2, '0');
  ro.s.textContent = `${num} ${sections[cur].dataset.title}`;
  ro.p.textContent = cur ? r.prev.slice(0, 12) : 'none';
  ro.h.textContent = r.hash.slice(0, 12);
  ro.st.textContent = broken ? (tamperAt === cur ? 'broken here' : 'broken: an earlier link changed') : 'sealed';
  ro.st.classList.toggle('bad', broken);
  ro.btn.textContent = tamperAt === cur ? 'Undo the change' : 'Add one character here';
  ro.btn.setAttribute('aria-pressed', String(tamperAt === cur));
  const a = links[cur], c = a.closest('.chain');
  if (c && c.scrollWidth > c.clientWidth) c.scrollLeft = a.parentElement.offsetLeft - 60;
  if (c && c.scrollHeight > c.clientHeight + 1) { const t = a.parentElement.offsetTop; if (t < c.scrollTop + 4 || t + 44 > c.scrollTop + c.clientHeight) c.scrollTop = Math.max(0, t - c.clientHeight / 2); }
}
async function init() {
  if (!(window.crypto && crypto.subtle)) { ro.h.textContent = 'unavailable'; return; }
  sealed = await chainFor(null); live = sealed; paint();
}
ro.btn.addEventListener('click', async () => {
  if (!sealed) return;
  tamperAt = tamperAt === cur ? null : cur;
  live = tamperAt === null ? sealed : await chainFor(tamperAt);
  paint();
});
function whichSection() {
  let n = 0; const line = innerHeight * .3 + 40;
  sections.forEach((s, i) => { if (s.getBoundingClientRect().top <= line) n = i; });
  if (n !== cur) { cur = n; paint(); }
}
let tick = false;
addEventListener('scroll', () => { if (tick) return; tick = true; setTimeout(() => { tick = false; whichSection(); }, 40); }, { passive: true });
init().then(whichSection);

// 2. Copy buttons (copy the visible pane)
for (const block of $$('.cb')) {
  const head = $('.cb-head', block);
  if (!head) continue;
  const btn = document.createElement('button');
  btn.type = 'button'; btn.className = 'copy'; btn.textContent = 'Copy'; btn.setAttribute('aria-label', 'Copy this code');
  btn.addEventListener('click', async () => {
    const pre = $('pre:not([hidden])', block); if (!pre) return;
    try { await navigator.clipboard.writeText(pre.textContent); }
    catch (e) {
      const range = document.createRange(); range.selectNodeContents(pre);
      const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
      try { document.execCommand('copy'); } catch (e2) {}
      sel.removeAllRanges();
    }
    btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
  });
  head.append(btn);
}

// 3. cURL / Python tabs
for (const box of $$('[data-tabs]')) {
  const tabs = $$('.ptab', box), panes = $$('pre[data-p]', box);
  const pick = (name, focus) => {
    tabs.forEach(t => { const on = t.dataset.p === name; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; if (on && focus) t.focus(); });
    panes.forEach(p => { p.hidden = p.dataset.p !== name; });
  };
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => pick(t.dataset.p));
    t.addEventListener('keydown', e => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); pick(tabs[(i + 1) % tabs.length].dataset.p, true); }
    });
  });
  pick('curl');
}

// 4. Replay a recorded response. Nothing is sent anywhere.
for (const fig of $$('.resp')) {
  const btn = $('.replay', fig), pre = $('.rp', fig), note = $('.replay-note', fig);
  const full = pre.textContent; let timer = null;
  btn.addEventListener('click', () => {
    clearInterval(timer);
    if (reduce) { pre.textContent = full; note.textContent = 'Replayed. This is a recorded response. Nothing was sent to PayPal.'; return; }
    const lines = full.split('\n'); let n = 0; pre.textContent = ''; note.textContent = 'Replaying a recorded response. Nothing is sent to PayPal.';
    timer = setInterval(() => {
      n++; pre.textContent = lines.slice(0, n).join('\n');
      if (n >= lines.length) { clearInterval(timer); note.textContent = 'Replayed. This is a recorded response. Nothing was sent to PayPal.'; }
    }, 140);
  });
}

// 5. Search this page: dim the links of sections that do not match, Enter jumps to the first match
const search = $('#docsearch'), findnote = $('#findnote');
function matches() {
  const q = search.value.trim().toLowerCase();
  return texts.map(t => !q || t.toLowerCase().includes(q));
}
search.addEventListener('input', () => {
  const m = matches(), q = search.value.trim();
  links.forEach((a, i) => a.classList.toggle('dim', !m[i]));
  findnote.textContent = q ? `${m.filter(Boolean).length} of ${m.length} sections match` : '';
});
search.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const i = matches().findIndex(Boolean);
  if (i >= 0) { location.hash = '#' + sections[i].id; sections[i].scrollIntoView(); }
});

// 6. Error explorer
const errs = $$('.err'), errq = $('#errsearch'), errn = $('#errcount');
function filterErrs() {
  const q = errq.value.trim().toLowerCase(); let n = 0;
  errs.forEach(li => { const hit = !q || li.textContent.toLowerCase().includes(q); li.hidden = !hit; if (hit) n++; });
  errn.textContent = q ? `${n} of ${errs.length} entries` : `${errs.length} entries`;
}
errq.addEventListener('input', filterErrs); filterErrs();

// 7. Checklist, remembered in this browser only
for (const box of $$('.checklist input')) {
  try { box.checked = localStorage.getItem('cw-dev-' + box.dataset.k) === '1'; } catch (e) {}
  box.addEventListener('change', () => { try { localStorage.setItem('cw-dev-' + box.dataset.k, box.checked ? '1' : '0'); } catch (e) {} });
}

// 8. Command palette on Ctrl K, slash for page search
const pal = $('#pal'), palq = $('#palq'), pall = $('#pall');
const items = [
  ...sections.map((s, i) => ({ k: 'Section', l: `${String(i + 1).padStart(2, '0')} ${s.dataset.title}`, go: () => { location.hash = '#' + s.id; s.scrollIntoView(); } })),
  ...$$('.ep').map(e => ({ k: 'Endpoint', l: e.dataset.title, go: () => { location.hash = '#' + e.id; e.scrollIntoView(); } })),
  ...errs.map(e => ({ k: 'Error', l: e.dataset.title, go: () => { errq.value = e.dataset.title; filterErrs(); location.hash = '#errors'; $('#errors').scrollIntoView(); } })),
  { k: 'Action', l: 'Switch theme', go: () => $('.theme').click() },
  { k: 'Action', l: 'Verify the settled by offer log', go: () => { location.hash = '#vcard'; $('#vcard').scrollIntoView(); } }
];
let shown = [], sel = 0, opener = null;
function renderPal() {
  const q = palq.value.trim().toLowerCase();
  shown = items.filter(i => !q || (i.k + ' ' + i.l).toLowerCase().includes(q)).slice(0, 40); sel = 0;
  pall.replaceChildren(...shown.map((it, i) => {
    const li = document.createElement('li'); li.setAttribute('role', 'option'); li.setAttribute('aria-selected', String(i === 0));
    const k = document.createElement('span'); k.className = 'k'; k.textContent = it.k;
    const l = document.createElement('span'); l.className = 'l'; l.textContent = it.l;
    li.append(k, l); li.addEventListener('click', () => choose(i)); return li;
  }));
}
function mark() { $$('li', pall).forEach((li, i) => { li.setAttribute('aria-selected', String(i === sel)); if (i === sel) li.scrollIntoView({ block: 'nearest' }); }); }
function openPal() { opener = document.activeElement; pal.hidden = false; palq.value = ''; renderPal(); palq.focus(); }
function closePal() { pal.hidden = true; if (opener && opener.focus) opener.focus(); }
function choose(i) { const it = shown[i]; closePal(); if (it) it.go(); }
palq.addEventListener('input', renderPal);
palq.addEventListener('keydown', e => {
  if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, shown.length - 1); mark(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); mark(); }
  else if (e.key === 'Enter') { e.preventDefault(); choose(sel); }
  else if (e.key === 'Tab') { e.preventDefault(); }
});
pal.addEventListener('click', e => { if (e.target.hasAttribute('data-close')) closePal(); });
$('#palopen').addEventListener('click', openPal);
addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); if (pal.hidden) openPal(); else closePal(); return; }
  if (e.key === 'Escape' && !pal.hidden) { closePal(); return; }
  if (e.key === '/' && pal.hidden && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) { e.preventDefault(); search.focus(); }
});

// 9. Receipt check with the site's own verify.js
const card = $('#vcard');
if (card) {
  const result = $('.vresult', card), fails = $('.vfails', card); let text = null;
  async function run(tamper) {
    try {
      if (text === null) text = await (await fetch(card.dataset.log)).text();
      let t = text;
      if (tamper) { const lines = text.replace(/\n$/, '').split('\n'); lines[1] = lines[1].replace('"success":true', '"success":false'); t = lines.join('\n') + '\n'; }
      const r = await verifyLog(t, card.dataset.key);
      result.textContent = r.ok ? `Pass: all ${r.count} lines, chain intact, signed by this key`
        : `Fail: ${r.failures.length} problem${r.failures.length === 1 ? '' : 's'} in ${r.count} lines`;
      result.className = 'vresult ' + (r.ok ? 'ok' : 'bad');
      fails.replaceChildren(...r.failures.slice(0, 5).map(f => { const li = document.createElement('li'); li.textContent = `line ${f.line}: ${f.reason}`; return li; }));
    } catch (e) { result.className = 'vresult bad'; result.textContent = 'Could not verify: ' + e.message; }
  }
  $('[data-act="verify"]', card).addEventListener('click', () => run(false));
  $('[data-act="tamper"]', card).addEventListener('click', () => run(true));
}
