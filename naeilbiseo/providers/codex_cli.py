"""Codex CLI 연결 — 실험적(이 프로젝트에서 실제 CLI 로 검증하지 못함).

공식 문서: https://developers.openai.com/codex/non-interactive-mode  (codex exec)
이 파일은 공식 문서의 요약(검색 결과)과 공개된 사용법을 바탕으로 썼다. 개발 환경에서 문서
원문 페이지를 열지 못했고 Codex CLI 도 설치되어 있지 않아 실제 동작은 확인하지 못했다.

제한의 한계(중요)
  * `--sandbox read-only` 로 파일 쓰기와 네트워크 명령을 막는다.
  * 그러나 Codex 는 '명령 실행 도구' 자체를 끄는 옵션이 없고, 읽기 전용 샌드박스는
    폴더 밖 파일 '읽기'까지 막지는 않는다. 즉 앱이 '작업 폴더 밖을 못 읽는다'고 보장할 수 없다.
  그래서 설정에서 사용자가 이 한계를 확인하고 켠 경우에만 쓸 수 있게 한다.
"""
from __future__ import annotations

import json

from .base import ChatRequest, CliProvider, ErrorKind, OnText, ProviderError, ProviderStatus, RunState, classify_failure


class CodexCliProvider(CliProvider):
    id = "codex"
    name = "Codex CLI"
    vendor = "OpenAI"
    experimental = True
    executable_names = ("codex",)
    docs_url = "https://developers.openai.com/codex/non-interactive-mode"
    install_hint = "공식 안내대로 Codex CLI 를 설치해 주세요. 예: npm install -g @openai/codex"
    login_hint = "터미널에서 `codex login` 을 실행해 본인 계정으로 로그인해 주세요."
    terms_note = ("Codex CLI 사용 가능 여부와 한도는 ChatGPT 요금제·OpenAI 약관에 따릅니다. "
                  "내일비서가 무료·무제한 사용을 보장하지 않습니다.")

    def status(self) -> ProviderStatus:
        exe = self.find_executable()
        st = ProviderStatus(self.id, self.name, installed=bool(exe), executable=exe or "")
        st.warnings.append("실험적 연결: 이 프로젝트에서 실제 Codex CLI 로 검증되지 않았습니다.")
        st.warnings.append("Codex 는 명령 실행 도구를 끌 수 없고, 읽기 전용 샌드박스는 폴더 밖 '읽기'를 막지 못합니다.")
        if not exe:
            st.detail = self.install_hint
            return st
        code, out, err = self.capture([exe, "--version"])
        if code != 0:
            st.installed = False
            st.detail = f"버전 확인에 실패했습니다: {(err or out).strip()[:200]}"
            return st
        st.version = out.strip().splitlines()[0] if out.strip() else ""
        st.restrictions.append("읽기 전용 샌드박스(--sandbox read-only) — 파일 쓰기·네트워크 명령 차단")
        st.restrictions.append("빈 폴더에서 실행")
        code, out, err = self.capture([exe, "login", "status"])
        text = (out + err).lower()
        if code == 0 and "not logged in" not in text:
            st.logged_in = True
        elif "not logged in" in text or code != 0:
            st.logged_in = False
        st.usable = st.logged_in is not False
        st.detail = "설치됨" + (" · 로그인됨" if st.logged_in else f" · {self.login_hint}")
        return st

    def build_command(self, exe: str, request: ChatRequest, workdir: str) -> tuple[list[str], str]:
        help_text = self.help_text(exe, "exec")
        args = [exe, "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check"]
        if "--ephemeral" in help_text:
            args.append("--ephemeral")
        args.append("-")   # 프롬프트는 stdin 으로
        stdin_text = f"[비서 지침 — 반드시 따를 것]\n{request.system}\n\n" \
                     "명령을 실행하거나 파일을 열지 말고, 아래에 주어진 자료만으로 답하세요.\n\n" + request.prompt
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
        item = data.get("item") or {}
        item_type = item.get("type") or item.get("item_type") or ""
        if kind == "item.completed" and item_type in ("agent_message", "assistant_message"):
            text = item.get("text") or ""
            if text:
                if state.chunks:
                    state.chunks.append("\n\n")
                    on_text("\n\n")
                state.chunks.append(text)
                on_text(text)
        elif kind in ("item.started", "item.completed") and item_type in (
                "command_execution", "file_change", "mcp_tool_call", "web_search"):
            used = state.meta.setdefault("tools_used", [])
            label = f"{item_type}: {str(item.get('command') or item.get('query') or '')[:120]}"
            if label not in used:
                used.append(label)
        elif kind in ("turn.failed", "error"):
            message = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else None
            raw = str(message or data.get("message") or "알 수 없는 오류")
            err_kind = classify_failure(raw)
            state.error = ProviderError(err_kind, self.failure_message(err_kind, raw), raw[:1500])
