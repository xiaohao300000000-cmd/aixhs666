from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from integrations.feishu.bitable import FeishuBitableSettings, FeishuBitableWriteResult
from integrations.feishu.comment_replies import CommentReplySendResult, apply_comment_reply_callback, create_comment_reply_for_valid_screening
from services.comment_reply_generation import CommentReplyDraft
from services.feishu_customer_followup import push_customer_followup
from storage.database import Base
from storage.models import Comment, Content, FeishuBitableRecord, Lead, LeadCommentReply, LeadScreeningResult, PublicProfile


class Generator:
    def generate(self, screening: LeadScreeningResult) -> CommentReplyDraft:
        return CommentReplyDraft(text="可以先做一次能力诊断，再按薄弱项规划。", model_name="fake")


class CardClient:
    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        return {"message_id": "om-integration", "chat_id": chat_id}

    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}


class Sender:
    def reply_to_comment(self, **kwargs: Any) -> CommentReplySendResult:
        return CommentReplySendResult(outcome="sent", platform_reply_id="xhs-reply-1", response_json={"ok": True})


class FollowupClient:
    def __init__(self) -> None:
        self.settings = FeishuBitableSettings(enabled=True, app_id="app", app_secret="secret", app_token="followup-app", table_id="followup-table")
        self.upserts: list[tuple[str | None, dict[str, Any]]] = []

    def find_records_by_exact_field(self, field_name: str, value: str) -> list[dict[str, Any]]:
        return []

    def upsert_record(self, record_id: str | None, fields: dict[str, Any]) -> FeishuBitableWriteResult:
        self.upserts.append((record_id, fields))
        return FeishuBitableWriteResult(record_id="rec-1", dry_run=False, payload={"fields": fields}, response_json={"ok": True})


def test_create_callback_sent_then_customer_followup_upsert() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="user-integration", display_name="家长A")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id, status="qualified")
        content = Content(platform="xhs", platform_content_id="note-integration", content_type="note", author_profile_id=profile.id, title="PET备考", url="https://www.xiaohongshu.com/explore/note-integration")
        session.add_all([lead, content])
        session.flush()
        comment = Comment(platform="xhs", platform_comment_id="comment-integration", content_id=content.id, author_profile_id=profile.id, body_text="孩子PET怎么规划？")
        session.add(comment)
        session.flush()
        screening = LeadScreeningResult(platform="xhs", source_entity_type="comment", source_entity_id=comment.id, content_id=content.id, comment_id=comment.id, public_profile_id=profile.id, review_status="accepted", workflow_status="reviewed", human_review_status="valid", demand_type="PET备考", context_json={"current_comment": comment.body_text, "post_title": content.title, "source_url": content.url, "customer_name": profile.display_name})
        session.add(screening)
        session.commit()
        reply = create_comment_reply_for_valid_screening(session, screening_id=screening.id, generator=Generator(), card_client=CardClient(), chat_id="oc-review")
        assert reply.lead_id == lead.id
        reply_id = reply.id

    payload = {"token": "token", "event": {"token": "update-token", "operator": {"open_id": "ou-reviewer"}, "context": {"open_message_id": "om-integration", "open_chat_id": "oc-review"}, "action": {"name": f"confirm_comment_reply_{reply_id}", "form_value": {"comment_reply_text": "可以先做一次能力诊断，再按薄弱项规划。"}}}}
    result = apply_comment_reply_callback(factory, payload, card_client=CardClient(), sender=Sender(), verification_token="token")
    assert result.status == "sent"

    client = FollowupClient()
    sync = push_customer_followup(factory, reply_id=reply_id, client=client)
    assert sync.status == "synced"
    assert client.upserts[0][1]["客户唯一键"] == "xhs:user-integration"
    assert client.upserts[0][1]["评论发送结果"] == "评论成功"
    with factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        mapping = session.scalar(select(FeishuBitableRecord).where(FeishuBitableRecord.local_entity_id == lead.id))
        assert reply.status == "sent"
        assert mapping.record_id == "rec-1"


def test_operator_cli_replaces_unknown_card_then_retry_succeeds_once(monkeypatch, capsys) -> None:
    from apps import cli

    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="user-retry", display_name="家长B")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id, status="qualified")
        content = Content(platform="xhs", platform_content_id="note-retry", content_type="note", author_profile_id=profile.id, title="KET备考", url="https://www.xiaohongshu.com/explore/note-retry")
        session.add_all([lead, content])
        session.flush()
        comment = Comment(platform="xhs", platform_comment_id="comment-retry", content_id=content.id, author_profile_id=profile.id, body_text="怎么规划？")
        session.add(comment)
        session.flush()
        screening = LeadScreeningResult(platform="xhs", source_entity_type="comment", source_entity_id=comment.id, content_id=content.id, comment_id=comment.id, public_profile_id=profile.id, review_status="accepted", workflow_status="reviewed", human_review_status="valid", context_json={"current_comment": comment.body_text, "post_title": content.title, "source_url": content.url, "customer_name": profile.display_name})
        session.add(screening)
        session.commit()
        reply = create_comment_reply_for_valid_screening(session, screening_id=screening.id, generator=Generator(), card_client=CardClient(), chat_id="oc-review")
        reply.status = "result_unknown"
        reply.feishu_card_status = "result_unknown"
        session.commit()
        reply_id = reply.id

    class ReplacementCardClient(CardClient):
        sent_cards: list[dict[str, Any]] = []

        def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
            self.sent_cards.append(card)
            return {"message_id": "om-retry", "chat_id": chat_id}

    monkeypatch.setattr(cli, "_load_runtime_dependencies", lambda: None)
    monkeypatch.setattr(cli, "SessionLocal", factory)
    monkeypatch.setattr(cli, "PipelineRunner", lambda **kwargs: object())
    monkeypatch.setattr(cli, "load_adapter", lambda name: object())
    monkeypatch.setattr(cli, "FeishuIMClient", ReplacementCardClient)
    assert cli.main(["--json", "comment-reply-confirm-not-sent", "--reply-id", str(reply_id), "--operator", "ops@example.com", "--reason", "verified absent on XHS"]) == 0
    output = __import__("json").loads(capsys.readouterr().out)["comment_reply_not_sent_confirmation"]
    assert output["card_status"] == "replaced"
    assert ReplacementCardClient.sent_cards[0]["body"]["elements"][-1]["elements"][-1]["name"] == f"retry_comment_reply_{reply_id}"

    sender = Sender()
    retry_payload = {"token": "token", "event": {"token": "update-token", "operator": {"open_id": "ou-reviewer"}, "context": {"open_message_id": "om-retry", "open_chat_id": "oc-review"}, "action": {"name": f"retry_comment_reply_{reply_id}", "form_value": {"comment_reply_text": "可以先做一次能力诊断，再按薄弱项规划。"}}}}
    first = apply_comment_reply_callback(factory, retry_payload, card_client=CardClient(), sender=sender, verification_token="token")
    duplicate = apply_comment_reply_callback(factory, retry_payload, card_client=CardClient(), sender=sender, verification_token="token")
    assert first.status == "sent"
    assert duplicate.duplicate is True
