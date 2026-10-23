"""Tests for read-only Codex home cleanup classification."""

from __future__ import annotations

import os
import time

from codex_switch import cleanup


def _old(path, days: int = 30) -> None:
    ts = time.time() - days * 86400
    os.utime(path, (ts, ts))


def test_cleanup_classifies_storage_without_deleting(codex_env):
    home = codex_env.codex

    staging = home / ".tmp" / "bundled-marketplaces" / "openai-bundled.staging-old"
    staging.mkdir(parents=True)
    (staging / "blob").write_text("x" * 10, encoding="utf-8")
    _old(staging)

    plugin_backup = home / ".tmp" / "plugins-backup-test"
    plugin_backup.mkdir(parents=True)
    (plugin_backup / "plugin").write_text("x" * 5, encoding="utf-8")
    _old(plugin_backup)

    releases = home / "packages" / "standalone" / "releases"
    current_release = releases / "0.2.0-test"
    old_release = releases / "0.1.0-test"
    current_release.mkdir(parents=True)
    old_release.mkdir()
    (current_release / "bin").write_text("current", encoding="utf-8")
    (old_release / "bin").write_text("old", encoding="utf-8")
    (home / "packages" / "standalone" / "current").symlink_to(current_release)

    (home / "logs_2.sqlite.backup-before-test").write_text("log", encoding="utf-8")
    (home / "sessions").mkdir()
    (home / "sessions" / "active.jsonl").write_text("active", encoding="utf-8")
    (home / "archived_sessions").mkdir()
    (home / "archived_sessions" / "archived.jsonl").write_text("archived", encoding="utf-8")
    (home / "generated_images").mkdir()
    (home / "generated_images" / "image.png").write_text("image", encoding="utf-8")
    (home / "auth.json").write_text("secret", encoding="utf-8")

    report = cleanup.collect_cleanup_report(older_than_days=7)
    rows = {(item.action, item.category, item.path) for item in report.items}

    assert ("remove", "temporary staging", str(staging)) in rows
    assert ("remove", "temporary backup", str(plugin_backup)) in rows
    assert ("remove", "old standalone release", str(old_release)) in rows
    assert ("archive", "archived thread history", str(home / "archived_sessions")) in rows
    assert ("archive", "generated image artifacts", str(home / "generated_images")) in rows
    assert ("protect", "active thread history", str(home / "sessions")) in rows
    assert old_release.exists()
    assert staging.exists()


def test_cleanup_json_shape(codex_env):
    report = cleanup.collect_cleanup_report()
    data = report.to_dict()
    assert data["codex_home"] == str(codex_env.codex)
    assert "total_candidate_bytes" in data
    assert "items" in data


def test_cleanup_clean_candidates_deletes_only_selected_remove_bucket(codex_env):
    home = codex_env.codex
    staging = home / ".tmp" / "bundled-marketplaces" / "openai-bundled.staging-old"
    staging.mkdir(parents=True)
    (staging / "blob").write_text("x" * 10, encoding="utf-8")
    _old(staging)

    sessions = home / "sessions"
    sessions.mkdir()
    (sessions / "active.jsonl").write_text("active", encoding="utf-8")

    result = cleanup.clean_candidates(
        categories=["temporary staging"],
        older_than_days=7,
        dry_run=False,
    )

    assert len(result.deleted) == 1
    assert not staging.exists()
    assert sessions.exists()


def test_cleanup_clean_candidates_dry_run_keeps_files(codex_env):
    staging = codex_env.codex / ".tmp" / "bundled-marketplaces" / "openai-bundled.staging-old"
    staging.mkdir(parents=True)
    (staging / "blob").write_text("x" * 10, encoding="utf-8")
    _old(staging)

    result = cleanup.clean_candidates(
        categories=["temporary staging"],
        older_than_days=7,
        dry_run=True,
    )

    assert len(result.matched) == 1
    assert result.deleted == []
    assert staging.exists()
