"""모의 연결 — 실제 AI 가 아니다.

AI 를 설치·로그인하기 전에 화면과 승인 흐름을 연습해 보는 용도다. 답은 미리 정해 둔 글이며
외부로 아무것도 보내지 않는다. 모든 답에 '모의 응답'이라고 분명히 표시한다.
"""
from __future__ import annotations

import json
import re
import threading
import time

from ..actions import BLOCK_TAG
from .base import ChatRequest, ErrorKind, OnText, Provider, ProviderError, ProviderStatus, RunResult

MOCK_BANNER = "【모의 응답 — 실제 AI 가 쓴 글이 아닙니다】"


class MockProvider(Provider):
    id = "mock"
    name = "모의 모드"
    vendor = "없음(외부로 보내지 않음)"
    is_mock = True
    install_hint = ""
    login_hint = ""
    terms_note = "모의 모드는 연습용입니다. 실제 AI 답변이 아니며 외부로 자료를 보내지 않습니다."

    def __init__(self, chunk_delay: float = 0.02):
        self.chunk_delay = chunk_delay

    def status(self) -> ProviderStatus:
        return ProviderStatus(self.id, self.name, installed=True, version="내장", logged_in=True,
                              detail="연습용 모의 응답입니다. 실제 AI 연결이 아닙니다.", usable=True,
                              restrictions=["외부로 아무것도 보내지 않음"])

    @staticmethod
    def _question(prompt: str) -> str:
        marker = "[사용자 요청]"
        return prompt.rsplit(marker, 1)[-1].strip() if marker in prompt else prompt.strip()

    def compose(self, request: ChatRequest) -> str:
        question = self._question(request.prompt)
        attached = re.findall(r"\[첨부 문서 \d+: (.+?) · ", request.prompt)
        lines = [MOCK_BANNER, "",
                 f"**결론** 받은 요청은 「{question[:60]}」 입니다. 모의 모드라서 내용을 실제로 판단하지는 않았습니다.", ""]
        if attached:
            lines += ["**읽은 자료** " + ", ".join(f"`{p}`" for p in attached), ""]
        lines += ["**다음 할 일**", "1. 설정 → AI 연결에서 실제 AI(Claude Code)를 연결합니다.",
                  "2. 같은 질문을 다시 보내 실제 답을 받습니다.", ""]
        actions = []
        if any(word in question for word in ("만들어", "저장", "써 줘", "써줘", "작성")):
            actions.append({"type": "write_file", "path": "모의_연습/모의_초안.md",
                            "content": f"# 모의 초안\n\n{MOCK_BANNER}\n\n요청: {question}\n\n"
                                       "이 파일은 승인 흐름을 연습하기 위한 것입니다.\n"})
            lines.append("파일 저장을 **제안**했습니다. 아래 「승인 대기」에서 내용을 확인하고 승인해 주세요.")
        if "기억" in question:
            actions.append({"type": "add_memory", "text": f"(모의) {question[:100]}"})
        if actions:
            lines += ["", f"```{BLOCK_TAG}", json.dumps({"actions": actions}, ensure_ascii=False), "```"]
        return "\n".join(lines)

    def run(self, request: ChatRequest, on_text: OnText, cancel: threading.Event) -> RunResult:
        started = time.monotonic()
        text = self.compose(request)
        deadline = started + request.timeout_sec
        for piece in re.findall(r"\S+\s*|\s+", text):
            if cancel.is_set():
                raise ProviderError(ErrorKind.CANCELLED, "요청을 멈췄습니다.")
            if time.monotonic() > deadline:
                raise ProviderError(ErrorKind.TIMEOUT, "제한 시간 안에 답이 오지 않아 멈췄습니다.")
            on_text(piece)
            if self.chunk_delay:
                time.sleep(self.chunk_delay)
        return RunResult(text=text, provider_id=self.id, provider_name=self.name, is_mock=True,
                         duration_sec=time.monotonic() - started, meta={"mock": True})
