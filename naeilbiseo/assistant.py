"""비서의 두뇌 역할을 하는 서비스 계층(화면과 무관 — 테스트하기 쉽게 Qt 를 쓰지 않는다).

한 번의 대화 흐름
  1) 첨부하기로 한 문서를 PathGuard 로 검증해 읽는다 → 작업 로그 '문서 읽음'
  2) 프롬프트를 만든다(무엇이 AI 로 나가는지 Disclosure 로 남긴다)
  3) AI 연결(Provider)에 보내 답을 스트리밍으로 받는다
  4) 답에서 '제안'을 꺼내 검증하고 '승인 대기'에 올린다 — 이때까지 디스크는 바뀌지 않는다
  5) 사용자가 승인하면 실행기가 다시 검증한 뒤 반영한다 → 작업 로그 '파일 만듦/고침'
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Callable

from . import config
from .actions import describe, parse_reply
from .db import Database
from .editions import Edition, get_edition
from .fileops import ChangePlan, FileOpError, apply_change, plan_change
from .prompts import DEFAULT_SEND, PromptBundle, build_prompt
from .providers import DEFAULT_PROVIDER, ChatRequest, ErrorKind, Provider, ProviderError, create_provider
from .security import PathGuard
from .workspace import DocContent, DocEntry, DocumentError, human_size, list_documents, open_guard, read_document

DEFAULT_JOBS = {
    "briefing": {"enabled": True, "time": "07:00", "use_ai": False},
    "journal": {"enabled": True, "time": "21:30", "use_ai": False},
}


@dataclass
class PreparedTurn:
    bundle: PromptBundle
    docs: list[DocContent]
    skipped: list[tuple[str, str]]          # (경로, 못 읽은 이유)


@dataclass
class TurnResult:
    conversation_id: int
    text: str = ""
    message_id: int | None = None
    proposals: list[dict] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    error: ProviderError | None = None
    is_mock: bool = False


@dataclass
class ApproveResult:
    ok: bool
    message: str
    followup: bool = False                  # 문서 읽기 요청을 승인해 이어서 물어야 할 때


class Assistant:
    def __init__(self, db: Database, provider_factory: Callable[[str, str], Provider] | None = None):
        self.db = db
        self._provider_factory = provider_factory or create_provider

    # ── 설정 ─────────────────────────────────────────────────────
    def edition(self) -> Edition:
        return get_edition(self.db.get_setting("edition", "general"))

    def set_edition(self, key: str) -> None:
        self.db.set_setting("edition", get_edition(key).key)

    def profile(self, edition_key: str | None = None) -> dict:
        ed = get_edition(edition_key or self.edition().key)
        prof = self.db.get_setting(f"profile.{ed.key}", {}) or {}
        prof.setdefault("honorific", ed.default_honorific)
        return prof

    def set_profile(self, edition_key: str, profile: dict) -> None:
        clean = {k: str(profile.get(k, "")).strip()[:1000] for k in ("name", "honorific", "org", "about")}
        self.db.set_setting(f"profile.{get_edition(edition_key).key}", clean)

    def workspace(self) -> str:
        return self.db.get_setting("workspace", "") or ""

    def set_workspace(self, path: str) -> None:
        real = os.path.realpath(path)
        if not os.path.isdir(real):
            raise ValueError("폴더가 아닙니다.")
        home = os.path.realpath(os.path.expanduser("~"))
        drive_root = os.path.splitdrive(real)[1] in ("\\", "/", "")
        if real == home or drive_root:
            raise ValueError("홈 폴더 전체나 드라이브 전체는 작업 폴더로 쓸 수 없습니다. 일할 자료만 모은 폴더를 골라 주세요.")
        self.db.set_setting("workspace", real)
        self.db.log("workspace", f"작업 폴더를 정함: {real}", {"path": real})

    def guard(self) -> PathGuard | None:
        return open_guard(self.workspace())

    def send_options(self) -> dict:
        return {**DEFAULT_SEND, **(self.db.get_setting("send", {}) or {})}

    def jobs(self) -> dict:
        saved = self.db.get_setting("jobs", {}) or {}
        return {key: {**default, **(saved.get(key) or {})} for key, default in DEFAULT_JOBS.items()}

    def provider_id(self) -> str:
        return self.db.get_setting("provider", DEFAULT_PROVIDER) or DEFAULT_PROVIDER

    def provider(self) -> Provider:
        pid = self.provider_id()
        return self._provider_factory(pid, self.db.get_setting(f"provider.exe.{pid}", "") or "")

    # ── 문서 ─────────────────────────────────────────────────────
    def documents(self) -> tuple[list[DocEntry], bool]:
        guard = self.guard()
        return list_documents(guard) if guard else ([], False)

    def attach(self, conv_id: int, rel_path: str) -> None:
        """문서 하나를 이 대화에 첨부한다(검증 통과한 것만)."""
        guard = self.guard()
        if not guard:
            raise DocumentError("no_workspace", "작업 폴더를 먼저 정해 주세요.")
        doc = read_document(guard, rel_path)
        conv = self.db.get_conversation(conv_id)
        self.db.set_attachments(conv_id, [*conv["attachments"], doc.rel_path])

    def detach(self, conv_id: int, rel_path: str) -> None:
        conv = self.db.get_conversation(conv_id)
        self.db.set_attachments(conv_id, [p for p in conv["attachments"] if p != rel_path])

    # ── 한 번의 대화 ─────────────────────────────────────────────
    def prepare(self, conv_id: int, user_text: str) -> PreparedTurn:
        conv = self.db.get_conversation(conv_id)
        edition = get_edition(conv["edition"])
        topic = edition.topic(conv["topic"])
        guard = self.guard()
        docs: list[DocContent] = []
        skipped: list[tuple[str, str]] = []
        entries: list[DocEntry] = []
        if guard:
            entries, _ = list_documents(guard)
            total = 0
            for rel in conv["attachments"]:
                try:
                    doc = read_document(guard, rel)
                except DocumentError as exc:
                    skipped.append((rel, exc.message))
                    continue
                if total + doc.size > config.MAX_TOTAL_ATTACH_BYTES:
                    skipped.append((rel, f"첨부 합계 한도({human_size(config.MAX_TOTAL_ATTACH_BYTES)}) 초과"))
                    continue
                total += doc.size
                docs.append(doc)
        elif conv["attachments"]:
            skipped = [(rel, "작업 폴더가 정해지지 않음") for rel in conv["attachments"]]
        bundle = build_prompt(
            edition=edition, topic=topic, profile=self.profile(edition.key), user_text=user_text,
            history=self.db.list_messages(conv_id), memories=self.db.list_memories(only_enabled=True),
            events=self.db.list_events(), todos=self.db.list_todos(), doc_entries=entries,
            attached_docs=docs, send=self.send_options(), workspace_set=guard is not None)
        return PreparedTurn(bundle, docs, skipped)

    def run_turn(self, conv_id: int, user_text: str, on_text: Callable[[str], None],
                 cancel: threading.Event) -> TurnResult:
        user_text = user_text.strip()
        result = TurnResult(conv_id)
        prepared = self.prepare(conv_id, user_text)
        provider = self.provider()
        result.is_mock = provider.is_mock

        conv = self.db.get_conversation(conv_id)
        if conv["title"] == "새 대화":
            self.db.rename_conversation(conv_id, user_text.replace("\n", " ")[:28] or "새 대화")
        self.db.add_message(conv_id, "user", user_text, meta={
            "attachments": [d.rel_path for d in prepared.docs],
            "sent": prepared.bundle.disclosure.items,
        })
        for doc in prepared.docs:
            self.db.log("doc_read", f"문서 읽음: {doc.rel_path} ({human_size(doc.size)})",
                        {"path": doc.rel_path, "bytes": doc.size, "sha256": doc.sha256,
                         "sent_to": provider.vendor if not provider.is_mock else "보내지 않음(모의 모드)"}, conv_id)
        for rel, reason in prepared.skipped:
            self.db.log("blocked", f"문서를 읽지 않음: {rel} — {reason}", {"path": rel, "reason": reason}, conv_id)

        timeout = float(self.db.get_setting("timeout_sec", config.DEFAULT_TIMEOUT_SEC))
        model = self.db.get_setting(f"provider.model.{provider.id}", "") or ""
        request = ChatRequest(system=prepared.bundle.system, prompt=prepared.bundle.prompt,
                              timeout_sec=timeout, model=model)
        sent = prepared.bundle.disclosure.one_line()
        try:
            run = provider.run(request, on_text, cancel)
        except ProviderError as exc:
            result.error = exc
            label = "멈춤" if exc.kind == ErrorKind.CANCELLED else "오류"
            self.db.add_message(conv_id, "notice", f"⚠ {exc.message}", provider=provider.id, is_mock=provider.is_mock,
                                meta={"error": exc.kind.value})
            self.db.log("ai_error", f"AI {label}({provider.name}): {exc.message}",
                        {"kind": exc.kind.value, "detail": exc.detail, "sent": sent}, conv_id)
            return result

        parsed = parse_reply(run.text)
        result.text = parsed.display_text
        result.parse_errors = parsed.errors
        result.message_id = self.db.add_message(
            conv_id, "assistant", parsed.display_text or "(빈 답)", provider=run.provider_id, is_mock=run.is_mock,
            meta={"provider_name": run.provider_name, "duration_sec": round(run.duration_sec, 1),
                  "model": run.meta.get("model", ""), "proposal_errors": parsed.errors})
        mode = "모의 응답(실제 AI 아님)" if run.is_mock else "실제 AI 응답"
        self.db.log("ai_answer", f"{mode} 받음: {run.provider_name} · {run.duration_sec:.1f}초",
                    {"provider": run.provider_id, "model": run.meta.get("model", ""), "mock": run.is_mock,
                     "sent": sent, "sent_chars": prepared.bundle.disclosure.total_chars,
                     "tools_at_start": run.meta.get("tools_at_start"),
                     "init_checked": run.meta.get("init_checked", False)}, conv_id)
        for tool in run.meta.get("tools_used", []) or []:
            self.db.log("cli_tool", f"주의: CLI 가 스스로 도구를 사용함 — {tool}", {"tool": tool}, conv_id)
        for err in parsed.errors:
            self.db.log("blocked", f"제안을 받아들이지 않음: {err}", {}, conv_id)
        for action in parsed.actions:
            pid = self.db.add_proposal(conv_id, result.message_id, action["type"], action)
            self.db.log("proposal", f"제안 받음(승인 대기): {describe(action)}", {"proposal_id": pid}, conv_id)
            result.proposals.append(self.db.get_proposal(pid))
        return result

    # ── 제안 승인·거절 ───────────────────────────────────────────
    def plan_for(self, proposal: dict) -> ChangePlan:
        """파일 제안의 변경 계획(차이 포함)을 만든다. 승인 창에서 보여 준다."""
        guard = self.guard()
        if not guard:
            raise FileOpError("no_workspace", "작업 폴더를 먼저 정해 주세요.")
        payload = proposal["payload"]
        return plan_change(guard, payload["path"], payload["content"])

    def approve(self, proposal_id: int, plan: ChangePlan | None = None) -> ApproveResult:
        prop = self.db.get_proposal(proposal_id)
        if not prop or prop["status"] != "pending":
            return ApproveResult(False, "이미 처리된 제안입니다.")
        conv_id, payload, kind = prop["conversation_id"], prop["payload"], prop["type"]

        if kind == "write_file":
            guard = self.guard()
            try:
                if not guard:
                    raise FileOpError("no_workspace", "작업 폴더를 먼저 정해 주세요.")
                plan = plan or plan_change(guard, payload["path"], payload["content"])
                if plan.new_content != plan_change(guard, payload["path"], payload["content"]).new_content:
                    raise FileOpError("mismatch", "승인한 내용과 제안 내용이 다릅니다.")
                done = apply_change(guard, plan)
            except FileOpError as exc:
                # 충돌처럼 다시 시도할 수 있는 실패가 아니면 제안을 닫는다
                status = "pending" if exc.code == "no_workspace" else "failed"
                if status == "failed":
                    self.db.resolve_proposal(proposal_id, "failed", exc.message)
                self.db.log("blocked", f"파일 쓰기 거절: {payload['path']} — {exc.message}",
                            {"path": payload["path"], "code": exc.code}, conv_id)
                return ApproveResult(False, exc.message)
            if done.kind == "create":
                msg = f"파일 만듦: {done.rel_path} ({human_size(done.bytes_written)})"
                self.db.log("file_created", msg, {"path": done.rel_path, "bytes": done.bytes_written}, conv_id)
            else:
                msg = f"파일 고침: {done.rel_path} ({human_size(done.bytes_written)}) · 백업 {done.backup_rel_path}"
                self.db.log("file_updated", msg, {"path": done.rel_path, "bytes": done.bytes_written,
                                                  "backup": done.backup_rel_path}, conv_id)
            self.db.resolve_proposal(proposal_id, "applied", msg)
            return ApproveResult(True, msg)

        if kind == "request_read":
            guard = self.guard()
            if not guard:
                return ApproveResult(False, "작업 폴더를 먼저 정해 주세요.")
            accepted, refused = [], []
            for rel in payload["paths"]:
                try:
                    accepted.append(read_document(guard, rel).rel_path)
                except DocumentError as exc:
                    refused.append(f"{rel}({exc.message})")
                    self.db.log("blocked", f"읽기 요청 거절: {rel} — {exc.message}",
                                {"path": rel, "code": exc.code}, conv_id)
            if accepted:
                conv = self.db.get_conversation(conv_id)
                self.db.set_attachments(conv_id, [*conv["attachments"], *accepted])
            msg = "첨부함: " + (", ".join(accepted) or "없음")
            if refused:
                msg += " / 거절: " + ", ".join(refused)
            self.db.resolve_proposal(proposal_id, "applied" if accepted else "failed", msg)
            self.db.log("read_approved", f"문서 읽기 허락: {msg}", {"accepted": accepted}, conv_id)
            return ApproveResult(bool(accepted), msg, followup=bool(accepted))

        if kind == "add_memory":
            self.db.add_memory(payload["text"], source="ai")
            msg = f"기억에 남김: {payload['text'][:60]}"
        elif kind == "add_event":
            self.db.add_event(payload["title"], payload["date"], payload.get("time", ""),
                              payload.get("kind", ""), payload.get("note", ""))
            msg = f"일정 추가: {payload['date']} {payload['title']}"
        elif kind == "add_todo":
            self.db.add_todo(payload["title"], payload.get("due", ""), payload.get("note", ""))
            msg = f"할 일 추가: {payload['title']}"
        else:
            self.db.resolve_proposal(proposal_id, "failed", "알 수 없는 제안")
            return ApproveResult(False, "알 수 없는 제안입니다.")
        self.db.resolve_proposal(proposal_id, "applied", msg)
        self.db.log("record", msg, {"type": kind}, conv_id)
        return ApproveResult(True, msg)

    def reject(self, proposal_id: int) -> None:
        prop = self.db.get_proposal(proposal_id)
        if prop and prop["status"] == "pending":
            self.db.resolve_proposal(proposal_id, "rejected", "사용자가 거절함")
            self.db.log("rejected", f"제안 거절: {describe(prop['payload'])}", {"proposal_id": proposal_id},
                        prop["conversation_id"])
