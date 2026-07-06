from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from services.feishu_ai_workbench import build_ai_workbench_export
from storage.database import Base
from storage.models import Comment, Content, PublicProfile


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


def test_ai_workbench_export_filters_to_intent_customers(factory: sessionmaker[Session]) -> None:
    _seed_profile_with_comment(
        factory,
        user_id="parent-1",
        display_name="福州PET家长",
        comment_text="孩子PET没过，福州有二刷冲刺班推荐吗？价格多少？",
    )
    _seed_profile_with_comment(
        factory,
        user_id="resource-only",
        display_name="资料党",
        comment_text="求PET真题资料，谢谢",
    )

    with factory() as session:
        export = build_ai_workbench_export(session)

    assert len(export.customer_rows) == 1
    customer = export.customer_rows[0]
    assert customer["客户"] == "福州PET家长"
    assert customer["平台用户ID"] == "parent-1"
    assert customer["意向程度"] == "高"
    assert customer["证据数量"] == 1
    assert "二刷" in customer["需求摘要"]
    assert "课程价格" in customer["为什么推荐"]

    assert len(export.evidence_rows) == 1
    evidence = export.evidence_rows[0]
    assert evidence["平台用户ID"] == "parent-1"
    assert evidence["证据类型"] == "comment"
    assert evidence["AI判断"] == "push"
    assert "孩子PET没过" in evidence["抓取原文"]


def test_ai_workbench_export_merges_multiple_evidence_for_one_customer(factory: sessionmaker[Session]) -> None:
    profile_id = _seed_profile_with_comment(
        factory,
        user_id="parent-2",
        display_name="PET二刷家长",
        comment_text="孩子PET没过，想找二刷冲刺班",
    )
    now = datetime.now(UTC)
    with factory() as session:
        content = Content(
            platform="xhs",
            platform_content_id="note-extra",
            content_type="note",
            author_profile_id=profile_id,
            title="PET 二刷怎么选",
            body_text="孩子PET压线没过，纠结线上还是线下课程。",
            published_at=now,
            url="https://example.test/note-extra",
        )
        session.add(content)
        session.commit()

    with factory() as session:
        export = build_ai_workbench_export(session)

    assert len(export.customer_rows) == 1
    assert export.customer_rows[0]["证据数量"] == 2
    assert len(export.evidence_rows) == 2
    assert {row["证据类型"] for row in export.evidence_rows} == {"content", "comment"}


def test_ai_workbench_export_requires_intent_signal_in_raw_evidence(factory: sessionmaker[Session]) -> None:
    _seed_profile_with_comment(
        factory,
        user_id="chat-only",
        display_name="普通讨论用户",
        comment_text="求默写词汇",
    )

    with factory() as session:
        export = build_ai_workbench_export(session)

    assert export.customer_rows == []
    assert export.evidence_rows == []


def test_ai_workbench_export_skips_guide_style_content(factory: sessionmaker[Session]) -> None:
    now = datetime.now(UTC)
    with factory() as session:
        profile = PublicProfile(
            platform="xhs",
            platform_user_id="guide-author",
            display_name="备考博主",
            profile_url="https://example.test/user/guide-author",
        )
        session.add(profile)
        session.flush()
        session.add(
            Content(
                platform="xhs",
                platform_content_id="guide-note",
                content_type="note",
                author_profile_id=profile.id,
                title="自鸡KET，骂醒一个是一个",
                body_text="备考KET有正确步骤和规划，不建议直接丢给机构，#ket报名",
                published_at=now,
                url="https://example.test/guide-note",
            )
        )
        session.commit()

    with factory() as session:
        export = build_ai_workbench_export(session)

    assert export.customer_rows == []
    assert export.evidence_rows == []


def test_ai_workbench_export_skips_out_of_scope_exam_noise(factory: sessionmaker[Session]) -> None:
    now = datetime.now(UTC)
    with factory() as session:
        profile = PublicProfile(
            platform="xhs",
            platform_user_id="pte-author",
            display_name="PTE考生",
        )
        session.add(profile)
        session.flush()
        session.add(
            Content(
                platform="xhs",
                platform_content_id="pte-note",
                content_type="note",
                author_profile_id=profile.id,
                title="PTE十天速成",
                body_text="PTE考试需要报名，#PTE考试 #PET",
                published_at=now,
                url="https://example.test/pte-note",
            )
        )
        session.commit()

    with factory() as session:
        export = build_ai_workbench_export(session)

    assert export.customer_rows == []
    assert export.evidence_rows == []


def test_ai_workbench_export_skips_generic_price_opinion(factory: sessionmaker[Session]) -> None:
    _seed_profile_with_comment(
        factory,
        user_id="price-opinion",
        display_name="路人评论",
        comment_text="这个价格，她们以后出来真的能挣回来么",
    )

    with factory() as session:
        export = build_ai_workbench_export(session)

    assert export.customer_rows == []
    assert export.evidence_rows == []


def _seed_profile_with_comment(
    factory: sessionmaker[Session],
    *,
    user_id: str,
    display_name: str,
    comment_text: str,
) -> int:
    now = datetime.now(UTC)
    with factory() as session:
        profile = PublicProfile(
            platform="xhs",
            platform_user_id=user_id,
            display_name=display_name,
            profile_url=f"https://example.test/user/{user_id}",
        )
        session.add(profile)
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id=f"note-{user_id}",
            content_type="note",
            title="PET 讨论",
            body_text="PET 家长交流",
            published_at=now - timedelta(hours=2),
            url=f"https://example.test/note/{user_id}",
        )
        session.add(content)
        session.flush()
        session.add(
            Comment(
                platform="xhs",
                platform_comment_id=f"comment-{user_id}",
                content_id=content.id,
                author_profile_id=profile.id,
                body_text=comment_text,
                published_at=now - timedelta(hours=1),
            )
        )
        session.commit()
        return profile.id
