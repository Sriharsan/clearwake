// Home: the measured numbers, read from data/totals.json (built by scripts/build_site_data.py from the run files).
// Nothing here is typed by hand: when a new run file lands and the script runs again, the numbers change. No file, no numbers.
(function () {
  'use strict';
  var host = document.getElementById('lead-numbers');
  if (!host || !window.fetch) return;
  fetch('data/totals.json', { credentials: 'omit' }).then(function (r) { if (!r.ok) throw new Error('no totals'); return r.json(); }).then(function (t) {
    var list = (t && t.public) || [];
    if (!list.length) return;
    host.textContent = '';
    list.slice(0, 3).forEach(function (n) {
      var d = document.createElement('div'), v = document.createElement('dd'), l = document.createElement('dt'), s = document.createElement('dd');
      v.className = 'num tnum'; v.textContent = String(n.value); l.textContent = String(n.label);
      s.className = 'src'; s.textContent = (n.mode ? String(n.mode) + ' \u00b7 ' : '') + String(n.source || '');
      d.append(v, l, s); host.append(d);
    });
    host.hidden = false;
  }).catch(function () { /* no numbers rather than invented ones */ });
})();
