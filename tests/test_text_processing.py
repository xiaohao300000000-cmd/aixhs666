from __future__ import annotations

from intelligence.text_processing import (
    LowInfoReason,
    extract_fields,
    is_low_information,
    normalize_text,
    process_text,
    process_texts,
)
from storage import stable_text_hash
from storage.text_hash import normalize_text_for_hash


def test_normalize_text_is_stable_and_idempotent() -> None:
    normalized = normalize_text("  福州　PET！！\n求推荐   ")

    assert normalized == "福州 PET! 求推荐"
    assert normalize_text(normalized) == normalized


def test_low_information_marks_empty_punctuation_and_generic_phrases() -> None:
    assert is_low_information("")[1] == (LowInfoReason.EMPTY,)
    assert is_low_information(" 😂😂！！！ ")[1] == (LowInfoReason.ONLY_PUNCTUATION_OR_EMOJI,)
    assert is_low_information("蹲一下")[1] == (LowInfoReason.GENERIC_SHORT_ACK,)
    assert is_low_information("福州 PET 二刷求推荐")[0] is False


def test_extract_fields_from_education_signal_text() -> None:
    fields = extract_fields("福州五年级 PET 二刷，想比较学而思英语和新东方教育，有没有试听？")

    assert fields.regions == ("福州",)
    assert fields.exams == ("PET",)
    assert fields.grades == ("五年级",)
    assert "学而思英语" in fields.institution_candidates
    assert "新东方教育" in fields.institution_candidates


def test_process_text_returns_structured_result() -> None:
    result = process_text("上海 初一 KET 压线，英孚英语怎么样？", source_id="comment-1")

    assert result.source_id == "comment-1"
    assert result.raw_text == "上海 初一 KET 压线，英孚英语怎么样？"
    assert result.normalized_text == "上海 初一 KET 压线,英孚英语怎么样?"
    assert result.is_low_information is False
    assert result.low_info_reasons == ()
    assert result.fields.regions == ("上海",)
    assert result.fields.exams == ("KET",)
    assert result.fields.grades == ("初一",)
    assert result.fields.institution_candidates == ("英孚英语",)


def test_process_texts_accepts_plain_text_and_source_pairs() -> None:
    plain_results = process_texts(["谢谢", "深圳三年级 PET 求机构"])
    paired_results = process_texts([("c1", "看看"), ("c2", "北京 FCE")])

    assert [result.source_id for result in plain_results] == ["0", "1"]
    assert plain_results[0].is_low_information is True
    assert plain_results[1].fields.regions == ("深圳",)
    assert [result.source_id for result in paired_results] == ["c1", "c2"]
    assert paired_results[1].fields.exams == ("FCE",)


def test_text_hash_uses_shared_normalization() -> None:
    assert normalize_text_for_hash("  AI\tStudy！！\nPlan  ") == "ai study! plan"
    assert stable_text_hash("AI Study!! Plan") == stable_text_hash("ai study! plan")
