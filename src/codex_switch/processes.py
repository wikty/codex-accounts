"""Codex Desktop background process discovery and cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass

from codex_switch import config

APP_SERVER_MARKER = "/Applications/ChatGPT.app/Contents/Resources/codex"
APP_SERVER_ARG = "app-server"
TOOL_RUNTIME_MARKER = "/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node_repl"
CHATGPT_APP_MARKER = "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"
COMPUTER_USE_RELATIVE_PATH = (
    "computer-use/Codex Computer Use.app/Contents/MacOS/SkyComputerUseService"
)


@dataclass(frozen=True)
class CodexProcess:
    """A safe-to-manage Codex Desktop background process."""

    pid: int
    ppid: int
    cpu: str
    mem: str
    kind: str
    command: str


@dataclass(frozen=True)
class KillResult:
    """Result of a stale-process cleanup attempt."""

    found: list[CodexProcess]
    signaled: list[CodexProcess]
    missing: list[CodexProcess]
    failed: list[tuple[CodexProcess, str]]
    remaining: list[CodexProcess]


class ChatGPTStillRunning(RuntimeError):
    """Raised when cleanup is requested while the desktop app is still open."""


class UnsupportedPlatform(RuntimeError):
    """Raised when a process cleanup operation is unavailable on this platform."""


def is_supported_platform() -> bool:
    """Return True when this module knows Codex Desktop's process layout."""

    return config.IS_MACOS


def list_stale_processes() -> list[CodexProcess]:
    """Return leftover Codex Desktop background processes we know how to clean."""

    if not is_supported_platform():
        return []

    processes: list[CodexProcess] = []
    for pid, ppid, cpu, mem, command in _iter_process_table():
        kind = classify_command(command)
        if kind:
            processes.append(
                CodexProcess(pid=pid, ppid=ppid, cpu=cpu, mem=mem, kind=kind, command=command)
            )
    return processes


def classify_command(command: str) -> str | None:
    """Return a user-facing process kind for commands managed by this tool."""

    if command.startswith(APP_SERVER_MARKER) and APP_SERVER_ARG in command:
        return "background service"
    if command.startswith(TOOL_RUNTIME_MARKER):
        return "tool runtime"
    if command.startswith(_computer_use_service_path()):
        return "tool service"
    return None


def is_chatgpt_app_running() -> bool:
    """Return True when the desktop app is still open.

    Cleanup refuses to run in that state because these background processes may
    be active children of a healthy app session.
    """

    if config.IS_MACOS:
        return any(command.startswith(CHATGPT_APP_MARKER) for *_, command in _iter_process_table())
    return False


def terminate_stale_processes(wait_seconds: float = 2.0) -> KillResult:
    """Terminate all known stale Codex Desktop background processes."""

    if not is_supported_platform():
        raise UnsupportedPlatform("process cleanup is currently macOS-only")

    if is_chatgpt_app_running():
        raise ChatGPTStillRunning("ChatGPT/Codex is still running")

    found = list_stale_processes()
    if _has_live_external_parent(found):
        raise ChatGPTStillRunning("Codex background processes still have a live parent")

    signaled: list[CodexProcess] = []
    missing: list[CodexProcess] = []
    failed: list[tuple[CodexProcess, str]] = []

    for proc in found:
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            missing.append(proc)
        except OSError as e:
            failed.append((proc, str(e)))
        else:
            signaled.append(proc)

    if signaled and wait_seconds > 0:
        time.sleep(wait_seconds)

    remaining = list_stale_processes()
    return KillResult(
        found=found,
        signaled=signaled,
        missing=missing,
        failed=failed,
        remaining=remaining,
    )


def _iter_process_table() -> list[tuple[int, int, str, str, str]]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,pcpu=,pmem=,command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []

    rows: list[tuple[int, int, str, str, str]] = []
    for line in result.stdout.splitlines():
        parsed = _parse_ps_line(line)
        if parsed is not None:
            rows.append(parsed)
    return rows


def _computer_use_service_path() -> str:
    return str(config.codex_home() / COMPUTER_USE_RELATIVE_PATH)


def _has_live_external_parent(processes: list[CodexProcess]) -> bool:
    candidate_pids = {proc.pid for proc in processes}
    for proc in processes:
        if proc.ppid in (0, 1) or proc.ppid in candidate_pids:
            continue
        if _pid_exists(proc.ppid):
            return True
    return False


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _parse_ps_line(line: str) -> tuple[int, int, str, str, str] | None:
    parts = line.strip().split(maxsplit=4)
    if len(parts) != 5:
        return None
    try:
        pid = int(parts[0])
        ppid = int(parts[1])
    except ValueError:
        return None
    return pid, ppid, parts[2], parts[3], parts[4]
