"""AI 연결 목록.

새 AI 를 붙이려면 Provider(또는 CliProvider)를 상속한 클래스를 만들고 여기 등록하면 된다.
"""
from __future__ import annotations

from .base import (ChatRequest, CliProvider, ErrorKind, Provider, ProviderError, ProviderStatus,  # noqa: F401
                   RunResult)
from .claude_cli import ClaudeCliProvider
from .codex_cli import CodexCliProvider
from .gemini_cli import GeminiCliProvider
from .mock import MOCK_BANNER, MockProvider  # noqa: F401

PROVIDER_CLASSES: dict[str, type[Provider]] = {
    ClaudeCliProvider.id: ClaudeCliProvider,
    CodexCliProvider.id: CodexCliProvider,
    GeminiCliProvider.id: GeminiCliProvider,
    MockProvider.id: MockProvider,
}
PROVIDER_ORDER = ("claude", "codex", "gemini", "mock")
DEFAULT_PROVIDER = "mock"   # 처음 켰을 때는 아무것도 밖으로 보내지 않는 모의 모드


def create_provider(provider_id: str, executable_override: str = "") -> Provider:
    cls = PROVIDER_CLASSES.get(provider_id, MockProvider)
    if issubclass(cls, CliProvider):
        return cls(executable_override=executable_override)
    return cls()
