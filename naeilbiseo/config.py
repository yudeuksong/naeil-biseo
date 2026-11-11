"""앱 전역 상수와 경로.

여기 있는 한도 값은 '프롬프트 지시'가 아니라 코드가 실제로 강제하는 값이다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_ID

# ── 파일 읽기/쓰기 한도 ──────────────────────────────────────────────
MAX_READ_BYTES = 200_000          # 문서 한 개를 AI 에 보낼 때의 최대 크기
MAX_TOTAL_ATTACH_BYTES = 400_000  # 한 번의 요청에 붙이는 문서 합계
MAX_WRITE_BYTES = 1_000_000       # AI 가 제안한 파일 한 개의 최대 크기
MAX_LIST_ENTRIES = 2_000          # 문서 목록 최대 개수
MAX_LIST_DEPTH = 6                # 문서 목록 최대 깊이
MAX_ACTIONS_PER_REPLY = 20        # 한 답변에서 받아들이는 제안 수
MAX_HISTORY_CHARS = 24_000        # 프롬프트에 넣는 이전 대화 글자 수
MAX_PROMPT_BYTES = 2_000_000      # CLI stdin 으로 보내는 전체 프롬프트 상한

# 읽을 수 있는(=AI 에 보낼 수 있는) 글 문서 확장자
READABLE_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".ini", ".yaml", ".yml"}
# AI 제안으로 만들거나 고칠 수 있는 확장자 (1차 범위: 글·마크다운·CSV)
WRITABLE_EXTENSIONS = {".txt", ".md", ".csv"}

# 백업 폴더 이름(작업 폴더 안). 목록·읽기 대상에서 뺀다.
BACKUP_DIRNAME = ".내일비서_백업"

DEFAULT_TIMEOUT_SEC = 300


def app_data_dir() -> Path:
    """앱 자료(데이터베이스·임시 실행 폴더)를 두는 곳.

    NAEILBISEO_DATA_DIR 환경 변수로 바꿀 수 있다(테스트·휴대용 실행용).
    """
    override = os.environ.get("NAEILBISEO_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / APP_ID
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_ID
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return app_data_dir() / "naeilbiseo.sqlite3"


def cli_scratch_dir() -> Path:
    """AI CLI 를 실행하는 빈 폴더.

    작업 폴더가 아니라 이 빈 폴더에서 CLI 를 띄운다. CLI 가 현재 폴더의 설정 파일이나
    문서를 스스로 읽는 일을 막기 위해서다. 문서는 앱이 검증한 뒤 프롬프트에 넣어 보낸다.
    """
    d = app_data_dir() / "cli_run"
    d.mkdir(parents=True, exist_ok=True)
    return d
