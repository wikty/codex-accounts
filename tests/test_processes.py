"""Tests for Codex Desktop process discovery and cleanup guards."""

from __future__ import annotations

from codex_switch import processes


def test_is_chatgpt_app_running_uses_app_path(monkeypatch):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: True)
    monkeypatch.setattr(
        processes,
        "_iter_process_table",
        lambda: [
            (
                10,
                1,
                "0.0",
                "1.0",
                "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT",
            )
        ],
    )
    assert processes.is_chatgpt_app_running() is True


def test_is_chatgpt_app_running_ignores_background_service_only(monkeypatch):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: True)
    monkeypatch.setattr(
        processes,
        "_iter_process_table",
        lambda: [
            (
                20,
                1,
                "0.0",
                "1.0",
                "/Applications/ChatGPT.app/Contents/Resources/codex app-server",
            )
        ],
    )
    assert processes.is_chatgpt_app_running() is False


def test_classify_computer_use_service_uses_codex_home(monkeypatch, tmp_path):
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    command = (
        str(codex_home)
        + "/computer-use/Codex Computer Use.app/Contents/MacOS/SkyComputerUseService"
    )

    assert processes.classify_command(command) == "tool service"


def test_list_processes_includes_computer_use_service(monkeypatch, tmp_path):
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(processes, "is_supported_platform", lambda: True)
    monkeypatch.setattr(
        processes,
        "_iter_process_table",
        lambda: [
            (
                30,
                1,
                "0.0",
                "0.1",
                str(codex_home)
                + "/computer-use/Codex Computer Use.app/Contents/MacOS/SkyComputerUseService",
            )
        ],
    )

    rows = processes.list_stale_processes()
    assert len(rows) == 1
    assert rows[0].kind == "tool service"


def test_list_processes_is_empty_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: False)

    def fail_iter():
        raise AssertionError("unsupported platforms should not scan process layout")

    monkeypatch.setattr(processes, "_iter_process_table", fail_iter)
    assert processes.list_stale_processes() == []


def test_terminate_raises_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(processes, "is_supported_platform", lambda: False)
    try:
        processes.terminate_stale_processes()
    except processes.UnsupportedPlatform:
        pass
    else:
        raise AssertionError("expected UnsupportedPlatform")
