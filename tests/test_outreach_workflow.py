from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from integrations.feishu.outreach import (
    apply_outreach_callback,
    build_outreach_approval_card,
    create_outreach_for_valid_screening,
    send_approved_outreach,
)
from services.outreach_generation import OutreachDraft
from storage.database import Base
from storage.models import LeadOutreachMessage, LeadScreeningResult, PublicProfile


class FakeOutreachGenerator:
    def generate(self, screening: LeadScreeningResult) -> OutreachDraft:
        return OutreachDraft(text=f"你好，看到你在问：{screening.context_json['current_comment']}，想了解孩子几年级？", model_name="fake")


class FakeCardClient:
    def __init__(self) -> None:
        self.sent_cards: list[dict[str, Any]] = []
        self.updated_cards: list[dict[str, Any]] = []

    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        self.sent_cards.append(card)
        return {"message_id": "om_outreach_1", "chat_id": chat_id}

    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
        self.updated_cards.append({"token": token, "card": card})
        return {"ok": True}


class FailingUpdateCardClient(FakeCardClient):
    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("card update failed")


class FakeXhsSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send_message(self, *, profile_url: str, text: str) -> dict[str, str]:
        self.sent.append({"profile_url": profile_url, "text": text})
        return {"status": "sent"}


class FailingXhsSender:
    def send_message(self, *, profile_url: str, text: str) -> dict[str, str]:
        raise RuntimeError("xhs send failed")


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield SessionLocal
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_valid_screening_creates_outreach_card_once(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_valid_screening(factory)
    card_client = FakeCardClient()

    with factory() as session:
        outreach = create_outreach_for_valid_screening(
            session,
            screening_id=screening_id,
            generator=FakeOutreachGenerator(),
            card_client=card_client,
            chat_id="oc_review",
        )
        duplicate = create_outreach_for_valid_screening(
            session,
            screening_id=screening_id,
            generator=FakeOutreachGenerator(),
            card_client=card_client,
            chat_id="oc_review",
        )
        session.commit()

    assert outreach is not None
    assert duplicate is not None
    assert outreach.id == duplicate.id
    assert len(card_client.sent_cards) == 1
    card_text = str(card_client.sent_cards[0])
    assert "话术审批" in card_text
    assert "message_text" in card_text
    assert "发送" in card_text

    with factory() as session:
        saved = session.scalar(select(LeadOutreachMessage))
        assert saved is not None
        assert saved.status == "card_sent"
        assert saved.generated_text.startswith("你好")
        assert saved.feishu_message_id == "om_outreach_1"


def test_outreach_callback_approves_edited_text_without_sending_xhs(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_valid_screening(factory)
    card_client = FakeCardClient()
    xhs_sender = FakeXhsSender()

    with factory() as session:
        outreach = create_outreach_for_valid_screening(
            session,
            screening_id=screening_id,
            generator=FakeOutreachGenerator(),
            card_client=card_client,
            chat_id="oc_review",
        )
        session.commit()
        outreach_id = outreach.id

    with factory() as session:
        result = apply_outreach_callback(
            session,
            _outreach_payload(outreach_id, "您好，孩子现在几年级？"),
            card_client=card_client,
            verification_token="token",
        )
        session.commit()

    assert result.applied is True
    assert result.status == "approved_to_send"
    assert xhs_sender.sent == []
    assert len(card_client.updated_cards) == 1
    assert "待发送" in str(card_client.updated_cards[0]["card"])

    with factory() as session:
        saved = session.get(LeadOutreachMessage, outreach_id)
        assert saved is not None
        assert saved.status == "approved_to_send"
        assert saved.final_text == "您好，孩子现在几年级？"
        assert saved.sent_at is None


def test_outreach_callback_is_idempotent(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_valid_screening(factory)
    xhs_sender = FakeXhsSender()

    with factory() as session:
        outreach = create_outreach_for_valid_screening(
            session,
            screening_id=screening_id,
            generator=FakeOutreachGenerator(),
            card_client=FakeCardClient(),
            chat_id="oc_review",
        )
        session.commit()
        outreach_id = outreach.id

    with factory() as session:
        first = apply_outreach_callback(
            session,
            _outreach_payload(outreach_id, "第一条"),
            card_client=FakeCardClient(),
            verification_token="token",
        )
        duplicate = apply_outreach_callback(
            session,
            _outreach_payload(outreach_id, "第二条"),
            card_client=FakeCardClient(),
            verification_token="token",
        )
        session.commit()

    assert first.applied is True
    assert duplicate.applied is False
    assert duplicate.duplicate is True
    assert xhs_sender.sent == []


def test_send_approved_outreach_records_send_failure(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_valid_screening(factory)
    card_client = FakeCardClient()

    with factory() as session:
        outreach = create_outreach_for_valid_screening(
            session,
            screening_id=screening_id,
            generator=FakeOutreachGenerator(),
            card_client=card_client,
            chat_id="oc_review",
        )
        session.commit()
        outreach_id = outreach.id

    with factory() as session:
        approval = apply_outreach_callback(
            session,
            _outreach_payload(outreach_id, "失败测试"),
            card_client=card_client,
            verification_token="token",
        )
        result = send_approved_outreach(
            session,
            outreach_id=outreach_id,
            xhs_sender=FailingXhsSender(),
        )
        session.commit()

    assert approval.status == "approved_to_send"
    assert result.applied is True
    assert result.status == "failed"

    with factory() as session:
        saved = session.get(LeadOutreachMessage, outreach_id)
        assert saved is not None
        assert saved.status == "failed"
        assert saved.feishu_card_status == "failed"
        assert saved.attempt_count == 1
        assert saved.last_error == "xhs send failed"


def test_outreach_callback_persists_approval_when_card_update_fails(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_valid_screening(factory)

    with factory() as session:
        outreach = create_outreach_for_valid_screening(
            session,
            screening_id=screening_id,
            generator=FakeOutreachGenerator(),
            card_client=FakeCardClient(),
            chat_id="oc_review",
        )
        session.commit()
        outreach_id = outreach.id

    with factory() as session:
        result = apply_outreach_callback(
            session,
            _outreach_payload(outreach_id, "失败测试"),
            card_client=FailingUpdateCardClient(),
            verification_token="token",
        )
        session.commit()

    assert result.applied is True
    assert result.status == "approved_to_send"

    with factory() as session:
        saved = session.get(LeadOutreachMessage, outreach_id)
        assert saved is not None
        assert saved.status == "approved_to_send"
        assert saved.last_error is not None
        assert "card update failed" in saved.last_error


def _seed_valid_screening(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        profile = PublicProfile(
            platform="xhs",
            platform_user_id="u1",
            display_name="家长",
            profile_url="https://www.xiaohongshu.com/user/profile/u1",
        )
        session.add(profile)
        session.flush()
        screening = LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=1,
            public_profile_id=profile.id,
            review_status="accepted",
            workflow_status="reviewed",
            human_review_status="valid",
            demand_type="KET/PET咨询",
            intent_strength="high",
            confidence=90,
            context_json={
                "current_comment": "怎么入门呢",
                "post_title": "KET/PET备考规划",
                "source_url": "https://www.xiaohongshu.com/explore/note-1",
            },
        )
        session.add(screening)
        session.commit()
        return int(screening.id)


def _outreach_payload(outreach_id: int, text: str) -> dict[str, Any]:
    return {
        "token": "token",
        "event": {
            "token": "update-token",
            "operator": {"open_id": "ou_reviewer"},
            "context": {"open_message_id": "om_outreach_1", "open_chat_id": "oc_review"},
            "action": {
                "name": f"send_outreach_{outreach_id}",
                "form_value": {"message_text": text},
            },
        },
    }
