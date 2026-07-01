from __future__ import annotations

import hashlib
import re
import unicodedata


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text_for_hash(text: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    return _WHITESPACE_RE.sub(" ", normalized).strip().casefold()


def stable_text_hash(text: str | None) -> str:
    normalized = normalize_text_for_hash(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
