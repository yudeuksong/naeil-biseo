"""실제 Claude Code CLI 로 도는 통합 시나리오 — 기본은 건너뛴다.

실제 AI 를 부르므로 구독 사용량이 조금 든다. 직접 켜야만 실행된다:

    NAEILBISEO_REAL_CLAUDE=1 python -m pytest tests/test_real_claude.py -v -s

Claude Code 가 설치·로그인되어 있지 않으면 건너뛴다.
"""
from __future__ import annotations

import os
import threading

import pytest

from naeilbiseo.assistant import Assistant
from naeilbiseo.db import Database
from naeilbiseo.providers import ClaudeCliProvider

pytestmark = pytest.mark.skipif(os.environ.get("NAEILBISEO_REAL_CLAUDE") != "1",
                                reason="실제 AI 호출 테스트는 NAEILBISEO_REAL_CLAUDE=1 일 때만 실행")


def test_real_claude_core_scenario(tmp_path, workspace):
    provider = ClaudeCliProvider()
    status = provider.status()
    if not (status.installed and status.usable and status.logged_in):
        pytest.skip(f"Claude Code 를 쓸 수 없음: {status.summary}")
    print(f"\n[실제 CLI] {status.version} · {status.summary}")

    db_file = tmp_path / "real.sqlite3"
    db = Database(db_file)
    assistant = Assistant(db, provider_factory=lambda _p, _e: ClaudeCliProvider())
    assistant.set_workspace(str(workspace))
    assistant.set_edition("pastor")
    conv = db.create_conversation("pastor", "sermon")
    assistant.attach(conv, "설교/시편23편_메모.md")

    chunks: list[str] = []
    result = assistant.run_turn(
        conv,
        "첨부한 메모에 적힌 문장을 그대로 한 번 인용하고, 그 메모를 바탕으로 세 줄짜리 설교 개요를 "
        "'설교/시편23편_개요.md' 파일로 저장하도록 제안해 주세요.",
        chunks.append, threading.Event())
    assert result.error is None, result.error
    assert not result.is_mock
    print(f"[실제 답변 {len(chunks)}조각]\n{result.text}\n")
    assert len(chunks) >= 1 and "목자" in result.text                    # 첨부 문서 내용을 실제로 받았다

    files = [p for p in result.proposals if p["type"] == "write_file"]
    assert files, f"파일 제안이 없음. 해석 오류: {result.parse_errors}"
    plan = assistant.plan_for(files[0])
    outcome = assistant.approve(files[0]["id"], plan)
    assert outcome.ok, outcome.message
    saved = workspace / files[0]["payload"]["path"]
    assert saved.is_file() and saved.stat().st_size > 0
    print(f"[저장됨] {files[0]['payload']['path']} ({saved.stat().st_size}바이트)")

    log = {row["kind"]: row for row in db.list_log(conversation_id=conv)}
    assert {"doc_read", "ai_answer", "proposal", "file_created"} <= set(log)
    assert log["ai_answer"]["detail"]["mock"] is False
    assert log["ai_answer"]["detail"]["tools_at_start"] == []            # 실제 CLI 가 도구 0개로 시작함
    assert log["ai_answer"]["detail"]["init_checked"] is True
    db.close()

    db2 = Database(db_file)
    try:
        assert [m["role"] for m in db2.list_messages(conv)] == ["user", "assistant"]
        assert db2.list_proposals(conv, status=None)[0]["status"] in ("applied", "pending", "rejected")
    finally:
        db2.close()
