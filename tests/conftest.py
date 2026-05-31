"""Pytest fixtures.

Every test gets a freshly isolated ``CODEX_HOME`` and ``CODEX_SWITCH_HOME``
so that real user data is never touched.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import time
from pathlib import Path

import pytest


def _make_jwt(
    email: str = "user@example.com",
    plan: str = "plus",
    account_id: str = "user-AAAAAA",
    user_id: str = "user-AAAAAA",
    exp_offset: int = 7 * 86400,
) -> str:
    """Build a syntactically valid (but unsigned) JWT for tests."""
    header = {"alg": "none", "typ": "JWT"}
    payload = {
        "https://api.openai.com/profile": {"email": email, "email_verified": True},
        "https://api.openai.com/auth": {
            "chatgpt_plan_type": plan,
            "chatgpt_account_id": account_id,
            "chatgpt_user_id": user_id,
        },
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_offset,
    }

    def _b64(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return f"{_b64(header)}.{_b64(payload)}.signature"


def _write_auth_json(path: Path, **jwt_kwargs) -> None:
    payload = {
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": _make_jwt(**jwt_kwargs),
            "access_token": _make_jwt(**jwt_kwargs),
            "refresh_token": "rt-test",
            "account_id": jwt_kwargs.get("account_id", "user-AAAAAA"),
        },
        "auth_mode": "chatgpt",
        "last_refresh": "2026-01-01T00:00:00Z",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_state_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE threads (
                id INTEGER PRIMARY KEY,
                title TEXT,
                model TEXT,
                tokens_used INTEGER,
                created_at INTEGER,
                created_at_ms INTEGER
            )
            """
        )
        now_ms = int(time.time() * 1000)
        rows = [
            ("recent thread", "gpt-5", 1234, None, now_ms - 60_000),
            ("yesterday", "gpt-5", 4321, None, now_ms - 86_400_000),
            ("a month ago", "gpt-5-mini", 999, None, now_ms - 30 * 86_400_000),
        ]
        conn.executemany(
            "INSERT INTO threads (title, model, tokens_used, created_at, created_at_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def codex_env(tmp_path, monkeypatch):
    """Isolated Codex home + accounts home + helpers to seed live state."""
    codex_home = tmp_path / "codex"
    accounts_home = tmp_path / "codex-accounts"
    codex_home.mkdir()
    accounts_home.mkdir()

    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_SWITCH_HOME", str(accounts_home))

    # Reload config so the env vars take effect for any modules that cached them.
    from codex_switch import config as cfg

    assert cfg.codex_home() == codex_home
    assert cfg.accounts_home() == accounts_home

    class Helpers:
        codex = codex_home
        accounts_dir = accounts_home

        def seed_live_account(
            self, email: str = "user@example.com", plan: str = "plus", **kw
        ) -> None:
            _write_auth_json(codex_home / "auth.json", email=email, plan=plan, **kw)
            _seed_state_db(codex_home / "state_5.sqlite")
            (codex_home / "session_index.jsonl").write_text("", encoding="utf-8")
            (codex_home / ".codex-global-state.json").write_text("{}", encoding="utf-8")
            for d in ("sessions", "archived_sessions", "shell_snapshots"):
                (codex_home / d).mkdir(exist_ok=True)

        def clear_live_account(self) -> None:
            for p in codex_home.iterdir():
                if p.is_file():
                    p.unlink()
                else:
                    import shutil

                    shutil.rmtree(p)

    return Helpers()
