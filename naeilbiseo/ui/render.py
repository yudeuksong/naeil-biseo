"""대화 글을 화면용 HTML 로 바꾼다.

AI 가 쓴 글 안의 HTML 은 해석하지 않고 글자 그대로 보여 준다(MarkdownNoHTML).
그림·스크립트 같은 외부 자원을 불러오지 않게 하기 위해서다.
"""
from __future__ import annotations

import html
import re

from PySide6.QtGui import QTextDocument

from . import theme

_BODY = re.compile(r"<body[^>]*>(.*)</body>", re.S)
_FEATURES = QTextDocument.MarkdownFeature.MarkdownDialectGitHub | QTextDocument.MarkdownFeature.MarkdownNoHTML


def md_to_html(text: str) -> str:
    doc = QTextDocument()
    doc.setMarkdown(text or "", _FEATURES)
    match = _BODY.search(doc.toHtml())
    body = match.group(1) if match else html.escape(text or "")
    # 표가 보이도록 테두리를 준다
    return body.replace("<table ", f'<table border="1" cellpadding="6" style="border-color:{theme.LINE};" ')


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def bubble(header: str, body_html: str, *, bg: str, header_color: str = theme.MUTED, footer: str = "") -> str:
    foot = f'<div style="color:{theme.MUTED}; font-size:small; margin-top:6px;">{footer}</div>' if footer else ""
    return (f'<table width="100%" cellspacing="0" cellpadding="12" style="margin-top:10px; background-color:{bg};">'
            f'<tr><td><div style="color:{header_color}; font-weight:700; font-size:small;">{header}</div>'
            f'{body_html}{foot}</td></tr></table>')


def render_message(msg: dict, honorific: str) -> str:
    when = (msg.get("created_at") or "")[11:16]
    role = msg["role"]
    if role == "user":
        attachments = (msg.get("meta") or {}).get("attachments") or []
        footer = ("📎 함께 보낸 문서: " + ", ".join(esc(a) for a in attachments)) if attachments else ""
        body = "<p>" + esc(msg["content"]).replace("\n", "<br>") + "</p>"
        return bubble(f"{esc(honorific)} · {when}", body, bg=theme.USER_BUBBLE, header_color=theme.PRIMARY_DARK,
                      footer=footer)
    if role == "notice":
        return bubble(f"알림 · {when}", "<p>" + esc(msg["content"]) + "</p>", bg=theme.DANGER_SOFT,
                      header_color=theme.DANGER)
    meta = msg.get("meta") or {}
    name = meta.get("provider_name") or msg.get("provider") or "AI"
    if msg.get("is_mock"):
        header, color, bg = f"🧪 모의 응답 · 실제 AI 아님 · {when}", theme.AMBER, "#fffaf0"
    else:
        header, color, bg = f"🤖 내일비서 · {esc(name)} · {when}", theme.PRIMARY_DARK, theme.PANEL
    notes = []
    if meta.get("duration_sec") is not None:
        notes.append(f"{meta['duration_sec']}초")
    if meta.get("model"):
        notes.append(esc(str(meta["model"])))
    for err in meta.get("proposal_errors") or []:
        notes.append("⚠ " + esc(err))
    return bubble(header, md_to_html(msg["content"]), bg=bg, header_color=color, footer=" · ".join(notes))


def render_streaming(text: str, is_mock: bool) -> str:
    header = "🧪 모의 응답 쓰는 중…" if is_mock else "🤖 내일비서 답변 쓰는 중…"
    return bubble(header, md_to_html(text) if text else "<p>…</p>", bg="#fffaf0" if is_mock else theme.PANEL,
                  header_color=theme.AMBER if is_mock else theme.PRIMARY_DARK)


def page(inner: str) -> str:
    return f'<html><body style="color:{theme.INK};">{inner}</body></html>'
