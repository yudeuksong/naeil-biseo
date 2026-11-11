"""문서 목록·읽기와 파일 변경 실행기."""
from __future__ import annotations

import os

import pytest

from conftest import can_symlink
from naeilbiseo import config
from naeilbiseo.fileops import FileOpError, apply_change, plan_change
from naeilbiseo.security import PathGuard
from naeilbiseo.workspace import DocumentError, list_documents, read_document


# ── 목록·읽기 ────────────────────────────────────────────────────────
def test_list_marks_sensitive_and_non_text_files(workspace):
    entries, truncated = list_documents(PathGuard(workspace))
    by_path = {e.rel_path: e for e in entries}
    assert not truncated
    assert by_path["주보.txt"].readable
    assert by_path["설교/시편23편_메모.md"].readable
    assert by_path[".env"].sensitive and not by_path[".env"].readable
    assert not by_path["사진.png"].readable


def test_list_skips_links_and_backup_folder(workspace, tmp_path):
    (workspace / config.BACKUP_DIRNAME / "x").mkdir(parents=True)
    (workspace / config.BACKUP_DIRNAME / "x" / "옛날.md").write_text("old", encoding="utf-8")
    if can_symlink(tmp_path):
        outside = tmp_path / "밖"
        outside.mkdir()
        (outside / "비밀.md").write_text("secret", encoding="utf-8")
        os.symlink(outside, workspace / "연결", target_is_directory=True)
    paths = [e.rel_path for e in list_documents(PathGuard(workspace))[0]]
    assert not any(p.startswith(config.BACKUP_DIRNAME) for p in paths)
    assert not any(p.startswith("연결") for p in paths)


def test_read_utf8_and_cp949(workspace):
    guard = PathGuard(workspace)
    doc = read_document(guard, "설교/시편23편_메모.md")
    assert "목자 되신 주님" in doc.text and doc.encoding == "utf-8-sig"
    csv = read_document(guard, "가계부.csv")          # 엑셀이 저장한 한글 CSV(cp949)
    assert "식비" in csv.text and csv.encoding == "cp949"


@pytest.mark.parametrize("rel,code", [
    ("../밖.md", "traversal"), ("/etc/hostname", "absolute"), (".env", "sensitive"),
    ("사진.png", "unsupported"), ("없는파일.md", "not_found"),
])
def test_read_refuses_bad_targets(workspace, rel, code):
    with pytest.raises(DocumentError) as exc:
        read_document(PathGuard(workspace), rel)
    assert exc.value.code == code


def test_read_refuses_large_and_binary(workspace):
    (workspace / "큰문서.txt").write_text("가" * (config.MAX_READ_BYTES), encoding="utf-8")
    (workspace / "이진.txt").write_bytes(b"abc\x00def")
    guard = PathGuard(workspace)
    with pytest.raises(DocumentError) as exc:
        read_document(guard, "큰문서.txt")
    assert exc.value.code == "too_large"
    with pytest.raises(DocumentError) as exc:
        read_document(guard, "이진.txt")
    assert exc.value.code == "binary"


# ── 만들기 ───────────────────────────────────────────────────────────
def test_create_new_markdown_file(workspace):
    guard = PathGuard(workspace)
    plan = plan_change(guard, "홍보/초안.md", "# 제목\n내용")
    assert plan.kind == "create" and plan.added == 2
    assert not (workspace / "홍보").exists()          # 계획만으로는 디스크가 바뀌지 않는다
    done = apply_change(guard, plan)
    assert done.kind == "create" and done.backup_rel_path is None
    assert (workspace / "홍보" / "초안.md").read_text(encoding="utf-8").replace("\r\n", "\n") == "# 제목\n내용\n"


def test_create_csv_gets_bom_for_excel(workspace):
    guard = PathGuard(workspace)
    apply_change(guard, plan_change(guard, "예산.csv", "항목,금액\n식비,10000\n"))
    assert (workspace / "예산.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_create_refuses_to_overwrite_file_that_appeared(workspace):
    guard = PathGuard(workspace)
    plan = plan_change(guard, "새문서.md", "제안 내용")
    (workspace / "새문서.md").write_text("그 사이 사용자가 만든 내용", encoding="utf-8")
    with pytest.raises(FileOpError) as exc:
        apply_change(guard, plan)
    assert exc.value.code == "conflict"
    assert (workspace / "새문서.md").read_text(encoding="utf-8") == "그 사이 사용자가 만든 내용"


# ── 고치기 ───────────────────────────────────────────────────────────
def test_update_shows_diff_and_makes_backup(workspace):
    guard = PathGuard(workspace)
    plan = plan_change(guard, "주보.txt", "이번 주 주보 광고 확정본\n추가된 줄\n")
    assert plan.kind == "update"
    assert "-이번 주 주보 광고 초안" in plan.diff and "+추가된 줄" in plan.diff
    assert (plan.added, plan.removed) == (2, 1)
    done = apply_change(guard, plan)
    assert done.backup_rel_path.startswith(config.BACKUP_DIRNAME + "/")
    assert (workspace / done.backup_rel_path).read_text(encoding="utf-8") == "이번 주 주보 광고 초안\n"
    assert "확정본" in (workspace / "주보.txt").read_text(encoding="utf-8")


def test_update_keeps_original_encoding(workspace):
    guard = PathGuard(workspace)
    apply_change(guard, plan_change(guard, "가계부.csv", "날짜,항목,금액\n2026-11-01,식비,15000\n"))
    assert "15000" in (workspace / "가계부.csv").read_bytes().decode("cp949")


def test_update_conflict_when_file_changed_after_plan(workspace):
    guard = PathGuard(workspace)
    plan = plan_change(guard, "주보.txt", "AI 가 제안한 내용\n")
    (workspace / "주보.txt").write_text("사용자가 그 사이 직접 고침\n", encoding="utf-8")
    with pytest.raises(FileOpError) as exc:
        apply_change(guard, plan)
    assert exc.value.code == "conflict"
    assert (workspace / "주보.txt").read_text(encoding="utf-8") == "사용자가 그 사이 직접 고침\n"
    assert not (workspace / config.BACKUP_DIRNAME).exists()


# ── 거절되는 쓰기 ────────────────────────────────────────────────────
@pytest.mark.parametrize("rel,code", [
    ("../밖.md", "traversal"), ("/tmp/밖.md", "absolute"), ("C:\\밖.md", "absolute"),
    (".env", "sensitive"), ("설정/credentials.json", "sensitive"),
    ("실행.py", "extension"), ("스크립트.bat", "extension"), ("페이지.html", "extension"), ("확장자없음", "extension"),
    (config.BACKUP_DIRNAME + "/a.md", "protected"),
])
def test_write_refuses_bad_targets(workspace, tmp_path, rel, code):
    guard = PathGuard(workspace)
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(FileOpError) as exc:
        plan_change(guard, rel, "내용")
    assert exc.value.code == code
    assert sorted(p.name for p in tmp_path.iterdir()) == before     # 폴더 밖에 아무것도 생기지 않음


def test_write_refuses_oversized_and_nul_content(workspace):
    guard = PathGuard(workspace)
    with pytest.raises(FileOpError) as exc:
        plan_change(guard, "큰파일.md", "가" * config.MAX_WRITE_BYTES)
    assert exc.value.code == "too_large"
    with pytest.raises(FileOpError) as exc:
        plan_change(guard, "이상.md", "a\x00b")
    assert exc.value.code == "content"


def test_write_through_symlink_is_refused(workspace, tmp_path):
    if not can_symlink(tmp_path):
        pytest.skip("이 환경에서는 심볼릭 링크를 만들 수 없음")
    outside = tmp_path / "밖의_문서.md"
    outside.write_text("원래 내용", encoding="utf-8")
    os.symlink(outside, workspace / "링크.md")
    outside_dir = tmp_path / "밖폴더"
    outside_dir.mkdir()
    os.symlink(outside_dir, workspace / "연결", target_is_directory=True)
    guard = PathGuard(workspace)
    for rel in ("링크.md", "연결/새문서.md"):
        with pytest.raises(FileOpError) as exc:
            plan_change(guard, rel, "덮어쓰기 시도")
        assert exc.value.code == "symlink"
    assert outside.read_text(encoding="utf-8") == "원래 내용"
    assert list(outside_dir.iterdir()) == []


def test_apply_revalidates_when_folder_becomes_link(workspace, tmp_path):
    """계획 뒤에 중간 폴더가 링크로 바뀌면 쓰기 직전 검사에서 걸린다."""
    if not can_symlink(tmp_path):
        pytest.skip("이 환경에서는 심볼릭 링크를 만들 수 없음")
    guard = PathGuard(workspace)
    plan = plan_change(guard, "나중폴더/문서.md", "내용")
    outside_dir = tmp_path / "밖폴더"
    outside_dir.mkdir()
    os.symlink(outside_dir, workspace / "나중폴더", target_is_directory=True)
    with pytest.raises(FileOpError) as exc:
        apply_change(guard, plan)
    assert exc.value.code == "symlink"
    assert list(outside_dir.iterdir()) == []
