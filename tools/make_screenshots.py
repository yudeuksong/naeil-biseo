"""예시 자료로 화면을 띄워 스크린샷을 만든다(개발용).

    QT_QPA_PLATFORM=offscreen python tools/make_screenshots.py <출력 폴더> [--real-claude]

--real-claude 를 주면 설치·로그인된 실제 Claude Code 로 한 번 질문한다(구독 사용량이 조금 든다).
주지 않으면 모의 모드로만 찍는다. 화면 속 이름·교회·일정은 모두 지어낸 예시다.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

out_dir = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "screenshots").resolve()
use_real = "--real-claude" in sys.argv
work = out_dir / "_작업"
shutil.rmtree(work, ignore_errors=True)
(work / "data").mkdir(parents=True)
os.environ["NAEILBISEO_DATA_DIR"] = str(work / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from naeilbiseo import config  # noqa: E402
from naeilbiseo.assistant import Assistant  # noqa: E402
from naeilbiseo.db import Database  # noqa: E402
from naeilbiseo.dday import today_local  # noqa: E402
from naeilbiseo.fileops import plan_change  # noqa: E402
from naeilbiseo.scheduler import run_job  # noqa: E402
from naeilbiseo.ui import theme  # noqa: E402
from naeilbiseo.ui.dialogs import ApprovalDialog, SentDataDialog  # noqa: E402
from naeilbiseo.ui.main_window import TAB_CHAT, TAB_DOCS, TAB_LOG, TAB_MEMORY, TAB_NOTES, TAB_PLAN, MainWindow  # noqa: E402
from naeilbiseo.ui.settings_dialog import SettingsDialog  # noqa: E402


def seed_workspace(root: Path) -> None:
    (root / "설교").mkdir(parents=True)
    (root / "주보").mkdir()
    (root / "설교" / "시편23편_묵상메모.md").write_text(
        "# 시편 23편 묵상 메모 (예시)\n\n"
        "- 1절: 여호와는 나의 목자시니 — '나의'라는 말에 오래 머물렀다.\n"
        "- 4절: 골짜기를 '지나간다'. 머무는 곳이 아니라 지나가는 길.\n"
        "- 이번 주 교우들: 병상에 있는 분, 일자리를 찾는 청년이 떠올랐다.\n"
        "- 전하고 싶은 것: 형편이 아니라 목자를 바라보자.\n", encoding="utf-8")
    (root / "주보" / "11월2주_광고초안.txt").write_text(
        "1. 추수감사주일 예배 안내\n2. 제직회: 주일 오후\n3. 새가족 환영 모임\n", encoding="utf-8")
    (root / "교회일정.csv").write_text("날짜,행사,담당\n(예시),추수감사주일,예배부\n(예시),제직회,서기\n",
                                    encoding="utf-8-sig")
    (root / ".env").write_text("EXAMPLE_KEY=이것은_예시입니다\n", encoding="utf-8")
    (root / "계정_비밀번호.txt").write_text("예시 파일 — 민감 파일 차단을 보여 주기 위한 것\n", encoding="utf-8")


def pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(condition, timeout_ms: int) -> bool:
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(lambda: condition() and loop.quit())
    timer.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    return bool(condition())


def shot(widget, name: str) -> None:
    QApplication.processEvents()
    pump(120)
    path = out_dir / name
    widget.grab().save(str(path))
    print("saved", path.name)


def main() -> int:
    app = QApplication(sys.argv[:1])
    theme.apply_theme(app, 1)
    ws = work / "예시_작업폴더"
    seed_workspace(ws)

    db = Database(config.db_path())
    assistant = Assistant(db)
    assistant.set_workspace(str(ws))
    assistant.set_edition("pastor")
    assistant.set_profile("pastor", {"name": "김예시", "honorific": "목사님", "org": "예시교회 담임(가상)",
                                     "about": "답은 짧게. 설교는 30분 안쪽으로 준비합니다."})
    assistant.set_profile("general", {"name": "김예시", "honorific": "선생님", "org": "동네 책방 운영(가상)", "about": ""})
    today = today_local()
    sunday = today + timedelta(days=(6 - today.weekday()) % 7 or 7)
    db.add_event("주일 설교 — 시편 23편", sunday.isoformat(), "11:00", "설교")
    db.add_event("이 집사님 댁 심방(예시)", (today + timedelta(days=2)).isoformat(), "15:00", "심방")
    db.add_event("제직회", (sunday + timedelta(days=7)).isoformat(), "13:30", "회의")
    db.add_todo("주보 광고 확정", (today + timedelta(days=1)).isoformat())
    db.add_todo("추수감사주일 초청장 문구", (today + timedelta(days=5)).isoformat())
    db.add_todo("지난주 심방 기록 정리", (today - timedelta(days=1)).isoformat())
    db.add_memory("설교는 30분 안쪽으로 준비한다")
    db.add_memory("주보 마감은 매주 목요일 저녁")
    db.set_setting("topic.pastor", "sermon")
    db.set_setting("provider", "claude" if use_real else "mock")

    window = MainWindow(assistant, run_scheduler=False, check_status=use_real)
    window.show()
    pump(300)
    chat = window.chat
    if use_real:
        ok = wait_until(lambda: window._status is not None, 60_000)
        print("status:", window._status.summary if ok else "확인 실패")
        if not (ok and window._status.usable and window._status.logged_in):
            print("실제 Claude Code 를 쓸 수 없어 중단합니다.")
            return 2

    # 1) 설교 준비 대화 — 문서 첨부 후 질문
    assistant.attach(chat.conv_id, "설교/시편23편_묵상메모.md")
    chat.refresh()
    chat.input.setPlainText("첨부한 묵상 메모를 바탕으로 시편 23편 설교 개요를 잡아 주세요. "
                            "개요는 '설교/시편23편_개요.md' 로 저장을 제안해 주시고, 설교 원고 초안 쓰기를 할 일에 넣어 주세요.")
    shot(window, "01_대화_질문_보내기_전.png")
    chat.send()
    pump(2500 if use_real else 150)
    shot(window, "02_대화_답변_쓰는_중.png")
    if not wait_until(lambda: not chat.is_busy(), 240_000):
        print("답변이 제한 시간 안에 오지 않았습니다.")
        return 3
    pump(200)
    shot(window, "03_대화_답변과_승인대기.png")
    bar = chat.view.verticalScrollBar()
    bar.setValue(0)
    shot(window, "03b_대화_답변_윗부분.png")

    proposals = db.list_proposals(chat.conv_id)
    print("proposals:", [p["type"] for p in proposals])
    file_props = [p for p in proposals if p["type"] == "write_file"]
    if file_props:
        plan = assistant.plan_for(file_props[0])
        dialog = ApprovalDialog(plan, assistant.workspace(), window)
        dialog.show()
        shot(dialog, "04_파일_승인창_새파일.png")
        dialog.close()
        print("approve:", assistant.approve(file_props[0]["id"], plan).message)
    for p in proposals:
        if p["type"] != "write_file":
            print("approve:", assistant.approve(p["id"]).message)
    chat.refresh()
    window.refresh_side()

    # 보내는 자료 창
    prepared = assistant.prepare(chat.conv_id, "(다음 질문이 여기에 들어갑니다)")
    provider = assistant.provider()
    sent = SentDataDialog(prepared.bundle, f"{provider.name}({provider.vendor})", provider.is_mock, window)
    sent.show()
    shot(sent, "05_AI로_보내는_자료.png")
    sent.close()

    # 기존 파일 수정 승인창(차이 보기) — 화면 설명용으로 손으로 만든 제안
    demo_plan = plan_change(assistant.guard(), "주보/11월2주_광고초안.txt",
                            "1. 추수감사주일 예배 안내 — 온 가족이 함께 드립니다\n2. 제직회: 주일 오후\n"
                            "3. 새가족 환영 모임\n4. 김장 나눔 봉사자 모집\n")
    dialog = ApprovalDialog(demo_plan, assistant.workspace(), window)
    dialog.show()
    shot(dialog, "06_파일_승인창_기존파일_차이(설명용_제안).png")
    dialog.close()

    window.tabs.setCurrentIndex(TAB_DOCS)
    pump(100)
    for row in range(window.docs.table.rowCount()):
        if "개요" in window.docs.table.item(row, 0).text():
            window.docs.table.selectRow(row)
    shot(window, "07_문서_탭.png")
    window.tabs.setCurrentIndex(TAB_PLAN)
    shot(window, "08_일정_할일_탭.png")
    window.tabs.setCurrentIndex(TAB_MEMORY)
    shot(window, "09_기억_탭.png")
    run_job(assistant, "briefing", use_ai=False)
    window.tabs.setCurrentIndex(TAB_NOTES)
    shot(window, "10_브리핑_탭.png")
    window.tabs.setCurrentIndex(TAB_LOG)
    pump(100)
    window.log.table.selectRow(window.log.table.rowCount() - 1)
    shot(window, "11_작업로그_탭.png")

    settings = SettingsDialog(assistant, window, start_tab=2)
    settings.show()
    wait_until(lambda: all(w.isFinished() for w in settings._workers), 60_000)
    shot(settings, "12_설정_AI연결.png")
    settings.tabs.setCurrentIndex(1)
    shot(settings, "13_설정_작업폴더_보내는자료.png")
    settings.tabs.setCurrentIndex(3)
    shot(settings, "14_설정_자동작업.png")
    settings.reject()

    # 일반용 + 모의 모드
    db.set_setting("provider", "mock")
    window.check_provider()
    window.tabs.setCurrentIndex(TAB_CHAT)
    window.switch_edition("general")
    window.topic_list.setCurrentRow(2)
    pump(100)
    shot(window, "15_일반용_빈_대화.png")
    chat.input.setPlainText("신제품 안내 글 초안을 만들어 줘")
    chat.send()
    wait_until(lambda: not chat.is_busy(), 30_000)
    shot(window, "16_일반용_모의모드_답변.png")

    window.close()
    db.close()
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
