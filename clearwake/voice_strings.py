"""Every word the phone voice page shows, in one table, like Relayloom's strings.json.

LANGUAGES lists the languages offered. Only English is in the table now. To add one, add its code to LANGUAGES and a value under
that code for each key: the page falls back to English for any key a language does not have yet. A {name} in a string is filled
by the page. Answers composed by clearwake/voice.py (the read back and the dispute summary) are English text made by code.
"""
LANGUAGES = {"en": "English"}


def _s(en):
    return {"en": en}


STRINGS = {
    "p.title": _s("Clearwake voice"),
    "p.label": _s("Speech is read on the laptop. Nothing goes to a cloud service."),
    "p.language": _s("Language"),
    "p.theme_light": _s("Light"),
    "p.theme_dark": _s("Dark"),
    "p.ready": _s("Ready. Hold the button and speak, or tap once to start and tap again to stop."),
    "p.ready_native": _s("Ready. Tap the button, record your sentence with the phone recorder, then save it."),
    "p.hold": _s("Hold to talk"),
    "p.record_native": _s("Record"),
    "p.tap_stop": _s("Tap to stop"),
    "p.release": _s("Release to send"),
    "p.working": _s("Working"),
    "p.allow_mic": _s("Allow the microphone if your phone asks."),
    "p.recording": _s("Recording. Speak now."),
    "p.recording_tap": _s("Recording. Tap the button again when you finish."),
    "p.too_short": _s("That was too short. Hold the button while you speak."),
    "p.reading": _s("Reading your voice on this laptop."),
    "p.sending_clip": _s("Sending {kb} KB to this laptop."),
    "p.heard_in": _s("Heard in {s} s on this laptop, {a} s of audio"),
    "p.not_read": _s("Not read"),
    "p.typed": _s("Typed"),
    "p.no_recording": _s("No recording yet"),
    "p.nothing_heard": _s("I heard nothing. Try again closer to the microphone."),
    "p.said_h": _s("You said"),
    "p.said_empty": _s("Your words appear here."),
    "p.read_h": _s("Read back"),
    "p.also_say": _s("You can also say yes or no."),
    "p.yes": _s("Yes"),
    "p.no": _s("No"),
    "p.answer_h": _s("Answer"),
    "p.answer_empty": _s("The spoken answer appears here, word for word."),
    "p.speak_again": _s("Speak again"),
    "p.voice_on": _s("Voice on"),
    "p.voice_off": _s("Voice off"),
    "p.record_phone": _s("Use my phone's recorder"),
    "p.type_h": _s("Type instead"),
    "p.type_label": _s("Type what you would say"),
    "p.type_ph": _s("What happened with my disputes today?"),
    "p.send": _s("Send"),
    "p.tips_h": _s("What you can say"),
    "p.tip_rules": _s("Set rules: Refund anything under $30 that has not arrived in 10 days. Ask me above that. Never refund twice."),
    "p.tip_ask": _s("Ask: What happened with my disputes today?"),
    "p.tip_approve": _s("Approve: Approve the sixty four dollar one."),
    "p.tip_note": _s("A voice command never moves money by itself. Rules and approvals wait for your yes."),
    "p.working_on": _s("Working on it."),
    "p.done": _s("Done."),
    "p.not_done": _s("Not done. See the answer."),
    "p.confirming": _s("Confirming."),
    "p.cancelling": _s("Cancelling."),
    "p.failed": _s("That did not work."),
    "p.no_transcript": _s("No transcript."),
    "p.understood": _s("Understood as: {intent}"),
    "p.invalid": _s("This link is not valid. Scan the code on the laptop again."),
    "p.unreachable": _s("This page could not reach the laptop."),
    "p.no_stt": _s("Speech to text is not installed on this laptop, so use Type instead below. Everything else works the same."),
    "p.insecure": _s("This page is on plain http, so the phone's own recorder is used: tap Record, speak, save, and the clip comes here. For the in page microphone, start the laptop with --phone --tls."),
    "p.mic_blocked": _s("The microphone is blocked. Allow it for this page in the browser settings, or use my phone's recorder, or type below."),
    "p.mic_none": _s("No microphone was found on this device. Use the phone's recorder or type below."),
    "p.mic_failed": _s("The microphone could not start. Use the phone's recorder or type below."),
    "p.too_big": _s("That recording is over 5 MB. Keep it under 30 seconds."),
}
