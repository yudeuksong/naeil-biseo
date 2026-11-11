"""문서 · 일정/할 일 · 기억 · 브리핑/일지 · 작업 로그 화면."""
from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from .. import config
from ..assistant import Assistant
from ..dday import dday_label, korean_date, today_local
from ..scheduler import JOB_LABELS
from ..workspace import DocumentError, human_size, read_document
from . import render, theme
from .dialogs import EventDialog, TextDialog, TodoDialog
from .workers import JobWorker


def make_table(headers: list[str], stretch_col: int) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
    return table


def cell(text: str, data=None, color: str | None = None, bold: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    if color:
        item.setForeground(QColor(color))
    if bold:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
    return item


def selected_id(table: QTableWidget):
    row = table.currentRow()
    if row < 0:
        return None
    for col in range(table.columnCount()):
        item = table.item(row, col)
        if item is not None and item.data(Qt.ItemDataRole.UserRole) is not None:
            return item.data(Qt.ItemDataRole.UserRole)
    return None


def dday_color(label: str) -> str | None:
    if label == "D-DAY" or label.startswith("D+"):
        return theme.DANGER
    if label.startswith("D-") and label[2:].isdigit() and int(label[2:]) <= 3:
        return theme.AMBER
    return theme.PRIMARY_DARK


# ─────────────────────────────────────────────────────────────────────
class DocsPage(QWidget):
    """작업 폴더의 문서 목록과 미리 보기. 여기서 대화에 첨부한다."""
    choose_workspace = Signal()
    changed = Signal()

    def __init__(self, assistant: Assistant, parent=None):
        super().__init__(parent)
        self.assistant = assistant
        self.conv_id: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)

        top = QHBoxLayout()
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        top.addWidget(self.path_label, 1)
        pick = QPushButton("📁 작업 폴더 고르기")
        pick.setObjectName("primary")
        pick.clicked.connect(self.choose_workspace.emit)
        reload_btn = QPushButton("다시 읽기")
        reload_btn.clicked.connect(self.reload)
        top.addWidget(pick)
        top.addWidget(reload_btn)
        lay.addLayout(top)

        note = QLabel("내일비서는 이 폴더 안의 글 문서(.txt .md .csv 등)만 읽습니다. 폴더 밖 경로, 바로 가기(링크)를 거친 경로, "
                      "비밀번호·열쇠·.env 같은 민감 파일은 코드로 막혀 있어 읽거나 보내지 않습니다.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        split = QSplitter()
        self.table = make_table(["문서", "상태", "크기"], 0)
        self.table.itemSelectionChanged.connect(self._preview)
        split.addWidget(self.table)
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(8, 0, 0, 0)
        self.info = QLabel("문서를 고르면 내용이 보입니다.")
        self.info.setWordWrap(True)
        rlay.addWidget(self.info)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        rlay.addWidget(self.preview, 1)
        self.attach_btn = QPushButton("이 대화에 첨부")
        self.attach_btn.setObjectName("primary")
        self.attach_btn.clicked.connect(self._toggle_attach)
        self.target_label = QLabel("")
        self.target_label.setObjectName("muted")
        self.target_label.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.target_label, 1)
        row.addWidget(self.attach_btn)
        rlay.addLayout(row)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([560, 480])
        lay.addWidget(split, 1)

    def set_conversation(self, conv_id: int | None) -> None:
        self.conv_id = conv_id
        self._update_attach_button()

    def _attached(self) -> list[str]:
        conv = self.assistant.db.get_conversation(self.conv_id) if self.conv_id else None
        return conv["attachments"] if conv else []

    def reload(self) -> None:
        ws = self.assistant.workspace()
        self.path_label.setText(f"📁 작업 폴더: {ws}" if ws else "📁 작업 폴더가 아직 정해지지 않았습니다.")
        entries, truncated = self.assistant.documents()
        attached = set(self._attached())
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            when = datetime.fromtimestamp(e.mtime).strftime("%Y-%m-%d %H:%M")
            if e.sensitive:
                state, color = "🔒 민감 — 읽지 않음", theme.DANGER
            elif not e.readable:
                state, color = ("목록만 표시" if "글 문서가 아님" in e.reason else e.reason), theme.MUTED
            elif e.rel_path in attached:
                state, color = "📎 첨부됨", theme.PRIMARY_DARK
            else:
                state, color = "읽을 수 있음", theme.INK
            name = cell(e.rel_path, data=e.rel_path, color=theme.MUTED if not e.readable else None)
            name.setToolTip(f"{e.rel_path}\n고친 날: {when}")
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, cell(state, color=color))
            self.table.setItem(row, 2, cell(human_size(e.size)))
        if truncated:
            self.path_label.setText(self.path_label.text() + f"  (파일이 많아 처음 {config.MAX_LIST_ENTRIES}개만 표시)")
        self._preview()

    def _current(self) -> str | None:
        return selected_id(self.table)

    def _preview(self) -> None:
        rel = self._current()
        self.preview.clear()
        if not rel:
            self.info.setText("문서를 고르면 내용이 보입니다.")
            self._update_attach_button()
            return
        guard = self.assistant.guard()
        try:
            doc = read_document(guard, rel)
        except DocumentError as exc:
            self.info.setText(f"⛔ {rel}\n{exc.message}")
            self._update_attach_button(readable=False)
            return
        self.info.setText(f"📄 {doc.rel_path} · {human_size(doc.size)} · {doc.encoding}")
        self.preview.setPlainText(doc.text)
        self._update_attach_button(readable=True)

    def _update_attach_button(self, readable: bool | None = None) -> None:
        rel = self._current()
        conv = self.assistant.db.get_conversation(self.conv_id) if self.conv_id else None
        self.target_label.setText(f"첨부 대상 대화: {conv['title']}" if conv else "")
        if readable is None:
            readable = False
        attached = rel in self._attached() if rel else False
        self.attach_btn.setEnabled(bool(rel and conv and (readable or attached)))
        self.attach_btn.setText("첨부 빼기" if attached else "이 대화에 첨부")

    def _toggle_attach(self) -> None:
        rel = self._current()
        if not rel or not self.conv_id:
            return
        try:
            if rel in self._attached():
                self.assistant.detach(self.conv_id, rel)
            else:
                self.assistant.attach(self.conv_id, rel)
        except DocumentError as exc:
            QMessageBox.warning(self, "첨부할 수 없습니다", exc.message)
        row = self.table.currentRow()
        self.reload()
        self.table.selectRow(row)
        self.changed.emit()


# ─────────────────────────────────────────────────────────────────────
class PlanPage(QWidget):
    """일정(D-day)과 할 일."""
    changed = Signal()

    def __init__(self, assistant: Assistant, parent=None):
        super().__init__(parent)
        self.db = assistant.db
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)

        ev_box = QGroupBox("🗓️ 일정")
        ev = QVBoxLayout(ev_box)
        self.events = make_table(["D-day", "날짜", "시각", "제목", "종류"], 3)
        self.events.doubleClicked.connect(lambda _i: self.edit_event())
        ev.addWidget(self.events, 1)
        row = QHBoxLayout()
        self.past_check = QCheckBox("지난 일정도 보기")
        self.past_check.toggled.connect(self.reload)
        row.addWidget(self.past_check)
        row.addStretch(1)
        for text, fn, name in (("＋ 일정 추가", self.add_event, "primary"), ("고치기", self.edit_event, ""),
                               ("지우기", self.delete_event, "")):
            b = QPushButton(text)
            b.setObjectName(name)
            b.clicked.connect(fn)
            row.addWidget(b)
        ev.addLayout(row)
        lay.addWidget(ev_box, 1)

        td_box = QGroupBox("☑️ 할 일")
        td = QVBoxLayout(td_box)
        self.todos = make_table(["", "할 일", "기한", "D-day"], 1)
        self.todos.itemChanged.connect(self._todo_checked)
        self.todos.doubleClicked.connect(lambda _i: self.edit_todo())
        td.addWidget(self.todos, 1)
        row = QHBoxLayout()
        self.done_check = QCheckBox("끝낸 일도 보기")
        self.done_check.toggled.connect(self.reload)
        row.addWidget(self.done_check)
        row.addStretch(1)
        for text, fn, name in (("＋ 할 일 추가", self.add_todo, "primary"), ("고치기", self.edit_todo, ""),
                               ("지우기", self.delete_todo, "")):
            b = QPushButton(text)
            b.setObjectName(name)
            b.clicked.connect(fn)
            row.addWidget(b)
        td.addLayout(row)
        lay.addWidget(td_box, 1)

    def reload(self) -> None:
        today = today_local()
        events = self.db.list_events(None if self.past_check.isChecked() else today.isoformat())
        self.events.setRowCount(len(events))
        for r, e in enumerate(events):
            label = dday_label(e["date"], today)
            self.events.setItem(r, 0, cell(label, data=e["id"], color=dday_color(label), bold=True))
            self.events.setItem(r, 1, cell(korean_date(e["date"])))
            self.events.setItem(r, 2, cell(e["time"]))
            self.events.setItem(r, 3, cell(e["title"] + (f"  — {e['note']}" if e["note"] else "")))
            self.events.setItem(r, 4, cell(e["kind"]))
        todos = self.db.list_todos(include_done=self.done_check.isChecked())
        self.todos.blockSignals(True)
        self.todos.setRowCount(len(todos))
        for r, t in enumerate(todos):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Checked if t["done"] else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, t["id"])
            self.todos.setItem(r, 0, check)
            color = theme.MUTED if t["done"] else None
            self.todos.setItem(r, 1, cell(t["title"] + (f"  — {t['note']}" if t["note"] else ""), color=color))
            self.todos.setItem(r, 2, cell(korean_date(t["due"]) if t["due"] else ""))
            label = "" if t["done"] else dday_label(t["due"], today)
            self.todos.setItem(r, 3, cell(label, color=dday_color(label) if label else None, bold=True))
        self.todos.blockSignals(False)

    def _todo_checked(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        self.db.set_todo_done(item.data(Qt.ItemDataRole.UserRole), item.checkState() == Qt.CheckState.Checked)
        self.reload()
        self.changed.emit()

    def add_event(self) -> None:
        dialog = EventDialog(parent=self)
        if dialog.exec():
            self.db.add_event(**dialog.value())
            self._after()

    def edit_event(self) -> None:
        event_id = selected_id(self.events)
        current = next((e for e in self.db.list_events() if e["id"] == event_id), None)
        if not current:
            return
        dialog = EventDialog(current, self)
        if dialog.exec():
            self.db.update_event(event_id, **dialog.value())
            self._after()

    def delete_event(self) -> None:
        event_id = selected_id(self.events)
        if event_id is not None and self._confirm("이 일정을 지울까요?"):
            self.db.delete_event(event_id)
            self._after()

    def add_todo(self) -> None:
        dialog = TodoDialog(parent=self)
        if dialog.exec():
            self.db.add_todo(**dialog.value())
            self._after()

    def edit_todo(self) -> None:
        todo_id = selected_id(self.todos)
        current = next((t for t in self.db.list_todos() if t["id"] == todo_id), None)
        if not current:
            return
        dialog = TodoDialog(current, self)
        if dialog.exec():
            self.db.update_todo(todo_id, **dialog.value())
            self._after()

    def delete_todo(self) -> None:
        todo_id = selected_id(self.todos)
        if todo_id is not None and self._confirm("이 할 일을 지울까요?"):
            self.db.delete_todo(todo_id)
            self._after()

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "확인", text) == QMessageBox.StandardButton.Yes

    def _after(self) -> None:
        self.reload()
        self.changed.emit()


# ─────────────────────────────────────────────────────────────────────
class MemoryPage(QWidget):
    """기억: 사용자가 보고, 고치고, 지우고, AI 로 보낼지 끌 수 있다."""
    changed = Signal()

    def __init__(self, assistant: Assistant, parent=None):
        super().__init__(parent)
        self.db = assistant.db
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        note = QLabel("기억은 다음 대화에서도 챙겨야 할 결정·약속·선호입니다. 이 컴퓨터에만 저장되며, 체크된 기억만 "
                      "대화할 때 AI 로 보냅니다. AI 가 기억을 남기자고 제안해도 승인하신 것만 여기에 들어옵니다.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.table = make_table(["AI 로 보내기", "기억", "남긴 곳", "날짜"], 1)
        self.table.itemChanged.connect(self._toggled)
        self.table.doubleClicked.connect(lambda _i: self.edit())
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        for text, fn, name in (("＋ 기억 추가", self.add, "primary"), ("고치기", self.edit, ""), ("지우기", self.delete, "")):
            b = QPushButton(text)
            b.setObjectName(name)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)

    def reload(self) -> None:
        items = self.db.list_memories()
        self.table.blockSignals(True)
        self.table.setRowCount(len(items))
        for r, m in enumerate(items):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Checked if m["enabled"] else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, m["id"])
            self.table.setItem(r, 0, check)
            self.table.setItem(r, 1, cell(m["text"].replace("\n", " "), color=None if m["enabled"] else theme.MUTED))
            self.table.setItem(r, 2, cell("직접 적음" if m["source"] == "user" else "AI 제안을 승인"))
            self.table.setItem(r, 3, cell(m["updated_at"][:10]))
        self.table.blockSignals(False)

    def _toggled(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self.db.update_memory(item.data(Qt.ItemDataRole.UserRole),
                                  enabled=item.checkState() == Qt.CheckState.Checked)
            self.reload()
            self.changed.emit()

    def add(self) -> None:
        dialog = TextDialog("기억 추가", "기억해 둘 내용", parent=self)
        if dialog.exec() and dialog.value():
            self.db.add_memory(dialog.value())
            self.reload()
            self.changed.emit()

    def edit(self) -> None:
        mem_id = selected_id(self.table)
        current = next((m for m in self.db.list_memories() if m["id"] == mem_id), None)
        if not current:
            return
        dialog = TextDialog("기억 고치기", "기억해 둘 내용", current["text"], parent=self)
        if dialog.exec() and dialog.value():
            self.db.update_memory(mem_id, text=dialog.value())
            self.reload()
            self.changed.emit()

    def delete(self) -> None:
        mem_id = selected_id(self.table)
        if mem_id is not None and QMessageBox.question(self, "확인", "이 기억을 지울까요?") == \
                QMessageBox.StandardButton.Yes:
            self.db.delete_memory(mem_id)
            self.reload()
            self.changed.emit()


# ─────────────────────────────────────────────────────────────────────
class NotesPage(QWidget):
    """아침 브리핑 · 저녁 일지."""
    changed = Signal()

    def __init__(self, assistant: Assistant, parent=None):
        super().__init__(parent)
        self.assistant = assistant
        self.db = assistant.db
        self.worker: JobWorker | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.ai_check = QCheckBox("AI 조언 포함(브리핑·오늘 대화 발췌를 AI 로 보냅니다)")
        row.addWidget(self.ai_check, 1)
        self.brief_btn = QPushButton("☀ 지금 브리핑 만들기")
        self.brief_btn.setObjectName("primary")
        self.brief_btn.clicked.connect(lambda: self.run_now("briefing"))
        self.journal_btn = QPushButton("📓 지금 일지 만들기")
        self.journal_btn.clicked.connect(lambda: self.run_now("journal"))
        self.delete_btn = QPushButton("지우기")
        self.delete_btn.clicked.connect(self.delete)
        for b in (self.brief_btn, self.journal_btn, self.delete_btn):
            row.addWidget(b)
        lay.addLayout(row)
        split = QSplitter()
        self.list = QListWidget()
        self.list.setObjectName("plain")
        self.list.currentItemChanged.connect(lambda *_: self._show())
        split.addWidget(self.list)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        split.addWidget(self.view)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        lay.addWidget(split, 1)

    def reload(self, select_first: bool = True) -> None:
        jobs = self.assistant.jobs()
        parts = []
        for key, label in JOB_LABELS.items():
            conf = jobs[key]
            state = f"매일 {conf['time']}" if conf["enabled"] else "꺼짐"
            ai = "AI 조언 포함" if conf["use_ai"] else "AI 미사용(규칙 요약)"
            parts.append(f"{label}: {state} · {ai}")
        self.status.setText("자동 작업 — " + "  |  ".join(parts) +
                            "\n내일비서가 켜져 있을 때만 돌고, 하루에 한 번만 만듭니다. 시각과 켜기·끄기는 설정 → 자동 작업에서 바꿉니다.")
        self.list.clear()
        for n in self.db.list_notes():
            icon = "☀" if n["kind"] == "briefing" else "📓"
            tag = " · 모의" if n["is_mock"] else (" · AI" if n["used_ai"] else "")
            item = QListWidgetItem(f"{icon} {korean_date(n['date'])} {JOB_LABELS[n['kind']]}{tag}")
            item.setData(Qt.ItemDataRole.UserRole, n)
            self.list.addItem(item)
        if self.list.count() and select_first:
            self.list.setCurrentRow(0)
        elif not self.list.count():
            self.view.setHtml(render.page('<p style="color:%s;">아직 브리핑이나 일지가 없습니다. '
                                          "위 단추로 지금 만들어 볼 수 있습니다.</p>" % theme.MUTED))

    def _show(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        note = item.data(Qt.ItemDataRole.UserRole)
        self.view.setHtml(render.page(render.md_to_html(note["content"])))

    def run_now(self, job_key: str) -> None:
        if self.worker:
            return
        self.worker = JobWorker(self.assistant, job_key, self.ai_check.isChecked(), self)
        self.worker.done.connect(self._done)
        self.brief_btn.setEnabled(False)
        self.journal_btn.setEnabled(False)
        self.worker.start()

    def _done(self, _job_key: str, ok: bool, message: str) -> None:
        worker, self.worker = self.worker, None
        if worker:
            worker.wait(2000)
            worker.deleteLater()
        self.brief_btn.setEnabled(True)
        self.journal_btn.setEnabled(True)
        if not ok:
            QMessageBox.warning(self, "만들지 못했습니다", message)
        self.reload()
        self.changed.emit()

    def delete(self) -> None:
        item = self.list.currentItem()
        if item and QMessageBox.question(self, "확인", "이 기록을 지울까요?") == QMessageBox.StandardButton.Yes:
            self.db.delete_note(item.data(Qt.ItemDataRole.UserRole)["id"])
            self.reload()


# ─────────────────────────────────────────────────────────────────────
LOG_KINDS = {
    "": "전체", "doc_read": "문서 읽음", "ai_answer": "AI 답변", "ai_error": "AI 오류·멈춤", "proposal": "제안 받음",
    "file_created": "파일 만듦", "file_updated": "파일 고침", "record": "기억·일정·할 일", "rejected": "거절함",
    "blocked": "차단됨", "read_approved": "읽기 허락", "cli_tool": "CLI 도구 사용", "job": "자동 작업",
    "workspace": "작업 폴더",
}
LOG_COLORS = {"blocked": theme.DANGER, "ai_error": theme.DANGER, "cli_tool": theme.DANGER,
              "file_created": theme.PRIMARY_DARK, "file_updated": theme.PRIMARY_DARK, "doc_read": theme.AMBER}


class LogPage(QWidget):
    """작업 로그: 실제로 읽은 자료와 바뀐 파일을 그대로 보여 준다."""

    def __init__(self, assistant: Assistant, parent=None):
        super().__init__(parent)
        self.db = assistant.db
        self.conv_id: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        note = QLabel("내일비서가 실제로 한 일의 기록입니다. 어떤 문서를 읽어 어디로 보냈는지, 어떤 파일을 만들거나 고쳤는지, "
                      "무엇을 막았는지가 남습니다. AI 가 한 말이 아니라 앱이 직접 적는 기록입니다.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        row = QHBoxLayout()
        self.kind_box = QComboBox()
        for key, label in LOG_KINDS.items():
            self.kind_box.addItem(label, key)
        self.kind_box.currentIndexChanged.connect(self.reload)
        self.conv_check = QCheckBox("지금 대화만")
        self.conv_check.toggled.connect(self.reload)
        refresh = QPushButton("새로 고침")
        refresh.clicked.connect(self.reload)
        row.addWidget(QLabel("종류"))
        row.addWidget(self.kind_box)
        row.addWidget(self.conv_check)
        row.addStretch(1)
        row.addWidget(refresh)
        lay.addLayout(row)
        self.table = make_table(["시각", "종류", "내용"], 2)
        self.table.itemSelectionChanged.connect(self._detail)
        lay.addWidget(self.table, 3)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("줄을 고르면 자세한 기록이 보입니다.")
        self.detail.setMaximumHeight(150)
        lay.addWidget(self.detail, 1)

    def set_conversation(self, conv_id: int | None) -> None:
        self.conv_id = conv_id

    def reload(self) -> None:
        kind = self.kind_box.currentData() or None
        conv = self.conv_id if self.conv_check.isChecked() else None
        rows = self.db.list_log(limit=500, conversation_id=conv, kind=kind)
        self.table.setRowCount(len(rows))
        for r, entry in enumerate(rows):
            self.table.setItem(r, 0, cell(entry["ts"][:19].replace("T", " "), data=entry))
            self.table.setItem(r, 1, cell(LOG_KINDS.get(entry["kind"], entry["kind"]),
                                          color=LOG_COLORS.get(entry["kind"]), bold=True))
            self.table.setItem(r, 2, cell(entry["summary"]))
        self.detail.clear()

    def _detail(self) -> None:
        entry = selected_id(self.table)
        if entry:
            self.detail.setPlainText(f"{entry['ts']}\n{entry['summary']}\n\n"
                                     + json.dumps(entry["detail"], ensure_ascii=False, indent=2))
