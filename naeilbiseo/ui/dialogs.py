"""작은 창들: 파일 승인(차이 보기), 일정·할 일·기억 편집, 보내는 자료 보기."""
from __future__ import annotations

import html

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QCheckBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout)

from ..dday import parse_date, parse_time, today_local
from ..fileops import ChangePlan
from ..prompts import PromptBundle
from ..workspace import human_size
from . import theme


def _buttons(dialog: QDialog, ok_text: str, cancel_text: str = "취소") -> QDialogButtonBox:
    box = QDialogButtonBox()
    ok = box.addButton(ok_text, QDialogButtonBox.ButtonRole.AcceptRole)
    ok.setObjectName("primary")
    box.addButton(cancel_text, QDialogButtonBox.ButtonRole.RejectRole)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def diff_html(plan: ChangePlan) -> str:
    rows = []
    for line in plan.diff.splitlines():
        text = html.escape(line) or "&nbsp;"
        if line.startswith("+++") or line.startswith("---"):
            style = f"color:{theme.MUTED};"
        elif line.startswith("@@"):
            style = "color:#5b4b9b; background-color:#f1eefb;"
        elif line.startswith("+"):
            style = "background-color:#e3f4e8; color:#14532d;"
        elif line.startswith("-"):
            style = "background-color:#fde8e6; color:#8c1d18;"
        else:
            style = ""
        rows.append(f'<div style="{style} white-space:pre-wrap; font-family:monospace;">{text}</div>')
    return "".join(rows) or "<p>바뀌는 내용이 없습니다.</p>"


class ApprovalDialog(QDialog):
    """AI 가 제안한 파일 변경을 보여 주고 승인을 받는다."""

    def __init__(self, plan: ChangePlan, workspace: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("파일 저장 승인")
        self.resize(860, 640)
        lay = QVBoxLayout(self)
        if plan.kind == "create":
            head = f"<b>새 파일을 만듭니다</b> — {html.escape(plan.rel_path)}"
            sub = f"{plan.added}줄 · {human_size(len(plan.new_content.encode('utf-8')))}"
        else:
            head = f"<b>기존 파일을 고칩니다</b> — {html.escape(plan.rel_path)}"
            sub = (f"더하는 줄 {plan.added} · 빼는 줄 {plan.removed} · 고치기 전 파일은 작업 폴더의 "
                   "「.내일비서_백업」에 따로 보관합니다.")
        title = QLabel(head)
        title.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(title)
        info = QLabel(f"{sub}\n저장 위치: {workspace}")
        info.setObjectName("muted")
        info.setWordWrap(True)
        lay.addWidget(info)
        view = QTextBrowser()
        view.setOpenLinks(False)
        view.setHtml(diff_html(plan))
        lay.addWidget(view, 1)
        note = QLabel("초록 줄은 새로 들어가는 내용, 빨간 줄은 빠지는 내용입니다. 승인해야만 파일이 바뀝니다.")
        note.setObjectName("muted")
        lay.addWidget(note)
        lay.addWidget(_buttons(self, "승인하고 저장", "닫기(아직 저장 안 함)"))


class TextDialog(QDialog):
    """글 한 덩어리를 입력받는다(기억 추가·수정, 대화 이름 등)."""

    def __init__(self, title: str, label: str, text: str = "", multiline: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 300 if multiline else 150)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(label))
        if multiline:
            self.edit = QPlainTextEdit(text)
        else:
            self.edit = QLineEdit(text)
        lay.addWidget(self.edit)
        lay.addWidget(_buttons(self, "저장"))

    def value(self) -> str:
        text = self.edit.toPlainText() if isinstance(self.edit, QPlainTextEdit) else self.edit.text()
        return text.strip()


class _DateRow(QHBoxLayout):
    def __init__(self, value: str, optional: bool):
        super().__init__()
        self.optional = optional
        self.check = QCheckBox("날짜 정하기")
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd (ddd)")
        parsed = parse_date(value) or today_local()
        self.date.setDate(QDate(parsed.year, parsed.month, parsed.day))
        if optional:
            self.check.setChecked(bool(value))
            self.date.setEnabled(bool(value))
            self.check.toggled.connect(self.date.setEnabled)
            self.addWidget(self.check)
        self.addWidget(self.date, 1)

    def value(self) -> str:
        if self.optional and not self.check.isChecked():
            return ""
        return self.date.date().toString("yyyy-MM-dd")


class EventDialog(QDialog):
    def __init__(self, event: dict | None = None, parent=None):
        super().__init__(parent)
        event = event or {}
        self.setWindowTitle("일정 고치기" if event else "일정 추가")
        self.resize(520, 320)
        form = QFormLayout(self)
        self.title = QLineEdit(event.get("title", ""))
        self.title.setPlaceholderText("예: 주일 설교, 거래처 미팅")
        self.date = _DateRow(event.get("date", ""), optional=False)
        self.time = QLineEdit(event.get("time", ""))
        self.time.setPlaceholderText("예: 14:30 (비워 둬도 됩니다)")
        self.kind = QLineEdit(event.get("kind", ""))
        self.kind.setPlaceholderText("예: 설교, 심방, 미팅, 마감")
        self.note = QLineEdit(event.get("note", ""))
        self.error = QLabel("")
        self.error.setStyleSheet(f"color:{theme.DANGER};")
        form.addRow("제목", self.title)
        form.addRow("날짜", self.date)
        form.addRow("시각", self.time)
        form.addRow("종류", self.kind)
        form.addRow("메모", self.note)
        form.addRow(self.error)
        form.addRow(_buttons(self, "저장"))

    def accept(self) -> None:
        if not self.title.text().strip():
            self.error.setText("제목을 적어 주세요.")
            return
        if parse_time(self.time.text()) is None:
            self.error.setText("시각은 14:30 처럼 적어 주세요.")
            return
        super().accept()

    def value(self) -> dict:
        return {"title": self.title.text().strip(), "date": self.date.value(),
                "time": parse_time(self.time.text()) or "", "kind": self.kind.text().strip(),
                "note": self.note.text().strip()}


class TodoDialog(QDialog):
    def __init__(self, todo: dict | None = None, parent=None):
        super().__init__(parent)
        todo = todo or {}
        self.setWindowTitle("할 일 고치기" if todo else "할 일 추가")
        self.resize(520, 240)
        form = QFormLayout(self)
        self.title = QLineEdit(todo.get("title", ""))
        self.title.setPlaceholderText("예: 주보 광고 쓰기")
        self.due = _DateRow(todo.get("due", ""), optional=True)
        self.note = QLineEdit(todo.get("note", ""))
        self.error = QLabel("")
        self.error.setStyleSheet(f"color:{theme.DANGER};")
        form.addRow("할 일", self.title)
        form.addRow("기한", self.due)
        form.addRow("메모", self.note)
        form.addRow(self.error)
        form.addRow(_buttons(self, "저장"))

    def accept(self) -> None:
        if not self.title.text().strip():
            self.error.setText("할 일을 적어 주세요.")
            return
        super().accept()

    def value(self) -> dict:
        return {"title": self.title.text().strip(), "due": self.due.value(), "note": self.note.text().strip()}


class SentDataDialog(QDialog):
    """다음 질문을 보낼 때 외부 AI 로 나가는 글을 그대로 보여 준다."""

    def __init__(self, bundle: PromptBundle, destination: str, is_mock: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 로 보내는 자료")
        self.resize(900, 700)
        lay = QVBoxLayout(self)
        if is_mock:
            head = QLabel("지금은 <b>모의 모드</b>라서 아래 글은 어디로도 보내지 않습니다. 실제 AI 를 연결하면 이 글이 그대로 전송됩니다.")
        else:
            head = QLabel(f"아래 글 전체가 <b>{html.escape(destination)}</b> 로 전송됩니다. "
                          "이 밖의 자료(다른 파일, 꺼 둔 기억 등)는 보내지 않습니다.")
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setWordWrap(True)
        lay.addWidget(head)
        items = " · ".join(f"{label} {detail}" for label, detail in bundle.disclosure.items)
        summary = QLabel(f"포함: {items}\n전체 {bundle.disclosure.total_chars:,}자")
        summary.setObjectName("sendLine")
        summary.setWordWrap(True)
        lay.addWidget(summary)
        local = QLabel("🔒 이 컴퓨터에만 저장: 대화 기록 · 기억 · 일정 · 할 일 · 작업 로그 · 브리핑/일지 (내일비서는 자체 서버가 없습니다)")
        local.setObjectName("muted")
        local.setWordWrap(True)
        lay.addWidget(local)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText("━━━ 비서 지침(시스템) ━━━\n" + bundle.system + "\n━━━ 자료와 질문 ━━━\n" + bundle.prompt)
        lay.addWidget(view, 1)
        close = QPushButton("닫기")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
