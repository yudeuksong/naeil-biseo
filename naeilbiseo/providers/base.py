"""AI 연결 공통 틀(Provider).

모든 AI 연결은 같은 모양을 따른다.
  status()  설치·로그인 상태 확인 (공식 CLI 의 공식 명령만 사용)
  run()     한 번 묻고 답을 스트리밍으로 받기 (취소·제한 시간·오류 분류 포함)

CLI 는 항상 인자 '목록'으로 실행한다(shell=True 를 쓰지 않는다). 사용자가 쓴 글과 문서는
명령 인자가 아니라 표준 입력(stdin)으로만 보낸다. 앱은 CLI 의 로그인 파일·토큰을 읽지 않는다.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .. import config


class ErrorKind(str, Enum):
    NOT_INSTALLED = "not_installed"
    NOT_LOGGED_IN = "not_logged_in"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    USAGE_LIMIT = "usage_limit"
    UNSAFE_CONFIG = "unsafe_config"
    CLI_ERROR = "cli_error"
    BAD_OUTPUT = "bad_output"
    PROMPT_TOO_LARGE = "prompt_too_large"


class ProviderError(Exception):
    def __init__(self, kind: ErrorKind, message: str, detail: str = ""):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.detail = detail


@dataclass
class ProviderStatus:
    provider_id: str
    name: str
    installed: bool
    version: str = ""
    logged_in: bool | None = None       # None = 확인할 방법이 없거나 확인 실패
    executable: str = ""
    detail: str = ""
    restrictions: list[str] = field(default_factory=list)   # 앱이 CLI 에 실제로 건 제한
    warnings: list[str] = field(default_factory=list)       # 앱이 강제하지 못하는 부분
    usable: bool = False                # 지금 대화에 쓸 수 있는가

    @property
    def summary(self) -> str:
        if not self.installed:
            return "설치되지 않음"
        if self.logged_in is False:
            return "로그인 필요"
        if not self.usable:
            return "사용할 수 없음"
        if self.logged_in is None:
            return "설치됨 · 로그인 상태 확인 불가"
        return "연결됨"


@dataclass
class ChatRequest:
    system: str
    prompt: str
    timeout_sec: float = config.DEFAULT_TIMEOUT_SEC
    model: str = ""


@dataclass
class RunResult:
    text: str
    provider_id: str
    provider_name: str
    is_mock: bool
    duration_sec: float
    meta: dict = field(default_factory=dict)


OnText = Callable[[str], None]


class Provider(ABC):
    id: str = ""
    name: str = ""
    vendor: str = ""                 # 자료를 받는 회사(화면 표시에 사용)
    is_mock: bool = False
    experimental: bool = False       # 실제 CLI 로 검증되지 않은 연결
    install_hint: str = ""
    login_hint: str = ""
    docs_url: str = ""
    terms_note: str = ""

    @abstractmethod
    def status(self) -> ProviderStatus: ...

    @abstractmethod
    def run(self, request: ChatRequest, on_text: OnText, cancel: threading.Event) -> RunResult: ...


# ─────────────────────────────────────────────────────────────────────
#  CLI 를 부르는 연결의 공통 부분
# ─────────────────────────────────────────────────────────────────────
@dataclass
class RunState:
    chunks: list[str] = field(default_factory=list)
    final_text: str | None = None
    error: ProviderError | None = None      # 실행이 끝난 뒤 알릴 오류
    abort: ProviderError | None = None      # 즉시 프로세스를 멈춰야 하는 오류
    meta: dict = field(default_factory=dict)
    stray: list[str] = field(default_factory=list)   # 해석하지 못한 출력(진단용, 일부만)

    def text(self) -> str:
        return self.final_text if self.final_text is not None else "".join(self.chunks)


def classify_failure(text: str, status_code: int | None = None) -> ErrorKind:
    """CLI 가 알려 준 실패 글로 오류 종류를 가린다."""
    low = (text or "").lower()
    login_marks = ("not logged in", "please run /login", "/login", "invalid api key", "authentication_error",
                   "authentication failed", "authentication_failed", "unauthorized", "oauth token",
                   "log in", "login required", "not authenticated", "sign in", "no credentials",
                   "please login", "expired token", "token has expired")
    limit_marks = ("usage limit", "rate limit", "rate_limit", "limit reached", "quota", "out of credits",
                   "credit balance", "too many requests", "billing", "resource_exhausted", "overloaded")
    if status_code in (401, 403) or any(m in low for m in login_marks):
        return ErrorKind.NOT_LOGGED_IN
    if status_code == 429 or any(m in low for m in limit_marks):
        return ErrorKind.USAGE_LIMIT
    return ErrorKind.CLI_ERROR


def _popen_platform_kwargs() -> dict:
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": flags}
    return {"start_new_session": True}


def kill_process_tree(proc: subprocess.Popen) -> None:
    """CLI 와 그 자식 프로세스까지 멈춘다."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass


class CliProvider(Provider):
    """공식 CLI 를 하위 프로세스로 부르는 연결의 공통 구현."""

    executable_names: tuple[str, ...] = ()
    executable_override: str = ""           # 설정에서 직접 지정한 실행 파일 경로

    def __init__(self, executable_override: str = ""):
        self.executable_override = executable_override.strip()
        self._help_cache: dict[tuple[str, ...], str] = {}

    # ── 실행 파일 찾기 ────────────────────────────────────────────
    def extra_search_dirs(self) -> list[str]:
        dirs: list[str] = []
        home = os.path.expanduser("~")
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            if appdata:
                dirs.append(os.path.join(appdata, "npm"))
            dirs.append(os.path.join(home, ".local", "bin"))
        else:
            dirs += [os.path.join(home, ".local", "bin"), os.path.join(home, ".npm-global", "bin"),
                     "/usr/local/bin", "/opt/homebrew/bin"]
        return dirs

    def find_executable(self) -> str | None:
        if self.executable_override:
            return self.executable_override if os.path.isfile(self.executable_override) else None
        for name in self.executable_names:
            found = shutil.which(name)
            if found:
                return found
        extra = os.pathsep.join(d for d in self.extra_search_dirs() if os.path.isdir(d))
        if extra:
            for name in self.executable_names:
                found = shutil.which(name, path=extra)
                if found:
                    return found
        return None

    # ── 짧은 확인 명령(버전·도움말·로그인 상태) ───────────────────
    def capture(self, args: list[str], timeout: float = 25.0) -> tuple[int, str, str]:
        try:
            done = subprocess.run(args, capture_output=True, timeout=timeout, shell=False,
                                  stdin=subprocess.DEVNULL, cwd=str(config.cli_scratch_dir()),
                                  **_popen_platform_kwargs())
        except FileNotFoundError:
            return 127, "", "실행 파일을 찾을 수 없습니다."
        except subprocess.TimeoutExpired:
            return 124, "", "확인 명령이 제한 시간 안에 끝나지 않았습니다."
        except OSError as exc:
            return 126, "", str(exc)
        return (done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace"))

    def help_text(self, exe: str, *sub: str) -> str:
        key = (exe, *sub)
        if key not in self._help_cache:
            code, out, err = self.capture([exe, *sub, "--help"])
            self._help_cache[key] = (out + "\n" + err) if code in (0, 1) else ""
        return self._help_cache[key]

    # ── 하위 클래스가 채우는 부분 ────────────────────────────────
    @abstractmethod
    def build_command(self, exe: str, request: ChatRequest, workdir: str) -> tuple[list[str], str]:
        """(인자 목록, stdin 으로 보낼 글)."""

    @abstractmethod
    def handle_line(self, line: str, state: RunState, on_text: OnText) -> None: ...

    def finish(self, state: RunState, returncode: int, stderr: str) -> None:
        """실행이 끝난 뒤 state 를 보고 오류면 ProviderError 를 던진다."""
        if state.error:
            raise state.error
        if state.text().strip():
            return
        tail = (stderr.strip() or "\n".join(state.stray))[-1500:]
        if returncode != 0:
            kind = classify_failure(tail)
            raise ProviderError(kind, self.failure_message(kind, tail), tail)
        raise ProviderError(ErrorKind.BAD_OUTPUT, "AI 가 빈 답을 돌려주었습니다. 다시 시도해 주세요.", tail)

    def failure_message(self, kind: ErrorKind, raw: str) -> str:
        if kind == ErrorKind.NOT_LOGGED_IN:
            return f"{self.name} 에 로그인되어 있지 않습니다. {self.login_hint}"
        if kind == ErrorKind.USAGE_LIMIT:
            return (f"{self.name} 의 사용 한도·요금 문제로 답을 받지 못했습니다. "
                    "한도와 요금제는 해당 AI 회사 화면에서 확인해 주세요.")
        first = raw.strip().splitlines()[-1][:300] if raw.strip() else "알 수 없는 오류"
        return f"{self.name} 실행 중 오류가 났습니다: {first}"

    def build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.setdefault("NO_COLOR", "1")
        return env

    # ── 실행 ─────────────────────────────────────────────────────
    def run(self, request: ChatRequest, on_text: OnText, cancel: threading.Event) -> RunResult:
        exe = self.find_executable()
        if not exe:
            raise ProviderError(ErrorKind.NOT_INSTALLED,
                                f"{self.name} 가 이 컴퓨터에 설치되어 있지 않습니다. {self.install_hint}")
        if len((request.system + request.prompt).encode("utf-8")) > config.MAX_PROMPT_BYTES:
            raise ProviderError(ErrorKind.PROMPT_TOO_LARGE, "보내려는 자료가 너무 큽니다. 첨부 문서를 줄여 주세요.")
        if cancel.is_set():
            raise ProviderError(ErrorKind.CANCELLED, "요청을 멈췄습니다.")

        workdir = os.path.join(str(config.cli_scratch_dir()), uuid.uuid4().hex)
        os.makedirs(workdir, exist_ok=False)
        started = time.monotonic()
        state = RunState()
        stop_reason: list[str] = []
        stderr_chunks: list[bytes] = []
        proc: subprocess.Popen | None = None
        try:
            args, stdin_text = self.build_command(exe, request, workdir)
            try:
                proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, cwd=workdir, shell=False,
                                        env=self.build_env(), **_popen_platform_kwargs())
            except FileNotFoundError as exc:
                raise ProviderError(ErrorKind.NOT_INSTALLED,
                                    f"{self.name} 실행 파일을 찾을 수 없습니다. {self.install_hint}") from exc
            except OSError as exc:
                raise ProviderError(ErrorKind.CLI_ERROR, f"{self.name} 를 실행하지 못했습니다: {exc}") from exc

            finished = threading.Event()
            deadline = started + max(1.0, request.timeout_sec)

            def watchdog() -> None:
                while not finished.is_set():
                    if cancel.is_set():
                        stop_reason.append("cancel")
                        kill_process_tree(proc)
                        return
                    if time.monotonic() > deadline:
                        stop_reason.append("timeout")
                        kill_process_tree(proc)
                        return
                    finished.wait(0.05)

            def feed_stdin() -> None:
                try:
                    proc.stdin.write(stdin_text.encode("utf-8"))
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass

            def drain_stderr() -> None:
                size = 0
                try:
                    for chunk in iter(lambda: proc.stderr.read(4096), b""):
                        if size < 64_000:
                            stderr_chunks.append(chunk)
                            size += len(chunk)
                except (OSError, ValueError):
                    pass

            helpers = [threading.Thread(target=fn, daemon=True) for fn in (watchdog, feed_stdin, drain_stderr)]
            for t in helpers:
                t.start()
            try:
                for raw in iter(proc.stdout.readline, b""):
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    self.handle_line(line, state, on_text)
                    if state.abort:
                        stop_reason.append("abort")
                        kill_process_tree(proc)
                        break
                proc.wait()
            finally:
                finished.set()
                kill_process_tree(proc)
                for t in helpers:
                    t.join(timeout=5)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        if "cancel" in stop_reason:
            raise ProviderError(ErrorKind.CANCELLED, "요청을 멈췄습니다.")
        if "timeout" in stop_reason:
            raise ProviderError(ErrorKind.TIMEOUT,
                                f"{int(request.timeout_sec)}초 안에 답이 오지 않아 멈췄습니다. 다시 시도해 주세요.")
        if state.abort:
            raise state.abort
        self.finish(state, proc.returncode or 0, b"".join(stderr_chunks).decode("utf-8", "replace"))
        return RunResult(text=state.text(), provider_id=self.id, provider_name=self.name, is_mock=False,
                         duration_sec=time.monotonic() - started, meta=state.meta)
