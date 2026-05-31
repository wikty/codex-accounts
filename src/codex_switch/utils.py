"""Small helpers: JWT decoding, formatting, validation, terminal colors."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

from codex_switch import config

# ---------------------------------------------------------------------------
# Account name validation
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def validate_account_name(name: str) -> str:
    """Validate an account name. Raise ``ValueError`` on bad input.

    Names are used as directory components, so we restrict them to a safe
    character set and forbid anything that could traverse the filesystem.
    """
    if not name:
        raise ValueError("account name must not be empty")
    if not _NAME_RE.fullmatch(name):
        raise ValueError(
            f"invalid account name {name!r}: use letters, digits, "
            "'-', '_', '.' (max 64 chars, must start with alphanumeric)"
        )
    if name.startswith("."):
        raise ValueError(f"account name {name!r} must not start with '.'")
    return name


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def ensure_private_dir(path: Path) -> None:
    """Create ``path`` (and parents) and tighten permissions to 0700.

    No-op on Windows, where POSIX permissions do not apply.
    """
    path.mkdir(parents=True, exist_ok=True)
    if not config.IS_WINDOWS:
        # Best-effort: some network filesystems reject chmod.
        with contextlib.suppress(OSError):
            path.chmod(0o700)


# ---------------------------------------------------------------------------
# JWT decoding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthInfo:
    """Subset of ``auth.json`` fields used by the UI."""

    email: str
    plan: str
    exp: int
    iat: int
    account_id: str
    user_id: str
    auth_mode: str
    access_token: str

    @property
    def expires_at(self) -> datetime | None:
        if not self.exp:
            return None
        return datetime.fromtimestamp(self.exp, tz=timezone.utc)

    @property
    def seconds_to_expiry(self) -> float:
        if not self.exp:
            return float("inf")
        return self.exp - datetime.now(timezone.utc).timestamp()

    @property
    def is_expired(self) -> bool:
        return self.seconds_to_expiry <= 0


def _b64url_decode(segment: str) -> bytes:
    pad = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(pad)


def decode_auth_file(path: Path) -> AuthInfo | None:
    """Parse a Codex ``auth.json`` file and decode the embedded JWT.

    Returns ``None`` if the file is missing or malformed.
    """
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            auth = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None

    tokens = auth.get("tokens") or {}
    access_token = tokens.get("access_token") or ""
    if access_token.count(".") != 2:
        return None
    try:
        payload = json.loads(_b64url_decode(access_token.split(".")[1]))
    except (ValueError, json.JSONDecodeError):
        return None

    profile = payload.get("https://api.openai.com/profile") or {}
    auth_claims = payload.get("https://api.openai.com/auth") or {}

    return AuthInfo(
        email=profile.get("email", ""),
        plan=auth_claims.get("chatgpt_plan_type", ""),
        exp=int(payload.get("exp") or 0),
        iat=int(payload.get("iat") or 0),
        account_id=auth_claims.get("chatgpt_account_id", ""),
        user_id=auth_claims.get("chatgpt_user_id", ""),
        auth_mode=auth.get("auth_mode", ""),
        access_token=access_token,
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def fmt_plan(plan: str) -> str:
    return config.PLAN_LABELS.get(plan.lower(), plan.capitalize() or "?")


def fmt_token_status(info: AuthInfo | None) -> str:
    """Short human label for ``info``'s expiry, suitable for tabular output."""
    if info is None or not info.exp:
        return "no token"
    diff = info.seconds_to_expiry
    if diff <= 0:
        return "expired"
    days = int(diff // 86400)
    hours = int((diff % 86400) // 3600)
    if days == 0:
        return f"{hours}h left"
    if days <= 3:
        return f"{days}d left ⚠"
    return f"{days}d left"


def fmt_last_used(ts: str) -> str:
    """Render an ISO8601 timestamp as a human-friendly relative time."""
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts[:10]
    diff = (datetime.now(timezone.utc) - dt).total_seconds()
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    if diff < 172_800:
        return "yesterday"
    if diff < 604_800:
        return f"{int(diff // 86400)}d ago"
    return dt.strftime("%Y-%m-%d")


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    if s <= 0:
        return "now"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    h, rem = divmod(s, 3600)
    m = rem // 60
    return f"{h}h{m}m" if m else f"{h}h"


# ---------------------------------------------------------------------------
# Terminal colors / progress bars
# ---------------------------------------------------------------------------


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


_COLOR = _supports_color()


def color(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def dim(text: str) -> str:
    return color("2", text)


def bold(text: str) -> str:
    return color("1", text)


def red(text: str) -> str:
    return color("91", text)


def yellow(text: str) -> str:
    return color("93", text)


def green(text: str) -> str:
    return color("92", text)


def progress_bar(pct: float, width: int = 24) -> str:
    """Render an inline percentage bar with traffic-light coloring."""
    pct = max(0.0, min(100.0, pct))
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    if pct >= 90:
        bar = red(bar)
    elif pct >= 70:
        bar = yellow(bar)
    else:
        bar = green(bar)
    return f"{bar} {int(pct):3d}%"


# ---------------------------------------------------------------------------
# Process / app detection
# ---------------------------------------------------------------------------


def is_codex_running() -> bool:
    """Return True if a Codex client process is currently running.

    Falls back to ``False`` on platforms where we cannot tell.
    """
    if config.IS_MACOS:
        return _pgrep("Codex", exact=True) or _pgrep("codex", exact=False)
    if config.IS_LINUX:
        return _pgrep("codex", exact=False)
    return False


def _pgrep(pattern: str, exact: bool) -> bool:
    if shutil.which("pgrep") is None:
        return False
    args = ["pgrep", "-x", pattern] if exact else ["pgrep", "-f", pattern]
    try:
        result = subprocess.run(args, capture_output=True, timeout=5, check=False)
    except (subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


# ---------------------------------------------------------------------------
# Output sinks
# ---------------------------------------------------------------------------


def echo(msg: str = "") -> None:
    print(msg)


def info(msg: str) -> None:
    print(f"i  {msg}")


def ok(msg: str) -> None:
    print(green("✓ ") + msg)


def warn(msg: str) -> None:
    print(yellow("! ") + msg, file=sys.stderr)


def die(msg: str, code: int = 1) -> NoReturn:
    print(red("✗ ") + msg, file=sys.stderr)
    sys.exit(code)
