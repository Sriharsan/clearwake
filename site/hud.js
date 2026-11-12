// THE CONVERSATION scene and the dispute id diagram on the Proof page; on the Home page it fills the seven steps from the same recorded case.
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
  if (!hud) {
    /* the Home page carries the seven steps as text: only the values are filled in, from the same recorded case */
    if ($('steps7')) load().then(fill).catch(function (err) { if (window.console) console.error('hud', err); });
    return;
  }

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
            dispute: c.dispute, order: c.order, paid: usd(c.paid), ask: usd(c.ask), offer: usd(c.offer), limit: usd(c.limit_alone), fee: usd(c.fee), feeLine: c.fee_line, refund: usd(c.refund),
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
    if ($('gb-fill')) { $('gb-fill').setAttribute('width', String(300 * D.ratio)); $('gb-mark').setAttribute('d', 'M299 0v16'); }
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

  /* ---------- the three characters: original semi realistic bust portraits, drawn here in SVG, no outside assets ---------- */
  function figure(kind) {
    var p = kind + '-', u = function (id) { return 'url(#' + p + id + ')'; };
    var F = 'M80 27C103 27 113 46 112.5 68C112 92 101 112 80 117C59 112 48 92 47.5 68C47 46 57 27 80 27Z';
    var T = 'M6 180C8 152 30 140 62 135L98 135C130 140 152 152 154 180Z';
    var core = {
      owner: '<g class="core"><circle class="cglow" cx="42" cy="158" r="8" filter="' + u('bg') + '"/><circle class="cring" cx="42" cy="158" r="5.6"/><circle class="cdia" cx="42" cy="158" r="2.6"/></g>',
      buyer: '<g class="core"><circle class="cglow" cx="80" cy="162" r="8" filter="' + u('bg') + '"/><path class="cring" d="M80 156.5l5.5 5.5-5.5 5.5-5.5-5.5z"/><circle class="cdia" cx="80" cy="162" r="2.4"/></g>',
      merch: '<g class="core"><circle class="cglow" cx="118" cy="160" r="8" filter="' + u('bg') + '"/><circle class="cring" cx="118" cy="160" r="5.6"/><circle class="cdia" cx="118" cy="160" r="2.6"/></g>'
    }[kind];
    var K = {
      owner: {
        back: '',
        torso: '<path class="shirt" d="M62 134L80 168L98 134L92 131L80 142L68 131Z"/><path class="lap" d="M60 135L80 170L50 180L26 162C36 148 48 139 60 135Z"/><path class="lap" d="M100 135L80 170L110 180L134 162C124 148 112 139 100 135Z"/><path class="lt" d="M60 135L80 170M100 135L80 170"/><path class="fold" d="M20 172Q30 160 34 180M140 172Q132 162 128 180M70 152Q64 166 62 180M104 160Q108 170 106 180"/><path class="fhi" d="M16 168Q22 152 38 146M118 150Q132 152 142 164"/>',
        shade: '<path d="M50 84C52 106 64 116 80 117C96 116 108 106 110 84C104 96 96 100 80 100C64 100 56 96 50 84Z" fill="' + u('hr') + '" opacity=".2" filter="' + u('bl') + '"/>',
        age: '<path class="wr" d="M62 38Q72 35 82 37M66 43Q76 41 90 42M60 82Q56 92 61 100M100 82Q104 92 99 100"/>',
        facial: '',
        hair: '<path d="M47 68C43 40 58 22 82 22C103 22 117 38 113 68C111 55 107 47 100 43C88 47 68 45 56 41C50 47 48 57 47 68Z" fill="' + u('hr') + '"/><path class="grey" d="M47 68C46 57 47 51 50 46L54 48C52 55 51 61 51 70ZM113 68C114 57 113 51 110 46L106 48C108 55 109 61 109 70Z"/><path class="strand" d="M58 38Q72 29 90 31M54 44Q70 34 96 38M64 36Q76 31 98 36M52 52Q55 44 62 40"/><path class="hrim" d="M100 28C111 36 114 52 113 68" filter="' + u('bg') + '"/>',
        brow: 2.6, bw: 'M53 58Q62 52 73 56M87 56Q98 52 107 58'
      },
      buyer: {
        back: '<path d="M44 62C32 100 36 150 28 176L132 176C124 150 128 100 116 62C112 32 98 20 80 20C62 20 48 32 44 62Z" fill="' + u('hr') + '"/><path class="strand" d="M40 100C38 130 36 154 34 172M50 90C46 124 44 150 42 172M120 100C122 130 124 154 126 172M110 90C114 124 116 150 118 172"/>',
        torso: '<path class="plate" d="M10 180C10 156 26 143 50 138L55 152C42 156 32 164 30 180Z"/><path class="plate" d="M150 180C150 156 134 143 110 138L105 152C118 156 128 164 130 180Z"/><path class="cos2" d="M60 136L80 152L100 136L108 180H52Z"/><path class="lt" d="M10 180C10 156 26 143 50 138M150 180C150 156 134 143 110 138M80 152V180M60 136L80 152L100 136M64 170H74M86 170H96"/><path class="cos2" d="M62 132L60 114L68 120L70 134ZM98 132L100 114L92 120L90 134Z"/><path class="lt" d="M60 114L62 132M100 114L98 132"/><path class="fhi" d="M16 166Q22 152 40 146M144 166Q138 152 120 146"/>',
        shade: '',
        age: '',
        facial: '',
        hair: '<path d="M46 76C41 44 56 22 82 22C107 22 119 44 114 76C112 58 106 46 95 39C84 47 63 49 53 59C49 63 47 69 46 76Z" fill="' + u('hr') + '"/><path class="strand" d="M56 40Q70 30 92 30M52 50Q66 38 96 38M60 34Q80 26 100 34M50 62Q52 52 60 46"/><path class="hrim" d="M102 28C113 38 116 58 114 76" filter="' + u('bg') + '"/><circle class="sig" cx="49.5" cy="72" r="2"/>',
        brow: 2, bw: 'M54 58Q62 53 73 56M87 56Q98 53 106 58'
      },
      merch: {
        back: '',
        torso: '<path class="cos2" d="M56 136L50 180H26C26 160 36 146 56 136ZM104 136L110 180H134C134 160 124 146 104 136Z"/><path class="coll" d="M56 134L60 108L72 124L72 140Z"/><path class="coll" d="M104 134L100 108L88 124L88 140Z"/><path class="lt" d="M80 142V180M60 108L56 134M100 108L104 134"/><circle class="btn" cx="84" cy="156" r="1.8"/><circle class="btn" cx="84" cy="168" r="1.8"/><path class="fold" d="M22 170Q32 160 34 180M138 172Q130 162 128 180"/><path class="fhi" d="M14 168Q22 152 38 146M120 148Q134 152 146 166"/>',
        shade: '',
        age: '<path class="wr" d="M60 36Q72 33 84 35M64 41Q76 39 92 40M56 66Q54 70 56 74M104 66Q106 70 104 74M62 84Q58 94 63 100M98 84Q102 94 97 100"/>',
        facial: '<path d="M49 80C50 106 62 118 80 119C98 118 110 106 111 80C107 92 100 97 92 98.5C86 96 74 96 68 98.5C60 97 53 92 49 80Z" fill="' + u('bd') + '"/><path class="strand2" d="M56 96C60 108 68 114 80 115M104 96C100 108 92 114 80 115M70 106Q80 111 90 106"/><path d="M68 98.5Q74 94 80 96.5Q86 94 92 98.5Q86 97 80 98.4Q74 97 68 98.5Z" fill="' + u('bd') + '"/>',
        hair: '<path d="M48 66C45 40 60 25 80 25C100 25 115 40 112 66C110 52 104 44 96 41C84 38 72 39 64 42C56 46 50 55 48 66Z" fill="' + u('hr') + '"/><path class="strand2" d="M58 38Q72 30 92 32M54 46Q70 36 98 40M62 34Q80 28 100 36"/><path class="hrim" d="M100 30C110 38 113 52 112 66" filter="' + u('bg') + '"/>',
        brow: 3.2, bw: 'M53 59Q62 54 73 57M87 57Q98 54 107 59'
      }
    }[kind];
    function eye(cx, s) {
      var x = function (d) { return (cx + s * d).toFixed(1); };
      var al = 'M' + (cx - 9) + ' 67Q' + cx + ' 59.5 ' + (cx + 9) + ' 67Q' + cx + ' 73 ' + (cx - 9) + ' 67Z';
      return '<g class="eyes"><g clip-path="url(#' + p + 'c' + cx + ')"><path d="' + al + '" fill="#eceff4"/><g class="pup"><circle cx="' + cx + '" cy="66.8" r="4.7" fill="' + u('ir') + '"/><circle cx="' + cx + '" cy="66.8" r="1.9" fill="#0b0b10"/><circle cx="' + (cx - 1.7) + '" cy="65.2" r="1.15" fill="#fff"/><circle cx="' + (cx + 1.5) + '" cy="68.2" r=".5" fill="#fff" opacity=".6"/></g>' +
        '<path d="M' + (cx - 9) + ' 67Q' + cx + ' 59.5 ' + (cx + 9) + ' 67L' + (cx + 9) + ' 61L' + (cx - 9) + ' 61Z" class="lidsh"/></g>' +
        '<path class="lid" d="M' + (cx - 9.6) + ' 67Q' + cx + ' 59 ' + (cx + 9.6) + ' 67"/><path class="lash" d="M' + x(9.4) + ' 66.6l' + (s * 2.6) + ' -1.6M' + x(8) + ' 64.8l' + (s * 2.2) + ' -2"/><path class="crease" d="M' + (cx - 7.5) + ' 63Q' + cx + ' 57 ' + (cx + 7.5) + ' 63"/><path class="crease" d="M' + (cx - 6) + ' 70.2Q' + cx + ' 73.6 ' + (cx + 6) + ' 70.2"/></g>';
    }
    var defs = '<defs>' +
      '<linearGradient id="' + p + 'sk" x1="0" y1="0" x2="1" y2=".3"><stop offset="0" class="s-hi"/><stop offset=".5" class="s-bs"/><stop offset="1" class="s-sh"/></linearGradient>' +
      '<linearGradient id="' + p + 'hr" x1="0" y1="0" x2="1" y2="1"><stop offset="0" class="h-hi"/><stop offset="1" class="h-lo"/></linearGradient>' +
      '<linearGradient id="' + p + 'bd" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="h-hi"/><stop offset="1" class="h-lo"/></linearGradient>' +
      '<linearGradient id="' + p + 'co" x1="0" y1="0" x2="1" y2="1"><stop offset="0" class="c-hi"/><stop offset="1" class="c-lo"/></linearGradient>' +
      '<radialGradient id="' + p + 'ir" cx=".5" cy=".5" r=".5"><stop offset="0" class="e-hi"/><stop offset=".7" class="e-hi"/><stop offset="1" class="e-lo"/></radialGradient>' +
      '<linearGradient id="' + p + 'fd" x1="0" y1="0" x2="0" y2="1"><stop offset=".6" stop-color="#fff"/><stop offset="1" stop-color="#4a4a4a"/></linearGradient>' +
      '<mask id="' + p + 'pm" maskUnits="userSpaceOnUse" x="0" y="0" width="160" height="180"><rect width="160" height="180" fill="' + u('fd') + '"/></mask>' +
      '<filter id="' + p + 'bl" filterUnits="userSpaceOnUse" x="-20" y="-20" width="200" height="220"><feGaussianBlur stdDeviation="3"/></filter>' +
      '<filter id="' + p + 'bs" filterUnits="userSpaceOnUse" x="-20" y="-20" width="200" height="220"><feGaussianBlur stdDeviation="1.1"/></filter>' +
      '<filter id="' + p + 'bg" filterUnits="userSpaceOnUse" x="-20" y="-20" width="200" height="220"><feGaussianBlur stdDeviation="2.2"/></filter>' +
      '<clipPath id="' + p + 'fc"><path d="' + F + '"/></clipPath><clipPath id="' + p + 'bc"><path d="' + T + '"/></clipPath>' +
      '<clipPath id="' + p + 'c64"><path d="M55 67Q64 59.5 73 67Q64 73 55 67Z"/></clipPath><clipPath id="' + p + 'c96"><path d="M87 67Q96 59.5 105 67Q96 73 87 67Z"/></clipPath>' +
      '<pattern id="' + p + 'sl" width="160" height="4" patternUnits="userSpaceOnUse"><rect width="160" height="1" class="scn"/></pattern></defs>';
    var body = '<g class="body" mask="' + u('pm') + '"><path d="' + T + '" fill="' + u('co') + '"/>' +
      '<path d="M66 100L66 128C66 138 94 138 94 128L94 100Z" fill="' + u('sk') + '"/><ellipse cx="80" cy="112" rx="16" ry="8" class="shd" opacity=".55" filter="' + u('bl') + '"/>' +
      '<path class="tr" d="M70 116L70 126L74 130M90 116L90 126L86 130M80 118L80 132"/><circle class="trn" cx="74" cy="130" r="1.1"/><circle class="trn" cx="86" cy="130" r="1.1"/><circle class="trn" cx="80" cy="132" r="1.1"/>' +
      K.torso + core + '<g clip-path="' + u('bc') + '"><rect class="scan" x="0" y="-8" width="160" height="200" fill="' + u('sl') + '"/></g>' +
      '<path class="rim" d="M6 180C8 152 30 140 62 135" filter="' + u('bg') + '"/><path class="rim" d="M154 180C152 152 130 140 98 135" filter="' + u('bg') + '"/></g>';
    var card = '<g class="card"><rect x="44" y="136" width="72" height="38" rx="4"/><path d="M52 146h40M52 154h28M52 162h34"/><circle class="cd" cx="104" cy="148" r="3"/>' +
      '<g class="hands"><ellipse class="hand" cx="45" cy="172" rx="7.5" ry="6"/><ellipse class="hand" cx="48" cy="164" rx="3" ry="5.5"/><ellipse class="hand" cx="53" cy="163" rx="2.6" ry="5.2"/><ellipse class="hand" cx="115" cy="172" rx="7.5" ry="6"/><ellipse class="hand" cx="112" cy="164" rx="3" ry="5.5"/><ellipse class="hand" cx="107" cy="163" rx="2.6" ry="5.2"/></g></g>';
    var head = '<g class="headg"><g class="head">' +
      '<ellipse cx="47" cy="73" rx="5" ry="9" fill="' + u('sk') + '"/><ellipse cx="113" cy="73" rx="5" ry="9" fill="' + u('sk') + '"/><ellipse cx="47.5" cy="74" rx="2.6" ry="5.6" class="wm" opacity=".6" filter="' + u('bs') + '"/><ellipse cx="112.5" cy="74" rx="2.6" ry="5.6" class="wm" opacity=".6" filter="' + u('bs') + '"/>' +
      '<path d="' + F + '" fill="' + u('sk') + '"/>' +
      '<g clip-path="' + u('fc') + '"><ellipse cx="113" cy="82" rx="14" ry="38" class="shd" opacity=".4" filter="' + u('bl') + '"/><ellipse cx="80" cy="122" rx="32" ry="10" class="shd" opacity=".5" filter="' + u('bl') + '"/>' +
      '<ellipse cx="58" cy="90" rx="9" ry="7" class="wm" opacity=".42" filter="' + u('bl') + '"/><ellipse cx="102" cy="90" rx="9" ry="7" class="wm" opacity=".36" filter="' + u('bl') + '"/><ellipse cx="51" cy="72" rx="5" ry="11" class="wm" opacity=".4" filter="' + u('bl') + '"/>' +
      '<ellipse cx="71" cy="40" rx="12" ry="4.6" fill="#fff" opacity=".3" filter="' + u('bs') + '"/><ellipse cx="63" cy="80" rx="6" ry="3" fill="#fff" opacity=".16" filter="' + u('bs') + '"/>' +
      K.shade + K.age + '<path class="tr" d="M53 58L53 66L49 71L49 84L53 89M107 58L107 66L111 71L111 84L107 89"/><circle class="trn" cx="53" cy="89" r="1.1"/><circle class="trn" cx="107" cy="89" r="1.1"/><circle class="trn" cx="53" cy="58" r="1.1"/><circle class="trn" cx="107" cy="58" r="1.1"/>' +
      '<rect class="scan" x="0" y="-8" width="160" height="200" fill="' + u('sl') + '"/></g>' +
      '<g class="feat">' + eye(64, -1) + eye(96, 1) +
      '<path class="brow" stroke-width="' + K.brow + '" d="' + K.bw + '"/>' +
      '<path class="nshade" d="M83 66Q86 78 86.5 85M75 86Q73 90 77 90.5M85 86Q87 90 83 90.5"/><path class="nhi" d="M79 68L78 83" filter="' + u('bs') + '"/><ellipse cx="80" cy="86.5" rx="2.4" ry="1.6" fill="#fff" opacity=".35" filter="' + u('bs') + '"/><ellipse cx="77" cy="89" rx="1.6" ry=".9" class="nostril"/><ellipse cx="83" cy="89" rx="1.6" ry=".9" class="nostril"/><ellipse cx="80" cy="92" rx="5" ry="1.5" class="shd" opacity=".4" filter="' + u('bs') + '"/>' +
      K.facial +
      '<path class="lipu" d="M68 100.4Q74 96.8 80 98.8Q86 96.8 92 100.4Q80 103 68 100.4Z"/><path class="lipl" d="M69 100.8Q80 103.4 91 100.8Q88 108.6 80 109Q72 108.6 69 100.8Z"/><ellipse cx="80" cy="105.4" rx="5" ry="1.3" fill="#fff" opacity=".32" filter="' + u('bs') + '"/>' +
      '<path class="m-rest" d="M69.5 100.8Q80 103.4 90.5 100.8"/><path class="m-glad" d="M67.5 99.6Q80 106.8 92.5 99.6"/><ellipse class="m-open" cx="80" cy="102.6" rx="6" ry="3.4"/></g>' +
      K.hair + '<path class="rim" d="' + F + '" filter="' + u('bg') + '"/>' +
      '<g class="vl"><path d="M122 60q7 8 0 16M128 53q11 14 0 30M134 46q15 20 0 44"/></g></g></g>';
    return '<svg viewBox="0 0 160 180" focusable="false" aria-hidden="true">' + defs +
      '<g class="headg"><g class="head">' + K.back + '</g></g>' + body + card + head + '</svg>';
  }
  var FIG = {};
  /* portraits: three frames per person (idle, blink, talk), layered; CSS drives breathing, blink and the talking swap */
  var PORTRAIT = { owner: 'owner', buyer: 'buyer', merch: 'merchant' };
  function portrait(kind) {
    var base = 'img/characters/' + PORTRAIT[kind] + '-';
    return ['idle', 'blink', 'talk'].map(function (f) {
      return '<img class="fi fi-' + f + '" src="' + base + f + '.webp" width="560" height="700" alt="" decoding="async">';
    }).join('');
  }
  ['owner', 'buyer', 'merch'].forEach(function (n) { var h = $('fg-' + n); if (h) { h.innerHTML = portrait(n); FIG[n] = h; } });
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
      function () { cap('PayPal’s record reads ' + D.status + ' at ' + D.stage + '. Before any claim.'); active('merch'); st('merch-st', 'resolved'); on('m4'); core.classList.add('done', 'flash'); lookAt('merch', true); st('rc-state', D.status); return sleep(1600); },
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
