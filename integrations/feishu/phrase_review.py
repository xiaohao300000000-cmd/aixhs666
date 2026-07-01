from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PhraseReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONVERTED_TO_QUERY = "converted_to_query"


class PhraseReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    CONVERT_TO_QUERY = "convert_to_query"


@dataclass(frozen=True)
class FeishuPhraseReviewPayload:
    candidate_id: str
    message_type: str
    card: dict[str, Any]
    callback_value: dict[str, str]


@dataclass(frozen=True)
class PhraseReviewState:
    candidate_id: str
    phrase: str
    status: PhraseReviewStatus = PhraseReviewStatus.PENDING
    reviewer_id: str | None = None
    review_reason: str | None = None
    query_text: str | None = None


@dataclass(frozen=True)
class QueryCreationRequest:
    query_text: str
    platform: str
    source: str = "feishu_phrase_review"
    metadata: dict[str, Any] = field(default_factory=dict)


def build_phrase_review_payload(
    candidate: Any,
    *,
    candidate_id: str | None = None,
    locale: str = "zh_cn",
) -> FeishuPhraseReviewPayload:
    phrase = _candidate_phrase(candidate)
    resolved_candidate_id = candidate_id or _candidate_id(candidate, phrase)
    examples = _candidate_examples(candidate)
    source_text_count = _candidate_int(candidate, "source_text_count", default=0)
    novelty_score = _candidate_float(candidate, "novelty_score", default=0.0)
    query_potential_score = _candidate_float(candidate, "query_potential_score", default=0.0)

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "新词审核"},
        },
        "elements": [
            {"tag": "markdown", "content": f"**候选表达**：{phrase}"},
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"来源文本数：{source_text_count}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"新颖度：{novelty_score:.4f}"}},
                    {
                        "is_short": True,
                        "text": {"tag": "lark_md", "content": f"查询潜力：{query_potential_score:.4f}"},
                    },
                ],
            },
            {"tag": "markdown", "content": _examples_markdown(examples)},
            {
                "tag": "action",
                "actions": [
                    _button("批准", PhraseReviewAction.APPROVE, resolved_candidate_id),
                    _button("拒绝", PhraseReviewAction.REJECT, resolved_candidate_id),
                    _button("转查询", PhraseReviewAction.CONVERT_TO_QUERY, resolved_candidate_id),
                ],
            },
        ],
    }
    return FeishuPhraseReviewPayload(
        candidate_id=resolved_candidate_id,
        message_type="interactive",
        card=card,
        callback_value={"candidate_id": resolved_candidate_id, "locale": locale},
    )


def build_phrase_review_payloads(candidates: Iterable[Any]) -> list[FeishuPhraseReviewPayload]:
    return [build_phrase_review_payload(candidate) for candidate in candidates]


def apply_phrase_review_action(
    state: PhraseReviewState,
    action: PhraseReviewAction | str,
    *,
    reviewer_id: str | None = None,
    reason: str | None = None,
    query_text: str | None = None,
) -> PhraseReviewState:
    normalized_action = PhraseReviewAction(action)
    next_status = _next_status(state.status, normalized_action)
    return PhraseReviewState(
        candidate_id=state.candidate_id,
        phrase=state.phrase,
        status=next_status,
        reviewer_id=reviewer_id,
        review_reason=reason,
        query_text=query_text if next_status == PhraseReviewStatus.CONVERTED_TO_QUERY else state.query_text,
    )


def phrase_review_to_query_request(
    state: PhraseReviewState,
    *,
    platform: str = "xhs",
    region: str | None = None,
    exam: str | None = None,
) -> QueryCreationRequest:
    if state.status not in {PhraseReviewStatus.APPROVED, PhraseReviewStatus.CONVERTED_TO_QUERY}:
        raise ValueError(f"cannot create query from review status: {state.status}")

    query_text = state.query_text or _join_query_parts(region, exam, state.phrase)
    return QueryCreationRequest(
        query_text=query_text,
        platform=platform,
        metadata={
            "candidate_id": state.candidate_id,
            "phrase": state.phrase,
            "review_status": state.status.value,
        },
    )


def _next_status(status: PhraseReviewStatus, action: PhraseReviewAction) -> PhraseReviewStatus:
    transitions = {
        (PhraseReviewStatus.PENDING, PhraseReviewAction.APPROVE): PhraseReviewStatus.APPROVED,
        (PhraseReviewStatus.PENDING, PhraseReviewAction.REJECT): PhraseReviewStatus.REJECTED,
        (PhraseReviewStatus.APPROVED, PhraseReviewAction.CONVERT_TO_QUERY): PhraseReviewStatus.CONVERTED_TO_QUERY,
    }
    try:
        return transitions[(status, action)]
    except KeyError as exc:
        raise ValueError(f"illegal phrase review transition: {status} -> {action}") from exc


def _button(label: str, action: PhraseReviewAction, candidate_id: str) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "value": {"candidate_id": candidate_id, "action": action.value},
        "type": "primary" if action != PhraseReviewAction.REJECT else "danger",
    }


def _examples_markdown(examples: Sequence[str]) -> str:
    if not examples:
        return "**代表样本**：暂无"
    rows = "\n".join(f"- {example}" for example in examples)
    return f"**代表样本**：\n{rows}"


def _candidate_phrase(candidate: Any) -> str:
    phrase = _candidate_value(candidate, "phrase")
    if not phrase:
        raise ValueError("phrase candidate requires phrase")
    return str(phrase)


def _candidate_id(candidate: Any, phrase: str) -> str:
    explicit = _candidate_value(candidate, "candidate_id") or _candidate_value(candidate, "id")
    if explicit:
        return str(explicit)
    return f"phrase:{phrase.casefold()}"


def _candidate_examples(candidate: Any) -> tuple[str, ...]:
    raw_examples = _candidate_value(candidate, "representative_examples") or ()
    return tuple(str(example) for example in raw_examples)


def _candidate_int(candidate: Any, field_name: str, *, default: int) -> int:
    raw_value = _candidate_value(candidate, field_name)
    return default if raw_value is None else int(raw_value)


def _candidate_float(candidate: Any, field_name: str, *, default: float) -> float:
    raw_value = _candidate_value(candidate, field_name)
    return default if raw_value is None else float(raw_value)


def _candidate_value(candidate: Any, field_name: str) -> Any:
    if isinstance(candidate, Mapping):
        return candidate.get(field_name)
    return getattr(candidate, field_name, None)


def _join_query_parts(*parts: str | None) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = " ".join(str(part).split()) if part else ""
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            values.append(normalized)
    return " ".join(values)
