"""Smoke tests around the CLI entry point."""

from __future__ import annotations

from codex_switch import accounts, cli


def test_help_exits_clean(capsys):
    parser = cli.build_parser()
    try:
        parser.parse_args(["--help"])
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert "codex-accounts" in out
    assert "list" in out


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


def test_doctor_runs(codex_env, capsys):
    rc = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "codex-accounts" in out
    assert "python" in out


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
