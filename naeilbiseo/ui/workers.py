"""오래 걸리는 일을 화면과 다른 스레드에서 돌리는 일꾼들."""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from ..assistant import Assistant, TurnResult
from ..providers import ErrorKind, Provider, ProviderError, ProviderStatus
from ..scheduler import run_job


class TurnWorker(QThread):
    """AI 에 한 번 묻고 답을 받는다. delta 로 조각이, done 으로 결과가 온다."""
    delta = Signal(str)
    done = Signal(object)

    def __init__(self, assistant: Assistant, conv_id: int, text: str, parent=None):
        super().__init__(parent)
        self.assistant, self.conv_id, self.text = assistant, conv_id, text
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            result = self.assistant.run_turn(self.conv_id, self.text, self.delta.emit, self.cancel_event)
        except Exception as exc:  # noqa: BLE001 — 화면이 멈추지 않도록 모든 오류를 결과로 돌려준다
            result = TurnResult(self.conv_id, error=ProviderError(ErrorKind.CLI_ERROR, f"예상하지 못한 오류: {exc}"))
            self.assistant.db.log("ai_error", f"예상하지 못한 오류: {exc}", {}, self.conv_id)
        self.done.emit(result)


class StatusWorker(QThread):
    """AI 연결의 설치·로그인 상태를 확인한다."""
    done = Signal(str, object)

    def __init__(self, provider: Provider, parent=None):
        super().__init__(parent)
        self.provider = provider

    def run(self) -> None:
        try:
            status = self.provider.status()
        except Exception as exc:  # noqa: BLE001
            status = ProviderStatus(self.provider.id, self.provider.name, installed=False,
                                    detail=f"상태 확인 중 오류: {exc}")
        self.done.emit(self.provider.id, status)


class JobWorker(QThread):
    """브리핑·일지를 지금 만든다(수동 실행)."""
    done = Signal(str, bool, str)

    def __init__(self, assistant: Assistant, job_key: str, use_ai: bool, parent=None):
        super().__init__(parent)
        self.assistant, self.job_key, self.use_ai = assistant, job_key, use_ai
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            _note_id, summary = run_job(self.assistant, self.job_key, cancel=self.cancel_event, use_ai=self.use_ai)
            self.done.emit(self.job_key, True, summary)
        except Exception as exc:  # noqa: BLE001
            self.done.emit(self.job_key, False, str(exc))


class TickWorker(QThread):
    """자동 작업 확인(스케줄러 tick)."""
    done = Signal(object)

    def __init__(self, scheduler, parent=None):
        super().__init__(parent)
        self.scheduler = scheduler

    def run(self) -> None:
        try:
            outcomes = self.scheduler.tick()
        except Exception:  # noqa: BLE001
            outcomes = []
        self.done.emit(outcomes)
