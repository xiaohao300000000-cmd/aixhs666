from __future__ import annotations

import hashlib

from intelligence.text_processing import normalize_text


def _normalize_text_for_hash_only(text: str | None) -> str:
    return normalize_text(text).casefold()


def normalize_text_for_hash(text: str | None) -> str:
    return _normalize_text_for_hash_only(text)


def stable_text_hash(text: str | None) -> str:
    normalized = normalize_text_for_hash(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
