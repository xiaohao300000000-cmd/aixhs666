from __future__ import annotations

import json
from typing import Any
import urllib.error

import pytest

from services.comment_reply_generation import (
    OpenAICompatibleCommentReplyGenerator,
    validate_comment_reply_text,
)
from storage.models import LeadScreeningResult


class FakeResponse:
    def __init__(self, payload: object | None = None) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        payload = self.payload if self.payload is not None else _provider_payload()
        if isinstance(payload, bytes):
            return payload
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class FakeUrlopen:
    last_json: dict[str, Any]

    def __init__(self, response: FakeResponse | Exception | None = None) -> None:
        self.response = response or FakeResponse()

    def __call__(self, request: Any, *, timeout: int) -> FakeResponse:
        self.last_json = json.loads(request.data.decode("utf-8"))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture()
def fake_urlopen(monkeypatch: pytest.MonkeyPatch) -> FakeUrlopen:
    fake = FakeUrlopen()
    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fake


@pytest.fixture()
def screening() -> LeadScreeningResult:
    return LeadScreeningResult(
        platform="xhs",
        source_entity_type="comment",
        source_entity_id=1,
        context_json={
            "current_comment": "孩子 PET 阅读总是错很多，怎么提高？",
            "post_title": "PET 阅读怎么准备",
            "post_body": "分享备考方法。",
            "parent_comment": "阅读有什么好的练习方法？",
        },
        demand_type="learning_method",
        intent_strength="medium",
        qualification_decision="qualified",
    )


def test_generator_requests_helpful_optional_soft_dm_prompt(fake_urlopen: FakeUrlopen, screening: LeadScreeningResult) -> None:
    generator = OpenAICompatibleCommentReplyGenerator(api_key="key", model="model")

    draft = generator.generate(screening)

    body = fake_urlopen.last_json
    system = body["messages"][0]["content"]
    assert "先提供" in system
    assert "私信" in system
    assert draft.text == "可以先根据错题判断薄弱点，如果方便可以私信聊聊具体情况。"
    assert draft.model_name == "model"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "加微信详聊",
        "加 微 信 详聊",
        "V信联系",
        "vx：pet123",
        "wx：pet123",
        "留下手机号",
        "电话：138 0013 8000",
        "保证提分",
        "保 证 通 过",
        "包过 PET",
        "PET 稳过",
        "百分百通过",
    ],
)
def test_validate_comment_reply_rejects_unsafe_text(text: str) -> None:
    with pytest.raises(ValueError):
        validate_comment_reply_text(text)


def test_validate_comment_reply_normalizes_whitespace_and_punctuation() -> None:
    assert validate_comment_reply_text("  可以\n先看错题，\t再做专项练习！！！  ") == "可以先看错题，再做专项练习！"


def test_validate_comment_reply_allows_benign_private_message_mention() -> None:
    assert validate_comment_reply_text("可以先按错题类型练习；如果方便，私信说说孩子目前的情况。") == "可以先按错题类型练习；如果方便，私信说说孩子目前的情况。"


def test_validate_comment_reply_rejects_text_over_300_characters_after_normalization() -> None:
    with pytest.raises(ValueError, match="exceeds 300"):
        validate_comment_reply_text("答" * 301)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (b"not-json", "invalid outer JSON"),
        ({}, "missing choices"),
        ({"choices": []}, "missing choices"),
        ({"choices": [{"message": {"content": 1}}]}, "non-string content"),
        ({"choices": [{"message": {"content": "[]"}}]}, "non-object JSON content"),
        ({"choices": [{"message": {"content": "{}"}}]}, "empty message"),
    ],
)
def test_generator_reports_malformed_provider_responses(
    monkeypatch: pytest.MonkeyPatch,
    screening: LeadScreeningResult,
    payload: object,
    error: str,
) -> None:
    monkeypatch.setattr("urllib.request.urlopen", FakeUrlopen(FakeResponse(payload)))
    generator = OpenAICompatibleCommentReplyGenerator(api_key="key", model="model")

    with pytest.raises(RuntimeError, match=error):
        generator.generate(screening)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (urllib.error.URLError("offline"), "comment reply LLM request failed: offline"),
        (urllib.error.HTTPError("https://example.test", 429, "rate limited", {}, None), "HTTP 429"),
    ],
)
def test_generator_reports_provider_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
    screening: LeadScreeningResult,
    error: Exception,
    expected: str,
) -> None:
    monkeypatch.setattr("urllib.request.urlopen", FakeUrlopen(error))
    generator = OpenAICompatibleCommentReplyGenerator(api_key="key", model="model")

    with pytest.raises(RuntimeError, match=expected):
        generator.generate(screening)


def _provider_payload() -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"message": "可以先根据错题判断薄弱点，如果方便可以私信聊聊具体情况。"},
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }
