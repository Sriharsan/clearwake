// Clearwake voice page, hosted console only. The server has no speech model here, so the browser reads the speech.
// Chrome does this with its own speech service. The laptop page (voice.js) never uses it and stays on local Whisper.
(function () {
  "use strict";
  window.ClearwakeHostedSpeech = function (api) {
    var Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Rec) return false;
    var el = api.el, rec = null, heard = "", live = false;
    if (api.label) api.label.textContent = "Voice rules. Your browser reads the speech and the console reads it back before anything is signed. No PayPal call is made on this page.";
    api.notice("This server has no speech model, so your browser reads the speech. Hold the button and speak. Chrome sends the audio to its own speech service for this step.");
    function stop() { if (rec && live) { try { rec.stop(); } catch (e) {} } }
    el.mic.addEventListener("pointerdown", function (ev) {
      ev.stopImmediatePropagation(); ev.preventDefault();
      if (api.getState() !== "idle") return;
      heard = ""; live = true; api.setState("recording"); api.paint(); api.say("Listening. Speak your rule.");
      rec = new Rec(); rec.lang = "en-US"; rec.interimResults = true; rec.continuous = false;
      rec.onresult = function (e) { var t = ""; for (var i = 0; i < e.results.length; i++) t += e.results[i][0].transcript; heard = t; el.transcript.textContent = t; };
      rec.onerror = function () { live = false; api.setState("idle"); api.paint(); api.say("I heard nothing. Say it again, or use Type instead below."); };
      rec.onend = function () {
        live = false;
        if (!heard.trim()) { if (api.getState() === "recording") { api.setState("idle"); api.paint(); api.say("I heard nothing. Say it again, closer to the microphone."); } return; }
        el.chip.textContent = "Heard"; api.turn({ text: heard.trim() });
      };
      try { rec.start(); } catch (e) { live = false; api.setState("idle"); api.paint(); }
    }, true);
    el.mic.addEventListener("pointerup", function (ev) { ev.stopImmediatePropagation(); stop(); }, true);
    el.mic.addEventListener("pointercancel", function (ev) { ev.stopImmediatePropagation(); stop(); }, true);
    return true;
  };
})();
