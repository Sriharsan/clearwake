// Home: the line of real totals under the hero. It starts as the three recorded sandbox results written in the page.
// When the data files in data/ hold more disputes than those three (the batch of ten), the line is rebuilt from the rows.
// Format of the rows: scripts/build_site_data.py. Nothing is sent anywhere.
(function () {
  'use strict';
  var line = document.getElementById('proof-line');
  if (!line || !window.fetch) return;
  function get(path) { return fetch(path, { credentials: 'omit' }).then(function (r) { if (!r.ok) throw new Error(path); return r.json(); }); }
  get('data/manifest.json').then(function (m) {
    var files = (m.files || []).filter(function (f) { return /^[A-Za-z0-9._-]+\.json$/.test(f) && f !== 'manifest.json'; });
    return Promise.all(files.map(function (f) { return get('data/' + f).then(function (d) { return Array.isArray(d) ? d : (d && d.rows) || []; }, function () { return []; }); }));
  }).then(function (lists) {
    var seen = {}, disputes = [].concat.apply([], lists).filter(function (r) {
      if (!r || typeof r.dispute !== 'string' || seen[r.dispute] || r.kind === 'refund') return false;
      seen[r.dispute] = true; return true;
    });
    if (disputes.length <= 3) return;   // the written line already says it
    var bucket = function (r) {
      if (['settled', 'evidence', 'escalated', 'open'].indexOf(r.result) >= 0) return r.result;
      var t = String(r.decided || '') + ' ' + String(r.dispatch || '');
      return r.settled_before_escalation === true ? 'settled' : /escalat/i.test(t) ? 'escalated' : /evidence|proof/i.test(t) ? 'evidence' : 'open';
    };
    var count = function (k) { return disputes.filter(function (r) { return bucket(r) === k; }).length; };
    var settled = count('settled'), evidence = count('evidence'), escalated = count('escalated'), other = count('open');
    var parts = [[disputes.length, 'disputes on the real sandbox']];
    if (settled) parts.push([settled, 'settled at INQUIRY, no fee']);
    if (evidence) parts.push([evidence, 'answered with evidence']);
    if (escalated) parts.push([escalated, 'escalated to the owner']);
    if (other > 0) parts.push([other, 'still open or held']);
    line.textContent = '';
    parts.forEach(function (p) {
      var li = document.createElement('li'), b = document.createElement('b');
      b.textContent = String(p[0]); li.append(b, ' ' + p[1]); line.append(li);
    });
  }).catch(function () { /* keep the written line */ });
})();
