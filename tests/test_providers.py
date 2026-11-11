"""AI 연결 — 가짜 CLI 로 설치·로그인·스트리밍·취소·제한 시간·안전 검사를 확인한다.

주의: 여기의 CLI 는 tests/fake_cli.py(가짜)다. 실제 AI 연동 확인은 test_real_claude.py 가 따로 한다.
"""
from __future__ import annotations

import json
import os
import threading
import time

import pytest

from naeilbiseo.providers import (ChatRequest, ClaudeCliProvider, CodexCliProvider, ErrorKind, GeminiCliProvider,
                                  MOCK_BANNER, MockProvider, ProviderError)
from naeilbiseo.providers.base import RunState, classify_failure

REQUEST = ChatRequest(system="당신은 비서입니다.", prompt="[사용자 요청]\n안녕하세요 & \"따옴표\" %PATH% $(whoami)",
                      timeout_sec=20)


def run(provider, request=REQUEST, cancel=None):
    chunks: list[str] = []
    result = provider.run(request, chunks.append, cancel or threading.Event())
    return result, chunks


# ── 설치·로그인 상태 ─────────────────────────────────────────────────
def test_not_installed(tmp_path):
    provider = ClaudeCliProvider(executable_override=str(tmp_path / "없는_claude"))
    status = provider.status()
    assert not status.installed and not status.usable and status.summary == "설치되지 않음"
    with pytest.raises(ProviderError) as exc:
        run(provider)
    assert exc.value.kind == ErrorKind.NOT_INSTALLED


def test_status_ok_lists_enforced_restrictions(fake_provider):
    status = fake_provider.status()
    assert status.installed and status.logged_in is True and status.usable
    assert status.version.startswith("9.9.9")
    assert any("--tools" in r for r in status.restrictions)
    assert "should-not-be-used@example.com" not in json.dumps(status.__dict__, ensure_ascii=False)


def test_status_not_logged_in(fake_provider, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "not_logged_in")
    status = fake_provider.status()
    assert status.installed and status.logged_in is False and not status.usable
    assert status.summary == "로그인 필요"


def test_run_not_logged_in(fake_provider, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "not_logged_in")
    with pytest.raises(ProviderError) as exc:
        run(fake_provider)
    assert exc.value.kind == ErrorKind.NOT_LOGGED_IN
    assert "claude auth login" in exc.value.message


def test_old_cli_without_tool_blocking_is_refused(fake_provider, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "old_version")
    status = fake_provider.status()
    assert status.installed and not status.usable
    with pytest.raises(ProviderError) as exc:
        run(fake_provider)
    assert exc.value.kind == ErrorKind.UNSAFE_CONFIG


# ── 정상 실행 ────────────────────────────────────────────────────────
def test_streaming_and_safe_invocation(fake_provider, fake_cli, isolated_data_dir):
    result, chunks = run(fake_provider)
    assert len(chunks) > 1 and "".join(chunks) == result.text
    assert result.text.startswith("결론부터") and not result.is_mock
    assert result.meta["init_checked"] and result.meta["tools_at_start"] == []

    rec = json.loads(fake_cli["record"].read_text(encoding="utf-8"))
    argv = rec["argv"]
    assert argv[argv.index("--tools") + 1] == ""                      # 도구 전부 끔
    assert {"--strict-mcp-config", "--safe-mode", "--disable-slash-commands"} <= set(argv)
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--bare" not in argv and "--dangerously-skip-permissions" not in argv
    assert not any("안녕하세요" in a or "비서" in a for a in argv)       # 사용자 글은 인자로 나가지 않음
    assert "안녕하세요" in rec["stdin"] and "$(whoami)" in rec["stdin"]  # stdin 으로 그대로(셸 해석 없음)
    assert rec["system"] == "당신은 비서입니다."
    run_root = os.path.normcase(os.path.realpath(isolated_data_dir / "cli_run"))
    assert os.path.normcase(os.path.realpath(rec["cwd"])).startswith(run_root)   # 앱의 빈 실행 폴더
    assert rec["cwd_files"] == ["system_prompt.txt"]
    assert list((isolated_data_dir / "cli_run").iterdir()) == []      # 끝나면 실행 폴더를 지움


def test_model_name_is_validated(fake_provider):
    with pytest.raises(ProviderError):
        run(fake_provider, ChatRequest(system="s", prompt="p", model="sonnet; rm -rf /"))
    result, _ = run(fake_provider, ChatRequest(system="s", prompt="p", model="sonnet"))
    assert result.text


# ── 취소·제한 시간 ───────────────────────────────────────────────────
def test_cancel_stops_cli_quickly(fake_provider, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "hang")
    cancel = threading.Event()
    threading.Timer(0.6, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(ProviderError) as exc:
        run(fake_provider, cancel=cancel)
    assert exc.value.kind == ErrorKind.CANCELLED
    assert time.monotonic() - started < 15


def test_cancel_before_start(fake_provider):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ProviderError) as exc:
        run(fake_provider, cancel=cancel)
    assert exc.value.kind == ErrorKind.CANCELLED


def test_timeout(fake_provider, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "hang")
    started = time.monotonic()
    with pytest.raises(ProviderError) as exc:
        run(fake_provider, ChatRequest(system="s", prompt="p", timeout_sec=1.5))
    assert exc.value.kind == ErrorKind.TIMEOUT
    assert time.monotonic() - started < 15


# ── 안전 검사·오류 분류 ──────────────────────────────────────────────
def test_cli_started_with_tools_is_killed(fake_provider, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "unsafe_tools")
    started = time.monotonic()
    with pytest.raises(ProviderError) as exc:
        run(fake_provider)
    assert exc.value.kind == ErrorKind.UNSAFE_CONFIG and "Bash" in exc.value.detail
    assert time.monotonic() - started < 15


def test_tool_use_attempt_is_killed(fake_provider, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "tool_use")
    with pytest.raises(ProviderError) as exc:
        run(fake_provider)
    assert exc.value.kind == ErrorKind.UNSAFE_CONFIG


def test_usage_limit_is_reported_without_promises(fake_provider, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "usage_limit")
    with pytest.raises(ProviderError) as exc:
        run(fake_provider)
    assert exc.value.kind == ErrorKind.USAGE_LIMIT and "한도" in exc.value.message


def test_cli_rejecting_a_flag_is_cli_error(fake_provider, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "bad_flag")
    with pytest.raises(ProviderError) as exc:
        run(fake_provider)
    assert exc.value.kind == ErrorKind.CLI_ERROR and "unknown option" in exc.value.detail


def test_oversized_prompt_is_refused_before_launch(fake_provider, fake_cli):
    with pytest.raises(ProviderError) as exc:
        run(fake_provider, ChatRequest(system="s", prompt="가" * 1_000_000))
    assert exc.value.kind == ErrorKind.PROMPT_TOO_LARGE
    assert not fake_cli["record"].exists()


@pytest.mark.parametrize("text,code,kind", [
    ("Invalid API key · Please run /login", None, ErrorKind.NOT_LOGGED_IN),
    ("", 401, ErrorKind.NOT_LOGGED_IN),
    ("You've hit your usage limit", None, ErrorKind.USAGE_LIMIT),
    ("", 429, ErrorKind.USAGE_LIMIT),
    ("Something exploded", None, ErrorKind.CLI_ERROR),
])
def test_classify_failure(text, code, kind):
    assert classify_failure(text, code) == kind


# ── 모의 모드 ────────────────────────────────────────────────────────
def test_mock_is_clearly_labelled_and_cancellable():
    mock = MockProvider(chunk_delay=0)
    assert mock.is_mock and mock.status().usable
    result, chunks = run(mock, ChatRequest(system="s", prompt="[사용자 요청]\n홍보글 만들어 줘"))
    assert result.is_mock and result.text.startswith(MOCK_BANNER) and "naeil-actions" in result.text
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ProviderError) as exc:
        run(mock, cancel=cancel)
    assert exc.value.kind == ErrorKind.CANCELLED


# ── Codex·Gemini: 출력 해석기만 확인(실제 CLI 로는 검증하지 못함) ────
def test_codex_event_parsing():
    provider, state, seen = CodexCliProvider(), RunState(), []
    assert provider.experimental
    for event in (
        {"type": "thread.started", "thread_id": "t"},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "첫 문단"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "둘째 문단"}},
        {"type": "turn.completed"},
    ):
        provider.handle_line(json.dumps(event, ensure_ascii=False), state, seen.append)
    assert state.text() == "첫 문단\n\n둘째 문단"
    assert state.meta["tools_used"] == ["command_execution: ls"]
    provider.handle_line(json.dumps({"type": "turn.failed", "error": {"message": "Not logged in"}}), state, seen.append)
    assert state.error.kind == ErrorKind.NOT_LOGGED_IN


def test_codex_command_uses_read_only_sandbox_and_stdin(tmp_path):
    provider = CodexCliProvider(executable_override=str(tmp_path / "codex"))
    provider._help_cache[(str(tmp_path / "codex"), "exec")] = "--ephemeral"
    args, stdin_text = provider.build_command(str(tmp_path / "codex"), REQUEST, str(tmp_path))
    assert args[1:6] == ["exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check"]
    assert args[-1] == "-" and "안녕하세요" in stdin_text and not any("안녕하세요" in a for a in args)


def test_gemini_event_parsing_and_command(tmp_path):
    provider, state, seen = GeminiCliProvider(), RunState(), []
    assert provider.experimental
    for event in (
        {"type": "init", "model": "gemini-x"},
        {"type": "message", "role": "user", "content": "질문"},
        {"type": "message", "role": "assistant", "content": "안녕", "delta": True},
        {"type": "message", "role": "assistant", "content": "하세요", "delta": True},
        {"type": "tool_use", "tool_name": "read_file"},
        {"type": "result", "status": "success"},
    ):
        provider.handle_line(json.dumps(event, ensure_ascii=False), state, seen.append)
    assert state.text() == "안녕하세요" and state.meta["tools_used"] == ["read_file"] and state.error is None
    args, stdin_text = provider.build_command("gemini", REQUEST, str(tmp_path))
    assert args == ["gemini", "--output-format", "stream-json", "--approval-mode", "default"]
    assert "--yolo" not in args and "안녕하세요" in stdin_text
