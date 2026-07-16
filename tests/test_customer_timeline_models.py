from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from storage.database import Base
from storage.models import CustomerTimelineEvent, Lead, PublicProfile


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield session_factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_customer_timeline_event_key_is_unique(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="timeline-user")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id)
        session.add(lead)
        session.flush()

        session.add(
            CustomerTimelineEvent(
                lead_id=lead.id,
                event_key="review:event-1",
                event_type="candidate_promoted",
            )
        )
        session.commit()

        session.add(
            CustomerTimelineEvent(
                lead_id=lead.id,
                event_key="review:event-1",
                event_type="candidate_promoted",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
