from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from storage.database import Base
from storage.models import ReviewQueueItem


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_review_queue_item_persists_business_day_identity_and_audit_fields() -> None:
    factory = _factory()
    with factory() as session:
        item = ReviewQueueItem(
            queue_date=date(2026, 7, 16),
            candidate_key="profile:42",
            screening_ids_json=[10, 11],
            layer="uncertain_review",
            slot_type="quality_control",
            priority_rank=300,
            position=1,
            status="pending",
            is_emergency=False,
            queue_reason="低置信度保留人工判断",
            exclusion_sample_reason=None,
        )
        session.add(item)
        session.commit()

        stored = session.scalar(select(ReviewQueueItem))
        assert stored is not None
        assert stored.candidate_key == "profile:42"
        assert stored.screening_ids_json == [10, 11]
        assert stored.human_decision is None
        assert stored.reviewed_at is None


def test_review_queue_item_is_unique_per_business_day_and_candidate() -> None:
    factory = _factory()
    with factory() as session:
        common = {
            "queue_date": date(2026, 7, 16),
            "candidate_key": "profile:42",
            "screening_ids_json": [10],
            "layer": "standard_review",
            "slot_type": "business",
            "priority_rank": 200,
            "status": "pending",
            "is_emergency": False,
            "queue_reason": "普通候选",
        }
        session.add_all(
            [ReviewQueueItem(position=1, **common), ReviewQueueItem(position=2, **common)]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_review_queue_has_date_status_position_read_index() -> None:
    factory = _factory()
    index_names = {
        item["name"] for item in inspect(factory.kw["bind"]).get_indexes("review_queue_items")
    }

    assert "ix_review_queue_items_date_status_position" in index_names
