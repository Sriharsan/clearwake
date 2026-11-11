// Anatomy of one dispute: batch case 3 flows down six layers. Data: data/hud-case.json (recorded run).
(() => {
  const root = document.getElementById('anatomy');
  if (!root) return;
  const sheets = [...root.querySelectorAll('.anat-sheet')];
  const lines = [...root.querySelectorAll('.anat-lines li span')];
  const cap = root.querySelector('.anat-cap');
  const captions = [
    'One dispute. Six layers.',
    'The owner says the rule once. Clearwake reads it back and signs it.',
    'The buyer agent files the claim. It cannot pay itself.',
    "The merchant agent offers inside its owner's limit.",
    'The gate checks the action before any money moves.',
    'Every step is signed. Each receipt checks the one before it.',
    "PayPal's record is the judge. It matches. Paid once."];
  let step = 0;
  let timer = null;
  const fill = (d) => {
    const t = (i, s) => { if (lines[i]) lines[i].textContent = s; };
    t(0, `Rule signed. Limit USD ${d.limit_alone} alone, ceiling USD ${d.ceiling}.`);
    t(1, `Claim filed for order ${d.order}: item not received, USD ${d.ask}.`);
    t(2, `Offer of USD ${d.offer} sent, inside the owner's limit of USD ${d.limit_alone}.`);
    t(3, `Model proposed ${d.proposed} (${d.model}). The gate allowed it. Overridden: ${d.overridden ? 'yes' : 'no'}.`);
    t(4, `Receipts signed on both sides. Policy hash ${String(d.policy_hash).slice(0, 12)}.`);
    t(5, `PayPal reads ${d.status} at ${d.stage}. Refund USD ${d.refund}. Fee USD ${d.fee}.`);
  };
  const show = (n) => {
    step = n;
    root.dataset.step = String(n);
    sheets.forEach((s, i) => s.classList.toggle('on', i === n - 1));
    lines.forEach((l, i) => l.parentElement.classList.toggle('on', i < n));
    cap.textContent = captions[n] || captions[0];
  };
  const play = () => {
    clearInterval(timer);
    show(0);
    let n = 0;
    timer = setInterval(() => { n += 1; show(n); if (n >= 6) clearInterval(timer); }, 3600);
  };
  const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  fetch('data/hud-case.json').then((r) => r.json()).then((d) => { fill(d); if (calm) show(6); }).catch(() => {});
  sheets.forEach((s, i) => {
    const pick = () => { clearInterval(timer); show(i + 1); };
    s.addEventListener('click', pick);
    s.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
  });
  root.querySelector('.anat-replay').addEventListener('click', play);
  if (calm) { show(6); }
  else if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((e) => { if (e[0].isIntersecting && step === 0) { play(); io.disconnect(); } }, { threshold: 0.35 });
    io.observe(root);
  } else { play(); }
})();
