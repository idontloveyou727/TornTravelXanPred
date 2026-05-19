# YATA UK Item 206 Restock Monitor

Small Python background worker for Render. It polls the YATA travel export API, tracks item `206` in the UK, detects confirmed restocks when quantity changes from `0` to `>0`, normalizes delayed observations down to the previous 5-minute tick, predicts the next restock, and optionally sends Discord webhook notifications.

The worker stores observations, events, predictions, and notification state in SQLite so it can resume from the latest known quantity after a restart and avoid duplicate notifications.

## Environment

Create `.env` from the example:

```bash
cp .env.example .env
```

Required variables:

```bash
YATA_URL=https://yata.yt/api/v1/travel/export/
ITEM_ID=206
COUNTRY=UK
POLL_SECONDS=60
```

Optional variables:

```bash
DISCORD_WEBHOOK_URL=
DATABASE_PATH=./data/restock_tracker.sqlite3
PREDICTION_HISTORY_WINDOW=10
GITHUB_ACTIONS_DELAY_BUFFER_MINUTES=5
PING_LEAD_MINUTES=0
ENABLE_AIRSTRIP_PINGS=1
ENABLE_BUSINESS_CLASS_PINGS=1
DEFAULT_DEPLETION_RATE_PER_MINUTE=312.5
DEPLETION_RATE_HISTORY_WINDOW=20
MIN_DEPLETION_RATE_SAMPLE_SECONDS=90
DEPLETION_RATE_MIN_MULTIPLIER=0.25
DEPLETION_RATE_MAX_MULTIPLIER=1.75
LOG_LEVEL=INFO
```

`DISCORD_WEBHOOK_URL` can be empty. In that mode the worker logs the Discord message content instead of sending it.

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python monitor.py
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python monitor.py
```

Run tests:

```bash
pytest
```

Run one GitHub Actions-style check locally:

```bash
STATE_BACKEND=json STATE_PATH=./data/github_actions_state.json python monitor.py --once
```

## Render Deployment

This repository includes `render.yaml` for a Render Background Worker:

```yaml
services:
  - type: worker
    name: yata-restock-monitor
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: python monitor.py
```

Deployment steps:

1. Push this folder to GitHub.
2. In Render, create a new Blueprint from the repository, or create a Background Worker manually.
3. Use `pip install -r requirements.txt` as the build command.
4. Use `python monitor.py` as the start command.
5. Set environment variables in Render:

```bash
YATA_URL=https://yata.yt/api/v1/travel/export/
ITEM_ID=206
COUNTRY=UK
POLL_SECONDS=10
DISCORD_WEBHOOK_URL=<your webhook, optional>
```

For persistent SQLite state on Render, add a persistent disk and set:

```bash
DATABASE_PATH=/var/data/restock_tracker.sqlite3
```

Without a persistent disk, Render restarts may lose the local SQLite file. The worker will still run, but restart-safe duplicate prevention depends on persistent storage.

## Free GitHub Actions Deployment

This repository also supports a free GitHub Actions mode. Unlike Render, GitHub Actions does not run a continuous worker. The workflow runs every 5 minutes, performs one monitor check with `python monitor.py --once`, writes lightweight JSON state to `data/github_actions_state.json`, commits that state file if it changed, and exits.

Setup:

1. Open the GitHub repository.
2. Go to Settings.
3. Go to Secrets and variables -> Actions.
4. Add a repository secret named `DISCORD_WEBHOOK_URL`.
5. Paste a new Discord webhook as the value.

Do not commit a Discord webhook to GitHub. If an old webhook was ever shared publicly or committed anywhere, regenerate it in Discord before using this workflow.

The workflow file is `.github/workflows/monitor.yml`. It runs on the schedule `2/5 * * * *`, which means every 5 minutes with a small offset to reduce schedule congestion. It can also be run manually from Actions -> YATA Restock Monitor -> Run workflow.

GitHub scheduled workflows can be delayed or skipped during platform congestion. This mode is free and useful, but it is not true real-time monitoring.

Departure reminder timing is designed around those delays:

- Latest safe departure is calculated as `predicted restock - flight duration`.
- Recommended departure is shifted earlier by `GITHUB_ACTIONS_DELAY_BUFFER_MINUTES`.
- Ping time is `recommended departure - PING_LEAD_MINUTES`.
- Airstrip and Business Class departure pings can be enabled independently with `ENABLE_AIRSTRIP_PINGS` and `ENABLE_BUSINESS_CLASS_PINGS`.
- Ticks are now one minute, and reminder predictions anchor to the estimated depleted timestamp rather than the observed restock timestamp.
- Restock detected messages project the next cycle from the current positive observation's estimated depletion time, so their departure block stays future-facing.
- The default stock depletion rate is `312.5` units/minute, based on a 2500-unit restock selling out in 8 minutes. The monitor updates this from clean `>0 -> >0` quantity drops, ignores `0 -> >0` and `>0 -> 0` edges, requires at least `MIN_DEPLETION_RATE_SAMPLE_SECONDS`, and filters outliers before saving `depletion_rate_history`.

The default GitHub delay buffer is 5 minutes, so a latest safe departure of `00:07` becomes a recommended departure of `00:02`. With `PING_LEAD_MINUTES=0`, the ping is scheduled for `00:02`. If GitHub Actions runs a few minutes late, the notification still has a chance to arrive before the latest safe departure.

Workflow env example:

```yaml
GITHUB_ACTIONS_DELAY_BUFFER_MINUTES: "5"
PING_LEAD_MINUTES: "0"
ENABLE_AIRSTRIP_PINGS: "1"
ENABLE_BUSINESS_CLASS_PINGS: "1"
DEFAULT_DEPLETION_RATE_PER_MINUTE: "312.5"
DEPLETION_RATE_HISTORY_WINDOW: "20"
MIN_DEPLETION_RATE_SAMPLE_SECONDS: "90"
DEPLETION_RATE_MIN_MULTIPLIER: "0.25"
DEPLETION_RATE_MAX_MULTIPLIER: "1.75"
```

Suggested tuning:

- Normal: delay buffer 5, ping lead 0.
- Safer: delay buffer 10, ping lead 0.
- Very safe: delay buffer 10, ping lead 5.

Increasing these values reduces late pings, but it cannot guarantee real-time delivery if GitHub skips or heavily delays scheduled jobs.

## Behavior

- Fetch timeout is 15 seconds.
- API failures use retry/backoff and the next monitor loop continues instead of crashing permanently.
- `SIGTERM` and `SIGINT` trigger graceful shutdown, which is required for Render worker deploys and restarts.
- `python monitor.py --once` runs one check and exits for GitHub Actions.
- Restock detection only fires for `0 -> >0`.
- Restock timestamps are stored in UTC and normalized using floor-to-previous-5-minute logic, such as `12:07:12 -> 12:05:00`.
- Discord timestamps use `<t:UNIX:F>` and `<t:UNIX:R>` so Discord renders local time for each viewer.
- Discord `429` responses are handled by parsing `retry_after` or rate-limit headers; no fixed Discord rate limit is hard-coded.

## Ubuntu systemd Alternative

A systemd unit is included at `systemd/restock-tracker.service` for VM deployment outside Render.

```bash
sudo useradd --system --create-home restock
sudo mkdir -p /opt/restock-tracker
sudo chown -R restock:restock /opt/restock-tracker
sudo systemctl daemon-reload
sudo systemctl enable restock-tracker
sudo systemctl start restock-tracker
sudo journalctl -u restock-tracker -f
```
