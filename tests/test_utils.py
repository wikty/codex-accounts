"""Unit tests for the standalone helpers in :mod:`codex_switch.utils`."""

from __future__ import annotations

import json

import pytest

from codex_switch import utils
from tests.conftest import _make_jwt


@pytest.mark.parametrize(
    "name",
    ["work", "Work", "team-1", "user_name", "a.b", "a", "A1"],
)
def test_validate_account_name_accepts(name):
    assert utils.validate_account_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["", ".hidden", "../etc", "with space", "weird/name", "name\n", "a" * 100, "-leading"],
)
def test_validate_account_name_rejects(name):
    with pytest.raises(ValueError):
        utils.validate_account_name(name)


def test_decode_auth_file_roundtrip(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "tokens": {"access_token": _make_jwt(email="me@x.io", plan="pro")},
                "auth_mode": "chatgpt",
            }
        ),
        encoding="utf-8",
    )
    info = utils.decode_auth_file(auth)
    assert info is not None
    assert info.email == "me@x.io"
    assert info.plan == "pro"
    assert info.auth_mode == "chatgpt"
    assert info.is_expired is False


def test_decode_auth_file_missing(tmp_path):
    assert utils.decode_auth_file(tmp_path / "nope.json") is None


def test_decode_auth_file_garbage(tmp_path):
    p = tmp_path / "auth.json"
    p.write_text("not json", encoding="utf-8")
    assert utils.decode_auth_file(p) is None


def test_fmt_duration_buckets():
    assert utils.fmt_duration(-1) == "now"
    assert utils.fmt_duration(30) == "30s"
    assert utils.fmt_duration(90) == "1m"
    assert utils.fmt_duration(3700) == "1h1m"
    assert utils.fmt_duration(7200) == "2h"


def test_progress_bar_clamps():
    bar_low = utils.progress_bar(-5)
    bar_high = utils.progress_bar(150)
    assert "  0%" in bar_low
    assert "100%" in bar_high


def test_ensure_private_dir_sets_mode(tmp_path):
    d = tmp_path / "private"
    utils.ensure_private_dir(d)
    assert d.is_dir()
    import os
    import sys

    if not sys.platform.startswith("win"):
        mode = os.stat(d).st_mode & 0o777
        assert mode == 0o700
