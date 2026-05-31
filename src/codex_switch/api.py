"""Network calls against Codex's private endpoints.

These endpoints were located by reverse-engineering the macOS Codex client
(see ``docs/internals/codex-app-internals.md``).  They are **not** part of
any public API and may change without notice; every function here is wrapped
so that callers can degrade gracefully when the schema shifts.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from codex_switch import config


@dataclass
class Window:
    """A rate-limit window slice as returned by ``/wham/usage``."""

    used_percent: float
    limit_window_seconds: int
    reset_after_seconds: int
    reset_at: int

    @classmethod
    def from_json(cls, data: dict) -> Window:
        return cls(
            used_percent=float(data.get("used_percent", 0) or 0),
            limit_window_seconds=int(data.get("limit_window_seconds", 0) or 0),
            reset_after_seconds=int(data.get("reset_after_seconds", 0) or 0),
            reset_at=int(data.get("reset_at", 0) or 0),
        )


@dataclass
class Quota:
    primary: Window | None
    secondary: Window | None
    allowed: bool
    limit_reached: bool
    credits_unlimited: bool
    credits_balance: str
    raw: dict


class ApiError(Exception):
    """Raised for any error from the private Codex API."""


def fetch_quota(access_token: str, *, timeout: float = 10.0) -> Quota:
    """GET ``/wham/usage`` and parse the response into a :class:`Quota`.

    Raises :class:`ApiError` on transport or parse failure.
    """
    req = urllib.request.Request(
        config.WHAM_USAGE_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "codex-accounts",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read(512).decode("utf-8", errors="replace")
        raise ApiError(f"HTTP {e.code}: {body[:200]}") from e
    except urllib.error.URLError as e:
        raise ApiError(f"network error: {e.reason}") from e
    except (TimeoutError, OSError) as e:
        raise ApiError(f"network error: {e}") from e
    except json.JSONDecodeError as e:
        raise ApiError(f"malformed JSON response: {e}") from e

    rl = data.get("rate_limit") or {}
    pw = rl.get("primary_window")
    sw = rl.get("secondary_window")
    credits = data.get("credits") or {}

    return Quota(
        primary=Window.from_json(pw) if pw else None,
        secondary=Window.from_json(sw) if sw else None,
        allowed=bool(rl.get("allowed", True)),
        limit_reached=bool(rl.get("limit_reached", False)),
        credits_unlimited=bool(credits.get("unlimited", False)),
        credits_balance=str(credits.get("balance", "")),
        raw=data,
    )


def activate_window(
    access_token: str,
    account_id: str,
    *,
    timeout: float = 30.0,
) -> None:
    """Send a minimal request to open the 5-hour rate-limit window.

    This is used by ``codex-accounts refresh`` to ensure each account's window
    starts counting down at the beginning of the day, so the full daily
    allotment is available to the user.  Raises :class:`ApiError` on failure.
    """
    payload = json.dumps(
        {
            "model": config.REFRESH_MODEL,
            "instructions": "You are a helpful assistant.",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Reply with just the word: ok"}],
                }
            ],
            "store": False,
            "stream": True,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        config.RESPONSES_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "OpenAI-Account-Id": account_id,
            "User-Agent": "codex-accounts",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Drain the stream so the server records the request.
            for _ in resp:
                pass
    except urllib.error.HTTPError as e:
        body = e.read(256).decode("utf-8", errors="replace")
        raise ApiError(f"HTTP {e.code}: {body[:160]}") from e
    except urllib.error.URLError as e:
        raise ApiError(f"network error: {e.reason}") from e
    except (TimeoutError, OSError) as e:
        raise ApiError(f"network error: {e}") from e
