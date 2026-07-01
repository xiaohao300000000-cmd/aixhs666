from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from intelligence.source_pool import (
    HighValueSource,
    HighValueSourcePool,
    SourceCandidate,
    build_account_candidate,
    build_comment_section_candidate,
    build_content_candidate,
)


HIGH_VALUE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "explicit_local_demand": ("求推荐", "本地", "附近", "福州", "厦门"),
    "institution_comparison": ("机构", "对比", "哪家", "老师", "课程"),
    "price_question": ("价格", "多少钱", "收费", "课时费"),
    "trial_request": ("试听", "体验课", "试课"),
    "exam_retry": ("二刷", "压线", "没过", "重考", "KET", "PET"),
    "dissatisfaction": ("退费", "不满意", "没效果", "踩雷"),
}


def generate_high_value_sources(
    *,
    pool: HighValueSourcePool,
    content: Any,
    comments: Iterable[Any] = (),
) -> list[HighValueSource]:
    candidates = build_source_candidates_from_context(content=content, comments=comments)
    return pool.upsert_many(candidates)


def build_source_candidates_from_context(*, content: Any, comments: Iterable[Any] = ()) -> list[SourceCandidate]:
    platform = _required_attr(content, "platform")
    platform_content_id = _required_attr(content, "platform_content_id")
    content_text = _join_text(
        getattr(content, "title", None),
        getattr(content, "body_text", None),
        getattr(content, "region_text", None),
    )
    content_signals = _detect_signals(content_text)
    comment_list = list(comments)
    comment_signals = _detect_comment_signals(comment_list)
    all_signals = _merge_signals(content_signals, comment_signals)

    candidates: list[SourceCandidate] = []
    if all_signals:
        candidates.append(
            build_content_candidate(
                platform=platform,
                platform_content_id=platform_content_id,
                reason_signals=all_signals,
                metadata={
                    "title": getattr(content, "title", None),
                    "comment_count": getattr(content, "comment_count", None),
                    "like_count": getattr(content, "like_count", None),
                },
                observed_at=getattr(content, "published_at", None),
            )
        )

    author_id = getattr(content, "platform_author_id", None)
    if author_id and all_signals:
        candidates.append(
            build_account_candidate(
                platform=platform,
                platform_user_id=str(author_id),
                reason_signals=all_signals,
                metadata={"source_content_id": platform_content_id},
                observed_at=getattr(content, "published_at", None),
            )
        )

    if _should_track_comment_section(content, comment_list, comment_signals):
        section_signals = _merge_signals(comment_signals, ("high_comment_volume",))
        candidates.append(
            build_comment_section_candidate(
                platform=platform,
                platform_content_id=platform_content_id,
                reason_signals=section_signals,
                metadata={
                    "sample_comment_count": len(comment_list),
                    "content_comment_count": getattr(content, "comment_count", None),
                },
            )
        )

    for comment in comment_list:
        commenter_id = getattr(comment, "platform_author_id", None)
        signals = _detect_signals(
            _join_text(
                getattr(comment, "body_text", None),
                getattr(comment, "region_text", None),
            )
        )
        if commenter_id and signals:
            candidates.append(
                build_account_candidate(
                    platform=platform,
                    platform_user_id=str(commenter_id),
                    reason_signals=signals,
                    base_score=0.28,
                    metadata={
                        "source_content_id": platform_content_id,
                        "source_comment_id": getattr(comment, "platform_comment_id", None),
                    },
                    observed_at=getattr(comment, "published_at", None),
                )
            )

    return candidates


def _required_attr(value: Any, attr_name: str) -> str:
    attr_value = getattr(value, attr_name, None)
    if not attr_value:
        raise ValueError(f"context content requires {attr_name}")
    return str(attr_value)


def _detect_comment_signals(comments: list[Any]) -> tuple[str, ...]:
    signals: list[str] = []
    for comment in comments:
        signals.extend(
            _detect_signals(
                _join_text(
                    getattr(comment, "body_text", None),
                    getattr(comment, "region_text", None),
                )
            )
        )
    return _merge_signals(signals)


def _detect_signals(text: str) -> tuple[str, ...]:
    return tuple(
        signal
        for signal, keywords in HIGH_VALUE_KEYWORDS.items()
        if any(keyword.lower() in text.lower() for keyword in keywords)
    )


def _should_track_comment_section(content: Any, comments: list[Any], signals: tuple[str, ...]) -> bool:
    content_comment_count = int(getattr(content, "comment_count", 0) or 0)
    return bool(signals) and (len(comments) >= 2 or content_comment_count >= 20)


def _merge_signals(*signal_groups: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in signal_groups:
        for signal in group:
            if signal not in seen:
                merged.append(signal)
                seen.add(signal)
    return tuple(merged)


def _join_text(*parts: object) -> str:
    return " ".join(str(part) for part in parts if part)
