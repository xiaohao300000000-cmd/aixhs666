from __future__ import annotations

from intelligence.clustering import build_semantic_signature, cluster_texts, semantic_similarity
from intelligence.phrase_discovery import (
    PhraseCandidate,
    approved_candidate_to_query_text,
    discover_phrase_candidates,
)


def test_semantic_signature_similarity_weights_shared_domain_signals() -> None:
    left = build_semantic_signature("福州 PET 压线，准备二刷，求推荐冲刺机构")
    right = build_semantic_signature("福州五年级 PET 没过，想找二刷冲刺班")
    unrelated = build_semantic_signature("上海初一托福资料怎么选")

    assert semantic_similarity(left, right) > semantic_similarity(left, unrelated)
    assert "exam:PET" in left.token_weights
    assert "region:福州" in left.token_weights
    assert "intent:exam_retry" in left.token_weights


def test_cluster_texts_generates_stable_clusters_with_representatives() -> None:
    texts = [
        "福州 PET 压线，准备二刷，求推荐冲刺机构",
        "福州五年级 PET 没过，想找二刷冲刺班",
        "上海 KET 试听课哪家机构靠谱",
        "上海 KET 想约试听，比较一下机构",
    ]

    first = cluster_texts(texts)
    second = cluster_texts(list(reversed(texts)))

    assert len(first) == 2
    assert sorted(len(cluster.member_indices) for cluster in first) == [2, 2]
    assert all(cluster.representative_examples for cluster in first)
    assert [cluster.name for cluster in first] == [cluster.name for cluster in second]


def test_discover_phrase_candidates_scores_and_counts_new_expressions() -> None:
    texts = [
        "福州 PET 压线，准备二刷，求推荐冲刺机构",
        "福州 PET 二刷，暑假冲刺班有没有推荐",
        "福州 PET 二刷压线，想比较机构价格",
        "上海 KET 试听课哪家机构靠谱",
    ]

    candidates = discover_phrase_candidates(texts, existing_phrases={"推荐"}, min_source_text_count=2)
    by_phrase = {candidate.phrase: candidate for candidate in candidates}

    assert by_phrase["福州"].source_text_count == 3
    assert by_phrase["PET"].source_text_count == 3
    assert by_phrase["二刷"].source_text_count == 3
    assert by_phrase["压线"].source_text_count == 2
    assert by_phrase["二刷"].novelty_score > 0
    assert by_phrase["二刷"].query_potential_score >= by_phrase["福州"].query_potential_score
    assert by_phrase["二刷"].representative_examples
    assert "推荐" not in by_phrase


def test_approved_candidate_to_query_text_is_pure_and_deduplicates_context() -> None:
    candidate = PhraseCandidate(
        phrase="二刷",
        source_text_count=3,
        novelty_score=0.8,
        query_potential_score=0.9,
        representative_examples=("福州 PET 二刷",),
    )

    assert approved_candidate_to_query_text(candidate, region="福州", exam="PET") == "福州 PET 二刷"
    assert approved_candidate_to_query_text("PET", region="福州", exam="PET") == "福州 PET"
