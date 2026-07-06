from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import create_app
from apps.cli import main as cli_main
from integrations.feishu.llm_review import (
    LLM_REVIEW_EVENT_TYPE,
    apply_llm_review_callback,
    build_llm_review_card,
    send_pending_llm_review_cards,
)
from integrations.feishu.im import FeishuIMClient, FeishuIMSettings
from storage.database import Base
from storage.models import CollectionEvent, Lead, LeadEvidence, LeadScreeningResult, PublicProfile


class FakeReviewCardClient:
    def __init__(self) -> None:
        self.sent_cards: list[dict[str, Any]] = []
        self.updated_cards: list[dict[str, Any]] = []

    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        self.sent_cards.append(card)
        return {"message_id": "om_review_1", "chat_id": chat_id}

    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
        self.updated_cards.append({"token": token, "card": card})
        return {"ok": True}


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


def test_send_pending_llm_review_card_saves_message_id(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_pending_screening(factory)
    client = FakeReviewCardClient()

    with factory() as session:
        result = send_pending_llm_review_cards(session, client=client, chat_id="oc_review", limit=1)
        session.commit()

    assert result == {"sent": 1, "skipped": 0, "failed": 0}
    assert len(client.sent_cards) == 1
    card_text = json.dumps(client.sent_cards[0], ensure_ascii=False)
    assert "原文" in card_text
    assert "上下文摘要" in card_text
    assert "AI判断" in card_text
    assert "意向等级" in card_text
    assert "置信度" in card_text
    assert "有效" in card_text
    assert "无效" in card_text
    assert "暂时观察" in card_text

    with factory() as session:
        screening = session.get(LeadScreeningResult, screening_id)
        assert screening is not None
        assert screening.feishu_message_id == "om_review_1"
        assert screening.feishu_chat_id == "oc_review"
        assert screening.feishu_card_status == "sent"
        assert screening.workflow_status == "sent"


def test_llm_review_callback_updates_database_once_and_updates_card(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_pending_screening(factory, with_lead=True)
    client = FakeReviewCardClient()

    with factory() as session:
        first = apply_llm_review_callback(
            session,
            _review_payload("evt-1", screening_id, "valid"),
            client=client,
            verification_token="token",
            now=datetime(2026, 7, 6, tzinfo=UTC),
        )
        duplicate = apply_llm_review_callback(
            session,
            _review_payload("evt-2", screening_id, "valid"),
            client=client,
            verification_token="token",
            now=datetime(2026, 7, 6, tzinfo=UTC),
        )
        session.commit()

    assert first.applied is True
    assert first.duplicate is False
    assert duplicate.applied is False
    assert duplicate.duplicate is True
    assert len(client.updated_cards) == 1
    updated_text = json.dumps(client.updated_cards[0]["card"], ensure_ascii=False)
    assert "已处理" in updated_text
    assert "有效" in updated_text

    with factory() as session:
        screening = session.get(LeadScreeningResult, screening_id)
        assert screening is not None
        assert screening.human_review_status == "valid"
        assert screening.human_reviewer_id == "ou_reviewer"
        assert screening.feishu_card_status == "processed"
        assert screening.human_reviewed_at.replace(tzinfo=UTC) == datetime(2026, 7, 6, tzinfo=UTC)
        lead = session.scalar(select(Lead))
        assert lead is not None
        assert lead.status == "qualified"
        events = session.scalars(select(CollectionEvent).where(CollectionEvent.event_type == LLM_REVIEW_EVENT_TYPE)).all()
        assert len(events) == 1
        assert events[0].event_data["screening_result_id"] == screening_id


def test_llm_review_callback_rejects_bad_token(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_pending_screening(factory)

    with factory() as session:
        with pytest.raises(ValueError, match="invalid Feishu verification token"):
            apply_llm_review_callback(
                session,
                _review_payload("evt-1", screening_id, "invalid"),
                client=FakeReviewCardClient(),
                verification_token="expected",
            )


def test_fastapi_llm_review_callback_verifies_signature_and_applies(
    factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screening_id = _seed_pending_screening(factory)
    fake_client = FakeReviewCardClient()
    monkeypatch.setattr("apps.api.routes.feishu_callbacks.SessionLocal", factory)
    monkeypatch.setattr("apps.api.routes.feishu_callbacks.FeishuIMClient", lambda: fake_client)
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "token")
    monkeypatch.setenv("FEISHU_ENCRYPT_KEY", "secret")
    payload = _review_payload("evt-route", screening_id, "watch")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    timestamp = "1782970000"
    nonce = "nonce"
    signature = base64.b64encode(
        hmac.new("secret".encode("utf-8"), f"{timestamp}{nonce}".encode("utf-8") + body, hashlib.sha256).digest()
    ).decode("utf-8")

    response = TestClient(create_app()).post(
        "/feishu/callback/llm-review",
        content=body,
        headers={
            "x-lark-request-timestamp": timestamp,
            "x-lark-request-nonce": nonce,
            "x-lark-signature": signature,
            "content-type": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.json()["applied"] is True
    with factory() as session:
        assert session.get(LeadScreeningResult, screening_id).human_review_status == "watch"


def test_build_llm_review_card_has_exactly_three_business_buttons(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_pending_screening(factory)
    with factory() as session:
        card = build_llm_review_card(session.get(LeadScreeningResult, screening_id))

    assert card["schema"] == "2.0"
    buttons = [element for element in card["body"]["elements"] if element.get("tag") == "button"]
    assert len(buttons) == 3
    button_labels = [button["text"]["content"] for button in buttons]
    assert button_labels == ["有效", "无效", "暂时观察"]
    assert [button["behaviors"][0]["type"] for button in buttons] == ["callback", "callback", "callback"]
    assert [button["behaviors"][0]["value"]["action"] for button in buttons] == ["valid", "invalid", "watch"]


def test_feishu_send_llm_reviews_cli_sends_pending_cards(
    factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_pending_screening(factory)
    fake_client = FakeReviewCardClient()
    monkeypatch.setattr("apps.cli.SessionLocal", factory)
    monkeypatch.setattr("apps.cli.FeishuIMClient", lambda: fake_client)

    exit_code = cli_main(["--json", "feishu-send-llm-reviews", "--chat-id", "oc_review", "--limit", "1"])

    assert exit_code == 0
    assert '"sent": 1' in capsys.readouterr().out
    with factory() as session:
        assert session.scalar(select(LeadScreeningResult)).feishu_message_id == "om_review_1"


def test_feishu_im_lark_cli_transport_sends_and_updates_cards() -> None:
    calls: list[tuple[list[str], str | None]] = []

    def runner(args: list[str], stdin: str | None) -> str:
        calls.append((args, stdin))
        if args[1:3] == ["im", "+messages-send"]:
            return json.dumps({"data": {"message": {"message_id": "om_cli_1", "chat_id": "oc_cli"}}})
        return json.dumps({"code": 0, "data": {}})

    client = FeishuIMClient(
        settings=FeishuIMSettings(
            enabled=True,
            app_id=None,
            app_secret=None,
            review_chat_id=None,
            transport="lark_cli",
            lark_cli_bin="lark-cli",
            lark_cli_as="user",
        ),
        command_runner=runner,
    )

    sent = client.send_interactive_card(chat_id="oc_cli", card={"config": {}, "elements": []})
    updated = client.update_interactive_card(token="update-token", card={"config": {}, "elements": []})

    assert sent == {"message_id": "om_cli_1", "chat_id": "oc_cli"}
    assert updated["code"] == 0
    assert calls[0][0][:3] == ["lark-cli", "im", "+messages-send"]
    assert "--msg-type" in calls[0][0]
    assert calls[1][0][:4] == ["lark-cli", "api", "POST", "/open-apis/interactive/v1/card/update"]


def _seed_pending_screening(factory: sessionmaker[Session], *, with_lead: bool = False) -> int:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="user-1", display_name="福州家长")
        session.add(profile)
        session.flush()
        screening = LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=101,
            comment_id=101,
            public_profile_id=profile.id,
            model_name="deepseek-v4-flash",
            valuable=False,
            demand_type="price",
            intent_strength="medium",
            confidence=48,
            judgment_evidence_json=["询问 PET 冲刺班价格和试听"],
            context_json={
                "post_title": "PET 二刷怎么准备",
                "post_body": "孩子压线，家长在讨论暑假冲刺。",
                "current_comment": "PET 冲刺班多少钱，可以试听吗？",
                "parent_comment": "福州哪家机构靠谱？",
            },
            llm_raw_json={"reason": "语境不足，需要人工确认"},
            review_status="needs_review",
            status_reason="置信度不足，需要人工确认",
            workflow_status="pending_feishu",
        )
        session.add(screening)
        session.flush()
        if with_lead:
            lead = Lead(platform="xhs", public_profile_id=profile.id, status="needs_review", intent_score=48)
            session.add(lead)
            session.flush()
            session.add(
                LeadEvidence(
                    lead_id=lead.id,
                    source_entity_type="comment",
                    source_entity_id=101,
                    comment_id=101,
                    evidence_text="PET 冲刺班多少钱，可以试听吗？",
                    demand_type="price",
                    intent_stage="evaluating",
                    score_contribution=48,
                )
            )
        session.commit()
        return screening.id


def _review_payload(event_id: str, screening_id: int, action: str) -> dict[str, Any]:
    return {
        "token": "token",
        "header": {"event_id": event_id},
        "event": {
            "operator": {"open_id": "ou_reviewer"},
            "token": "card-update-token",
            "context": {"open_message_id": "om_review_1", "open_chat_id": "oc_review"},
            "action": {
                "value": {
                    "screening_result_id": screening_id,
                    "action": action,
                }
            },
        },
    }
