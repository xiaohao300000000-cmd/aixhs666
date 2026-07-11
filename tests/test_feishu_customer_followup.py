from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from integrations.feishu.bitable import FeishuBitableSettings, FeishuBitableWriteResult
from services.feishu_customer_followup import pull_customer_followup_edits, push_customer_followup
from storage.database import Base
from storage.models import Comment, Content, FeishuBitableRecord, Lead, LeadCommentReply, LeadScreeningResult, PublicProfile


class FakeBitableClient:
    def __init__(self) -> None:
        self.settings = FeishuBitableSettings(
            enabled=True,
            app_id="app-id",
            app_secret="app-secret",
            app_token="followup-app",
            table_id="followup-table",
        )
        self.upserts: list[tuple[str | None, dict[str, object]]] = []
        self.remote_records: list[dict[str, object]] = []
        self.error: Exception | None = None

    def upsert_record(self, record_id: str | None, fields: dict[str, object]) -> FeishuBitableWriteResult:
        if self.error is not None:
            raise self.error
        self.upserts.append((record_id, fields))
        return FeishuBitableWriteResult(record_id=record_id or "rec-customer", dry_run=False, payload={"fields": fields})

    def list_records(self) -> list[dict[str, object]]:
        if self.error is not None:
            raise self.error
        return self.remote_records


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    engine.dispose()


def test_push_maps_sent_reply_and_upserts_idempotently(factory: sessionmaker[Session]) -> None:
    lead_id, reply_id = _seed_customer(factory, reply_status="sent")
    client = FakeBitableClient()

    first = push_customer_followup(factory, reply_id=reply_id, client=client)
    second = push_customer_followup(factory, reply_id=reply_id, client=client)

    assert first.status == second.status == "synced"
    assert client.upserts[0][0] is None
    assert client.upserts[1][0] == "rec-customer"
    assert client.upserts[0][1]["客户唯一键"] == "xhs:user-1"
    assert client.upserts[0][1]["当前客户状态"] == "已评论引导，等待客户私信"
    assert client.upserts[0][1]["评论发送结果"] == "评论成功"
    with factory() as session:
        mappings = session.scalars(select(FeishuBitableRecord)).all()
        assert len(mappings) == 1
        assert mappings[0].local_entity_type == "customer_followup"
        assert mappings[0].local_entity_id == lead_id


def test_pull_accepts_only_human_fields_and_preserves_system_facts(factory: sessionmaker[Session]) -> None:
    lead_id, reply_id = _seed_customer(factory, reply_status="sent", lead_status="qualified")
    client = FakeBitableClient()
    push_customer_followup(factory, reply_id=reply_id, client=client)
    client.remote_records = [
        {
            "record_id": "rec-customer",
            "fields": {
                "客户唯一键": "xhs:user-1",
                "负责人": "小王",
                "运营备注": "客户已主动私信",
                "下次跟进时间": "2026-07-15 10:00:00",
                "当前客户状态": "已收到私信",
                "评论发送结果": "未发送",
                "评论回复记录 ID": "999999",
            },
        }
    ]

    result = pull_customer_followup_edits(factory, client=client)

    assert result.status == "synced"
    with factory() as session:
        lead = session.get(Lead, lead_id)
        reply = session.get(LeadCommentReply, reply_id)
        assert lead is not None and reply is not None
        assert lead.followup_status == "已收到私信"
        assert lead.owner_name == "小王"
        assert lead.operator_note == "客户已主动私信"
        assert lead.next_followup_at.isoformat().startswith("2026-07-15T10:00:00")
        assert lead.status == "qualified"
        assert reply.status == "sent"


@pytest.mark.parametrize("human_status", ["已收到私信", "沟通中", "已成交", "已忽略"])
def test_push_never_regresses_terminal_human_status(factory: sessionmaker[Session], human_status: str) -> None:
    lead_id, reply_id = _seed_customer(factory, reply_status="sent", followup_status=human_status)
    client = FakeBitableClient()

    push_customer_followup(factory, reply_id=reply_id, client=client)

    assert client.upserts[0][1]["当前客户状态"] == human_status
    with factory() as session:
        assert session.get(Lead, lead_id).followup_status == human_status


def test_push_failure_is_recorded_without_mutating_reply(factory: sessionmaker[Session]) -> None:
    _, reply_id = _seed_customer(factory, reply_status="sent")
    client = FakeBitableClient()
    client.error = RuntimeError("base unavailable")

    result = push_customer_followup(factory, reply_id=reply_id, client=client)

    assert result.status == "failed"
    with factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        mapping = session.scalar(select(FeishuBitableRecord))
        assert reply is not None and mapping is not None
        assert reply.status == "sent"
        assert mapping.last_sync_status == "failed"
        assert mapping.last_error == "base unavailable"


def _seed_customer(
    factory: sessionmaker[Session],
    *,
    reply_status: str,
    lead_status: str = "new",
    followup_status: str | None = None,
) -> tuple[int, int]:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="user-1", display_name="家长")
        session.add(profile)
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id="note-1",
            content_type="note",
            author_profile_id=profile.id,
            url="https://www.xiaohongshu.com/explore/note-1",
        )
        lead = Lead(
            platform="xhs",
            public_profile_id=profile.id,
            status=lead_status,
            followup_status=followup_status,
        )
        session.add_all([content, lead])
        session.flush()
        comment = Comment(
            platform="xhs",
            platform_comment_id="comment-1",
            content_id=content.id,
            author_profile_id=profile.id,
            body_text="孩子备考 PET 应该怎么规划？",
        )
        session.add(comment)
        session.flush()
        screening = LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=comment.id,
            content_id=content.id,
            comment_id=comment.id,
            public_profile_id=profile.id,
            demand_type="PET备考",
            human_review_status="valid",
        )
        session.add(screening)
        session.flush()
        reply = LeadCommentReply(
            screening_result_id=screening.id,
            lead_id=lead.id,
            target_comment_id=comment.id,
            target_platform_comment_id=comment.platform_comment_id,
            target_content_id=content.id,
            target_platform_content_id=content.platform_content_id,
            target_url=content.url,
            draft_text="可以先做一次能力诊断。",
            approved_text="可以先做一次能力诊断。",
            status=reply_status,
            sent_at=datetime(2026, 7, 12, 9, 30, tzinfo=UTC) if reply_status == "sent" else None,
            platform_reply_id="reply-1" if reply_status == "sent" else None,
            last_error=None,
        )
        session.add(reply)
        session.commit()
        return lead.id, reply.id
