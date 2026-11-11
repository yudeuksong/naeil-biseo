"""작업 폴더 경계 검사(PathGuard).

AI 가 말한 경로든 사용자가 고른 경로든, 파일을 읽거나 쓰기 전에 반드시 여기를 거친다.
프롬프트로 "폴더 밖은 건드리지 마" 라고 부탁하는 것이 아니라, 앱 코드가 실제 경로를
풀어 보고(realpath) 작업 폴더 밖이면 거절한다.

막는 것:
  * 절대 경로(/etc/..., C:\\..., \\\\server\\share, C:상대경로, ~ 로 시작)
  * 상위 폴더 이동(..)
  * 심볼릭 링크·정션(junction)을 거쳐 폴더 밖으로 나가는 경로 — 경로 중간의 링크는 모두 거절
  * Windows 예약 이름(CON, NUL, COM1 …), 대체 데이터 스트림(이름 안의 ':'), 제어 문자
  * 민감 파일(자격증명·.env 등) — sensitive.py 규칙
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from .sensitive import sensitive_reason

_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_DRIVE = re.compile(r"^[A-Za-z]:")
MAX_REL_PATH_CHARS = 240
MAX_PARTS = 12


class PathViolation(Exception):
    """경로 검사에서 거절됨. code 는 기계가 읽는 이유, 메시지는 사용자에게 보여 줄 글."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _is_link_or_junction(path: str) -> bool:
    """심볼릭 링크이거나 Windows 정션/재분석 지점이면 True."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    # Windows: 정션·마운트 지점은 S_ISLNK 가 아니므로 재분석 지점 속성으로 판별
    attrs = getattr(st, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & reparse_flag)


def _within(child: str, root: str) -> bool:
    child_n = os.path.normcase(child)
    root_n = os.path.normcase(root)
    try:
        return os.path.commonpath([child_n, root_n]) == root_n
    except ValueError:  # 서로 다른 드라이브 등
        return False


class PathGuard:
    """한 작업 폴더에 대한 경로 검사기."""

    def __init__(self, root: str | os.PathLike[str]):
        root_str = os.fspath(root)
        if not root_str or not os.path.isdir(root_str):
            raise PathViolation("no_workspace", "작업 폴더가 없거나 폴더가 아닙니다.")
        self.root = Path(os.path.realpath(root_str))
        self._root_str = str(self.root)

    # ── 상대 경로 정리 ────────────────────────────────────────────
    @staticmethod
    def split_relative(rel_path: str) -> list[str]:
        """상대 경로를 검사하고 조각으로 나눈다. 문제가 있으면 PathViolation."""
        if not isinstance(rel_path, str):
            raise PathViolation("empty", "경로가 글자가 아닙니다.")
        raw = rel_path.strip()
        if not raw:
            raise PathViolation("empty", "경로가 비어 있습니다.")
        if len(raw) > MAX_REL_PATH_CHARS:
            raise PathViolation("too_long", "경로가 너무 깁니다.")
        if "\x00" in raw:
            raise PathViolation("bad_name", "경로에 쓸 수 없는 글자가 있습니다.")
        unified = raw.replace("\\", "/")
        if unified.startswith("/") or unified.startswith("~") or _DRIVE.match(unified):
            raise PathViolation("absolute", "작업 폴더 기준의 상대 경로만 쓸 수 있습니다(절대 경로 거절).")
        parts: list[str] = []
        for part in unified.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                raise PathViolation("traversal", "상위 폴더(..)로 나가는 경로는 쓸 수 없습니다.")
            if _BAD_CHARS.search(part):
                raise PathViolation("bad_name", f"이름에 쓸 수 없는 글자가 있습니다: {part!r}")
            if part != part.rstrip(". "):
                raise PathViolation("bad_name", f"이름이 점이나 공백으로 끝날 수 없습니다: {part!r}")
            if part.split(".")[0].lower() in _WINDOWS_RESERVED:
                raise PathViolation("reserved", f"Windows 예약 이름은 쓸 수 없습니다: {part!r}")
            parts.append(part)
        if not parts:
            raise PathViolation("empty", "경로가 비어 있습니다.")
        if len(parts) > MAX_PARTS:
            raise PathViolation("too_long", "폴더 깊이가 너무 깊습니다.")
        return parts

    # ── 핵심: 검증된 실제 경로 얻기 ──────────────────────────────
    def resolve(self, rel_path: str, *, allow_sensitive: bool = False) -> Path:
        """작업 폴더 안의 실제 경로를 돌려준다. 벗어나면 PathViolation.

        파일이 아직 없어도 된다(새 파일 만들기). 이미 있는 중간 폴더·대상이
        링크/정션이면 거절한다.
        """
        parts = self.split_relative(rel_path)
        rel_norm = "/".join(parts)
        if not allow_sensitive:
            reason = sensitive_reason(rel_norm)
            if reason:
                raise PathViolation("sensitive", f"민감 파일이라 다루지 않습니다 — {reason}")

        # 경로 중간(대상 포함)에 링크·정션이 있으면 거절
        current = self._root_str
        for part in parts:
            current = os.path.join(current, part)
            if _is_link_or_junction(current):
                raise PathViolation("symlink", "링크(바로 가기·정션)를 거치는 경로는 쓸 수 없습니다.")

        real = os.path.realpath(current)
        if not _within(real, self._root_str) or os.path.normcase(real) == os.path.normcase(self._root_str):
            raise PathViolation("outside", "작업 폴더 밖의 경로입니다.")
        return Path(real)

    def relative(self, abs_path: str | os.PathLike[str]) -> str:
        """실제 경로를 작업 폴더 기준 상대 경로('/' 구분)로 바꾼다."""
        real = os.path.realpath(os.fspath(abs_path))
        if not _within(real, self._root_str):
            raise PathViolation("outside", "작업 폴더 밖의 경로입니다.")
        rel = os.path.relpath(real, self._root_str)
        return rel.replace(os.sep, "/")

    def contains(self, abs_path: str | os.PathLike[str]) -> bool:
        return _within(os.path.realpath(os.fspath(abs_path)), self._root_str)

    @staticmethod
    def is_link(path: str | os.PathLike[str]) -> bool:
        return _is_link_or_junction(os.fspath(path))
