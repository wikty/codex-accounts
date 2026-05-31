"""Paths, constants, and platform detection.

All path constants are looked up *lazily* through helper functions so that
tests (and downstream users) can override them via environment variables.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _env_path(key: str, default: Path) -> Path:
    value = os.environ.get(key)
    return Path(value).expanduser() if value else default


def codex_home() -> Path:
    """Directory where the Codex desktop app keeps live state."""
    return _env_path("CODEX_HOME", Path.home() / ".codex")


def accounts_home() -> Path:
    """Directory where codex-accounts stores per-account snapshots."""
    return _env_path("CODEX_SWITCH_HOME", Path.home() / ".codex-accounts")


def current_file() -> Path:
    """Pointer file holding the name of the currently active account."""
    return accounts_home() / ".current"


# ---------------------------------------------------------------------------
# Codex-internal layout
# ---------------------------------------------------------------------------

# Files swapped in *share-sessions* mode (the default for ``use``).
AUTH_FILES: tuple[str, ...] = ("auth.json",)

# Files swapped in *full isolation* mode.  Glob patterns are allowed and
# expanded against ``codex_home()`` at runtime, so a future Codex schema bump
# from e.g. ``state_5.sqlite`` to ``state_6.sqlite`` still works.
ACCOUNT_FILE_PATTERNS: tuple[str, ...] = (
    "auth.json",
    "state_*.sqlite",
    "state_*.sqlite-shm",
    "state_*.sqlite-wal",
    "logs_*.sqlite",
    "logs_*.sqlite-shm",
    "logs_*.sqlite-wal",
    "session_index.jsonl",
    ".codex-global-state.json",
)

# Directories swapped in *full isolation* mode.
ACCOUNT_DIRS: tuple[str, ...] = (
    "sessions",
    "archived_sessions",
    "shell_snapshots",
)

# ---------------------------------------------------------------------------
# Codex private API (reverse-engineered; may break without notice)
# ---------------------------------------------------------------------------

WHAM_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"

# Model used by ``refresh`` to open the 5-hour window.  Picked because it is
# the cheapest variant exposed to ChatGPT-auth clients.
REFRESH_MODEL = "codex-mini-latest"

# ---------------------------------------------------------------------------
# Cosmetic
# ---------------------------------------------------------------------------

PLAN_LABELS: dict[str, str] = {
    "plus": "Plus",
    "free": "Free",
    "pro": "Pro",
    "team": "Team",
    "enterprise": "Enterprise",
}

# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------

IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
IS_WINDOWS = os.name == "nt"
