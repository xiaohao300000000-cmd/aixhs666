from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
import re

from intelligence.text_processing import is_low_information, normalize_text, process_text


_CJK_CHUNK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_ASCII_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{1,12}")
_KNOWN_LOW_VALUE = {
    "孩子",
    "家长",
    "老师",
    "推荐",
    "有没有",
    "怎么样",
    "求问",
    "一下",
    "这个",
}
_HIGH_INTENT_TERMS = (
    "求推荐",
    "试听",
    "价格",
    "多少钱",
    "退费",
    "二刷",
    "压线",
    "冲刺",
    "跟不上",
    "不满意",
    "比较",
    "分班考",
)


@dataclass(frozen=True)
class PhraseCandidate:
    phrase: str
    source_text_count: int
    novelty_score: float
    query_potential_score: float
    representative_examples: tuple[str, ...]


def discover_phrase_candidates(
    texts: list[str] | tuple[str, ...],
    *,
    existing_phrases: set[str] | frozenset[str] | None = None,
    min_source_text_count: int = 2,
    max_candidates: int = 20,
    max_representative_examples: int = 3,
) -> list[PhraseCandidate]:
    known = {normalize_text(phrase).casefold() for phrase in existing_phrases or set()}
    phrase_counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)

    for text in texts:
        normalized = normalize_text(text)
        low_info, _reasons = is_low_information(normalized)
        if low_info:
            continue

        seen_in_text: set[str] = set()
        for phrase in _candidate_phrases(normalized):
            key = phrase.casefold()
            if key in seen_in_text or key in known:
                continue
            seen_in_text.add(key)
            phrase_counts[phrase] += 1
            if len(examples[phrase]) < max_representative_examples:
                examples[phrase].append(normalized)

    candidates = [
        _build_candidate(phrase, count, len(texts), tuple(examples[phrase]))
        for phrase, count in phrase_counts.items()
        if count >= min_source_text_count
    ]
    return sorted(candidates, key=lambda item: (-item.query_potential_score, -item.novelty_score, item.phrase))[:max_candidates]


def approved_candidate_to_query_text(
    candidate: PhraseCandidate | str,
    *,
    region: str | None = None,
    exam: str | None = None,
) -> str:
    phrase = candidate.phrase if isinstance(candidate, PhraseCandidate) else candidate
    parts = [normalize_text(value) for value in (region, exam, phrase) if normalize_text(value)]
    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = part.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(part)
    return " ".join(deduped)


def _candidate_phrases(text: str) -> tuple[str, ...]:
    processed = process_text(text)
    phrases: list[str] = []

    phrases.extend(processed.fields.regions)
    phrases.extend(processed.fields.exams)
    phrases.extend(processed.fields.grades)
    phrases.extend(processed.fields.institution_candidates)
    phrases.extend(term for term in _HIGH_INTENT_TERMS if term.casefold() in text.casefold())
    phrases.extend(match.group(0).upper() for match in _ASCII_RE.finditer(text))

    for chunk in _CJK_CHUNK_RE.findall(text):
        phrases.extend(_significant_grams(chunk))

    return tuple(_unique_valid_phrases(phrases))


def _significant_grams(chunk: str) -> list[str]:
    grams: list[str] = []
    for size in (2, 3, 4):
        if len(chunk) < size:
            continue
        grams.extend(chunk[index : index + size] for index in range(len(chunk) - size + 1))
    return grams


def _unique_valid_phrases(phrases: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        normalized = normalize_text(phrase)
        key = normalized.casefold()
        if not normalized or key in seen or key in _KNOWN_LOW_VALUE:
            continue
        if len(normalized) < 2:
            continue
        seen.add(key)
        values.append(normalized)
    return values


def _build_candidate(phrase: str, count: int, total_text_count: int, examples: tuple[str, ...]) -> PhraseCandidate:
    novelty_score = _novelty_score(phrase, count, total_text_count)
    query_potential_score = min(1.0, novelty_score * 0.55 + _intent_score(phrase, examples) * 0.45)
    return PhraseCandidate(
        phrase=phrase,
        source_text_count=count,
        novelty_score=round(novelty_score, 4),
        query_potential_score=round(query_potential_score, 4),
        representative_examples=examples,
    )


def _novelty_score(phrase: str, count: int, total_text_count: int) -> float:
    if total_text_count <= 0:
        return 0.0
    frequency = count / total_text_count
    length_bonus = min(len(phrase) / 6, 1.0)
    return min(1.0, (math.log1p(count) / math.log1p(total_text_count)) * 0.75 + length_bonus * 0.25 - frequency * 0.1)


def _intent_score(phrase: str, examples: tuple[str, ...]) -> float:
    joined = " ".join((phrase, *examples)).casefold()
    score = 0.25
    for term in _HIGH_INTENT_TERMS:
        if term.casefold() in joined:
            score += 0.15
    return min(score, 1.0)
