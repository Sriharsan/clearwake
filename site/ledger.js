// Control Room ledger: AG Grid Community over recorded real sandbox rows read from data/*.json.
// Drop another file in site/data/ (format in scripts/build_site_data.py) and list it in data/manifest.json: its rows appear here.
// Nothing is sent anywhere. The CSV is built in this browser from the rows on screen.
(function () {
  'use strict';
  var L = window.ClearwakeConsole;
  var $ = function (id) { return document.getElementById(id); };
  var host = $('ledger-grid');
  if (!host || !L) return;

  var rows = [], stage = 'all', selected = null, api = null;
  var COLS = [
    { field: 'what_text', headerName: 'What ran', minWidth: 320, pinned: 'left', cellClass: 'cell-b' },
    { field: 'id_text', headerName: 'PayPal id', minWidth: 250, cellClass: 'cell-id' },
    { field: 'date_text', headerName: 'Recorded', minWidth: 120 },
    { field: 'stage_text', headerName: 'Stage', minWidth: 120 },
    { colId: 'countdown', headerName: 'Deadline', minWidth: 150, cellClass: 'cell-id', valueGetter: function (p) { return L.deadlineOf(p.data, Date.now()); },
      cellClassRules: { 'cw-late': function (p) { return p.value === 'Deadline passed'; },
        'cw-soon': function (p) { return !!(p.data && p.data.due && p.value !== 'closed' && L.countdown(p.data.due, Date.now()).state === 'soon'); } } },
    { field: 'due', headerName: 'Due (UTC)', hide: true },
    { field: 'proposal_text', headerName: 'Model proposal', minWidth: 160, tooltipField: 'model_text' },
    { field: 'decided_text', headerName: 'Policy decision', minWidth: 290 },
    { field: 'model_text', headerName: 'Proposed by', minWidth: 150 },
    { field: 'paypal_status', headerName: 'PayPal record', minWidth: 210 },
    { field: 'outcome', headerName: 'Outcome', minWidth: 380, tooltipField: 'outcome' },
    { field: 'amount_text', headerName: 'Amount USD', minWidth: 120, cellClass: 'cell-id' },
    { field: 'reason_text', headerName: 'Reason', minWidth: 240 },
    { field: 'fee_avoided', headerName: 'Fee avoided USD', minWidth: 150, cellClass: 'cell-id' },
    { field: 'dispatch_text', headerName: 'Dispatch proof', minWidth: 280 }
  ];

  var TITLES = { c: 'Refund under the limit', d: 'Refund above the approval line, approved', e: 'Lost reply, reconciled', m1: 'Refund before the network cut', m2: 'Refund held offline, then resumed', m3: 'Refund held offline, then resumed',
    i: 'Item not received, tracking sent', n: '3 Nov: offer paid, dispute resolved', o: '3 Nov: parcel count sent as evidence' };
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var KINDS = { settled: 'settled', review: 'answered with proof', owner: 'waiting for owner', mandate: 'refused' };
  function kindOf(r) {
    var o = String(r.outcome || '').toLowerCase();
    if (/^(refused|handled by mandate)/.test(o)) return 'mandate';
    if (r.state === 'awaiting approval' || /^(waiting for owner|escalated to merchant owner)/.test(o)) return 'owner';
    if (r.paypal_status === 'RESOLVED' && r.stage === 'INQUIRY') return 'settled';
    return 'review';
  }
  function titleOf(c, r) { var b = /^b(\d+)$/.exec(c); return TITLES[c] || (b ? 'Case ' + b[1] + ' of 10' + (r ? ', ' + KINDS[kindOf(r)] : '') : String(c)); }
  function dateOf(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || ''); return m ? (+m[3]) + ' ' + MONTHS[+m[2] - 1] + ' ' + m[1] : ''; }
  function idOf(r) {
    if (/^batch-sandbox/.test(r.dispute || '')) return 'none, refused before PayPal was called' + (r.record && r.record.order_id ? ' (order ' + r.record.order_id + ')' : '');
    return /^refund of case/.test(r.dispute || '') ? 'not written to the run file' : r.dispute;
  }
  function text(v) { return v === null || v === undefined || v === '' ? L.DASH : String(v); }
  function prepare(r) {
    return Object.assign({}, r, {
      what_text: titleOf(r.case, r), id_text: text(idOf(r)), date_text: text(dateOf(r.recorded)),
      stage_text: r.kind === 'refund' ? 'Refund, no dispute' : text(r.stage), proposal_text: L.proposalOf(r), model_text: r.proposed ? text(r.model) : L.DASH,
      decided_text: text(L.plain(r.decided)), amount_text: text(r.amount), reason_text: text(L.readable(r.reason)), dispatch_text: text(r.dispatch), outcome: text(r.outcome)
    });
  }
  function visible() { return rows.filter(function (r) { return L.stagePasses(r, stage); }); }

  // ---- data ----
  function good(r) { return r && typeof r === 'object' && typeof r.dispute === 'string' && r.dispute.length > 0 && r.dispute.length < 80; }
  function clean(r, file) {
    var out = Object.assign({ kind: 'dispute', case: '', reason: '', amount: '', stage: '', paypal_status: '', state: '', due: '', proposed: '', model: '', decided: '',
      outcome: '', fee_avoided: '', dispatch: '', message: '', record: {}, mode: 'real sandbox' }, r);
    ['case', 'reason', 'amount', 'stage', 'paypal_status', 'state', 'due', 'proposed', 'model', 'decided', 'outcome', 'fee_avoided', 'dispatch', 'message', 'mode']
      .forEach(function (k) { out[k] = out[k] === null || out[k] === undefined ? '' : String(out[k]); });
    out.kind = out.kind === 'refund' ? 'refund' : 'dispute';
    out.record = out.record && typeof out.record === 'object' ? out.record : {};
    out.settled_before_escalation = out.settled_before_escalation === true;
    out.receipts = typeof out.receipts === 'string' && /^receipts\/[A-Za-z0-9._-]+\.ndjson$/.test(out.receipts) ? out.receipts : '';
    out.file = file;
    return out;
  }
  function getJson(path) { return fetch(path, { credentials: 'omit' }).then(function (r) { if (!r.ok) throw new Error(path + ' ' + r.status); return r.json(); }); }
  function loadAll() {
    return getJson('data/manifest.json').catch(function () { return { files: ['ledger.json'] }; }).then(function (m) {
      var files = (m.files || []).filter(function (f) { return /^[A-Za-z0-9._-]+\.json$/.test(f) && f !== 'manifest.json'; });
      return Promise.all(files.map(function (f) {
        return getJson('data/' + f).then(function (d) { return (Array.isArray(d) ? d : (d && d.rows) || []).filter(good).map(function (r) { return clean(r, f); }); },
          function () { return []; });
      }));
    }).then(function (lists) {
      var seen = {};
      return [].concat.apply([], lists).filter(function (r) { if (seen[r.dispute]) return false; seen[r.dispute] = true; return true; });
    });
  }

  // ---- detail ----
  function showDetail(r) {
    selected = r ? r.dispute : null;
    $('row-detail').hidden = !r; $('detail-hint').hidden = !!r;
    if (!r) return;
    var facts = [['PayPal id', text(idOf(r))], ['What ran', titleOf(r.case, r)], ['Recorded', text(dateOf(r.recorded))], ['Reason', text(L.readable(r.reason))], ['Amount', r.amount ? 'USD ' + r.amount : L.DASH], ['Stage', r.stage_text],
      ['PayPal record', text(r.paypal_status)], ['Deadline', r.due ? r.due + ' (' + L.deadlineOf(r, Date.now()) + ')' : L.DASH],
      ['Model proposal', r.proposal_text + (r.proposed && r.model ? ', by ' + r.model : '')], ['Policy decision', r.decided_text], ['Outcome', r.outcome],
      ['Run', text(r.mode) + ', ' + text(r.recorded)]];
    var dl = $('detail-facts'); dl.textContent = '';
    facts.forEach(function (f) { var d = document.createElement('div'), t = document.createElement('dt'), v = document.createElement('dd'); t.textContent = f[0]; v.textContent = f[1]; d.append(t, v); dl.append(d); });
    $('detail-message').textContent = r.message ? 'The buyer wrote: "' + r.message + '"' : '';
    $('detail-raw').textContent = JSON.stringify(r.record, null, 2);
    var link = $('detail-receipts'); link.hidden = !r.receipts; if (r.receipts) link.href = r.receipts;
  }

  // ---- CSV ----
  function csv() {
    var name = 'clearwake-ledger-' + new Date().toISOString().slice(0, 10) + '.csv';
    var text;
    if (api) text = api.getDataAsCsv({ allColumns: true, columnSeparator: ',', processCellCallback: function (p) { return L.csvSafe(p.formatValue ? p.formatValue(p.value) : p.value); } });
    var heads = COLS.map(function (c) { return { headerName: c.headerName || c.field, get: function (r) { return c.colId === 'countdown' ? L.deadlineOf(r, Date.now()) : r[c.field] === undefined ? '' : r[c.field]; } }; });
    if (text === undefined) text = L.toCsv(heads, visible().map(prepare));
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' })); a.download = name;
    document.body.append(a); a.click(); a.remove();
  }

  // ---- the batch: its counts and cards are drawn by room.js from data/cases.json; this file keeps the file hash and the grid ----
  var BATCH = 'batch-sandbox-20261111-132948.json';
  function mk(tag, cls, txt) { var e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; }
  function hashBatch() {
    var el = $('batch-hash'); if (!el || !window.crypto || !crypto.subtle) return;
    fetch('data/' + BATCH, { credentials: 'omit' }).then(function (r) { return r.arrayBuffer(); }).then(function (b) { return crypto.subtle.digest('SHA-256', b); }).then(function (d) {
      var hex = Array.prototype.map.call(new Uint8Array(d), function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
      el.textContent = ''; el.append(document.createTextNode('SHA-256 of data/' + BATCH + ' computed in your browser: '), mk('code', 'id wrap-any', hex));
    }).catch(function () {});
  }

  // ---- grid, or a plain table when AG Grid did not load ----
  function count() {
    var shown = api ? api.getDisplayedRowCount() : visible().length;
    $('ledger-count').textContent = shown + ' of ' + rows.length + ' rows';
  }
  function plainTable(data) {
    var t = document.createElement('table'), head = t.createTHead().insertRow();
    t.className = 'plain-table';
    COLS.filter(function (c) { return !c.hide; }).forEach(function (c) { var th = document.createElement('th'); th.scope = 'col'; th.textContent = c.headerName; head.append(th); });
    var body = t.createTBody();
    data.forEach(function (r) {
      var tr = body.insertRow(); tr.tabIndex = 0;
      COLS.filter(function (c) { return !c.hide; }).forEach(function (c) { tr.insertCell().textContent = c.colId === 'countdown' ? L.deadlineOf(r, Date.now()) : text(r[c.field]); });
      var open = function () { showDetail(r); }; tr.addEventListener('click', open); tr.addEventListener('keydown', function (e) { if (e.key === 'Enter') open(); });
    });
    host.textContent = ''; host.classList.add('plain-host'); host.append(t);
  }
  function build() {
    var data = rows.map(prepare), ag = window.agGrid;
    if (!ag || !ag.createGrid) { rows = data; plainTable(visible()); count(); return; }
    rows = data;
    if (ag.ModuleRegistry && ag.AllCommunityModule) ag.ModuleRegistry.registerModules([ag.AllCommunityModule]);
    // Colours are CSS variables, so the grid follows the light and dark themes and its style text never changes (the CSP lists its hashes).
    var theme = ag.themeQuartz.withParams({ backgroundColor: 'var(--surface)', foregroundColor: 'var(--foreground)', headerBackgroundColor: 'var(--surface-2)',
      borderColor: 'var(--border)', accentColor: 'var(--teal)', oddRowBackgroundColor: 'var(--background)', fontFamily: 'Figtree, system-ui, sans-serif', fontSize: 14, headerFontSize: 14, spacing: 7, wrapperBorderRadius: 8 });
    api = ag.createGrid(host, {
      theme: theme, loading: false, columnDefs: COLS.map(function (c) { return Object.assign({ sortable: true, resizable: true }, c); }), rowData: rows,
      getRowId: function (p) { return p.data.dispute; }, ensureDomOrder: true, animateRows: false, domLayout: 'autoHeight',
      rowSelection: { mode: 'singleRow', checkboxes: false, enableClickSelection: true },
      onSelectionChanged: function (e) { showDetail(e.api.getSelectedRows()[0]); },
      isExternalFilterPresent: function () { return stage !== 'all'; },
      doesExternalFilterPass: function (n) { return L.stagePasses(n.data, stage); },
      overlayNoRowsTemplate: '<span>No rows at this stage.</span>'
    });
    count();
    // The deadline cells count down live; a row with no recorded due date stays a dash.
    setInterval(function () { api.refreshCells({ columns: ['countdown'], force: true }); if (selected) { var r = rows.filter(function (x) { return x.dispute === selected; })[0]; if (r && r.due) showDetail(r); } }, 1000);
  }

  $('stage-filter').addEventListener('change', function () {
    stage = $('stage-filter').value;
    if (api) api.onFilterChanged(); else plainTable(visible());
    count();
  });
  $('export-csv').addEventListener('click', csv);
  loadAll().then(function (list) {
    rows = list;
    if (!rows.length) { $('ledger-count').textContent = 'No recorded rows could be loaded.'; return; }
    hashBatch();
    build();
    var upd = document.createEvent('Event'); upd.initEvent('clearwake:ledger', true, false); document.dispatchEvent(upd);
  });
})();
