"""Lightweight local Codex health summary."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codex_switch import accounts, config, processes, utils


@dataclass(frozen=True)
class AccountStatus:
    name: str | None
    email: str
    token: str
    problem: str | None = None


@dataclass(frozen=True)
class ConfigStatus:
    model: str
    effort: str
    service_tier: str
    model_instructions_file: str
    agents_max_threads: str
    agents_max_depth: str
    mcp_enabled: int
    mcp_disabled: int
    mcp_remote: int
    plugins_enabled: int
    global_agents_bytes: int
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProcessStatus:
    supported: bool
    chatgpt_running: bool
    counts: dict[str, int]
    stale_candidate_count: int


@dataclass(frozen=True)
class LogStatus:
    since_hours: int
    remote_control_warnings: int
    responses_retry: int
    mcp_warnings: int
    plugin_warnings: int
    rollout_warnings: int
    readable: bool


@dataclass(frozen=True)
class StateStatus:
    codex_home_exists: bool
    state_db_exists: bool
    log_db_exists: bool
    active_threads: int | None
    active_rollout_bytes: int | None
    archived_threads: int | None
    subagent_threads_7d: int | None


@dataclass(frozen=True)
class StatusReport:
    verdict: str
    reasons: list[str]
    account: AccountStatus
    config: ConfigStatus
    processes: ProcessStatus
    logs: LogStatus
    state: StateStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reasons": self.reasons,
            "account": self.account.__dict__,
            "config": self.config.__dict__,
            "processes": self.processes.__dict__,
            "logs": self.logs.__dict__,
            "state": self.state.__dict__,
        }


@dataclass(frozen=True)
class ReconnectLogStatus:
    since_hours: int
    tls_handshake_eof: int
    broken_pipe: int
    request_timeouts: int
    stream_disconnected: int
    responses_retry: int
    websocket_errors: int
    remote_control_failures: int
    mcp_http_failures: int
    plugin_catalog_failures: int
    model_refresh_failures: int
    readable: bool


@dataclass(frozen=True)
class ReconnectLogSample:
    ts: int
    level: str
    target: str
    body: str


@dataclass(frozen=True)
class NetworkStatus:
    supported: bool
    pac_enabled: bool
    pac_url: str
    http_proxy_enabled: bool
    https_proxy_enabled: bool
    socks_proxy_enabled: bool
    tun_routes: int
    proxy_apps: list[str]
    problem: str | None = None


@dataclass(frozen=True)
class LiveProbe:
    url: str
    ok: bool
    status: str
    notes: list[str]


@dataclass(frozen=True)
class ReconnectDiagnosis:
    verdict: str
    reasons: list[str]
    next_steps: list[str]
    logs: ReconnectLogStatus
    samples: list[ReconnectLogSample]
    network: NetworkStatus
    processes: ProcessStatus
    probes: list[LiveProbe]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reasons": self.reasons,
            "next_steps": self.next_steps,
            "logs": self.logs.__dict__,
            "samples": [sample.__dict__ for sample in self.samples],
            "network": self.network.__dict__,
            "processes": self.processes.__dict__,
            "probes": [probe.__dict__ for probe in self.probes],
        }


def collect_status(since_hours: int = 24) -> StatusReport:
    """Collect a read-only, offline health snapshot."""

    account = _account_status()
    cfg = _config_status()
    proc = _process_status()
    logs = _log_status(since_hours)
    state = _state_status()
    verdict, reasons = _verdict(account, cfg, proc, logs, state)
    return StatusReport(
        verdict=verdict,
        reasons=reasons,
        account=account,
        config=cfg,
        processes=proc,
        logs=logs,
        state=state,
    )


def collect_reconnect_diagnosis(since_hours: int = 1, *, live: bool = False) -> ReconnectDiagnosis:
    """Collect read-only diagnostics for Codex Desktop reconnect failures."""

    logs, samples = _reconnect_log_status(since_hours)
    network = _network_status()
    proc = _process_status()
    probes = _live_probes() if live else []
    verdict, reasons, next_steps = _reconnect_verdict(logs, network, proc, probes)
    return ReconnectDiagnosis(
        verdict=verdict,
        reasons=reasons,
        next_steps=next_steps,
        logs=logs,
        samples=samples,
        network=network,
        processes=proc,
        probes=probes,
    )


def _account_status() -> AccountStatus:
    name = accounts.current_name()
    if not name:
        return AccountStatus(
            name=None, email="(none)", token="no current account", problem="no current account"
        )
    info = accounts.read_auth(name)
    if info is None:
        return AccountStatus(name=name, email="(unknown)", token="no auth", problem="no auth")
    token = utils.fmt_token_status(info)
    problem = "token expired" if info.is_expired else None
    return AccountStatus(name=name, email=info.email or "(unknown)", token=token, problem=problem)


def _config_status() -> ConfigStatus:
    raw = _parse_config_file(config.codex_home() / "config.toml")
    top = raw.get("", {})
    agents = raw.get("agents", {})
    features = raw.get("features", {})
    mcp_sections = [
        name for name in raw if name.startswith("mcp_servers.") and len(name.split(".")) == 2
    ]
    plugin_sections = [name for name in raw if name.startswith("plugins.")]

    mcp_enabled = 0
    mcp_disabled = 0
    mcp_remote = 0
    for section in mcp_sections:
        values = raw.get(section, {})
        enabled = _as_bool(values.get("enabled"), default=True)
        if enabled:
            mcp_enabled += 1
        else:
            mcp_disabled += 1
        if "url" in values:
            mcp_remote += 1

    plugins_enabled = sum(
        1
        for section in plugin_sections
        if _as_bool(raw.get(section, {}).get("enabled"), default=False)
    )

    problems: list[str] = []
    model_instructions_file = top.get("model_instructions_file", "")
    if model_instructions_file:
        problems.append("model_instructions_file set")
    effort = top.get("model_reasoning_effort", "")
    if effort in {"high", "xhigh", "max", "ultra"}:
        problems.append(f"high reasoning default: {effort}")
    if _as_bool(features.get("fast_mode"), default=False) or top.get("service_tier") == "fast":
        problems.append("fast mode/service tier enabled")
    max_threads = agents.get("max_threads", "")
    try:
        if max_threads and int(max_threads) > 3:
            problems.append(f"agents.max_threads={max_threads}")
    except ValueError:
        problems.append(f"agents.max_threads invalid: {max_threads}")

    agents_file = config.codex_home() / "AGENTS.md"
    return ConfigStatus(
        model=top.get("model", "(default)"),
        effort=effort or "(default)",
        service_tier=top.get("service_tier", "(default)"),
        model_instructions_file=model_instructions_file or "(unset)",
        agents_max_threads=max_threads or "(default)",
        agents_max_depth=agents.get("max_depth", "(default)"),
        mcp_enabled=mcp_enabled,
        mcp_disabled=mcp_disabled,
        mcp_remote=mcp_remote,
        plugins_enabled=plugins_enabled,
        global_agents_bytes=agents_file.stat().st_size if agents_file.exists() else 0,
        problems=problems,
    )


def _process_status() -> ProcessStatus:
    supported = processes.is_supported_platform()
    chatgpt_running = processes.is_chatgpt_app_running() if supported else False
    rows = processes.list_stale_processes() if supported else []
    counts = dict(Counter(proc.kind for proc in rows))
    stale_candidate_count = 0 if chatgpt_running else len(rows)
    return ProcessStatus(
        supported=supported,
        chatgpt_running=chatgpt_running,
        counts=counts,
        stale_candidate_count=stale_candidate_count,
    )


def _log_status(since_hours: int) -> LogStatus:
    db = config.codex_home() / "logs_2.sqlite"
    if not db.exists():
        return LogStatus(since_hours, 0, 0, 0, 0, 0, readable=False)
    cutoff = int(time.time() - since_hours * 3600)
    try:
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                """
                SELECT
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND target LIKE 'codex_app_server_transport::transport::remote_control%'
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND (target = 'codex_core::responses_retry'
                                 OR feedback_log_body LIKE '%retrying sampling request%')
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND (target LIKE '%mcp%'
                                 OR feedback_log_body LIKE '%mcpServerStatus%'
                                 OR feedback_log_body LIKE '%MCP server%')
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND (target LIKE 'codex_core_plugins%'
                                 OR target = 'codex_core_skills::loader')
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND (target = 'codex_rollout::list'
                                 OR target = 'codex_core::session::rollout_reconstruction'
                                 OR (lower(feedback_log_body) LIKE '%rollout%'
                                     AND lower(feedback_log_body) LIKE '%falling_back%'))
                           THEN 1 ELSE 0 END)
                FROM logs
                WHERE ts >= ?
                """,
                (cutoff,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return LogStatus(since_hours, 0, 0, 0, 0, 0, readable=False)
    values = [int(v or 0) for v in (rows or (0, 0, 0, 0, 0))]
    return LogStatus(
        since_hours,
        values[0],
        values[1],
        values[2],
        values[3],
        values[4],
        readable=True,
    )


def _state_status() -> StateStatus:
    home = config.codex_home()
    state_db = home / "state_5.sqlite"
    log_db = home / "logs_2.sqlite"
    active: int | None = None
    archived: int | None = None
    active_bytes: int | None = None
    subagent_7d: int | None = None
    if state_db.exists():
        try:
            conn = sqlite3.connect(state_db)
            try:
                active, archived = _thread_counts(conn)
                active_bytes = _active_rollout_bytes(conn)
                subagent_7d = _subagent_threads_7d(conn)
            finally:
                conn.close()
        except sqlite3.Error:
            active = archived = active_bytes = subagent_7d = None
    return StateStatus(
        codex_home_exists=home.is_dir(),
        state_db_exists=state_db.exists(),
        log_db_exists=log_db.exists(),
        active_threads=active,
        active_rollout_bytes=active_bytes,
        archived_threads=archived,
        subagent_threads_7d=subagent_7d,
    )


def _reconnect_log_status(
    since_hours: int,
) -> tuple[ReconnectLogStatus, list[ReconnectLogSample]]:
    db = config.codex_home() / "logs_2.sqlite"
    empty = ReconnectLogStatus(since_hours, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, readable=False)
    if not db.exists():
        return empty, []
    cutoff = int(time.time() - since_hours * 3600)
    try:
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                """
                SELECT
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND lower(feedback_log_body) LIKE '%tls handshake eof%'
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND lower(feedback_log_body) LIKE '%broken pipe%'
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND lower(feedback_log_body) LIKE '%timed out%'
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND lower(feedback_log_body) LIKE '%stream disconnected%'
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND (target = 'codex_core::responses_retry'
                                 OR lower(feedback_log_body) LIKE '%retrying sampling request%')
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND (lower(target) LIKE '%responses_websocket%'
                                 OR lower(feedback_log_body) LIKE '%websocket%')
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND target LIKE
                              'codex_app_server_transport::transport::remote_control%'
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND (lower(feedback_log_body) LIKE
                                   '%developers.openai.com/mcp%'
                                 OR lower(feedback_log_body) LIKE
                                   '%chatgpt.com/backend-api/ps/mcp%'
                                 OR lower(target) LIKE '%mcp%')
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND (target LIKE 'codex_core_plugins%'
                                 OR lower(feedback_log_body) LIKE '%/ps/plugins%')
                           THEN 1 ELSE 0 END),
                  SUM(CASE WHEN level IN ('WARN', 'ERROR')
                            AND target = 'codex_models_manager::manager'
                           THEN 1 ELSE 0 END)
                FROM logs
                WHERE ts >= ?
                """,
                (cutoff,),
            ).fetchone()
            sample_rows = conn.execute(
                """
                SELECT ts, level, target, COALESCE(feedback_log_body, '')
                FROM logs
                WHERE ts >= ?
                  AND level IN ('WARN', 'ERROR')
                  AND target NOT LIKE 'codex_app_server::attestation%'
                  AND (
                    lower(feedback_log_body) LIKE '%tls handshake eof%'
                    OR lower(feedback_log_body) LIKE '%broken pipe%'
                    OR lower(feedback_log_body) LIKE '%timed out%'
                    OR lower(feedback_log_body) LIKE '%stream disconnected%'
                    OR lower(feedback_log_body) LIKE '%websocket%'
                    OR target = 'codex_core::responses_retry'
                    OR target LIKE 'codex_app_server_transport::transport::remote_control%'
                    OR lower(feedback_log_body) LIKE '%developers.openai.com/mcp%'
                    OR lower(feedback_log_body) LIKE '%/ps/plugins%'
                    OR target = 'codex_models_manager::manager'
                  )
                ORDER BY ts DESC
                LIMIT 8
                """,
                (cutoff,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return empty, []

    values = [int(value or 0) for value in (row or (0,) * 10)]
    logs = ReconnectLogStatus(since_hours, *values, readable=True)
    samples = [
        ReconnectLogSample(
            ts=int(ts or 0),
            level=str(level or ""),
            target=str(target or ""),
            body=_interesting_excerpt(str(body or "")),
        )
        for ts, level, target, body in sample_rows
    ]
    return logs, samples


def _network_status() -> NetworkStatus:
    if not processes.is_supported_platform():
        return NetworkStatus(
            supported=False,
            pac_enabled=False,
            pac_url="",
            http_proxy_enabled=False,
            https_proxy_enabled=False,
            socks_proxy_enabled=False,
            tun_routes=0,
            proxy_apps=[],
            problem="network inspection currently supports macOS only",
        )

    proxy_text = _run_text(["scutil", "--proxy"])
    route_text = _run_text(["netstat", "-rn"])
    launch_text = _run_text(["launchctl", "list"])
    problem = None
    if proxy_text is None:
        problem = "could not read macOS proxy settings"
        proxy_text = ""
    if route_text is None:
        route_text = ""
    if launch_text is None:
        launch_text = ""

    proxy_apps = _proxy_apps(launch_text)
    return NetworkStatus(
        supported=True,
        pac_enabled=_proxy_flag(proxy_text, "ProxyAutoConfigEnable"),
        pac_url=_sanitize_log_text(_proxy_value(proxy_text, "ProxyAutoConfigURLString")),
        http_proxy_enabled=_proxy_flag(proxy_text, "HTTPEnable"),
        https_proxy_enabled=_proxy_flag(proxy_text, "HTTPSEnable"),
        socks_proxy_enabled=_proxy_flag(proxy_text, "SOCKSEnable"),
        tun_routes=sum(1 for line in route_text.splitlines() if "utun" in line),
        proxy_apps=proxy_apps,
        problem=problem,
    )


def _live_probes() -> list[LiveProbe]:
    urls = [
        "https://chatgpt.com/backend-api/",
        "https://developers.openai.com/mcp",
    ]
    return [_probe_url(url) for url in urls]


def _probe_url(url: str) -> LiveProbe:
    try:
        completed = subprocess.run(
            ["curl", "-I", "--connect-timeout", "10", "--max-time", "20", url],
            check=False,
            capture_output=True,
            text=True,
            timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return LiveProbe(url=url, ok=False, status="probe failed", notes=[str(e)])

    output = _sanitize_log_text((completed.stdout or "") + "\n" + (completed.stderr or ""))
    status = next((line.strip() for line in output.splitlines() if line.startswith("HTTP/")), "")
    if not status:
        status = f"curl exit {completed.returncode}"
    lower = output.lower()
    notes: list[str] = []
    if "operation timed out" in lower or "timed out" in lower:
        notes.append("timeout")
    if "tls" in lower:
        notes.append("tls error")
    if "cf-mitigated: challenge" in lower:
        notes.append("cloudflare challenge")
    if completed.returncode != 0:
        notes.append(f"curl_exit={completed.returncode}")
    ok = completed.returncode == 0 and "timeout" not in notes and "tls error" not in notes
    return LiveProbe(url=url, ok=ok, status=status, notes=notes)


def _run_text(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _proxy_flag(text: str, key: str) -> bool:
    return _proxy_value(text, key) == "1"


def _proxy_value(text: str, key: str) -> str:
    prefix = f"{key} :"
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _proxy_apps(text: str) -> list[str]:
    terms = ("clash", "surge", "loon", "mihomo", "shadow", "sing-box", "v2ray", "vpn")
    seen: list[str] = []
    for raw in text.splitlines():
        lower = raw.lower()
        if not any(term in lower for term in terms):
            continue
        label = raw.split()[-1] if raw.split() else raw.strip()
        label = _sanitize_log_text(label)
        if label and label not in seen:
            seen.append(label)
    return seen[:8]


def _sanitize_log_text(text: str) -> str:
    text = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", text)
    text = re.sub(r"(X-[A-Za-z0-9_-]*(?:Api-)?Key[\"'=:\s]+)[^,}\s\"]+", r"\1<redacted>", text)
    text = re.sub(r"v1\.[A-Za-z0-9._~+/=-]{40,}", "<redacted-token>", text)
    text = re.sub(r"[A-Za-z0-9._~+/=-]{96,}", "<redacted>", text)
    return " ".join(text.split())


def _interesting_excerpt(text: str, *, limit: int = 320) -> str:
    sanitized = _sanitize_log_text(text)
    lower = sanitized.lower()
    needles = (
        "tls handshake eof",
        "broken pipe",
        "request timed out",
        "timed out",
        "stream disconnected",
        "retrying sampling request",
        "websocket",
        "developers.openai.com/mcp",
        "/ps/plugins",
        "failed to refresh",
    )
    starts = [lower.find(needle) for needle in needles if lower.find(needle) >= 0]
    if not starts:
        return sanitized[:limit]
    start = max(0, min(starts) - 80)
    prefix = "..." if start else ""
    return prefix + sanitized[start : start + limit]


def _reconnect_verdict(
    logs: ReconnectLogStatus,
    network: NetworkStatus,
    proc: ProcessStatus,
    probes: list[LiveProbe],
) -> tuple[str, list[str], list[str]]:
    action: list[str] = []
    watch: list[str] = []
    next_steps: list[str] = []
    networkish = (
        logs.tls_handshake_eof
        + logs.broken_pipe
        + logs.request_timeouts
        + logs.websocket_errors
        + logs.stream_disconnected
    )

    if networkish:
        action.append(
            "model stream/network failures detected "
            f"(tls={logs.tls_handshake_eof}, broken_pipe={logs.broken_pipe}, "
            f"timeouts={logs.request_timeouts})"
        )
    if logs.responses_retry:
        watch.append(f"Responses request retries: {logs.responses_retry}")
    if logs.remote_control_failures:
        watch.append(f"remote-control reconnect failures: {logs.remote_control_failures}")
    if logs.mcp_http_failures or logs.plugin_catalog_failures or logs.model_refresh_failures:
        watch.append(
            "Codex backend/catalog/MCP refresh failures: "
            f"mcp={logs.mcp_http_failures}, plugins={logs.plugin_catalog_failures}, "
            f"models={logs.model_refresh_failures}"
        )
    if network.pac_enabled or network.http_proxy_enabled or network.https_proxy_enabled:
        watch.append("macOS proxy/PAC is enabled")
    if network.tun_routes:
        watch.append(f"utun routes present: {network.tun_routes}")
    if proc.stale_candidate_count:
        action.append(f"{proc.stale_candidate_count} stale Codex Desktop process candidate(s)")
    if any(not probe.ok for probe in probes):
        action.append("live HTTP probes reported failures")

    if networkish and (network.pac_enabled or network.tun_routes or network.proxy_apps):
        next_steps.append(
            "Check the proxy/VPN route used by chatgpt.com; WebSocket/TLS traffic may be unstable."
        )
    if proc.chatgpt_running:
        next_steps.append(
            "If the app is stuck, quit ChatGPT/Codex completely before running `codex-accounts app kill stale`."
        )
    elif proc.stale_candidate_count:
        next_steps.append("Run `codex-accounts app kill stale` to clean leftover desktop services.")
    if logs.mcp_http_failures or logs.plugin_catalog_failures or logs.model_refresh_failures:
        next_steps.append(
            "If proxy changes fix chatgpt.com, rerun this command to confirm catalog/MCP/model refresh errors disappear."
        )
    if not next_steps:
        next_steps.append("No obvious reconnect pattern found in the selected log window.")

    if action:
        return "ACTION", action + watch, next_steps
    if watch:
        return "WATCH", watch, next_steps
    return "OK", [], next_steps


def _thread_counts(conn: sqlite3.Connection) -> tuple[int | None, int | None]:
    try:
        rows = conn.execute("SELECT archived, COUNT(*) FROM threads GROUP BY archived").fetchall()
    except sqlite3.Error:
        return None, None
    counts = {int(row[0]): int(row[1]) for row in rows}
    return counts.get(0, 0), counts.get(1, 0)


def _active_rollout_bytes(conn: sqlite3.Connection) -> int | None:
    try:
        paths = [
            row[0]
            for row in conn.execute(
                "SELECT rollout_path FROM threads WHERE archived = 0 AND rollout_path <> ''"
            )
        ]
    except sqlite3.Error:
        return None
    total = 0
    for raw in paths:
        path = Path(raw).expanduser()
        if path.exists() and path.is_file():
            total += path.stat().st_size
    return total


def _subagent_threads_7d(conn: sqlite3.Connection) -> int | None:
    cutoff_ms = int((time.time() - 7 * 86400) * 1000)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM threads WHERE source LIKE '%thread_spawn%' AND created_at_ms >= ?",
                (cutoff_ms,),
            ).fetchone()[0]
            or 0
        )
    except sqlite3.Error:
        return None


def _verdict(
    account: AccountStatus,
    cfg: ConfigStatus,
    proc: ProcessStatus,
    logs: LogStatus,
    state: StateStatus,
) -> tuple[str, list[str]]:
    action: list[str] = []
    watch: list[str] = []
    if account.problem:
        action.append(account.problem)
    action.extend(cfg.problems)
    if proc.stale_candidate_count:
        action.append(f"{proc.stale_candidate_count} stale process candidate(s)")
    if logs.remote_control_warnings:
        action.append(f"remote-control warnings: {logs.remote_control_warnings}")
    if not state.codex_home_exists:
        action.append("CODEX_HOME missing")
    if not state.state_db_exists:
        action.append("state DB missing")

    if logs.responses_retry:
        watch.append(f"responses retries: {logs.responses_retry}")
    if logs.mcp_warnings:
        watch.append(f"MCP warnings: {logs.mcp_warnings}")
    if logs.plugin_warnings:
        watch.append(f"plugin/skill warnings: {logs.plugin_warnings}")
    if logs.rollout_warnings:
        watch.append(f"rollout warnings: {logs.rollout_warnings}")
    if state.active_threads is not None and state.active_threads >= 300:
        watch.append(f"many active threads: {state.active_threads}")
    if state.active_rollout_bytes is not None and state.active_rollout_bytes >= 1024**3:
        watch.append(f"active rollouts {format_bytes(state.active_rollout_bytes)}")
    if state.subagent_threads_7d:
        watch.append(f"subagent threads 7d: {state.subagent_threads_7d}")

    if action:
        return "ACTION", action + watch
    if watch:
        return "WATCH", watch
    return "OK", []


def _parse_config_file(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {"": {}}
    current = ""
    if not path.exists():
        return sections
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().strip('"')
            sections.setdefault(current, {})
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        sections.setdefault(current, {})[key.strip()] = _strip_toml_value(value.strip())
    return sections


def _strip_toml_value(value: str) -> str:
    if "#" in value:
        value = value.split("#", 1)[0].strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def _as_bool(value: str | None, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.lower() == "true"


def format_bytes(value: int | None) -> str:
    if value is None:
        return "?"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)}B"
            return f"{size:.1f}{unit}"
        size /= 1024


def dumps_json(report: StatusReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def dumps_reconnect_json(report: ReconnectDiagnosis) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
