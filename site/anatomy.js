// Anatomy of one dispute: an exploded view. Batch case 3 flows down six layers. Data: data/hud-case.json (recorded run).
(() => {
  const root = document.getElementById('anatomy');
  if (!root) return;
  const NS = 'http://www.w3.org/2000/svg';
  const board = root.querySelector('.anat-board');
  const leaders = root.querySelector('.anat-leaders');
  const bead = root.querySelector('.anat-bead');
  const cap = root.querySelector('.anat-cap');
  const openBtn = root.querySelector('.anat-open');
  const views = [...root.querySelectorAll('.anat-view')];
  const slabs = [1, 2, 3, 4, 5, 6].map((n) => root.querySelector(`.slab[data-layer="${n}"]`));
  const parts = [1, 2, 3, 4, 5, 6].map((n) => root.querySelector(`.anat-part[data-layer="${n}"]`));
  const presets = { all: [1, 2, 3, 4, 5, 6], rules: [1, 4], agents: [2, 3], receipts: [5], paypal: [6] };
  const captions = [
    'One dispute. Six layers.',
    'The owner says the rule once. Clearwake reads it back and signs it.',
    'The buyer agent files the claim. It cannot pay itself.',
    "The merchant agent answers inside its owner's limits.",
    'The gate checks the action before any money moves.',
    'Every step leaves a signed receipt. Each link checks the one before it.',
    "PayPal's record is the judge. It matches.",
    'Settled inside PayPal. Paid once. USD 5.00.'];
  const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const narrow = window.matchMedia('(max-width: 960px)');
  let step = 0;
  let view = 'all';
  let sel = presets.all;
  let timers = [];
  let tracking = 0;

  // leader lines: one per layer, from the card to its anchor on the figure
  const leads = [1, 2, 3, 4, 5, 6].map((n) => {
    const g = document.createElementNS(NS, 'g');
    g.setAttribute('class', `k-${['skel', 'musc', 'musc', 'skel', 'skin', 'heart'][n - 1]}`);
    const p = document.createElementNS(NS, 'path');
    p.setAttribute('class', 'anat-lead');
    const d1 = document.createElementNS(NS, 'circle');
    d1.setAttribute('class', 'anat-leadpt');
    d1.setAttribute('r', '4');
    g.append(p, d1);
    leaders.append(g);
    return { p, d1 };
  });
  const draw = () => {
    if (narrow.matches) return;
    const b = board.getBoundingClientRect();
    leads.forEach((l, i) => {
      const a = slabs[i].querySelector('.anc circle').getBoundingClientRect();
      const c = parts[i].getBoundingClientRect();
      const left = i < 3;
      const ax = a.left + a.width / 2 - b.left;
      const ay = a.top + a.height / 2 - b.top;
      const bx = (left ? c.right : c.left) - b.left;
      const by = c.top + Math.min(c.height / 2, 60) - b.top;
      const mx = bx + (left ? 30 : -30);
      l.p.setAttribute('d', `M${bx.toFixed(1)} ${by.toFixed(1)}H${mx.toFixed(1)}L${ax.toFixed(1)} ${ay.toFixed(1)}`);
      l.d1.setAttribute('cx', bx.toFixed(1));
      l.d1.setAttribute('cy', by.toFixed(1));
    });
  };
  const track = (ms) => {
    const end = performance.now() + ms;
    if (tracking) { tracking = end; return; }
    tracking = end;
    const tick = () => {
      draw();
      if (performance.now() < tracking) requestAnimationFrame(tick); else tracking = 0;
    };
    requestAnimationFrame(tick);
  };

  const render = () => {
    root.dataset.view = view;
    const iso = view !== 'all';
    slabs.forEach((s, i) => {
      const hit = sel.includes(i + 1);
      s.classList.toggle('dim', iso && !hit);
      s.classList.toggle('sel', iso && hit);
      s.classList.toggle('on', !iso && step === i + 1);
      parts[i].classList.toggle('dim', iso && !hit);
      parts[i].classList.toggle('sel', iso && hit);
      parts[i].classList.toggle('on', !iso && step === i + 1);
      leads[i].p.classList.toggle('dim', iso && !hit);
      leads[i].d1.classList.toggle('dim', iso && !hit);
      leads[i].p.classList.toggle('on', (iso && hit) || (!iso && step === i + 1));
    });
    views.forEach((v) => v.setAttribute('aria-pressed', String(v.dataset.view === view)));
    bead.setAttribute('class', `anat-bead st${step}`);
    cap.textContent = iso ? sel.map((n) => parts[n - 1].querySelector('h3').textContent).join(' and ') : captions[step];
  };
  const setOpen = (on) => {
    root.dataset.open = on ? '1' : '0';
    openBtn.setAttribute('aria-pressed', String(on));
    openBtn.textContent = on ? 'Assemble' : 'Explode';
    track(1300);
  };
  const stop = () => { timers.forEach(clearTimeout); timers = []; };
  const later = (fn, ms) => { timers.push(setTimeout(fn, ms)); };
  const show = (n) => { step = n; render(); };
  const choose = (name) => { stop(); view = name; sel = presets[name]; if (name !== 'all') setOpen(true); render(); track(1300); };
  const pickLayer = (n) => {
    stop();
    if (view === 'one' && sel.length === 1 && sel[0] === n) { choose('all'); return; }
    view = 'one'; sel = [n]; setOpen(true); render();
  };

  const play = () => {
    stop();
    view = 'all'; sel = presets.all;
    setOpen(false); show(0);
    later(() => setOpen(true), 1200);
    for (let n = 1; n <= 6; n += 1) later(() => show(n), 2400 + (n - 1) * 3600);
    later(() => { cap.textContent = captions[7]; }, 2400 + 6 * 3600);
  };

  // values from the recorded run
  const fill = (d) => {
    const set = (k, v) => root.querySelectorAll(`[data-v="${k}"]`).forEach((e) => { e.textContent = v; });
    set('limit', `USD ${d.limit_alone}`);
    set('ceiling', `USD ${d.ceiling}`);
    set('ask', `USD ${d.ask}`);
    set('order', d.order);
    set('offer', `USD ${d.offer}`);
    set('draft', `${(d.model_ms / 1000).toFixed(1)} s`);
    set('proposed', d.proposed);
    set('decided', d.decided);
    set('overridden', d.overridden ? 'yes' : 'no');
    set('hash', String(d.policy_hash).slice(0, 12));
    set('line', `line ${d.merchant.offer_line}`);
    set('status', `${d.status} at ${d.stage}`);
    set('refund', `USD ${d.refund}`);
    set('fee', `USD ${d.fee}`);
    track(100);
  };

  slabs.forEach((s, i) => {
    s.addEventListener('click', () => pickLayer(i + 1));
    s.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pickLayer(i + 1); } });
  });
  root.querySelectorAll('.anat-pick').forEach((b) => b.addEventListener('click', () => pickLayer(Number(b.dataset.layer))));
  views.forEach((v) => v.addEventListener('click', () => choose(v.dataset.view)));
  openBtn.addEventListener('click', () => { stop(); setOpen(root.dataset.open !== '1'); });
  root.querySelector('.anat-replay').addEventListener('click', play);

  if ('ResizeObserver' in window) new ResizeObserver(draw).observe(board);
  window.addEventListener('resize', draw);
  window.addEventListener('load', () => track(300));
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => track(300));

  fetch('data/hud-case.json').then((r) => r.json()).then(fill).catch(() => {});

  render();
  if (calm) { setOpen(true); show(6); cap.textContent = captions[7]; }
  else if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((e) => { if (e[0].isIntersecting && step === 0 && view === 'all') { play(); io.disconnect(); } }, { threshold: 0.3 });
    io.observe(root);
  } else { play(); }
  draw();
})();
