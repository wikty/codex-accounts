# Contributing to codex-accounts

Thanks for considering a contribution! This project is small enough that
process can stay light — please follow the conventions below and we'll
keep moving fast.

## Quick dev loop

```bash
git clone https://github.com/wikty/codex-accounts.git
cd codex-accounts

# Set up a virtualenv and install in editable mode with dev extras
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Install git hooks
pre-commit install

# Run the test suite
pytest

# Lint
ruff check .
ruff format --check .

# Run the full local gate (including secret scanning)
pre-commit run --all-files
```

The CLI is then available as `codex-accounts` inside the venv. It reads
its paths from `CODEX_HOME` and `CODEX_SWITCH_HOME` env vars, so you can
point it at a sandbox while iterating:

```bash
export CODEX_HOME=/tmp/cs-sandbox/codex
export CODEX_SWITCH_HOME=/tmp/cs-sandbox/accounts
mkdir -p "$CODEX_HOME" "$CODEX_SWITCH_HOME"
codex-accounts doctor
```

## Code style

- **Python 3.9+** with `from __future__ import annotations`.
- **stdlib only** in the runtime package. Dev-time deps belong in the
  `dev` extra of `pyproject.toml`.
- Type hints on every public function. Internal helpers are encouraged
  to have them too.
- Run `ruff check` and `ruff format` before opening a PR.
- Run `pre-commit run --all-files` before opening a PR when you've touched
  config, docs, or shell scripts.
- Comments explain *why*, not *what*. The reviewer can read the code.

## Tests

- Every behavioural change ships with a test. There's no formal coverage
  threshold, but new modules should land with smoke tests at minimum.
- Tests must not touch a real `~/.codex/` — use the `codex_env` fixture
  defined in `tests/conftest.py`, which isolates `CODEX_HOME` and
  `CODEX_SWITCH_HOME` under a `tmp_path`.
- Avoid network calls in tests. The `api` module is intentionally a thin
  wrapper around `urllib` so it can be stubbed with `monkeypatch`.
- Never commit real `auth.json`, SQLite snapshots, JSONL exports, or any
  sample copied from `~/.codex/` or `~/.codex-accounts/`. Keep real debug
  data outside the repository and use redacted fixtures only.

## Commits & pull requests

- Keep commits scoped and reviewable. "WIP" commits get squashed.
- Reference an issue number in the PR description when relevant.
- The PR description should answer:
  1. **What** changed?
  2. **Why** is the change needed?
  3. **How** was it verified (commands run, scenarios tested)?

## Areas where help is especially welcome

- **Linux compatibility.** The code paths are mostly portable but
  `is_codex_running()` and the install scripts are macOS-tuned. Anyone
  running the Codex Linux client: please open issues with concrete
  reproductions.
- **Codex schema watchdog.** When OpenAI bumps the SQLite schema or
  rotates the private API path, the integration breaks silently. PRs
  that add detection or fallbacks are very welcome.
- **Documentation translations.** We currently ship English and
  Simplified Chinese READMEs; other languages welcome.

## Releasing (maintainers)

1. Update `CHANGELOG.md` — move `[Unreleased]` into a dated section.
2. Bump `version` in `pyproject.toml` and `src/codex_switch/__init__.py`.
3. Tag `vX.Y.Z`, push, let CI build & publish.

## Code of Conduct

Participation is governed by the [Contributor Covenant](./CODE_OF_CONDUCT.md).
