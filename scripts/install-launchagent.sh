#!/usr/bin/env bash
# Install the codex-accounts refresh LaunchAgent on macOS.
#
# Idempotent: re-running replaces the existing agent and reloads it.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "✗  This installer is macOS-only." >&2
  exit 1
fi

REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
TEMPLATE="${REPO_ROOT}/packaging/com.codex-accounts.refresh.plist"
LABEL="com.codex-accounts.refresh"
DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

BIN="$(command -v codex-accounts || true)"
if [[ -z "$BIN" ]]; then
  echo "✗  codex-accounts is not on PATH. Install it first (see docs/installation.md)." >&2
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents"

# Substitute the absolute path of the installed CLI.
sed "s|@@CODEX_ACCOUNTS_BIN@@|${BIN}|g" "$TEMPLATE" > "$DEST"
chmod 0644 "$DEST"
echo "i  wrote ${DEST}"

# Reload: bootout existing instance (ignore errors), then bootstrap.
DOMAIN="gui/$(id -u)"
launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "${DOMAIN}" "$DEST"
echo "✓  LaunchAgent ${LABEL} installed and loaded."

cat <<EOF

Next steps:
  - Verify:   launchctl list | grep ${LABEL}
  - Trigger:  launchctl kickstart -k ${DOMAIN}/${LABEL}
  - Logs:     tail -f /tmp/codex-accounts-refresh.log
  - Edit schedule by re-running this script after editing the template.
  - Uninstall:
        launchctl bootout ${DOMAIN}/${LABEL}
        rm '${DEST}'
EOF
