// Lead numbers for the Control Room and Break it: tiles in the style of the Home numbers section (totals.js).
// Nothing here is typed by hand. A host element names its data file (data-src) and the list inside it (data-key, default "public");
// the files are built by scripts/build_site_data.py from the run files. No file, no numbers.
(function (root) {
  'use strict';
  function tile(n) {
    var d = document.createElement('div'), v = document.createElement('dd'), l = document.createElement('dt'), s = document.createElement('dd');
    v.className = 'num tnum'; v.textContent = String(n.value); l.textContent = String(n.label);
    s.className = 'src'; s.textContent = (n.mode ? String(n.mode) + ' \u00b7 ' : '') + String(n.source || '');
    d.append(v, l, s);
    return d;
  }
  function render(host, list) {
    if (!host || !list || !list.length) return;
    var tail = host.querySelector('[data-tail]');
    list.forEach(function (n) { if (tail) host.insertBefore(tile(n), tail); else host.append(tile(n)); });
    host.hidden = false;
  }
  root.ClearwakeNumbers = { tile: tile, render: render };
  if (typeof document === 'undefined') return;
  function start() {
    if (!root.fetch) return;
    [].forEach.call(document.querySelectorAll('[data-numbers-src]'), function (host) {
      fetch(host.getAttribute('data-numbers-src'), { credentials: 'omit' }).then(function (r) { if (!r.ok) throw new Error('no numbers'); return r.json(); })
        .then(function (j) {
          var list = (j && j[host.getAttribute('data-numbers-key') || 'public']) || [], pick = host.getAttribute('data-numbers-pick');
          if (pick) list = pick.split(',').map(function (i) { return list[+i]; }).filter(Boolean);
          render(host, list);
        })
        .catch(function () { /* no numbers rather than invented ones */ });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})(typeof self !== 'undefined' ? self : this);
