"""argparse-based command-line interface."""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

from codex_switch import __version__, accounts, api, config, stats, utils
from codex_switch.accounts import Account, SwapMode

PROG = "codex-accounts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _confirm_codex_closed(force: bool) -> None:
    if not utils.is_codex_running():
        return
    utils.warn("Codex is running; close it before switching to avoid SQLite lock issues.")
    if force:
        return
    try:
        ans = input("  Continue anyway? [y/N] ").strip().lower()
    except EOFError:
        ans = ""
    if ans not in ("y", "yes"):
        sys.exit(1)


def _require_current() -> str:
    name = accounts.current_name()
    if not name:
        utils.die("no active account. Save one first with: codex-accounts save <name>")
    return name


def _account_or_die(name: str, *, must_exist: bool = True) -> Account:
    try:
        return accounts.get_account(name, must_exist=must_exist)
    except (FileNotFoundError, ValueError) as e:
        utils.die(str(e))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    show_quota = bool(args.all)
    rows = accounts.list_accounts()
    if not rows:
        utils.echo(f"  no accounts saved yet — run `{PROG} save <name>` to add one.")
        return 0

    current = accounts.current_name()
    auth_map = {acct.name: accounts.read_auth(acct.name) for acct in rows}
    meta_map = {acct.name: acct.read_meta() for acct in rows}
    show_renews = any(m.get("renews_at") for m in meta_map.values())
    quota_map: dict[str, object] = {}

    if show_quota:
        candidates = [
            (acct.name, info.access_token)
            for acct, info in zip(rows, [auth_map[r.name] for r in rows])
            if info and not info.is_expired and info.access_token
        ]
        if candidates:
            utils.echo(utils.dim(f"  fetching live quota for {len(candidates)} account(s)..."))
            with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as pool:
                futures = {pool.submit(api.fetch_quota, tok): name for name, tok in candidates}
                for fut in as_completed(futures):
                    name = futures[fut]
                    try:
                        quota_map[name] = fut.result()
                    except api.ApiError as e:
                        quota_map[name] = e

    # Column widths factor in both the header label and the data values,
    # measured in terminal display cells (CJK chars count as 2).
    def _col_width(values: list[str], header: str) -> int:
        return max(utils.display_width(header), *(utils.display_width(v) for v in values))

    name_values = [r.name for r in rows]
    email_values = [
        (auth_map[r.name].email if auth_map[r.name] else "(no auth.json)") for r in rows
    ]
    max_name = _col_width(name_values, "name")
    max_email = _col_width(email_values, "email")

    utils.echo(f"\nAccounts ({config.accounts_home()}):\n")
    header_cols = [
        "  ",
        utils.display_ljust("name", max_name),
        utils.display_ljust("email", max_email),
        f"{'plan':<10}",
        f"{'token':<12}",
        f"{'last used':<10}",
    ]
    if show_renews:
        header_cols.append(f"{'renews':<7}")
    if show_quota:
        header_cols.append(f"{'5h':<14}")
        header_cols.append(f"{'weekly':<18}")
    header = "  ".join(header_cols)
    utils.echo(utils.dim(header))
    utils.echo(utils.dim("  " + "-" * (utils.display_width(header) - 2)))

    for acct in rows:
        info = auth_map[acct.name]
        meta = meta_map[acct.name]
        is_cur = acct.name == current
        marker = "▶" if is_cur else " "
        name_cell = utils.display_ljust(acct.name, max_name)
        email_cell = utils.display_ljust(info.email if info else "(no auth.json)", max_email)
        plan = utils.fmt_plan(info.plan if info else "")
        token = utils.fmt_token_status(info)
        last = utils.fmt_last_used(meta.get("last_used_at", ""))
        line = f"  {marker} {name_cell}  {email_cell}  {plan:<10}  {token:<12}  {last:<10}"
        if show_renews:
            line += "  " + _renews_cell(meta.get("renews_at", ""))
        if show_quota:
            line += "  " + _quota_cell(quota_map.get(acct.name), info)
        if is_cur:
            line += "  " + utils.bold("← current")
        notes = meta.get("notes")
        if notes:
            line += "  " + utils.dim(f"[{notes}]")
        utils.echo(line)
    utils.echo("")
    return 0


def _renews_cell(iso_date: str, width: int = 7) -> str:
    text = utils.fmt_renews(iso_date)
    padded = utils.display_ljust(text, width)
    if text == "today" or text.endswith("⚠"):
        return utils.yellow(padded)
    return padded


def _quota_cell(value: object, info: utils.AuthInfo | None) -> str:
    if value is None:
        if info is None:
            return utils.dim("(no auth)")
        if info.is_expired:
            return utils.dim("(token expired)")
        if not info.access_token:
            return utils.dim("(no token)")
        return utils.dim("(no live quota)")
    if isinstance(value, api.ApiError):
        return utils.red(f"err: {value}"[:40])
    q: api.Quota = value  # type: ignore[assignment]

    def short(window: api.Window | None, *, absolute: bool) -> str:
        if window is None:
            return "—"
        pct = int(window.used_percent)
        if absolute and window.reset_at:
            dt = datetime.fromtimestamp(window.reset_at, tz=timezone.utc).astimezone()
            reset = dt.strftime("%m-%d %H:%M")
        else:
            reset = "↺" + utils.fmt_duration(window.reset_after_seconds)
        return f"{pct:3d}% / {reset}"

    suffix = " ⛔" if not q.allowed or q.limit_reached else ""
    primary = short(q.primary, absolute=False)
    secondary = short(q.secondary, absolute=True)
    return f"{primary:<14}  {secondary:<18}{suffix}"


def cmd_current(_args: argparse.Namespace) -> int:
    name = accounts.current_name()
    utils.echo(name or "(no current account)")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    name = args.name or _require_current()
    acct = _account_or_die(name, must_exist=False)
    info = accounts.read_auth(name)
    meta = acct.read_meta()

    utils.echo(f"\nAccount: {utils.bold(name)}")
    utils.echo("─" * 48)
    if info is None:
        utils.echo("  auth.json missing or unreadable")
    else:
        utils.echo(f"  email     {info.email or '(unknown)'}")
        utils.echo(f"  plan      {utils.fmt_plan(info.plan)}")
        utils.echo(f"  mode      {info.auth_mode or '(unknown)'}")
        if info.expires_at:
            utils.echo(
                f"  token     {utils.fmt_token_status(info)} "
                f"(expires {info.expires_at.astimezone().strftime('%Y-%m-%d %H:%M')})"
            )
        if info.account_id:
            utils.echo(f"  account   …{info.account_id[-12:]}")
    last = meta.get("last_used_at", "")
    utils.echo(f"  last used {utils.fmt_last_used(last)}")
    renews = meta.get("renews_at", "")
    if renews:
        try:
            anchor = utils.parse_iso_date(renews)
            today = date.today()
            nxt = utils.next_renewal_date(anchor, today)
            diff = (nxt - today).days
            tail = "(today)" if diff == 0 else f"(in {diff}d)"
            utils.echo(f"  renews    {nxt.isoformat()}  {tail}")
        except ValueError:
            utils.echo(f"  renews    {renews}")
    notes = meta.get("notes", "")
    utils.echo(f"  notes     {notes or '(none)'}")
    utils.echo("")
    return 0


def cmd_save(args: argparse.Namespace) -> int:
    name = args.name
    try:
        utils.validate_account_name(name)
    except ValueError as e:
        utils.die(str(e))

    mode = SwapMode.AUTH if args.auth_only else SwapMode.FULL
    utils.info(f"saving live Codex state to account '{name}' ({mode.value} mode)…")
    try:
        accounts.save_account(name, mode=mode)
    except FileNotFoundError as e:
        utils.die(str(e))
    accounts.set_current(name)
    utils.ok(f"saved: {name}")
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    name = args.name
    try:
        utils.validate_account_name(name)
    except ValueError as e:
        utils.die(str(e))

    _confirm_codex_closed(force=args.force)
    mode = SwapMode.FULL if args.no_share_sessions else SwapMode.AUTH

    current = accounts.current_name()
    if current and current != name:
        utils.info(f"snapshotting current account '{current}' before switching…")
        try:
            accounts.save_account(current, mode=mode)
        except FileNotFoundError as e:
            utils.warn(str(e))

    try:
        accounts.load_account(name, mode=mode)
    except FileNotFoundError as e:
        utils.die(str(e))
    utils.ok(f"switched to: {name}  ({mode.value} mode)")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    name = args.name
    try:
        accounts.init_account(name)
    except (FileExistsError, ValueError) as e:
        utils.die(str(e))
    utils.ok(f"initialised empty snapshot dir for '{name}'")
    utils.info(f"next: run `{PROG} use {name}`, complete OAuth in Codex, then `{PROG} save {name}`")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    try:
        accounts.set_note(args.name, args.text)
    except (FileNotFoundError, ValueError) as e:
        utils.die(str(e))
    utils.ok(f"note set on '{args.name}'")
    return 0


def cmd_billing(args: argparse.Namespace) -> int:
    name = args.name
    try:
        acct = accounts.get_account(name, must_exist=True)
    except (FileNotFoundError, ValueError) as e:
        utils.die(str(e))

    if args.clear:
        accounts.set_billing(name, None)
        utils.ok(f"{name}: renewal date cleared")
        return 0

    if args.date:
        try:
            anchor = utils.parse_iso_date(args.date)
        except ValueError as e:
            utils.die(str(e))
        accounts.set_billing(name, anchor.isoformat())
        today = date.today()
        nxt = utils.next_renewal_date(anchor, today)
        diff = (nxt - today).days
        when = "today" if diff == 0 else f"in {diff}d"
        utils.ok(f"{name}: renews {nxt.isoformat()} ({when})")
        if nxt != anchor:
            utils.info(
                f"        anchor {anchor.isoformat()} auto-rolled monthly to {nxt.isoformat()}"
            )
        return 0

    # No date and no --clear → show current
    cur = acct.read_meta().get("renews_at")
    if not cur:
        utils.echo(f"{name}: no renewal date set")
        utils.echo(f"       set with: {PROG} billing {name} YYYY-MM-DD")
        return 0
    try:
        anchor = utils.parse_iso_date(cur)
        today = date.today()
        nxt = utils.next_renewal_date(anchor, today)
        diff = (nxt - today).days
        when = "today" if diff == 0 else f"in {diff}d"
        utils.echo(f"{name}: renews {nxt.isoformat()} ({when})")
        if nxt != anchor:
            utils.echo(utils.dim(f"       (monthly cycle, anchor {anchor.isoformat()})"))
    except ValueError:
        utils.echo(f"{name}: renews {cur}  (unparseable; clear and re-set)")
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    try:
        accounts.rename_account(args.old, args.new)
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        utils.die(str(e))
    utils.ok(f"renamed: {args.old} → {args.new}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    name = args.name
    if not args.yes:
        try:
            ans = input(f"Delete snapshot '{name}'? Type the name to confirm: ").strip()
        except EOFError:
            ans = ""
        if ans != name:
            utils.die("aborted")
    try:
        path = accounts.delete_account(name)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        utils.die(str(e))
    utils.ok(f"deleted: {path}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    try:
        s = stats.compute_stats(args.name)
    except FileNotFoundError as e:
        utils.die(str(e))

    utils.echo(f"\nUsage stats for {utils.bold(s.name)}")
    utils.echo(utils.dim(f"  source: {s.source}"))
    utils.echo("─" * 52)
    if not s.sessions:
        utils.echo("  (no sessions recorded)\n")
        return 0
    utils.echo(f"  sessions       {s.total_sessions:,}")
    utils.echo(f"  total tokens   {s.total_tokens:,}")
    utils.echo(f"   last  7 days  {s.last_7d_tokens:>14,}  ({s.last_7d_sessions} sessions)")
    utils.echo(f"   last 30 days  {s.last_30d_tokens:>14,}  ({s.last_30d_sessions} sessions)")
    if s.by_model:
        utils.echo("\n  by model:")
        for model, tokens in sorted(s.by_model.items(), key=lambda kv: -kv[1]):
            bar_len = int(tokens / s.total_tokens * 20) if s.total_tokens else 0
            utils.echo(f"    {model:<22} {tokens:>14,}  {'█' * bar_len}")
    utils.echo("\n  recent sessions:")
    for sess in s.sessions[:10]:
        ts = sess.created_at.astimezone().strftime("%m-%d %H:%M") if sess.created_at else "?"
        utils.echo(f"    {ts}  {(sess.title)[:36]:<36}  {sess.tokens_used:>10,}  {sess.model[:14]}")
    utils.echo("")
    return 0


def cmd_quota(args: argparse.Namespace) -> int:
    name = args.name or _require_current()
    info = accounts.read_auth(name)
    if info is None:
        utils.die(f"no auth.json for '{name}'")
    if info.is_expired:
        utils.die(f"token for '{name}' has expired; re-login in Codex and run `{PROG} save {name}`")

    utils.echo(f"\nQuota for {utils.bold(name)}")
    utils.echo("─" * 52)
    utils.echo(f"  email   {info.email or '(unknown)'}")
    utils.echo(f"  plan    {utils.fmt_plan(info.plan)}")
    utils.echo(f"  token   {utils.fmt_token_status(info)}")
    utils.echo("\n  fetching live quota…")
    try:
        q = api.fetch_quota(info.access_token)
    except api.ApiError as e:
        utils.die(f"could not fetch quota: {e}")

    utils.echo("")
    utils.echo("  5-hour window")
    if q.primary:
        utils.echo(f"    used    {utils.progress_bar(q.primary.used_percent)}")
        utils.echo(
            f"    resets  in {utils.fmt_duration(q.primary.reset_after_seconds)} "
            f"(window: {q.primary.limit_window_seconds // 3600}h)"
        )
    else:
        utils.echo("    (no data)")

    utils.echo("\n  weekly window")
    if q.secondary:
        utils.echo(f"    used    {utils.progress_bar(q.secondary.used_percent)}")
        utils.echo(
            f"    resets  in {utils.fmt_duration(q.secondary.reset_after_seconds)} (window: 7d)"
        )
    else:
        utils.echo("    (no data)")

    utils.echo("")
    if not q.allowed:
        utils.echo("  " + utils.red("⛔ throttled — Codex requests are currently blocked"))
    elif q.limit_reached:
        utils.echo("  " + utils.yellow("⚠ quota exhausted — waiting for reset"))
    else:
        utils.echo("  " + utils.green("✓ quota healthy"))

    if q.credits_unlimited:
        utils.echo("  " + utils.dim("credits: unlimited"))
    elif q.credits_balance and q.credits_balance != "0":
        utils.echo(f"  credits: {q.credits_balance}")
    utils.echo("")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    rows = accounts.list_accounts()
    if not rows:
        utils.echo("  no accounts to refresh")
        return 0

    utils.echo(f"refreshing 5h window for {len(rows)} account(s)…\n")
    activated = skipped = errors = 0
    for i, acct in enumerate(rows):
        info = accounts.read_auth(acct.name)
        if info is None:
            utils.echo(f"  {utils.dim('skip')}  {acct.name}: no auth.json")
            errors += 1
            continue
        if info.is_expired:
            utils.echo(f"  {utils.dim('skip')}  {acct.name}: token expired")
            errors += 1
            continue
        try:
            q = api.fetch_quota(info.access_token)
        except api.ApiError as e:
            utils.echo(f"  {utils.red('err ')}  {acct.name}: {e}")
            errors += 1
            continue
        used = q.primary.used_percent if q.primary else 0
        if used > 0:
            utils.echo(f"  {utils.green('ok  ')}  {acct.name}: already active ({int(used)}% used)")
            skipped += 1
            continue

        utils.echo(
            f"  {utils.yellow('open')}  {acct.name}: 5h window cold, activating…",
        )
        if args.dry_run:
            utils.echo(f"          (dry-run: would call {config.RESPONSES_URL})")
            continue
        try:
            api.activate_window(info.access_token, info.account_id)
            utils.ok(f"        {acct.name}: window opened")
            activated += 1
        except api.ApiError as e:
            utils.echo(f"  {utils.red('err ')}  {acct.name}: activation failed — {e}")
            errors += 1

        if i < len(rows) - 1 and args.delay > 0:
            utils.echo(utils.dim(f"          sleeping {args.delay}s before next account…"))
            time.sleep(args.delay)

    utils.echo(f"\n  activated={activated}  skipped={skipped}  errors={errors}\n")
    return 0 if errors == 0 else 1


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Diagnostic dump for bug reports."""
    utils.echo(f"codex-accounts {__version__}")
    utils.echo(f"  python        {sys.version.split()[0]}")
    utils.echo(f"  platform      {sys.platform}")
    utils.echo(
        f"  codex home    {config.codex_home()}  "
        f"{'[exists]' if config.codex_home().is_dir() else '[MISSING]'}"
    )
    utils.echo(
        f"  accounts home {config.accounts_home()}  "
        f"{'[exists]' if config.accounts_home().is_dir() else '[missing]'}"
    )
    utils.echo(f"  current       {accounts.current_name() or '(none)'}")
    utils.echo(f"  codex running {'yes' if utils.is_codex_running() else 'no'}")
    n = len(accounts.list_accounts())
    utils.echo(f"  saved accts   {n}")
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Manage multiple OpenAI Codex desktop accounts.",
        epilog=f"Run `{PROG} <command> --help` for command-specific options.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    sp = sub.add_parser("list", help="list saved accounts")
    sp.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="also fetch live 5h/weekly quota (requires network)",
    )
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("current", help="print the active account name")
    sp.set_defaults(func=cmd_current)

    sp = sub.add_parser("info", help="show account details")
    sp.add_argument("name", nargs="?", help="account name (default: current)")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("save", help="snapshot live Codex state under <name>")
    sp.add_argument("name")
    sp.add_argument(
        "--auth-only", action="store_true", help="only snapshot auth.json (skip session DBs)"
    )
    sp.set_defaults(func=cmd_save)

    sp = sub.add_parser("use", help="activate a saved account")
    sp.add_argument("name")
    sp.add_argument(
        "--no-share-sessions",
        action="store_true",
        help="full isolation: also swap session DBs and history",
    )
    sp.add_argument("-f", "--force", action="store_true", help="skip the 'is Codex running?' check")
    sp.set_defaults(func=cmd_use)

    sp = sub.add_parser("init", help="create an empty account snapshot directory")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("note", help="set a free-text note on an account")
    sp.add_argument("name")
    sp.add_argument("text")
    sp.set_defaults(func=cmd_note)

    sp = sub.add_parser(
        "billing",
        help="set/show the monthly billing date (auto-rolls forward)",
        description=(
            "Store the renewal date for an account. Treated as the anchor of "
            "a monthly cycle: the stored value is preserved, and display auto-"
            "rolls forward to the next occurrence (clamped to month length)."
        ),
    )
    sp.add_argument("name")
    sp.add_argument(
        "date",
        nargs="?",
        help="anchor date as YYYY-MM-DD (any past or future date that matches the cycle)",
    )
    sp.add_argument("--clear", action="store_true", help="remove the stored renewal date")
    sp.set_defaults(func=cmd_billing)

    sp = sub.add_parser("rename", help="rename an account")
    sp.add_argument("old")
    sp.add_argument("new")
    sp.set_defaults(func=cmd_rename)

    sp = sub.add_parser("delete", help="delete an account snapshot")
    sp.add_argument("name")
    sp.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    sp.set_defaults(func=cmd_delete)

    sp = sub.add_parser("stats", help="local token usage from state_*.sqlite")
    sp.add_argument("name", nargs="?", help="account name (default: current)")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("quota", help="live 5h/weekly quota (requires network)")
    sp.add_argument("name", nargs="?", help="account name (default: current)")
    sp.set_defaults(func=cmd_quota)

    sp = sub.add_parser(
        "refresh",
        help="open the 5h window on every account that hasn't used it today",
    )
    sp.add_argument(
        "--delay", type=int, default=30, help="seconds to wait between accounts (default: 30)"
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be activated without sending requests",
    )
    sp.set_defaults(func=cmd_refresh)

    sp = sub.add_parser("doctor", help="print environment diagnostics for bug reports")
    sp.set_defaults(func=cmd_doctor)

    return p


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        utils.echo("")
        utils.warn("interrupted")
        return 130
