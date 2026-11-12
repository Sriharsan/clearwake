// Control Room: keyboard driven river of recorded disputes, the fee what-if from clearwake/fees.py, receipt Verify buttons.
// Nothing is sent. The river reads data attributes in the page; the cards at the end of this file read data/cases.json.
(function () {
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var all = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };
  var secs = all(".index a").map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); });
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (en) {
      en.forEach(function (e) { if (e.isIntersecting) all(".index a").forEach(function (a) { if (a.getAttribute("href") === "#" + e.target.id) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current"); }); });
    }, { rootMargin: "-30% 0px -60% 0px" });
    secs.forEach(function (s) { if (s) io.observe(s); });
  }
  var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  var lanes = all(".lane"), marks = all(".mark"), cur = null, hv = false;
  var feeNum = $("#fee-num"), feeCase = $("#fee-case"), feeNote = $("#fee-note"), hvBtn = $("#hv");
  function money(v) { return '<span class="cur">USD</span> ' + v; }
  function paintFee() {
    if (!cur) return;
    var lane = cur.closest(".lane"), std = lane.dataset.std, hi = lane.dataset.hv;
    feeCase.textContent = lane.dataset.title;
    feeNum.classList.remove("leak");
    if (!hv) { feeNum.innerHTML = money(std || "0.00"); feeNote.textContent = lane.dataset.note; }
    else if (hi) { feeNum.innerHTML = money(hi); feeNum.classList.add("leak"); feeNote.textContent = "What if: more than 100 sales and a rate of 1.5% or more. PayPal's rule then charges the High Volume Dispute Fee of USD 30.00 when a counted case becomes a claim. Settling in conversation avoids it."; }
    else { feeNum.innerHTML = money("0.00"); feeNote.textContent = "The what-if applies to disputes with a recorded reason. This case has none, so nothing is computed."; }
  }
  function select(m, focus) {
    if (!m) return;
    cur = m;
    marks.forEach(function (x) { x.classList.toggle("sel", x === m); });
    lanes.forEach(function (l) { l.classList.toggle("on", l === m.closest(".lane")); });
    var d = m.dataset;
    $("#d-meta").textContent = m.closest(".lane").dataset.title + ", step " + (+d.i + 1) + ", " + d.time + ", " + d.ok;
    $("#d-label").textContent = d.label;
    $("#d-why").textContent = d.why;
    $("#d-sig").textContent = d.sig;
    $("#d-prev").textContent = d.prev;
    paintFee();
    if (focus) { m.focus({ preventScroll: true }); try { m.scrollIntoView({ block: "nearest", inline: "center", behavior: reduce ? "auto" : "smooth" }); } catch (e) {} }
  }
  marks.forEach(function (m) {
    m.addEventListener("click", function () { select(m, false); });
    m.addEventListener("focus", function () { if (cur !== m) select(m, false); });
  });
  function move(dx, dy) {
    var m = cur || marks[0], lane = m.closest(".lane"), mine = all(".mark", lane), i = mine.indexOf(m);
    if (dx) return select(mine[Math.max(0, Math.min(mine.length - 1, i + dx))], true);
    var li = lanes.indexOf(lane) + dy; if (li < 0 || li >= lanes.length) return;
    var to = all(".mark", lanes[li]); select(to[Math.min(i, to.length - 1)], true);
  }
  function setHv(v) { hv = v; hvBtn.setAttribute("aria-pressed", v ? "true" : "false"); paintFee(); }
  hvBtn.addEventListener("click", function () { setHv(!hv); });
  addEventListener("keydown", function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    var t = ev.target, tag = t && t.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    var k = ev.key, inRiver = t && t.closest && t.closest("#river");
    if (inRiver && (k === "ArrowLeft" || k === "ArrowRight" || k === "ArrowUp" || k === "ArrowDown")) {
      ev.preventDefault(); move(k === "ArrowLeft" ? -1 : k === "ArrowRight" ? 1 : 0, k === "ArrowUp" ? -1 : k === "ArrowDown" ? 1 : 0);
    } else if (k === "h" || k === "H") { setHv(!hv); }
    else if (k >= "1" && k <= "8" && tag !== "BUTTON" && tag !== "SUMMARY") {
      var s = secs[+k - 1]; if (s) s.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    }
  });
  // Receipts: each Verify button fetches its log and checks Ed25519 signatures and the SHA-256 hash chain with WebCrypto, in this browser.
  all(".verify").forEach(function (b) {
    var out = b.closest("li").querySelector(".verify-out");
    b.addEventListener("click", function () {
      out.className = "verify-out"; out.textContent = "Fetching the log and checking it in this browser.";
      fetch(b.dataset.log, { credentials: "omit" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (text) { return import("./verify.js").then(function (m) { return m.verifyLog(text, b.dataset.key); }); })
        .then(function (res) {
          if (res.ok) { out.className = "verify-out pass"; out.textContent = "All " + res.count + " lines verify: Ed25519 signatures and SHA-256 hash chain, against the key above."; }
          else { out.className = "verify-out fail"; out.textContent = "Does not verify. " + res.failures.slice(0, 3).map(function (f) { return "line " + f.line + ", " + f.reason; }).join("; ") + "."; }
        })
        .catch(function () { out.className = "verify-out fail"; out.textContent = "This browser could not run the check (Ed25519 in WebCrypto is required). Run python -m verdock_core verify on the log."; });
    });
  });
  // Lead number: every log listed in receipts/manifest.json is fetched and checked here, with the same verifier as the buttons below.
  (function () {
    var num = $("#v-num"), label = $("#v-label"), src = $("#v-src");
    if (!num) return;
    function done(ok, total, lines) {
      num.textContent = ok + " of " + total;
      label.textContent = "signed logs verify in this browser, " + lines + " lines checked: Ed25519 signatures and the SHA-256 hash chain";
      num.classList.toggle("bad", ok !== total);
    }
    function skip() { num.textContent = "Not run"; label.textContent = "This browser could not run the check (Ed25519 in WebCrypto is required). Use the Verify buttons or python -m verdock_core verify."; num.classList.add("bad"); }
    fetch("receipts/manifest.json", { credentials: "omit" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (man) {
      var logs = man.logs || [];
      return import("./verify.js").then(function (m) {
        return Promise.all(logs.map(function (l) {
          return fetch(l.file, { credentials: "omit" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); }).then(function (t) { return m.verifyLog(t, l.public_key); });
        }));
      }).then(function (res) {
        done(res.filter(function (x) { return x.ok; }).length, logs.length, res.reduce(function (a, x) { return a + (x.count || 0); }, 0));
      });
    }).catch(skip);
  })();
  var first = $(".lane .mark");
  if (first) select(first, false);
})();

// Cases: one card per dispute, drawn from data/cases.json (built by scripts/build_site_data.py from the case-records run file, the batch file,
// the two signed batch logs and the policy file). Each Verify button checks the receipt lines of its card against the published log with site/verify.js.
(function () {
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var host = $("#case-cards");
  if (!host) return;
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var WORD = { "settled": "Settled", "resolved at chargeback": "Resolved at chargeback", "answered with proof": "Answered with proof", "waiting for owner": "Waiting for owner", "refused": "Refused" };
  var SLUG = { "settled": "settled", "resolved at chargeback": "chargeback", "answered with proof": "proof", "waiting for owner": "owner", "refused": "refused" };
  var DATA = null, logs = {};
  function el(tag, cls, txt) { var e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined && txt !== null) e.textContent = txt; return e; }
  function when(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?Z$/.exec(iso);
    return m ? (+m[3]) + " " + MONTHS[+m[2] - 1] + " " + m[1] + " " + m[4] + ":" + m[5] + (m[6] ? ":" + m[6] : "") + " UTC" : iso;
  }
  function nice(t) { return String(t).replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z/g, when); }
  function cap(t) { t = String(t || ""); return t.charAt(0).toUpperCase() + t.slice(1); }

  // Each batch log is fetched once and checked with the same verifier as the Receipts buttons; single lines are then answered from that result.
  function checked(side) {
    if (!logs[side]) {
      var L = DATA.logs[side];
      logs[side] = fetch(L.file, { credentials: "omit" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (text) {
          return import("./verify.js").then(function (m) { return m.verifyLog(text, L.key); }).then(function (res) {
            var bad = {}; res.failures.forEach(function (f) { (bad[f.line] = bad[f.line] || []).push(f.reason); });
            return { res: res, bad: bad, lines: text.replace(/\n$/, "").split("\n") };
          });
        });
    }
    return logs[side];
  }
  function verifyCard(steps, out, btn) {
    out.className = "verify-out"; out.textContent = "Fetching the logs and checking them in this browser.";
    btn.disabled = true;
    var sides = steps.reduce(function (a, s) { if (a.indexOf(s.step.log) < 0) a.push(s.step.log); return a; }, []);
    Promise.all(sides.map(function (side) { return checked(side).then(function (c) { return [side, c]; }); })).then(function (pairs) {
      var by = {}; pairs.forEach(function (p) { by[p[0]] = p[1]; });
      var good = 0;
      steps.forEach(function (s) {
        var c = by[s.step.log], row = null, why = "";
        try { row = JSON.parse(c.lines[s.step.line - 1]); } catch (e) { why = "the line is not in the log"; }
        if (row && row.action_id !== s.step.action) why = "the line is " + row.action_id + ", not " + s.step.action;
        if (!why && c.bad[s.step.line]) why = c.bad[s.step.line][0];
        s.mark.className = "st " + (why ? "bad" : "ok");
        s.mark.textContent = why ? "does not verify: " + why : "verifies";
        if (!why) good++;
      });
      var whole = sides.every(function (sd) { return by[sd].res.ok; });
      out.className = "verify-out " + (good === steps.length ? "pass" : "fail");
      out.textContent = good === steps.length
        ? "All " + good + " receipt lines of this card verify: Ed25519 signature and SHA-256 hash link" + (whole ? ", and so does every other line of the log." : ".")
        : (steps.length - good) + " of " + steps.length + " receipt lines do not verify.";
    }).catch(function () {
      out.className = "verify-out fail"; out.textContent = "This browser could not run the check (Ed25519 in WebCrypto is required). Run python -m verdock_core verify on the log.";
    }).then(function () { btn.disabled = false; });
  }

  function block(title) { var s = el("section", "c-col"); s.append(el("h4", null, title)); return s; }
  function card(c) {
    var slug = SLUG[c.result];
    var art = el("article", "case r-" + slug), head = el("header", "c-head"), h = el("h3", null, cap(c.scenario));
    art.id = "case-" + c.n; art.setAttribute("aria-labelledby", "case-h-" + c.n); h.id = "case-h-" + c.n;
    head.append(el("span", "c-n tnum", "Case " + c.n + " of 10"), h, el("span", "res res-" + slug, WORD[c.result]));
    art.append(head, el("p", "c-sum", c.summary));
    var meta = el("p", "c-meta");
    if (c.dispute) meta.append(el("span", "id", c.dispute), document.createTextNode(", ")); else meta.append(document.createTextNode("No dispute id, none was opened, "));
    meta.append(document.createTextNode("order "), el("span", "id", c.order), document.createTextNode(c.ask ? ", asked USD " + c.ask + " of USD " + c.paid + " paid" : ", USD " + c.paid + " paid"));
    art.append(meta);
    var cols = el("div", "c-cols"), left = block(c.result === "refused" ? "What the buyer agent did" : "What the merchant agent sent"), right = block("PayPal's own record");
    var ol = el("ol", "c-steps"), pending = [];
    c.steps.forEach(function (s) {
      var li = el("li"), ref = el("span", "c-r"), link = el("a", null, "receipt line " + s.line + ", " + s.file), st = el("span", "st", "");
      link.href = "receipts/" + s.file;
      ref.append(link, document.createTextNode(" "), st);
      li.append(el("strong", null, s.label), el("span", "c-d", s.detail), ref);
      ol.append(li); pending.push({ step: s, mark: st });
    });
    left.append(ol);
    if (c.paypal.length) {
      var dl = el("dl", "c-facts");
      c.paypal.forEach(function (f) { var d = el("div"); d.append(el("dt", null, f[0]), el("dd", null, nice(f[1]))); dl.append(d); });
      right.append(dl);
    } else {
      right.append(el("p", null, "No dispute was opened, so PayPal holds no record for this case."));
    }
    if (c.refund) {
      var rb = el("div", "c-refund"), ul = el("ul");
      c.refund.movements.forEach(function (m) { ul.append(el("li", null, m)); });
      rb.append(el("p", "c-big", "Refund " + c.refund.id + ", USD " + c.refund.amount), el("p", "note", "PayPal's money movements on this dispute:"), ul);
      right.append(rb);
    }
    cols.append(left, right); art.append(cols);
    if (c.rule) {
      var rule = el("div", "c-rule");
      rule.append(el("h4", null, "Why it waits for the owner"), el("p", null, c.rule.text),
        el("p", "note", "Rule read from " + c.rule.source + (c.rule.decision_line ? "; decision receipt line " + c.rule.decision_line + ", batch-merchant.ndjson" : "") + "."));
      art.append(rule);
    }
    if (c.mandate) {
      var mb = el("div", "c-rule");
      mb.append(el("h4", null, "Why it was refused"), el("p", null, c.mandate.why), el("p", "note", "The buyer agent's rule: " + c.mandate.rule + " Mandate receipt " + c.mandate.receipt + "."));
      art.append(mb);
    }
    if (c.voice) {
      var vb = el("div", "c-rule");
      vb.append(el("h4", null, "Decided by the owner's voice"),
        el("p", null, "“" + c.voice.command + "”, heard by " + c.voice.speech_to_text + ", owner voice " + c.voice.owner_voice + ", replies in " + c.voice.reply_voice + ". " + c.voice.what_ran + ". Writes to PayPal: " + c.voice.writes + "."),
        el("p", "note", "Signed policy " + c.voice.policy_hash.slice(0, 12) + (c.voice.approval ? ", approval " + c.voice.approval.slice(0, 8) : "") + ". Read back from PayPal's record on " + c.voice.recorded.slice(0, 10) + ", run file " + c.voice.file + "."));
      art.append(vb);
    }
    if (c.buyer_wrote) art.append(el("p", "c-buyer", "The buyer wrote: “" + c.buyer_wrote + "”"));
    var acts = el("div", "c-acts"), btn = el("button", "btn verify-card", "Verify " + c.steps.length + " receipt lines in your browser"), out = el("p", "verify-out");
    btn.type = "button"; out.setAttribute("aria-live", "polite");
    btn.addEventListener("click", function () { verifyCard(pending, out, btn); });
    acts.append(btn, out); art.append(acts);
    if (c.raw) {
      var det = el("details", "c-raw"), pre = el("pre", "codeblock", JSON.stringify(c.raw, null, 2));
      pre.tabIndex = 0;
      det.append(el("summary", null, c.result === "refused" ? "The receipt as recorded, JSON" : "PayPal's record, raw JSON"), el("p", "note", c.raw_label + "."), pre);
      art.append(det);
    }
    return art;
  }

  function cost(d) {
    var k = d.cost, nums = $("#cost-numbers"), table = $("#cost-table");
    if (!k || !window.ClearwakeNumbers) return;
    var list = [{ value: (k.merchant_calls + k.buyer_calls) + " calls", label: k.merchant_calls + " merchant and " + k.buyer_calls + " buyer model calls over " + k.cases + " cases", source: d.batch, mode: d.mode }];
    if (k.median_seconds_per_call !== null) list.push({ value: k.median_seconds_per_call + " s", label: "median per model call, read from the " + k.calls_checked + " calls in the two signed logs", source: "receipts/batch-merchant.ndjson and batch-buyer.ndjson", mode: d.mode });
    list.push({ value: "USD " + k.cost_per_call_usd, label: "model cost per call: " + k.model, source: d.batch, mode: d.mode });
    nums.textContent = ""; ClearwakeNumbers.render(nums, list);
    $("#cost-note").textContent = k.note + " Model time in total: " + k.model_seconds_total + " s.";
    var tb = $("tbody", table); tb.textContent = "";
    k.per_case.forEach(function (r) {
      var tr = tb.insertRow();
      ["Case " + r.n, r.merchant_calls, r.buyer_calls, r.model_seconds + " s", "USD " + r.cost_usd].forEach(function (v, i) { var td = tr.insertCell(); td.textContent = v; if (i) td.className = "tnum"; });
    });
    table.hidden = false;
  }

  // The rest of the page that reads the same file: the tally, the waiting count and the deadline, the limits and the batch policy.
  function around(d) {
    var ids = { "settled": "t-settled", "resolved at chargeback": "t-chargeback", "answered with proof": "t-review", "waiting for owner": "t-owner", "refused": "t-mandate" };
    Object.keys(ids).forEach(function (k) { var e = document.getElementById(ids[k]); if (e) e.textContent = d.counts[k]; });
    var wc = $("#w-count"), ws = $("#w-sub");
    if (wc) {
      wc.textContent = d.waiting.length;
      ws.textContent = d.waiting.length ? "Case" + (d.waiting.length > 1 ? "s " : " ") + d.waiting.join(" and ") + (d.waiting.length > 1 ? " wait" : " waits") + " for the owner. Their cards say why." : "No case waits for the owner.";
    }
    var due = d.deadlines[0], wd = $("#w-due"), wds = $("#w-due-sub");
    if (wd) {
      if (due) {
        var ms = Date.parse(due.due) - Date.now(), days = Math.floor(ms / 86400000);
        wd.textContent = when(due.due).replace(/:\d\d UTC$/, " UTC");
        wds.textContent = "PayPal's seller response due date on case " + due.n + (ms > 0 ? ", " + days + (days === 1 ? " day" : " days") + " from now." : ", passed.");
      } else { wd.textContent = "None"; wds.textContent = "PayPal's records carry no seller response due date."; }
    }
    var al = $("#approval-limits");
    if (al) al.textContent = "Refund up to USD 5.00 alone, approval above USD " + d.policy.refund_approval_above + ". Offers: the agent settles alone up to USD " + d.policy.offer_alone_up_to + ", asks the owner up to USD " + d.policy.offer_ceiling + ", never more.";
    var aw = $("#approval-waiting");
    if (aw) {
      aw.textContent = "";
      d.cases.filter(function (c) { return c.result === "waiting for owner"; }).forEach(function (c) {
        var a = el("a", null, "Case " + c.n); a.href = "#case-" + c.n; aw.append(a, document.createTextNode(": " + c.rule.text + " "));
      });
    }
    var pol = $("#batch-policy"), orule = $("#owner-rule");
    if (pol) pol.textContent = d.policy.text;
    if (orule) orule.textContent = "The owner's rule in words: “" + d.policy.owner_rule + "”";
    var target = location.hash && document.getElementById(location.hash.slice(1));
    if (target) target.scrollIntoView();
  }

  fetch("data/cases.json", { credentials: "omit" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (d) {
    DATA = d; host.textContent = "";
    d.cases.forEach(function (c) { host.append(card(c)); });
    cost(d); around(d);
  }).catch(function () { host.textContent = "The cards could not be loaded. The same data is in data/cases.json."; });
})();
