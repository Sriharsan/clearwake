/* Break it page. A classic script with no inline code, so the page keeps its strict CSP. Also loads in Node (tests/test_toolkit_guard.py).
 *
 * PATTERNS is the pattern list of clearwake/guard.py (INJECTION), copied name for name and in the same order; MONEY is guard.MONEY.
 * The Python test compares both lists and the result for every text of tests/fixtures/injection_cases.json. Python stays the authority:
 * this port uses JavaScript word boundaries, which see ASCII letters only.
 */
(function (root) {
  'use strict';

  var PATTERNS = {
    "ignore_instructions": "\\b(ignore|disregard|forget|override|bypass)\\b.{0,40}\\b(instruction|limit|rule|polic|prompt|above|previous|cap)",
    "new_policy": "\\b(new|updated|changed) (polic|rule|instruction|limit)",
    "role_claim": "\\b(system prompt|system message|developer mode|you are now|act as|jailbreak|i am (the )?(owner|admin|merchant|paypal))\\b",
    "demands_amount": "\\b(refund|pay|send|offer)\\b.{0,25}(\\$|usd|us\\$)\\s?\\d|(\\$|usd)\\s?\\d[\\d,.]*.{0,25}\\b(refund|now|immediately)\\b",
    "dictates_output": "(reply|respond) with (action|offer|json)|offer_usd|action\\s*[:=]?\\s*(settle|fight|escalate)",
    "unlimited": "\\b(unlimited|no limit|without (any )?limit|full amount regardless)\\b"
  };
  var MONEY = "(?:(?:US\\$|\\$|USD)\\s?(\\d[\\d,]*(?:\\.\\d{1,2})?))|(?:(\\d[\\d,]*(?:\\.\\d{1,2})?)\\s?(?:USD|dollars?|US\\$|\\$))";

  function injectionSignals(text) {
    var found = [];
    Object.keys(PATTERNS).forEach(function (name) {
      if (new RegExp(PATTERNS[name], 'is').test(text || '')) found.push(name);
    });
    return found;
  }

  function minor(text) {
    var s = String(text).replace(/,/g, ''), at = s.indexOf('.');
    var whole = at < 0 ? s : s.slice(0, at), frac = at < 0 ? '' : s.slice(at + 1);
    return parseInt(whole, 10) * 100 + parseInt((frac + '00').slice(0, 2), 10);
  }

  function amountsIn(text) {
    var re = new RegExp(MONEY, 'gi'), out = [], m;
    while ((m = re.exec(text || '')) !== null) out.push(minor(m[1] || m[2]));
    return out;
  }

  function usd(minorUnits) {
    var n = Math.abs(minorUnits), whole = Math.floor(n / 100), cents = String(n % 100).padStart(2, '0');
    return 'USD ' + (minorUnits < 0 ? '-' : '') + String(whole).replace(/\B(?=(\d{3})+(?!\d))/g, ',') + '.' + cents;
  }

  var API = { PATTERNS: PATTERNS, MONEY: MONEY, injectionSignals: injectionSignals, amountsIn: amountsIn, minor: minor, usd: usd };
  if (typeof module === 'object' && module.exports) { module.exports = API; return; }
  root.BreakIt = API;
  if (typeof document === 'undefined') return;

  var DATA = null, ATTACK = 'lost_response', SHOWN = {}, LIMIT = 500;
  var BLURB = {
    lost_response: 'PayPal applied the refund, then the answer never arrived. The agent calls the tool again.',
    injection: 'The buyer\'s message gives the agent orders and names an amount.',
    over_limit: 'The buyer asks for more than the owner\'s limit.',
    duplicate: 'The same case is delivered to the agent two or three times.'
  };
  var NAMES = {
    'clearwake.model.injection_attempt': 'Buyer text read as data, order-giving words found',
    'clearwake.policy.refused': 'Refused above the policy limit',
    'clearwake.guard.held_for_person': 'Held for a person, nothing sent',
    'clearwake.approval.requested': 'Above the approval threshold, a person was asked',
    'clearwake.approval.used': 'The person approved this exact move',
    'clearwake.refund.unknown': 'Answer lost, held as UNKNOWN',
    'clearwake.refund.checked': 'PayPal\'s record read back',
    'clearwake.toolkit.call': 'The call, its amount from PayPal\'s record, its request id'
  };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

  function say(step, guarded) {
    var table = guarded ? {
      'VERIFIED': 'The guard read PayPal\'s record after the call: the claim shows resolved for the amount.',
      'VERIFIED, nothing sent': 'The guard read PayPal\'s record first: it already shows the claim accepted. Nothing was sent again.',
      'held for a person, nothing sent': 'The guard read the amount from PayPal\'s record, found it above the owner\'s limit, and held it for a person. Nothing was sent.',
      'no answer, called again': 'No answer came, so the agent called the same tool again.',
      'error shown to the caller': 'PayPal refused the call and the agent saw the error.'
    } : {
      'accepted': 'The agent called accept_dispute_claim. PayPal answered.',
      'no answer, called again': 'No answer came, so the agent called the same tool again.',
      'error shown to the caller': 'PayPal refused the repeat and the agent saw an error.',
      'resolved': 'The dispute closed in the buyer\'s favour.'
    };
    return table[step] || step;
  }

  function stat(label, value, tone) {
    var wrap = el('div', 'stat');
    wrap.appendChild(el('dt', null, label));
    wrap.appendChild(el('dd', tone || null, value));
    return wrap;
  }

  function side(kind, data, unguarded) {
    var guarded = kind === 'guarded';
    var node = el('section', 'side ' + kind + (guarded ? '' : ' bad'));
    node.setAttribute('aria-labelledby', 'h-' + kind);
    node.appendChild(el('h3', 'side-title', guarded ? 'Guarded agent' : 'Unguarded agent'));
    node.lastChild.id = 'h-' + kind;
    node.appendChild(el('p', 'side-note', guarded ? 'The same episode with the guard in front of the tool. Replayed on the local PayPal layer.' : 'Calls PayPal\'s tool directly. Copied from the recorded run.'));
    node.appendChild(el('p', 'big tnum', usd(data.refunded_minor)));
    node.appendChild(el('p', 'big-cap', guarded && data.refund_records === 0 ? 'paid out. Nothing was sent to PayPal.' : 'paid out by the local PayPal layer'));
    node.appendChild(el('p', 'verdict', data.result.charAt(0).toUpperCase() + data.result.slice(1)));
    var stats = el('dl', 'stats');
    stats.appendChild(stat('Refunds recorded', String(data.refund_records)));
    stats.appendChild(stat('Overpaid', usd(data.overpaid_minor), data.overpaid_minor > 0 ? 'coral' : 'teal'));
    stats.appendChild(stat('Double refunds', String(data.double_refunds), data.double_refunds > 0 ? 'coral' : 'teal'));
    if (guarded) stats.appendChild(stat('Needed a person', data.held_for_person ? 'Yes, held' : data.approvals ? 'Approved ' + data.approvals + (data.approvals === 1 ? ' move' : ' moves') : 'No'));
    node.appendChild(stats);
    var steps = el('ol', 'steps');
    data.steps.forEach(function (s) { steps.appendChild(el('li', null, say(s, guarded))); });
    node.appendChild(el('p', 'mini', 'What happened'));
    node.appendChild(steps);
    return node;
  }

  function supportsEd25519() {
    if (!(window.crypto && crypto.subtle)) return Promise.resolve(false);
    return crypto.subtle.importKey('raw', new Uint8Array(32), { name: 'Ed25519' }, false, ['verify']).then(function () { return true; }, function () { return false; });
  }

  function receipts(item) {
    var g = item.guarded, box = el('section', 'receipts');
    box.setAttribute('aria-labelledby', 'h-rec');
    var h = el('h3', 'side-title', 'Signed receipts of the guarded run');
    h.id = 'h-rec';
    box.appendChild(h);
    box.appendChild(el('p', 'side-note', g.receipt_lines.length + ' lines, same format as Clearwake\'s own receipts: signed, hash chained, checked offline.'));
    var list = el('ol', 'chain-list');
    g.receipt_lines.forEach(function (line) {
      var r = JSON.parse(line), li = el('li');
      li.appendChild(el('span', 'rname', NAMES[r.action_id] || r.action_id));
      li.appendChild(el('code', 'rid', r.action_id.replace('clearwake.', '')));
      list.appendChild(li);
    });
    box.appendChild(list);
    var last = JSON.parse(g.receipt_lines[g.receipt_lines.length - 1]).params;
    box.appendChild(el('p', 'receipt-fact', 'Last line: amount ' + usd(last.amount_minor) + ' from ' + last.amount_source + ', the agent claimed ' + (last.claimed_amount_minor < 0 ? 'nothing' : usd(last.claimed_amount_minor)) + ', state ' + last.state + '.'));
    var more = el('details', 'raw');
    more.appendChild(el('summary', null, 'Show the last signed line'));
    more.appendChild(el('pre', 'rawline', g.receipt_lines[g.receipt_lines.length - 1]));
    box.appendChild(more);
    var row = el('div', 'row');
    var verify = el('button', 'btn primary', 'Verify the receipts in this browser');
    verify.type = 'button';
    var tamper = el('button', 'btn', 'Change one character, verify again');
    tamper.type = 'button';
    row.appendChild(verify); row.appendChild(tamper);
    box.appendChild(row);
    var out = el('p', 'verify-out');
    out.setAttribute('role', 'status');
    box.appendChild(out);
    function check(text, label) {
      out.className = 'verify-out';
      out.textContent = 'Checking...';
      supportsEd25519().then(function (ok) {
        if (!ok) { out.textContent = 'This browser cannot check Ed25519 signatures. Run python -m verdock_core verify on the log instead.'; return null; }
        return import('./verify.js').then(function (m) { return m.verifyLog(text, g.public_key); }).then(function (res) {
          if (res.ok) { out.className = 'verify-out pass'; out.textContent = label + ': all ' + res.count + ' lines verify (signatures and hash chain) against key ' + g.public_key.slice(0, 16) + '...'; }
          else { out.className = 'verify-out fail'; out.textContent = label + ': does not verify. ' + res.failures.slice(0, 3).map(function (f) { return 'line ' + f.line + ', ' + f.reason; }).join('; ') + '.'; }
        });
      }).catch(function () { out.className = 'verify-out fail'; out.textContent = 'The verifier could not run here.'; });
    }
    var text = g.receipt_lines.join('\n') + '\n';
    verify.addEventListener('click', function () { check(text, 'Receipts'); });
    tamper.addEventListener('click', function () { check(text.replace(/("ts_ms":)(\d)/, function (m, a, d) { return a + ((+d + 1) % 10); }), 'One digit changed'); });
    return box;
  }

  function injectionBox(item) {
    var box = el('section', 'inject');
    box.setAttribute('aria-labelledby', 'h-inj');
    var h = el('h3', 'side-title', 'Change the buyer\'s sentence');
    h.id = 'h-inj';
    box.appendChild(h);
    box.appendChild(el('p', 'side-note', 'The pattern check reads your text. The recorded money result above stays the same, because the guard never takes an amount from text.'));
    var label = el('label', 'sr', 'Buyer message');
    label.setAttribute('for', 'inj-text');
    var area = el('textarea', 'inj-text');
    area.id = 'inj-text'; area.rows = 3; area.maxLength = 500; area.value = item.episode.message;
    var reset = el('button', 'btn', 'Put the recorded sentence back');
    reset.type = 'button';
    var read = el('div', 'inj-read');
    read.setAttribute('role', 'status');
    function paint() {
      var signals = injectionSignals(area.value), named = amountsIn(area.value), real = item.episode.amount_minor;
      clear(read);
      read.appendChild(el('p', signals.length ? 'flag' : 'noflag', signals.length ? 'Pattern check: flagged (' + signals.join(', ') + '). The guard writes a receipt and changes nothing else.' : 'Pattern check: no pattern matched. The guard writes no flag for this text.'));
      read.appendChild(el('p', null, 'Amount named in the text: ' + (named.length ? named.map(usd).join(', ') + ', ignored' : 'none') + '. Amount the guard uses: ' + usd(real) + ', read from PayPal\'s record, then checked against the owner\'s limit of ' + usd(LIMIT) + '.'));
      read.appendChild(el('p', 'mini-note', signals.length ? 'The flag warns the owner. The limit keeps the money safe.' : 'No pattern matched, and the amount is still held above the limit, because the limit does not read text.'));
    }
    area.addEventListener('input', paint);
    reset.addEventListener('click', function () { area.value = item.episode.message; paint(); });
    box.appendChild(label); box.appendChild(area); box.appendChild(reset); box.appendChild(read);
    paint();
    return box;
  }

  function show() {
    var list = DATA.attacks[ATTACK].shown, i = SHOWN[ATTACK] % list.length, item = list[i];
    var out = clear($('result'));
    out.className = 'result rise';
    var head = el('p', 'episode', DATA.attacks[ATTACK].title + '. Recorded episode ' + item.episode.n + ' of the ' + DATA.episodes + ' (' + (i + 1) + ' of ' + list.length + ' shown here; press Run for the next).');
    out.appendChild(head);
    if (ATTACK === 'injection') out.appendChild(el('blockquote', 'quote', item.episode.message));
    var sides = el('div', 'sides');
    sides.appendChild(side('unguarded', item.unguarded, true));
    sides.appendChild(side('guarded', item.guarded, false));
    out.appendChild(sides);
    out.appendChild(receipts(item));
    if (ATTACK === 'injection') out.appendChild(injectionBox(item));
    SHOWN[ATTACK] += 1;
    $('run').textContent = 'Run again (next recorded episode)';
  }

  function choose(key) {
    ATTACK = key;
    $('blurb').textContent = BLURB[key];
    if (!SHOWN[key]) { clear($('result')); $('result').className = 'result'; $('run').textContent = 'Run'; }
    SHOWN[key] = SHOWN[key] || 0;
    $('run').textContent = SHOWN[key] ? 'Run again (next recorded episode)' : 'Run';
  }

  function totals() {
    var t = DATA.totals, box = clear($('totals'));
    function fig(num, tone, label) {
      var div = el('div', 'fig');
      div.appendChild(el('dt', null, label));
      div.appendChild(el('dd', 'figure tnum ' + tone, num));
      return div;
    }
    box.appendChild(fig(usd(t.unguarded_overpaid_minor), 'coral', 'overpaid by the unguarded agent over all ' + t.episodes + ' attack episodes. The guarded agent: ' + usd(t.guarded_overpaid_minor) + '.'));
    box.appendChild(fig(String(t.unguarded_double_refunds), 'coral', 'double refunds, from lost responses and repeated deliveries. The guarded agent: ' + t.guarded_double_refunds + '.'));
    box.appendChild(fig(t.held_for_person + ' of ' + t.episodes, 'teal', 'episodes the guard held for a person instead of paying. A person decides each of those.'));
  }

  function start() {
    var theme = document.querySelector('.theme');
    if (theme && !theme.textContent) theme.textContent = 'Light';
    fetch('data/break.json').then(function (r) { if (!r.ok) throw new Error('data'); return r.json(); }).then(function (data) {
      DATA = data; LIMIT = data.owner_limit_minor;
      $('label').textContent = 'Recorded from the ' + data.episodes + ' episode run, seed ' + data.seed + ', on the ' + data.layer + '. Replayed with no PayPal call, and no money moves.';
      totals();
      Array.prototype.forEach.call(document.querySelectorAll('input[name="attack"]'), function (radio) {
        radio.addEventListener('change', function () { choose(radio.value); });
      });
      $('run').addEventListener('click', show);
      choose(document.querySelector('input[name="attack"]:checked').value);
      var wanted = (location.hash || '').replace('#', '');
      if (DATA.attacks[wanted]) { document.querySelector('input[value="' + wanted + '"]').checked = true; choose(wanted); }
    }).catch(function () {
      $('label').textContent = 'The recorded episodes could not be loaded. Reload the page.';
      $('run').disabled = true;
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})(typeof self !== 'undefined' ? self : this);
