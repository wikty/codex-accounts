#!/usr/bin/env bash
# install.sh — bootstrap install for codex-accounts.
#
# This is a thin wrapper around the canonical install paths described in
# docs/installation.md. It prefers pipx, falls back to pip --user, and
# offers to install shell completions and the LaunchAgent.
#
# Run from anywhere:
#     ./install.sh                 # interactive
#     ./install.sh --yes           # accept all defaults
#     ./install.sh --from-source   # install from the local checkout
#
set -euo pipefail

# --- pretty output ----------------------------------------------------------

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_DIM='\033[2m'; C_OK='\033[92m'; C_WARN='\033[93m'; C_ERR='\033[91m'; C_RESET='\033[0m'
else
  C_DIM=''; C_OK=''; C_WARN=''; C_ERR=''; C_RESET=''
fi
info()  { printf '%b\n' "${C_DIM}i  $*${C_RESET}"; }
ok()    { printf '%b\n' "${C_OK}✓  $*${C_RESET}"; }
warn()  { printf '%b\n' "${C_WARN}!  $*${C_RESET}" >&2; }
die()   { printf '%b\n' "${C_ERR}✗  $*${C_RESET}" >&2; exit 1; }

# --- argument parsing -------------------------------------------------------

YES=0
FROM_SOURCE=0
INSTALL_COMPLETIONS=auto
INSTALL_LAUNCHAGENT=auto

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes) YES=1 ;;
    --from-source) FROM_SOURCE=1 ;;
    --completions) INSTALL_COMPLETIONS=1 ;;
    --no-completions) INSTALL_COMPLETIONS=0 ;;
    --launchagent) INSTALL_LAUNCHAGENT=1 ;;
    --no-launchagent) INSTALL_LAUNCHAGENT=0 ;;
    -h|--help)
      sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) die "unknown flag: $1" ;;
  esac
  shift
done

ask() {
  # ask "prompt" default(Y|N) → echoes "yes" or "no"
  local prompt="$1" default="${2:-N}" answer
  if (( YES )); then
    echo "$([[ "$default" == "Y" ]] && echo yes || echo no)"
    return
  fi
  read -r -p "$prompt " answer || answer=""
  answer="${answer:-$default}"
  case "$answer" in
    [Yy]*) echo yes ;;
    *)     echo no ;;
  esac
}

# --- Python check -----------------------------------------------------------

if ! command -v python3 >/dev/null 2>&1; then
  die "python3 not found on PATH — install Python 3.9+ first."
fi

PYV="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYV_MAJOR="${PYV%.*}"; PYV_MINOR="${PYV#*.}"
if (( PYV_MAJOR < 3 )) || { (( PYV_MAJOR == 3 )) && (( PYV_MINOR < 9 )); }; then
  die "Python ${PYV} found; codex-accounts needs >= 3.9."
fi
info "Python ${PYV} detected."

# --- main install -----------------------------------------------------------

REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

install_via_pipx() {
  info "Installing codex-accounts via pipx…"
  if (( FROM_SOURCE )); then
    pipx install --force "$REPO_ROOT"
  else
    pipx install --force codex-accounts
  fi
}

install_via_pip() {
  info "Installing codex-accounts via pip --user…"
  if (( FROM_SOURCE )); then
    python3 -m pip install --user --upgrade "$REPO_ROOT"
  else
    python3 -m pip install --user --upgrade codex-accounts
  fi
}

if command -v pipx >/dev/null 2>&1; then
  install_via_pipx
else
  warn "pipx is not installed (recommended). Falling back to pip --user."
  install_via_pip
fi

if ! command -v codex-accounts >/dev/null 2>&1; then
  warn "codex-accounts is installed but not on PATH yet."
  warn "Add the Python user-base bin dir to PATH, then re-open your shell."
else
  ok "codex-accounts is on PATH: $(command -v codex-accounts)"
  codex-accounts --version || true
fi

# --- optional: completions --------------------------------------------------

if [[ "$INSTALL_COMPLETIONS" == "auto" ]]; then
  ans="$(ask "Install shell completion for the current shell? [y/N]" N)"
  [[ "$ans" == "yes" ]] && INSTALL_COMPLETIONS=1 || INSTALL_COMPLETIONS=0
fi

if (( INSTALL_COMPLETIONS )); then
  shell_name="$(basename "${SHELL:-/bin/sh}")"
  case "$shell_name" in
    zsh)
      target="${HOME}/.zsh/completions/_codex-accounts"
      mkdir -p "$(dirname "$target")"
      cp "${REPO_ROOT}/completions/_codex-accounts" "$target"
      ok "zsh completion installed at $target"
      info "Make sure ~/.zshrc has:  fpath=(~/.zsh/completions \$fpath); autoload -Uz compinit && compinit"
      ;;
    bash)
      target="${HOME}/.bash_completion.d/codex-accounts"
      mkdir -p "$(dirname "$target")"
      cp "${REPO_ROOT}/completions/codex-accounts.bash" "$target"
      ok "bash completion installed at $target"
      info "Make sure ~/.bashrc sources it:  [ -f $target ] && . $target"
      ;;
    *)
      warn "Unsupported shell '$shell_name' — skipping completions."
      ;;
  esac
fi

# --- optional: LaunchAgent (macOS only) -------------------------------------

if [[ "$(uname -s)" == "Darwin" ]]; then
  if [[ "$INSTALL_LAUNCHAGENT" == "auto" ]]; then
    ans="$(ask "Install the daily 'codex-accounts refresh' LaunchAgent? [y/N]" N)"
    [[ "$ans" == "yes" ]] && INSTALL_LAUNCHAGENT=1 || INSTALL_LAUNCHAGENT=0
  fi

  if (( INSTALL_LAUNCHAGENT )); then
    "${REPO_ROOT}/scripts/install-launchagent.sh"
  fi
fi

ok "Done. Run 'codex-accounts --help' to get started."
