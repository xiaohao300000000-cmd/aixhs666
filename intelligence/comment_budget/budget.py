from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable


DEFAULT_BATCH_SIZE = 30
DEFAULT_MAX_PARENT_COMMENTS = 500
DEFAULT_MAX_TOTAL_COMMENTS = 1000
LOW_INFORMATION_BATCHES_TO_STOP = 2

_TEXT_TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_KNOWN_REGIONS = (
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
    "青岛",
    "长沙",
    "郑州",
)
_INSTITUTION_HINTS = ("机构", "学校", "教育", "英语", "外教", "培训", "老师", "中心", "学院")


class BudgetDecisionAction(StrEnum):
    CONTINUE = "continue"
    STOP = "stop"
    MAXED_OUT = "maxed_out"


@dataclass(frozen=True, slots=True)
class CommentIdentity:
    comment_id: str | None
    author_id: str | None
    text: str | None
    region_text: str | None = None
    is_reply: bool = False


@dataclass(frozen=True, slots=True)
class CommentBatchMetrics:
    batch_size: int
    new_user_rate: float
    new_expression_rate: float
    valid_text_rate: float
    duplicate_rate: float
    new_region_count: int
    new_institution_count: int

    @property
    def information_score(self) -> float:
        return (
            self.new_user_rate * 0.30
            + self.new_expression_rate * 0.30
            + self.valid_text_rate * 0.20
            + (1.0 - self.duplicate_rate) * 0.20
        )

    @property
    def has_entity_discovery(self) -> bool:
        return self.new_region_count > 0 or self.new_institution_count > 0


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    action: BudgetDecisionAction
    reason: str
    next_batch_size: int
    low_information_streak: int = 0

    @property
    def should_continue(self) -> bool:
        return self.action == BudgetDecisionAction.CONTINUE

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "next_batch_size": self.next_batch_size,
            "low_information_streak": self.low_information_streak,
        }


@dataclass(frozen=True, slots=True)
class CommentBudgetConfig:
    batch_size: int = DEFAULT_BATCH_SIZE
    max_parent_comments: int = DEFAULT_MAX_PARENT_COMMENTS
    max_total_comments: int = DEFAULT_MAX_TOTAL_COMMENTS
    low_information_batches_to_stop: int = LOW_INFORMATION_BATCHES_TO_STOP
    min_new_user_rate: float = 0.20
    min_new_expression_rate: float = 0.25
    min_valid_text_rate: float = 0.55
    max_duplicate_rate: float = 0.45
    min_information_score: float = 0.46
    high_value_min_information_score: float = 0.34

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size must be greater than 0")
        if self.max_parent_comments < 1:
            raise ValueError("max_parent_comments must be greater than 0")
        if self.max_total_comments < 1:
            raise ValueError("max_total_comments must be greater than 0")
        if self.low_information_batches_to_stop < 1:
            raise ValueError("low_information_batches_to_stop must be greater than 0")


@dataclass(frozen=True, slots=True)
class CommentBudgetState:
    seen_comment_ids: frozenset[str] = frozenset()
    seen_author_ids: frozenset[str] = frozenset()
    seen_expressions: frozenset[str] = frozenset()
    seen_regions: frozenset[str] = frozenset()
    seen_institutions: frozenset[str] = frozenset()
    parent_comment_count: int = 0
    total_comment_count: int = 0
    low_information_streak: int = 0
    metrics_history: tuple[CommentBatchMetrics, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "seen_comment_ids": sorted(self.seen_comment_ids),
            "seen_author_ids": sorted(self.seen_author_ids),
            "seen_expressions": sorted(self.seen_expressions),
            "seen_regions": sorted(self.seen_regions),
            "seen_institutions": sorted(self.seen_institutions),
            "parent_comment_count": self.parent_comment_count,
            "total_comment_count": self.total_comment_count,
            "low_information_streak": self.low_information_streak,
            "metrics_history": [
                {
                    "batch_size": metrics.batch_size,
                    "new_user_rate": metrics.new_user_rate,
                    "new_expression_rate": metrics.new_expression_rate,
                    "valid_text_rate": metrics.valid_text_rate,
                    "duplicate_rate": metrics.duplicate_rate,
                    "new_region_count": metrics.new_region_count,
                    "new_institution_count": metrics.new_institution_count,
                }
                for metrics in self.metrics_history
            ],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> CommentBudgetState:
        if not payload:
            return cls()
        return cls(
            seen_comment_ids=frozenset(str(value) for value in payload.get("seen_comment_ids", ())),
            seen_author_ids=frozenset(str(value) for value in payload.get("seen_author_ids", ())),
            seen_expressions=frozenset(str(value) for value in payload.get("seen_expressions", ())),
            seen_regions=frozenset(str(value) for value in payload.get("seen_regions", ())),
            seen_institutions=frozenset(str(value) for value in payload.get("seen_institutions", ())),
            parent_comment_count=int(payload.get("parent_comment_count", 0) or 0),
            total_comment_count=int(payload.get("total_comment_count", 0) or 0),
            low_information_streak=int(payload.get("low_information_streak", 0) or 0),
            metrics_history=tuple(_metrics_from_dict(item) for item in payload.get("metrics_history", ())),
        )


@dataclass(frozen=True, slots=True)
class BudgetEvaluation:
    metrics: CommentBatchMetrics
    decision: BudgetDecision
    state: CommentBudgetState


def build_comment_identity(comment: Any) -> CommentIdentity:
    parent_id = getattr(comment, "parent_platform_comment_id", None)
    if parent_id is None:
        parent_id = getattr(comment, "parent_comment_id", None)
    return CommentIdentity(
        comment_id=_optional_str(
            getattr(comment, "platform_comment_id", None)
            or getattr(comment, "comment_id", None)
            or getattr(comment, "id", None)
        ),
        author_id=_optional_str(
            getattr(comment, "platform_author_id", None)
            or getattr(comment, "author_profile_id", None)
            or getattr(comment, "author_id", None)
        ),
        text=_optional_str(getattr(comment, "body_text", None) or getattr(comment, "text", None)),
        region_text=_optional_str(getattr(comment, "region_text", None)),
        is_reply=parent_id is not None,
    )


def summarize_comment_batch(
    comments: Iterable[CommentIdentity],
    *,
    state: CommentBudgetState | None = None,
) -> tuple[CommentBatchMetrics, CommentBudgetState]:
    previous = state or CommentBudgetState()
    batch = tuple(comments)
    batch_size = len(batch)
    if batch_size == 0:
        metrics = CommentBatchMetrics(
            batch_size=0,
            new_user_rate=0.0,
            new_expression_rate=0.0,
            valid_text_rate=0.0,
            duplicate_rate=0.0,
            new_region_count=0,
            new_institution_count=0,
        )
        return metrics, _advance_state(previous, batch, metrics, low_information_streak=previous.low_information_streak)

    seen_comment_ids = set(previous.seen_comment_ids)
    seen_authors = set(previous.seen_author_ids)
    seen_expressions = set(previous.seen_expressions)
    seen_regions = set(previous.seen_regions)
    seen_institutions = set(previous.seen_institutions)

    new_users = 0
    new_expressions = 0
    valid_texts = 0
    duplicates = 0
    batch_comment_ids: set[str] = set()
    batch_authors: set[str] = set()
    batch_expressions: set[str] = set()
    batch_regions: set[str] = set()
    batch_institutions: set[str] = set()

    for comment in batch:
        comment_id = comment.comment_id
        expression = normalize_expression(comment.text)
        if _is_valid_text(comment.text):
            valid_texts += 1

        if comment.author_id and comment.author_id not in seen_authors and comment.author_id not in batch_authors:
            new_users += 1
        if comment.author_id:
            batch_authors.add(comment.author_id)

        is_duplicate = False
        if comment_id:
            is_duplicate = comment_id in seen_comment_ids or comment_id in batch_comment_ids
            batch_comment_ids.add(comment_id)
        if expression:
            if expression in seen_expressions or expression in batch_expressions:
                is_duplicate = True
            elif expression not in seen_expressions:
                new_expressions += 1
            batch_expressions.add(expression)
        if is_duplicate:
            duplicates += 1

        batch_regions.update(extract_regions(comment.region_text, comment.text))
        batch_institutions.update(extract_institutions(comment.text))

    metrics = CommentBatchMetrics(
        batch_size=batch_size,
        new_user_rate=_rate(new_users, batch_size),
        new_expression_rate=_rate(new_expressions, batch_size),
        valid_text_rate=_rate(valid_texts, batch_size),
        duplicate_rate=_rate(duplicates, batch_size),
        new_region_count=len(batch_regions - seen_regions),
        new_institution_count=len(batch_institutions - seen_institutions),
    )
    updated = _advance_state(previous, batch, metrics, low_information_streak=previous.low_information_streak)
    return metrics, updated


def evaluate_comment_budget(
    comments: Iterable[CommentIdentity],
    *,
    state: CommentBudgetState | None = None,
    config: CommentBudgetConfig | None = None,
    high_value_source: bool = False,
) -> BudgetEvaluation:
    effective_config = config or CommentBudgetConfig()
    previous = state or CommentBudgetState()
    metrics, updated_without_decision = summarize_comment_batch(comments, state=previous)
    low_information = _is_low_information(metrics, config=effective_config, high_value_source=high_value_source)
    low_streak = previous.low_information_streak + 1 if low_information else 0
    updated = _replace_low_streak(updated_without_decision, low_streak)
    decision = decide_next_budget(
        metrics,
        state=updated,
        config=effective_config,
        high_value_source=high_value_source,
    )
    return BudgetEvaluation(metrics=metrics, decision=decision, state=_replace_low_streak(updated, decision.low_information_streak))


def decide_next_budget(
    current_metrics: CommentBatchMetrics,
    *,
    state: CommentBudgetState,
    config: CommentBudgetConfig | None = None,
    high_value_source: bool = False,
) -> BudgetDecision:
    effective_config = config or CommentBudgetConfig()
    if state.parent_comment_count >= effective_config.max_parent_comments:
        return BudgetDecision(
            action=BudgetDecisionAction.MAXED_OUT,
            reason="max_parent_comments_reached",
            next_batch_size=0,
            low_information_streak=state.low_information_streak,
        )
    if state.total_comment_count >= effective_config.max_total_comments:
        return BudgetDecision(
            action=BudgetDecisionAction.MAXED_OUT,
            reason="max_total_comments_reached",
            next_batch_size=0,
            low_information_streak=state.low_information_streak,
        )
    if current_metrics.batch_size == 0:
        return BudgetDecision(
            action=BudgetDecisionAction.STOP,
            reason="empty_batch",
            next_batch_size=0,
            low_information_streak=state.low_information_streak,
        )
    if state.low_information_streak >= effective_config.low_information_batches_to_stop:
        return BudgetDecision(
            action=BudgetDecisionAction.STOP,
            reason="consecutive_low_information_batches",
            next_batch_size=0,
            low_information_streak=state.low_information_streak,
        )

    remaining_parent = effective_config.max_parent_comments - state.parent_comment_count
    remaining_total = effective_config.max_total_comments - state.total_comment_count
    next_batch_size = min(effective_config.batch_size, remaining_parent, remaining_total)
    reason = "high_value_source_expanded" if high_value_source else "information_still_growing"
    return BudgetDecision(
        action=BudgetDecisionAction.CONTINUE,
        reason=reason,
        next_batch_size=max(next_batch_size, 0),
        low_information_streak=state.low_information_streak,
    )


def normalize_expression(text: str | None) -> str | None:
    if not text:
        return None
    tokens = _TEXT_TOKEN_PATTERN.findall(text.lower())
    if not tokens:
        return None
    return " ".join(tokens)


def extract_regions(*texts: str | None) -> frozenset[str]:
    joined = " ".join(text for text in texts if text)
    return frozenset(region for region in _KNOWN_REGIONS if region in joined)


def extract_institutions(text: str | None) -> frozenset[str]:
    if not text:
        return frozenset()
    matches: set[str] = set()
    for token in _TEXT_TOKEN_PATTERN.findall(text):
        if 2 <= len(token) <= 16 and any(hint in token for hint in _INSTITUTION_HINTS):
            matches.add(token)
    return frozenset(matches)


def _is_low_information(
    metrics: CommentBatchMetrics,
    *,
    config: CommentBudgetConfig,
    high_value_source: bool,
) -> bool:
    min_score = config.high_value_min_information_score if high_value_source else config.min_information_score
    if metrics.has_entity_discovery:
        return False
    if high_value_source:
        return (
            metrics.information_score < min_score
            or metrics.valid_text_rate < config.min_valid_text_rate * 0.8
            or metrics.duplicate_rate > min(0.75, config.max_duplicate_rate + 0.20)
        )
    return (
        metrics.information_score < min_score
        or metrics.new_user_rate < config.min_new_user_rate
        or metrics.new_expression_rate < config.min_new_expression_rate
        or metrics.valid_text_rate < config.min_valid_text_rate
        or metrics.duplicate_rate > config.max_duplicate_rate
    )


def _advance_state(
    state: CommentBudgetState,
    batch: tuple[CommentIdentity, ...],
    metrics: CommentBatchMetrics,
    *,
    low_information_streak: int,
) -> CommentBudgetState:
    comment_ids = set(state.seen_comment_ids)
    authors = set(state.seen_author_ids)
    expressions = set(state.seen_expressions)
    regions = set(state.seen_regions)
    institutions = set(state.seen_institutions)
    parent_count = state.parent_comment_count
    total_count = state.total_comment_count

    for comment in batch:
        if comment.comment_id:
            comment_ids.add(comment.comment_id)
        if comment.author_id:
            authors.add(comment.author_id)
        expression = normalize_expression(comment.text)
        if expression:
            expressions.add(expression)
        regions.update(extract_regions(comment.region_text, comment.text))
        institutions.update(extract_institutions(comment.text))
        total_count += 1
        if not comment.is_reply:
            parent_count += 1

    return CommentBudgetState(
        seen_comment_ids=frozenset(comment_ids),
        seen_author_ids=frozenset(authors),
        seen_expressions=frozenset(expressions),
        seen_regions=frozenset(regions),
        seen_institutions=frozenset(institutions),
        parent_comment_count=parent_count,
        total_comment_count=total_count,
        low_information_streak=low_information_streak,
        metrics_history=(*state.metrics_history, metrics),
    )


def _replace_low_streak(state: CommentBudgetState, low_information_streak: int) -> CommentBudgetState:
    return CommentBudgetState(
        seen_comment_ids=state.seen_comment_ids,
        seen_author_ids=state.seen_author_ids,
        seen_expressions=state.seen_expressions,
        seen_regions=state.seen_regions,
        seen_institutions=state.seen_institutions,
        parent_comment_count=state.parent_comment_count,
        total_comment_count=state.total_comment_count,
        low_information_streak=low_information_streak,
        metrics_history=state.metrics_history,
    )


def _metrics_from_dict(payload: dict[str, Any]) -> CommentBatchMetrics:
    return CommentBatchMetrics(
        batch_size=int(payload.get("batch_size", 0) or 0),
        new_user_rate=float(payload.get("new_user_rate", 0.0) or 0.0),
        new_expression_rate=float(payload.get("new_expression_rate", 0.0) or 0.0),
        valid_text_rate=float(payload.get("valid_text_rate", 0.0) or 0.0),
        duplicate_rate=float(payload.get("duplicate_rate", 0.0) or 0.0),
        new_region_count=int(payload.get("new_region_count", 0) or 0),
        new_institution_count=int(payload.get("new_institution_count", 0) or 0),
    )


def _is_valid_text(text: str | None) -> bool:
    expression = normalize_expression(text)
    return expression is not None and len(expression.replace(" ", "")) >= 2


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 6)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
