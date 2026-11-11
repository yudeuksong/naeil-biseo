"""작업 폴더의 문서 목록과 읽기.

모든 접근은 PathGuard 를 거친다. 읽은 내용은 '자료'일 뿐이며, 문서 속에 적힌
지시문을 앱이나 AI 가 실행하지 않도록 prompts.py 에서 자료 구획으로 감싸 보낸다.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from . import config
from .security import PathGuard, PathViolation, sensitive_reason


@dataclass
class DocEntry:
    rel_path: str
    size: int
    mtime: float
    readable: bool
    reason: str = ""          # 읽을 수 없을 때 이유
    sensitive: bool = False


@dataclass
class DocContent:
    rel_path: str
    text: str
    size: int                 # 원본 바이트 수
    sha256: str
    encoding: str
    newline: str = "\n"


class DocumentError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _decode(data: bytes) -> tuple[str, str]:
    """한국어 문서에 흔한 인코딩 순서로 풀어 본다."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8"


def list_documents(guard: PathGuard) -> tuple[list[DocEntry], bool]:
    """작업 폴더의 파일 목록. (목록, 한도 때문에 잘렸는지) 를 돌려준다.

    링크·정션은 따라가지 않고, 숨김 폴더와 백업 폴더는 건너뛴다.
    민감 파일은 목록에 '잠김'으로만 보여 주고 읽지 않는다.
    """
    entries: list[DocEntry] = []
    truncated = False
    root = str(guard.root)

    def walk(folder: str, depth: int) -> None:
        nonlocal truncated
        if truncated:
            return
        try:
            with os.scandir(folder) as it:
                items = sorted(it, key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
        except OSError:
            return
        for item in items:
            if len(entries) >= config.MAX_LIST_ENTRIES:
                truncated = True
                return
            if PathGuard.is_link(item.path):
                continue
            rel = os.path.relpath(item.path, root).replace(os.sep, "/")
            if item.is_dir(follow_symlinks=False):
                if item.name == config.BACKUP_DIRNAME or item.name.startswith("."):
                    continue
                if sensitive_reason(rel + "/x"):
                    continue
                if depth < config.MAX_LIST_DEPTH:
                    walk(item.path, depth + 1)
                continue
            if not item.is_file(follow_symlinks=False):
                continue
            try:
                st = item.stat(follow_symlinks=False)
            except OSError:
                continue
            reason = sensitive_reason(rel)
            if reason:
                entries.append(DocEntry(rel, st.st_size, st.st_mtime, False, reason, True))
                continue
            ext = os.path.splitext(item.name)[1].lower()
            if ext not in config.READABLE_EXTENSIONS:
                entries.append(DocEntry(rel, st.st_size, st.st_mtime, False, "글 문서가 아님(목록만 표시)"))
            elif st.st_size > config.MAX_READ_BYTES:
                entries.append(DocEntry(rel, st.st_size, st.st_mtime, False,
                                        f"너무 큼({st.st_size:,}바이트 > {config.MAX_READ_BYTES:,})"))
            else:
                entries.append(DocEntry(rel, st.st_size, st.st_mtime, True))

    walk(root, 0)
    return entries, truncated


def read_document(guard: PathGuard, rel_path: str) -> DocContent:
    """검증된 글 문서 하나를 읽는다. 크기·종류·민감 파일·이진 파일을 걸러낸다."""
    try:
        path = guard.resolve(rel_path)
    except PathViolation as exc:
        raise DocumentError(exc.code, exc.message) from exc
    ext = path.suffix.lower()
    if ext not in config.READABLE_EXTENSIONS:
        raise DocumentError("unsupported", f"읽을 수 있는 글 문서가 아닙니다: {ext or '(확장자 없음)'}")
    if not path.is_file():
        raise DocumentError("not_found", "파일이 없습니다.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise DocumentError("io", f"파일을 열 수 없습니다: {exc.strerror or exc}") from exc
    try:
        size = os.fstat(fd).st_size
        if size > config.MAX_READ_BYTES:
            raise DocumentError("too_large", f"파일이 너무 큽니다({size:,}바이트). 한도 {config.MAX_READ_BYTES:,}바이트.")
        chunks: list[bytes] = []
        remaining = config.MAX_READ_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    finally:
        os.close(fd)
    if len(data) > config.MAX_READ_BYTES:
        raise DocumentError("too_large", "파일이 너무 큽니다.")
    if b"\x00" in data:
        raise DocumentError("binary", "글 문서가 아닌 이진 파일로 보입니다.")
    text, encoding = _decode(data)
    newline = "\r\n" if "\r\n" in text else "\n"
    return DocContent(
        rel_path=guard.relative(path),
        text=text.replace("\r\n", "\n"),
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        encoding=encoding,
        newline=newline,
    )


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n}바이트"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / 1024 / 1024:.1f}MB"


def open_guard(workspace: str | None) -> PathGuard | None:
    """설정된 작업 폴더로 PathGuard 를 만든다. 없으면 None."""
    if not workspace:
        return None
    try:
        return PathGuard(Path(workspace))
    except PathViolation:
        return None
