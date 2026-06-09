"""Account snapshot management: save / load / list / init / rename / delete."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from codex_switch import config, utils
from codex_switch.utils import AuthInfo


class SwapMode(str, Enum):
    """How much state to swap when saving/loading an account.

    * ``AUTH`` — only ``auth.json``.  Sessions and history are shared across
      accounts (the default).
    * ``FULL`` — every per-account file and directory listed in
      :mod:`codex_switch.config` is swapped, giving complete isolation.
    """

    AUTH = "auth"
    FULL = "full"

    def patterns(self) -> tuple[str, ...]:
        return config.AUTH_FILES if self is SwapMode.AUTH else config.ACCOUNT_FILE_PATTERNS

    def dirs(self) -> tuple[str, ...]:
        return () if self is SwapMode.AUTH else config.ACCOUNT_DIRS


@dataclass
class Account:
    """A snapshot directory under ``~/.codex-accounts/``."""

    name: str
    path: Path

    @property
    def auth_file(self) -> Path:
        return self.path / "auth.json"

    @property
    def meta_file(self) -> Path:
        return self.path / "meta.json"

    @property
    def dirs_root(self) -> Path:
        return self.path / "dirs"

    def read_meta(self) -> dict:
        if not self.meta_file.exists():
            return {}
        try:
            with self.meta_file.open(encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def update_meta(self, **changes: object) -> None:
        meta = self.read_meta()
        meta.update({k: v for k, v in changes.items() if v is not None})
        utils.ensure_private_dir(self.path)
        with self.meta_file.open("w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
            fh.write("\n")


# ---------------------------------------------------------------------------
# Current account pointer
# ---------------------------------------------------------------------------


def current_name() -> str | None:
    f = config.current_file()
    if not f.exists():
        return None
    try:
        name = f.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return name or None


def set_current(name: str) -> None:
    utils.ensure_private_dir(config.accounts_home())
    config.current_file().write_text(name + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def list_accounts() -> list[Account]:
    home = config.accounts_home()
    if not home.is_dir():
        return []
    out: list[Account] = []
    for entry in sorted(home.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith("."):
            continue
        if not entry.is_dir():
            continue
        out.append(Account(name=entry.name, path=entry))
    return out


def get_account(name: str, *, must_exist: bool = True) -> Account:
    utils.validate_account_name(name)
    path = config.accounts_home() / name
    if must_exist and not path.is_dir():
        raise FileNotFoundError(f"account '{name}' not found under {config.accounts_home()}")
    return Account(name=name, path=path)


def auth_file_for(name: str) -> Path:
    """Return the live or snapshotted ``auth.json`` for ``name``.

    The currently active account reads from ``~/.codex/auth.json`` so we
    pick up the freshest token; other accounts use their snapshot copy.
    """
    if current_name() == name:
        return config.codex_home() / "auth.json"
    return config.accounts_home() / name / "auth.json"


def read_auth(name: str) -> AuthInfo | None:
    return utils.decode_auth_file(auth_file_for(name))


# ---------------------------------------------------------------------------
# Snapshot mutations
# ---------------------------------------------------------------------------


def _iter_matches(root: Path, patterns: Iterable[str]) -> Iterator[Path]:
    seen: set[Path] = set()
    for pattern in patterns:
        for match in sorted(root.glob(pattern)):
            if match in seen:
                continue
            seen.add(match)
            yield match


def init_account(name: str) -> Account:
    """Create an empty snapshot directory (no files copied)."""
    utils.validate_account_name(name)
    home = config.accounts_home()
    utils.ensure_private_dir(home)
    path = home / name
    if path.exists():
        raise FileExistsError(f"account '{name}' already exists at {path}")
    utils.ensure_private_dir(path)
    utils.ensure_private_dir(path / "dirs")
    Account(name=name, path=path).update_meta(
        created_at=_now_iso(),
    )
    return Account(name=name, path=path)


def save_account(name: str, mode: SwapMode = SwapMode.FULL) -> Account:
    """Copy live Codex state into the account snapshot directory."""
    utils.validate_account_name(name)
    home = config.accounts_home()
    utils.ensure_private_dir(home)
    dest = home / name
    utils.ensure_private_dir(dest)
    utils.ensure_private_dir(dest / "dirs")

    src = config.codex_home()
    if not src.is_dir():
        raise FileNotFoundError(
            f"Codex home not found at {src} — is the Codex desktop app installed?"
        )

    for live in _iter_matches(src, mode.patterns()):
        if not live.is_file():
            continue
        shutil.copy2(live, dest / live.name)

    for d in mode.dirs():
        src_dir = src / d
        if not src_dir.is_dir():
            continue
        target = dest / "dirs" / d
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src_dir, target, symlinks=True)

    account = Account(name=name, path=dest)
    account.update_meta(last_used_at=_now_iso())
    return account


def load_account(name: str, mode: SwapMode = SwapMode.FULL) -> Account:
    """Copy the account snapshot back into the live Codex home."""
    account = get_account(name, must_exist=True)
    dest = config.codex_home()
    utils.ensure_private_dir(dest)

    # Files: replace if snapshot has them, delete from live home if not.
    snap_files = {p.name: p for p in _iter_matches(account.path, mode.patterns())}
    live_files = {p.name: p for p in _iter_matches(dest, mode.patterns())}

    for name_, src in snap_files.items():
        shutil.copy2(src, dest / name_)

    for name_, live in live_files.items():
        if name_ not in snap_files:
            live.unlink(missing_ok=True)

    # Directories: only swap when in FULL mode; preserve live dirs otherwise.
    for d in mode.dirs():
        live_dir = dest / d
        snap_dir = account.path / "dirs" / d
        if snap_dir.is_dir():
            if live_dir.exists():
                shutil.rmtree(live_dir)
            shutil.copytree(snap_dir, live_dir, symlinks=True)

    set_current(name)
    account.update_meta(last_used_at=_now_iso())
    return account


def rename_account(old: str, new: str) -> Account:
    src = get_account(old, must_exist=True)
    utils.validate_account_name(new)
    dst_path = config.accounts_home() / new
    if dst_path.exists():
        raise FileExistsError(f"account '{new}' already exists")
    src.path.rename(dst_path)
    if current_name() == old:
        set_current(new)
    return Account(name=new, path=dst_path)


def delete_account(name: str, *, dry_run: bool = False) -> Path:
    account = get_account(name, must_exist=True)
    if current_name() == name:
        raise RuntimeError(f"cannot delete the currently active account '{name}'; switch first")
    if not dry_run:
        shutil.rmtree(account.path)
    return account.path


def set_note(name: str, text: str) -> None:
    account = get_account(name, must_exist=True)
    account.update_meta(notes=text)


def set_billing(name: str, renews_at: str | None) -> None:
    """Store (or clear) the next billing/renewal date for an account.

    ``renews_at`` should be a ``YYYY-MM-DD`` string or ``None`` to clear.
    Caller is expected to have validated the date format.
    """
    account = get_account(name, must_exist=True)
    meta = account.read_meta()
    if renews_at is None:
        meta.pop("renews_at", None)
    else:
        meta["renews_at"] = renews_at
    utils.ensure_private_dir(account.path)
    with account.meta_file.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
