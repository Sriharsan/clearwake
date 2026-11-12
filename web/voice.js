// Clearwake voice page. Records on this device, sends the audio to this laptop's own server for local Whisper,
// Speech to text order: Sarvam Saaras (when the server has the key), then local Whisper, then the browser's own speech (voice_hosted.js), and typing.
// Replies are spoken by Sarvam Bulbul from audio the server caches; without it the browser's own speech synthesis reads them.
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var MAX_SECONDS = 28, MIN_MS = 600, HOLD_MS = 450;
  var el = {
    mic: $("mic"), word: $("mic-word"), status: $("status"), level: $("level"), timer: $("timer"), notice: $("notice"),
    chip: $("heard-chip"), transcript: $("transcript"), readCard: $("readback-card"), readback: $("readback"), yes: $("yes"), no: $("no"),
    answer: $("answer"), meta: $("meta"), speak: $("speak"), mute: $("mute"), typed: $("typed"), text: $("text"), send: $("send"),
    owner: $("owner"), ownerPlayer: $("owner-player"), ownerLabel: $("owner-label"), ownerAudio: $("owner-audio"),
    replyPlayer: $("reply-player"), replyLabel: $("reply-label"), replyAudio: $("reply-audio"), budget: $("budget")
  };
  var OWNER_LABEL = "Owner's voice: Sarvam Bulbul", REPLY_LABEL = "Clearwake's voice: Sarvam Bulbul";
  var sarvamOn = false;
  var csrf = "", token = "", lastSpoken = "", muted = false;
  var state = "idle";                      // idle, recording, sending
  var stream = null, recorder = null, chunks = [], stopTimer = null, tick = null, startedAt = 0, pressAt = 0, tapMode = false;
  var audioCtx = null, analyser = null, meterFrame = 0, releaseTimer = null, mime = "";

  function say(message) { el.status.textContent = message; }
  function notice(message) { el.notice.textContent = message; el.notice.hidden = !message; }

  // ---- session -------------------------------------------------------------------------------------------------
  function session() {
    return fetch("/console/api/session", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (j) { csrf = j.csrf; });
  }
  function post(path, body, raw, type, extra) {
    var headers = { "X-Clearwake-CSRF": csrf };
    if (!raw) headers["Content-Type"] = "application/json";
    else if (type) headers["Content-Type"] = type;
    if (extra) for (var k in extra) headers[k] = extra[k];
    return fetch(path, { method: "POST", credentials: "same-origin", headers: headers, body: raw ? body : JSON.stringify(body) }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error(j.error || "The request failed."); e.status = r.status; throw e; }
        return j;
      });
    });
  }

  // ---- speech out (the device's own voices) --------------------------------------------------------------------
  function pickVoice() {
    var list = window.speechSynthesis ? speechSynthesis.getVoices() : [];
    var english = list.filter(function (v) { return /^en[-_]/i.test(v.lang); });
    var local = english.filter(function (v) { return v.localService; });
    return local[0] || english[0] || null;
  }
  function speakText(text) {
    lastSpoken = text;
    if (muted || !text || !window.speechSynthesis) return;
    try {
      speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(text), v = pickVoice();
      if (v) { u.voice = v; u.lang = v.lang; } else { u.lang = "en-US"; }
      u.rate = 1;
      speechSynthesis.speak(u);
    } catch (e) { /* the text is on screen either way */ }
  }
  function primeSpeech() {            // some phone browsers allow speech only after a tap: say nothing once, inside the tap
    try { if (window.speechSynthesis && !primeSpeech.done) { primeSpeech.done = true; var u = new SpeechSynthesisUtterance(" "); u.volume = 0; speechSynthesis.speak(u); } } catch (e) {}
  }

  function paintBudget(u) {
    if (!u) return;
    el.budget.textContent = "Sarvam used so far: " + u.tts_chars + " of " + u.tts_chars_cap + " characters spoken, " + u.stt_seconds + " of " + u.stt_seconds_cap + " seconds heard, " + u.calls + " requests.";
    el.budget.hidden = false;
  }
  function refreshBudget() {
    if (!sarvamOn) return;
    fetch("/console/api/voice/status", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (s) { paintBudget(s.sarvam); }).catch(function () {});
  }

  // ---- Sarvam audio: the label shows whenever that voice plays ----------------------------------------------------
  function wirePlayer(audio, label, text) {
    audio.addEventListener("play", function () { label.textContent = text; label.hidden = false; });
  }
  wirePlayer(el.ownerAudio, el.ownerLabel, OWNER_LABEL);
  wirePlayer(el.replyAudio, el.replyLabel, REPLY_LABEL);
  function playClip(audio, player, url, autoplay) {
    return new Promise(function (resolve) {
      audio.pause();
      player.hidden = false;
      audio.src = url;
      var done = function () { audio.removeEventListener("ended", done); audio.removeEventListener("error", done); resolve(); };
      audio.addEventListener("ended", done); audio.addEventListener("error", done);
      if (!autoplay) { resolve(); return; }
      var p = audio.play();
      if (p && p.catch) p.catch(function () { resolve(); });      // blocked by the browser: the player and its button are on screen
    });
  }

  // ---- showing a turn ------------------------------------------------------------------------------------------
  function show(turn) {
    if (turn.transcript) el.transcript.textContent = turn.transcript;
    el.answer.textContent = turn.text;
    var bits = [];
    if (turn.intent && turn.intent !== "yes" && turn.intent !== "no") bits.push("Understood as: " + turn.intent.replace("_", " "));
    if (turn.source === "voice") bits.push("source: voice");
    if (turn.source_record && turn.source_record.stt) bits.push("speech to text: " + turn.source_record.stt);
    if (turn.heard) bits.push("read as: " + turn.heard);
    if (turn.policy_hash) bits.push("policy " + turn.policy_hash.slice(0, 12));
    if (turn.transcript_sha256) bits.push("transcript " + turn.transcript_sha256.slice(0, 12));
    el.meta.textContent = bits.join(" | ");
    token = turn.needs_confirm ? turn.token : "";
    el.readCard.hidden = !turn.needs_confirm;
    if (turn.needs_confirm) { el.readback.textContent = turn.text; el.yes.disabled = el.no.disabled = false; el.yes.focus({ preventScroll: false }); }
    if (turn.reply_audio) { lastSpoken = turn.text; if (!muted) playClip(el.replyAudio, el.replyPlayer, turn.reply_audio, true); else playClip(el.replyAudio, el.replyPlayer, turn.reply_audio, false); }
    else { if (turn.voice_note) el.meta.textContent += (el.meta.textContent ? " | " : "") + turn.voice_note; speakText(turn.text); }
  }
  function turn(body) {
    state = "sending"; paint();
    say("Working on it.");
    return post("/console/api/voice/turn", body).then(function (t) { show(t); say(t.refused ? "Not done. See the answer." : "Done."); refreshBudget(); })
      .catch(function (e) { el.answer.textContent = e.message; say("That did not work."); })
      .then(function () { state = "idle"; paint(); });
  }
  function answer(choice) {
    if (!token) return;
    el.yes.disabled = el.no.disabled = true;
    state = "sending"; paint(); say(choice === "yes" ? "Confirming." : "Cancelling.");
    post("/console/api/voice/answer", { token: token, answer: choice }).then(function (t) { show(t); el.readCard.hidden = !t.needs_confirm; say("Done."); })
      .catch(function (e) { el.answer.textContent = e.message; say("That did not work."); el.yes.disabled = el.no.disabled = false; })
      .then(function () { state = "idle"; paint(); });
  }

  // ---- recording -----------------------------------------------------------------------------------------------
  function paint() {
    var rec = state === "recording";
    el.mic.classList.toggle("recording", rec);
    el.mic.classList.toggle("busy", state === "sending");
    el.mic.setAttribute("aria-pressed", rec ? "true" : "false");
    el.word.textContent = rec ? (tapMode ? "Tap to stop" : "Release to send") : state === "sending" ? "Working" : "Hold to talk";
  }
  function pickMime() {
    var options = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
    for (var i = 0; i < options.length; i++) if (MediaRecorder.isTypeSupported(options[i])) return options[i];
    return "";
  }
  function secure() {
    return window.isSecureContext && navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === "function" && window.MediaRecorder;
  }
  function getStream() {
    if (stream && stream.getTracks().some(function (t) { return t.readyState === "live"; })) return Promise.resolve(stream);
    return navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } }).then(function (s) { stream = s; return s; });
  }
  function releaseStreamSoon() {
    clearTimeout(releaseTimer);
    releaseTimer = setTimeout(function () { if (state !== "recording" && stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; stopMeter(); } }, 30000);
  }
  function startMeter(s) {
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      audioCtx = audioCtx || new Ctx();
      if (audioCtx.state === "suspended") audioCtx.resume();
      var src = audioCtx.createMediaStreamSource(s);
      analyser = audioCtx.createAnalyser(); analyser.fftSize = 1024; src.connect(analyser);
      var buf = new Uint8Array(analyser.fftSize);
      (function loop() {
        if (!analyser) return;
        analyser.getByteTimeDomainData(buf);
        var sum = 0; for (var i = 0; i < buf.length; i++) { var v = (buf[i] - 128) / 128; sum += v * v; }
        el.level.value = Math.min(1, Math.sqrt(sum / buf.length) * 4);
        meterFrame = requestAnimationFrame(loop);
      })();
    } catch (e) { /* the meter is optional */ }
  }
  function stopMeter() { analyser = null; cancelAnimationFrame(meterFrame); el.level.value = 0; }

  function begin() {
    if (state !== "idle") return;
    primeSpeech();
    if (!secure()) { notice("The microphone works only on an https address or on localhost. Open the https address printed on the laptop, or use Type instead below."); el.typed.open = true; return; }
    state = "recording"; paint(); say("Allow the microphone if your phone asks.");
    getStream().then(function (s) {
      if (state !== "recording") return;      // released before permission came back
      notice("");
      mime = pickMime();
      chunks = [];
      recorder = mime ? new MediaRecorder(s, { mimeType: mime }) : new MediaRecorder(s);
      recorder.ondataavailable = function (ev) { if (ev.data && ev.data.size) chunks.push(ev.data); };
      recorder.onstop = finish;
      recorder.start();
      startedAt = Date.now(); startMeter(s);
      say("Recording. Speak now.");
      tick = setInterval(function () { var sec = Math.floor((Date.now() - startedAt) / 1000); el.timer.textContent = Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0"); }, 250);
      stopTimer = setTimeout(end, MAX_SECONDS * 1000);
    }).catch(function (e) {
      state = "idle"; paint(); tapMode = false;
      if (e && (e.name === "NotAllowedError" || e.name === "SecurityError")) {
        notice("The microphone is blocked. Allow it for this page in the browser settings, then tap the button again. Or use Type instead below.");
      } else if (e && e.name === "NotFoundError") {
        notice("No microphone was found on this device. Use Type instead below.");
      } else { notice("The microphone could not start. Use Type instead below."); }
      say("No recording."); el.typed.open = true;
    });
  }
  function end() {
    if (state !== "recording") return;
    clearTimeout(stopTimer); clearInterval(tick); stopMeter();
    if (recorder && recorder.state !== "inactive") { recorder.stop(); } else { state = "idle"; paint(); }
  }
  function finish() {
    var ms = Date.now() - startedAt;
    var type = (recorder && recorder.mimeType) || mime || "";
    var blob = new Blob(chunks, { type: type || "application/octet-stream" });
    chunks = []; el.timer.textContent = "0:00"; releaseStreamSoon();
    if (ms < MIN_MS || blob.size < 800) { state = "idle"; paint(); say("That was too short. Hold the button while you speak."); return; }
    state = "sending"; paint(); say("Reading your voice on this laptop.");
    el.chip.textContent = "Reading the recording";
    var began = Date.now();
    post("/console/api/voice/transcribe", blob, true, blob.type, { "X-Clearwake-Seconds": (ms / 1000).toFixed(2) }).then(function (t) {
      el.transcript.textContent = t.transcript || "(nothing heard)";
      el.chip.textContent = t.stt === "sarvam saaras:v4"
        ? "Heard by Sarvam Saaras v4 in " + (t.ms / 1000).toFixed(1) + " s, " + t.audio_seconds.toFixed(1) + " s of audio"
        : "Heard in " + (t.ms / 1000).toFixed(1) + " s on this laptop, " + t.audio_seconds.toFixed(1) + " s of audio";
      if (!t.transcript) { state = "idle"; paint(); say("I heard nothing. Say it again, closer to the microphone."); return; }
      return turn({ transcript_id: t.transcript_id });
    }).catch(function (e) {
      el.chip.textContent = "Not read";
      notice(e.message + (e.status === 503 ? "" : " You can use Type instead below."));
      if (e.status === 503) el.typed.open = true;
      state = "idle"; paint(); say("No transcript.");
    });
  }

  // press and hold sends on release; a quick tap starts, and the next tap stops
  el.mic.addEventListener("pointerdown", function (ev) {
    ev.preventDefault();
    if (state === "recording" && tapMode) { tapMode = false; end(); return; }
    if (state !== "idle") return;
    pressAt = Date.now(); tapMode = false;
    try { el.mic.setPointerCapture(ev.pointerId); } catch (e) {}
    begin();
  });
  function release() {
    if (state !== "recording" || tapMode) return;
    if (Date.now() - pressAt < HOLD_MS) { tapMode = true; paint(); say("Recording. Tap the button again when you finish."); return; }
    end();
  }
  el.mic.addEventListener("pointerup", release);
  el.mic.addEventListener("pointercancel", function () { if (state === "recording" && !tapMode) end(); });
  el.mic.addEventListener("contextmenu", function (ev) { ev.preventDefault(); });
  el.mic.addEventListener("keydown", function (ev) {       // keyboard: Space or Enter starts, the same key stops
    if (ev.repeat || (ev.key !== " " && ev.key !== "Enter")) return;
    ev.preventDefault();
    if (state === "recording") { tapMode = false; end(); } else if (state === "idle") { tapMode = true; pressAt = 0; begin(); }
  });
  el.mic.addEventListener("keyup", function (ev) { if (ev.key === " " || ev.key === "Enter") ev.preventDefault(); });

  el.yes.addEventListener("click", function () { answer("yes"); });
  el.no.addEventListener("click", function () { answer("no"); });
  function owner() {
    if (state !== "idle") return;
    var line = el.text.value.trim();
    state = "sending"; paint(); el.owner.disabled = true; notice("");
    say("The owner's voice is being made.");
    el.chip.textContent = "Owner's voice";
    post("/console/api/voice/owner", line ? { text: line } : {}).then(function (t) {
      el.transcript.textContent = "";
      say("The owner is speaking.");
      return playClip(el.ownerAudio, el.ownerPlayer, t.owner_audio, true).then(function () {
        el.transcript.textContent = t.transcript || "(nothing heard)";
        el.chip.textContent = "Heard by Sarvam Saaras v4 in " + (t.ms / 1000).toFixed(1) + " s, " + t.audio_seconds.toFixed(1) + " s of audio";
        if (!t.transcript) { say("Nothing was heard."); return; }
        return turn({ transcript_id: t.transcript_id });
      });
    }).catch(function (e) { notice(e.message); say("No owner command."); el.typed.open = true; })
      .then(function () { el.owner.disabled = false; if (state !== "idle") { state = "idle"; paint(); } });
  }
  el.owner.addEventListener("click", owner);
  el.speak.addEventListener("click", function () {
    if (el.replyPlayer.hidden === false && el.replyAudio.src) { el.replyAudio.currentTime = 0; var pr = el.replyAudio.play(); if (pr && pr.catch) pr.catch(function () {}); return; }
    primeSpeech(); var t = lastSpoken || el.answer.textContent; var m = muted; muted = false; speakText(t); muted = m; });
  el.mute.addEventListener("click", function () {
    muted = !muted; el.mute.setAttribute("aria-pressed", muted ? "true" : "false"); el.mute.textContent = muted ? "Voice off" : "Voice on";
    if (muted) { el.replyAudio.pause(); el.ownerAudio.pause(); }
    if (muted && window.speechSynthesis) speechSynthesis.cancel();
  });
  el.send.addEventListener("click", function () {
    var value = el.text.value.trim();
    if (!value || state !== "idle") return;
    primeSpeech();
    el.transcript.textContent = value; el.chip.textContent = "Typed"; el.text.value = "";
    turn({ text: value });
  });
  el.text.addEventListener("keydown", function (ev) { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); el.send.click(); } });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden && state === "recording") end();
    if (document.hidden && stream && state === "idle") { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; stopMeter(); }
  });
  if (window.speechSynthesis && speechSynthesis.addEventListener) speechSynthesis.addEventListener("voiceschanged", function () {});



  // ---- hosted console only: this server has no speech model, so a separate file lets the browser read the speech ----
  function loadHostedSpeech() {
    var fail = function () { notice("This server has no speech model and this browser has none either, so use Type instead below. Everything else works the same."); el.typed.open = true; };
    var api = { el: el, label: $("label"), getState: function () { return state; }, setState: function (v) { state = v; },
                paint: paint, say: say, notice: notice, turn: turn };
    var sc = document.createElement("script");
    sc.src = "/voice_hosted.js";
    sc.onload = function () { if (!(typeof window.ClearwakeHostedSpeech === "function" && window.ClearwakeHostedSpeech(api))) fail(); };
    sc.onerror = fail;
    document.head.appendChild(sc);
  }

  // ---- start ---------------------------------------------------------------------------------------------------
  paint();
  if (!secure()) {
    notice(window.isSecureContext === false
      ? "The microphone works only on an https address or on localhost, and this page is not on one. Use Type instead below, or open the https address printed on the laptop."
      : "This browser cannot record audio. Use Type instead below.");
    el.typed.open = true;
    say("Typing is ready.");
  }
  session().then(function () { return fetch("/console/api/voice/status", { credentials: "same-origin" }).then(function (r) { return r.json(); }); })
    .then(function (s) {
      if (s && s.sarvam && s.sarvam.active) {
        sarvamOn = true; el.owner.hidden = false; $("label").textContent = s.label;
        paintBudget(s.sarvam);
      }
      if (s && s.stt === false) { loadHostedSpeech(); }
    })
    .catch(function () { notice("This page could not reach the console server."); });
})();
