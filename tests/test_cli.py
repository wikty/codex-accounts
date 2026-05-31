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
