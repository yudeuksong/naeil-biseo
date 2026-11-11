"""AI 답변에서 '제안'을 꺼내고 검증한다.

AI 는 파일·기억·일정을 직접 바꾸지 못한다. 바꾸고 싶으면 답변 끝에 아래 모양의
구획을 붙이고, 앱이 이를 해석·검증해 '승인 대기' 목록에 올린다.

    ```naeil-actions
    {"actions": [{"type": "write_file", "path": "홍보/초안.md", "content": "..."}]}
    ```

허용하는 종류와 필드만 받아들이고, 나머지는 버리고 이유를 기록한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import config
from .dday import parse_date, parse_time

BLOCK_TAG = "naeil-actions"
_BLOCK_RE = re.compile(r"```[ \t]*" + BLOCK_TAG + r"[ \t]*\r?\n(.*?)\r?\n?```", re.S)
_OPEN_RE = re.compile(r"```[ \t]*" + BLOCK_TAG)

ALLOWED_TYPES = ("write_file", "request_read", "add_memory", "add_event", "add_todo")

MAX_TEXT = 2_000
MAX_TITLE = 200


@dataclass
class ParsedReply:
    display_text: str                         # 제안 구획을 뺀, 사용자에게 보여 줄 글
    actions: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def strip_for_display(text: str) -> str:
    """스트리밍 중에도 쓸 수 있게, 제안 구획(완성됐든 쓰는 중이든)을 잘라낸다."""
    out = _BLOCK_RE.sub("", text)
    m = _OPEN_RE.search(out)
    if m:
        out = out[: m.start()]
    return out.rstrip()


def _str(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > limit:
        return None
    return value


def _validate(action) -> tuple[dict | None, str | None]:
    if not isinstance(action, dict):
        return None, "제안 항목이 객체가 아닙니다."
    kind = action.get("type")
    if kind not in ALLOWED_TYPES:
        return None, f"허용하지 않는 제안 종류입니다: {kind!r}"

    if kind == "write_file":
        path = _str(action.get("path"), 240)
        content = action.get("content")
        if path is None or not isinstance(content, str):
            return None, "write_file 에는 path 와 content(글자)가 필요합니다."
        if len(content.encode("utf-8")) > config.MAX_WRITE_BYTES:
            return None, f"파일 내용이 너무 큽니다: {path}"
        return {"type": kind, "path": path, "content": content}, None

    if kind == "request_read":
        paths = action.get("paths")
        if not isinstance(paths, list) or not paths:
            return None, "request_read 에는 paths 목록이 필요합니다."
        clean = [p for p in (_str(x, 240) for x in paths[:10]) if p]
        if not clean:
            return None, "request_read 의 paths 가 비어 있습니다."
        return {"type": kind, "paths": clean, "reason": _str(action.get("reason"), 300) or ""}, None

    if kind == "add_memory":
        text = _str(action.get("text"), MAX_TEXT)
        if text is None:
            return None, "add_memory 에는 text 가 필요합니다."
        return {"type": kind, "text": text}, None

    if kind == "add_event":
        title = _str(action.get("title"), MAX_TITLE)
        date = action.get("date")
        if title is None or not isinstance(date, str) or parse_date(date) is None:
            return None, "add_event 에는 title 과 날짜(YYYY-MM-DD)가 필요합니다."
        time = parse_time(action.get("time") if isinstance(action.get("time"), str) else "")
        if time is None:
            return None, "add_event 의 time 은 HH:MM 이어야 합니다."
        return {"type": kind, "title": title, "date": parse_date(date).isoformat(), "time": time,
                "kind": _str(action.get("kind"), 20) or "", "note": _str(action.get("note"), 500) or ""}, None

    # add_todo
    title = _str(action.get("title"), MAX_TITLE)
    if title is None:
        return None, "add_todo 에는 title 이 필요합니다."
    due = action.get("due") or ""
    if due and (not isinstance(due, str) or parse_date(due) is None):
        return None, "add_todo 의 due 는 YYYY-MM-DD 이어야 합니다."
    return {"type": kind, "title": title, "due": parse_date(due).isoformat() if due else "",
            "note": _str(action.get("note"), 500) or ""}, None


def parse_reply(text: str) -> ParsedReply:
    """답변 전체를 받아 보여 줄 글과 검증된 제안 목록으로 나눈다."""
    result = ParsedReply(display_text=strip_for_display(text))
    blocks = _BLOCK_RE.findall(text)
    if not blocks:
        if _OPEN_RE.search(text):
            result.errors.append("제안 구획이 끝까지 쓰이지 않아 무시했습니다.")
        return result
    for raw in blocks:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            result.errors.append(f"제안 구획을 해석하지 못해 무시했습니다(JSON 오류: {exc.msg}).")
            continue
        items = data.get("actions") if isinstance(data, dict) else None
        if not isinstance(items, list):
            result.errors.append("제안 구획에 actions 목록이 없어 무시했습니다.")
            continue
        for item in items:
            if len(result.actions) >= config.MAX_ACTIONS_PER_REPLY:
                result.errors.append("제안이 너무 많아 일부를 버렸습니다.")
                break
            action, error = _validate(item)
            if action:
                result.actions.append(action)
            elif error:
                result.errors.append(error)
    return result


def describe(action: dict) -> str:
    """승인 대기 목록에 보여 줄 한 줄 설명."""
    kind = action.get("type")
    if kind == "write_file":
        return f"파일 저장: {action['path']}"
    if kind == "request_read":
        return "문서 읽기 요청: " + ", ".join(action["paths"])
    if kind == "add_memory":
        return f"기억에 남기기: {action['text'][:80]}"
    if kind == "add_event":
        when = action["date"] + (f" {action['time']}" if action.get("time") else "")
        return f"일정 추가: {when} {action['title']}"
    if kind == "add_todo":
        due = f" (기한 {action['due']})" if action.get("due") else ""
        return f"할 일 추가: {action['title']}{due}"
    return str(kind)
