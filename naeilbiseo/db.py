"""SQLite 저장소.

대화·기억·일정·할 일·작업 로그·제안·자동 작업 기록을 이 컴퓨터의 파일 하나에 저장한다.
인터넷 서버로 보내는 것은 없다(AI 로 보내는 자료는 prompts.py 가 따로 만든다).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edition TEXT NOT NULL,
    topic TEXT NOT NULL,
    title TEXT NOT NULL,
    attachments TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,              -- user | assistant | notice
    content TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    is_mock INTEGER NOT NULL DEFAULT 0,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',   -- user | ai
    enabled INTEGER NOT NULL DEFAULT 1,    -- 1 이면 대화 때 AI 로 보냄
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    date TEXT NOT NULL,                    -- YYYY-MM-DD (이 컴퓨터의 현지 날짜)
    time TEXT NOT NULL DEFAULT '',         -- HH:MM 또는 빈 값
    kind TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    due TEXT NOT NULL DEFAULT '',          -- YYYY-MM-DD 또는 빈 값
    note TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    done_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS worklog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    conversation_id INTEGER,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_worklog_conv ON worklog(conversation_id, id);
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id INTEGER,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | applied | rejected | failed
    result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                    -- briefing | journal
    date TEXT NOT NULL,
    content TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    is_mock INTEGER NOT NULL DEFAULT 0,
    used_ai INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL,
    run_date TEXT NOT NULL,                -- 현지 날짜. (job_key, run_date) 가 하루 한 번을 보장
    status TEXT NOT NULL,                  -- running | done | failed
    attempts INTEGER NOT NULL DEFAULT 1,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    UNIQUE(job_key, run_date)
);
"""


def now_iso() -> str:
    """현지 시각을 시간대 정보(+09:00 등)까지 붙여 적는다."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys=ON")
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            self._conn.executescript(_SCHEMA)
            if self.get_setting("schema_version") is None:
                self.set_setting("schema_version", SCHEMA_VERSION)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── 저수준 ───────────────────────────────────────────────────
    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    def _all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def _one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    # ── 설정 ─────────────────────────────────────────────────────
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._one("SELECT value FROM settings WHERE key=?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_setting(self, key: str, value: Any) -> None:
        self._exec(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    # ── 대화 ─────────────────────────────────────────────────────
    def create_conversation(self, edition: str, topic: str, title: str = "새 대화") -> int:
        ts = now_iso()
        cur = self._exec(
            "INSERT INTO conversations(edition,topic,title,created_at,updated_at) VALUES(?,?,?,?,?)",
            (edition, topic, title, ts, ts),
        )
        return int(cur.lastrowid)

    def list_conversations(self, edition: str, topic: str | None = None) -> list[dict]:
        if topic is None:
            return self._all("SELECT * FROM conversations WHERE edition=? ORDER BY updated_at DESC, id DESC", (edition,))
        return self._all(
            "SELECT * FROM conversations WHERE edition=? AND topic=? ORDER BY updated_at DESC, id DESC",
            (edition, topic),
        )

    def get_conversation(self, conv_id: int) -> dict | None:
        row = self._one("SELECT * FROM conversations WHERE id=?", (conv_id,))
        if row:
            row["attachments"] = json.loads(row["attachments"] or "[]")
        return row

    def rename_conversation(self, conv_id: int, title: str) -> None:
        self._exec("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title, now_iso(), conv_id))

    def set_attachments(self, conv_id: int, rel_paths: list[str]) -> None:
        self._exec("UPDATE conversations SET attachments=? WHERE id=?",
                   (json.dumps(sorted(set(rel_paths)), ensure_ascii=False), conv_id))

    def delete_conversation(self, conv_id: int) -> None:
        self._exec("DELETE FROM conversations WHERE id=?", (conv_id,))

    def add_message(self, conv_id: int, role: str, content: str, *, provider: str = "",
                    is_mock: bool = False, meta: dict | None = None) -> int:
        ts = now_iso()
        cur = self._exec(
            "INSERT INTO messages(conversation_id,role,content,provider,is_mock,meta,created_at) VALUES(?,?,?,?,?,?,?)",
            (conv_id, role, content, provider, int(is_mock), json.dumps(meta or {}, ensure_ascii=False), ts),
        )
        self._exec("UPDATE conversations SET updated_at=? WHERE id=?", (ts, conv_id))
        return int(cur.lastrowid)

    def list_messages(self, conv_id: int) -> list[dict]:
        rows = self._all("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (conv_id,))
        for r in rows:
            r["meta"] = json.loads(r["meta"] or "{}")
        return rows

    def messages_on_date(self, date: str) -> list[dict]:
        return self._all(
            "SELECT m.*, c.title AS conv_title FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            "WHERE substr(m.created_at,1,10)=? ORDER BY m.id", (date,))

    # ── 기억 ─────────────────────────────────────────────────────
    def add_memory(self, text: str, source: str = "user") -> int:
        ts = now_iso()
        cur = self._exec("INSERT INTO memories(text,source,created_at,updated_at) VALUES(?,?,?,?)",
                         (text.strip(), source, ts, ts))
        return int(cur.lastrowid)

    def list_memories(self, only_enabled: bool = False) -> list[dict]:
        sql = "SELECT * FROM memories" + (" WHERE enabled=1" if only_enabled else "") + " ORDER BY id"
        return self._all(sql)

    def update_memory(self, mem_id: int, *, text: str | None = None, enabled: bool | None = None) -> None:
        if text is not None:
            self._exec("UPDATE memories SET text=?, updated_at=? WHERE id=?", (text.strip(), now_iso(), mem_id))
        if enabled is not None:
            self._exec("UPDATE memories SET enabled=?, updated_at=? WHERE id=?", (int(enabled), now_iso(), mem_id))

    def delete_memory(self, mem_id: int) -> None:
        self._exec("DELETE FROM memories WHERE id=?", (mem_id,))

    # ── 일정 ─────────────────────────────────────────────────────
    def add_event(self, title: str, date: str, time: str = "", kind: str = "", note: str = "") -> int:
        cur = self._exec("INSERT INTO events(title,date,time,kind,note,created_at) VALUES(?,?,?,?,?,?)",
                         (title.strip(), date, time, kind, note, now_iso()))
        return int(cur.lastrowid)

    def list_events(self, from_date: str | None = None) -> list[dict]:
        if from_date:
            return self._all("SELECT * FROM events WHERE date>=? ORDER BY date, time, id", (from_date,))
        return self._all("SELECT * FROM events ORDER BY date, time, id")

    def update_event(self, event_id: int, **fields: Any) -> None:
        allowed = {k: v for k, v in fields.items() if k in {"title", "date", "time", "kind", "note"}}
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            self._exec(f"UPDATE events SET {sets} WHERE id=?", (*allowed.values(), event_id))

    def delete_event(self, event_id: int) -> None:
        self._exec("DELETE FROM events WHERE id=?", (event_id,))

    # ── 할 일 ────────────────────────────────────────────────────
    def add_todo(self, title: str, due: str = "", note: str = "") -> int:
        cur = self._exec("INSERT INTO todos(title,due,note,created_at) VALUES(?,?,?,?)",
                         (title.strip(), due, note, now_iso()))
        return int(cur.lastrowid)

    def list_todos(self, include_done: bool = True) -> list[dict]:
        sql = "SELECT * FROM todos" + ("" if include_done else " WHERE done=0")
        return self._all(sql + " ORDER BY done, CASE WHEN due='' THEN 1 ELSE 0 END, due, id")

    def update_todo(self, todo_id: int, **fields: Any) -> None:
        allowed = {k: v for k, v in fields.items() if k in {"title", "due", "note"}}
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            self._exec(f"UPDATE todos SET {sets} WHERE id=?", (*allowed.values(), todo_id))

    def set_todo_done(self, todo_id: int, done: bool) -> None:
        self._exec("UPDATE todos SET done=?, done_at=? WHERE id=?",
                   (int(done), now_iso() if done else "", todo_id))

    def delete_todo(self, todo_id: int) -> None:
        self._exec("DELETE FROM todos WHERE id=?", (todo_id,))

    # ── 작업 로그 ────────────────────────────────────────────────
    def log(self, kind: str, summary: str, detail: dict | None = None, conversation_id: int | None = None) -> int:
        cur = self._exec("INSERT INTO worklog(ts,conversation_id,kind,summary,detail) VALUES(?,?,?,?,?)",
                         (now_iso(), conversation_id, kind, summary, json.dumps(detail or {}, ensure_ascii=False)))
        return int(cur.lastrowid)

    def list_log(self, limit: int = 500, conversation_id: int | None = None, kind: str | None = None) -> list[dict]:
        where, params = [], []
        if conversation_id is not None:
            where.append("conversation_id=?")
            params.append(conversation_id)
        if kind:
            where.append("kind=?")
            params.append(kind)
        sql = "SELECT * FROM worklog" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
        rows = self._all(sql, (*params, limit))
        for r in rows:
            r["detail"] = json.loads(r["detail"] or "{}")
        return rows

    # ── 제안(승인 대기) ──────────────────────────────────────────
    def add_proposal(self, conv_id: int, message_id: int | None, type_: str, payload: dict) -> int:
        cur = self._exec(
            "INSERT INTO proposals(conversation_id,message_id,type,payload,created_at) VALUES(?,?,?,?,?)",
            (conv_id, message_id, type_, json.dumps(payload, ensure_ascii=False), now_iso()))
        return int(cur.lastrowid)

    def _proposal_row(self, row: dict | None) -> dict | None:
        if row:
            row["payload"] = json.loads(row["payload"])
        return row

    def get_proposal(self, proposal_id: int) -> dict | None:
        return self._proposal_row(self._one("SELECT * FROM proposals WHERE id=?", (proposal_id,)))

    def list_proposals(self, conv_id: int | None = None, status: str | None = "pending") -> list[dict]:
        where, params = [], []
        if conv_id is not None:
            where.append("conversation_id=?")
            params.append(conv_id)
        if status:
            where.append("status=?")
            params.append(status)
        sql = "SELECT * FROM proposals" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
        return [self._proposal_row(r) for r in self._all(sql, params)]

    def resolve_proposal(self, proposal_id: int, status: str, result: str = "") -> None:
        self._exec("UPDATE proposals SET status=?, result=?, resolved_at=? WHERE id=?",
                   (status, result, now_iso(), proposal_id))

    # ── 브리핑·일지 ──────────────────────────────────────────────
    def add_note(self, kind: str, date: str, content: str, *, provider: str = "", is_mock: bool = False,
                 used_ai: bool = False) -> int:
        cur = self._exec(
            "INSERT INTO notes(kind,date,content,provider,is_mock,used_ai,created_at) VALUES(?,?,?,?,?,?,?)",
            (kind, date, content, provider, int(is_mock), int(used_ai), now_iso()))
        return int(cur.lastrowid)

    def list_notes(self, kind: str | None = None, limit: int = 200) -> list[dict]:
        if kind:
            return self._all("SELECT * FROM notes WHERE kind=? ORDER BY date DESC, id DESC LIMIT ?", (kind, limit))
        return self._all("SELECT * FROM notes ORDER BY date DESC, id DESC LIMIT ?", (limit,))

    def delete_note(self, note_id: int) -> None:
        self._exec("DELETE FROM notes WHERE id=?", (note_id,))

    # ── 자동 작업 실행 기록(중복 방지) ───────────────────────────
    def get_job_run(self, job_key: str, run_date: str) -> dict | None:
        return self._one("SELECT * FROM job_runs WHERE job_key=? AND run_date=?", (job_key, run_date))

    def claim_job(self, job_key: str, run_date: str, ts: str | None = None) -> bool:
        """오늘 이 작업을 '내가 맡는다'고 적는다. 이미 적혀 있으면 False(중복 실행 방지)."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO job_runs(job_key,run_date,status,started_at) VALUES(?,?,?,?)",
                (job_key, run_date, "running", ts or now_iso()))
            return cur.rowcount == 1

    def reclaim_job(self, job_key: str, run_date: str, expected_status: str, expected_attempts: int,
                    ts: str | None = None) -> bool:
        """실패했거나 멈춘 실행을 다시 맡는다. 다른 쪽이 먼저 맡았으면 False."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE job_runs SET status='running', attempts=attempts+1, started_at=?, finished_at='', message='' "
                "WHERE job_key=? AND run_date=? AND status=? AND attempts=?",
                (ts or now_iso(), job_key, run_date, expected_status, expected_attempts))
            return cur.rowcount == 1

    def finish_job(self, job_key: str, run_date: str, status: str, message: str = "") -> None:
        self._exec("UPDATE job_runs SET status=?, finished_at=?, message=? WHERE job_key=? AND run_date=?",
                   (status, now_iso(), message, job_key, run_date))

    def list_job_runs(self, limit: int = 50) -> list[dict]:
        return self._all("SELECT * FROM job_runs ORDER BY run_date DESC, id DESC LIMIT ?", (limit,))
