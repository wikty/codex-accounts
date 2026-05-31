# FAQ

### Is this affiliated with OpenAI?

No. `codex-accounts` is an independent community project. It works
against the local files the official Codex desktop app writes; it does
not modify the app itself, and it is not endorsed by OpenAI.

### What gets stored in `~/.codex-accounts/`?

Per account, a snapshot of selected files from `~/.codex/`:

- `auth.json` — the OAuth token bundle.
- (FULL mode only) `state_*.sqlite`, `logs_*.sqlite`,
  `session_index.jsonl`, `.codex-global-state.json`, and the
  `sessions/`, `archived_sessions/`, `shell_snapshots/` directories.

Plus a `meta.json` with codex-accounts's own bookkeeping (notes, last-used
timestamp). Nothing else.

The full list lives in
[`src/codex_switch/config.py`](../src/codex_switch/config.py).

### Why not just use multiple OS users?

You can — and if you have strict separation needs (e.g. work vs.
personal on a corporate device), that's a better answer. `codex-accounts`
is designed for the much more common case where one human wants to
juggle several ChatGPT logins on one OS account, without losing chat
history when they switch.

### What's the difference between AUTH and FULL mode?

- **AUTH mode** (`use <name>` default) only swaps `auth.json`. All
  accounts share the same `state_*.sqlite`, so your session sidebar in
  Codex shows every conversation, regardless of which account is
  "active" at the moment.
- **FULL mode** (`use <name> --no-share-sessions`) additionally swaps
  the session DBs, log DBs, indices, and the `sessions/` etc.
  directories. Each account gets its own session sidebar.

Most users want AUTH. FULL mode is useful when you genuinely want to
hide work conversations from personal mode (or vice-versa).

### Does switching delete my chat history?

In AUTH mode, no — chat history is shared. In FULL mode, history is
moved to the snapshot for the *current* account before the target
account's history is loaded. As long as you `save` (or `use`, which
auto-saves) cleanly, nothing is lost.

### How does `quota` work?

It POSTs nothing — it issues a `GET` against
`https://chatgpt.com/backend-api/wham/usage` with your account's bearer
token, parses the response, and renders it. The endpoint is the same
one the Codex client's rate-limit progress bar uses internally.
Methodology is documented in
[`docs/internals/codex-app-internals.md`](./internals/codex-app-internals.md).

### How does `refresh` work, and is it safe?

`refresh` sends a single tiny streaming request per account, using the
cheapest available model, to start the 5-hour rate-limit window. The
goal is to ensure your daily quota isn't wasted by a window that never
opened.

**Safety:** these are real API calls and they consume a handful of
tokens. Read [`docs/auto-refresh.md`](./auto-refresh.md) before
enabling the cron job, and pick a generous `--delay` for scheduled runs.

### Why is the account name `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`?

Names are used as directory components, so anything that could traverse
the filesystem (`..`, `/`, leading dots) or break shell parsing
(spaces, newlines, glob characters) is forbidden. The 64-character cap
matches POSIX `NAME_MAX` on most filesystems with margin.

### Can I sync `~/.codex-accounts/` across machines (Dropbox / iCloud / git)?

You **can**, but treat the directory as you would `~/.ssh/`: it
contains plaintext credentials. Specifically:

- Never commit it to a public repository.
- If you sync via cloud, prefer providers that offer at-rest
  encryption you control.
- Keep the directory mode at `0700`; codex-accounts enforces this on
  creation but cloud sync clients can override.

### Codex updated and now `quota` is broken. What do I do?

Run `codex-accounts doctor` to confirm everything else is OK, then file
a bug with the doctor output. The integration is built around private
endpoints; OpenAI bumping a path is the most likely cause. The
methodology to re-discover the new path is in
[`docs/internals/codex-app-internals.md`](./internals/codex-app-internals.md).

### Why isn't there a Windows build?

Two reasons: (1) the macOS-focused process detection in
`is_codex_running()` would need an alternative, and (2) the install
flows (LaunchAgent, completions) are Unix-shaped. The Python code
itself is portable — a PR adding Windows support is welcome.

### Where is `codex-accounts` installed?

`pipx install codex-accounts` puts the entry point in
`~/.local/bin/codex-accounts` (or `~/Library/Python/.../bin/codex-accounts`
for `pip --user`). Run `which codex-accounts` to confirm.

### How do I uninstall it cleanly?

```bash
pipx uninstall codex-accounts     # or: pip uninstall codex-accounts
rm -rf ~/.codex-accounts        # removes all snapshots
# optional: remove the LaunchAgent if you installed it
launchctl bootout gui/$(id -u)/com.codex-accounts.refresh
rm -f ~/Library/LaunchAgents/com.codex-accounts.refresh.plist
```

`~/.codex/` (the live Codex client home) is **not** touched.
