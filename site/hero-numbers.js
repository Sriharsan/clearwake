// Home hero: two lead numbers, read from data/totals.json (built by scripts/build_site_data.py from the run files).
// Nothing here is typed by hand: the value, baseline, episode count, tag and source all come from the file. No file, no numbers.
(function () {
  'use strict';
  var host = document.getElementById('hero-numbers');
  if (!host || !window.fetch) return;
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; e.textContent = text; return e; }
  function tile(tag, big, vs, label, src) {
    var d = document.createElement('div');
    d.append(el('dd', 'tag', tag), el('dd', 'num tnum', big));
    if (vs) d.append(el('dd', 'vs tnum', vs));
    d.append(el('dt', '', label), el('dd', 'src', src));
    return d;
  }
  function cap(s) { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); }
  fetch('data/totals.json', { credentials: 'omit' }).then(function (r) { if (!r.ok) throw new Error('no totals'); return r.json(); }).then(function (t) {
    var list = (t && t.public) || [], base = null, settled = null;
    list.forEach(function (n) {
      if (!base && /^USD /.test(String(n.value))) base = n;
      if (!settled && /settled at INQUIRY/.test(String(n.label))) settled = n;
    });
    if (!base && !settled) return;
    host.textContent = '';
    if (base) {
      var z = /(USD [\d.,]+) by Clearwake/.exec(base.label), ep = /in (\d+) episodes/.exec(base.label);
      if (z) host.append(tile(cap(base.mode), String(base.value), 'vs ' + z[1], 'overpaid by an agent on the PayPal Agent Toolkit alone' + (ep ? ', ' + ep[1] + ' episodes, baseline' : ''), String(base.source)));
    }
    if (settled) host.append(tile(cap(settled.mode), String(settled.value), '', String(settled.label), String(settled.source)));
    host.hidden = !host.children.length;
  }).catch(function () { /* no numbers rather than invented ones */ });
})();
