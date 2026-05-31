# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/wikty/codex-accounts/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/wikty/codex-accounts/releases/tag/v0.1.0
