// Home page data. Every figure here is read at load from a data file built from the run files; nothing numeric is typed in this file.
//  - the local run baseline beside the real sandbox result: data/totals.json
//  - the merchant's proof counts: data/batch-sandbox-20261111-132948.json (the recorded batch rows), or data/room.json when it carries a "merchant_proof" list
//  - the Why now line: shown only when data/why-now.json exists and holds facts
//  - the video button: its link is the value of data-video, so a placeholder file edit fills it
(function () {
  'use strict';
  var doc = document;
  function $(id) { return doc.getElementById(id); }
  function get(url) { return fetch(url, { credentials: 'omit' }).then(function (r) { if (!r.ok) throw new Error(url); return r.json(); }); }
  function cap(s) { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); }

  var watch = $('watch-video');
  if (watch) watch.setAttribute('href', watch.getAttribute('data-video'));

  get('data/totals.json').then(function (t) {
    var base = ((t && t.public) || []).filter(function (n) { return /^USD /.test(String(n.value)); })[0];
    if (!base) return;
    if ($('res-base')) $('res-base').textContent = String(base.value);
    if ($('res-mode')) $('res-mode').textContent = cap(base.mode);
    if ($('res-src')) $('res-src').textContent = String(base.source);
  }).catch(function () { /* the static sentence stays */ });

  function tile(value, label) {
    var d = doc.createElement('div'), v = doc.createElement('dd'), l = doc.createElement('dt');
    v.className = 'num tnum'; v.textContent = String(value); l.textContent = label;
    d.append(v, l); return d;
  }
  get('data/batch-sandbox-20261111-132948.json').then(function (b) {
    var rows = (b && b.rows) || [];
    if (!rows.length) return;
    var settled = rows.filter(function (r) { return r.result === 'settled'; }).length;
    var waiting = rows.filter(function (r) { return /^escalated to merchant owner/.test(String(r.outcome)); }).length;
    var proof = rows.filter(function (r) { return r.result === 'open' && /^pending/.test(String(r.outcome)); }).length;
    var host = $('mp-nums');
    host.append(tile(proof, 'answered with proof'), tile(settled, 'settled with the refund'), tile(waiting, 'waiting for the owner'));
    host.hidden = false;
    var tag = doc.createElement('p'); tag.className = 'res-tag'; tag.textContent = 'Real PayPal sandbox run, ' + rows.length + ' cases';
    host.parentNode.insertBefore(tag, host);
  }).catch(function () { /* no counts rather than unsourced ones */ });

  get('data/why-now.json').then(function (w) {
    if (Array.isArray(w) && w.length && $('why-line')) $('why-line').hidden = false;
  }).catch(function () { /* no file, no line */ });
})();
