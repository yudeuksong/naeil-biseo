"""Claude Code CLI 연결 (첫 번째 실제 연결 대상).

공식 문서: https://code.claude.com/docs/en/headless  (claude -p, stream-json)

안전 설계
  * `--tools ""` 로 내장 도구(파일 읽기·쓰기·명령 실행·웹)를 모두 끈다.
  * `--strict-mcp-config`, `--disable-slash-commands`, `--safe-mode`,
    `--permission-mode dontAsk`, `--permission-prompts none` 을 지원하는 버전이면 함께 건다.
  * 작업 폴더가 아닌 '빈 폴더'에서 실행한다.
  * 실행 직후 CLI 가 알려 주는 초기 정보(system/init)의 tools·mcp_servers 가 비어 있는지
    앱이 직접 확인하고, 비어 있지 않으면 즉시 프로세스를 멈춘다(옵션이 먹지 않은 경우 대비).
  * `--bare` 는 쓰지 않는다. 공식 문서상 bare 모드는 구독 로그인(OAuth)을 읽지 않기 때문이다.
"""
from __future__ import annotations

import json
import os
import re

from .base import ChatRequest, CliProvider, ErrorKind, OnText, ProviderError, ProviderStatus, RunState, classify_failure

_MODEL_RE = re.compile(r"^[A-Za-z0-9._\-\[\]]{1,64}$")
SYSTEM_PROMPT_FILE = "system_prompt.txt"


class ClaudeCliProvider(CliProvider):
    id = "claude"
    name = "Claude Code"
    vendor = "Anthropic"
    executable_names = ("claude",)
    docs_url = "https://code.claude.com/docs/en/setup"
    install_hint = ("공식 안내(code.claude.com/docs/en/setup)대로 Claude Code 를 설치해 주세요. "
                    "예: npm install -g @anthropic-ai/claude-code")
    login_hint = "터미널에서 `claude auth login` 을 실행해 본인 계정으로 로그인해 주세요."
    terms_note = ("Claude Code 를 쓰려면 Claude Code 가 포함된 Anthropic 요금제(또는 API 결제)가 필요합니다. "
                  "사용 한도·요금·약관은 Anthropic 기준을 따르며, 내일비서가 무료·무제한 사용을 보장하지 않습니다.")

    # ── 이 버전이 지원하는 옵션 확인 ──────────────────────────────
    def capabilities(self, exe: str) -> dict[str, bool]:
        text = self.help_text(exe)
        return {
            "tools": "--tools" in text,
            "strict_mcp": "--strict-mcp-config" in text,
            "no_slash": "--disable-slash-commands" in text,
            "no_persist": "--no-session-persistence" in text,
            "dont_ask": "dontAsk" in text,
            "no_prompts": "--permission-prompts" in text,
            "safe_mode": "--safe-mode" in text,
            "system_file": ("--system-prompt-file" in text) or ("system-prompt[-file]" in text),
            "partial": "--include-partial-messages" in text,
        }

    def status(self) -> ProviderStatus:
        exe = self.find_executable()
        st = ProviderStatus(self.id, self.name, installed=bool(exe), executable=exe or "")
        if not exe:
            st.detail = self.install_hint
            return st
        code, out, err = self.capture([exe, "--version"])
        if code != 0:
            st.installed = False
            st.detail = f"실행 파일은 있지만 버전 확인에 실패했습니다: {(err or out).strip()[:200]}"
            return st
        st.version = out.strip().splitlines()[0] if out.strip() else ""

        caps = self.capabilities(exe)
        if not caps["tools"]:
            st.detail = ("이 버전의 Claude Code 는 도구를 끄는 옵션(--tools)을 지원하지 않아 안전하게 쓸 수 없습니다. "
                         "Claude Code 를 최신 버전으로 올려 주세요.")
            st.warnings.append("도구 차단 옵션 미지원 — 사용 불가")
            return st

        st.restrictions.append("내장 도구 전부 끔(--tools \"\") — 파일 읽기·쓰기·명령 실행·웹 접근 없음")
        st.restrictions.append("빈 폴더에서 실행 — 작업 폴더를 CLI 에 직접 열어 주지 않음")
        st.restrictions.append("시작 정보의 도구·MCP 목록이 비어 있는지 매번 검사, 아니면 즉시 중단")
        if caps["strict_mcp"]:
            st.restrictions.append("MCP 서버 연결 안 함(--strict-mcp-config)")
        else:
            st.warnings.append("이 버전은 --strict-mcp-config 를 지원하지 않습니다(시작 정보 검사로 대신 막습니다).")
        if caps["safe_mode"]:
            st.restrictions.append("개인 설정·훅·플러그인·CLAUDE.md 불러오지 않음(--safe-mode)")
        else:
            st.warnings.append("이 버전은 --safe-mode 를 지원하지 않아 개인 설정(훅 등)이 함께 불릴 수 있습니다.")
        if caps["dont_ask"]:
            st.restrictions.append("허락이 필요한 동작은 모두 거절(--permission-mode dontAsk)")

        # 로그인 상태: 공식 명령만 사용. 계정 정보(이메일 등)는 읽어도 저장·표시하지 않는다.
        code, out, _err = self.capture([exe, "auth", "status", "--json"])
        try:
            data = json.loads(out)
            if isinstance(data, dict) and isinstance(data.get("loggedIn"), bool):
                st.logged_in = data["loggedIn"]
        except (json.JSONDecodeError, ValueError):
            st.logged_in = None
        if st.logged_in is False:
            st.detail = self.login_hint
        elif st.logged_in is None:
            st.detail = "로그인 상태를 확인하지 못했습니다. 대화를 보내 보면 알 수 있습니다."
            st.usable = True
        else:
            st.detail = "설치와 로그인이 확인되었습니다."
            st.usable = True
        return st

    # ── 실행 ─────────────────────────────────────────────────────
    def build_command(self, exe: str, request: ChatRequest, workdir: str) -> tuple[list[str], str]:
        caps = self.capabilities(exe)
        if not caps["tools"]:
            raise ProviderError(ErrorKind.UNSAFE_CONFIG,
                                "이 버전의 Claude Code 는 도구를 끄는 옵션(--tools)을 지원하지 않아 실행하지 않았습니다. "
                                "Claude Code 를 최신 버전으로 올려 주세요.")
        args = [exe, "-p", "--output-format", "stream-json", "--verbose"]
        if caps["partial"]:
            args.append("--include-partial-messages")
        args += ["--tools", ""]
        if caps["strict_mcp"]:
            args.append("--strict-mcp-config")
        if caps["no_slash"]:
            args.append("--disable-slash-commands")
        if caps["no_persist"]:
            args.append("--no-session-persistence")
        if caps["dont_ask"]:
            args += ["--permission-mode", "dontAsk"]
        if caps["no_prompts"]:
            args += ["--permission-prompts", "none"]
        if caps["safe_mode"]:
            args.append("--safe-mode")
        if request.model:
            if not _MODEL_RE.match(request.model):
                raise ProviderError(ErrorKind.CLI_ERROR, "모델 이름에 쓸 수 없는 글자가 있습니다.")
            args += ["--model", request.model]

        stdin_text = request.prompt
        if caps["system_file"]:
            # 사용자 자료가 명령 인자로 나가지 않도록, 실행 폴더 안의 고정된 이름 파일로 넘긴다.
            with open(os.path.join(workdir, SYSTEM_PROMPT_FILE), "w", encoding="utf-8") as fh:
                fh.write(request.system)
            args += ["--system-prompt-file", SYSTEM_PROMPT_FILE]
        else:
            stdin_text = f"[비서 지침]\n{request.system}\n\n{request.prompt}"
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
        kind, sub = data.get("type"), data.get("subtype")

        if kind == "system" and sub == "init":
            tools = data.get("tools") or []
            servers = data.get("mcp_servers") or []
            state.meta["model"] = data.get("model", "")
            state.meta["cli_version"] = data.get("claude_code_version", "")
            state.meta["tools_at_start"] = list(tools)
            state.meta["init_checked"] = True
            if tools or servers:
                names = ", ".join(str(t) for t in tools[:8]) or ", ".join(str(s.get("name", s)) for s in servers[:8])
                state.abort = ProviderError(
                    ErrorKind.UNSAFE_CONFIG,
                    "Claude Code 가 도구를 켠 채로 시작되어 실행을 즉시 멈췄습니다(안전 설정이 적용되지 않음).",
                    f"켜져 있던 것: {names}")
            return

        if kind == "system" and sub == "api_retry":
            category = str(data.get("error", ""))
            if category in ("authentication_failed", "oauth_org_not_allowed"):
                state.abort = ProviderError(ErrorKind.NOT_LOGGED_IN, self.failure_message(ErrorKind.NOT_LOGGED_IN, ""),
                                            category)
            elif category in ("billing_error", "account_on_hold"):
                state.abort = ProviderError(ErrorKind.USAGE_LIMIT, self.failure_message(ErrorKind.USAGE_LIMIT, ""),
                                            category)
            return

        if kind == "stream_event":
            event = data.get("event") or {}
            if event.get("type") == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    state.chunks.append(delta["text"])
                    state.meta["streamed"] = True
                    on_text(delta["text"])
            return

        if kind == "assistant":
            blocks = (data.get("message") or {}).get("content") or []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    state.abort = ProviderError(
                        ErrorKind.UNSAFE_CONFIG,
                        "Claude Code 가 도구를 쓰려 해서 실행을 즉시 멈췄습니다.", str(block.get("name", "")))
                    return
            if not state.meta.get("streamed"):   # 부분 스트리밍이 없는 버전: 완성된 글을 통째로 받는다
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                        state.chunks.append(block["text"])
                        on_text(block["text"])
            return

        if kind == "result":
            state.meta["duration_ms"] = data.get("duration_ms")
            state.meta["num_turns"] = data.get("num_turns")
            if data.get("permission_denials"):
                state.meta["permission_denials"] = len(data["permission_denials"])
            text = data.get("result")
            if data.get("is_error") or (sub and sub != "success"):
                raw = text if isinstance(text, str) else str(sub or "")
                status_code = data.get("api_error_status")
                err_kind = classify_failure(raw, status_code if isinstance(status_code, int) else None)
                state.error = ProviderError(err_kind, self.failure_message(err_kind, raw), raw[:1500])
            elif isinstance(text, str):
                state.final_text = text
