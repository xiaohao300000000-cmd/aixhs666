from __future__ import annotations

import pytest

from apps.worker.phrase_review import prepare_feishu_phrase_review_payloads
from integrations.feishu import (
    PhraseReviewAction,
    PhraseReviewState,
    PhraseReviewStatus,
    apply_phrase_review_action,
    build_phrase_review_payload,
    phrase_review_to_query_request,
)
from intelligence.phrase_discovery import PhraseCandidate


def test_build_phrase_review_payload_contains_card_actions_without_network_io() -> None:
    candidate = PhraseCandidate(
        phrase="二刷",
        source_text_count=3,
        novelty_score=0.8123,
        query_potential_score=0.9234,
        representative_examples=("福州 PET 二刷求推荐",),
    )

    payload = build_phrase_review_payload(candidate, candidate_id="cand-1")

    assert payload.message_type == "interactive"
    assert payload.candidate_id == "cand-1"
    assert payload.card["header"]["title"]["content"] == "新词审核"
    assert "二刷" in payload.card["elements"][0]["content"]
    actions = payload.card["elements"][-1]["actions"]
    assert {action["value"]["action"] for action in actions} == {
        PhraseReviewAction.APPROVE.value,
        PhraseReviewAction.REJECT.value,
        PhraseReviewAction.CONVERT_TO_QUERY.value,
    }


def test_phrase_review_actions_approve_reject_and_convert_statuses() -> None:
    pending = PhraseReviewState(candidate_id="cand-1", phrase="二刷")

    approved = apply_phrase_review_action(pending, PhraseReviewAction.APPROVE, reviewer_id="user-a")
    rejected = apply_phrase_review_action(pending, PhraseReviewAction.REJECT, reviewer_id="user-b", reason="重复")
    converted = apply_phrase_review_action(
        approved,
        PhraseReviewAction.CONVERT_TO_QUERY,
        reviewer_id="user-a",
        query_text="福州 PET 二刷",
    )

    assert approved.status == PhraseReviewStatus.APPROVED
    assert approved.reviewer_id == "user-a"
    assert rejected.status == PhraseReviewStatus.REJECTED
    assert rejected.review_reason == "重复"
    assert converted.status == PhraseReviewStatus.CONVERTED_TO_QUERY
    assert converted.query_text == "福州 PET 二刷"


def test_illegal_phrase_review_transition_raises() -> None:
    pending = PhraseReviewState(candidate_id="cand-1", phrase="二刷")
    rejected = apply_phrase_review_action(pending, PhraseReviewAction.REJECT)

    with pytest.raises(ValueError, match="illegal phrase review transition"):
        apply_phrase_review_action(rejected, PhraseReviewAction.APPROVE)

    with pytest.raises(ValueError, match="illegal phrase review transition"):
        apply_phrase_review_action(pending, PhraseReviewAction.CONVERT_TO_QUERY)


def test_approved_or_converted_review_can_create_query_request() -> None:
    approved = PhraseReviewState(candidate_id="cand-1", phrase="二刷", status=PhraseReviewStatus.APPROVED)
    converted = PhraseReviewState(
        candidate_id="cand-2",
        phrase="压线",
        status=PhraseReviewStatus.CONVERTED_TO_QUERY,
        query_text="福州 PET 压线",
    )

    approved_request = phrase_review_to_query_request(approved, region="福州", exam="PET")
    converted_request = phrase_review_to_query_request(converted)

    assert approved_request.query_text == "福州 PET 二刷"
    assert approved_request.platform == "xhs"
    assert approved_request.metadata["candidate_id"] == "cand-1"
    assert converted_request.query_text == "福州 PET 压线"


def test_pending_review_cannot_create_query_request() -> None:
    pending = PhraseReviewState(candidate_id="cand-1", phrase="二刷")

    with pytest.raises(ValueError, match="cannot create query"):
        phrase_review_to_query_request(pending)


def test_worker_prepares_review_payloads_for_candidate_list() -> None:
    payloads = prepare_feishu_phrase_review_payloads(
        [
            {
                "candidate_id": "cand-1",
                "phrase": "二刷",
                "source_text_count": 3,
                "novelty_score": 0.8,
                "query_potential_score": 0.9,
                "representative_examples": ["福州 PET 二刷"],
            }
        ]
    )

    assert len(payloads) == 1
    assert payloads[0].candidate_id == "cand-1"
