# Keep the hosted console awake

Render's free plan puts a service to sleep after 15 minutes without a request, and the next request waits for a cold start. Judges open the console at unknown hours, so two pingers keep it warm until the end of 2026. Both are free. Neither logs in, changes data or costs money.

## Pinger 1: GitHub Actions (already in the repository)

`.github/workflows/keepalive.yml` runs every 10 minutes:

* it calls `https://clearwake-console.onrender.com/healthz` (a tiny answer, `{"ok":true}`);
* in the first 10 minutes of each hour it also calls `/console`, so the page itself stays warm;
* a failed call never fails the run (the next run pings again);
* the first step checks the date and the job does nothing after 31 December 2026;
* `workflow_dispatch` is on, so Sri can start it by hand from the Actions tab (Keep the console warm, Run workflow).

GitHub can start a scheduled run late, and on a repository with no pushes for 60 days it can switch schedules off. That is why there is a second pinger.

## Pinger 2: UptimeRobot, every 5 minutes (Sri does this, about 3 minutes)

I did not create an account. These are the exact steps:

1. Open https://uptimerobot.com and choose Register for free. Sign up with email or Google. Choose the free plan (50 monitors, 5 minute interval). No card is asked for on the free plan; if a page asks for payment details, stop.
2. In the dashboard press **+ New monitor**.
3. Monitor Type: **HTTP(s)**.
4. Friendly Name: `Clearwake console healthz`.
5. URL: `https://clearwake-console.onrender.com/healthz`
6. Monitoring Interval: **5 minutes**.
7. Under alert contacts keep your own email, or untick all alerts to avoid mail.
8. Press **Create Monitor**. The status turns Up within a minute. The response time column shows how long the service took; a first answer after a long sleep can be slow.
9. Optional second monitor with the same steps for `https://clearwake-console.onrender.com/console` at 5 minutes, named `Clearwake console page`.

Alternative if UptimeRobot is not wanted: https://cron-job.org, free account, Create cronjob, URL `https://clearwake-console.onrender.com/healthz`, schedule Every 5 minutes, save.

## Remove after the judging window

* GitHub: the workflow stops by itself after 31 December 2026. To stop it sooner, Actions, Keep the console warm, the three dots, Disable workflow.
* UptimeRobot: open the monitor, More actions, Pause or Delete.

## Check it worked

```sh
python scripts/check_warm.py
```

It requests `/healthz` and `/console` several times, records the first request after a warm request, asserts that it is under 5 seconds and saves the measurement to `data/runs/warm-<date>.json`. A cold start (first request after a long sleep) takes longer; the script prints that time too and does not count it against the 5 second limit.
