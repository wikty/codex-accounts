# Security policy

## Supported versions

Only the latest minor release of `codex-accounts` receives security fixes.

| Version | Supported |
|---------|-----------|
| `0.x`   | ✅ Latest minor |
| Older   | ❌ |

## Reporting a vulnerability

**Please do not open public GitHub issues for security problems.**

Use GitHub's private vulnerability reporting:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Include:
   - A short description of the issue and its impact.
   - Reproduction steps or a minimal PoC.
   - The version / commit you tested against.
   - Your suggested fix, if you have one.

We aim to acknowledge reports within **3 business days** and to ship a
fix or mitigation within **14 days** for high-severity issues.

## Scope

In scope:

- Path traversal, command injection, or privilege escalation in the
  `codex-accounts` CLI or installer.
- Information leaks involving snapshotted `auth.json` files or other
  credentials read by the tool.
- Issues that allow a third party to manipulate another user's Codex
  account state through `codex-accounts`.

Out of scope:

- Bugs in the OpenAI Codex desktop app itself. Please report those to
  OpenAI directly.
- The intentional design where `~/.codex-accounts/` stores `auth.json`
  in plaintext, mirroring the storage format the Codex client uses.
  Hardening this (e.g. keychain integration) is welcome as a feature
  contribution but is not treated as a vulnerability.
- Anything that requires an attacker to already have local read access
  to the user's home directory.

## Responsible disclosure

We will credit reporters in the release notes for fixes derived from
their report, unless they request otherwise.
