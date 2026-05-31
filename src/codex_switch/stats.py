"""Local token-usage statistics extracted from Codex's SQLite database."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from codex_switch import accounts, config


@dataclass
class Session:
    title: str
    model: str
    tokens_used: int
    created_at: datetime | None


@dataclass
class Stats:
    name: str
    source: str
    sessions: list[Session] = field(default_factory=list)
    by_model: dict[str, int] = field(default_factory=dict)
    total_tokens: int = 0
    total_sessions: int = 0
    last_7d_tokens: int = 0
    last_7d_sessions: int = 0
    last_30d_tokens: int = 0
    last_30d_sessions: int = 0


# ---------------------------------------------------------------------------
# DB discovery
# ---------------------------------------------------------------------------


def _find_state_db(name: str | None) -> tuple[Path, str]:
    """Return the SQLite path and a human-friendly source label."""
    current = accounts.current_name()
    target = name or current
    if target is None:
        raise FileNotFoundError("no account specified and no active account")

    if target == current:
        root = config.codex_home()
        label = f"live ({root})"
    else:
        root = config.accounts_home() / target
        label = f"snapshot ({root})"

    candidates = sorted(root.glob("state_*.sqlite"))
    if not candidates:
        raise FileNotFoundError(f"no state_*.sqlite under {root}; save a full snapshot first")
    return candidates[-1], label


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------


def _parse_timestamp(value: object) -> datetime | None:
    """Codex has used several timestamp encodings; handle them all."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _from_unix(float(value))
    if isinstance(value, str):
        try:
            return _from_unix(float(value))
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _from_unix(value: float) -> datetime:
    # Heuristic: anything past year 2286 is almost certainly milliseconds.
    if value > 1e10:
        value /= 1000
    return datetime.fromtimestamp(value, tz=timezone.utc)


def compute_stats(name: str | None = None) -> Stats:
    db_path, label = _find_state_db(name)
    target = name or accounts.current_name() or "(unknown)"

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)").fetchall()}
        has_ms = "created_at_ms" in columns
        order_col = "created_at_ms" if has_ms else "created_at"
        select_ms = "created_at_ms" if has_ms else "NULL AS created_at_ms"
        rows = conn.execute(
            f"""
            SELECT title, model, tokens_used, created_at, {select_ms}
            FROM threads
            WHERE tokens_used > 0
            ORDER BY {order_col} DESC
            """
        ).fetchall()
    finally:
        conn.close()

    stats = Stats(name=target, source=label)
    if not rows:
        return stats

    now = datetime.now(timezone.utc)
    ago_7 = now - timedelta(days=7)
    ago_30 = now - timedelta(days=30)

    for row in rows:
        created = _parse_timestamp(row["created_at_ms"]) or _parse_timestamp(row["created_at"])
        sess = Session(
            title=row["title"] or "(untitled)",
            model=row["model"] or "(unknown)",
            tokens_used=int(row["tokens_used"] or 0),
            created_at=created,
        )
        stats.sessions.append(sess)
        stats.total_tokens += sess.tokens_used
        stats.by_model[sess.model] = stats.by_model.get(sess.model, 0) + sess.tokens_used
        if created and created >= ago_7:
            stats.last_7d_tokens += sess.tokens_used
            stats.last_7d_sessions += 1
        if created and created >= ago_30:
            stats.last_30d_tokens += sess.tokens_used
            stats.last_30d_sessions += 1

    stats.total_sessions = len(stats.sessions)
    return stats
