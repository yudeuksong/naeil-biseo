"""Gemini CLI 연결 — 실험적(이 프로젝트에서 실제 CLI 로 검증하지 못함).

공식 문서
  * 인증: https://geminicli.com/docs/get-started/authentication/
  * 헤드리스: https://geminicli.com/docs/cli/headless/  (--output-format stream-json)
문서 내용대로 썼지만 Gemini CLI 가 개발 환경에 없어 실제 동작은 확인하지 못했다.

인증(공식 문서 기준)
  * 헤드리스 실행은 '이미 로그인해 저장된 인증'이 있으면 그것을 쓴다. 없으면 GEMINI_API_KEY 나
    Vertex AI 환경 변수가 필요하다. 로그인은 사용자가 터미널에서 `gemini` 를 실행해
    "Sign in with Google" 을 고르는 공식 흐름으로만 한다. 앱은 인증 파일을 읽지 않는다.
  * 로그인 상태를 묻는 공식 명령이 없어 '확인 불가'로 표시한다.

제한의 한계(중요)
  * 승인 모드는 기본값(default)이라 헤드리스에서는 확인이 필요한 도구(파일 쓰기·명령 실행)가
    실행되지 않는다. 다만 읽기·검색 계열 도구까지 끄는 것은 이 프로젝트에서 확인하지 못했다.
  * 빈 폴더에서 실행해 작업 폴더를 CLI 의 작업 공간으로 주지 않는다.
"""
from __future__ import annotations

import json

from .base import ChatRequest, CliProvider, ErrorKind, OnText, ProviderError, ProviderStatus, RunState, classify_failure


class GeminiCliProvider(CliProvider):
    id = "gemini"
    name = "Gemini CLI"
    vendor = "Google"
    experimental = True
    executable_names = ("gemini",)
    docs_url = "https://geminicli.com/docs/get-started/authentication/"
    install_hint = "공식 안내대로 Gemini CLI 를 설치해 주세요. 예: npm install -g @google/gemini-cli"
    login_hint = "터미널에서 `gemini` 를 한 번 실행해 「Sign in with Google」로 로그인해 주세요."
    terms_note = ("인증 방식에 따라 한도·요금·약관·개인정보 고지가 달라집니다(Google 공식 문서 참고). "
                  "내일비서가 무료·무제한 사용을 보장하지 않습니다.")

    def status(self) -> ProviderStatus:
        exe = self.find_executable()
        st = ProviderStatus(self.id, self.name, installed=bool(exe), executable=exe or "")
        st.warnings.append("실험적 연결: 이 프로젝트에서 실제 Gemini CLI 로 검증되지 않았습니다.")
        st.warnings.append("읽기·검색 계열 도구까지 꺼지는지는 확인하지 못했습니다.")
        if not exe:
            st.detail = self.install_hint
            return st
        code, out, err = self.capture([exe, "--version"])
        if code != 0:
            st.installed = False
            st.detail = f"버전 확인에 실패했습니다: {(err or out).strip()[:200]}"
            return st
        st.version = out.strip().splitlines()[0] if out.strip() else ""
        st.logged_in = None
        st.usable = True
        st.restrictions.append("승인 모드 기본값 — 헤드리스에서는 승인이 필요한 도구가 실행되지 않음")
        st.restrictions.append("빈 폴더에서 실행")
        st.detail = "설치됨 · 로그인 상태는 확인할 공식 명령이 없어 대화를 보내 봐야 압니다."
        return st

    def build_command(self, exe: str, request: ChatRequest, workdir: str) -> tuple[list[str], str]:
        args = [exe, "--output-format", "stream-json", "--approval-mode", "default"]
        stdin_text = f"[비서 지침 — 반드시 따를 것]\n{request.system}\n\n" \
                     "도구를 쓰지 말고, 아래에 주어진 자료만으로 답하세요.\n\n" + request.prompt
        return args, stdin_text

    def handle_line(self, line: str, state: RunState, on_text: OnText) -> None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            if len(state.stray) < 20:
                state.stray.append(line[:300])
            return
        if not isinstance(data, dict):
            return
        kind = data.get("type", "")
        if kind == "init":
            state.meta["model"] = data.get("model", "")
        elif kind == "message" and data.get("role") in ("assistant", "model"):
            text = data.get("content")
            if isinstance(text, str) and text:
                state.chunks.append(text)
                on_text(text)
        elif kind == "tool_use":
            used = state.meta.setdefault("tools_used", [])
            label = str(data.get("tool_name") or data.get("name") or "tool")[:120]
            if label not in used:
                used.append(label)
        elif kind == "result":
            status = str(data.get("status", "")).lower()
            if status and status not in ("success", "ok"):
                raw = json.dumps(data.get("error") or data, ensure_ascii=False)[:1500]
                err_kind = classify_failure(raw)
                state.error = ProviderError(err_kind, self.failure_message(err_kind, raw), raw)

    def finish(self, state: RunState, returncode: int, stderr: str) -> None:
        if returncode == 42 and not state.error:
            raise ProviderError(ErrorKind.CLI_ERROR, "Gemini CLI 가 입력 오류(종료 코드 42)를 알렸습니다.", stderr[-1500:])
        if returncode == 53 and not state.error:
            raise ProviderError(ErrorKind.CLI_ERROR, "Gemini CLI 가 턴 한도 초과(종료 코드 53)를 알렸습니다.", stderr[-1500:])
        super().finish(state, returncode, stderr)
