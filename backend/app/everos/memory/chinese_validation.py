"""Validation helpers for Chinese EverOS memory text."""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z_-]*")
_ALLOWED_LATIN_WORDS = {
    "agent",
    "ai",
    "api",
    "app",
    "id",
    "jd",
    "json",
    "llm",
    "utc",
    "everos",
    "memory",
    "service",
}


def is_valid_chinese_memory_text(text: object) -> bool:
    """Return true when text is Chinese narrative, not English prose or JSON."""
    if not isinstance(text, str):
        return False
    value = normalise_memory_text(text)
    if not value or not _CJK_RE.search(value):
        return False
    if value.startswith(("{", "[")):
        return False
    lowered = value.casefold()
    return not (
        '"foresights"' in lowered
        or '"atomic_facts"' in lowered
        or '"fact"' in lowered
        or "```json" in lowered
        or _looks_like_english_prose(value)
    )


def normalise_memory_text(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _looks_like_english_prose(text: str) -> bool:
    cjk_count = len(_CJK_RE.findall(text))
    latin_words = [
        word
        for word in _LATIN_WORD_RE.findall(text)
        if not _is_allowed_latin_token(word)
    ]
    if not latin_words:
        return False
    stripped = text.lstrip()
    starts_with_latin = stripped[:1].isascii() and stripped[:1].isalpha()
    if starts_with_latin and len(latin_words) >= 3 and cjk_count < 12:
        return True
    if not starts_with_latin and cjk_count >= 8:
        return False
    return len(latin_words) >= 12 and len(latin_words) > cjk_count * 2


def _is_allowed_latin_token(token: str) -> bool:
    lowered = token.casefold().strip("_-")
    if not lowered:
        return True
    if lowered in _ALLOWED_LATIN_WORDS:
        return True
    if lowered.startswith("huajie_sun"):
        return True
    if re.fullmatch(r"[a-f]+", lowered):
        return True
    if re.fullmatch(r"[a-f0-9]{6,}", lowered):
        return True
    return False
