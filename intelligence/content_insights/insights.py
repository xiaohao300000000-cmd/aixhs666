from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from intelligence.dashboard import DashboardSummary
from intelligence.phrase_discovery import PhraseCandidate
from intelligence.text_processing import extract_fields, normalize_text


@dataclass(frozen=True, slots=True)
class ContentInsightInput:
    text: str
    occurred_at: datetime
    region: str | None = None
    exam: str | None = None
    institution: str | None = None
    source_score: float = 0.0
    candidate_phrases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InsightItem:
    title: str
    score: float
    reason: str
    evidence_count: int
    examples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LocalDemandDifference:
    region: str
    top_terms: tuple[str, ...]
    evidence_count: int
    reason: str


@dataclass(frozen=True, slots=True)
class ContentInsightReport:
    frequent_questions: tuple[InsightItem, ...]
    emerging_anxieties: tuple[InsightItem, ...]
    content_topics: tuple[InsightItem, ...]
    lead_magnet_topics: tuple[InsightItem, ...]
    live_stream_topics: tuple[InsightItem, ...]
    local_demand_differences: tuple[LocalDemandDifference, ...]


_ANXIETY_TERMS = (
    "跟不上",
    "压线",
    "没过",
    "二刷",
    "退费",
    "不满意",
    "来不及",
    "焦虑",
    "踩雷",
    "分班考",
)
_QUESTION_TERMS = ("吗", "？", "?", "有没有", "求推荐", "想问", "请问", "怎么", "如何", "哪家", "价格", "试听")
_ACTION_TERMS = ("价格", "多少钱", "试听", "体验课", "报名", "冲刺", "二刷", "压线", "退费")


def generate_content_insights(
    items: Iterable[ContentInsightInput],
    *,
    dashboard_summary: DashboardSummary | None = None,
    phrase_candidates: Iterable[PhraseCandidate | str] = (),
    limit: int = 6,
) -> ContentInsightReport:
    records = tuple(_enrich_item(item) for item in items if normalize_text(item.text))
    candidate_terms = _candidate_terms(phrase_candidates)
    question_items = _build_insight_items(records, candidate_terms=candidate_terms, mode="question", limit=limit)
    anxiety_items = _build_insight_items(records, candidate_terms=candidate_terms, mode="anxiety", limit=limit)
    content_topics = _topic_items(question_items, anxiety_items, dashboard_summary=dashboard_summary, prefix="选题")
    lead_magnets = _topic_items(question_items, anxiety_items, dashboard_summary=dashboard_summary, prefix="资料包")
    live_topics = _topic_items(question_items, anxiety_items, dashboard_summary=dashboard_summary, prefix="直播")

    return ContentInsightReport(
        frequent_questions=question_items,
        emerging_anxieties=anxiety_items,
        content_topics=content_topics[:limit],
        lead_magnet_topics=lead_magnets[:limit],
        live_stream_topics=live_topics[:limit],
        local_demand_differences=_local_differences(records, limit=limit),
    )


@dataclass(frozen=True, slots=True)
class _EnrichedRecord:
    text: str
    normalized_text: str
    region: str | None
    exam: str | None
    institution: str | None
    source_score: float
    candidate_phrases: tuple[str, ...]


def _enrich_item(item: ContentInsightInput) -> _EnrichedRecord:
    normalized = normalize_text(item.text)
    fields = extract_fields(normalized)
    region = item.region or (fields.regions[0] if fields.regions else None)
    exam = item.exam or (fields.exams[0] if fields.exams else None)
    institution = item.institution or (fields.institution_candidates[0] if fields.institution_candidates else None)
    return _EnrichedRecord(
        text=item.text,
        normalized_text=normalized,
        region=region,
        exam=exam,
        institution=institution,
        source_score=_clamp(item.source_score),
        candidate_phrases=tuple(normalize_text(phrase) for phrase in item.candidate_phrases if normalize_text(phrase)),
    )


def _build_insight_items(
    records: tuple[_EnrichedRecord, ...],
    *,
    candidate_terms: tuple[str, ...],
    mode: str,
    limit: int,
) -> tuple[InsightItem, ...]:
    evidence: dict[str, list[_EnrichedRecord]] = defaultdict(list)
    for record in records:
        terms = _record_terms(record, candidate_terms=candidate_terms)
        for term in terms:
            if mode == "question" and not _is_question_signal(record.normalized_text, term):
                continue
            if mode == "anxiety" and not _is_anxiety_signal(record.normalized_text, term):
                continue
            evidence[term].append(record)

    items = [
        _insight_item(term, records=term_records, mode=mode)
        for term, term_records in evidence.items()
        if len(term_records) >= 1
    ]
    return tuple(sorted(items, key=lambda item: (-item.score, -item.evidence_count, item.title))[:limit])


def _record_terms(record: _EnrichedRecord, *, candidate_terms: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    terms.extend(record.candidate_phrases)
    terms.extend(term for term in candidate_terms if term and term in record.normalized_text)
    if record.exam:
        terms.append(record.exam)
    if record.institution:
        terms.append(record.institution)
    terms.extend(term for term in _ACTION_TERMS if term in record.normalized_text)
    return _dedupe(terms)


def _insight_item(term: str, *, records: list[_EnrichedRecord], mode: str) -> InsightItem:
    evidence_count = len(records)
    avg_source_score = sum(record.source_score for record in records) / evidence_count
    action_hits = sum(1 for record in records if any(action in record.normalized_text for action in _ACTION_TERMS))
    score = round(min(1.0, 0.18 * evidence_count + 0.42 * avg_source_score + 0.08 * action_hits), 6)
    label = "高频问题" if mode == "question" else "新增焦虑点"
    examples = tuple(record.normalized_text for record in records[:3])
    return InsightItem(
        title=f"{label}: {term}",
        score=score,
        reason=f"term={term}; evidence_count={evidence_count}; avg_source_score={avg_source_score:.3f}; action_hits={action_hits}",
        evidence_count=evidence_count,
        examples=examples,
    )


def _topic_items(
    questions: tuple[InsightItem, ...],
    anxieties: tuple[InsightItem, ...],
    *,
    dashboard_summary: DashboardSummary | None,
    prefix: str,
) -> tuple[InsightItem, ...]:
    base_items = _dedupe_insight_items((*questions, *anxieties))
    conversion_note = ""
    if dashboard_summary is not None:
        conversion_note = (
            f"; new_content={dashboard_summary.totals.new_content_count}; "
            f"new_comments={dashboard_summary.totals.new_comment_count}"
        )

    topics: list[InsightItem] = []
    for item in base_items:
        core = item.title.split(": ", 1)[-1]
        if prefix == "选题":
            title = f"选题: {core} 家长最关心的三个决策点"
        elif prefix == "资料包":
            title = f"资料包: {core} 准备清单与避坑指南"
        else:
            title = f"直播: {core} 现场答疑专场"
        topics.append(
            InsightItem(
                title=title,
                score=item.score,
                reason=f"derived_from={item.title}; {item.reason}{conversion_note}",
                evidence_count=item.evidence_count,
                examples=item.examples,
            )
        )
    return tuple(topics)


def _local_differences(records: tuple[_EnrichedRecord, ...], *, limit: int) -> tuple[LocalDemandDifference, ...]:
    by_region: dict[str, Counter[str]] = defaultdict(Counter)
    examples_by_region: dict[str, list[str]] = defaultdict(list)
    for record in records:
        if not record.region:
            continue
        terms = _record_terms(record, candidate_terms=())
        for term in terms:
            by_region[record.region][term] += 1
        if len(examples_by_region[record.region]) < 3:
            examples_by_region[record.region].append(record.normalized_text)

    differences = [
        LocalDemandDifference(
            region=region,
            top_terms=tuple(term for term, _count in counter.most_common(5)),
            evidence_count=sum(counter.values()),
            reason=f"region={region}; top_terms={','.join(term for term, _count in counter.most_common(5))}; examples={len(examples_by_region[region])}",
        )
        for region, counter in by_region.items()
        if counter
    ]
    return tuple(sorted(differences, key=lambda item: (-item.evidence_count, item.region))[:limit])


def _candidate_terms(candidates: Iterable[PhraseCandidate | str]) -> tuple[str, ...]:
    terms = []
    for candidate in candidates:
        terms.append(candidate.phrase if isinstance(candidate, PhraseCandidate) else str(candidate))
    return tuple(_dedupe(terms))


def _is_question_signal(text: str, term: str) -> bool:
    return term in text and any(question_term in text for question_term in _QUESTION_TERMS)


def _is_anxiety_signal(text: str, term: str) -> bool:
    return term in text and any(anxiety_term in text for anxiety_term in _ANXIETY_TERMS)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = normalize_text(value)
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            deduped.append(normalized)
    return tuple(deduped)


def _dedupe_insight_items(items: tuple[InsightItem, ...]) -> tuple[InsightItem, ...]:
    seen: set[str] = set()
    deduped: list[InsightItem] = []
    for item in items:
        key = item.title.split(": ", 1)[-1].casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return tuple(deduped)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
