from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from integrations.feishu import FeishuPhraseReviewPayload, build_phrase_review_payloads


def prepare_feishu_phrase_review_payloads(candidates: Iterable[Any]) -> list[FeishuPhraseReviewPayload]:
    return build_phrase_review_payloads(candidates)
