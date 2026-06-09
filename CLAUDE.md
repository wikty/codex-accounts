# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Dev commands

```bash
# One-time setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install

# Tests
pytest                                       # full suite
pytest tests/test_accounts.py                # one file
pytest tests/test_accounts.py::test_save_and_load_roundtrip -x  # one test, stop on first fail
pytest -k "rename"                           # by keyword

# Lint / format (CI runs both)
ruff check .
ruff format --check .
ruff format .                                # apply formatting

# Full local gate (lint + gitleaks + file hygiene)
pre-commit run --all-files
```

The CLI installs as `codex-accounts` inside the venv. To exercise it without
touching real Codex state, point `CODEX_HOME` and `CODEX_SWITCH_HOME` at a
sandbox — every path in the runtime resolves through `config.codex_home()` /
`config.accounts_home()`, both of which read those env vars:

```bash
export CODEX_HOME=/tmp/cs-sandbox/codex
export CODEX_SWITCH_HOME=/tmp/cs-sandbox/accounts
mkdir -p "$CODEX_HOME" "$CODEX_SWITCH_HOME"
codex-accounts doctor
```

## Architecture

The product is a thin file-swapper around `~/.codex/`. The Codex desktop app
has no per-account row in its SQLite DBs, so switching accounts means
physically moving files in and out of `~/.codex/` before launching Codex.

**Two swap modes** (`accounts.SwapMode`):

- `AUTH` — only `auth.json` is moved. Sessions/history stay in `~/.codex/` and
  are shared across accounts. This is the default for `use`.
- `FULL` — every file matching `config.ACCOUNT_FILE_PATTERNS` (state DBs, log
  DBs, JSONL index, global UI state) **and** every directory in
  `config.ACCOUNT_DIRS` (`sessions/`, `archived_sessions/`,
  `shell_snapshots/`) is moved. Used when `use --no-share-sessions` is passed
  and as the default for `save` (so a future `--no-share-sessions` switch has
  data to load).

`load_account` is asymmetric on purpose: when a snapshot is *missing* a file
that exists in live `~/.codex/`, the live file is deleted. This is what lets
the `init` → `use` workflow clear `auth.json` so Codex re-prompts for OAuth.

**The file list uses glob patterns** (`state_*.sqlite`, `logs_*.sqlite`) so
that Codex schema bumps (`state_5.sqlite` → `state_6.sqlite`) don't silently
miss files. If you add a new pattern, add it to `ACCOUNT_FILE_PATTERNS` in
`config.py`, not inline.

### Module layout

- `config.py` — all paths and constants. Paths are functions, not module-level
  values, so env-var overrides take effect even after import.
- `accounts.py` — snapshot model. `Account` is a dataclass over a directory
  under `~/.codex-accounts/<name>/`; `meta.json` lives next to the swapped
  files; `dirs/` holds copies of `ACCOUNT_DIRS` in FULL mode.
- `cli.py` — argparse entry point. Each subcommand is a `cmd_*` function;
  `main()` wires them together. The `_confirm_codex_closed` helper guards
  every command that writes to `~/.codex/` because SQLite will corrupt under
  concurrent writes.
- `api.py` — thin `urllib` wrapper around two **private, reverse-engineered**
  Codex endpoints: `/backend-api/wham/usage` (quota) and
  `/backend-api/codex/responses` (used by `refresh` to open the 5-hour
  window). Treat any change to URLs, headers, or model names as a breaking
  contract — see `docs/internals/codex-app-internals.md` for the
  rediscovery methodology.
- `stats.py` — read-only SQLite queries against `state_*.sqlite`. Never write.
- `utils.py` — JWT decoding (Codex stores its OAuth bundle in `auth.json` and
  the access token is a JWT we parse for email/plan/expiry), name validation,
  formatting, ANSI colors, and `is_codex_running()` (macOS/Linux only).

### Things to know before editing

- **Runtime is stdlib-only.** New dependencies for the shipping package are a
  hard no. Dev tooling goes in the `dev` extra of `pyproject.toml`.
- **Python 3.9+, `from __future__ import annotations` at the top of every
  module.** Use modern syntax (`X | None`, `list[T]`) in annotations.
- **Account names are validated** against `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`
  (`utils.validate_account_name`). They become directory components, so any
  new code path that takes a name from the user must validate.
- **All created dirs get 0700** via `utils.ensure_private_dir`. Snapshots
  contain plaintext OAuth tokens.
- **Tests must never touch real `~/.codex/`.** Use the `codex_env` fixture in
  `tests/conftest.py`, which sets `CODEX_HOME` and `CODEX_SWITCH_HOME` to
  `tmp_path` subdirs and provides `seed_live_account()` / `clear_live_account()`.
- **No network in tests.** `api` is a thin `urllib` wrapper specifically so
  it can be stubbed with `monkeypatch`.
- **Never commit real auth/session data.** Gitleaks runs in pre-commit and CI;
  fixtures in `conftest.py` build syntactically-valid-but-unsigned JWTs from
  scratch instead.

### Platform support

macOS is primary. Linux is best-effort (`is_codex_running()` and install
scripts are macOS-tuned). Windows is unsupported; `config.IS_WINDOWS` exists
mainly so `ensure_private_dir` can skip `chmod`.
