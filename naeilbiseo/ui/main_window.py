"""메인 창."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..assistant import Assistant
from ..dday import WEEKDAYS, dday_label, korean_date, parse_date, today_local
from ..editions import EDITIONS
from ..providers import ProviderStatus
from ..scheduler import JOB_LABELS, Scheduler
from . import theme
from .chat_page import ChatPage
from .pages import DocsPage, LogPage, MemoryPage, NotesPage, PlanPage
from .settings_dialog import SettingsDialog, choose_workspace
from .workers import StatusWorker, TickWorker

TAB_CHAT, TAB_DOCS, TAB_PLAN, TAB_MEMORY, TAB_NOTES, TAB_LOG = range(6)


def make_icon() -> QIcon:
    pix = QPixmap(128, 128)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(theme.PRIMARY))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(6, 6, 116, 116, 28, 28)
    painter.setPen(QColor("white"))
    font = QFont(theme.pick_font_family(), 54)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "내")
    painter.end()
    return QIcon(pix)


class MainWindow(QMainWindow):
    def __init__(self, assistant: Assistant, run_scheduler: bool = True, check_status: bool = True):
        super().__init__()
        self.assistant = assistant
        self.db = assistant.db
        self.scheduler = Scheduler(assistant)
        self._status: ProviderStatus | None = None
        self._status_worker: StatusWorker | None = None
        self._tick_worker: TickWorker | None = None
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(make_icon())
        self.resize(1320, 860)
        self.setMinimumSize(1040, 680)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        body.addWidget(self.tabs, 1)
        outer.addLayout(body, 1)

        self.chat = ChatPage(assistant)
        self.docs = DocsPage(assistant)
        self.plan = PlanPage(assistant)
        self.memory = MemoryPage(assistant)
        self.notes = NotesPage(assistant)
        self.log = LogPage(assistant)
        for page, title in ((self.chat, "💬 대화"), (self.docs, "📂 문서"), (self.plan, "🗓️ 일정·할 일"),
                            (self.memory, "🧠 기억"), (self.notes, "☀ 브리핑·일지"), (self.log, "📋 작업 로그")):
            self.tabs.addTab(page, title)
        self.tabs.currentChanged.connect(self._on_tab)

        self.chat.changed.connect(self.refresh_side)
        self.chat.open_documents.connect(lambda: self.tabs.setCurrentIndex(TAB_DOCS))
        self.chat.choose_workspace.connect(self.pick_workspace)
        self.chat.busy_changed.connect(self._on_busy)
        self.docs.choose_workspace.connect(self.pick_workspace)
        self.docs.changed.connect(self.chat.refresh)
        self.plan.changed.connect(self.refresh_side)
        self.memory.changed.connect(self.chat.refresh)
        self.notes.changed.connect(self.refresh_side)

        self._load_topics()
        self.refresh_side()
        self.statusBar().showMessage("자료는 이 컴퓨터에 저장됩니다. AI 로 보내는 자료는 대화 화면 아래에 항상 표시됩니다.")

        if check_status:
            self.check_provider()
        else:
            self._update_status_chip()
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._tick)
        if run_scheduler:
            self._timer.start()
            QTimer.singleShot(3_000, self._tick)

    # ── 머리 부분 ────────────────────────────────────────────────
    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(18, 10, 18, 10)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        sub = QLabel("내 컴퓨터에서 일하는 AI 업무·목회 비서")
        sub.setObjectName("appSub")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        lay.addLayout(title_box)
        lay.addSpacing(24)

        self.edition_group = QButtonGroup(self)
        self.edition_buttons: dict[str, QPushButton] = {}
        seg = QHBoxLayout()
        seg.setSpacing(0)
        for key, edition in EDITIONS.items():
            btn = QPushButton(f"{edition.icon} {edition.name}")
            btn.setObjectName("seg")
            btn.setCheckable(True)
            btn.setChecked(key == self.assistant.edition().key)
            btn.clicked.connect(lambda _=False, k=key: self.switch_edition(k))
            self.edition_group.addButton(btn)
            self.edition_buttons[key] = btn
            seg.addWidget(btn)
        lay.addLayout(seg)
        lay.addStretch(1)

        self.status_btn = QPushButton("AI 상태 확인 중…")
        self.status_btn.setObjectName("status")
        self.status_btn.setToolTip("누르면 AI 연결 설정이 열립니다")
        self.status_btn.clicked.connect(lambda: self.open_settings(2))
        lay.addWidget(self.status_btn)
        settings = QPushButton("⚙ 설정")
        settings.clicked.connect(lambda: self.open_settings(0))
        lay.addWidget(settings)
        return header

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(268)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(4)

        label = QLabel("주제")
        label.setObjectName("sectionTitle")
        lay.addWidget(label)
        self.topic_list = QListWidget()
        self.topic_list.currentRowChanged.connect(self._on_topic)
        self.topic_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.topic_list, 5)

        label = QLabel("다가오는 일정")
        label.setObjectName("sectionTitle")
        lay.addWidget(label)
        self.event_list = QListWidget()
        self.event_list.setObjectName("plain")
        self.event_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.event_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.event_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.event_list.itemClicked.connect(lambda _i: self.tabs.setCurrentIndex(TAB_PLAN))
        lay.addWidget(self.event_list, 3)

        label = QLabel("할 일")
        label.setObjectName("sectionTitle")
        lay.addWidget(label)
        self.todo_list = QListWidget()
        self.todo_list.setObjectName("plain")
        self.todo_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.todo_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.todo_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.todo_list.itemChanged.connect(self._side_todo_checked)
        lay.addWidget(self.todo_list, 3)
        return side

    # ── 주제·판 ──────────────────────────────────────────────────
    def _load_topics(self) -> None:
        edition = self.assistant.edition()
        saved = self.db.get_setting(f"topic.{edition.key}", edition.topics[0].key)
        self.topic_list.blockSignals(True)
        self.topic_list.clear()
        for topic in edition.topics:
            item = QListWidgetItem(f"{topic.icon}  {topic.name}")
            item.setData(Qt.ItemDataRole.UserRole, topic.key)
            self.topic_list.addItem(item)
        keys = [t.key for t in edition.topics]
        row = keys.index(saved) if saved in keys else 0
        self.topic_list.setCurrentRow(row)
        self.topic_list.blockSignals(False)
        self.chat.set_context(edition.key, keys[row])
        self._sync_conversation()

    def _on_topic(self, row: int) -> None:
        if row < 0:
            return
        if self.chat.is_busy():
            return
        edition = self.assistant.edition()
        key = self.topic_list.item(row).data(Qt.ItemDataRole.UserRole)
        self.db.set_setting(f"topic.{edition.key}", key)
        self.chat.set_context(edition.key, key)
        self._sync_conversation()
        self.tabs.setCurrentIndex(TAB_CHAT)

    def switch_edition(self, key: str) -> None:
        if self.chat.is_busy() or key == self.assistant.edition().key:
            self.edition_buttons[self.assistant.edition().key].setChecked(True)
            return
        self.assistant.set_edition(key)
        self._load_topics()
        self.refresh_side()
        self.statusBar().showMessage(f"{EDITIONS[key].name}(으)로 바꿨습니다. 일정·할 일·기억은 두 판이 함께 씁니다.", 6000)

    def _on_busy(self, busy: bool) -> None:
        self.topic_list.setEnabled(not busy)
        for btn in self.edition_buttons.values():
            btn.setEnabled(not busy)

    def _sync_conversation(self) -> None:
        self.docs.set_conversation(self.chat.conv_id)
        self.log.set_conversation(self.chat.conv_id)

    # ── 옆 칸(일정·할 일) ────────────────────────────────────────
    def refresh_side(self) -> None:
        today = today_local()
        self.event_list.clear()
        events = self.db.list_events(today.isoformat())[:6]
        for e in events:
            day = parse_date(e["date"])
            short = f"{day.month}/{day.day}({WEEKDAYS[day.weekday()]})" if day else e["date"]
            item = QListWidgetItem(f"{dday_label(e['date'], today)} · {short} {e['title']}")
            item.setToolTip(f"{korean_date(e['date'])} {e['time']} {e['title']} {e['note']}".strip())
            self.event_list.addItem(item)
        if not events:
            item = QListWidgetItem("적어 둔 일정이 없습니다")
            item.setForeground(QColor(theme.MUTED))
            self.event_list.addItem(item)

        self.todo_list.blockSignals(True)
        self.todo_list.clear()
        todos = self.db.list_todos(include_done=False)[:8]
        for t in todos:
            label = t["title"] + (f"  ({dday_label(t['due'], today)})" if t["due"] else "")
            item = QListWidgetItem(label)
            item.setToolTip(label)
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, t["id"])
            if t["due"] and t["due"] < today.isoformat():
                item.setForeground(QColor(theme.DANGER))
            self.todo_list.addItem(item)
        if not todos:
            item = QListWidgetItem("남은 할 일이 없습니다")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setForeground(QColor(theme.MUTED))
            self.todo_list.addItem(item)
        self.todo_list.blockSignals(False)
        self._sync_conversation()
        self._reload_current_tab()

    def _side_todo_checked(self, item: QListWidgetItem) -> None:
        todo_id = item.data(Qt.ItemDataRole.UserRole)
        if todo_id is not None and item.checkState() == Qt.CheckState.Checked:
            self.db.set_todo_done(todo_id, True)
            QTimer.singleShot(0, self.refresh_side)

    def _on_tab(self, _index: int) -> None:
        self._sync_conversation()
        self._reload_current_tab()

    def _reload_current_tab(self) -> None:
        index = self.tabs.currentIndex()
        if index == TAB_DOCS:
            self.docs.reload()
        elif index == TAB_PLAN:
            self.plan.reload()
        elif index == TAB_MEMORY:
            self.memory.reload()
        elif index == TAB_NOTES:
            self.notes.reload()
        elif index == TAB_LOG:
            self.log.reload()
        elif index == TAB_CHAT and not self.chat.is_busy():
            self.chat.refresh()

    # ── 설정·작업 폴더 ───────────────────────────────────────────
    def pick_workspace(self) -> None:
        if choose_workspace(self, self.assistant):
            self.chat.refresh()
            self._reload_current_tab()
            self.statusBar().showMessage(f"작업 폴더: {self.assistant.workspace()}", 8000)

    def open_settings(self, tab: int = 0) -> None:
        if self.chat.is_busy():
            self.statusBar().showMessage("답변을 받는 중에는 설정을 바꿀 수 없습니다.", 5000)
            return
        dialog = SettingsDialog(self.assistant, self, start_tab=tab)
        if dialog.exec():
            from PySide6.QtWidgets import QApplication
            theme.apply_theme(QApplication.instance(), int(self.db.get_setting("font_step", theme.DEFAULT_FONT_STEP)))
            self.check_provider()
        self.chat.refresh()
        self.refresh_side()

    # ── AI 상태 ──────────────────────────────────────────────────
    def check_provider(self) -> None:
        provider = self.assistant.provider()
        if provider.is_mock:
            self._status = provider.status()
            self._update_status_chip()
            return
        self.status_btn.setText(f"{provider.name} 확인 중…")
        worker = StatusWorker(provider, self)
        worker.done.connect(self._on_status)
        self._status_worker = worker
        worker.start()

    def _on_status(self, provider_id: str, status: ProviderStatus) -> None:
        if provider_id == self.assistant.provider_id():
            self._status = status
            self._update_status_chip()

    def _update_status_chip(self) -> None:
        provider = self.assistant.provider()
        if provider.is_mock:
            name, text = "statusMock", "🧪 모의 모드 · 실제 AI 아님"
        elif self._status and self._status.usable and self._status.logged_in is not False:
            name, text = "status", f"🤖 {provider.name} · {self._status.summary}"
        elif self._status:
            name, text = "statusBad", f"⚠ {provider.name} · {self._status.summary}"
        else:
            name, text = "status", f"🤖 {provider.name}"
        self.status_btn.setObjectName(name)
        self.status_btn.setText(text)
        self.status_btn.style().unpolish(self.status_btn)
        self.status_btn.style().polish(self.status_btn)

    # ── 자동 작업 ────────────────────────────────────────────────
    def _tick(self) -> None:
        if self._tick_worker is not None:
            return
        if not self.scheduler.due():
            return
        self._tick_worker = TickWorker(self.scheduler, self)
        self._tick_worker.done.connect(self._on_tick)
        self._tick_worker.start()

    def _on_tick(self, outcomes: list) -> None:
        worker, self._tick_worker = self._tick_worker, None
        if worker:
            worker.wait(2000)
            worker.deleteLater()
        done = [JOB_LABELS[o.job_key] for o in outcomes if o.status == "done"]
        if done:
            self.statusBar().showMessage("자동 작업 완료: " + ", ".join(done) + " — 「브리핑·일지」 탭에서 볼 수 있습니다.", 15000)
            if self.tabs.currentIndex() == TAB_NOTES:
                self.notes.reload()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        if self.chat.worker:
            self.chat.worker.cancel()
            self.chat.worker.wait(8000)
        for worker in (self._status_worker, self._tick_worker, self.notes.worker):
            if worker is not None and worker.isRunning():
                worker.wait(8000)
        super().closeEvent(event)
