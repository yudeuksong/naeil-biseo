"""화면 연기 테스트(offscreen) — 모의 모드로 보내기 → 승인 → 파일 저장 → 다시 열기."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from naeilbiseo.assistant import Assistant  # noqa: E402
from naeilbiseo.db import Database  # noqa: E402
from naeilbiseo.providers import MockProvider  # noqa: E402
from naeilbiseo.ui import theme  # noqa: E402
from naeilbiseo.ui.dialogs import ApprovalDialog  # noqa: E402
from naeilbiseo.ui.main_window import TAB_DOCS, TAB_LOG, TAB_MEMORY, TAB_NOTES, TAB_PLAN, MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply_theme(instance, 1)
    return instance


def wait_until(app, condition, timeout_ms=10_000):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: condition() and loop.quit())
    timer.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    assert condition(), "제한 시간 안에 끝나지 않음"


def open_window(db_file):
    db = Database(db_file)
    assistant = Assistant(db, provider_factory=lambda _p, _e: MockProvider(chunk_delay=0))
    window = MainWindow(assistant, run_scheduler=False, check_status=False)
    window.show()
    return db, assistant, window


def test_send_approve_and_reopen(app, tmp_path, workspace, monkeypatch):
    monkeypatch.setattr(ApprovalDialog, "exec", lambda self: ApprovalDialog.DialogCode.Accepted)
    db_file = tmp_path / "ui.sqlite3"
    db, assistant, window = open_window(db_file)
    assistant.set_workspace(str(workspace))
    assert "모의 모드" in window.status_btn.text()
    assert window.topic_list.count() == 7                       # 일반용 주제 일곱

    window.switch_edition("pastor")
    assert window.topic_list.count() == 6                       # 목회자용 주제 여섯
    window.topic_list.setCurrentRow(1)                          # 설교 준비
    chat = window.chat
    assert chat.topic_key == "sermon" and not chat.pending_frame.isVisibleTo(window)

    assistant.attach(chat.conv_id, "설교/시편23편_메모.md")
    chat.input.setPlainText("설교 개요 초안을 만들어 주세요. 그리고 기억해 주세요.")
    chat.send()
    assert chat.is_busy() and chat.send_btn.text() == "■ 멈춤"
    wait_until(app, lambda: not chat.is_busy())

    html = chat.view.toPlainText()
    assert "모의 응답" in html and "실제 AI 아님" in html
    assert "모의 모드" in chat.send_line.text() and "보내지 않습니다" in chat.send_line.text()
    proposals = db.list_proposals(chat.conv_id)
    assert [p["type"] for p in proposals] == ["write_file", "add_memory"]
    assert chat.pending_frame.isVisibleTo(window)

    target = workspace / "모의_연습" / "모의_초안.md"
    assert not target.exists()
    chat.approve(proposals[0])                                   # 승인 창(가짜 승인) → 저장
    assert target.is_file()
    chat.reject(proposals[1])
    assert db.list_proposals(chat.conv_id) == [] and db.list_memories() == []

    # 다른 탭들이 오류 없이 그려지는지
    db.add_event("주일 설교", "2099-01-04", "11:00")
    db.add_todo("주보 광고 쓰기")
    db.add_memory("설교는 30분 안쪽")
    window.refresh_side()
    for tab in (TAB_DOCS, TAB_PLAN, TAB_MEMORY, TAB_NOTES, TAB_LOG):
        window.tabs.setCurrentIndex(tab)
        app.processEvents()
    assert window.log.table.rowCount() >= 5
    assert window.plan.events.rowCount() == 1 and window.plan.todos.rowCount() == 1
    assert window.memory.table.rowCount() == 1
    assert any("모의_초안.md" in window.docs.table.item(r, 0).text() for r in range(window.docs.table.rowCount()))
    conv_id = chat.conv_id
    window.close()
    db.close()

    # 재시작: 판·주제·대화·할 일·기억이 그대로
    db2, _assistant2, window2 = open_window(db_file)
    try:
        assert window2.assistant.edition().key == "pastor" and window2.chat.topic_key == "sermon"
        assert window2.chat.conv_id == conv_id
        assert "설교 개요 초안을 만들어 주세요" in window2.chat.view.toPlainText()
        assert window2.todo_list.item(0).text().startswith("주보 광고 쓰기")
        assert [m["text"] for m in db2.list_memories()] == ["설교는 30분 안쪽"]
    finally:
        window2.close()
        db2.close()


def test_stop_button_cancels(app, tmp_path):
    db = Database(tmp_path / "stop.sqlite3")
    assistant = Assistant(db, provider_factory=lambda _p, _e: MockProvider(chunk_delay=0.2))
    window = MainWindow(assistant, run_scheduler=False, check_status=False)
    window.show()
    try:
        chat = window.chat
        chat.input.setPlainText("오래 걸리는 질문")
        chat.send()
        wait_until(app, lambda: chat._stream != "", 5000)
        chat.stop()
        wait_until(app, lambda: not chat.is_busy(), 8000)
        roles = [m["role"] for m in db.list_messages(chat.conv_id)]
        assert roles == ["user", "notice"] and "멈췄습니다" in chat.view.toPlainText()
        assert chat.send_btn.text() == "보내기"
    finally:
        window.close()
        db.close()
