// Proof page: the Why now block. It renders from data/why-now.json (an array of {claim, quote, source_name, source_url, date}) and stays hidden when the file is missing or empty.
// Text goes in as text. A link is made only for an https address.
(function () {
  'use strict';
  var doc = document, host = doc.getElementById('why-now'), list = doc.getElementById('why-list');
  if (!host || !list || !window.fetch) return;
  function el(tag, cls, text) { var e = doc.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }
  fetch('data/why-now.json', { credentials: 'omit' }).then(function (r) { if (!r.ok) throw new Error('no why-now'); return r.json(); }).then(function (items) {
    if (!Array.isArray(items) || !items.length) return;
    items.forEach(function (it) {
      if (!it || !it.claim) return;
      var li = el('li');
      li.append(el('h3', 'why-claim', String(it.claim)));
      if (it.quote) li.append(el('blockquote', 'why-quote', '“' + String(it.quote) + '”'));
      var src = el('p', 'why-src');
      if (it.source_url && /^https:\/\//.test(String(it.source_url))) {
        var a = el('a', '', String(it.source_name || it.source_url));
        a.href = String(it.source_url); a.rel = 'noopener'; src.append(a);
      } else if (it.source_name) src.append(doc.createTextNode(String(it.source_name)));
      if (it.date) src.append(el('span', 'why-date', ' ' + String(it.date)));
      li.append(src); list.append(li);
    });
    if (!list.children.length) return;
    host.hidden = false;
    var jump = doc.getElementById('jump-why'); if (jump) jump.hidden = false;
  }).catch(function () { /* no file, no block */ });
})();
