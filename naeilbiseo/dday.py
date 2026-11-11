"""날짜 계산(D-day)과 날짜 글자 검사."""
from __future__ import annotations

from datetime import date, datetime

WEEKDAYS = "월화수목금토일"


def today_local() -> date:
    """이 컴퓨터의 현지 날짜."""
    return datetime.now().astimezone().date()


def parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def parse_time(text: str) -> str | None:
    """'9:5' 같은 입력을 'HH:MM' 으로 고친다. 잘못된 값이면 None, 빈 값이면 ''."""
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        hh, mm = raw.split(":")
        h, m = int(hh), int(mm)
    except ValueError:
        return None
    if 0 <= h <= 23 and 0 <= m <= 59:
        return f"{h:02d}:{m:02d}"
    return None


def days_until(target: date, today: date | None = None) -> int:
    return (target - (today or today_local())).days


def dday_label(target: str | date, today: date | None = None) -> str:
    """'D-3', 'D-DAY', 'D+2'. 날짜가 아니면 빈 글자."""
    d = parse_date(target) if isinstance(target, str) else target
    if d is None:
        return ""
    n = days_until(d, today)
    if n == 0:
        return "D-DAY"
    return f"D-{n}" if n > 0 else f"D+{-n}"


def korean_date(d: str | date) -> str:
    """2026-11-15 → '11월 15일(일)'"""
    dt = parse_date(d) if isinstance(d, str) else d
    if dt is None:
        return str(d)
    return f"{dt.month}월 {dt.day}일({WEEKDAYS[dt.weekday()]})"
