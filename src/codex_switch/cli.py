"""argparse-based command-line interface."""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

from codex_switch import (
    __version__,
    accounts,
    api,
    cleanup,
    config,
    processes,
    stats,
    status,
    utils,
)
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

    mode = SwapMode.FULL if args.no_share_sessions else SwapMode.AUTH
    if mode is SwapMode.FULL:
        _confirm_codex_closed(force=args.force)

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


def cmd_kill(args: argparse.Namespace) -> int:
    """List or clean Codex Desktop background processes."""

    if not processes.is_supported_platform():
        msg = "kill is currently supported only for the macOS ChatGPT/Codex desktop app"
        if args.action == "list":
            utils.echo(msg)
            return 0
        utils.warn(msg)
        return 1

    if args.action == "list":
        _print_stale_processes(processes.list_stale_processes())
        return 0

    if args.dry_run:
        _print_stale_processes(processes.list_stale_processes())
        utils.echo(utils.dim("dry-run: no processes were signaled"))
        return 0

    try:
        result = processes.terminate_stale_processes()
    except processes.UnsupportedPlatform as e:
        utils.warn(str(e))
        return 1
    except processes.ChatGPTStillRunning:
        utils.warn("ChatGPT/Codex is still running; quit it before cleaning stale processes.")
        _print_stale_processes(processes.list_stale_processes())
        return 1

    if not result.found:
        utils.echo("no Codex Desktop background processes found")
        return 0

    for proc in result.signaled:
        utils.ok(f"signaled {proc.kind} pid={proc.pid}")
    for proc in result.missing:
        utils.echo(utils.dim(f"already gone {proc.kind} pid={proc.pid}"))
    for proc, err in result.failed:
        utils.warn(f"could not signal {proc.kind} pid={proc.pid}: {err}")

    if result.remaining:
        utils.warn("some Codex Desktop background processes are still running:")
        _print_stale_processes(result.remaining)
        return 1

    utils.ok("no Codex Desktop background processes remain")
    return 0


def _print_stale_processes(rows: list[processes.CodexProcess]) -> None:
    if not rows:
        utils.echo("no Codex Desktop background processes found")
        return

    utils.echo("\nCodex Desktop background processes:")
    utils.echo(utils.dim("  pid      ppid     cpu    mem    kind"))
    utils.echo(utils.dim("  " + "-" * 52))
    for proc in rows:
        utils.echo(f"  {proc.pid:<8} {proc.ppid:<8} {proc.cpu:<6} {proc.mem:<6} {proc.kind}")
    utils.echo("")


def cmd_status(args: argparse.Namespace) -> int:
    """Fast local Codex health summary."""

    report = status.collect_status(since_hours=args.since)
    if args.json:
        utils.echo(status.dumps_json(report))
        return 0 if report.verdict != "ACTION" else 1

    utils.echo(f"\nCodex Status  {utils.bold(report.verdict)}")
    utils.echo("─" * 56)
    account = report.account
    account_name = account.name or "(none)"
    utils.echo(f"  account    {account_name} · {account.email} · {account.token}")
    cfg = report.config
    utils.echo(
        f"  config     {cfg.model} / {cfg.effort} · agents "
        f"{cfg.agents_max_threads}x depth {cfg.agents_max_depth} · "
        f"global AGENTS {status.format_bytes(cfg.global_agents_bytes)}"
    )
    utils.echo(
        f"  mcp        enabled={cfg.mcp_enabled} disabled={cfg.mcp_disabled} "
        f"remote={cfg.mcp_remote} · plugins={cfg.plugins_enabled}"
    )
    proc = report.processes
    process_summary = ", ".join(f"{name}={count}" for name, count in sorted(proc.counts.items()))
    if not process_summary:
        process_summary = "none"
    platform = "macOS" if proc.supported else "unsupported platform"
    running = "running" if proc.chatgpt_running else "not running"
    utils.echo(f"  processes  {platform} · ChatGPT {running} · {process_summary}")
    logs = report.logs
    readable = "" if logs.readable else " · unreadable"
    utils.echo(
        f"  logs {logs.since_hours}h  remote_control={logs.remote_control_warnings} "
        f"responses_retry={logs.responses_retry} mcp_warnings={logs.mcp_warnings} "
        f"plugin_warnings={logs.plugin_warnings} rollout_warnings={logs.rollout_warnings}"
        f"{readable}"
    )
    state = report.state
    active = "?" if state.active_threads is None else f"{state.active_threads:,}"
    archived = "?" if state.archived_threads is None else f"{state.archived_threads:,}"
    subagents = "?" if state.subagent_threads_7d is None else f"{state.subagent_threads_7d:,}"
    utils.echo(
        f"  state      active={active} archived={archived} "
        f"active_rollouts={status.format_bytes(state.active_rollout_bytes)} "
        f"subagents_7d={subagents}"
    )
    if report.reasons:
        utils.echo("\n  signals")
        for reason in report.reasons[:8]:
            utils.echo(f"    - {reason}")
    utils.echo("")
    return 0 if report.verdict != "ACTION" else 1


def cmd_app_doctor(args: argparse.Namespace) -> int:
    """Diagnose Codex Desktop reconnect and streaming failures."""

    report = status.collect_reconnect_diagnosis(since_hours=args.since, live=args.live)
    if args.json:
        utils.echo(status.dumps_reconnect_json(report))
        return 0 if report.verdict != "ACTION" else 1

    utils.echo(f"\nCodex Reconnect Doctor  {utils.bold(report.verdict)}")
    utils.echo("─" * 56)
    logs = report.logs
    readable = "" if logs.readable else " · unreadable"
    utils.echo(
        f"  logs {logs.since_hours}h  tls_eof={logs.tls_handshake_eof} "
        f"broken_pipe={logs.broken_pipe} timeouts={logs.request_timeouts} "
        f"stream_disconnect={logs.stream_disconnected} retry={logs.responses_retry} "
        f"websocket={logs.websocket_errors}{readable}"
    )
    utils.echo(
        f"  remote     remote_control={logs.remote_control_failures} "
        f"mcp_http={logs.mcp_http_failures} plugins={logs.plugin_catalog_failures} "
        f"models={logs.model_refresh_failures}"
    )

    net = report.network
    proxy_apps = ", ".join(net.proxy_apps) if net.proxy_apps else "none"
    network_label = "macOS" if net.supported else "unsupported platform"
    utils.echo(
        f"  network    {network_label} · PAC={'on' if net.pac_enabled else 'off'} "
        f"HTTP={'on' if net.http_proxy_enabled else 'off'} "
        f"HTTPS={'on' if net.https_proxy_enabled else 'off'} "
        f"SOCKS={'on' if net.socks_proxy_enabled else 'off'} · "
        f"utun_routes={net.tun_routes} · proxy_apps={proxy_apps}"
    )
    if net.pac_url:
        utils.echo(f"             PAC URL: {net.pac_url}")
    if net.problem:
        utils.echo(f"             {net.problem}")

    proc = report.processes
    process_summary = ", ".join(f"{name}={count}" for name, count in sorted(proc.counts.items()))
    if not process_summary:
        process_summary = "none"
    running = "running" if proc.chatgpt_running else "not running"
    utils.echo(f"  processes  ChatGPT {running} · {process_summary}")

    if report.probes:
        utils.echo("\n  live probes")
        for probe in report.probes:
            marker = "ok" if probe.ok else "fail"
            notes = f" · {', '.join(probe.notes)}" if probe.notes else ""
            utils.echo(f"    - {marker:<4} {probe.url} · {probe.status}{notes}")
    elif not args.live:
        utils.echo(utils.dim("  live probe skipped; add --live to test OpenAI endpoints"))

    if report.reasons:
        utils.echo("\n  likely signals")
        for reason in report.reasons[:8]:
            utils.echo(f"    - {reason}")
    if report.next_steps:
        utils.echo("\n  next steps")
        for step in report.next_steps[:6]:
            utils.echo(f"    - {step}")
    if report.samples:
        utils.echo("\n  recent samples (sanitized)")
        for sample in report.samples:
            utils.echo(f"    - {sample.level} {sample.target}: {sample.body}")
    utils.echo("")
    return 0 if report.verdict != "ACTION" else 1


def cmd_gc(args: argparse.Namespace) -> int:
    """Show read-only Codex home cleanup candidates."""

    report = cleanup.collect_cleanup_report(older_than_days=args.older_than_days)
    if args.json:
        utils.echo(cleanup.dumps_json(report))
        return 0

    utils.echo(f"\nCodex App GC  {utils.bold('DRY-RUN')}")
    utils.echo("─" * 56)
    utils.echo(f"  home       {report.codex_home}")
    utils.echo(f"  age gate   {report.older_than_days}d for temp/cache candidates")
    utils.echo(
        f"  candidates {status.format_bytes(cleanup.total_candidate_bytes(report))} "
        "(remove/rebuild only)"
    )

    by_action: dict[str, list[cleanup.CleanupItem]] = {}
    for item in report.items:
        by_action.setdefault(item.action, []).append(item)

    labels = {
        "remove": "remove candidates",
        "rebuild": "rebuildable caches",
        "archive": "archive candidates",
        "protect": "protected state",
    }
    for action in ("remove", "rebuild", "archive", "protect"):
        rows = by_action.get(action, [])
        if not rows:
            continue
        utils.echo(f"\n  {labels[action]}")
        for item in sorted(rows, key=lambda row: row.bytes, reverse=True)[: args.limit]:
            count = f" · files={item.count}" if item.count != 1 else ""
            utils.echo(
                f"    - {status.format_bytes(item.bytes):>8} · {item.risk:<6} · "
                f"{item.category}{count}"
            )
            utils.echo(f"      {item.path}")
            utils.echo(utils.dim(f"      {item.reason}"))
        if len(rows) > args.limit:
            utils.echo(utils.dim(f"      ... {len(rows) - args.limit} more"))

    if report.notes:
        utils.echo("\n  notes")
        for note in report.notes:
            utils.echo(f"    - {note}")
    utils.echo("\n  dry-run only: no files were changed\n")
    return 0


def cmd_gc_clean(args: argparse.Namespace) -> int:
    """Clean selected Codex home remove candidates."""

    categories = args.category or []
    paths = args.path or []
    if not categories and not paths:
        utils.die("choose at least one --category or --path from `codex-accounts app gc`")
    if args.action != "remove":
        utils.die("only --action remove is currently supported")
    if not args.dry_run and not args.yes:
        utils.die("refusing to delete without --yes; use --dry-run to preview")
    if not args.dry_run and not args.force and utils.is_codex_running():
        utils.die("ChatGPT/Codex is running; quit it first or pass --force")

    result = cleanup.clean_candidates(
        older_than_days=args.older_than_days,
        categories=categories,
        paths=paths,
        dry_run=args.dry_run,
    )
    if not result.matched:
        utils.echo("no matching remove candidates found")
        return 0

    mode = "DRY-RUN" if result.dry_run else "CLEAN"
    utils.echo(f"\nCodex App GC {utils.bold(mode)}")
    utils.echo("─" * 56)
    utils.echo(
        f"  matched    {len(result.matched)} item(s), {status.format_bytes(result.matched_bytes)}"
    )

    if result.dry_run:
        for item in result.matched:
            utils.echo(f"  would remove {status.format_bytes(item.bytes):>8} · {item.category}")
            utils.echo(f"    {item.path}")
        utils.echo("\n  dry-run only: no files were changed\n")
        return 0

    for item in result.deleted:
        utils.ok(f"removed {item.category}: {item.path}")
    for item in result.missing:
        utils.echo(utils.dim(f"already gone {item.category}: {item.path}"))
    for item, err in result.failed:
        utils.warn(f"failed {item.category}: {item.path}: {err}")

    utils.echo(
        f"\n  removed    {len(result.deleted)} item(s), {status.format_bytes(result.deleted_bytes)}"
    )
    if result.failed:
        return 1
    utils.echo("")
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def _add_status_parser(subparsers: argparse._SubParsersAction) -> None:
    sp = subparsers.add_parser(
        "status",
        help="fast local Codex health summary",
        description="Show a read-only, offline summary of local Codex health signals.",
    )
    sp.add_argument("--since", type=int, default=24, help="hours of logs to scan (default: 24)")
    sp.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sp.set_defaults(func=cmd_status)


def _add_app_doctor_parser(subparsers: argparse._SubParsersAction) -> None:
    sp = subparsers.add_parser(
        "doctor",
        help="diagnose Codex Desktop reconnect failures",
        description=(
            "Diagnose Codex Desktop reconnect, WebSocket, TLS EOF, broken-pipe, "
            "and timeout failures from local logs and runtime state. Network probes "
            "run only when --live is passed."
        ),
    )
    sp.add_argument("--since", type=int, default=1, help="hours of logs to scan (default: 1)")
    sp.add_argument("--live", action="store_true", help="run lightweight live HTTP probes")
    sp.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sp.set_defaults(func=cmd_app_doctor)


def _add_kill_parser(subparsers: argparse._SubParsersAction) -> None:
    sp = subparsers.add_parser(
        "kill",
        help="list or clean Codex Desktop background processes",
        description=(
            "List Codex Desktop background processes, or clean stale processes "
            "after ChatGPT/Codex has quit. Currently supports the macOS desktop app."
        ),
    )
    sp.add_argument(
        "action",
        nargs="?",
        choices=("list", "stale"),
        default="list",
        help="list background processes or clean stale ones (default: list)",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="show matching processes without terminating them",
    )
    sp.set_defaults(func=cmd_kill)


def _add_gc_parser(subparsers: argparse._SubParsersAction) -> None:
    sp = subparsers.add_parser(
        "gc",
        help="show Codex home cleanup candidates",
        description=(
            "Classify large Codex home storage into remove, rebuild, archive, "
            "and protected buckets. Use `gc clean` for explicit remove-candidate cleanup."
        ),
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="accepted for clarity; gc is currently always read-only",
    )
    sp.add_argument(
        "--older-than-days",
        type=int,
        default=7,
        help="minimum age for temp/cache candidates (default: 7)",
    )
    sp.add_argument("--limit", type=int, default=12, help="items to show per bucket (default: 12)")
    sp.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sp.set_defaults(func=cmd_gc)

    gc_sub = sp.add_subparsers(dest="gc_command", metavar="<gc-command>")
    clean_sp = gc_sub.add_parser(
        "clean",
        help="delete selected remove candidates",
        description=(
            "Delete selected items that currently appear in the remove bucket. "
            "Archive, rebuild, and protected buckets are never deleted by this command."
        ),
    )
    clean_sp.add_argument(
        "--action",
        choices=("remove",),
        default="remove",
        help="candidate action to clean (default: remove)",
    )
    clean_sp.add_argument(
        "--category",
        action="append",
        help="remove candidates from this exact category; may be repeated",
    )
    clean_sp.add_argument(
        "--path",
        action="append",
        help="remove this exact path when it appears in the current remove bucket",
    )
    clean_sp.add_argument(
        "--older-than-days",
        type=int,
        default=7,
        help="minimum age for temp/cache candidates (default: 7)",
    )
    clean_sp.add_argument("--dry-run", action="store_true", help="preview selected deletions")
    clean_sp.add_argument("--yes", action="store_true", help="confirm deletion")
    clean_sp.add_argument(
        "--force",
        action="store_true",
        help="allow cleanup while ChatGPT/Codex appears to be running",
    )
    clean_sp.set_defaults(func=cmd_gc_clean)


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
    sp.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="skip the running-client confirmation for --no-share-sessions",
    )
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

    # Runtime/app commands live under `app`; top-level `status` remains a
    # short alias because it is a frequent read-only check.
    sp = sub.add_parser(
        "app",
        help="manage Codex Desktop runtime",
        description="Inspect and manage local Codex Desktop runtime state.",
    )
    app_sub = sp.add_subparsers(dest="app_command", metavar="<app-command>")
    app_sub.required = True
    _add_status_parser(app_sub)
    _add_app_doctor_parser(app_sub)
    _add_kill_parser(app_sub)
    _add_gc_parser(app_sub)

    _add_status_parser(sub)

    return p


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "kill":
        argv = ["app", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        utils.echo("")
        utils.warn("interrupted")
        return 130
