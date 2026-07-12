from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from storage.database import Base
from storage.models import Comment, Content, Lead, LeadCommentReply, LeadScreeningResult, PublicProfile


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


def test_comment_reply_defaults_and_unique_screening(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="comment-reply-user")
        session.add(profile)
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id="comment-reply-note",
            content_type="note",
            author_profile_id=profile.id,
            url="https://www.xiaohongshu.com/explore/comment-reply-note",
        )
        lead = Lead(platform="xhs", public_profile_id=profile.id)
        session.add_all([content, lead])
        session.flush()
        comment = Comment(
            platform="xhs",
            platform_comment_id="comment-reply-target",
            content_id=content.id,
            author_profile_id=profile.id,
            body_text="孩子目前阅读题总丢分，应该先练什么？",
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
        )
        session.add(screening)
        session.flush()

        reply = LeadCommentReply(
            screening_result_id=screening.id,
            lead_id=lead.id,
            target_comment_id=comment.id,
            target_platform_comment_id=comment.platform_comment_id,
            target_content_id=comment.content_id,
            target_platform_content_id=comment.content.platform_content_id,
            target_url=comment.content.url,
            draft_text="可以先看看孩子目前卡在哪个题型。",
        )
        session.add(reply)
        session.commit()

        assert reply.status == "pending_review"
        assert reply.attempt_count == 0
        assert lead.followup_status is None
        assert lead.next_followup_at is None

        session.add(
            LeadCommentReply(
                screening_result_id=screening.id,
                target_comment_id=comment.id,
                target_platform_comment_id=comment.platform_comment_id,
                target_content_id=comment.content_id,
                target_platform_content_id=comment.content.platform_content_id,
                draft_text="重复草稿",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_comment_reply_preserves_denormalized_targets_without_local_rows(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="deleted-target-user")
        session.add(profile)
        session.flush()
        screening = LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=999,
            public_profile_id=profile.id,
        )
        session.add(screening)
        session.flush()
        reply = LeadCommentReply(
            screening_result_id=screening.id,
            target_comment_id=None,
            target_platform_comment_id="deleted-platform-comment",
            target_content_id=None,
            target_platform_content_id="deleted-platform-content",
            draft_text="保留审核和发送证据。",
        )
        session.add(reply)
        session.commit()

        assert reply.target_comment_id is None
        assert reply.target_content_id is None
        assert reply.target_platform_comment_id == "deleted-platform-comment"
        assert reply.target_platform_content_id == "deleted-platform-content"


def test_comment_reply_target_platform_comment_is_unique(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="recollected-comment-user")
        session.add(profile)
        session.flush()
        first_screening = LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=1001,
            public_profile_id=profile.id,
        )
        second_screening = LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=1002,
            public_profile_id=profile.id,
        )
        session.add_all([first_screening, second_screening])
        session.flush()
        session.add(
            LeadCommentReply(
                screening_result_id=first_screening.id,
                target_platform_comment_id="durable-platform-comment",
                target_platform_content_id="durable-platform-content",
                draft_text="第一条草稿",
            )
        )
        session.commit()

        session.add(
            LeadCommentReply(
                screening_result_id=second_screening.id,
                target_platform_comment_id="durable-platform-comment",
                target_platform_content_id="recollected-platform-content",
                draft_text="重新采集后生成的重复草稿",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_comment_reply_target_foreign_keys_use_set_null() -> None:
    table = LeadCommentReply.__table__

    assert table.c.screening_result_id.nullable is True
    assert table.c.target_comment_id.nullable is True
    assert table.c.target_content_id.nullable is True
    assert table.c.target_platform_comment_id.nullable is False
    assert table.c.target_platform_content_id.nullable is False
    assert next(iter(table.c.screening_result_id.foreign_keys)).ondelete == "SET NULL"
    assert next(iter(table.c.target_comment_id.foreign_keys)).ondelete == "SET NULL"
    assert next(iter(table.c.target_content_id.foreign_keys)).ondelete == "SET NULL"
