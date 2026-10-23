"""Read-only Codex home cleanup candidate discovery."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codex_switch import config


@dataclass(frozen=True)
class CleanupItem:
    category: str
    action: str
    risk: str
    path: str
    bytes: int
    reason: str
    count: int = 1


@dataclass(frozen=True)
class CleanupReport:
    codex_home: str
    older_than_days: int
    generated_at: int
    items: list[CleanupItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "codex_home": self.codex_home,
            "older_than_days": self.older_than_days,
            "generated_at": self.generated_at,
            "total_candidate_bytes": total_candidate_bytes(self),
            "items": [item.__dict__ for item in self.items],
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CleanupRunResult:
    matched: list[CleanupItem]
    deleted: list[CleanupItem]
    missing: list[CleanupItem]
    failed: list[tuple[CleanupItem, str]]
    dry_run: bool

    @property
    def matched_bytes(self) -> int:
        return sum(item.bytes for item in self.matched)

    @property
    def deleted_bytes(self) -> int:
        return sum(item.bytes for item in self.deleted)


def collect_cleanup_report(older_than_days: int = 7) -> CleanupReport:
    """Collect a read-only garbage-collection candidate report.

    This function intentionally never deletes, moves, vacuums, or rewrites
    Codex files. It classifies storage by lifecycle so callers can decide what
    is safe enough to clean in a separate, explicit operation.
    """

    home = config.codex_home()
    cutoff = time.time() - older_than_days * 86400
    items: list[CleanupItem] = []
    notes: list[str] = []

    if not home.exists():
        return CleanupReport(
            codex_home=str(home),
            older_than_days=older_than_days,
            generated_at=int(time.time()),
            notes=["CODEX_HOME does not exist"],
        )

    items.extend(_tmp_candidates(home, cutoff))
    items.extend(_old_standalone_releases(home))
    items.extend(_log_backup_candidates(home))
    items.extend(_rebuildable_cache_candidates(home, cutoff))
    items.extend(_archive_candidates(home))
    items.extend(_protected_state_summaries(home))

    if _has_live_sqlite_files(home):
        notes.append(
            "Codex appears to have live SQLite WAL/SHM files; clean only after quitting Codex."
        )
    if _path_size(home / "sessions"):
        notes.append(
            "Active session rollout files are protected; archive threads before compacting history."
        )

    return CleanupReport(
        codex_home=str(home),
        older_than_days=older_than_days,
        generated_at=int(time.time()),
        items=items,
        notes=notes,
    )


def total_candidate_bytes(report: CleanupReport) -> int:
    return sum(item.bytes for item in report.items if item.action in {"remove", "rebuild"})


def clean_candidates(
    *,
    older_than_days: int = 7,
    categories: list[str] | None = None,
    paths: list[str] | None = None,
    dry_run: bool = True,
) -> CleanupRunResult:
    """Delete selected remove-candidate items from the current report."""

    report = collect_cleanup_report(older_than_days=older_than_days)
    matched = select_items(report, action="remove", categories=categories, paths=paths)
    if dry_run:
        return CleanupRunResult(matched=matched, deleted=[], missing=[], failed=[], dry_run=True)

    deleted: list[CleanupItem] = []
    missing: list[CleanupItem] = []
    failed: list[tuple[CleanupItem, str]] = []
    for item in matched:
        try:
            _delete_item(Path(report.codex_home), item)
        except FileNotFoundError:
            missing.append(item)
        except OSError as e:
            failed.append((item, str(e)))
        else:
            deleted.append(item)
    return CleanupRunResult(
        matched=matched,
        deleted=deleted,
        missing=missing,
        failed=failed,
        dry_run=False,
    )


def select_items(
    report: CleanupReport,
    *,
    action: str,
    categories: list[str] | None = None,
    paths: list[str] | None = None,
) -> list[CleanupItem]:
    categories = categories or []
    paths = paths or []
    wanted_paths = {str(Path(path).expanduser()) for path in paths}
    selected: list[CleanupItem] = []
    for item in report.items:
        if item.action != action:
            continue
        if categories and item.category in categories:
            selected.append(item)
            continue
        if wanted_paths and item.path in wanted_paths:
            selected.append(item)
    return selected


def _tmp_candidates(home: Path, cutoff: float) -> list[CleanupItem]:
    tmp = home / ".tmp"
    if not tmp.exists():
        return []

    items: list[CleanupItem] = []
    marketplace = tmp / "bundled-marketplaces"
    if marketplace.exists():
        for child in sorted(marketplace.iterdir()):
            is_staging = (
                child.name.endswith(".staging")
                or ".staging-" in child.name
                or child.name.startswith("staging-")
            )
            if is_staging and _mtime(child) <= cutoff:
                items.append(
                    CleanupItem(
                        category="temporary staging",
                        action="remove",
                        risk="low",
                        path=str(child),
                        bytes=_path_size(child),
                        reason="old bundled marketplace staging directory",
                    )
                )

    for child in sorted(tmp.iterdir()):
        if child.name.startswith("plugins-backup-") and _mtime(child) <= cutoff:
            items.append(
                CleanupItem(
                    category="temporary backup",
                    action="remove",
                    risk="low",
                    path=str(child),
                    bytes=_path_size(child),
                    reason="old plugin backup left under .tmp",
                )
            )
        elif child.name == "plugins" and _mtime(child) <= cutoff:
            items.append(
                CleanupItem(
                    category="temporary checkout",
                    action="remove",
                    risk="medium",
                    path=str(child),
                    bytes=_path_size(child),
                    reason="temporary plugin checkout; regenerate instead of preserving",
                )
            )
    return items


def _old_standalone_releases(home: Path) -> list[CleanupItem]:
    standalone = home / "packages" / "standalone"
    releases = standalone / "releases"
    if not releases.exists():
        return []

    current_target: Path | None = None
    current = standalone / "current"
    if current.exists() or current.is_symlink():
        try:
            current_target = current.resolve()
        except OSError:
            current_target = None

    items: list[CleanupItem] = []
    for child in sorted(releases.iterdir()):
        try:
            resolved = child.resolve()
        except OSError:
            resolved = child
        if current_target is not None and resolved == current_target:
            continue
        if child.is_dir():
            items.append(
                CleanupItem(
                    category="old standalone release",
                    action="remove",
                    risk="low",
                    path=str(child),
                    bytes=_path_size(child),
                    reason="not the current standalone Codex package target",
                )
            )
    return items


def _log_backup_candidates(home: Path) -> list[CleanupItem]:
    return [
        CleanupItem(
            category="log backup",
            action="remove",
            risk="low",
            path=str(path),
            bytes=_path_size(path),
            reason="old copied log database; live logs are kept separately",
        )
        for path in sorted(home.glob("logs_*.sqlite.backup*"))
        if path.is_file()
    ]


def _rebuildable_cache_candidates(home: Path, cutoff: float) -> list[CleanupItem]:
    items: list[CleanupItem] = []
    for path in sorted((home / "cache").iterdir()) if (home / "cache").exists() else []:
        if _mtime(path) <= cutoff:
            items.append(
                CleanupItem(
                    category="rebuildable cache",
                    action="rebuild",
                    risk="medium",
                    path=str(path),
                    bytes=_path_size(path),
                    reason="local cache; may be regenerated after cleanup",
                )
            )
    return items


def _archive_candidates(home: Path) -> list[CleanupItem]:
    items: list[CleanupItem] = []
    archived_sessions = home / "archived_sessions"
    if archived_sessions.exists():
        count = _count_files(archived_sessions)
        size = _path_size(archived_sessions)
        if size:
            items.append(
                CleanupItem(
                    category="archived thread history",
                    action="archive",
                    risk="medium",
                    path=str(archived_sessions),
                    bytes=size,
                    reason="archived rollouts remain full-size; compress or cold-store as a bundle",
                    count=count,
                )
            )

    generated_images = home / "generated_images"
    if generated_images.exists():
        count = _count_files(generated_images)
        size = _path_size(generated_images)
        if size:
            items.append(
                CleanupItem(
                    category="generated image artifacts",
                    action="archive",
                    risk="medium",
                    path=str(generated_images),
                    bytes=size,
                    reason="user-visible generated images; archive before deleting",
                    count=count,
                )
            )
    return items


def _protected_state_summaries(home: Path) -> list[CleanupItem]:
    items: list[CleanupItem] = []
    sessions = home / "sessions"
    if sessions.exists():
        items.append(
            CleanupItem(
                category="active thread history",
                action="protect",
                risk="high",
                path=str(sessions),
                bytes=_path_size(sessions),
                reason="referenced by state DB; do not delete directly",
                count=_count_files(sessions),
            )
        )

    protected_files = [
        "auth.json",
        "config.toml",
        "AGENTS.md",
        "state_5.sqlite",
        "logs_2.sqlite",
        "installation_id",
    ]
    existing = [home / name for name in protected_files if (home / name).exists()]
    if existing:
        items.append(
            CleanupItem(
                category="protected core files",
                action="protect",
                risk="high",
                path=str(home),
                bytes=sum(_path_size(path) for path in existing),
                reason="auth, config, live indexes, or current logs",
                count=len(existing),
            )
        )
    return items


def _has_live_sqlite_files(home: Path) -> bool:
    return any(home.glob("*.sqlite-wal")) or any(home.glob("*.sqlite-shm"))


def _path_size(path: Path) -> int:
    if not path.exists() and not path.is_symlink():
        return 0
    if path.is_file() or path.is_symlink():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, dirs, files in os.walk(path):
        root_path = Path(root)
        for name in files:
            total += _path_size(root_path / name)
        for name in dirs:
            child = root_path / name
            if child.is_symlink():
                total += _path_size(child)
    return total


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    count = 0
    for _, _, files in os.walk(path):
        count += len(files)
    return count


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def dumps_json(report: CleanupReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def _delete_item(home: Path, item: CleanupItem) -> None:
    if item.action != "remove" or item.risk == "high":
        raise OSError(f"refusing to delete protected item: {item.category}")

    root = home.resolve(strict=False)
    target = Path(item.path).expanduser()
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as e:
        raise OSError(f"refusing to delete outside CODEX_HOME: {target}") from e

    if not target.exists() and not target.is_symlink():
        raise FileNotFoundError(str(target))
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    else:
        target.unlink()


def find_unreferenced_rollouts(home: Path | None = None) -> tuple[int, int]:
    """Return count and bytes for rollout files not referenced by state DB.

    Kept separate from the normal report because it touches every rollout file
    and should remain an explicit diagnostic building block.
    """

    home = home or config.codex_home()
    db = home / "state_5.sqlite"
    if not db.exists():
        return 0, 0

    referenced: set[Path] = set()
    try:
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute("SELECT rollout_path FROM threads WHERE rollout_path <> ''")
            referenced = {Path(row[0]).expanduser() for row in rows if row[0]}
        finally:
            conn.close()
    except sqlite3.Error:
        return 0, 0

    count = 0
    size = 0
    for root_name in ("sessions", "archived_sessions"):
        root = home / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            if path not in referenced:
                count += 1
                size += _path_size(path)
    return count, size
