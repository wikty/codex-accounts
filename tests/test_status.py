"""Tests for the lightweight status report."""

from __future__ import annotations

import sqlite3
import time

from codex_switch import status


def test_status_config_counts_only_top_level_mcp_servers(codex_env):
    (codex_env.codex / "config.toml").write_text(
        """
model = "gpt-5.5"
model_reasoning_effort = "medium"

[mcp_servers.node_repl]
command = "node_repl"

[mcp_servers.node_repl.env]
CODEX_HOME = "/tmp/codex"

[mcp_servers.remote]
enabled = false
url = "https://example.com/mcp"

[mcp_servers.remote.http_headers]
X-Test = "secret"

[plugins."browser@example"]
enabled = true
""",
        encoding="utf-8",
    )

    cfg = status.collect_status().config
    assert cfg.mcp_enabled == 1
    assert cfg.mcp_disabled == 1
    assert cfg.mcp_remote == 1
    assert cfg.plugins_enabled == 1


def test_status_logs_counts_generic_health_signals(codex_env):
    db = codex_env.codex / "logs_2.sqlite"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            CREATE TABLE logs (
                ts INTEGER NOT NULL,
                level TEXT NOT NULL,
                target TEXT NOT NULL,
                feedback_log_body TEXT
            )
            """
        )
        now = int(time.time())
        rows = [
            (
                now,
                "WARN",
                "codex_app_server_transport::transport::remote_control::websocket",
                "failed to connect to app-server remote control websocket",
            ),
            (now, "WARN", "codex_core::responses_retry", "stream disconnected"),
            (now, "WARN", "codex_mcp::connection_manager", "Failed to list resources"),
            (now, "WARN", "codex_core_skills::loader", "ignoring bad plugin icon path"),
            (now, "WARN", "codex_rollout::list", "falling_back"),
            (
                now,
                "INFO",
                "feedback_tags",
                "user mentioned mcp errors, remote_409, and responses_retry",
            ),
            (
                now - 3 * 86400,
                "WARN",
                "codex_app_server_transport::transport::remote_control::websocket",
                "old remote control warning",
            ),
        ]
        conn.executemany(
            "INSERT INTO logs (ts, level, target, feedback_log_body) VALUES (?, ?, ?, ?)", rows
        )
        conn.commit()
    finally:
        conn.close()

    logs = status.collect_status(since_hours=24).logs
    assert logs.remote_control_warnings == 1
    assert logs.responses_retry == 1
    assert logs.mcp_warnings == 1
    assert logs.plugin_warnings == 1
    assert logs.rollout_warnings == 1


def test_reconnect_diagnosis_counts_and_sanitizes_samples(codex_env, monkeypatch):
    monkeypatch.setattr(status.processes, "is_supported_platform", lambda: False)
    db = codex_env.codex / "logs_2.sqlite"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            CREATE TABLE logs (
                ts INTEGER NOT NULL,
                level TEXT NOT NULL,
                target TEXT NOT NULL,
                feedback_log_body TEXT
            )
            """
        )
        now = int(time.time())
        secret = "v1." + "a" * 120
        rows = [
            (
                now,
                "ERROR",
                "codex_api::endpoint::responses_websocket",
                f"failed to connect websocket: tls handshake eof Bearer {secret}",
            ),
            (
                now,
                "ERROR",
                "codex_api::endpoint::responses_websocket",
                "failed to send websocket request: IO error: Broken pipe (os error 32)",
            ),
            (now, "ERROR", "codex_core", "request timed out"),
            (now, "WARN", "codex_core::responses_retry", "stream disconnected"),
            (
                now,
                "WARN",
                "codex_app_server_transport::transport::remote_control::websocket",
                "failed to connect to app-server remote control websocket",
            ),
            (
                now,
                "WARN",
                "rmcp::transport::worker",
                "HTTP request failed: https://developers.openai.com/mcp",
            ),
            (
                now,
                "WARN",
                "codex_core_plugins::manager",
                "failed request to https://chatgpt.com/backend-api/ps/plugins/list",
            ),
            (
                now,
                "WARN",
                "codex_models_manager::manager",
                "failed to refresh available models: request timed out",
            ),
        ]
        conn.executemany(
            "INSERT INTO logs (ts, level, target, feedback_log_body) VALUES (?, ?, ?, ?)", rows
        )
        conn.commit()
    finally:
        conn.close()

    report = status.collect_reconnect_diagnosis(since_hours=1)

    assert report.verdict == "ACTION"
    assert report.logs.tls_handshake_eof == 1
    assert report.logs.broken_pipe == 1
    assert report.logs.request_timeouts == 2
    assert report.logs.responses_retry == 1
    assert report.logs.remote_control_failures == 1
    assert report.logs.mcp_http_failures == 1
    assert report.logs.plugin_catalog_failures == 1
    assert report.logs.model_refresh_failures == 1
    joined_samples = "\n".join(sample.body for sample in report.samples)
    assert secret not in joined_samples
    assert "<redacted" in joined_samples


def test_status_json_shape(codex_env):
    report = status.collect_status()
    data = report.to_dict()
    assert "verdict" in data
    assert "config" in data
    assert "logs" in data
