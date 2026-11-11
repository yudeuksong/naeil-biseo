"""설정 창: 프로필 · 작업 폴더와 보내는 자료 · AI 연결 · 자동 작업 · 화면."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, QTime
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QRadioButton, QTabWidget, QTextBrowser, QTimeEdit, QVBoxLayout, QWidget)

from .. import config
from ..assistant import Assistant
from ..editions import EDITIONS
from ..providers import PROVIDER_ORDER, ProviderStatus, create_provider
from ..scheduler import JOB_LABELS
from . import theme
from .workers import StatusWorker

HONORIFICS = {"general": ["선생님", "사장님", "대표님", "님"], "pastor": ["목사님", "전도사님", "사모님", "선교사님"]}


def choose_workspace(parent: QWidget, assistant: Assistant) -> bool:
    """폴더 고르기 창을 띄워 작업 폴더를 정한다. 정했으면 True."""
    start = assistant.workspace() or ""
    folder = QFileDialog.getExistingDirectory(parent, "작업 폴더 고르기 — 일할 자료를 모아 둔 폴더", start)
    if not folder:
        return False
    try:
        assistant.set_workspace(folder)
    except ValueError as exc:
        QMessageBox.warning(parent, "이 폴더는 쓸 수 없습니다", str(exc))
        return False
    return True


class SettingsDialog(QDialog):
    def __init__(self, assistant: Assistant, parent=None, start_tab: int = 0):
        super().__init__(parent)
        self.assistant = assistant
        self.db = assistant.db
        self.setWindowTitle("설정")
        self.resize(900, 720)
        self._workers: list[StatusWorker] = []
        self._status: dict[str, ProviderStatus] = {}
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._profile_tab(), "👤 프로필")
        self.tabs.addTab(self._workspace_tab(), "📁 작업 폴더·보내는 자료")
        self.tabs.addTab(self._ai_tab(), "🤖 AI 연결")
        self.tabs.addTab(self._jobs_tab(), "⏰ 자동 작업")
        self.tabs.addTab(self._screen_tab(), "🔠 화면")
        self.tabs.setCurrentIndex(start_tab)
        row = QHBoxLayout()
        row.addStretch(1)
        save = QPushButton("저장")
        save.setObjectName("primary")
        save.clicked.connect(self.accept)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        row.addWidget(save)
        row.addWidget(cancel)
        lay.addLayout(row)

    # ── 프로필 ───────────────────────────────────────────────────
    def _profile_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        note = QLabel("프로필은 이 컴퓨터에 저장되고, 대화할 때 AI 가 호칭과 사정을 알도록 함께 보냅니다"
                      "(작업 폴더·보내는 자료 탭에서 끌 수 있습니다). 판마다 따로 적습니다.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.profile_fields: dict[str, dict[str, QWidget]] = {}
        for key, edition in EDITIONS.items():
            box = QGroupBox(f"{edition.icon} {edition.name} 프로필")
            form = QFormLayout(box)
            prof = self.assistant.profile(key)
            name = QLineEdit(prof.get("name", ""))
            name.setPlaceholderText("예: 홍길동")
            honorific = QComboBox()
            honorific.setEditable(True)
            honorific.addItems(HONORIFICS[key])
            honorific.setCurrentText(prof.get("honorific") or edition.default_honorific)
            org = QLineEdit(prof.get("org", ""))
            org.setPlaceholderText("예: ○○교회 담임" if key == "pastor" else "예: 동네 빵집 운영, 회사원, 학부모")
            about = QPlainTextEdit(prof.get("about", ""))
            about.setPlaceholderText("비서가 알아 두면 좋은 사정과 선호를 적어 주세요. 예: 답은 짧게, 표로 정리해 주면 좋음")
            about.setFixedHeight(76)
            form.addRow("이름", name)
            form.addRow("호칭", honorific)
            form.addRow("하는 일·소속", org)
            form.addRow("소개·선호", about)
            self.profile_fields[key] = {"name": name, "honorific": honorific, "org": org, "about": about}
            lay.addWidget(box)
        lay.addStretch(1)
        return page

    # ── 작업 폴더 ────────────────────────────────────────────────
    def _workspace_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        box = QGroupBox("작업 폴더")
        b = QVBoxLayout(box)
        self.ws_label = QLabel(self.assistant.workspace() or "(아직 정하지 않음)")
        self.ws_label.setWordWrap(True)
        self.ws_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        pick = QPushButton("📁 폴더 고르기")
        pick.setObjectName("primary")
        pick.clicked.connect(self._pick_workspace)
        row = QHBoxLayout()
        row.addWidget(self.ws_label, 1)
        row.addWidget(pick)
        b.addLayout(row)
        rules = QLabel(
            "앱이 코드로 지키는 것\n"
            "· 읽기·쓰기 모두 이 폴더 안에서만 (상위 폴더 이동, 절대 경로, 바로 가기·정션을 거친 경로는 거절)\n"
            "· 비밀번호·열쇠·.env·인증서 같은 민감 파일은 읽지도 보내지도 고치지도 않음\n"
            f"· 읽기 {config.MAX_READ_BYTES // 1000}KB, 쓰기 {config.MAX_WRITE_BYTES // 1000}KB 까지 · "
            "만들고 고치는 파일은 .txt .md .csv 만\n"
            "· 기존 파일을 고칠 때는 차이를 보여 드리고 승인받은 뒤, 원본을 「.내일비서_백업」에 보관하고 저장\n"
            "지키지 못하는 것\n"
            "· 민감 파일은 이름으로 가려냅니다. 평범한 이름의 문서 안에 적힌 비밀번호까지는 알아내지 못합니다.\n"
            "· 홈 폴더 전체나 드라이브 전체는 작업 폴더로 쓸 수 없습니다. 일할 자료만 모은 폴더를 골라 주세요.")
        rules.setObjectName("muted")
        rules.setWordWrap(True)
        b.addWidget(rules)
        lay.addWidget(box)

        send_box = QGroupBox("대화할 때 AI 로 보내는 자료")
        s = QVBoxLayout(send_box)
        opts = self.assistant.send_options()
        self.send_checks = {}
        for key, label in (("profile", "프로필(이름·호칭·하는 일·소개)"), ("memory", "기억(체크해 둔 것만)"),
                           ("schedule", "다가오는 일정과 아직 안 한 할 일"),
                           ("file_list", "작업 폴더의 문서 이름 목록(내용은 첨부한 문서만)")):
            check = QCheckBox(label)
            check.setChecked(bool(opts.get(key, True)))
            self.send_checks[key] = check
            s.addWidget(check)
        always = QLabel("항상 보내는 것: 적으신 질문, 이 대화의 이전 내용, 직접 첨부한 문서의 내용.\n"
                        "이 컴퓨터에만 두는 것: 대화 기록, 기억, 일정, 할 일, 작업 로그, 브리핑·일지 (내일비서는 자체 서버가 없습니다).\n"
                        "보낸 자료가 AI 회사에서 어떻게 다뤄지는지는 그 회사의 약관·개인정보 처리방침을 따릅니다.")
        always.setObjectName("muted")
        always.setWordWrap(True)
        s.addWidget(always)
        lay.addWidget(send_box)
        lay.addStretch(1)
        return page

    def _pick_workspace(self) -> None:
        if choose_workspace(self, self.assistant):
            self.ws_label.setText(self.assistant.workspace())

    # ── AI 연결 ──────────────────────────────────────────────────
    def _ai_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        note = QLabel("내일비서는 이 컴퓨터에 설치된 각 회사의 공식 프로그램(CLI)을 불러 씁니다. 설치와 로그인은 본인이 "
                      "공식 방법으로 직접 하고, 내일비서는 로그인 파일·토큰을 읽거나 복사하지 않습니다. "
                      "사용 한도·요금·약관은 각 회사 기준이며, 무료·무제한 사용을 보장하지 않습니다.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.provider_group = QButtonGroup(self)
        self.provider_radios: dict[str, QRadioButton] = {}
        self.provider_state: dict[str, QLabel] = {}
        current = self.assistant.provider_id()
        box = QGroupBox("쓸 AI 고르기")
        b = QVBoxLayout(box)
        for pid in PROVIDER_ORDER:
            provider = create_provider(pid)
            title = provider.name
            if provider.is_mock:
                title += " — 연습용, 실제 AI 아님(외부 전송 없음)"
            elif provider.experimental:
                title += " — 실험적(실제 CLI 로 검증되지 않음)"
            else:
                title += f" — {provider.vendor}"
            radio = QRadioButton(title)
            radio.setChecked(pid == current)
            radio.toggled.connect(lambda on, p=pid: on and self._show_provider(p))
            self.provider_group.addButton(radio)
            self.provider_radios[pid] = radio
            state = QLabel("확인 중…" if not provider.is_mock else "언제나 쓸 수 있음")
            state.setObjectName("muted")
            row = QHBoxLayout()
            row.addWidget(radio, 1)
            row.addWidget(state)
            b.addLayout(row)
            self.provider_state[pid] = state
        lay.addWidget(box)

        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)
        lay.addWidget(self.detail, 1)

        self.consent = QCheckBox("실험적 연결의 한계(앱이 폴더 밖 읽기를 막는다고 보장하지 못함)를 읽었고, 그래도 사용합니다")
        lay.addWidget(self.consent)

        form = QFormLayout()
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("비워 두면 CLI 의 기본 모델 (예: sonnet)")
        self.exe_edit = QLineEdit()
        self.exe_edit.setPlaceholderText("비워 두면 자동으로 찾습니다")
        self.timeout_box = QComboBox()
        for seconds, label in ((60, "1분"), (180, "3분"), (300, "5분 (기본)"), (600, "10분"), (1200, "20분")):
            self.timeout_box.addItem(label, seconds)
        saved = int(self.db.get_setting("timeout_sec", config.DEFAULT_TIMEOUT_SEC))
        nearest = min(range(self.timeout_box.count()), key=lambda i: abs(self.timeout_box.itemData(i) - saved))
        self.timeout_box.setCurrentIndex(nearest)
        self.timeout_box.setToolTip("이 시간 안에 답이 오지 않으면 멈춥니다.")
        form.addRow("모델(선택)", self.model_edit)
        form.addRow("실행 파일 위치(선택)", self.exe_edit)
        form.addRow("답변 제한 시간", self.timeout_box)
        lay.addLayout(form)

        row = QHBoxLayout()
        recheck = QPushButton("🔄 설치·로그인 상태 다시 확인")
        recheck.clicked.connect(self._check_all)
        copy_login = QPushButton("로그인 명령 복사")
        copy_login.clicked.connect(self._copy_login)
        row.addWidget(recheck)
        row.addWidget(copy_login)
        row.addStretch(1)
        lay.addLayout(row)

        self._shown = current
        self._load_provider_fields(current)
        self._show_provider(current)
        self._check_all()
        return page

    def _selected_provider(self) -> str:
        for pid, radio in self.provider_radios.items():
            if radio.isChecked():
                return pid
        return "mock"

    def _load_provider_fields(self, pid: str) -> None:
        self.model_edit.setText(self.db.get_setting(f"provider.model.{pid}", "") or "")
        self.exe_edit.setText(self.db.get_setting(f"provider.exe.{pid}", "") or "")
        self.consent.setChecked(bool(self.db.get_setting(f"provider.consent.{pid}", False)))

    def _store_provider_fields(self, pid: str) -> None:
        self.db.set_setting(f"provider.model.{pid}", self.model_edit.text().strip())
        self.db.set_setting(f"provider.exe.{pid}", self.exe_edit.text().strip())
        self.db.set_setting(f"provider.consent.{pid}", self.consent.isChecked())

    def _check_all(self) -> None:
        for pid in PROVIDER_ORDER:
            provider = create_provider(pid, self.db.get_setting(f"provider.exe.{pid}", "") or "")
            if provider.is_mock:
                self._status[pid] = provider.status()
                continue
            self.provider_state[pid].setText("확인 중…")
            worker = StatusWorker(provider, self)
            worker.done.connect(self._on_status)
            self._workers.append(worker)
            worker.start()

    def _on_status(self, pid: str, status: ProviderStatus) -> None:
        self._status[pid] = status
        text = status.summary + (f" · {status.version}" if status.version else "")
        self.provider_state[pid].setText(text)
        color = theme.PRIMARY_DARK if status.usable and status.logged_in else (
            theme.AMBER if status.installed else theme.MUTED)
        self.provider_state[pid].setStyleSheet(f"color:{color}; font-weight:700;")
        if pid == self._selected_provider():
            self._show_provider(pid, reload_fields=False)

    def _show_provider(self, pid: str, reload_fields: bool = True) -> None:
        if reload_fields and getattr(self, "_shown", pid) != pid:
            self._store_provider_fields(self._shown)
            self._load_provider_fields(pid)
        self._shown = pid
        provider = create_provider(pid)
        status = self._status.get(pid)
        e = html.escape
        parts = [f"<h3>{e(provider.name)}</h3>"]
        if provider.is_mock:
            parts.append("<p>연습용입니다. 미리 정해 둔 글로 답하며 <b>실제 AI 가 아닙니다.</b> 외부로 아무것도 보내지 않습니다. "
                         "모든 답에 「모의 응답」 표시가 붙습니다.</p>")
        else:
            parts.append(f"<p>자료를 받는 곳: <b>{e(provider.vendor)}</b></p>")
            if status:
                parts.append(f"<p><b>상태</b>: {e(status.summary)}"
                             + (f" · {e(status.version)}" if status.version else "") + f"<br>{e(status.detail)}</p>")
                if status.restrictions:
                    parts.append("<p><b>앱이 실제로 거는 제한</b></p><ul>"
                                 + "".join(f"<li>{e(r)}</li>" for r in status.restrictions) + "</ul>")
                if status.warnings:
                    parts.append(f'<p style="color:{theme.DANGER};"><b>앱이 보장하지 못하는 것</b></p><ul>'
                                 + "".join(f"<li>{e(w)}</li>" for w in status.warnings) + "</ul>")
            parts.append(f"<p><b>설치</b>: {e(provider.install_hint)}<br><b>로그인</b>: {e(provider.login_hint)}"
                         f"<br><b>공식 문서</b>: {e(provider.docs_url)}</p>")
        parts.append(f'<p style="color:{theme.MUTED};">{e(provider.terms_note)}</p>')
        self.detail.setHtml("".join(parts))
        self.consent.setVisible(provider.experimental)
        for w in (self.model_edit, self.exe_edit):
            w.setEnabled(not provider.is_mock)

    def _copy_login(self) -> None:
        provider = create_provider(self._selected_provider())
        command = {"claude": "claude auth login", "codex": "codex login", "gemini": "gemini"}.get(provider.id, "")
        if command:
            QGuiApplication.clipboard().setText(command)
            QMessageBox.information(self, "복사했습니다", f"터미널(명령 프롬프트)에 붙여 넣어 실행하세요:\n\n{command}\n\n"
                                                    "로그인은 그 프로그램의 공식 화면에서 본인 계정으로 하시면 됩니다.")

    # ── 자동 작업 ────────────────────────────────────────────────
    def _jobs_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        note = QLabel("내일비서가 켜져 있을 때만 돕니다(꺼져 있으면 돌지 않습니다). 정한 시각이 지난 뒤에 켜면 그날 몫을 한 번 "
                      "만들고, 같은 날 다시 켜도 중복해서 만들지 않습니다. 시각은 이 컴퓨터의 현지 시간 기준입니다.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        jobs = self.assistant.jobs()
        self.job_widgets: dict[str, tuple[QCheckBox, QTimeEdit, QCheckBox]] = {}
        hints = {"briefing": "오늘 일정 · 다가오는 일정(D-day) · 할 일을 정리합니다.",
                 "journal": "오늘 나눈 대화 · 만든 파일 · 끝낸 할 일을 정리합니다."}
        for key, label in JOB_LABELS.items():
            conf = jobs[key]
            box = QGroupBox(label)
            b = QVBoxLayout(box)
            b.addWidget(QLabel(hints[key]))
            enabled = QCheckBox("매일 자동으로 만들기")
            enabled.setChecked(bool(conf["enabled"]))
            time = QTimeEdit()
            time.setDisplayFormat("HH:mm")
            hh, mm = (conf["time"] or "07:00").split(":")
            time.setTime(QTime(int(hh), int(mm)))
            use_ai = QCheckBox("AI 조언 포함 — 켜면 그 내용을 AI 로 보내고 구독 사용량을 씁니다(끄면 규칙 요약만, 외부 전송 없음)")
            use_ai.setChecked(bool(conf["use_ai"]))
            row = QHBoxLayout()
            row.addWidget(enabled)
            row.addWidget(QLabel("시각"))
            row.addWidget(time)
            row.addStretch(1)
            b.addLayout(row)
            b.addWidget(use_ai)
            self.job_widgets[key] = (enabled, time, use_ai)
            lay.addWidget(box)
        lay.addStretch(1)
        return page

    # ── 화면 ─────────────────────────────────────────────────────
    def _screen_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.font_box = QComboBox()
        for i, name in enumerate(theme.FONT_STEP_NAMES):
            self.font_box.addItem(f"{name} ({theme.FONT_STEPS[i]}pt)", i)
        self.font_box.setCurrentIndex(int(self.db.get_setting("font_step", theme.DEFAULT_FONT_STEP)))
        form.addRow("글자 크기", self.font_box)
        data = QLabel(str(config.app_data_dir()))
        data.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        data.setWordWrap(True)
        form.addRow("자료 저장 위치", data)
        info = QLabel("대화·기억·일정·할 일·작업 로그가 위 폴더의 파일 하나(naeilbiseo.sqlite3)에 저장됩니다. "
                      "이 파일을 복사해 두면 백업이 됩니다.")
        info.setObjectName("muted")
        info.setWordWrap(True)
        form.addRow("", info)
        return page

    # ── 저장 ─────────────────────────────────────────────────────
    def accept(self) -> None:
        pid = self._selected_provider()
        self._store_provider_fields(self._shown)
        provider = create_provider(pid)
        if provider.experimental and not self.db.get_setting(f"provider.consent.{pid}", False):
            QMessageBox.warning(self, "확인이 필요합니다",
                                f"{provider.name} 는 실험적 연결입니다. 한계를 읽고 동의 칸에 체크해야 쓸 수 있습니다.")
            self.tabs.setCurrentIndex(2)
            return
        for key, fields in self.profile_fields.items():
            self.assistant.set_profile(key, {
                "name": fields["name"].text(), "honorific": fields["honorific"].currentText(),
                "org": fields["org"].text(), "about": fields["about"].toPlainText()})
        self.db.set_setting("send", {k: c.isChecked() for k, c in self.send_checks.items()})
        self.db.set_setting("provider", pid)
        self.db.set_setting("timeout_sec", self.timeout_box.currentData())
        self.db.set_setting("jobs", {key: {"enabled": en.isChecked(), "time": tm.time().toString("HH:mm"),
                                           "use_ai": ai.isChecked()}
                                     for key, (en, tm, ai) in self.job_widgets.items()})
        self.db.set_setting("font_step", self.font_box.currentData())
        super().accept()

    def done(self, code: int) -> None:
        for worker in self._workers:
            worker.wait(30000)
        super().done(code)
