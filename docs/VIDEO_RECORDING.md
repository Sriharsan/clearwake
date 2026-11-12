# Recording the video scenes

One command turns each scene of the video into one finished mp4. Sri speaks the narration in his own voice; the recorder adds none.

```
python scripts/record_scene.py --list
python scripts/record_scene.py --scene 07
python scripts/record_scene.py --scene 03 --base-url http://127.0.0.1:8820 --out "D:\paypal hackathon\video"
python scripts/record_scene.py --all
```

Output goes to `D:\paypal hackathon\video\` as `scene-<NN>-<slug>.mp4` (H.264 video, AAC audio, 1440 by 810, 25 frames a second) and one `timing.json`. The raw Playwright video and the sound event file of every scene stay in `video\_work\scene-<NN>\`, so a scene can be muxed again without recording it. The `voices` folder is never touched.

## What a recording is

* Chromium through Playwright, video 1440 pixels wide. The page is zoomed to 125 percent with CSS zoom, so it lays out about 1152 pixels wide and fills the whole frame.
* A visible cursor drawn in the page follows every mouse move and shows a ripple on each click. Mouse moves follow a gentle curve with easing, scrolls ease in and out, and every scene waits for the page to settle before the first frame (`rec.begin()`). Everything before `begin()` is cut away.
* The recorder holds the last frame until the scene reaches its slot in the script, so each clip is as long as its window (0:00 to 0:12, 0:12 to 0:25, and so on).
* Site scenes run against a local clean URL server over `site/` (the same pages Vercel serves). Console scenes expect `python -m clearwake --port 8810`. Pass `--base-url` to use another host, for example `https://clearwake-mu.vercel.app`.

## Sound

Playwright video has no audio, so sound is an event timeline.

1. The page is watched for audio: every `play()` call and `play` event of an audio element, and every Web Audio buffer source (with the url of the file it decoded). Each event keeps the src, the start offset, the volume and the video time. A sound the product plays outside the page is logged with `rec.add_audio(path)`.
2. After the scene, `scripts/mux_audio.py` finds the cached WAV file for each event (`data/voice-cache`, then `site`, `web`, `data`), places it at its time with ffmpeg `adelay`, mixes with `amix`, pads to the clip length and muxes one mp4. A scene with no sound gets a silent AAC track, so every clip has the same streams.
3. Muxing again by hand: `python scripts/mux_audio.py --video raw.webm --timeline raw.events.json --out scene.mp4`.

Nothing is downloaded and no network call is made. The recorder never calls Sarvam and never writes to the PayPal sandbox. The voice files it needs are cached WAV files made before the recording.

## timing.json

For each scene: its slot in the script (`start`, `end`, `script_window`), the recorded `duration`, the `audio_events` with their video time and file, any `audio_events_skipped` (a sound with no local file), the tag and caption, and the `narration` slot with the line Sri says. Recording a scene again replaces its entry only.

## The scenes

| No | Window | Scene | Page |
| --- | --- | --- | --- |
| 01 | 0:00 to 0:12 | The real result, case 3 | Control Room, case 3 card |
| 02 | 0:12 to 0:25 | The claim, then the bad outcome | Break it, unguarded side |
| 03 | 0:25 to 0:40 | The same action, stopped | Break it, guarded side and receipts |
| 04 | 0:40 to 1:00 | Rules said once, by voice | Stub for the voice agent |
| 05 | 1:00 to 1:30 | Anatomy, one dispute, six layers | Proof, explode, case 3 bead, layer switch |
| 06 | 1:30 to 1:48 | The two agents settle it | Stub for the voice agent |
| 07 | 1:48 to 2:03 | Check it | Home, Verify the signed logs |
| 08 | 2:03 to 2:33 | All ten cases counted | Control Room, tally, cases, ledger |
| 09 | 2:33 to 2:55 | End card | `video/endcard.html`, numbers from `site/data/totals.json` |

The stubs in `video/scenes.py` carry the signature, the window and a TODO with the steps. The recorder refuses to run a stub.

## Tests

`python -m pytest -q tests/test_record_scene.py` records a 3 second scene of a local page, checks the mp4 with ffprobe (duration, width 1440, H.264, AAC) and checks that a generated test WAV lands at the right time. Localhost only.
