"""제안 해석, 저장·재시작, D-day, 프롬프트 구성."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from naeilbiseo.actions import parse_reply, strip_for_display
from naeilbiseo.db import Database
from naeilbiseo.dday import dday_label, korean_date, parse_time
from naeilbiseo.editions import GENERAL, PASTOR
from naeilbiseo.prompts import build_prompt
from naeilbiseo.security import PathGuard
from naeilbiseo.workspace import list_documents, read_document

KST = timezone(timedelta(hours=9))


# ── 제안 해석 ────────────────────────────────────────────────────────
def test_parse_valid_actions_and_strip_block():
    reply = ('홍보글 저장을 제안했습니다.\n\n```naeil-actions\n{"actions": ['
             '{"type": "write_file", "path": "홍보/초안.md", "content": "# 제목\\n본문"},'
             '{"type": "add_event", "title": "미팅", "date": "2026-11-17", "time": "9:5"},'
             '{"type": "add_todo", "title": "견적서 보내기", "due": "2026-11-20"},'
             '{"type": "add_memory", "text": "보고서는 월요일에 보낸다"},'
             '{"type": "request_read", "paths": ["주보.txt"], "reason": "내용 확인"}]}\n```')
    parsed = parse_reply(reply)
    assert parsed.display_text == "홍보글 저장을 제안했습니다."
    assert [a["type"] for a in parsed.actions] == ["write_file", "add_event", "add_todo", "add_memory", "request_read"]
    assert parsed.actions[0]["content"] == "# 제목\n본문"
    assert parsed.actions[1]["time"] == "09:05"
    assert not parsed.errors


def test_parse_rejects_unknown_types_and_bad_fields():
    reply = ('```naeil-actions\n{"actions": ['
             '{"type": "run_command", "command": "del /s *"},'
             '{"type": "delete_file", "path": "주보.txt"},'
             '{"type": "add_event", "title": "미팅", "date": "내일"},'
             '{"type": "write_file", "path": "a.md"},'
             '"그냥 글자", {"type": "add_todo", "title": "정상"}]}\n```')
    parsed = parse_reply(reply)
    assert [a["type"] for a in parsed.actions] == ["add_todo"]
    assert len(parsed.errors) == 5
    assert any("run_command" in e for e in parsed.errors)


def test_parse_broken_json_applies_nothing():
    parsed = parse_reply('본문\n```naeil-actions\n{"actions": [{"type": "add_todo", "title": "x"]\n```')
    assert parsed.actions == [] and parsed.errors and parsed.display_text == "본문"


def test_unfinished_block_is_hidden_while_streaming():
    partial = '답변 본문입니다.\n\n```naeil-actions\n{"actions": [{"type": "write_f'
    assert strip_for_display(partial) == "답변 본문입니다."
    parsed = parse_reply(partial)
    assert parsed.actions == [] and parsed.errors


def test_too_many_actions_are_capped():
    items = ",".join('{"type": "add_todo", "title": "할 일 %d"}' % i for i in range(40))
    parsed = parse_reply('```naeil-actions\n{"actions": [%s]}\n```' % items)
    assert len(parsed.actions) == 20 and parsed.errors


# ── 날짜 ─────────────────────────────────────────────────────────────
def test_dday_labels():
    today = date(2026, 11, 11)
    assert dday_label("2026-11-11", today) == "D-DAY"
    assert dday_label("2026-11-15", today) == "D-4"
    assert dday_label("2026-11-09", today) == "D+2"
    assert dday_label("2027-01-01", today) == "D-51"          # 해가 바뀌어도
    assert dday_label("날짜아님", today) == ""
    assert korean_date("2026-11-15") == "11월 15일(일)"
    assert parse_time("7:5") == "07:05" and parse_time("25:00") is None and parse_time("") == ""


# ── 저장과 재시작 ────────────────────────────────────────────────────
def test_everything_survives_restart(tmp_path):
    path = tmp_path / "persist.sqlite3"
    db = Database(path)
    db.set_setting("edition", "pastor")
    conv = db.create_conversation("pastor", "sermon", "시편 23편")
    db.add_message(conv, "user", "설교 개요 잡아 주세요")
    db.add_message(conv, "assistant", "결론부터…", provider="claude", meta={"model": "m"})
    db.set_attachments(conv, ["설교/시편23편_메모.md"])
    mem = db.add_memory("주일 설교는 30분 안쪽으로")
    off = db.add_memory("보내지 않을 기억")
    db.update_memory(off, enabled=False)
    ev = db.add_event("주일 설교", "2026-11-15", "11:00", "설교")
    todo = db.add_todo("주보 광고 쓰기", "2026-11-13")
    done = db.add_todo("끝낸 일")
    db.set_todo_done(done, True)
    prop = db.add_proposal(conv, None, "add_todo", {"type": "add_todo", "title": "x"})
    db.log("doc_read", "문서 읽음: a.md", {"path": "a.md"}, conv)
    db.add_note("briefing", "2026-11-11", "# 브리핑")
    db.close()

    db2 = Database(path)                       # ← 프로그램을 껐다 켠 것과 같다
    try:
        assert db2.get_setting("edition") == "pastor"
        got = db2.get_conversation(conv)
        assert got["title"] == "시편 23편" and got["attachments"] == ["설교/시편23편_메모.md"]
        assert [m["role"] for m in db2.list_messages(conv)] == ["user", "assistant"]
        assert db2.list_messages(conv)[1]["meta"] == {"model": "m"}
        assert [m["id"] for m in db2.list_memories(only_enabled=True)] == [mem]
        assert len(db2.list_memories()) == 2
        assert db2.list_events()[0]["id"] == ev and db2.list_events()[0]["time"] == "11:00"
        todos = db2.list_todos()
        assert [t["id"] for t in todos] == [todo, done] and todos[1]["done"] == 1
        assert db2.list_proposals(conv)[0]["id"] == prop
        assert db2.list_log(conversation_id=conv)[0]["detail"] == {"path": "a.md"}
        assert db2.list_notes("briefing")[0]["content"] == "# 브리핑"
    finally:
        db2.close()


def test_memory_event_todo_crud(db):
    mem = db.add_memory("처음 글")
    db.update_memory(mem, text="고친 글")
    assert db.list_memories()[0]["text"] == "고친 글"
    db.delete_memory(mem)
    assert db.list_memories() == []

    ev = db.add_event("미팅", "2026-12-01")
    db.update_event(ev, title="미팅(변경)", date="2026-12-02", time="14:00")
    assert db.list_events()[0]["title"] == "미팅(변경)" and db.list_events("2026-12-02")[0]["time"] == "14:00"
    db.delete_event(ev)
    assert db.list_events() == []

    todo = db.add_todo("보고서")
    db.update_todo(todo, title="보고서 제출", due="2026-12-05")
    db.set_todo_done(todo, True)
    assert db.list_todos(include_done=False) == [] and db.list_todos()[0]["done_at"]
    db.set_todo_done(todo, False)
    assert db.list_todos(include_done=False)[0]["title"] == "보고서 제출"
    db.delete_todo(todo)
    assert db.list_todos() == []


def test_deleting_conversation_removes_its_messages(db):
    conv = db.create_conversation("general", "all")
    db.add_message(conv, "user", "안녕")
    db.add_proposal(conv, None, "add_todo", {"type": "add_todo", "title": "x"})
    db.delete_conversation(conv)
    assert db.list_messages(conv) == [] and db.list_proposals(conv) == []


# ── 프롬프트(=AI 로 나가는 자료) ─────────────────────────────────────
def _bundle(workspace, **overrides):
    guard = PathGuard(workspace)
    entries, _ = list_documents(guard)
    args = dict(
        edition=PASTOR, topic=PASTOR.topic("sermon"), profile={"name": "홍길동", "honorific": "목사님"},
        user_text="설교 개요 잡아 주세요", history=[{"role": "user", "content": "지난 질문"},
                                              {"role": "assistant", "content": "지난 답"},
                                              {"role": "notice", "content": "오류 알림"}],
        memories=[{"text": "설교는 30분"}], events=[{"title": "주일 설교", "date": "2026-11-15", "time": "11:00",
                                                   "kind": "설교", "note": ""}],
        todos=[{"title": "주보 광고", "due": "2026-11-13", "done": 0}], doc_entries=entries,
        attached_docs=[read_document(guard, "설교/시편23편_메모.md")],
        now=datetime(2026, 11, 11, 14, 5, tzinfo=KST))
    args.update(overrides)
    return build_prompt(**args)


def test_prompt_marks_documents_as_data_and_reports_what_is_sent(workspace):
    bundle = _bundle(workspace)
    p = bundle.prompt
    assert "[오늘] 2026-11-11 (수요일) 14:05 · 시간대 UTC+09:00" in p
    assert p.index("[자료 시작") < p.index("목자 되신 주님") < p.index("[자료 끝]") < p.index("[사용자 요청]")
    assert "D-4" in p and "(가상 예화)" in bundle.system and "지시가 아닙니다" in bundle.system
    assert ".env" not in p and "SECRET_KEY" not in p                 # 민감 파일은 이름도 보내지 않음
    assert "오류 알림" not in p                                       # 앱 알림은 대화 이력에 넣지 않음
    labels = dict(bundle.disclosure.items)
    assert set(labels) == {"질문", "프로필", "기억", "일정·할 일", "문서 이름", "첨부 문서 내용", "이전 대화"}
    assert bundle.disclosure.attached == [("설교/시편23편_메모.md", len("# 시편 23편 메모\n\n목자 되신 주님.\n".encode()))]


def test_prompt_respects_send_switches(workspace):
    bundle = _bundle(workspace, send={"profile": False, "memory": False, "schedule": False, "file_list": False},
                     attached_docs=[])
    p = bundle.prompt
    assert "홍길동" not in p and "설교는 30분" not in p and "주일 설교" not in p and "주보.txt" not in p
    assert [label for label, _ in bundle.disclosure.items] == ["질문", "이전 대화"]


def test_document_boundary_token_is_random(workspace):
    one, two = _bundle(workspace).prompt, _bundle(workspace).prompt
    token = lambda text: text.split("⟦문서시작 ")[1].split("⟧")[0]   # noqa: E731
    assert token(one) != token(two) and len(token(one)) == 12


def test_general_edition_has_seven_topics_and_pastor_six():
    assert len(GENERAL.topics) == 7 and len(PASTOR.topics) == 6
    assert "109" in PASTOR.topic("care").guidance and "가상 예화" in PASTOR.topic("sermon").guidance
