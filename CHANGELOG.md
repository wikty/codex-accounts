# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-06-09

### Added
- `billing <name> [<date>] [--clear]` subcommand: track each account's
  monthly subscription renewal date. The stored value is preserved as an
  anchor, and display auto-rolls forward month-by-month (Stripe-style:
  day-of-month is clamped to each month's last day), so a single
  `billing` call covers all future renewals.
- `renews` column in `list` — only rendered when at least one account
  has a date set — plus a `renews` line in `info`. ≤7d shows yellow
  ⚠, `today` is yellow.
- `utils.next_renewal_date()` and `utils.fmt_renews()` helpers, with
  parametrized tests covering leap-year, month-end clamping, and
  year-boundary rollover.

### Changed
- `list` column alignment: header labels now factor into column widths,
  so short data (e.g. one-letter names) no longer pushes every
  downstream column to the right of its header.
- `list -a` quota column: header split into separate `5h` and `weekly`
  columns; the weekly window now renders an absolute `MM-DD HH:MM`
  instead of a relative `↺Xh` (clearer for week-scale resets).
- `list -a` quota cell distinguishes `(no auth)` / `(token expired)` /
  `(no token)` / `(no live quota)` / `err: ...` instead of collapsing
  every miss to `(no live quota)`.
- CJK-safe column widths: new `utils.display_width()` /
  `utils.display_ljust()` treat East-Asian Wide chars as 2 cells, so
  Chinese notes / names no longer skew table columns.

## [0.1.0] - 2026-05-30

Initial open-source release. The project began as a single-file Bash
script for personal use; this version is a from-scratch rewrite as a
clean Python package.

### Added
- Python package `codex_switch` with stdlib-only dependencies.
- Subcommands: `list`, `current`, `info`, `save`, `use`, `init`, `note`,
  `rename`, `delete`, `stats`, `quota`, `refresh`, `doctor`.
- Two swap modes (`AUTH` and `FULL`) selectable via `--no-share-sessions`.
- Glob-based file matching (`state_*.sqlite`, `logs_*.sqlite`) so Codex
  schema bumps no longer require code changes.
- Account-name validation against `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`.
- Automatic `chmod 0700` on accounts home and per-account directories.
- LaunchAgent template for the daily `refresh` cron job.
- Shell completions for bash and zsh.
- Pytest suite with isolated `CODEX_HOME` / `CODEX_SWITCH_HOME` fixtures.
- GitHub Actions CI matrix on macOS and Ubuntu.

[Unreleased]: https://github.com/wikty/codex-accounts/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/wikty/codex-accounts/releases/tag/v0.2.0
[0.1.0]: https://github.com/wikty/codex-accounts/releases/tag/v0.1.0
