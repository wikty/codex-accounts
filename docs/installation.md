# Installation

`codex-accounts` is a single-file console script with **no runtime
dependencies** beyond the Python standard library. Three install paths
are supported, in order of preference.

## 1. pipx (recommended)

[`pipx`](https://pipx.pypa.io/) installs Python CLIs into isolated
environments and puts the entry point on your `PATH` — exactly what you
want for a global tool like this.

```bash
# Install pipx itself if you don't have it
brew install pipx           # macOS
sudo apt install pipx       # Debian/Ubuntu
pipx ensurepath

# Install codex-accounts
pipx install codex-accounts
```

Upgrade later with `pipx upgrade codex-accounts`.

## 2. pip --user

```bash
pip install --user codex-accounts
```

You may need to add `~/Library/Python/3.x/bin` (macOS) or
`~/.local/bin` (Linux) to your `PATH`.

## 3. Run from source

Useful for hacking on the project.

```bash
git clone https://github.com/wikty/codex-accounts.git
cd codex-accounts
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
codex-accounts --version
```

## 4. Shell completion

`codex-accounts` ships zsh and bash completion stubs. They are installed
manually because most users don't want a CLI to write to their shell
config without consent.

### Zsh

```bash
# Pick a directory that is on your $fpath (or add this one to it)
mkdir -p ~/.zsh/completions
curl -fsSL https://raw.githubusercontent.com/wikty/codex-accounts/main/completions/_codex-accounts \
  -o ~/.zsh/completions/_codex-accounts

# In ~/.zshrc:
fpath=(~/.zsh/completions $fpath)
autoload -Uz compinit && compinit
```

### Bash

```bash
mkdir -p ~/.bash_completion.d
curl -fsSL https://raw.githubusercontent.com/wikty/codex-accounts/main/completions/codex-accounts.bash \
  -o ~/.bash_completion.d/codex-accounts

# In ~/.bashrc:
[ -f ~/.bash_completion.d/codex-accounts ] && . ~/.bash_completion.d/codex-accounts
```

## 5. Verify

```bash
codex-accounts --version
codex-accounts doctor
```

`doctor` prints a small diagnostic dump (Python version, paths, whether
Codex is running). Include it when filing bug reports.

## Where data is stored

| Path | What it holds | Override via |
|---|---|---|
| `~/.codex/` | Live Codex client state (auth, sessions, logs) | `CODEX_HOME` |
| `~/.codex-accounts/` | Per-account snapshots managed by codex-accounts | `CODEX_SWITCH_HOME` |

Both can be redirected with environment variables, which is useful for
sandboxed testing.
