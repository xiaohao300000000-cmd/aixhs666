from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from storage.database import Base
from storage import models


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_contact_reply_starts_at_revision_one(factory: sessionmaker[Session]) -> None:
    assert hasattr(models, "ContactCommandOperation")
    ContactCommandOperation = models.ContactCommandOperation
    LeadCommentReply = models.LeadCommentReply
    with factory() as session:
        reply = LeadCommentReply(
            target_platform_comment_id="comment-1",
            target_platform_content_id="content-1",
            draft_text="先了解一下孩子目前最卡的题型。",
        )
        session.add(reply)
        session.commit()

        assert reply.draft_revision == 1
        assert reply.approved_revision is None
        assert reply.queued_at is None


def test_contact_operation_scope_entity_and_key_hash_are_unique(factory: sessionmaker[Session]) -> None:
    assert hasattr(models, "ContactCommandOperation")
    ContactCommandOperation = models.ContactCommandOperation
    with factory() as session:
        session.add(
            ContactCommandOperation(
                operation_scope="edit_contact_draft",
                entity_id=41,
                idempotency_key_hash="a" * 64,
                request_json={"draft_revision": 1},
                result_json={"draft_revision": 2},
            )
        )
        session.commit()
        session.add(
            ContactCommandOperation(
                operation_scope="edit_contact_draft",
                entity_id=41,
                idempotency_key_hash="a" * 64,
                request_json={"draft_revision": 1},
                result_json={"draft_revision": 2},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
