# 내일비서

내 컴퓨터에서 일하는 **로컬 AI 업무·목회 비서**입니다. 작업 폴더의 문서를 근거로 조언하고,
말씀하시면 파일·일정·할 일·기억을 **제안**하며, 승인하신 것만 실제로 반영합니다.
일반용과 목회자용을 한 프로그램 안에서 바꿔 씁니다. (이름 「내일비서」는 임시 명칭입니다.)

- 언어·화면: 한국어, 큰 글씨(4단계), Windows 우선(Python + PySide6 + SQLite)
- 버전: 0.1.0 (1차 범위 + 브리핑·일지 스케줄러)

---

## 1. 무엇을 참고했고 무엇을 하지 않았나

이 프로그램은 공개된 소개 사이트(`solomon-biz.vercel.app`의 소개·기능·설치·자주 묻는 질문·미리 체험 페이지)에
**적힌 설명만** 읽고, 비슷한 쓰임새를 **처음부터 따로 구현**한 것입니다. 역공학 도구(REA 등)는 쓰지 않았고,
**공개 자료 기반 분석**입니다.

| 구분 | 내용 |
|---|---|
| 공개 페이지가 **주장하는** 기능(참고함) | 작업 폴더·프로필·기억, 일반용 7개/목회자용 6개 주제, 결론부터 답하기, 파일 만들기·고치기, 일정·할 일·D-day, 아침 브리핑·저녁 일지, 작업 과정 보기, AI 고르기(공식 CLI 호출), 팀 모드 등 |
| **확인하지 못한** 것 | 그 프로그램의 내부 소스·실제 동작·보안 수준. 유료 프로그램을 내려받거나 실행해 보지 않았습니다. |
| **가져오지 않은** 것 | 명칭·로고·문구·이미지·소스 코드·이용코드 체계. 이 저장소의 코드·문구·화면은 모두 새로 작성했습니다. |

## 2. 할 수 있는 일 (1차 범위)

| 기능 | 설명 |
|---|---|
| 프로필·작업 폴더 | 판마다 이름·호칭·하는 일·선호를 적고, 일할 자료를 모은 폴더 하나를 고릅니다. |
| 주제별 대화 | 일반용 7개(전체·생활·홍보·고객·돈·문서·AI 활용법), 목회자용 6개(목회 전체·설교 준비·심방·행정·교회 성장·AI 활용법). 대화는 저장되고 다시 열면 이어집니다. |
| 기억 | 직접 보고·고치고·지울 수 있습니다. 항목마다 「AI 로 보내기」를 끌 수 있습니다. |
| 일정·할 일 | 추가·수정·삭제, D-day 표시, 기한 지난 할 일 표시. |
| 문서 | 작업 폴더의 문서 목록과 미리 보기, 대화에 첨부. |
| 파일 만들기·고치기 | AI 가 제안 → 차이(diff) 확인 → 승인 → 저장. `.txt .md .csv` 만. 기존 파일은 백업 후 저장. |
| 작업 로그 | 실제로 읽은 문서, 보낸 곳, 만든·고친 파일, 막은 요청을 앱이 직접 기록합니다. |
| 브리핑·일지 | 켜져 있을 때 정한 시각에 하루 한 번(재시작해도 중복 없음). 기본은 AI 를 쓰지 않는 규칙 요약. |

답변 규칙(시스템 지침): 결론 먼저, 근거 자료 밝히기, 주지 않은 숫자·출처를 지어내지 않고 되묻기,
지어낸 예화에는 「(가상 예화)」 표시, 세금·법률·의료·투자는 일반 안내까지만.
이 규칙은 AI 에게 주는 **지시**이므로 AI 가 어길 수 있습니다. 중요한 내용은 직접 확인해 주세요.

## 3. 실행 방법

### Windows

1. [Python 3.10 이상](https://www.python.org/downloads/)을 설치합니다(설치할 때 "Add python.exe to PATH" 체크).
2. 이 폴더의 `run_windows.bat` 를 두 번 누릅니다. 처음 한 번은 필요한 것을 내려받느라 시간이 걸립니다.

직접 하려면:

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\pythonw run.py
```

### macOS · Linux (개발용)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

처음 켜면 **모의 모드**(실제 AI 아님, 외부 전송 없음)로 시작합니다. 화면 오른쪽 위 상태 단추 또는
⚙ 설정 → 🤖 AI 연결에서 실제 AI 를 고릅니다.

## 4. AI 연결

내일비서는 각 회사의 **공식 CLI 를 이 컴퓨터에서 불러** 씁니다. 설치·로그인은 본인이 공식 방법으로 하고,
내일비서는 로그인 파일·토큰·쿠키를 읽거나 복사하지 않습니다(상태 확인도 공식 명령만 사용).

| 연결 | 상태 | 부르는 방법 | 비고 |
|---|---|---|---|
| **Claude Code** | 실제 CLI 로 검증함(Linux, v2.1.322) | `claude -p --output-format stream-json … --tools ""` | 첫 번째 실제 연결 대상 |
| Codex CLI | **실험적 · 미검증** | `codex exec --json --sandbox read-only --skip-git-repo-check -` | 출력 해석기 단위 테스트만 있음 |
| Gemini CLI | **실험적 · 미검증** | `gemini --output-format stream-json --approval-mode default` | 출력 해석기 단위 테스트만 있음 |
| 모의 모드 | 내장 | — | 연습용. 실제 AI 아님. 모든 답에 「모의 응답」 표시 |

Claude Code 준비(공식 안내: <https://code.claude.com/docs/en/setup>):

```bash
npm install -g @anthropic-ai/claude-code
```

```bash
claude auth login
```

- **요금·한도**: Claude Code 를 쓰려면 Claude Code 가 포함된 Anthropic 요금제(또는 API 결제)가 필요합니다.
  사용 한도·요금·약관은 각 AI 회사 기준이며, 내일비서는 **무료·무제한 사용을 보장하지 않습니다.**
  내일비서에서 쓴 만큼 그 구독의 한도가 줄어듭니다.
- **계정**: 본인 계정으로 본인 컴퓨터에서만 쓰세요. 각 회사 약관은 직접 확인해 주세요.
- 공식 문서상 `claude --bare` 는 구독 로그인(OAuth)을 읽지 않으므로 쓰지 않습니다.
- Codex·Gemini 는 설정에서 한계를 읽고 동의해야 고를 수 있습니다(아래 5-3 참고).

새 AI 를 붙이려면 `naeilbiseo/providers/base.py` 의 `CliProvider` 를 상속해 `status()`, `build_command()`,
`handle_line()` 을 채우고 `providers/__init__.py` 에 등록합니다.

## 5. 안전 설계 — 코드가 강제하는 것과 못 하는 것

### 5-1. 앱 코드가 실제로 강제하는 것

- **작업 폴더 경계**(`security/pathguard.py`): 읽기·쓰기 모두 실제 경로(realpath)를 풀어 폴더 안인지 확인합니다.
  `..`, 절대 경로(`/…`, `C:\…`, `\\서버\…`, `C:상대`, `~`), 심볼릭 링크·정션을 거친 경로, Windows 예약 이름,
  대체 데이터 스트림(`:`)을 거절합니다. 홈 폴더 전체·드라이브 전체는 작업 폴더로 받지 않습니다.
- **민감 파일 제외**(`security/sensitive.py`): `.env`, `credentials*`, `*.pem`/`*.key`, `id_rsa`, `.git/`, `.ssh/`,
  `.claude/` 등은 목록에 잠김으로만 보이고 읽지도 보내지도 고치지도 않습니다.
- **크기·종류 제한**: 읽기 200KB/개·합계 400KB, 쓰기 1MB, 쓰기는 `.txt .md .csv` 만.
- **AI 는 디스크를 직접 못 바꿈**: AI 는 답 끝에 구조화된 제안(JSON)만 붙일 수 있고, 앱이 종류·필드를 검증해
  「승인 대기」에 올립니다. 허용 종류는 `write_file`, `request_read`, `add_memory`, `add_event`, `add_todo` 뿐입니다.
  명령 실행·삭제 같은 종류는 없으며, 들어오면 버리고 로그에 남깁니다.
- **승인·차이·백업**: 파일 제안은 차이를 보여 주고 승인받은 뒤, 실행 직전에 다시 검증합니다. 승인하는 사이 파일이
  바뀌었으면 쓰지 않습니다(충돌). 기존 파일은 `작업폴더/.내일비서_백업/시각/…` 에 원본을 보관한 뒤 저장합니다.
- **Claude Code 도구 차단**: `--tools ""`(내장 도구 전부 끔), `--strict-mcp-config`, `--disable-slash-commands`,
  `--safe-mode`, `--permission-mode dontAsk`, `--permission-prompts none` 을 걸고, 작업 폴더가 아닌 **빈 폴더**에서 실행합니다.
  실행 직후 CLI 가 알려 주는 도구·MCP 목록이 비어 있는지 **매번 검사**해 아니면 즉시 프로세스를 멈춥니다.
  도구 차단 옵션이 없는 옛 버전은 아예 실행하지 않습니다.
- **셸을 거치지 않음**: CLI 는 인자 목록으로 실행하고(`shell=True` 없음), 질문·문서는 명령 인자가 아니라 표준 입력으로만 보냅니다.
- **문서는 자료로만**: 문서·기억은 무작위 경계 표시로 감싼 "자료" 구획에 넣고, 그 안의 지시는 따르지 말라고 지침에 적습니다.
  앱은 **AI 의 답에서만** 제안을 꺼내므로, 문서 안에 제안 구획이 적혀 있어도 실행되지 않습니다.

### 5-2. 강제하지 못하는 것(안전 보장으로 받아들이지 마세요)

- AI 가 문서 속 지시문에 **영향받아 틀린 답이나 엉뚱한 제안**을 할 수는 있습니다. 그래서 모든 변경은 승인을 거칩니다.
  승인 창의 내용을 꼭 읽어 주세요.
- 민감 파일은 **이름**으로 가려냅니다. 평범한 이름의 문서 안에 적힌 비밀번호·개인정보까지는 알아내지 못합니다.
- AI 로 보낸 자료가 그 회사에서 어떻게 다뤄지는지는 그 회사의 약관·개인정보 처리방침을 따릅니다.
- 검사와 쓰기 사이의 아주 짧은 틈에 다른 프로그램이 폴더를 링크로 바꾸는 경우까지 운영체제 수준에서 막지는 못합니다
  (쓰기 직전에 한 번 더 검사하는 것까지 합니다).
- 숫자·출처를 지어내지 말라는 것, 가상 예화 표시는 **AI 에게 준 지시**라서 어길 수 있습니다.

### 5-3. 실험적 연결의 한계

- **Codex CLI**: 명령 실행 도구 자체를 끄는 옵션이 없고, 읽기 전용 샌드박스는 폴더 밖 **읽기**를 막지 못합니다.
- **Gemini CLI**: 승인 모드 기본값에서는 승인이 필요한 도구가 실행되지 않지만, 읽기·검색 계열 도구까지 꺼지는지는 확인하지 못했습니다.
- 두 연결 모두 CLI 가 스스로 도구를 쓰면 작업 로그에 「CLI 도구 사용」으로 남깁니다.

## 6. 어떤 자료가 어디에 있나

| 자료 | 위치 |
|---|---|
| 대화·기억·일정·할 일·작업 로그·브리핑/일지·설정 | 이 컴퓨터의 `naeilbiseo.sqlite3` 한 파일. Windows: `%APPDATA%\NaeilBiseo\` |
| 만든·고친 파일, 백업 | 작업 폴더 안 |
| **AI 로 전송**되는 것 | 질문, 이 대화의 이전 내용, **직접 첨부한 문서의 내용**, (끌 수 있음) 프로필·켜 둔 기억·일정/할 일·문서 **이름** 목록 |

내일비서 자체 서버는 없습니다. 무엇이 전송되는지는 대화 화면 아래에 항상 표시되고, 「보내는 자료 보기」로 전문을 볼 수 있습니다.
`NAEILBISEO_DATA_DIR` 환경 변수로 자료 폴더를 바꿀 수 있습니다.

## 7. 브리핑·일지(자동 작업)

- 내일비서가 **켜져 있을 때만** 돕니다. 정한 시각이 지난 뒤 켜면 그날 몫을 한 번 만듭니다.
- (작업, 현지 날짜)를 DB 의 유일 키로 적어 **같은 날 다시 켜도 중복해서 만들지 않습니다.**
- 날짜·시각은 이 컴퓨터의 현지 시간대를 따릅니다(기록에는 `+09:00` 같은 시간대 정보가 붙습니다).
- 기본은 AI 를 쓰지 않는 규칙 요약(외부 전송 없음). 「AI 조언 포함」을 켠 경우에만 그 내용을 AI 로 보냅니다.
- 실패하면 10분 간격으로 하루 최대 3번까지 다시 시도합니다. 실행 중 꺼졌던 작업은 20분 뒤 다시 맡습니다.

## 8. 테스트

```bash
.venv/bin/pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
```

| 파일 | 확인하는 것 |
|---|---|
| `test_pathguard.py` | 폴더 밖 접근 차단(`..`, 절대 경로, 링크, 민감 파일, 예약 이름) |
| `test_files.py` | 문서 읽기 제한, 만들기·고치기, 차이·백업, 충돌, 링크를 통한 쓰기 차단 |
| `test_providers.py` | 미설치·미로그인·취소·제한 시간·도구 켜짐 감지·사용 한도(가짜 CLI), Codex/Gemini 출력 해석 |
| `test_scheduler.py` | 하루 한 번, 재시작 중복 방지, 시각·시간대, 재시도, 동시 실행 |
| `test_core.py` | 제안 해석·거절, 저장/재시작, D-day, 프롬프트(=보내는 자료) |
| `test_integration.py` | 핵심 시나리오 전체(가짜 CLI) |
| `test_ui.py` | 화면(offscreen): 보내기→승인→저장→재시작, 멈춤 |
| `test_real_claude.py` | **실제 Claude Code** 로 핵심 시나리오. 기본은 건너뜀 |

실제 AI 로 확인하려면(구독 사용량이 조금 듭니다):

```bash
NAEILBISEO_REAL_CLAUDE=1 .venv/bin/python -m pytest tests/test_real_claude.py -v -s
```

가짜 CLI(`tests/fake_cli.py`)는 실제 AI 가 아니라 출력 모양만 흉내 내는 시험용 대역입니다.

### 화면

`docs/screenshots/` 에 실행 화면이 있습니다. **Linux 에서 창 없이(offscreen) 그린 화면**이며 Windows 에서 찍은 것이 아닙니다.
글꼴은 나눔바른고딕으로 그려졌고, Windows 에서는 맑은 고딕으로 보입니다. 화면 속 이름·교회·일정은 지어낸 예시입니다.
`03`·`04`·`07`·`11` 의 답변과 파일은 실제 Claude Code 가 답한 것이고, `15`·`16` 은 모의 모드입니다.
`06` 의 제안은 차이 보기 화면을 설명하려고 손으로 만든 것입니다.

```bash
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 .venv/bin/python tools/make_screenshots.py docs/screenshots --real-claude
```

## 9. Windows exe 만들기

**이 저장소의 exe 빌드는 Windows 에서 아직 실행·검증되지 않았습니다.** 개발은 Linux 에서 했고,
같은 spec 으로 Linux 용 PyInstaller 빌드와 자가 점검만 확인했습니다. 절차:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

(또는 `packaging\build_windows.bat` 두 번 누르기.) 스크립트는 가상 환경 → 의존성 설치 → 테스트 → PyInstaller 빌드 →
만든 exe 의 자가 점검(`NaeilBiseo.exe --self-test`, 모의 모드·외부 전송 없음) 순서로 진행하고,
결과물은 `dist\NaeilBiseo\NaeilBiseo.exe` 입니다. 폴더째로 옮겨 씁니다.

GitHub 에 올리면 `.github/workflows/windows-build.yml` 이 Windows 러너에서 테스트·빌드·자가 점검을 하고 exe 를 올려 줍니다
(이 워크플로도 아직 한 번도 돌려 보지 않았습니다).

Windows 에서 확인이 남은 것:

1. `run_windows.bat` 로 실행, 한글 글꼴(맑은 고딕)·큰 글씨 표시
2. `claude.exe`/`claude.cmd` 를 찾아 실행하는지, `--tools ""` 빈 인자가 `.cmd` 를 거쳐도 유지되는지
   (유지되지 않으면 앱이 시작 정보 검사에서 감지해 실행을 멈춥니다)
3. 멈춤 단추가 `taskkill /T` 로 CLI 와 자식 프로세스를 모두 끝내는지
4. 정션(junction)·바로 가기 차단, NTFS 대소문자 구분 없음 처리
5. PyInstaller exe 의 실행과 SmartScreen 경고(코드 서명 없음)

## 10. 아직 없는 것(다음 단계)

팀 모드(역할별 여러 AI), 홈페이지 올리기(웹 배포), 핸드폰 원격 접속, 자동 업그레이드, 프로그램(exe) 만들기,
Word/Excel/PDF 읽기, 음성 입력. 모두 1차 동작을 Windows 에서 검증한 뒤 확장할 항목이며,
자동 배포·유료 서비스 연결·권한 확대는 사용자 승인 없이 넣지 않습니다.

## 11. 폴더 구조

```
naeilbiseo/
  app.py              시작점 (--self-test 자가 점검 포함)
  assistant.py        대화 한 번의 흐름, 제안 승인·거절 (화면과 무관)
  prompts.py          AI 로 보내는 글과 보내는 자료 요약
  actions.py          AI 답에서 제안을 꺼내 검증
  fileops.py          파일 변경 계획(차이)·실행(백업, 충돌 검사)
  workspace.py        문서 목록·읽기
  security/           경로 경계(pathguard) · 민감 파일(sensitive)
  providers/          AI 연결: base(공통) · claude_cli · codex_cli · gemini_cli · mock
  scheduler.py        브리핑·일지 자동 작업(하루 한 번)
  db.py               SQLite 저장소
  editions.py         일반용/목회자용 주제와 지침
  ui/                 PySide6 화면
tests/                단위·통합·화면 테스트, 가짜 CLI
packaging/            Windows 빌드 스크립트(PyInstaller)
tools/                스크린샷 생성 도구
```
