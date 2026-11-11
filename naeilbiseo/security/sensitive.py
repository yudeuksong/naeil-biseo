"""민감 파일 판별.

자격증명·열쇠·환경 파일처럼 AI 에 보내거나 AI 제안으로 건드리면 안 되는 파일을
이름과 폴더로 가려낸다. 이 검사는 목록·읽기·쓰기 모두에 적용된다.

주의: 이름으로 가려내는 방식이라 완벽하지 않다. 평범한 이름의 문서 안에 적힌
비밀번호까지 알아내지는 못한다(그 부분은 사용자가 첨부 전에 확인해야 한다).
"""
from __future__ import annotations

import fnmatch
from pathlib import PurePath

# 이름 그대로 일치(소문자 비교)
_SENSITIVE_NAMES = {
    ".env", ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".htpasswd",
    "credentials", "credentials.json", "credentials.yaml", "credentials.yml",
    "client_secret.json", "service-account.json", "service_account.json",
    "token.json", "tokens.json", "auth.json", "secrets.json", "secrets.yaml", "secrets.yml",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "known_hosts", "authorized_keys",
    "wallet.dat", "login data", "cookies", "cookies.sqlite", "key4.db", "logins.json",
    ".credentials.json", "oauth_creds.json",
}

# 와일드카드(소문자 비교)
_SENSITIVE_GLOBS = (
    ".env.*", "*.env", "*.pem", "*.key", "*.pfx", "*.p12", "*.jks", "*.keystore",
    "*.kdbx", "*.ppk", "*.ovpn", "*_rsa", "*_ed25519", "*.gpg", "*.asc",
    "*secret*", "*password*", "*passwd*", "*credential*", "*비밀번호*", "*인증서*",
    "*공인인증*", "*공동인증*", "*api_key*", "*apikey*", "*api-key*", "*.token",
    "*token*.json", "*token*.txt", "client_secret*",
)

# 이 이름의 폴더 아래는 통째로 제외(소문자 비교)
_SENSITIVE_DIRS = {
    ".git", ".ssh", ".gnupg", ".aws", ".azure", ".gcloud", ".kube", ".docker",
    ".claude", ".codex", ".gemini", ".config", "npki", "gpki",
    "node_modules", "__pycache__", ".venv", "venv",
}


def sensitive_reason(rel_path: str | PurePath) -> str | None:
    """민감한 이유를 돌려준다. 민감하지 않으면 None."""
    parts = [p for p in PurePath(str(rel_path).replace("\\", "/")).parts if p not in ("", ".")]
    if not parts:
        return None
    lowered = [p.lower() for p in parts]
    for folder in lowered[:-1]:
        if folder in _SENSITIVE_DIRS:
            return f"보호 폴더({folder}) 안의 파일"
    name = lowered[-1]
    if name in _SENSITIVE_DIRS:
        return f"보호 폴더({name})"
    if name in _SENSITIVE_NAMES:
        return "자격증명·열쇠 파일로 보이는 이름"
    for pattern in _SENSITIVE_GLOBS:
        if fnmatch.fnmatchcase(name, pattern):
            return f"민감 파일 규칙({pattern})"
    return None


def is_sensitive_path(rel_path: str | PurePath) -> bool:
    return sensitive_reason(rel_path) is not None
