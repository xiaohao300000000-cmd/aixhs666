from __future__ import annotations

import json
from typing import Any

import pytest

from services.comment_reply_generation import (
    OpenAICompatibleCommentReplyGenerator,
    validate_comment_reply_text,
)
from storage.models import LeadScreeningResult


class FakeResponse:
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "message": "可以先根据错题判断薄弱点，如果方便可以私信聊聊具体情况。"
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")


class FakeUrlopen:
    last_json: dict[str, Any]

    def __call__(self, request: Any, *, timeout: int) -> FakeResponse:
        self.last_json = json.loads(request.data.decode("utf-8"))
        return FakeResponse()


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


@pytest.mark.parametrize("text", ["", "加微信详聊", "留下手机号", "保证提分"])
def test_validate_comment_reply_rejects_unsafe_text(text: str) -> None:
    with pytest.raises(ValueError):
        validate_comment_reply_text(text)
