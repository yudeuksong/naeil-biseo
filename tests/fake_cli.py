"""테스트용 가짜 CLI — 실제 AI 가 아니다.

Claude Code CLI 의 헤드리스 출력(stream-json) 모양만 흉내 낸다. 받은 인자·표준 입력·실행 폴더를
FAKE_CLI_RECORD 파일에 적어 두어, 테스트가 '앱이 CLI 를 어떻게 불렀는지' 확인할 수 있게 한다.
동작은 FAKE_CLI_MODE 환경 변수로 고른다.
"""
import json
import os
import sys
import time

for _stream in (sys.stdout, sys.stderr):      # Windows 파이프의 기본 인코딩(코드 페이지)에 기대지 않는다
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

MODE = os.environ.get("FAKE_CLI_MODE", "ok")
RECORD = os.environ.get("FAKE_CLI_RECORD", "")

HELP = """Usage: claude [options]
  -p, --print
  --output-format <format>
  --include-partial-messages
  --tools <tools...>
  --strict-mcp-config
  --disable-slash-commands
  --no-session-persistence
  --permission-mode <mode>  (choices: "manual", "dontAsk")
  --permission-prompts <target>
  --safe-mode
  --system-prompt[-file]
  --model <model>
"""
HELP_OLD = """Usage: claude [options]
  -p, --print
  --output-format <format>
"""


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    args = sys.argv[1:]
    if args == ["--version"]:
        print("9.9.9 (Fake Claude Code)")
        return 0
    if "--help" in args:
        print(HELP_OLD if MODE == "old_version" else HELP)
        return 0
    if args[:2] == ["auth", "status"]:
        logged_in = MODE != "not_logged_in"
        print(json.dumps({"loggedIn": logged_in, "authMethod": "test", "email": "should-not-be-used@example.com"}))
        return 0 if logged_in else 1

    stdin_text = sys.stdin.buffer.read().decode("utf-8", "replace")
    system_text = ""
    if "--system-prompt-file" in args:
        name = args[args.index("--system-prompt-file") + 1]
        with open(name, encoding="utf-8") as fh:
            system_text = fh.read()
    if RECORD:
        with open(RECORD, "w", encoding="utf-8") as fh:
            json.dump({"argv": args, "stdin": stdin_text, "system": system_text, "cwd": os.getcwd(),
                       "cwd_files": sorted(os.listdir("."))}, fh, ensure_ascii=False)

    if MODE == "bad_flag":
        sys.stderr.write("error: unknown option '--tools'\n")
        return 1
    tools = ["Bash", "Read", "Write"] if MODE == "unsafe_tools" else []
    emit({"type": "system", "subtype": "init", "tools": tools, "mcp_servers": [], "model": "fake-model",
          "claude_code_version": "9.9.9"})
    if MODE == "unsafe_tools":
        time.sleep(30)   # 앱이 즉시 멈춰야 한다
        return 0
    if MODE == "hang":
        time.sleep(60)
        return 0
    if MODE == "not_logged_in":
        emit({"type": "result", "subtype": "success", "is_error": True, "api_error_status": 401,
              "result": "Not logged in · Please run /login"})
        return 1
    if MODE == "usage_limit":
        emit({"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429,
              "result": "Claude usage limit reached. Your limit will reset later."})
        return 1
    if MODE == "tool_use":
        emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}})
        time.sleep(30)
        return 0

    saw_doc = "⟦문서시작" in stdin_text
    reply = os.environ.get("FAKE_CLI_REPLY")
    if reply is None:
        reply = "결론부터 말씀드립니다. " + ("첨부 문서를 읽었습니다. " if saw_doc else "첨부 문서가 없습니다. ") + "끝."
    pieces = [reply[i:i + 7] for i in range(0, len(reply), 7)]
    for piece in pieces:
        emit({"type": "stream_event", "event": {"type": "content_block_delta",
                                               "delta": {"type": "text_delta", "text": piece}}})
        if MODE == "slow":
            time.sleep(0.05)
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": reply, "duration_ms": 12,
          "num_turns": 1, "permission_denials": []})
    return 0


if __name__ == "__main__":
    sys.exit(main())
