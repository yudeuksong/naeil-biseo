"""브리핑·일지 자동 작업 — 하루 한 번, 재시작해도 중복 없음, 시각·시간대."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from naeilbiseo.assistant import Assistant
from naeilbiseo.db import Database
from naeilbiseo.providers import ErrorKind, MockProvider, ProviderError
from naeilbiseo.scheduler import MAX_ATTEMPTS, RETRY_GAP, STALE_RUNNING, Scheduler, run_job

KST = timezone(timedelta(hours=9))


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=KST)


class CountingRunner:
    def __init__(self, fail_times: int = 0):
        self.calls: list[tuple[str, str]] = []
        self.fail_times = fail_times
        self.lock = threading.Lock()

    def __call__(self, assistant, job_key, now):
        with self.lock:
            self.calls.append((job_key, now.date().isoformat()))
            if self.fail_times > 0:
                self.fail_times -= 1
                raise RuntimeError("일부러 낸 실패")
        return 1, "테스트 실행"


@pytest.fixture
def assistant(db):
    a = Assistant(db, provider_factory=lambda _p, _e: MockProvider(chunk_delay=0))
    db.set_setting("jobs", {"briefing": {"enabled": True, "time": "07:00"},
                            "journal": {"enabled": True, "time": "21:30"}})
    return a


def test_not_due_before_time_and_runs_once_after(assistant):
    runner = CountingRunner()
    sched = Scheduler(assistant, runner=runner)
    assert sched.tick(at(11, 6, 59)) == []
    outcomes = sched.tick(at(11, 7, 0))
    assert [(o.job_key, o.status) for o in outcomes] == [("briefing", "done")]
    assert sched.tick(at(11, 7, 1)) == [] and sched.tick(at(11, 12)) == []
    assert runner.calls == [("briefing", "2026-11-11")]


def test_restart_same_day_does_not_repeat(tmp_path):
    path = tmp_path / "sched.sqlite3"
    runner = CountingRunner()
    db1 = Database(path)
    Scheduler(Assistant(db1), runner=runner).tick(at(11, 8))
    db1.close()

    db2 = Database(path)                       # 프로그램을 껐다 켬
    try:
        sched = Scheduler(Assistant(db2), runner=runner)
        assert sched.tick(at(11, 9)) == []     # 같은 날: 다시 하지 않음
        assert sched.due(at(11, 9)) == []
        assert [o.job_key for o in sched.tick(at(12, 7, 5))] == ["briefing"]   # 다음 날: 한 번
    finally:
        db2.close()
    assert runner.calls == [("briefing", "2026-11-11"), ("briefing", "2026-11-12")]


def test_late_start_catches_up_once_and_evening_job_runs_too(assistant):
    runner = CountingRunner()
    sched = Scheduler(assistant, runner=runner)
    outcomes = sched.tick(at(11, 22))          # 밤 10시에 처음 켬: 둘 다 그날 몫을 한 번씩
    assert sorted(o.job_key for o in outcomes) == ["briefing", "journal"]
    assert sched.tick(at(11, 23, 59)) == []
    assert len(runner.calls) == 2


def test_disabled_job_and_changed_time(assistant):
    assistant.db.set_setting("jobs", {"briefing": {"enabled": False, "time": "07:00"},
                                      "journal": {"enabled": True, "time": "18:00"}})
    runner = CountingRunner()
    sched = Scheduler(assistant, runner=runner)
    assert sched.tick(at(11, 17, 59)) == []
    assert [o.job_key for o in sched.tick(at(11, 18))] == ["journal"]
    assert runner.calls == [("journal", "2026-11-11")]


def test_local_date_decides_the_day_not_utc(assistant):
    """한국 시각 11월 12일 00:30 은 UTC 로는 아직 11일이다. 현지 날짜(12일)로 센다."""
    assistant.db.set_setting("jobs", {"briefing": {"enabled": True, "time": "00:10"},
                                      "journal": {"enabled": False}})
    runner = CountingRunner()
    sched = Scheduler(assistant, runner=runner)
    sched.tick(at(11, 23, 50))
    sched.tick(at(12, 0, 30))
    assert runner.calls == [("briefing", "2026-11-11"), ("briefing", "2026-11-12")]
    assert assistant.db.get_job_run("briefing", "2026-11-12")["status"] == "done"


def test_failed_job_retries_after_gap_up_to_limit(assistant):
    assistant.db.set_setting("jobs", {"briefing": {"enabled": True, "time": "07:00"}, "journal": {"enabled": False}})
    runner = CountingRunner(fail_times=10)
    sched = Scheduler(assistant, runner=runner)
    base = at(11, 8)
    assert sched.tick(base)[0].status == "failed"
    assert sched.tick(base + timedelta(minutes=1)) == []            # 간격 전에는 다시 하지 않음
    assert len(runner.calls) == 1
    for n in range(1, 6):
        sched.tick(base + n * (RETRY_GAP + timedelta(minutes=1)))
    assert len(runner.calls) == MAX_ATTEMPTS                        # 최대 횟수에서 멈춤
    assert assistant.db.get_job_run("briefing", base.date().isoformat())["status"] == "failed"


def test_crashed_run_is_reclaimed_only_after_it_is_stale(assistant):
    assistant.db.set_setting("jobs", {"briefing": {"enabled": True, "time": "07:00"}, "journal": {"enabled": False}})
    now = at(11, 9)
    assert assistant.db.claim_job("briefing", "2026-11-11", now.isoformat())      # 실행 중에 꺼진 상황
    runner = CountingRunner()
    sched = Scheduler(assistant, runner=runner)
    assert sched.tick(now + timedelta(minutes=1)) == [] and runner.calls == []
    outcomes = sched.tick(now + STALE_RUNNING + timedelta(minutes=5))
    assert [o.status for o in outcomes] == ["done"] and len(runner.calls) == 1


def test_two_schedulers_racing_run_the_job_once(tmp_path):
    path = tmp_path / "race.sqlite3"
    dbs = [Database(path), Database(path)]
    runner = CountingRunner()
    scheds = [Scheduler(Assistant(d), runner=runner) for d in dbs]
    barrier = threading.Barrier(2)

    def go(s):
        barrier.wait()
        s.tick(at(11, 8))

    threads = [threading.Thread(target=go, args=(s,)) for s in scheds]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for d in dbs:
        d.close()
    assert sorted(runner.calls) == [("briefing", "2026-11-11")]


# ── 실제 작업 내용 ───────────────────────────────────────────────────
def test_briefing_is_rule_based_by_default_and_lists_dday(assistant):
    db = assistant.db
    db.add_event("주일 설교", "2026-11-15", "11:00")
    db.add_event("오늘 심방", "2026-11-11", "15:00")
    db.add_todo("주보 광고 쓰기", "2026-11-10")
    note_id, summary = run_job(assistant, "briefing", at(11, 7))
    note = db.list_notes("briefing")[0]
    assert note["id"] == note_id and note["used_ai"] == 0 and "AI 미사용" in summary
    assert "15:00 오늘 심방" in note["content"] and "D-4" in note["content"]
    assert "기한이 지난 할 일이 1개" in note["content"]


def test_briefing_with_mock_ai_is_labelled_as_mock(assistant):
    _, summary = run_job(assistant, "briefing", at(11, 7), use_ai=True)
    note = assistant.db.list_notes("briefing")[0]
    assert note["is_mock"] == 1 and note["used_ai"] == 1
    assert "모의 응답 — 실제 AI 아님" in note["content"] and "모의" in summary


def test_ai_failure_still_saves_rule_based_note(db):
    class Failing(MockProvider):
        def run(self, request, on_text, cancel):
            raise ProviderError(ErrorKind.NOT_LOGGED_IN, "로그인되어 있지 않습니다.")

    assistant = Assistant(db, provider_factory=lambda _p, _e: Failing())
    _, summary = run_job(assistant, "journal", at(11, 21, 30), use_ai=True)
    note = db.list_notes("journal")[0]
    assert note["used_ai"] == 0 and "AI 조언은 받지 못했습니다" in note["content"]
    assert "not_logged_in" in summary
