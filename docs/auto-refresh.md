# Daily quota refresh

## Background

The Codex 5-hour quota window is a **sliding** window: it starts ticking
from the first request you make in a given period. If you don't touch
an account on a particular day, the window never opens — and the daily
allotment for that account silently goes to waste.

`codex-accounts refresh` walks through every saved account, checks the 5h
window state via the private quota endpoint, and — for any account that
hasn't used the window yet — fires a single low-cost request to start
the timer.

```bash
codex-accounts refresh [--delay SECONDS] [--dry-run]
```

| Account state | Action |
|---|---|
| 5h window cold (0% used) | Send one minimal request to open it |
| 5h window already open (> 0% used) | Skip |
| Token expired / `auth.json` missing | Skip with a warning |

`--delay` (default `30`) controls the gap between consecutive accounts.
For scheduled jobs, pick something more cautious — see the warnings
section below.

`--dry-run` lists what *would* happen without making any network
requests. Use it the first time you set up the cron job.

## Anti-abuse warnings — read first

`refresh` makes real API calls against `chatgpt.com/backend-api/codex/responses`,
the same endpoint the Codex client uses for inference. Some
considerations:

- **One request per account** is all this command sends, and the model
  used (`codex-mini-latest`) is the cheapest variant available. Token
  consumption per refresh is on the order of a few dozen tokens.
- All requests originate from your machine and your IP. Running this
  across many accounts in rapid succession from the same network is
  exactly the kind of pattern that abuse systems flag. **Use a generous
  `--delay`.** For automated cron jobs, `--delay 600` (10 minutes
  between accounts) is the recommended starting point.
- Codex's Terms of Service apply. This tool is provided as-is and
  comes with no guarantee that automated quota probing is acceptable
  use. If your account is suspended, that is between you and OpenAI.

## macOS LaunchAgent

A ready-to-customise LaunchAgent template lives at
[`packaging/com.codex-accounts.refresh.plist`](../packaging/com.codex-accounts.refresh.plist).
Edit the `__USER__` and `__BIN__` placeholders, then install with the
helper script:

```bash
./scripts/install-launchagent.sh
```

This installs the plist to `~/Library/LaunchAgents/` and bootstraps it
under `gui/$(id -u)/`. macOS's `StartCalendarInterval` has a useful
property: if the machine is asleep or off at the scheduled time, the
job runs as soon as it next wakes / boots, rather than being skipped
(which is how `cron` would behave).

### Verifying

```bash
launchctl list | grep codex-accounts.refresh
# expected (PID column may be "-" when idle):
#   -    0    com.codex-accounts.refresh

launchctl kickstart -k gui/$(id -u)/com.codex-accounts.refresh   # manual trigger
cat /tmp/codex-accounts-refresh.log
```

### Changing the schedule

Edit `~/Library/LaunchAgents/com.codex-accounts.refresh.plist`, then:

```bash
launchctl bootout   gui/$(id -u)/com.codex-accounts.refresh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.codex-accounts.refresh.plist
```

### Uninstalling

```bash
launchctl bootout gui/$(id -u)/com.codex-accounts.refresh
rm ~/Library/LaunchAgents/com.codex-accounts.refresh.plist
```

## Linux: systemd timer

The same effect on Linux is best achieved with a systemd user timer.
There is no canned unit file in the repo yet (PRs welcome); a minimal
example:

```ini
# ~/.config/systemd/user/codex-accounts-refresh.service
[Unit]
Description=Open the daily Codex 5h window across all accounts

[Service]
Type=oneshot
ExecStart=%h/.local/bin/codex-accounts refresh --delay 600

# ~/.config/systemd/user/codex-accounts-refresh.timer
[Unit]
Description=Daily codex-accounts refresh

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true
Unit=codex-accounts-refresh.service

[Install]
WantedBy=timers.target
```

Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now codex-accounts-refresh.timer
```

`Persistent=true` is the systemd analogue of the macOS catch-up
behaviour.

## Reading the log

Sample output from a healthy run:

```
refreshing 5h window for 3 account(s)…

  open  work:     5h window cold, activating…
✓         work:     window opened
          sleeping 600s before next account…
  ok    personal: already active (12% used)
  open  research: 5h window cold, activating…
✓         research: window opened

  activated=2  skipped=1  errors=0
```

If `errors > 0`, the most common causes are expired tokens (the only
fix is `codex-accounts use <name>` → re-login → `codex-accounts save <name>`)
or network issues / OpenAI returning a non-2xx response.
