# Voice for the merchant

Speak to Clearwake from a phone or the laptop. Speech to text runs on the laptop with local Whisper. Speech out uses the
voices already on the device. No cloud speech service is used anywhere: not Chrome's `webkitSpeechRecognition`, not a
hosted API.

## What it does

| You say | Clearwake does |
| --- | --- |
| "Refund anything under $30 that hasn't arrived in 10 days. Ask me above that. Never refund twice." | Turns it into rules with `clearwake/rules_nl.py`, reads them back in plain words (shown and spoken), waits for your yes. Yes signs the same policy a typed sentence signs, with `source=voice` and the SHA-256 of the transcript in the receipt. No cancels. |
| "What happened with my disputes today?" | Answers in two or three short sentences composed by code from the dispute ledger, the case list and the approval store. No model writes the answer. The text on screen is the text spoken. |
| "Approve the sixty four dollar one." | Finds the waiting approval, checks the signed policy allows that step, reads it back, and on yes uses the same approval the console button uses (`Console.approve`). The receipt `clearwake.voice.approval` carries `source=voice` and the transcript hash. If the policy does not allow it, it says why and approves nothing. |

A voice command alone never moves money. Rules and approvals wait for a spoken or tapped yes. An approval is checked
against the signed policy twice: at the read back and again at the yes.

Which of the three you meant is decided by code: a fixed matcher first. A local model may classify only when the matcher
fails, and its answer must be one of the fixed intents (`set_rules`, `ask`, `approve`) or it counts as unclear.

Raw audio is never stored. It goes through a temporary folder that is deleted when the transcript is made. Receipts hold
only the audio SHA-256, the transcript SHA-256, the length and the time taken.

## Phone steps

Phone mode works like Relayloom's phone alerts: a separate small server on the laptop's private LAN address, a random token in the
link, and a QR code. The main console stays on loopback. The phone server exposes only the voice page, transcribe, turn and answer,
and every request needs the token (compared in constant time).

1. Put the laptop and the phone on the same Wi-Fi.
2. On the laptop, in the repo folder, run `python -m clearwake --phone --tls` (https, the in page microphone) or `python -m clearwake --phone` (plain http, the phone's own recorder).
3. Scan the QR code with the phone camera, or type the printed link. The QR code needs `segno`; if it is missing the link is printed and the window says how to install it.
4. With `--tls` the phone shows a one time certificate warning because the certificate is made on the laptop (`data/voice-tls/`, git ignored). Choose Advanced, then Proceed. (Android Chrome: Advanced, Proceed. iPhone Safari: Show Details, visit this website.)
5. Allow the microphone when the phone asks. Hold the big button while you speak and let go to send, or tap once to start and tap again to stop.
6. Plain http (no `--tls`): browsers block the in page microphone off https, so the page switches by itself to the phone's own recorder. Tap Record, the phone's recorder opens, speak, save, and the clip uploads. m4a, aac, 3gp, amr, webm, ogg, wav and mp3 all work: ffmpeg turns them into 16 kHz wav for Whisper.
7. The transcript, the read back with big Yes and No buttons, and the spoken answer appear in large type. The phone's own voice reads them aloud. If speech to text is not installed, or both recording paths fail, the "Type instead" box does the same job.

The laptop loads the Whisper model when the server starts, runs one tiny warm-up transcription, and prints "Speech model ready" only after that. Wait for that line before the first sentence.
Stop with Ctrl+C. Windows may ask once to allow Python on private networks: allow private only. The server binds the private LAN
address only, never `0.0.0.0`. Ports: phone 8863 (`--phone-port`), console 8810 on loopback (`--port`).

`python -m clearwake --voice-lan` (CLEARWAKE_VOICE_LAN=1) is the earlier https mode that served the whole console over the LAN with cookie and CSRF. Prefer `--phone`.

The loopback page `/voice` on the console (cookie and CSRF, files `web/voice.*`) remains for the laptop.

Words on the page live in one table, `clearwake/voice_strings.py` (English now). Tamil and Hindi can be added there later by adding a language code and a value per key.

## Files

- `clearwake/voice.py`: transcription, intent matcher, answers, rules and approvals by voice, HTTP blocks.
- `clearwake/voice_phone.py`, `web/voice_phone.js`, `clearwake/voice_strings.py`: phone mode (token, QR, https option, native recorder path).
- `clearwake/voice_lan.py`, `scripts/voice_lan.py`: certificate helpers and the earlier whole console https mode.
- `web/voice.html`, `web/voice.js`, `web/voice.css`: the phone page (no inline script or style).
- `tests/test_voice.py`, `tests/fixtures/voice/`: tests and spoken clips (made with Windows SAPI by `scripts/make_voice_fixtures.ps1`).
- `scripts/voice_bench.py`: measures word error and time, writes `data/runs/voice-<timestamp>.json`.

## Routes

All need the console cookie and CSRF token, like every console write. In hosted mode they are rate limited per address.

- `GET /voice`: the page.
- `GET /console/api/voice/status`: whether speech to text is installed.
- `POST /console/api/voice/transcribe`: audio body (webm, ogg, mp4, wav, mp3, flac), at most 5 MB and 30 seconds. Returns `transcript`, `ms`, `audio_sha256`, `transcript_id`.
- `POST /console/api/voice/turn`: `{transcript_id}` or `{text}`. The server keeps the transcript, so the client cannot claim a voice source for typed text.
- `POST /console/api/voice/answer`: `{token, answer: "yes"|"no"}` for the buttons.

## Setup

- Model folder: `D:\my startup\_whisper\small.en` (or set `CLEARWAKE_WHISPER_DIR`). It must contain `model.bin`. Nothing is downloaded at run time.
- ffmpeg on the path, or set `CLEARWAKE_FFMPEG`. The WinGet install is found automatically.
- `faster-whisper` 1.2.1, int8, CPU.

## Measured

See the newest `data/runs/voice-*.json`. Label: local run on this laptop CPU. The clips are Windows SAPI speech, so a person on a phone
microphone will differ.
