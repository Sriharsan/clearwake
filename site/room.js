// Control Room: keyboard driven river of recorded disputes, the fee what-if from clearwake/fees.py, ledger sort and filter.
// Nothing is fetched or sent. Every value shown comes from data attributes in the page.
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
    var id = m.closest(".lane").dataset.lane;
    all("#ledger tbody tr").forEach(function (r) { r.classList.toggle("sel", r.dataset["case"] === id); });
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

  var table = $("#ledger"); if (!table) return;
  var body = table.tBodies[0], rows = [].slice.call(body.rows), count = $("#ledger-count"), filter = "all", sortKey = "", dir = 1;
  function render() {
    var shown = 0;
    rows.forEach(function (r) { var on = filter === "all" || r.dataset.source === filter; r.hidden = !on; if (on) shown++; });
    if (count) count.textContent = shown + " of " + rows.length + " rows, all recorded";
  }
  var chips = all("[data-filter]");
  chips.forEach(function (b) { b.addEventListener("click", function () { filter = b.dataset.filter; chips.forEach(function (o) { o.setAttribute("aria-pressed", o === b ? "true" : "false"); }); render(); }); });
  all(".sort", table).forEach(function (b) {
    b.addEventListener("click", function () {
      var key = b.dataset.key; dir = sortKey === key ? -dir : 1; sortKey = key;
      all("th", table.tHead).forEach(function (th) { th.removeAttribute("aria-sort"); });
      b.parentNode.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      rows.sort(function (a, c) {
        var x = a.dataset[key], y = c.dataset[key];
        if (key === "amount") { if (x === "" && y === "") return 0; if (x === "") return 1; if (y === "") return -1; return (parseFloat(x) - parseFloat(y)) * dir; }
        return (x < y ? -1 : x > y ? 1 : 0) * dir;
      });
      rows.forEach(function (r) { body.appendChild(r); });
    });
  });
  render();
})();
