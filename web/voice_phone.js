// Clearwake phone voice page. Inlined by clearwake/voice_phone.py with the strings table. The link's ?t= token is the credential.
// Secure origin (https): the in page microphone, MediaRecorder. Plain http: the phone's own recorder through <input type=file capture>.
// Typing is the last fallback. All three end in the same turn: transcript, read back, spoken answer.
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("cfg").textContent), LANGS = DATA.languages, ST = DATA.strings;
  var token = new URLSearchParams(location.search).get("t") || "";
  var lang = "en";
  try { var saved = localStorage.getItem("clearwake-lang"); if (saved && LANGS[saved]) lang = saved; } catch (e) {}
  function t(key, params) {
    var e = ST[key]; if (!e) return key;
    return (e[lang] || e.en).replace(/\{(\w+)\}/g, function (m, n) { return params && n in params ? params[n] : m; });
  }
  var $ = function (id) { return document.getElementById(id); };
  var MAX_SECONDS = 28, MIN_MS = 600, HOLD_MS = 450, MAX_BYTES = 5 * 1024 * 1024;
  var el = { mic: $("mic"), word: $("mic-word"), status: $("status"), level: $("level"), timer: $("timer"), notice: $("notice"), chip: $("heard-chip"),
    transcript: $("transcript"), readCard: $("readback-card"), readback: $("readback"), yes: $("yes"), no: $("no"), answer: $("answer"), meta: $("meta"),
    speak: $("speak"), mute: $("mute"), typed: $("typed"), text: $("text"), send: $("send"), clip: $("clip"), native: $("native"), lang: $("lang") };
  var answerToken = "", lastSpoken = "", muted = false, state = "idle", stream = null, recorder = null, chunks = [], stopTimer = null, tick = null;
  var startedAt = 0, pressAt = 0, tapMode = false, audioCtx = null, analyser = null, frame = 0, releaseTimer = null, mime = "", statusKey = "p.ready", noticeKey = "";

  function say(key, params) { statusKey = key; el.status.textContent = t(key, params); }
  function notice(key) { noticeKey = key || ""; el.notice.textContent = key ? t(key) : ""; el.notice.hidden = !key; }
  function secure() { return !!(window.isSecureContext && navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === "function" && window.MediaRecorder); }

  function api(path, body, raw, type) {
    var headers = {};
    if (raw) { if (type) headers["Content-Type"] = type; } else { headers["Content-Type"] = "application/json"; }
    return fetch(path + "?t=" + encodeURIComponent(token), { method: body === null ? "GET" : "POST", headers: headers, body: body === null ? undefined : (raw ? body : JSON.stringify(body)) })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) { var e = new Error(j.error || t("p.failed")); e.status = r.status; throw e; }
          return j;
        });
      });
  }

  // ---- speech out: the device's own voices -----------------------------------------------------------------------
  function pickVoice() {
    var list = window.speechSynthesis ? speechSynthesis.getVoices() : [];
    var en = list.filter(function (v) { return /^en[-_]/i.test(v.lang); });
    return en.filter(function (v) { return v.localService; })[0] || en[0] || null;
  }
  function speakText(text) {
    lastSpoken = text;
    if (muted || !text || !window.speechSynthesis) return;
    try {
      speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(text), v = pickVoice();
      if (v) { u.voice = v; u.lang = v.lang; } else { u.lang = "en-US"; }
      speechSynthesis.speak(u);
    } catch (e) {}
  }
  function prime() {
    try { if (window.speechSynthesis && !prime.done) { prime.done = true; var u = new SpeechSynthesisUtterance(" "); u.volume = 0; speechSynthesis.speak(u); } } catch (e) {}
  }

  // ---- showing a turn ---------------------------------------------------------------------------------------------
  function show(turn) {
    if (turn.transcript) el.transcript.textContent = turn.transcript;
    el.answer.textContent = turn.text;
    var bits = [];
    if (turn.intent && turn.intent !== "yes" && turn.intent !== "no") bits.push(t("p.understood", { intent: turn.intent.replace("_", " ") }));
    if (turn.source === "voice") bits.push("source: voice");
    if (turn.heard) bits.push("read as: " + turn.heard);
    if (turn.policy_hash) bits.push("policy " + turn.policy_hash.slice(0, 12));
    if (turn.transcript_sha256) bits.push("transcript " + turn.transcript_sha256.slice(0, 12));
    el.meta.textContent = bits.join(" | ");
    answerToken = turn.needs_confirm ? turn.token : "";
    el.readCard.hidden = !turn.needs_confirm;
    if (turn.needs_confirm) { el.readback.textContent = turn.text; el.yes.disabled = el.no.disabled = false; }
    speakText(turn.text);
  }
  function turn(body) {
    state = "sending"; paint(); say("p.working_on");
    return api("turn", body).then(function (x) { show(x); say(x.refused ? "p.not_done" : "p.done"); })
      .catch(function (e) { el.answer.textContent = e.message; say("p.failed"); })
      .then(function () { state = "idle"; paint(); });
  }
  function answer(choice) {
    if (!answerToken) return;
    el.yes.disabled = el.no.disabled = true; state = "sending"; paint(); say(choice === "yes" ? "p.confirming" : "p.cancelling");
    api("answer", { token: answerToken, answer: choice }).then(function (x) { show(x); el.readCard.hidden = !x.needs_confirm; say("p.done"); })
      .catch(function (e) { el.answer.textContent = e.message; say("p.failed"); el.yes.disabled = el.no.disabled = false; })
      .then(function () { state = "idle"; paint(); });
  }
  function transcribed(t0) {
    el.transcript.textContent = t0.transcript || "";
    el.chip.textContent = t("p.heard_in", { s: (t0.ms / 1000).toFixed(1), a: t0.audio_seconds.toFixed(1) });
    if (!t0.transcript) { state = "idle"; paint(); say("p.nothing_heard"); el.transcript.textContent = t("p.said_empty"); return null; }
    return turn({ transcript_id: t0.transcript_id });
  }
  function upload(blob, type) {
    if (blob.size > MAX_BYTES) { notice("p.too_big"); state = "idle"; paint(); return; }
    state = "sending"; paint(); say("p.sending_clip", { kb: Math.round(blob.size / 1024) }); el.chip.textContent = t("p.reading");
    api("transcribe", blob, true, type || "application/octet-stream").then(transcribed).catch(function (e) {
      el.chip.textContent = t("p.not_read"); notice(null); el.notice.textContent = e.message; el.notice.hidden = false; noticeKey = "";
      if (e.status === 503) el.typed.open = true;
      state = "idle"; paint(); say("p.no_transcript");
    });
  }

  // ---- in page recording (https) ----------------------------------------------------------------------------------
  function paint() {
    var rec = state === "recording", nat = !secure();
    el.mic.classList.toggle("recording", rec); el.mic.classList.toggle("busy", state === "sending");
    el.mic.setAttribute("aria-pressed", rec ? "true" : "false");
    el.word.textContent = rec ? (tapMode ? t("p.tap_stop") : t("p.release")) : state === "sending" ? t("p.working") : (nat ? t("p.record_native") : t("p.hold"));
  }
  function pickMime() {
    var o = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
    for (var i = 0; i < o.length; i++) if (MediaRecorder.isTypeSupported(o[i])) return o[i];
    return "";
  }
  function getStream() {
    if (stream && stream.getTracks().some(function (x) { return x.readyState === "live"; })) return Promise.resolve(stream);
    return navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } }).then(function (s) { stream = s; return s; });
  }
  function dropStream() { if (stream) { stream.getTracks().forEach(function (x) { x.stop(); }); stream = null; } stopMeter(); }
  function releaseSoon() { clearTimeout(releaseTimer); releaseTimer = setTimeout(function () { if (state !== "recording") dropStream(); }, 30000); }
  function startMeter(s) {
    try {
      var C = window.AudioContext || window.webkitAudioContext; if (!C) return;
      audioCtx = audioCtx || new C(); if (audioCtx.state === "suspended") audioCtx.resume();
      var src = audioCtx.createMediaStreamSource(s); analyser = audioCtx.createAnalyser(); analyser.fftSize = 1024; src.connect(analyser);
      var buf = new Uint8Array(analyser.fftSize);
      (function loop() {
        if (!analyser) return; analyser.getByteTimeDomainData(buf);
        var sum = 0; for (var i = 0; i < buf.length; i++) { var v = (buf[i] - 128) / 128; sum += v * v; }
        el.level.value = Math.min(1, Math.sqrt(sum / buf.length) * 4); frame = requestAnimationFrame(loop);
      })();
    } catch (e) {}
  }
  function stopMeter() { analyser = null; cancelAnimationFrame(frame); el.level.value = 0; }
  function begin() {
    if (state !== "idle") return;
    prime();
    if (!secure()) { el.clip.click(); return; }                  // plain http: the phone's own recorder
    state = "recording"; paint(); say("p.allow_mic");
    getStream().then(function (s) {
      if (state !== "recording") return;
      notice(null); mime = pickMime(); chunks = [];
      recorder = mime ? new MediaRecorder(s, { mimeType: mime }) : new MediaRecorder(s);
      recorder.ondataavailable = function (ev) { if (ev.data && ev.data.size) chunks.push(ev.data); };
      recorder.onstop = finish; recorder.start(); startedAt = Date.now(); startMeter(s); say("p.recording");
      tick = setInterval(function () { var n = Math.floor((Date.now() - startedAt) / 1000); el.timer.textContent = Math.floor(n / 60) + ":" + String(n % 60).padStart(2, "0"); }, 250);
      stopTimer = setTimeout(end, MAX_SECONDS * 1000);
    }).catch(function (e) {
      state = "idle"; tapMode = false; paint();
      notice(e && (e.name === "NotAllowedError" || e.name === "SecurityError") ? "p.mic_blocked" : e && e.name === "NotFoundError" ? "p.mic_none" : "p.mic_failed");
      say("p.no_transcript"); el.typed.open = true;
    });
  }
  function end() {
    if (state !== "recording") return;
    clearTimeout(stopTimer); clearInterval(tick); stopMeter();
    if (recorder && recorder.state !== "inactive") recorder.stop(); else { state = "idle"; paint(); }
  }
  function finish() {
    var ms = Date.now() - startedAt, type = (recorder && recorder.mimeType) || mime || "";
    var blob = new Blob(chunks, { type: type || "application/octet-stream" });
    chunks = []; el.timer.textContent = "0:00"; releaseSoon();
    if (ms < MIN_MS || blob.size < 800) { state = "idle"; paint(); say("p.too_short"); return; }
    upload(blob, blob.type);
  }

  el.mic.addEventListener("pointerdown", function (ev) {
    ev.preventDefault();
    if (!secure()) return;
    if (state === "recording" && tapMode) { tapMode = false; end(); return; }
    if (state !== "idle") return;
    pressAt = Date.now(); tapMode = false;
    try { el.mic.setPointerCapture(ev.pointerId); } catch (e) {}
    begin();
  });
  function release() {
    if (!secure() || state !== "recording" || tapMode) return;
    if (Date.now() - pressAt < HOLD_MS) { tapMode = true; paint(); say("p.recording_tap"); return; }
    end();
  }
  el.mic.addEventListener("pointerup", release);
  el.mic.addEventListener("pointercancel", function () { if (state === "recording" && !tapMode) end(); });
  el.mic.addEventListener("contextmenu", function (ev) { ev.preventDefault(); });
  el.mic.addEventListener("click", function (ev) { if (!secure() && state === "idle") { prime(); el.clip.click(); } });
  el.mic.addEventListener("keydown", function (ev) {
    if (ev.repeat || (ev.key !== " " && ev.key !== "Enter")) return;
    ev.preventDefault();
    if (!secure()) { if (state === "idle") el.clip.click(); return; }
    if (state === "recording") { tapMode = false; end(); } else if (state === "idle") { tapMode = true; pressAt = 0; begin(); }
  });
  el.native.addEventListener("click", function () { if (state === "idle") { prime(); el.clip.click(); } });
  el.clip.addEventListener("change", function () {            // the phone's own recorder returns a file: m4a, aac, 3gp, amr, webm, ogg, wav
    var f = this.files && this.files[0]; this.value = "";
    if (!f || state !== "idle") return;
    notice(null); upload(f, f.type || "application/octet-stream");
  });

  el.yes.addEventListener("click", function () { answer("yes"); });
  el.no.addEventListener("click", function () { answer("no"); });
  el.speak.addEventListener("click", function () { prime(); var m = muted; muted = false; speakText(lastSpoken || el.answer.textContent); muted = m; });
  el.mute.addEventListener("click", function () {
    muted = !muted; el.mute.setAttribute("aria-pressed", muted ? "true" : "false"); el.mute.textContent = t(muted ? "p.voice_off" : "p.voice_on");
    if (muted && window.speechSynthesis) speechSynthesis.cancel();
  });
  el.send.addEventListener("click", function () {
    var v = el.text.value.trim(); if (!v || state !== "idle") return;
    prime(); el.transcript.textContent = v; el.chip.textContent = t("p.typed"); el.text.value = ""; turn({ text: v });
  });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden && state === "recording") end();
    if (document.hidden && state === "idle") dropStream();
  });

  // ---- strings, theme, start -------------------------------------------------------------------------------------
  function apply() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i]").forEach(function (n) { n.textContent = t(n.getAttribute("data-i")); });
    document.querySelectorAll("[data-ph]").forEach(function (n) { n.setAttribute("placeholder", t(n.getAttribute("data-ph"))); });
    document.title = t("p.title"); paint();
    el.status.textContent = t(statusKey); if (noticeKey) el.notice.textContent = t(noticeKey);
    el.mute.textContent = t(muted ? "p.voice_off" : "p.voice_on");
  }
  Object.keys(LANGS).forEach(function (c) { var o = document.createElement("option"); o.value = c; o.textContent = LANGS[c]; el.lang.append(o); });
  el.lang.value = lang; el.lang.parentNode.hidden = Object.keys(LANGS).length < 2;
  el.lang.onchange = function () { lang = el.lang.value; try { localStorage.setItem("clearwake-lang", lang); } catch (e) {} apply(); };
  var themeBtn = $("theme"), root = document.documentElement;
  try { var th = localStorage.getItem("clearwake-theme"); if (th === "light" || th === "dark") root.setAttribute("data-theme", th); } catch (e) {}
  function themeNow() { return root.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); }
  function themePaint() { themeBtn.textContent = t(themeNow() === "light" ? "p.theme_dark" : "p.theme_light"); }
  themeBtn.addEventListener("click", function () { var n = themeNow() === "light" ? "dark" : "light"; root.setAttribute("data-theme", n); try { localStorage.setItem("clearwake-theme", n); } catch (e) {} themePaint(); });

  statusKey = secure() ? "p.ready" : "p.ready_native";
  apply(); themePaint();
  if (!secure()) { notice("p.insecure"); }
  el.native.hidden = !secure();                                  // on plain http the big button already is the phone recorder
  api("status", null).then(function (s) { if (s && s.stt === false) { notice("p.no_stt"); el.typed.open = true; } })
    .catch(function (e) { notice(e.status === 403 ? "p.invalid" : "p.unreachable"); });
})();
