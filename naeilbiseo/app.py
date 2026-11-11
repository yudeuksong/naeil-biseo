"""프로그램 시작점."""
from __future__ import annotations

import sys

from . import APP_NAME, config
from .assistant import Assistant
from .db import Database


def self_test() -> int:
    """포장한 실행 파일이 제대로 뜨는지 확인하는 자가 점검(모의 모드, 외부 전송 없음).

    창을 띄우지 않고(offscreen) 임시 자료 폴더에서 메인 창을 만들고 모의 질문을 한 번 보낸다.
    결과는 종료 코드(0=정상)와 selftest_result.txt 로 남긴다.
    """
    import os
    import tempfile
    import traceback

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    data_dir = os.environ.setdefault("NAEILBISEO_DATA_DIR", tempfile.mkdtemp(prefix="naeilbiseo-selftest-"))
    report = os.path.join(data_dir, "selftest_result.txt")
    try:
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication

        from .providers import MockProvider
        from .ui import theme
        from .ui.main_window import MainWindow

        app = QApplication(sys.argv[:1])
        db = Database(config.db_path())
        assistant = Assistant(db, provider_factory=lambda _p, _e: MockProvider(chunk_delay=0))
        theme.apply_theme(app, theme.DEFAULT_FONT_STEP)
        window = MainWindow(assistant, run_scheduler=False, check_status=False)
        window.show()
        window.chat.send("자가 점검: 초안을 만들어 줘")
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(50)
        timer.timeout.connect(lambda: (not window.chat.is_busy()) and loop.quit())
        timer.start()
        QTimer.singleShot(20_000, loop.quit)
        loop.exec()
        roles = [m["role"] for m in db.list_messages(window.chat.conv_id)]
        ok = roles == ["user", "assistant"] and len(db.list_proposals(window.chat.conv_id)) == 1
        window.close()
        db.close()
        with open(report, "w", encoding="utf-8") as fh:
            fh.write(("OK" if ok else "FAIL") + f" roles={roles}\n")
        return 0 if ok else 1
    except Exception:  # noqa: BLE001
        with open(report, "w", encoding="utf-8") as fh:
            fh.write("FAIL\n" + traceback.format_exc())
        return 1


def main(argv: list[str] | None = None) -> int:
    if "--self-test" in (argv if argv is not None else sys.argv):
        return self_test()

    from PySide6.QtWidgets import QApplication

    from .ui import theme
    from .ui.main_window import MainWindow

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    db = Database(config.db_path())
    assistant = Assistant(db)
    theme.apply_theme(app, int(db.get_setting("font_step", theme.DEFAULT_FONT_STEP)))
    window = MainWindow(assistant)
    window.show()
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
