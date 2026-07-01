from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
import unicodedata


_WHITESPACE_RE = re.compile(r"\s+")
_REPEATED_PUNCTUATION_RE = re.compile(r"([!?！？。,.，、~～])\1+")
_MEANINGFUL_TEXT_RE = re.compile(r"[\w\u4e00-\u9fff]", re.UNICODE)
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

_LOW_INFO_PHRASES = {
    "蹲",
    "蹲蹲",
    "蹲一下",
    "看看",
    "看一下",
    "插眼",
    "码住",
    "马克",
    "mark",
    "收藏",
    "已收藏",
    "谢谢",
    "感谢",
    "谢谢分享",
    "学习了",
    "同问",
    "求问",
    "dd",
    "顶",
    "路过",
}

_REGION_TERMS = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "南京",
    "苏州",
    "成都",
    "重庆",
    "武汉",
    "西安",
    "福州",
    "厦门",
    "泉州",
    "天津",
    "郑州",
    "长沙",
    "合肥",
    "青岛",
    "宁波",
    "佛山",
    "东莞",
)

_EXAM_TERMS = (
    "KET",
    "PET",
    "FCE",
    "CAE",
    "雅思",
    "托福",
    "小托福",
    "中考",
    "高考",
    "小升初",
    "分班考",
    "期中",
    "期末",
)

_KNOWN_INSTITUTION_BRANDS = (
    "学而思",
    "新东方",
    "英孚",
    "瑞思",
    "贝乐",
    "励步",
)

_INSTITUTION_SUFFIXES = ("机构", "教育", "英语", "学校", "学院", "课堂", "培训", "中心")

_GRADE_PATTERNS = (
    re.compile(r"(幼儿园|大班|中班|小班)"),
    re.compile(r"([一二三四五六七八九]年级)"),
    re.compile(r"(小学|初中|高中)([一二三四五六七八九123456789])年级?"),
    re.compile(r"(初[一二三]|高[一二三])"),
    re.compile(r"([1-9])年级"),
    re.compile(r"(G[1-9])", re.IGNORECASE),
)

_GENERIC_INSTITUTION_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9]{2,8}(?:机构|教育|英语|学校|学院|课堂|培训|中心))")


class LowInfoReason(StrEnum):
    EMPTY = "empty"
    ONLY_PUNCTUATION_OR_EMOJI = "only_punctuation_or_emoji"
    GENERIC_SHORT_ACK = "generic_short_ack"
    TOO_SHORT = "too_short"


@dataclass(frozen=True)
class ExtractedFields:
    regions: tuple[str, ...] = field(default_factory=tuple)
    exams: tuple[str, ...] = field(default_factory=tuple)
    grades: tuple[str, ...] = field(default_factory=tuple)
    institution_candidates: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TextProcessingResult:
    source_id: str | None
    raw_text: str
    normalized_text: str
    is_low_information: bool
    low_info_reasons: tuple[LowInfoReason, ...]
    fields: ExtractedFields


def normalize_text(text: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = _URL_RE.sub("", normalized)
    normalized = _REPEATED_PUNCTUATION_RE.sub(r"\1", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def is_low_information(text: str | None) -> tuple[bool, tuple[LowInfoReason, ...]]:
    normalized = normalize_text(text)
    compact = _compact_for_matching(normalized)
    reasons: list[LowInfoReason] = []

    if not normalized:
        reasons.append(LowInfoReason.EMPTY)
    elif not _MEANINGFUL_TEXT_RE.search(normalized):
        reasons.append(LowInfoReason.ONLY_PUNCTUATION_OR_EMOJI)
    elif compact.casefold() in _LOW_INFO_PHRASES:
        reasons.append(LowInfoReason.GENERIC_SHORT_ACK)
    elif len(compact) <= 1:
        reasons.append(LowInfoReason.TOO_SHORT)

    return bool(reasons), tuple(reasons)


def extract_fields(text: str | None) -> ExtractedFields:
    normalized = normalize_text(text)
    return ExtractedFields(
        regions=_unique_matches(term for term in _REGION_TERMS if term in normalized),
        exams=_unique_matches(term for term in _EXAM_TERMS if term.casefold() in normalized.casefold()),
        grades=_extract_grades(normalized),
        institution_candidates=_extract_institutions(normalized),
    )


def process_text(text: str | None, *, source_id: str | None = None) -> TextProcessingResult:
    normalized = normalize_text(text)
    low_info, reasons = is_low_information(normalized)
    return TextProcessingResult(
        source_id=source_id,
        raw_text=text or "",
        normalized_text=normalized,
        is_low_information=low_info,
        low_info_reasons=reasons,
        fields=extract_fields(normalized),
    )


def process_texts(items: list[str] | list[tuple[str | None, str | None]]) -> list[TextProcessingResult]:
    results: list[TextProcessingResult] = []
    for index, item in enumerate(items):
        if isinstance(item, tuple):
            source_id, text = item
        else:
            source_id, text = str(index), item
        results.append(process_text(text, source_id=source_id))
    return results


def _compact_for_matching(text: str) -> str:
    return re.sub(r"[\s!?！？。,.，、~～:：;；'\"“”‘’()\[\]{}<>《》]+", "", text)


def _extract_grades(text: str) -> tuple[str, ...]:
    matches: list[str] = []
    for pattern in _GRADE_PATTERNS:
        for match in pattern.finditer(text):
            matches.append(match.group(0))
    return _unique_matches(matches)


def _extract_institutions(text: str) -> tuple[str, ...]:
    candidates: list[str] = []
    compact_text = _compact_for_matching(text)
    for brand in _KNOWN_INSTITUTION_BRANDS:
        start = 0
        while True:
            index = compact_text.find(brand, start)
            if index < 0:
                break
            candidate = brand
            tail = compact_text[index + len(brand) :]
            for suffix in _INSTITUTION_SUFFIXES:
                if tail.startswith(suffix):
                    candidate = f"{brand}{suffix}"
                    break
            candidates.append(candidate)
            start = index + len(brand)

    for match in _GENERIC_INSTITUTION_RE.finditer(text):
        candidate = match.group(1)
        if not any(candidate.endswith(known) for known in candidates):
            candidates.append(candidate)
    return _unique_matches(candidates)


def _unique_matches(matches: object) -> tuple[str, ...]:
    seen: set[str] = set()
    values: list[str] = []
    for match in matches:
        value = str(match)
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            values.append(value)
    return tuple(values)
