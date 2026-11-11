"""파일 변경 계획과 실행기.

AI 는 파일을 직접 쓰지 못한다. AI 가 '이 파일을 이렇게 쓰자'고 제안하면
  1) plan_change() 가 경로·확장자·크기를 검증하고 기존 내용과의 차이(diff)를 만든다.
  2) 사용자가 차이를 보고 승인한다.
  3) apply_change() 가 다시 한 번 검증하고, 기존 파일은 백업한 뒤, 임시 파일을 거쳐 바꿔 쓴다.
승인 뒤 실행 전에 파일이 바뀌었으면(충돌) 쓰지 않는다.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime

from . import config
from .security import PathGuard, PathViolation
from .workspace import DocumentError, read_document


class FileOpError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ChangePlan:
    rel_path: str
    kind: str                    # "create" | "update"
    new_content: str
    old_content: str | None
    old_sha256: str | None       # 계획 시점의 기존 파일 지문(충돌 검사용)
    diff: str                    # 사람이 읽는 unified diff
    encoding: str
    newline: str
    added: int = 0
    removed: int = 0

    @property
    def unchanged(self) -> bool:
        return self.kind == "update" and self.old_content == self.new_content


@dataclass
class ApplyResult:
    rel_path: str
    kind: str
    bytes_written: int
    backup_rel_path: str | None


def _validate_target(guard: PathGuard, rel_path: str, content: str):
    try:
        path = guard.resolve(rel_path)
    except PathViolation as exc:
        raise FileOpError(exc.code, exc.message) from exc
    rel = "/".join(PathGuard.split_relative(rel_path))
    if rel.split("/")[0] == config.BACKUP_DIRNAME:
        raise FileOpError("protected", "백업 폴더에는 쓸 수 없습니다.")
    ext = path.suffix.lower()
    if ext not in config.WRITABLE_EXTENSIONS:
        allowed = ", ".join(sorted(config.WRITABLE_EXTENSIONS))
        raise FileOpError("extension", f"만들거나 고칠 수 있는 파일은 {allowed} 뿐입니다(요청: {ext or '확장자 없음'}).")
    if not isinstance(content, str):
        raise FileOpError("content", "파일 내용이 글자가 아닙니다.")
    if "\x00" in content:
        raise FileOpError("content", "파일 내용에 쓸 수 없는 글자(NUL)가 있습니다.")
    if len(content.encode("utf-8")) > config.MAX_WRITE_BYTES:
        raise FileOpError("too_large", f"파일이 너무 큽니다(한도 {config.MAX_WRITE_BYTES:,}바이트).")
    if path.exists() and not path.is_file():
        raise FileOpError("not_file", "같은 이름의 폴더가 있어 파일을 만들 수 없습니다.")
    return path, rel, ext


def plan_change(guard: PathGuard, rel_path: str, content: str) -> ChangePlan:
    """제안된 파일 쓰기를 검증하고 차이를 계산한다. 디스크는 건드리지 않는다."""
    path, rel, ext = _validate_target(guard, rel_path, content)
    new_content = content.replace("\r\n", "\n")
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

    if path.exists():
        try:
            old = read_document(guard, rel)
        except DocumentError as exc:
            raise FileOpError(exc.code, f"기존 파일을 읽을 수 없어 고치지 않습니다: {exc.message}") from exc
        old_lines = old.text.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff_lines = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"{rel} (지금)",
                                               tofile=f"{rel} (제안)", n=3))
        added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
        removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))
        return ChangePlan(rel, "update", new_content, old.text, old.sha256, "".join(diff_lines),
                          old.encoding, old.newline, added, removed)

    encoding = "utf-8-sig" if ext == ".csv" else "utf-8"   # 엑셀이 한글 CSV 를 바로 열도록 BOM
    newline = "\r\n" if os.name == "nt" else "\n"
    added = len(new_content.splitlines())
    preview = "".join(f"+{ln}" for ln in new_content.splitlines(keepends=True))
    return ChangePlan(rel, "create", new_content, None, None, preview, encoding, newline, added, 0)


def _encode(plan: ChangePlan) -> bytes:
    text = plan.new_content
    if plan.newline == "\r\n":
        text = text.replace("\n", "\r\n")
    try:
        return text.encode(plan.encoding)
    except UnicodeEncodeError:
        return text.encode("utf-8-sig")   # 원래 인코딩으로 못 담는 글자가 있으면 UTF-8 로


def _backup(guard: PathGuard, path, rel: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_root = os.path.join(str(guard.root), config.BACKUP_DIRNAME)
    if PathGuard.is_link(backup_root):
        raise FileOpError("symlink", "백업 폴더가 링크라서 백업할 수 없습니다.")
    dest = os.path.join(backup_root, stamp, *rel.split("/"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not guard.contains(dest):
        raise FileOpError("outside", "백업 위치가 작업 폴더를 벗어납니다.")
    shutil.copy2(str(path), dest)
    return os.path.relpath(dest, str(guard.root)).replace(os.sep, "/")


def apply_change(guard: PathGuard, plan: ChangePlan) -> ApplyResult:
    """승인된 계획을 실행한다. 실행 직전에 모든 검증을 다시 한다."""
    path, rel, _ext = _validate_target(guard, plan.rel_path, plan.new_content)
    exists = path.exists()
    backup_rel: str | None = None

    if plan.kind == "create":
        if exists:
            raise FileOpError("conflict", "승인하는 사이에 같은 이름의 파일이 생겼습니다. 덮어쓰지 않았습니다.")
    elif plan.kind == "update":
        if not exists:
            raise FileOpError("conflict", "승인하는 사이에 원래 파일이 없어졌습니다. 쓰지 않았습니다.")
        with open(path, "rb") as fh:
            current_sha = hashlib.sha256(fh.read()).hexdigest()
        if current_sha != plan.old_sha256:
            raise FileOpError("conflict", "승인하는 사이에 파일 내용이 바뀌었습니다. 다시 제안을 받아 주세요.")
        backup_rel = _backup(guard, path, rel)
    else:
        raise FileOpError("kind", "알 수 없는 변경 종류입니다.")

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    # 폴더를 만든 뒤 다시 한 번: 그 사이 링크로 바뀌지 않았는지
    if not guard.contains(parent) or guard.resolve(rel) != path:
        raise FileOpError("outside", "쓰기 직전 경로 검사에서 작업 폴더를 벗어났습니다.")

    data = _encode(plan)
    fd, tmp_name = tempfile.mkstemp(prefix=".내일비서-", suffix=".tmp", dir=str(parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return ApplyResult(rel, plan.kind, len(data), backup_rel)
