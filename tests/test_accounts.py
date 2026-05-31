"""Integration tests for save / load / list / rename / delete."""

from __future__ import annotations

import pytest

from codex_switch import accounts
from codex_switch.accounts import SwapMode


def test_save_and_load_full_isolates_sessions(codex_env):
    codex_env.seed_live_account(email="work@example.com")

    accounts.save_account("work", mode=SwapMode.FULL)
    assert (codex_env.accounts_dir / "work" / "auth.json").is_file()
    assert (codex_env.accounts_dir / "work" / "state_5.sqlite").is_file()
    assert (codex_env.accounts_dir / "work" / "dirs" / "sessions").is_dir()
    accounts.set_current("work")

    # Switch out: clear live, seed a new account.
    codex_env.clear_live_account()
    codex_env.seed_live_account(email="personal@example.com")
    accounts.save_account("personal", mode=SwapMode.FULL)
    accounts.set_current("personal")

    # Switch back to work; expect work's email to be restored.
    accounts.load_account("work", mode=SwapMode.FULL)
    info = accounts.read_auth("work")
    assert info is not None
    assert info.email == "work@example.com"
    assert accounts.current_name() == "work"


def test_save_auth_only_does_not_copy_state(codex_env):
    codex_env.seed_live_account(email="auth-only@example.com")
    accounts.save_account("auth-only-acct", mode=SwapMode.AUTH)
    snap = codex_env.accounts_dir / "auth-only-acct"
    assert (snap / "auth.json").is_file()
    assert not (snap / "state_5.sqlite").exists()


def test_list_accounts_sorted(codex_env):
    codex_env.seed_live_account()
    for name in ("zeta", "alpha", "Mike"):
        accounts.save_account(name, mode=SwapMode.AUTH)
    names = [a.name for a in accounts.list_accounts()]
    assert names == sorted(names, key=str.lower)


def test_init_account_creates_empty_dir(codex_env):
    accounts.init_account("newbie")
    snap = codex_env.accounts_dir / "newbie"
    assert snap.is_dir()
    assert (snap / "dirs").is_dir()
    assert not (snap / "auth.json").exists()


def test_init_rejects_existing(codex_env):
    accounts.init_account("x")
    with pytest.raises(FileExistsError):
        accounts.init_account("x")


def test_rename_account(codex_env):
    codex_env.seed_live_account()
    accounts.save_account("old", mode=SwapMode.AUTH)
    accounts.set_current("old")
    accounts.rename_account("old", "new")
    assert accounts.current_name() == "new"
    assert not (codex_env.accounts_dir / "old").exists()
    assert (codex_env.accounts_dir / "new").exists()


def test_delete_account(codex_env):
    codex_env.seed_live_account()
    accounts.save_account("garbage", mode=SwapMode.AUTH)
    # Ensure not current.
    accounts.set_current("some-other")
    accounts.delete_account("garbage")
    assert not (codex_env.accounts_dir / "garbage").exists()


def test_cannot_delete_current(codex_env):
    codex_env.seed_live_account()
    accounts.save_account("active", mode=SwapMode.AUTH)
    accounts.set_current("active")
    with pytest.raises(RuntimeError):
        accounts.delete_account("active")


def test_invalid_name_rejected(codex_env):
    with pytest.raises(ValueError):
        accounts.init_account("../escape")


def test_note_roundtrip(codex_env):
    accounts.init_account("noted")
    accounts.set_note("noted", "my main workspace")
    acct = accounts.get_account("noted")
    assert acct.read_meta()["notes"] == "my main workspace"
