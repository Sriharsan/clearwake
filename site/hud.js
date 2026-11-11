// THE CONVERSATION scene and the dispute id diagram on the Home page.
// Every value shown is read at load from data/hud-case.json and the two signed logs receipts/batch-merchant.ndjson and receipts/batch-buyer.ndjson
// (batch case 3, real PayPal sandbox, written by scripts/build_site_data.py from the newest clean batch run).
// Nothing numeric is typed in this file. No inline styles: states are class names, shapes move through CSS transforms.
(function () {
  'use strict';
  var doc = document;
  var $ = function (id) { return doc.getElementById(id); };
  var reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var CANCEL = { cancel: true };
  var hud = $('hud');
  if (!hud) return;

  /* ---------- data ---------- */
  function sha256(text) {
    if (!(window.crypto && crypto.subtle)) return Promise.resolve('');
    return crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)).then(function (buf) {
      return Array.prototype.map.call(new Uint8Array(buf), function (b) { return b.toString(16).padStart(2, '0'); }).join('');
    });
  }
  function load() {
    return fetch('data/hud-case.json', { credentials: 'omit' }).then(function (r) { return r.json(); }).then(function (c) {
      return Promise.all([
        fetch(c.merchant.file, { credentials: 'omit' }).then(function (r) { return r.text(); }),
        fetch(c.buyer.file, { credentials: 'omit' }).then(function (r) { return r.text(); })
      ]).then(function (got) {
        var m = got[0].replace(/\n$/, '').split('\n'), b = got[1].replace(/\n$/, '').split('\n');
        var lOffer = m[c.merchant.offer_line - 1], lClosed = b[c.buyer.closed_line - 1];
        if (!lOffer || !lClosed || JSON.parse(lOffer).params.dispute !== c.dispute || JSON.parse(lClosed).params.dispute_id !== c.dispute) throw new Error('case not found');
        return Promise.all([sha256(lOffer), sha256(lClosed)]).then(function (h) {
          var usd = function (v) { return 'USD ' + Number(v).toFixed(2); };
          var pick = function (hash, line) { return hash ? 'sha256 ' + hash.slice(0, 16) + '…' : 'sig ' + JSON.parse(line).signature.slice(0, 16) + '…'; };
          return {
            dispute: c.dispute, order: c.order, paid: usd(c.paid), ask: usd(c.ask), offer: usd(c.offer), limit: usd(c.limit_alone), fee: usd(c.fee), refund: usd(c.refund),
            status: c.status, stage: c.stage, outcome: c.outcome, proposed: c.proposed, model: c.model + ', ' + (c.model_ms / 1000).toFixed(1) + ' s',
            message: c.buyer_message, ruleBuyer: c.rule_buyer, ruleMerch: c.rule_merchant,
            policy8: c.policy_hash.slice(0, 8) + '…', h3: pick(h[0], lOffer), h5: pick(h[1], lClosed),
            ratio: Math.min(1, Number(c.offer) / Number(c.limit_alone)), id1: c.dispute.slice(0, 8), id2: c.dispute.slice(9)
          };
        });
      });
    });
  }
  function fill(D) {
    Array.prototype.forEach.call(doc.querySelectorAll('[data-f]'), function (n) { if (D[n.getAttribute('data-f')] != null) n.textContent = D[n.getAttribute('data-f')]; });
    $('gb-fill').setAttribute('width', String(300 * D.ratio));
    $('gb-mark').setAttribute('d', 'M299 0v16');
  }

  /* ---------- a clock that can pause ---------- */
  var paused = false, waits = [];
  function sleep(ms) {
    return new Promise(function (res, rej) {
      var w = { rem: ms, res: res, rej: rej, id: 0, t0: 0 }; waits.push(w); arm(w);
    });
  }
  function arm(w) {
    if (paused) return;
    w.t0 = performance.now();
    w.id = setTimeout(function () { waits.splice(waits.indexOf(w), 1); w.res(); }, Math.max(0, w.rem));
  }
  function stopClock() { paused = true; waits.forEach(function (w) { clearTimeout(w.id); w.rem -= performance.now() - w.t0; }); }
  function startClock() { paused = false; waits.forEach(arm); }
  function cancelAll() { var all = waits.slice(); waits = []; all.forEach(function (w) { clearTimeout(w.id); w.rej(CANCEL); }); }

  /* ---------- the dispute id diagram ---------- */
  function setLines(pairs, upTo) {
    pairs.forEach(function (p) { $(p[0]).textContent = p[1].slice(0, upTo === undefined ? p[1].length : Math.max(0, Math.min(p[1].length, upTo - (p[2] || 0)))); });
  }
  function vennInit(D) {
    var v = $('venn'); if (!v) return;
    var pairs = [['vid-h1', D.id1, 0], ['vid-h2', D.id2, D.id1.length], ['vid-v1', D.id1, 0], ['vid-v2', D.id2, D.id1.length]];
    setLines(pairs);
    if (reduced || !('IntersectionObserver' in window)) return;
    v.classList.add('arming'); setLines(pairs, 0);
    var io = new IntersectionObserver(function (es) {
      if (!es[0].isIntersecting) return; io.disconnect();
      var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
      v.classList.add('s1');
      wait(1500).then(function () { v.classList.add('s2'); return wait(800); }).then(function () {
        var n = D.id1.length + D.id2.length, i = 0;
        return new Promise(function (done) {
          var t = setInterval(function () { i++; setLines(pairs, i); if (i >= n) { clearInterval(t); done(); } }, 75);
        });
      }).then(function () { return wait(350); }).then(function () { $('vchip-a').classList.add('on'); return wait(550); })
        .then(function () { $('vchip-b').classList.add('on'); });
    }, { threshold: 0.55 });
    io.observe(v);
  }

  /* ---------- the scene ---------- */
  var capEl = $('hud-cap'), playBtn = $('hud-play'), playTxt = $('hud-play-t'), replayBtn = $('hud-replay');
  var state = 'idle', run = 0, userPaused = false, autoPaused = false, D = null;
  var wave = $('wave'), core = $('core'), ring = doc.querySelector('.ring-wrap');
  var IDS = ['rr-buyer', 'rr-merch', 'b1', 'b2', 'b3', 'b4', 't1', 't2', 't3', 'm1', 'm2', 'm3', 'm4', 'chip3', 'chip5'];

  /* ---------- the three characters: original vector figures, drawn here, no outside assets ---------- */
  function figure(kind) {
    var K = {
      owner: {
        back: '',
        torso: '<path class="cos" d="M12 140C12 108 34 98 60 98s48 10 48 42z"/><path class="cos2" d="M44 100L60 130 38 140 26 112z"/><path class="cos2" d="M76 100L60 130 82 140 94 112z"/><path class="shirt" d="M50 99L60 126 70 99z"/><path class="tie" d="M57 104h6l2 5-5 17-5-17z"/><path class="lap" d="M44 100L56 118 52 99zM76 100L64 118 68 99z"/><g class="core"><path class="cglow" d="M80 119l6 6-6 6-6-6z"/><path class="cdia" d="M80 121.5l3.5 3.5-3.5 3.5-3.5-3.5z"/></g>',
        hair: '<path class="hair" d="M38 56C34 30 50 20 62 20c14 0 22 12 20 36-2-8-5-14-9-16-8 4-22 5-30 2-3 3-4 9-5 14z"/><path class="grey" d="M38.5 56c0-5 1-9 3-12l2 2c-2 4-3 8-3 12zM81.5 56c0-5-1-9-3-12l-2 2c2 4 3 8 3 12z"/>',
        brow: 'M45 48q5-3 10-1M65 47q5-2 10 1', extra: ''
      },
      buyer: {
        back: '<path class="hair" d="M36 52C28 88 30 104 44 104h32c14 0 16-16 8-52z"/>',
        torso: '<path class="cos" d="M12 140C12 108 34 98 60 98s48 10 48 42z"/><path class="cos2" d="M46 99L60 112 74 99 70 88H50z"/><path class="plate" d="M40 114L60 124 80 114 80 132 60 140 40 132z"/><path class="edge" d="M60 112v28M40 114L60 124 80 114"/><ellipse class="plate" cx="19" cy="110" rx="12" ry="9" transform="rotate(-25 19 110)"/><ellipse class="plate" cx="101" cy="110" rx="12" ry="9" transform="rotate(25 101 110)"/><path class="lt" d="M10 112q8-10 17-6M110 112q-8-10-17-6"/><path class="lt" d="M46 120h10M64 120h10"/>',
        hair: '<path class="hair" d="M37 58C32 30 52 18 64 21c14 3 20 16 18 38-2-10-8-18-18-20-10 0-20 6-27 19z"/><circle class="sig sg" cx="39" cy="61" r="2.6"/>',
        brow: 'M45 49q5-3 10-1M65 48q5-2 10 1', extra: ''
      },
      merch: {
        back: '<circle class="hair" cx="60" cy="14" r="9"/>',
        torso: '<path class="cos" d="M12 140C12 108 34 98 60 98s48 10 48 42z"/><path class="cos2" d="M44 100L56 138H38L30 112zM76 100l12 38H64z"/><path class="coll" d="M46 97L50 82h20l4 15-14 10z"/><path class="lt" d="M60 107l0 33"/><circle class="btn" cx="68" cy="116" r="1.8"/><circle class="btn" cx="68" cy="126" r="1.8"/><g class="core"><circle class="cglow" cx="46" cy="122" r="7"/><circle class="cdia" cx="46" cy="122" r="4.2"/></g>',
        hair: '<path class="hair" d="M38 56C34 30 50 18 62 19c14 0 22 12 20 37-3-9-6-14-10-16-9 4-23 5-31 2-3 4-3 9-3 14z"/><circle class="sig sg" cx="81" cy="62" r="2.6"/>',
        brow: 'M45 48q5-2 10 0M65 48q5-2 10 0', extra: ''
      }
    }[kind];
    return '<svg viewBox="0 0 120 132" focusable="false" aria-hidden="true">' + K.back +
      '<g class="body"><path class="neck" d="M52 78h16v26H52z"/>' + K.torso +
      '<path class="slv" d="M20 106L24 138"/><path class="slv" d="M100 106L96 138"/>' +
      '<g class="card"><rect x="42" y="102" width="36" height="28" rx="3"/><path d="M48 111h24M48 117h16M48 123h20"/></g>' +
      '<g class="fa fa-l"><path class="slv" d="M24 138L45 152.7"/><circle class="hand" cx="45" cy="152.7" r="5.5"/></g>' +
      '<g class="fa fa-r"><path class="slv" d="M96 138L75 152.7"/><circle class="hand" cx="75" cy="152.7" r="5.5"/></g></g>' +
      '<g class="headg"><g class="head"><ellipse class="skin" cx="40" cy="60" rx="3.5" ry="5.5"/><ellipse class="skin" cx="80" cy="60" rx="3.5" ry="5.5"/><ellipse class="skin" cx="60" cy="58" rx="20" ry="25"/>' +
      '<g class="feat"><g class="eyes"><ellipse class="sclera" cx="51" cy="57" rx="5" ry="3.6"/><ellipse class="sclera" cx="69" cy="57" rx="5" ry="3.6"/><g class="pup"><circle class="iris" cx="51" cy="57" r="2.4"/><circle class="iris" cx="69" cy="57" r="2.4"/></g></g>' +
      '<path class="brow" d="' + K.brow + '"/><path class="nose" d="M60 59q-3 8 0 9h2"/>' +
      '<path class="m-rest" d="M53 73q7 4 14 0"/><path class="m-glad" d="M52 72q8 8 16 0"/><ellipse class="m-open" cx="60" cy="73" rx="5" ry="3.2"/></g>' + K.hair + '</g>' +
      '<g class="vl"><path d="M88 52q6 6 0 12M93 48q9 10 0 20M98 44q12 14 0 28"/></g></g></svg>';
  }
  var FIG = {};
  ['owner', 'buyer', 'merch'].forEach(function (n) { var h = $('fg-' + n); if (h) { h.innerHTML = figure(n); FIG[n] = h; } });
  /* who looks where: the speaker faces front, the others turn toward the speaker */
  function lookAt(sp, glad) {
    ['owner', 'buyer', 'merch'].forEach(function (n) {
      var f = FIG[n]; if (!f) return;
      var d = n === sp ? 'c' : (n === 'merch' ? 'l' : (sp === 'merch' ? 'r' : (n === 'owner' ? 'd' : 'u')));
      f.className = f.className.replace(/\s*\b(look-\w|speaking|hold|gest)\b/g, '') + ' look-' + d +
        (n === sp ? ' speaking' : '') + (n === sp && n !== 'owner' ? ' hold' : '') + (n === sp && n === 'owner' ? ' gest' : '') + (glad ? ' glad' : '');
    });
  }
  for (var k = 0; k < 30; k++) wave.appendChild(doc.createElement('i'));

  function on() { for (var i = 0; i < arguments.length; i++) $(arguments[i]).classList.add('on'); }
  function active(name) { ['owner', 'buyer', 'merch'].forEach(function (n) { $('pn-' + n).classList.toggle('active', n === name); }); lookAt(name); }
  function cap(text, final) {
    capEl.textContent = text; capEl.classList.toggle('final', !!final);
    capEl.classList.remove('in'); void capEl.offsetWidth; capEl.classList.add('in');
  }
  function st(id, text) { $(id).textContent = text; }
  function type(el, text, cps) {
    el.classList.add('typing'); el.textContent = '';
    var i = 0;
    return (function next() {
      if (i >= text.length) { el.classList.remove('typing'); return Promise.resolve(); }
      i++; el.textContent = text.slice(0, i);
      return sleep(1000 / cps).then(next);
    })();
  }
  function setState(s) {
    state = s;
    hud.classList.toggle('playing', s === 'playing');
    playTxt.textContent = s === 'playing' ? 'Pause' : (s === 'paused' ? 'Resume' : (s === 'done' ? 'Play again' : 'Play'));
    playBtn.setAttribute('aria-label', s === 'playing' ? 'Pause the scene' : (s === 'paused' ? 'Resume the scene' : 'Play the scene'));
  }
  function reset() {
    IDS.forEach(function (id) { $(id).classList.remove('on', 'signing', 'locked'); });
    ['pn-owner', 'pn-buyer', 'pn-merch'].forEach(function (id) { $(id).classList.remove('active'); }); lookAt('owner');
    core.classList.remove('armed', 'done', 'flash'); ring.classList.remove('bus');
    wave.classList.remove('talk');
    ['say-buyer', 'say-merch', 'rc-id1', 'rc-id2', 'rc-state'].forEach(function (id) { $(id).textContent = ''; $(id).classList && $(id).classList.remove('typing'); });
    st('owner-st', 'standing by'); st('buyer-st', 'watching'); st('merch-st', 'waiting');
    capEl.classList.remove('final');
  }

  function play(token) {
    var buyerRule = D.ruleBuyer, merchRule = D.ruleMerch;
    var chain = function (steps) {
      return steps.reduce(function (p, f) { return p.then(function () { if (token !== run) throw CANCEL; return f(); }); }, Promise.resolve());
    };
    var talk = function (ms) { wave.classList.add('talk'); return sleep(ms).then(function () { wave.classList.remove('talk'); }); };
    return chain([
      function () { reset(); setState('playing'); cap('You say your rules once, out loud.'); active('owner'); st('owner-st', 'speaking'); on('rr-buyer'); return sleep(500); },
      function () { return talk(1200); },
      function () { return type($('say-buyer'), buyerRule, 46); },
      function () { $('rr-buyer').classList.add('signing'); return sleep(900); },
      function () { $('rr-buyer').classList.replace('signing', 'locked'); return sleep(700); },
      function () { on('rr-merch'); return talk(1200); },
      function () { return type($('say-merch'), merchRule, 52); },
      function () { $('rr-merch').classList.add('signing'); return sleep(900); },
      function () { $('rr-merch').classList.replace('signing', 'locked'); core.classList.add('armed'); st('rc-state', 'RULES SIGNED'); return sleep(1100); },
      function () { st('owner-st', 'standing by'); cap('The buyer agent finds an order with no tracking.'); active('buyer'); on('b1'); return sleep(2000); },
      function () { cap('It opens the dispute, inside its rule.'); on('b2'); st('buyer-st', 'dispute open'); ring.classList.add('bus'); st('rc-state', 'DISPUTE OPEN'); return type($('rc-id1'), D.id1, 24); },
      function () { return type($('rc-id2'), D.id2, 24); },
      function () { on('b3'); return sleep(1600); },
      function () { cap('The merchant agent asks its model.'); active('merch'); st('merch-st', 'reading'); on('t1'); return sleep(1300); },
      function () { cap('A proposal comes in. The rule decides.'); st('merch-st', 'proposing'); on('m1', 't2'); return sleep(1900); },
      function () { on('m2'); st('rc-state', 'OFFER ' + D.offer.replace('USD ', '')); return sleep(2000); },
      function () { st('merch-st', 'inside the limit'); cap('One offer, sent alone.'); on('t3', 'm3'); return sleep(1700); },
      function () { cap('PayPal’s record reads ' + D.status + ' at ' + D.stage + '. No fee.'); active('merch'); st('merch-st', 'resolved'); on('m4'); core.classList.add('done', 'flash'); lookAt('merch', true); st('rc-state', D.status); return sleep(1600); },
      function () { active('buyer'); st('buyer-st', 'resolved'); cap('The buyer agent reads the same record.'); on('b4'); return sleep(1700); },
      function () { cap('Two signed receipts, one dispute id.'); on('chip3'); return sleep(650); },
      function () { on('chip5'); return sleep(1700); },
      function () { active('merch'); lookAt('owner', true); st('owner-st', 'not interrupted'); cap('Done. You were not asked.', true); setState('done'); return Promise.resolve(); }
    ]);
  }
  function start() {
    run++; cancelAll(); userPaused = false; autoPaused = false; startClock();
    var token = run;
    play(token).catch(function (e) { if (e !== CANCEL) { throw e; } });
  }
  function staticScene() {
    hud.classList.remove('live', 'playing');
    $('hud-play').parentNode.hidden = true;
    $('say-buyer').textContent = D.ruleBuyer; $('say-merch').textContent = D.ruleMerch;
    st('rc-state', D.status); $('rc-id1').textContent = D.id1; $('rc-id2').textContent = D.id2;
    capEl.textContent = 'Done. You were not asked.'; capEl.classList.add('final');
    st('owner-st', 'not interrupted');
    var sw = $('story-wrap'); if (sw) sw.setAttribute('open', '');
    core.classList.add('done', 'armed');
  }

  load().then(function (data) {
    D = data; fill(D); vennInit(D);
    if (reduced || !('IntersectionObserver' in window)) { staticScene(); return; }
    hud.classList.add('live'); reset(); setState('idle');
    active('owner'); cap('Press Play, or scroll and it starts.');
    playBtn.addEventListener('click', function () {
      if (state === 'idle' || state === 'done') start();
      else if (state === 'playing') { userPaused = true; stopClock(); hud.classList.add('paused'); setState('paused'); }
      else if (state === 'paused') { userPaused = false; startClock(); hud.classList.remove('paused'); setState('playing'); }
    });
    replayBtn.addEventListener('click', function () { hud.classList.remove('paused'); start(); });
    var started = false;
    new IntersectionObserver(function (es) {
      var e = es[0];
      if (e.isIntersecting && !started && e.intersectionRatio >= 0.3) { started = true; start(); return; }
      if (!started) return;
      if (!e.isIntersecting && state === 'playing') { autoPaused = true; stopClock(); hud.classList.add('paused'); setState('paused'); }
      else if (e.isIntersecting && autoPaused && !userPaused && state === 'paused') { autoPaused = false; startClock(); hud.classList.remove('paused'); setState('playing'); }
    }, { threshold: [0, 0.3] }).observe(hud);
  }).catch(function (err) {
    if (window.console) console.error('hud', err);
    $('hud-play').parentNode.hidden = true;
    capEl.textContent = 'The recorded case could not be loaded.';
  });

  /* the loop strip lights up in order as it scrolls into view */
  var chain = doc.querySelector('.chain');
  if (chain && !reduced && 'IntersectionObserver' in window) {
    chain.classList.add('arm');
    var cio = new IntersectionObserver(function (es) { if (es[0].isIntersecting) { chain.classList.add('go'); cio.disconnect(); } }, { threshold: 0.3 });
    cio.observe(chain);
  }
})();
