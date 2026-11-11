"""작업 폴더 밖 접근 차단 — 경로 검사."""
from __future__ import annotations

import os
import sys

import pytest

from conftest import can_symlink
from naeilbiseo.security import PathGuard, PathViolation, is_sensitive_path


def test_normal_relative_paths_are_allowed(workspace):
    guard = PathGuard(workspace)
    assert guard.resolve("주보.txt") == guard.root / "주보.txt"
    assert guard.resolve("설교/시편23편_메모.md").is_file()
    assert guard.resolve("설교\\새_원고.md") == guard.root / "설교" / "새_원고.md"   # 없는 새 파일도 됨
    assert guard.relative(guard.root / "설교" / "시편23편_메모.md") == "설교/시편23편_메모.md"


@pytest.mark.parametrize("bad", [
    "../밖.md", "설교/../../밖.md", "..\\..\\Windows\\system.ini", "설교/..",
    "..", "a/b/../../../c.txt",
])
def test_parent_traversal_is_blocked(workspace, bad):
    with pytest.raises(PathViolation) as exc:
        PathGuard(workspace).resolve(bad)
    assert exc.value.code == "traversal"


@pytest.mark.parametrize("bad", [
    "/etc/passwd", "C:\\Windows\\win.ini", "c:/Users/me/secret.txt", "C:상대.txt",
    "\\\\server\\share\\문서.txt", "//server/share/문서.txt", "~/.ssh/id_rsa", "\\Windows\\win.ini",
])
def test_absolute_paths_are_blocked(workspace, bad):
    with pytest.raises(PathViolation) as exc:
        PathGuard(workspace).resolve(bad)
    assert exc.value.code == "absolute"


@pytest.mark.parametrize("bad,code", [
    ("", "empty"), ("   ", "empty"), (".", "empty"), ("./", "empty"),
    ("CON.txt", "reserved"), ("폴더/nul", "reserved"), ("LPT1.md", "reserved"),
    ("문서.txt:숨은스트림", "bad_name"), ("a\x00b.txt", "bad_name"), ("질문?.md", "bad_name"),
    ("끝점.", "bad_name"), ("끝공백 /a.md", "bad_name"), ("a/" * 20 + "b.md", "too_long"),
    ("가" * 300 + ".md", "too_long"),
])
def test_bad_names_are_blocked(workspace, bad, code):
    with pytest.raises(PathViolation) as exc:
        PathGuard(workspace).resolve(bad)
    assert exc.value.code == code


@pytest.mark.parametrize("bad", [
    ".env", "설정/.env.local", "credentials.json", "키/id_rsa", ".git/config", ".ssh/known_hosts",
    "백업/server.pem", "내_비밀번호.txt", "api_key.txt", ".claude/settings.json", "secrets.yaml",
])
def test_sensitive_files_are_blocked(workspace, bad):
    assert is_sensitive_path(bad)
    with pytest.raises(PathViolation) as exc:
        PathGuard(workspace).resolve(bad)
    assert exc.value.code == "sensitive"


def test_ordinary_names_are_not_sensitive():
    for ok in ("설교/주일설교.md", "회의록.txt", "가계부.csv", "환경보고서.md", "keynote_원고.md"):
        assert not is_sensitive_path(ok)


def test_symlink_file_escaping_workspace_is_blocked(workspace, tmp_path):
    if not can_symlink(tmp_path):
        pytest.skip("이 환경에서는 심볼릭 링크를 만들 수 없음")
    outside = tmp_path / "밖의_비밀.txt"
    outside.write_text("밖에 있는 자료", encoding="utf-8")
    os.symlink(outside, workspace / "링크.txt")
    with pytest.raises(PathViolation) as exc:
        PathGuard(workspace).resolve("링크.txt")
    assert exc.value.code == "symlink"


def test_symlink_directory_escaping_workspace_is_blocked(workspace, tmp_path):
    if not can_symlink(tmp_path):
        pytest.skip("이 환경에서는 심볼릭 링크를 만들 수 없음")
    outside_dir = tmp_path / "밖폴더"
    outside_dir.mkdir()
    (outside_dir / "문서.md").write_text("밖", encoding="utf-8")
    os.symlink(outside_dir, workspace / "연결폴더", target_is_directory=True)
    guard = PathGuard(workspace)
    for target in ("연결폴더/문서.md", "연결폴더/새파일.md"):
        with pytest.raises(PathViolation) as exc:
            guard.resolve(target)
        assert exc.value.code == "symlink"


def test_symlink_inside_workspace_is_also_refused(workspace, tmp_path):
    """폴더 안을 가리키는 링크라도 링크를 거치는 경로는 받지 않는다(엄격 모드)."""
    if not can_symlink(tmp_path):
        pytest.skip("이 환경에서는 심볼릭 링크를 만들 수 없음")
    os.symlink(workspace / "주보.txt", workspace / "주보_링크.txt")
    with pytest.raises(PathViolation):
        PathGuard(workspace).resolve("주보_링크.txt")


def test_workspace_given_through_symlink_is_resolved_to_real_root(workspace, tmp_path):
    if not can_symlink(tmp_path):
        pytest.skip("이 환경에서는 심볼릭 링크를 만들 수 없음")
    alias = tmp_path / "작업폴더_별명"
    os.symlink(workspace, alias, target_is_directory=True)
    guard = PathGuard(alias)
    assert guard.root == workspace.resolve()
    assert guard.resolve("주보.txt").is_file()


def test_missing_workspace_is_rejected(tmp_path):
    with pytest.raises(PathViolation) as exc:
        PathGuard(tmp_path / "없는폴더")
    assert exc.value.code == "no_workspace"


def test_relative_rejects_outside_path(workspace, tmp_path):
    guard = PathGuard(workspace)
    with pytest.raises(PathViolation):
        guard.relative(tmp_path / "다른곳.txt")
    assert not guard.contains(tmp_path)


@pytest.mark.skipif(sys.platform != "win32", reason="정션은 Windows 에만 있음")
def test_windows_junction_escaping_workspace_is_blocked(workspace, tmp_path):
    import _winapi

    outside_dir = tmp_path / "밖폴더"
    outside_dir.mkdir()
    (outside_dir / "문서.md").write_text("밖", encoding="utf-8")
    _winapi.CreateJunction(str(outside_dir), str(workspace / "정션"))
    guard = PathGuard(workspace)
    for target in ("정션/문서.md", "정션/새파일.md"):
        with pytest.raises(PathViolation) as exc:
            guard.resolve(target)
        assert exc.value.code == "symlink"
    from naeilbiseo.workspace import list_documents
    assert not any(e.rel_path.startswith("정션") for e in list_documents(guard)[0])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 파일 이름은 대소문자를 가리지 않음")
def test_windows_case_insensitive_sensitive_names(workspace):
    for name in (".ENV", "Credentials.JSON", "ID_RSA", ".Git/config"):
        with pytest.raises(PathViolation) as exc:
            PathGuard(workspace).resolve(name)
        assert exc.value.code == "sensitive"
