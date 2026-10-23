# bash completion for codex-accounts.
#
# Install:
#   mkdir -p ~/.bash_completion.d
#   cp codex-accounts.bash ~/.bash_completion.d/codex-accounts
#   # In ~/.bashrc:
#   #   [ -f ~/.bash_completion.d/codex-accounts ] && . ~/.bash_completion.d/codex-accounts

_codex_switch_accounts() {
  local home="${CODEX_SWITCH_HOME:-$HOME/.codex-accounts}"
  if [[ -d "$home" ]]; then
    ls -1 "$home" 2>/dev/null | grep -v '^\.'
  fi
}

_codex_switch_complete() {
  local cur prev words cword
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"

  local commands="list current info save use init note rename delete stats quota refresh app status doctor --help --version"

  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
    return
  fi

  local subcmd="${COMP_WORDS[1]}"
  case "$subcmd" in
    list)
      COMPREPLY=( $(compgen -W "-a --all" -- "$cur") )
      ;;
    save)
      if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "--auth-only" -- "$cur") )
      else
        COMPREPLY=( $(compgen -W "$(_codex_switch_accounts)" -- "$cur") )
      fi
      ;;
    use)
      if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "--no-share-sessions -f --force" -- "$cur") )
      else
        COMPREPLY=( $(compgen -W "$(_codex_switch_accounts)" -- "$cur") )
      fi
      ;;
    info|stats|quota|init|note|delete|rename)
      COMPREPLY=( $(compgen -W "$(_codex_switch_accounts)" -- "$cur") )
      ;;
    refresh)
      COMPREPLY=( $(compgen -W "--delay --dry-run" -- "$cur") )
      ;;
    status)
      COMPREPLY=( $(compgen -W "--since --json" -- "$cur") )
      ;;
    app)
      if [[ $COMP_CWORD -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "status doctor kill gc" -- "$cur") )
        return
      fi
      local appcmd="${COMP_WORDS[2]}"
      case "$appcmd" in
        status)
          COMPREPLY=( $(compgen -W "--since --json" -- "$cur") )
          ;;
        doctor)
          COMPREPLY=( $(compgen -W "--since --live --json" -- "$cur") )
          ;;
        kill)
          COMPREPLY=( $(compgen -W "list stale --dry-run" -- "$cur") )
          ;;
        gc)
          if [[ $COMP_CWORD -eq 3 ]]; then
            COMPREPLY=( $(compgen -W "clean --dry-run --older-than-days --limit --json" -- "$cur") )
          else
            local gcaction="${COMP_WORDS[3]}"
            case "$gcaction" in
              clean)
                COMPREPLY=( $(compgen -W "--action --category --path --older-than-days --dry-run --yes --force" -- "$cur") )
                ;;
              *)
                COMPREPLY=( $(compgen -W "--dry-run --older-than-days --limit --json" -- "$cur") )
                ;;
            esac
          fi
          ;;
      esac
      ;;
  esac
}

complete -F _codex_switch_complete codex-accounts
