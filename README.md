<!-- markdownlint-disable MD041 -->
<h1 align="center">codex-accounts</h1>

<p align="center">
  <em>A multi-account CLI manager for the OpenAI Codex desktop app.</em>
</p>

<p align="center">
  <a href="https://github.com/wikty/codex-accounts/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/wikty/codex-accounts/ci.yml?branch=main&label=tests"></a>
  <a href="https://pypi.org/project/codex-accounts/"><img alt="PyPI" src="https://img.shields.io/pypi/v/codex-accounts.svg"></a>
  <a href="https://pypi.org/project/codex-accounts/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/codex-accounts.svg"></a>
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
</p>

<p align="center">
  <a href="./README.zh-CN.md">中文文档</a> · <a href="./docs/installation.md">Install</a> · <a href="./docs/add-account.md">Add an account</a> · <a href="./docs/faq.md">FAQ</a>
</p>

---

The OpenAI Codex desktop app stores all sessions, logs, and UI state in
`~/.codex/` — and the underlying SQLite database has **no notion of which
account a row belongs to**. The moment you switch to a different ChatGPT
account, every previous session disappears from the sidebar.

**codex-accounts** fixes this by swapping the relevant files in and out of
`~/.codex/`, giving you clean multi-account isolation with a single command:

```console
$ codex-accounts use work
✓ switched to: work  (auth mode)

$ codex-accounts list
Accounts (/Users/you/.codex-accounts):

  ▶ work       work@example.com    Plus       5d left      2h ago    ← current
    personal   personal@me.io      Plus       9d left      yesterday
    research   lab@university.edu  Pro        1d left ⚠    3d ago
```

## Features

- **One-command switching** — `codex-accounts use <name>` saves the current
  account and activates the target in a single step.
- **Two isolation modes** — share session history across all accounts
  (default) or fully isolate sessions, history, and shell snapshots per
  account (`--no-share-sessions`).
- **Live quota** — `quota` and `list -a` query the same private endpoint
  the Codex client uses for its 5h/weekly progress bars.
- **Local usage stats** — `stats` reads the Codex SQLite database directly
  for offline token-usage breakdowns.
- **Auto-refresh** — `refresh` opens the 5-hour window across every
  account so a sliding daily allotment never goes unused (see
  [docs/auto-refresh.md](./docs/auto-refresh.md)).
- **Zero dependencies** — pure stdlib Python; ships as a single console
  script.

## Requirements

| | Supported |
|---|---|
| **OS** | macOS 12+ (primary), Linux (best-effort, PRs welcome) |
| **Python** | 3.9+ |
| **Codex desktop app** | already installed and signed in at least once |

> Windows is not currently supported. The path conventions and process
> detection in `codex_switch.utils` would need to be extended; PRs welcome.

## Install

```bash
# Recommended: isolated install with pipx
pipx install codex-accounts

# Or with pip
pip install --user codex-accounts
```

For a no-package-manager install of the bundled launcher script, see
[`docs/installation.md`](./docs/installation.md).

## Quick start

```bash
# 1. Snapshot the account you're already logged in to
codex-accounts save work

# 2. Add a second account (interactive)
codex-accounts init personal      # placeholder dir
codex-accounts use   personal     # clears auth.json so Codex prompts you to log in
open -a Codex                   # finish OAuth in the browser
codex-accounts save  personal     # capture the new account's data

# 3. Day-to-day
codex-accounts list               # see everything at a glance
codex-accounts use work           # switch back
codex-accounts quota              # check 5h / weekly limits
codex-accounts stats              # local token usage
```

See [docs/add-account.md](./docs/add-account.md) for a full walkthrough.

## Commands

| Command | What it does |
|---|---|
| `list [-a]` | List saved accounts (`-a` adds live quota) |
| `current` | Print the active account |
| `info [name]` | Email, plan, token expiry, notes |
| `save <name> [--auth-only]` | Snapshot current Codex state under `<name>` |
| `use <name> [--no-share-sessions]` | Activate `<name>` (auto-saves the current one first) |
| `init <name>` | Create an empty snapshot directory (no copy) |
| `note <name> <text>` | Attach a free-text note |
| `rename <old> <new>` | Rename an account snapshot |
| `delete <name>` | Remove a snapshot directory |
| `stats [name]` | Token usage from local SQLite |
| `quota [name]` | Live quota via private API (requires network) |
| `refresh` | Open the 5h window on every account (cron-friendly) |
| `app status [--since HOURS] [--json]` | Fast local Codex Desktop health summary |
| `app doctor [--since HOURS] [--live] [--json]` | Diagnose Codex Desktop reconnect/WebSocket/TLS timeout issues |
| `app kill [list\|stale]` | List Codex Desktop background processes or clean stale ones (macOS desktop only) |
| `app gc [--dry-run] [--json]` | Classify large Codex home files into remove/rebuild/archive/protected buckets |
| `app gc clean --category <name> --yes` | Delete selected `remove` candidates after explicit confirmation |
| `status [--since HOURS] [--json]` | Shortcut for `app status` |
| `doctor` | Environment dump for bug reports |

Run `codex-accounts <cmd> --help` for command-specific options.

## How it works

```
~/.codex/                           ~/.codex-accounts/work/
├── auth.json          <─ swap ─>   ├── auth.json
├── state_*.sqlite     <─ swap ─>   ├── state_*.sqlite       (FULL mode only)
├── sessions/          <─ swap ─>   ├── dirs/sessions/       (FULL mode only)
├── config.toml                     └── meta.json            (notes, timestamps)
├── skills/  rules/  memories/     (shared across all accounts — never swapped)
└── installation_id
```

- **AUTH mode** (default for `use`) — only `auth.json` is swapped. Sessions
  and history live in `~/.codex/` and are visible from every account. This
  is what most people want. This mode does not prompt you to close Codex.
  Restart an already-running client if it continues to use the previous account.
- **FULL mode** (`use --no-share-sessions`) — session DBs, log DBs, JSONL
  index, the `sessions/`/`archived_sessions/`/`shell_snapshots/`
  directories, and the global UI state file are all swapped. Use this when
  you genuinely want separate session sidebars per account. This mode still
  asks for confirmation when Codex is running because it replaces SQLite files.

`app gc` is read-only by default. It reports likely temporary leftovers,
rebuildable caches, archived artifacts worth compressing, and protected live
state. `app gc clean` only deletes items that appear in the current `remove`
bucket, and requires an exact `--category` or `--path` plus `--yes`. It does
not delete rollout history, auth/config files, SQLite indexes, or generated
images.

The exact file list lives in
[`src/codex_switch/config.py`](./src/codex_switch/config.py) and uses
**glob patterns** (`state_*.sqlite`, `logs_*.sqlite`) so future Codex
schema bumps don't silently miss files.

## Security & privacy

- `~/.codex-accounts/` and every snapshot directory inside it are created
  with mode `0700`.
- Account names are validated against `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`
  to prevent path traversal.
- `auth.json` is the same plaintext OAuth bundle the Codex client itself
  stores. Treat snapshot directories with the same care you'd treat
  `~/.codex/` — back them up, but do not check them into git or sync them
  to anywhere unencrypted.
- `quota`, `list -a`, and `refresh` make network calls to
  `chatgpt.com/backend-api`. All other commands are fully offline.
- See [`SECURITY.md`](./SECURITY.md) for vulnerability reporting.

## Disclaimers

- This project is **not affiliated with OpenAI** in any way.
- `quota`, `list -a`, and `refresh` rely on private endpoints
  (`/backend-api/wham/usage` and `/backend-api/codex/responses`) that were
  located by reverse-engineering the Codex desktop client. They can change
  at any time. See
  [`docs/internals/codex-app-internals.md`](./docs/internals/codex-app-internals.md)
  for the methodology used to re-discover them when a Codex update breaks
  the integration.
- `refresh` sends low-cost API requests on your behalf. Read
  [`docs/auto-refresh.md`](./docs/auto-refresh.md) — including the
  rate-limit and abuse-prevention caveats — before enabling the cron job.

## Contributing

Pull requests, bug reports, and "I tried it on Linux and X broke" notes
are all welcome. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the dev
loop, and [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) for community
expectations.

## License

[MIT](./LICENSE) © codex-accounts contributors.
