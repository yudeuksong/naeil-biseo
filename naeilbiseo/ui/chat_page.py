"""대화 화면: 주제별 대화, 스트리밍 답변, 첨부 문서, 승인 대기, 보내는 자료 표시."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
                               QTextBrowser, QVBoxLayout, QWidget)

from ..actions import describe, strip_for_display
from ..assistant import Assistant, TurnResult
from ..fileops import FileOpError
from ..providers import ErrorKind
from . import render
from .dialogs import ApprovalDialog, SentDataDialog, TextDialog
from .workers import TurnWorker

FOLLOWUP_TEXT = "요청하신 문서를 첨부했습니다. 이어서 답해 주세요."


class InputBox(QPlainTextEdit):
    """Enter 로 보내고 Shift+Enter 로 줄을 바꾼다."""
    submitted = Signal()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class ChatPage(QWidget):
    changed = Signal()                 # 일정·할 일·로그 등이 바뀌었을 수 있음
    open_documents = Signal()          # '문서' 탭으로 가기
    choose_workspace = Signal()
    busy_changed = Signal(bool)

    def __init__(self, assistant: Assistant, parent=None):
        super().__init__(parent)
        self.assistant = assistant
        self.db = assistant.db
        self.edition_key = assistant.edition().key
        self.topic_key = "all"
        self.conv_id: int | None = None
        self.worker: TurnWorker | None = None
        self._stream = ""
        self._stream_dirty = False
        self._history_html = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        self.topic_label = QLabel("")
        self.topic_label.setObjectName("sectionTitle")
        top.addWidget(self.topic_label)
        self.conv_box = QComboBox()
        self.conv_box.setMinimumWidth(260)
        self.conv_box.currentIndexChanged.connect(self._on_conv_selected)
        top.addWidget(self.conv_box, 1)
        self.new_btn = QPushButton("＋ 새 대화")
        self.new_btn.clicked.connect(self.new_conversation)
        self.rename_btn = QPushButton("이름 바꾸기")
        self.rename_btn.clicked.connect(self.rename_conversation)
        self.delete_btn = QPushButton("대화 지우기")
        self.delete_btn.clicked.connect(self.delete_conversation)
        for b in (self.new_btn, self.rename_btn, self.delete_btn):
            top.addWidget(b)
        lay.addLayout(top)

        self.ws_banner = QFrame()
        self.ws_banner.setObjectName("pending")
        row = QHBoxLayout(self.ws_banner)
        row.addWidget(QLabel("📁 작업 폴더가 아직 없습니다. 폴더를 정해야 문서를 읽고 파일을 저장할 수 있습니다."), 1)
        pick = QPushButton("작업 폴더 고르기")
        pick.setObjectName("primary")
        pick.clicked.connect(self.choose_workspace.emit)
        row.addWidget(pick)
        lay.addWidget(self.ws_banner)

        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.setOpenExternalLinks(False)
        lay.addWidget(self.view, 1)

        self.starters = QHBoxLayout()
        self.starters_wrap = QWidget()
        self.starters_wrap.setLayout(self.starters)
        self.starters.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.starters_wrap)

        self.pending_frame = QFrame()
        self.pending_frame.setObjectName("pending")
        self.pending_lay = QVBoxLayout(self.pending_frame)
        self.pending_lay.setContentsMargins(12, 8, 12, 8)
        lay.addWidget(self.pending_frame)

        attach_row = QHBoxLayout()
        self.attach_label = QLabel("")
        self.attach_label.setWordWrap(True)
        attach_row.addWidget(self.attach_label, 1)
        self.attach_btn = QPushButton("📎 문서 첨부…")
        self.attach_btn.clicked.connect(self.open_documents.emit)
        attach_row.addWidget(self.attach_btn)
        self.detach_btn = QPushButton("첨부 모두 빼기")
        self.detach_btn.clicked.connect(self.clear_attachments)
        attach_row.addWidget(self.detach_btn)
        lay.addLayout(attach_row)

        send_row = QHBoxLayout()
        self.send_line = QLabel("")
        self.send_line.setWordWrap(True)
        send_row.addWidget(self.send_line, 1)
        self.sent_btn = QPushButton("보내는 자료 보기")
        self.sent_btn.clicked.connect(self.show_sent_data)
        send_row.addWidget(self.sent_btn)
        lay.addLayout(send_row)

        input_row = QHBoxLayout()
        self.input = InputBox()
        self.input.setFixedHeight(84)
        self.input.submitted.connect(self.send)
        input_row.addWidget(self.input, 1)
        self.send_btn = QPushButton("보내기")
        self.send_btn.setObjectName("primary")
        self.send_btn.setFixedHeight(84)
        self.send_btn.setMinimumWidth(110)
        self.send_btn.clicked.connect(self._send_or_stop)
        input_row.addWidget(self.send_btn)
        lay.addLayout(input_row)

        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._flush_stream)

    # ── 바깥에서 부르는 것 ────────────────────────────────────────
    def is_busy(self) -> bool:
        return self.worker is not None

    def set_context(self, edition_key: str, topic_key: str) -> None:
        self.edition_key, self.topic_key = edition_key, topic_key
        self.reload_conversations()

    def reload_conversations(self, select: int | None = None) -> None:
        edition = self.assistant.edition()
        topic = edition.topic(self.topic_key)
        self.topic_label.setText(f"{topic.icon} {topic.name}")
        self.input.setPlaceholderText(f"{topic.hint}  (Enter: 보내기 · Shift+Enter: 줄 바꿈)")
        convs = self.db.list_conversations(self.edition_key, self.topic_key)
        if not convs:
            self.db.create_conversation(self.edition_key, self.topic_key)
            convs = self.db.list_conversations(self.edition_key, self.topic_key)
        self.conv_box.blockSignals(True)
        self.conv_box.clear()
        for c in convs:
            self.conv_box.addItem(f"{c['title']}  ·  {c['updated_at'][5:16].replace('T', ' ')}", c["id"])
        ids = [c["id"] for c in convs]
        target = select if select in ids else (self.conv_id if self.conv_id in ids else ids[0])
        self.conv_box.setCurrentIndex(ids.index(target))
        self.conv_box.blockSignals(False)
        self.conv_id = target
        self.refresh()

    def refresh(self) -> None:
        """대화 내용·첨부·승인 대기·보내는 자료 줄을 다시 그린다."""
        self.ws_banner.setVisible(not self.assistant.workspace())
        if self.conv_id is None:
            return
        honorific = self.assistant.profile(self.edition_key).get("honorific", "")
        messages = self.db.list_messages(self.conv_id)
        self._history_html = "".join(render.render_message(m, honorific) for m in messages)
        if not messages:
            edition = self.assistant.edition()
            topic = edition.topic(self.topic_key)
            self._history_html = (
                f'<div style="margin:24px 8px; color:{render.theme.MUTED};">'
                f'<p style="font-size:large; color:{render.theme.PRIMARY_DARK};"><b>{topic.icon} {topic.name}</b></p>'
                f"<p>{render.esc(topic.hint)}</p>"
                "<p>아래 예시를 누르거나 직접 적어 보세요. 파일 저장·일정 추가 같은 변경은 "
                "승인하신 뒤에만 반영됩니다.</p></div>")
        self._render()
        self._refresh_starters(show=not messages)
        self._refresh_attachments()
        self._refresh_pending()
        self._refresh_send_line()

    # ── 그리기 ───────────────────────────────────────────────────
    def _render(self) -> None:
        extra = render.render_streaming(strip_for_display(self._stream), self._is_mock()) if self.worker else ""
        self.view.setHtml(render.page(self._history_html + extra))
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _flush_stream(self) -> None:
        if self._stream_dirty:
            self._stream_dirty = False
            self._render()

    def _is_mock(self) -> bool:
        return self.assistant.provider().is_mock

    def _refresh_starters(self, show: bool) -> None:
        while self.starters.count():
            item = self.starters.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.starters_wrap.setVisible(show)
        if not show:
            return
        for text in self.assistant.edition().topic(self.topic_key).starters:
            chip = QPushButton(text)
            chip.setObjectName("chip")
            chip.clicked.connect(lambda _=False, t=text: self._use_starter(t))
            self.starters.addWidget(chip)
        self.starters.addStretch(1)

    def _use_starter(self, text: str) -> None:
        self.input.setPlainText(text)
        self.input.setFocus()

    def _refresh_attachments(self) -> None:
        conv = self.db.get_conversation(self.conv_id)
        files = conv["attachments"] if conv else []
        if files:
            self.attach_label.setText("📎 이 대화에 첨부한 문서: " + ", ".join(files))
        else:
            self.attach_label.setText("📎 첨부한 문서 없음 — 문서 내용을 근거로 답하게 하려면 문서를 첨부하세요.")
        self.detach_btn.setVisible(bool(files))

    def _refresh_send_line(self) -> None:
        if self.conv_id is None:
            return
        provider = self.assistant.provider()
        prepared = self.assistant.prepare(self.conv_id, self.input.toPlainText() or "")
        items = [f"{label} {detail}" for label, detail in prepared.bundle.disclosure.items if label != "질문"]
        what = " · ".join(["질문", *items])
        if provider.is_mock:
            self.send_line.setObjectName("sendLineMock")
            self.send_line.setText(f"🧪 모의 모드 — 실제 AI 가 아니며 외부로 아무것도 보내지 않습니다. "
                                   f"(실제 AI 를 연결하면 보내게 될 자료: {what})")
        else:
            self.send_line.setObjectName("sendLine")
            self.send_line.setText(f"☁ 보내기를 누르면 {provider.name}({provider.vendor})로 전송: {what}   "
                                   f"🔒 그 밖의 자료는 이 컴퓨터에만 있습니다.")
        self.send_line.style().unpolish(self.send_line)
        self.send_line.style().polish(self.send_line)
        if prepared.skipped:
            self.attach_label.setText(self.attach_label.text() + "\n⚠ 보내지 않는 문서: "
                                      + ", ".join(f"{p}({why})" for p, why in prepared.skipped))

    def _refresh_pending(self) -> None:
        while self.pending_lay.count():
            item = self.pending_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        proposals = self.db.list_proposals(self.conv_id) if self.conv_id else []
        self.pending_frame.setVisible(bool(proposals))
        if not proposals:
            return
        title = QLabel(f"✋ 승인 대기 {len(proposals)}건 — 승인하셔야 실제로 반영됩니다")
        title.setObjectName("sectionTitle")
        self.pending_lay.addWidget(title)
        for prop in proposals:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            icon = {"write_file": "📄", "request_read": "📖", "add_memory": "🧠", "add_event": "🗓️",
                    "add_todo": "☑️"}.get(prop["type"], "•")
            label = QLabel(f"{icon} {describe(prop['payload'])}")
            label.setWordWrap(True)
            h.addWidget(label, 1)
            if prop["type"] == "write_file":
                ok = QPushButton("내용 보고 승인…")
            elif prop["type"] == "request_read":
                ok = QPushButton("읽게 허락")
            else:
                ok = QPushButton("승인")
            ok.setObjectName("primary")
            ok.clicked.connect(lambda _=False, p=prop: self.approve(p))
            no = QPushButton("거절")
            no.clicked.connect(lambda _=False, p=prop: self.reject(p))
            h.addWidget(ok)
            h.addWidget(no)
            self.pending_lay.addWidget(row)

    # ── 대화 관리 ────────────────────────────────────────────────
    def _on_conv_selected(self, index: int) -> None:
        if index < 0 or self.is_busy():
            return
        self.conv_id = self.conv_box.itemData(index)
        self.refresh()

    def new_conversation(self) -> None:
        if self.is_busy():
            return
        conv_id = self.db.create_conversation(self.edition_key, self.topic_key)
        self.reload_conversations(select=conv_id)
        self.input.setFocus()

    def rename_conversation(self) -> None:
        conv = self.db.get_conversation(self.conv_id)
        dialog = TextDialog("대화 이름 바꾸기", "대화 이름", conv["title"], multiline=False, parent=self)
        if dialog.exec() and dialog.value():
            self.db.rename_conversation(self.conv_id, dialog.value()[:60])
            self.reload_conversations(select=self.conv_id)

    def delete_conversation(self) -> None:
        if self.is_busy():
            return
        answer = QMessageBox.question(self, "대화 지우기", "이 대화와 그 안의 승인 대기 제안을 지울까요?\n"
                                                        "(만든 파일과 작업 로그는 그대로 남습니다.)")
        if answer == QMessageBox.StandardButton.Yes:
            self.db.delete_conversation(self.conv_id)
            self.conv_id = None
            self.reload_conversations()

    def clear_attachments(self) -> None:
        self.db.set_attachments(self.conv_id, [])
        self.refresh()

    def show_sent_data(self) -> None:
        provider = self.assistant.provider()
        text = self.input.toPlainText().strip() or "(여기에 질문이 들어갑니다)"
        prepared = self.assistant.prepare(self.conv_id, text)
        SentDataDialog(prepared.bundle, f"{provider.name}({provider.vendor})", provider.is_mock, self).exec()

    # ── 보내기·멈추기 ────────────────────────────────────────────
    def _send_or_stop(self) -> None:
        if self.is_busy():
            self.stop()
        else:
            self.send()

    def send(self, text: str | None = None) -> None:
        if self.is_busy() or self.conv_id is None:
            return
        text = (text if isinstance(text, str) else self.input.toPlainText()).strip()
        if not text:
            return
        self.input.clear()
        self._stream = ""
        self.worker = TurnWorker(self.assistant, self.conv_id, text, self)
        self.worker.delta.connect(self._on_delta)
        self.worker.done.connect(self._on_done)
        self._set_busy(True)
        # 보낸 질문을 바로 보여 준다
        honorific = self.assistant.profile(self.edition_key).get("honorific", "")
        self._history_html += render.render_message({"role": "user", "content": text, "created_at": ""}, honorific)
        self._refresh_starters(show=False)
        self._render()
        self._timer.start()
        self.worker.start()

    def stop(self) -> None:
        if self.worker:
            self.send_btn.setEnabled(False)
            self.send_btn.setText("멈추는 중…")
            self.worker.cancel()

    def _set_busy(self, busy: bool) -> None:
        self.send_btn.setEnabled(True)
        self.send_btn.setText("■ 멈춤" if busy else "보내기")
        self.send_btn.setObjectName("danger" if busy else "primary")
        self.send_btn.style().unpolish(self.send_btn)
        self.send_btn.style().polish(self.send_btn)
        for w in (self.conv_box, self.new_btn, self.rename_btn, self.delete_btn):
            w.setEnabled(not busy)
        self.busy_changed.emit(busy)

    def _on_delta(self, piece: str) -> None:
        self._stream += piece
        self._stream_dirty = True

    def _on_done(self, result: TurnResult) -> None:
        self._timer.stop()
        worker, self.worker = self.worker, None
        if worker:
            worker.wait(2000)
            worker.deleteLater()
        self._stream = ""
        self._set_busy(False)
        self.reload_conversations(select=result.conversation_id)
        self.changed.emit()
        if result.error and result.error.kind not in (ErrorKind.CANCELLED,):
            self.input.setFocus()

    # ── 승인·거절 ────────────────────────────────────────────────
    def approve(self, prop: dict) -> None:
        plan = None
        if prop["type"] == "write_file":
            try:
                plan = self.assistant.plan_for(prop)
            except FileOpError as exc:
                if exc.code == "no_workspace":
                    QMessageBox.information(self, "작업 폴더 필요", exc.message)
                    self.choose_workspace.emit()
                    return
                outcome = self.assistant.approve(prop["id"])      # 거절 사유를 기록하고 닫는다
                QMessageBox.warning(self, "저장할 수 없는 제안", outcome.message)
                self.refresh()
                self.changed.emit()
                return
            if ApprovalDialog(plan, self.assistant.workspace(), self).exec() != ApprovalDialog.DialogCode.Accepted:
                return
        outcome = self.assistant.approve(prop["id"], plan)
        if not outcome.ok:
            QMessageBox.warning(self, "반영하지 못했습니다", outcome.message)
        self.refresh()
        self.changed.emit()
        if outcome.followup and not self.is_busy():
            self.send(FOLLOWUP_TEXT)

    def reject(self, prop: dict) -> None:
        self.assistant.reject(prop["id"])
        self.refresh()
        self.changed.emit()
