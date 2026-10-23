"""Unit tests for the standalone helpers in :mod:`codex_switch.utils`."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date

import pytest

from codex_switch import utils
from tests.conftest import _make_jwt


@pytest.mark.parametrize(
    "macos,process_name,arguments,expected",
    [
        (True, "Codex", "", True),
        (True, "ChatGPT", "", True),
        (True, "codex", "app-server", True),
        (True, "uv", "--auth /Users/shaw/.codex/auth.json", False),
        (True, "python3.11", "codex-accounts use work", False),
        (False, "codex", "", True),
        (False, "python3", "--auth /home/user/.codex/auth.json", False),
    ],
)
def test_running_detection_matches_client_names(
    monkeypatch,
    macos,
    process_name,
    arguments,
    expected,
):
    monkeypatch.setattr(utils.config, "IS_MACOS", macos)
    monkeypatch.setattr(utils.config, "IS_LINUX", not macos)
    monkeypatch.setattr(utils.shutil, "which", lambda _: "/usr/bin/pgrep")

    def run(args, **kwargs):
        # Model pgrep's name-vs-command matching so path arguments cannot
        # accidentally turn a non-client process into a running client.
        candidate = process_name if "-f" not in args else f"{process_name} {arguments}"
        match = (re.fullmatch if "-x" in args else re.search)(args[-1], candidate)
        return subprocess.CompletedProcess(args, 0 if match else 1, b"123\n" if match else b"")

    monkeypatch.setattr(utils.subprocess, "run", run)

    assert utils.is_codex_running() is expected


@pytest.mark.parametrize(
    "anchor,today,expected",
    [
        # Anchor already in the future → returned unchanged.
        (date(2026, 7, 15), date(2026, 6, 9), date(2026, 7, 15)),
        # Anchor today → unchanged.
        (date(2026, 6, 9), date(2026, 6, 9), date(2026, 6, 9)),
        # One month past → next month, same day.
        (date(2026, 5, 9), date(2026, 6, 9), date(2026, 6, 9)),
        # Several months past → rolls to nearest future occurrence.
        (date(2026, 1, 15), date(2026, 6, 9), date(2026, 6, 15)),
        # Day-of-month clamped to month length: Jan-31 anchor → Feb-28 in non-leap.
        (date(2025, 1, 31), date(2025, 2, 15), date(2025, 2, 28)),
        # After clamp, next month restores the original day.
        (date(2025, 1, 31), date(2025, 3, 1), date(2025, 3, 31)),
        # Leap year: Jan-31 anchor → Feb-29 in 2024.
        (date(2024, 1, 31), date(2024, 2, 15), date(2024, 2, 29)),
        # Crosses year boundary.
        (date(2025, 12, 20), date(2026, 1, 5), date(2026, 1, 20)),
    ],
)
def test_next_renewal_date(anchor, today, expected):
    assert utils.next_renewal_date(anchor, today) == expected


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
