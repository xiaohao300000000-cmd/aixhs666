from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from integrations.feishu.bitable import FeishuBitableSettings, FeishuBitableWriteResult
from services.feishu_ai_review_sync import sync_feishu_ai_review_rows
from storage.database import Base
from storage.models import Comment, Content, FeishuBitableRecord, LeadScreeningResult, PublicProfile


class FakeBitableClient:
    def __init__(self, *, table_id: str) -> None:
        self.settings = FeishuBitableSettings(
            enabled=True,
            app_id=None,
            app_secret=None,
            app_token="base_token",
            table_id=table_id,
            transport="lark_cli",
        )
        self.upserts: list[tuple[str | None, dict[str, object]]] = []
        self._created = 0

    def upsert_record(self, record_id: str | None, fields: dict[str, object]) -> FeishuBitableWriteResult:
        self.upserts.append((record_id, fields))
        if record_id is None:
            self._created += 1
            record_id = f"{self.settings.table_id}_rec_{self._created}"
        return FeishuBitableWriteResult(record_id=record_id, dry_run=False, payload={"fields": fields})


def test_feishu_ai_review_sync_writes_deepseek_result_to_customer_and_evidence_tables(
    factory: sessionmaker[Session],
) -> None:
    customer_client = FakeBitableClient(table_id="customer_table")
    evidence_client = FakeBitableClient(table_id="evidence_table")
    with factory() as session:
        screening_id = _seed_screening(session)
        result = sync_feishu_ai_review_rows(
            session,
            customer_client=customer_client,
            evidence_client=evidence_client,
        )
        session.commit()

    assert result.to_dict() == {
        "customers_created": 1,
        "customers_updated": 0,
        "evidence_created": 1,
        "evidence_updated": 0,
        "dry_run": 0,
        "skipped": 0,
        "failed": 0,
    }
    customer_fields = customer_client.upserts[0][1]
    evidence_fields = evidence_client.upserts[0][1]
    assert list(customer_fields)[:6] == ["需求摘要", "意向程度", "下一步", "状态", "证据数量", "为什么推荐"]
    assert customer_fields["客户"] == "福州家长"
    assert customer_fields["平台用户ID"] == "u1"
    assert customer_fields["状态"] == "待确认"
    assert "DeepSeek=needs_review" in str(customer_fields["为什么推荐"])
    assert "Campaign=needs_review" in str(customer_fields["为什么推荐"])
    assert "福州" in str(customer_fields["为什么推荐"])
    assert f"screening-{screening_id}" in str(evidence_fields["证据标题"])
    assert list(evidence_fields)[:6] == ["证据标题", "抓取原文", "证据类型", "AI判断", "置信度", "为什么推荐"]
    assert evidence_fields["AI判断"] == "needs_review"
    assert evidence_fields["置信度"] == 68
    assert evidence_fields["关联客户线索"] == ["customer_table_rec_1"]
    assert customer_client.upserts[-1][1]["关联证据明细"] == ["evidence_table_rec_1"]

    with factory() as session:
        mappings = session.scalars(select(FeishuBitableRecord).order_by(FeishuBitableRecord.local_entity_type)).all()
        assert [(item.local_entity_type, item.local_entity_id, item.record_id) for item in mappings] == [
            ("ai_review_customer", 1, "customer_table_rec_1"),
            ("ai_review_evidence", screening_id, "evidence_table_rec_1"),
        ]


def test_feishu_ai_review_sync_is_idempotent_and_updates_existing_records(factory: sessionmaker[Session]) -> None:
    customer_client = FakeBitableClient(table_id="customer_table")
    evidence_client = FakeBitableClient(table_id="evidence_table")
    with factory() as session:
        _seed_screening(session)
        first = sync_feishu_ai_review_rows(session, customer_client=customer_client, evidence_client=evidence_client)
        second = sync_feishu_ai_review_rows(session, customer_client=customer_client, evidence_client=evidence_client)
        session.commit()

    assert first.customers_created == 1
    assert first.evidence_created == 1
    assert second.customers_updated == 1
    assert second.evidence_updated == 1
    assert customer_client.upserts[2][0] == "customer_table_rec_1"
    assert evidence_client.upserts[1][0] == "evidence_table_rec_1"

    with factory() as session:
        assert session.query(FeishuBitableRecord).count() == 2


def test_feishu_ai_review_sync_skips_rejected_screenings(factory: sessionmaker[Session]) -> None:
    customer_client = FakeBitableClient(table_id="customer_table")
    evidence_client = FakeBitableClient(table_id="evidence_table")
    with factory() as session:
        _seed_screening(session, review_status="rejected", valuable=False)
        result = sync_feishu_ai_review_rows(session, customer_client=customer_client, evidence_client=evidence_client)
        session.commit()

    assert result.skipped == 1
    assert customer_client.upserts == []
    assert evidence_client.upserts == []


def test_feishu_ai_review_sync_cli_outputs_counts(
    factory: sessionmaker[Session],
    monkeypatch,
    capsys,
) -> None:
    import apps.cli as cli

    class StubRunner:
        def __init__(self, **_: object) -> None:
            pass

    with factory() as session:
        _seed_screening(session)
        session.commit()

    monkeypatch.setattr(cli, "PipelineRunner", StubRunner)
    monkeypatch.setattr(cli, "load_adapter", lambda _: object())
    monkeypatch.setattr(cli, "SessionLocal", factory)
    monkeypatch.setattr(
        "services.feishu_ai_review_sync.FeishuBitableClient",
        lambda settings=None: FakeBitableClient(table_id=settings.table_id),
    )

    exit_code = cli.main(["--json", "feishu-ai-review-sync"])

    assert exit_code == 0
    assert '"customers_created": 1' in capsys.readouterr().out


def _seed_screening(
    session: Session,
    *,
    review_status: str = "needs_review",
    valuable: bool = True,
) -> int:
    now = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    profile = PublicProfile(
        platform="xhs",
        platform_user_id="u1",
        display_name="福州家长",
        profile_url="https://www.xiaohongshu.com/user/profile/u1",
        region_text="福建 福州",
    )
    session.add(profile)
    session.flush()
    content = Content(
        platform="xhs",
        platform_content_id="note1",
        content_type="note",
        author_profile_id=profile.id,
        title="PET 二刷",
        body_text="孩子阅读弱",
        url="https://www.xiaohongshu.com/explore/note1",
        region_text="福建",
        published_at=now,
    )
    session.add(content)
    session.flush()
    comment = Comment(
        platform="xhs",
        platform_comment_id="comment1",
        content_id=content.id,
        author_profile_id=profile.id,
        body_text="请问福州线下 PET 冲刺班怎么选？",
        region_text="福建 福州",
        published_at=now,
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
        model_name="deepseek-v4-flash",
        valuable=valuable,
        demand_type="course",
        intent_strength="medium",
        confidence=68,
        judgment_evidence_json=["询问福州线下 PET 冲刺班"],
        context_json={
            "post_title": content.title,
            "post_body": content.body_text,
            "current_comment": comment.body_text,
            "profile_region": profile.region_text,
            "source_url": content.url,
        },
        review_status=review_status,
        status_reason="需要人工确认是否适合线下跟进",
        workflow_status="llm_done",
        qualification_decision="needs_review",
        qualification_human_reason="地区匹配福州，但模型不确定",
        qualification_reason_codes_json=["model_uncertain", "location_matched"],
        qualification_confidence=68,
        qualification_location_json={
            "match_status": "matched",
            "reason": "location_matched",
            "resolved_location": {"province": "福建", "city": "福州"},
            "evidence": [{"raw_text": "福建 福州"}],
        },
    )
    session.add(screening)
    session.flush()
    return screening.id


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
