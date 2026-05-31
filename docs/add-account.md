# Adding a new account

A "new account" here means: a ChatGPT login that the Codex desktop app
has never authenticated against on this machine before. The flow is the
same on every operating system Codex supports.

## TL;DR

```bash
codex-accounts save current-acct   # snapshot what you have right now
# quit the Codex app (Cmd+Q on macOS, File → Quit elsewhere)
codex-accounts init new-acct
codex-accounts use  new-acct       # clears auth.json so Codex prompts for login
open -a Codex                    # finish OAuth in your browser
# quit Codex again
codex-accounts save new-acct       # capture the new tokens + session data
codex-accounts list
```

The next sections explain each step.

## Why these steps?

The Codex app stores credentials in `~/.codex/auth.json`. When the file
is absent at launch, Codex sends you through OAuth to acquire fresh
tokens. `codex-accounts` exploits this by clearing `auth.json` on switch,
running the new login, and then snapshotting the result.

The reason for quitting Codex between steps is that the app keeps
SQLite write locks on `state_*.sqlite` and `logs_*.sqlite`. Copying
those files while Codex is running risks a partial / corrupted snapshot.

## Step-by-step

### 1 — Snapshot the current account

If you have not run `codex-accounts save` before, your current login is
not yet under management. Save it first so you can come back to it:

```bash
codex-accounts save current-acct
```

Pick whatever name you like — typically the email prefix or a short
label like `work` or `personal`.

### 2 — Quit Codex

Right-click the Codex menu bar icon → Quit, or use `Cmd+Q`. Confirm with
`pgrep -x Codex` (no output = quit).

### 3 — Initialise an empty snapshot directory for the new account

```bash
codex-accounts init new-acct
```

This just creates `~/.codex-accounts/new-acct/` so the next `use`
command knows the account name is legitimate.

### 4 — Switch to the new (still-empty) account

```bash
codex-accounts use new-acct
```

In the default share-sessions mode, this deletes `~/.codex/auth.json`
and records the new account name as current. **No session data is
touched**, so your existing chat history will still be visible.

### 5 — Re-launch Codex and complete OAuth

```bash
open -a Codex
```

Codex notices that no token is present and pops the browser-based OAuth
flow. Sign in with the **new** account credentials. Once Codex shows
the welcome page or main UI, the token has been written.

### 6 — Quit Codex and capture the snapshot

```bash
# Quit Codex first
codex-accounts save new-acct
```

### 7 — Verify

```bash
codex-accounts list
codex-accounts info new-acct
codex-accounts quota new-acct      # optional — needs network
```

You should see two rows in `list`, each with its own email and plan.

## Switching back to the original account

```bash
codex-accounts use current-acct
open -a Codex
```

`use` auto-snapshots whatever is currently live before swapping in the
target account, so you never lose state by switching.

## Common questions

### Codex says "Codex is running, continue?" during `use`

Answer no, quit Codex, then retry. The warning exists because SQLite
write locks make in-flight copies unsafe.

### After `save`, `list` shows "(no auth.json)"

Step 5 was incomplete — Codex did not finish writing the token before
quit. Re-launch, wait until the main UI is visible, quit again, and
re-save.

### Token shows "expired"

ChatGPT access tokens last roughly 10 days. Refresh by:

```bash
codex-accounts use   <name>
open -a Codex                  # Codex will refresh or prompt you to re-login
# quit Codex
codex-accounts save  <name>
```

### Permanently remove an account

```bash
codex-accounts delete <name>
```

This removes the local snapshot under `~/.codex-accounts/<name>/`.
It does **not** touch the ChatGPT account itself.

## Reference: snapshot layout

```
~/.codex-accounts/
└── work/
    ├── auth.json                 # OAuth bundle (JWT inside)
    ├── state_*.sqlite            # session DB (FULL mode only)
    ├── logs_*.sqlite             # log DB (FULL mode only)
    ├── session_index.jsonl       # session index (FULL mode only)
    ├── .codex-global-state.json  # UI state (FULL mode only)
    ├── dirs/
    │   ├── sessions/             # FULL mode only
    │   ├── archived_sessions/    # FULL mode only
    │   └── shell_snapshots/      # FULL mode only
    └── meta.json                 # codex-accounts bookkeeping (notes, timestamps)
```
