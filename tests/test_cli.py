"""Smoke tests around the CLI entry point."""

from __future__ import annotations

import pytest

from codex_switch import accounts, cli, processes


def test_help_exits_clean(capsys):
    parser = cli.build_parser()
    try:
        parser.parse_args(["--help"])
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert "codex-accounts" in out
    assert "list" in out
    assert "app" in out
    assert "kill" not in out


def test_version_flag(capsys):
    from codex_switch import __version__

    try:
        cli.main(["--version"])
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert __version__ in out


def test_list_empty(codex_env, capsys):
    rc = cli.main(["list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no accounts saved" in out


def test_save_then_list(codex_env, capsys):
    codex_env.seed_live_account(email="ci@example.com")
    rc = cli.main(["save", "ci", "--auth-only"])
    assert rc == 0
    capsys.readouterr()

    rc = cli.main(["list"])
    out = capsys.readouterr().out
    assert "ci" in out
    assert "ci@example.com" in out


def _seed_switch_accounts(codex_env):
    codex_env.seed_live_account(email="saved@example.com")
    accounts.save_account("saved")
    codex_env.clear_live_account()
    codex_env.seed_live_account(email="current@example.com")
    accounts.save_account("current")
    accounts.set_current("current")


def test_use_auth_only_skips_running_warning_and_preserves_sessions(
    codex_env,
    monkeypatch,
    capsys,
):
    _seed_switch_accounts(codex_env)
    monkeypatch.setattr(cli.utils, "is_codex_running", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("auth switch must not prompt"))
    db = codex_env.codex / "state_5.sqlite"
    before_db = db.read_bytes()
    session = codex_env.codex / "sessions" / "current.jsonl"
    session.write_text("keep current session\n")

    assert cli.main(["use", "saved"]) == 0

    captured = capsys.readouterr()
    assert "SQLite" not in captured.err
    assert "Codex is running" not in captured.err
    assert "switched to: saved" in captured.out
    assert accounts.current_name() == "saved"
    assert accounts.read_auth("saved").email == "saved@example.com"
    assert accounts.read_auth("current").email == "current@example.com"
    assert db.read_bytes() == before_db
    assert session.read_text() == "keep current session\n"


def test_use_full_running_decline_leaves_account_unchanged(codex_env, monkeypatch, capsys):
    _seed_switch_accounts(codex_env)
    before_auth = (codex_env.codex / "auth.json").read_bytes()
    monkeypatch.setattr(cli.utils, "is_codex_running", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "n")

    with pytest.raises(SystemExit) as exc:
        cli.main(["use", "saved", "--no-share-sessions"])

    assert exc.value.code == 1
    assert "SQLite lock issues" in capsys.readouterr().err
    assert accounts.current_name() == "current"
    assert (codex_env.codex / "auth.json").read_bytes() == before_auth


@pytest.mark.parametrize("force", [False, True])
def test_use_full_running_confirmation_and_force(codex_env, monkeypatch, capsys, force):
    _seed_switch_accounts(codex_env)
    session = codex_env.codex / "sessions" / "current.jsonl"
    session.write_text("current-only session\n")
    monkeypatch.setattr(cli.utils, "is_codex_running", lambda: True)
    monkeypatch.setattr(
        "builtins.input",
        lambda _: pytest.fail("--force must not prompt") if force else "y",
    )
    args = ["use", "saved", "--no-share-sessions"]
    if force:
        args.append("--force")

    assert cli.main(args) == 0

    assert "SQLite lock issues" in capsys.readouterr().err
    assert accounts.current_name() == "saved"
    assert not session.exists()
    assert (codex_env.accounts_dir / "current" / "dirs" / "sessions" / session.name).exists()


def test_doctor_runs(codex_env, capsys):
    rc = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "codex-accounts" in out
    assert "python" in out


def test_status_runs(codex_env, monkeypatch, capsys):
    from codex_switch import status as status_mod

    monkeypatch.setattr(status_mod.processes, "is_supported_platform", lambda: False)
    rc = cli.main(["status"])
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert "Codex Status" in out
    assert "account" in out


def test_status_json_runs(codex_env, monkeypatch, capsys):
    from codex_switch import status as status_mod

    monkeypatch.setattr(status_mod.processes, "is_supported_platform", lambda: False)
    rc = cli.main(["status", "--json"])
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert '"verdict"' in out


def test_app_status_runs(codex_env, monkeypatch, capsys):
    from codex_switch import status as status_mod

    monkeypatch.setattr(status_mod.processes, "is_supported_platform", lambda: False)
    rc = cli.main(["app", "status"])
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert "Codex Status" in out


def test_app_doctor_runs(codex_env, monkeypatch, capsys):
    from codex_switch import status as status_mod

    monkeypatch.setattr(status_mod.processes, "is_supported_platform", lambda: False)
    rc = cli.main(["app", "doctor"])
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert "Codex Reconnect Doctor" in out
    assert "live probe skipped" in out


def test_app_doctor_json_runs(codex_env, monkeypatch, capsys):
    from codex_switch import status as status_mod

    monkeypatch.setattr(status_mod.processes, "is_supported_platform", lambda: False)
    rc = cli.main(["app", "doctor", "--json"])
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert '"verdict"' in out
    assert '"network"' in out


def test_app_help_lists_runtime_commands(capsys):
    parser = cli.build_parser()
    try:
        parser.parse_args(["app", "--help"])
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert "status" in out
    assert "doctor" in out
    assert "kill" in out
    assert "gc" in out


def test_app_kill_help_lists_user_facing_actions(capsys):
    parser = cli.build_parser()
    try:
        parser.parse_args(["app", "kill", "--help"])
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert "stale" in out
    assert "app-server" not in out
    assert "node-repl" not in out


def test_app_gc_runs(codex_env, capsys):
    (codex_env.codex / ".tmp" / "bundled-marketplaces").mkdir(parents=True)
    rc = cli.main(["app", "gc"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Codex App GC" in out
    assert "dry-run only" in out


def test_app_gc_json_runs(codex_env, capsys):
    rc = cli.main(["app", "gc", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"total_candidate_bytes"' in out


def test_app_gc_clean_requires_yes(codex_env, capsys):
    rc = 0
    try:
        cli.main(["app", "gc", "clean", "--category", "temporary staging"])
    except SystemExit as e:
        rc = e.code
    err = capsys.readouterr().err
    assert rc == 1
    assert "--yes" in err


def test_app_gc_clean_deletes_selected_remove_candidate(codex_env, monkeypatch, capsys):
    import os
    import time

    monkeypatch.setattr(cli.utils, "is_codex_running", lambda: False)
    staging = codex_env.codex / ".tmp" / "bundled-marketplaces" / "openai-bundled.staging-old"
    staging.mkdir(parents=True)
    (staging / "blob").write_text("x" * 10, encoding="utf-8")
    old = time.time() - 30 * 86400
    os.utime(staging, (old, old))

    rc = cli.main(["app", "gc", "clean", "--category", "temporary staging", "--yes"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "removed" in out
    assert not staging.exists()


def test_app_gc_clean_dry_run_keeps_selected_candidate(codex_env, capsys):
    import os
    import time

    staging = codex_env.codex / ".tmp" / "bundled-marketplaces" / "openai-bundled.staging-old"
    staging.mkdir(parents=True)
    (staging / "blob").write_text("x" * 10, encoding="utf-8")
    old = time.time() - 30 * 86400
    os.utime(staging, (old, old))

    rc = cli.main(["app", "gc", "clean", "--category", "temporary staging", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "would remove" in out
    assert staging.exists()


def test_kill_list_empty(monkeypatch, capsys):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: True)
    monkeypatch.setattr(processes, "list_stale_processes", lambda: [])
    rc = cli.main(["app", "kill"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no Codex Desktop background processes" in out


def test_top_level_kill_remains_as_hidden_compatibility_alias(monkeypatch, capsys):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: True)
    monkeypatch.setattr(processes, "list_stale_processes", lambda: [])
    rc = cli.main(["kill", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no Codex Desktop background processes" in out


def test_kill_list_processes(monkeypatch, capsys):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: True)
    proc = processes.CodexProcess(
        pid=123,
        ppid=1,
        cpu="0.0",
        mem="0.1",
        kind="background service",
        command="/Applications/ChatGPT.app/Contents/Resources/codex app-server",
    )
    monkeypatch.setattr(processes, "list_stale_processes", lambda: [proc])
    rc = cli.main(["app", "kill", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "background service" in out
    assert "123" in out


def test_kill_stale_refuses_when_chatgpt_running(monkeypatch, capsys):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: True)
    monkeypatch.setattr(processes, "list_stale_processes", lambda: [])

    def still_running():
        raise processes.ChatGPTStillRunning("running")

    monkeypatch.setattr(processes, "terminate_stale_processes", still_running)
    rc = cli.main(["app", "kill", "stale"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "still running" in err


def test_kill_stale_refuses_when_background_process_has_live_parent(monkeypatch, capsys):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: True)
    proc = processes.CodexProcess(
        pid=123,
        ppid=42,
        cpu="0.0",
        mem="0.1",
        kind="background service",
        command="/Applications/ChatGPT.app/Contents/Resources/codex app-server",
    )
    monkeypatch.setattr(processes, "is_chatgpt_app_running", lambda: False)
    monkeypatch.setattr(processes, "list_stale_processes", lambda: [proc])
    monkeypatch.setattr(processes, "_pid_exists", lambda pid: pid == 42)

    def fail_kill(*_args):
        raise AssertionError("must not signal processes with a live external parent")

    monkeypatch.setattr(processes.os, "kill", fail_kill)
    rc = cli.main(["app", "kill", "stale"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "still running" in err


def test_kill_stale_signals_processes(monkeypatch, capsys):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: True)
    proc = processes.CodexProcess(
        pid=123,
        ppid=1,
        cpu="0.0",
        mem="0.1",
        kind="tool runtime",
        command="/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node_repl",
    )
    monkeypatch.setattr(
        processes,
        "terminate_stale_processes",
        lambda: processes.KillResult(
            found=[proc],
            signaled=[proc],
            missing=[],
            failed=[],
            remaining=[],
        ),
    )
    rc = cli.main(["app", "kill", "stale"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "signaled tool runtime" in out


def test_kill_stale_signals_computer_use_service(monkeypatch, capsys):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: True)
    proc = processes.CodexProcess(
        pid=124,
        ppid=1,
        cpu="0.0",
        mem="0.1",
        kind="tool service",
        command="/Users/me/.codex/computer-use/Codex Computer Use.app/Contents/MacOS/SkyComputerUseService",
    )
    monkeypatch.setattr(
        processes,
        "terminate_stale_processes",
        lambda: processes.KillResult(
            found=[proc],
            signaled=[proc],
            missing=[],
            failed=[],
            remaining=[],
        ),
    )
    rc = cli.main(["app", "kill", "stale"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "signaled tool service" in out


def test_kill_list_on_unsupported_platform(monkeypatch, capsys):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: False)
    rc = cli.main(["app", "kill", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "macOS" in out


def test_kill_stale_on_unsupported_platform(monkeypatch, capsys):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: False)
    rc = cli.main(["app", "kill", "stale"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "macOS" in err


def test_billing_set_show_and_clear(codex_env, capsys):
    import json as _json
    from datetime import date, timedelta

    codex_env.seed_live_account()
    cli.main(["save", "demo", "--auth-only"])
    capsys.readouterr()

    future = (date.today() + timedelta(days=15)).isoformat()

    rc = cli.main(["billing", "demo", future])
    out = capsys.readouterr().out
    assert rc == 0
    assert future in out
    assert "15d" in out

    meta_path = codex_env.accounts_dir / "demo" / "meta.json"
    assert _json.load(meta_path.open())["renews_at"] == future

    rc = cli.main(["list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "renews" in out  # header column appears when any account has it

    rc = cli.main(["info", "demo"])
    out = capsys.readouterr().out
    assert rc == 0
    assert future in out

    rc = cli.main(["billing", "demo", "--clear"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "cleared" in out
    assert "renews_at" not in _json.load(meta_path.open())


def test_billing_auto_rolls_past_anchor(codex_env, capsys):
    import json as _json
    from datetime import date, timedelta

    codex_env.seed_live_account()
    cli.main(["save", "demo", "--auth-only"])
    capsys.readouterr()

    # Anchor ~2 months in the past — should be stored as-is, displayed rolled.
    anchor = (date.today() - timedelta(days=70)).isoformat()
    cli.main(["billing", "demo", anchor])
    set_out = capsys.readouterr().out
    assert "auto-rolled" in set_out

    meta_path = codex_env.accounts_dir / "demo" / "meta.json"
    assert _json.load(meta_path.open())["renews_at"] == anchor

    cli.main(["billing", "demo"])
    show_out = capsys.readouterr().out
    # First line is "demo: renews <next-date> (in Nd)" — must NOT show the
    # raw past anchor. (A second dim line discloses the anchor for context.)
    assert anchor not in show_out.splitlines()[0]
    assert "monthly" in show_out

    cli.main(["list"])
    list_out = capsys.readouterr().out
    assert "renews" in list_out  # header column appears


def test_billing_rejects_bad_date(codex_env, capsys):
    codex_env.seed_live_account()
    cli.main(["save", "demo", "--auth-only"])
    capsys.readouterr()
    try:
        cli.main(["billing", "demo", "not-a-date"])
    except SystemExit as e:
        assert e.code == 1
    err = capsys.readouterr().err
    assert "YYYY-MM-DD" in err


def test_stats_on_seeded_db(codex_env, capsys):
    codex_env.seed_live_account()
    cli.main(["save", "demo", "--auth-only"])
    accounts.set_current("demo")
    # Stats needs a state DB; in auth-only mode the snapshot has none, so
    # we read directly from the live home (current account points there).
    capsys.readouterr()
    rc = cli.main(["stats"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Usage stats" in out
    assert "total tokens" in out
