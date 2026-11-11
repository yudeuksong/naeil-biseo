"""테스트 공통 준비물."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naeilbiseo.assistant import Assistant  # noqa: E402
from naeilbiseo.db import Database  # noqa: E402
from naeilbiseo.providers import ClaudeCliProvider, MockProvider  # noqa: E402

FAKE_CLI_SOURCE = Path(__file__).with_name("fake_cli.py")


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """앱 자료 폴더를 테스트마다 임시 폴더로 돌린다(실제 사용자 자료를 건드리지 않게)."""
    data = tmp_path / "appdata"
    data.mkdir()
    monkeypatch.setenv("NAEILBISEO_DATA_DIR", str(data))
    for name in ("FAKE_CLI_MODE", "FAKE_CLI_RECORD", "FAKE_CLI_REPLY"):
        monkeypatch.delenv(name, raising=False)
    return data


@pytest.fixture
def workspace(tmp_path) -> Path:
    root = tmp_path / "작업폴더"
    (root / "설교").mkdir(parents=True)
    # write_bytes: Windows 의 줄바꿈 자동 변환(\n → \r\n) 없이 그대로 쓴다
    (root / "설교" / "시편23편_메모.md").write_bytes("# 시편 23편 메모\n\n목자 되신 주님.\n".encode("utf-8"))
    (root / "주보.txt").write_bytes("이번 주 주보 광고 초안\n".encode("utf-8"))
    (root / "가계부.csv").write_bytes("날짜,항목,금액\n2026-11-01,식비,12000\n".encode("cp949"))
    (root / ".env").write_bytes(b"SECRET_KEY=abc123\n")
    (root / "사진.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    return root


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    yield database
    database.close()


def make_fake_cli(folder: Path, name: str = "claude") -> str:
    """가짜 CLI 실행 파일을 만든다. Windows 에서는 .cmd, 그 밖에는 실행 권한이 있는 스크립트."""
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = folder / f"{name}.cmd"
        path.write_text(f'@"{sys.executable}" "{FAKE_CLI_SOURCE}" %*\r\n', encoding="utf-8")
    else:
        path = folder / name
        path.write_text(f"#!{sys.executable}\n" + FAKE_CLI_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


@pytest.fixture
def fake_cli(tmp_path, monkeypatch) -> dict:
    """가짜 Claude CLI 와 그 호출 기록 파일."""
    exe = make_fake_cli(tmp_path / "bin")
    record = tmp_path / "cli_record.json"
    monkeypatch.setenv("FAKE_CLI_RECORD", str(record))
    return {"exe": exe, "record": record}


@pytest.fixture
def fake_provider(fake_cli) -> ClaudeCliProvider:
    return ClaudeCliProvider(executable_override=fake_cli["exe"])


@pytest.fixture
def assistant_mock(db) -> Assistant:
    return Assistant(db, provider_factory=lambda _pid, _exe: MockProvider(chunk_delay=0))


@pytest.fixture
def assistant_fake(db, fake_cli) -> Assistant:
    return Assistant(db, provider_factory=lambda _pid, _exe: ClaudeCliProvider(executable_override=fake_cli["exe"]))


def can_symlink(tmp_path: Path) -> bool:
    try:
        target = tmp_path / "_symlink_probe_target"
        target.write_text("x", encoding="utf-8")
        link = tmp_path / "_symlink_probe_link"
        os.symlink(target, link)
        link.unlink()
        target.unlink()
        return True
    except (OSError, NotImplementedError):
        return False
