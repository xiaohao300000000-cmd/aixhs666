from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import storage.models  # noqa: F401
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from collectors import CollectedProfile, MockPlatformAdapter
from storage import (
    IngestReferenceError,
    ingest_comment,
    ingest_content,
    ingest_profile,
    ingest_search_result,
    upsert_discovery_relation,
    stable_text_hash,
)
from storage.database import Base
from storage.models import CollectionEvent, Comment, Content, DiscoveryRelation, PublicProfile, Query
from storage.text_hash import normalize_text_for_hash


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_content_ingest_deduplicates_and_updates_mutable_fields(session: Session) -> None:
    adapter = MockPlatformAdapter()
    content = adapter.get_content("note-ai-001")
    first_seen = datetime(2026, 1, 1, tzinfo=UTC)
    last_seen = first_seen + timedelta(hours=1)

    stored = ingest_content(session, content, now=first_seen)
    updated = ingest_content(
        session,
        replace(content, title="Updated checklist", like_count=content.like_count + 10),
        now=last_seen,
    )

    assert updated.id == stored.id
    assert session.scalars(select(Content)).all() == [stored]
    assert updated.title == "Updated checklist"
    assert updated.like_count == content.like_count + 10
    assert updated.first_seen_at == first_seen
    assert updated.last_seen_at == last_seen


def test_comment_ingest_deduplicates_and_updates_mutable_fields(session: Session) -> None:
    adapter = MockPlatformAdapter()
    content = ingest_content(session, adapter.get_content("note-ai-001"), now=datetime(2026, 1, 1, tzinfo=UTC))
    comment = adapter.list_comments(content.platform_content_id).items[0]
    first_seen = datetime(2026, 1, 2, tzinfo=UTC)
    last_seen = first_seen + timedelta(hours=1)

    stored = ingest_comment(session, comment, now=first_seen)
    updated = ingest_comment(
        session,
        replace(comment, body_text="Updated question", like_count=comment.like_count + 3),
        now=last_seen,
    )

    assert updated.id == stored.id
    assert session.scalars(select(Comment)).all() == [stored]
    assert updated.content_id == content.id
    assert updated.body_text == "Updated question"
    assert updated.like_count == comment.like_count + 3
    assert updated.first_seen_at == first_seen
    assert updated.last_seen_at == last_seen


def test_comment_ingest_persists_region_text_when_adapter_provides_it(session: Session) -> None:
    adapter = MockPlatformAdapter()
    content = ingest_content(session, adapter.get_content("note-ai-001"), now=datetime(2026, 1, 1, tzinfo=UTC))
    comment = replace(adapter.list_comments(content.platform_content_id).items[0], region_text="福州")

    stored = ingest_comment(session, comment, now=datetime(2026, 1, 2, tzinfo=UTC))

    assert stored.region_text == "福州"


def test_region_text_empty_update_does_not_overwrite_existing_value(session: Session) -> None:
    adapter = MockPlatformAdapter()
    content = ingest_content(
        session,
        replace(adapter.get_content("note-ai-001"), region_text="福建"),
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    comment = replace(adapter.list_comments(content.platform_content_id).items[0], region_text="福州")
    stored_comment = ingest_comment(session, comment, now=datetime(2026, 1, 2, tzinfo=UTC))
    profile = ingest_profile(
        session,
        CollectedProfile(
            platform="xhs",
            platform_user_id="profile-region-user",
            display_name="家长",
            profile_url=None,
            bio=None,
            region_text="上海",
            public_contact_text=None,
        ),
        now=datetime(2026, 1, 3, tzinfo=UTC),
    )

    ingest_content(session, replace(adapter.get_content("note-ai-001"), region_text=None), now=datetime(2026, 1, 4, tzinfo=UTC))
    ingest_comment(session, replace(comment, region_text=None), now=datetime(2026, 1, 5, tzinfo=UTC))
    ingest_profile(
        session,
        CollectedProfile(
            platform="xhs",
            platform_user_id="profile-region-user",
            display_name="家长",
            profile_url=None,
            bio=None,
            region_text=None,
            public_contact_text=None,
        ),
        now=datetime(2026, 1, 6, tzinfo=UTC),
    )

    assert content.region_text == "福建"
    assert stored_comment.region_text == "福州"
    assert profile.region_text == "上海"


def test_region_text_conflict_does_not_overwrite_and_records_event(session: Session) -> None:
    adapter = MockPlatformAdapter()
    content = ingest_content(
        session,
        replace(adapter.get_content("note-ai-001"), region_text="福建"),
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    updated = ingest_content(
        session,
        replace(adapter.get_content("note-ai-001"), region_text="上海"),
        now=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert updated.id == content.id
    assert updated.region_text == "福建"
    event = session.scalar(select(CollectionEvent).where(CollectionEvent.event_type == "region_text_conflict"))
    assert event is not None
    assert event.entity_type == "content"
    assert event.entity_id == content.id
    assert event.event_data["existing_region_text"] == "福建"
    assert event.event_data["incoming_region_text"] == "上海"


def test_profile_ingest_deduplicates_and_updates_profile_fields(session: Session) -> None:
    adapter = MockPlatformAdapter()
    profile = adapter.get_profile("user-author-001")
    first_seen = datetime(2026, 1, 3, tzinfo=UTC)
    last_seen = first_seen + timedelta(hours=1)

    stored = ingest_profile(session, profile, now=first_seen)
    updated = ingest_profile(
        session,
        CollectedProfile(
            platform=profile.platform,
            platform_user_id=profile.platform_user_id,
            display_name="Updated Lab",
            profile_url=profile.profile_url,
            bio="Updated profile text.",
            region_text=profile.region_text,
            public_contact_text="new@example.invalid",
        ),
        now=last_seen,
    )

    assert updated.id == stored.id
    assert session.scalars(select(PublicProfile)).all() == [stored]
    assert updated.display_name == "Updated Lab"
    assert updated.bio == "Updated profile text."
    assert updated.region_text == profile.region_text
    assert updated.public_contact_text == "new@example.invalid"
    assert updated.first_seen_at == first_seen
    assert updated.last_seen_at == last_seen


def test_multiple_queries_can_discover_one_content_without_content_duplication(session: Session) -> None:
    adapter = MockPlatformAdapter()
    first_query = _query(session, "ai-study")
    second_query = _query(session, "admissions")
    first_result = adapter.search("ai-study").items[0]
    second_result = adapter.search("admissions").items[0]

    first_content, first_relation = ingest_search_result(session, first_query, first_result)
    second_content, second_relation = ingest_search_result(session, second_query, second_result)

    assert first_content.id == second_content.id
    assert session.scalars(select(Content)).all() == [first_content]
    relations = session.scalars(select(DiscoveryRelation)).all()
    assert {relation.id for relation in relations} == {first_relation.id, second_relation.id}
    assert {relation.query_id for relation in relations} == {first_query.id, second_query.id}
    assert {relation.content_id for relation in relations} == {first_content.id}


def test_same_query_content_discovery_is_idempotent(session: Session) -> None:
    adapter = MockPlatformAdapter()
    query = _query(session, "ai-study")
    result = adapter.search("ai-study").items[0]
    first_seen = datetime(2026, 1, 4, tzinfo=UTC)
    last_seen = first_seen + timedelta(hours=1)

    _content, first_relation = ingest_search_result(session, query, result, now=first_seen)
    _content, updated_relation = ingest_search_result(
        session,
        query,
        replace(result, rank_position=5, result_page=2),
        now=last_seen,
    )

    assert updated_relation.id == first_relation.id
    assert session.scalars(select(DiscoveryRelation)).all() == [first_relation]
    assert updated_relation.rank_position == 5
    assert updated_relation.result_page == 2
    assert updated_relation.discovered_at == last_seen


def test_discovery_relation_upsert_uses_unique_identity(session: Session) -> None:
    adapter = MockPlatformAdapter()
    query = _query(session, "ai-study")
    content = ingest_content(session, adapter.get_content("note-ai-001"))

    first_relation = upsert_discovery_relation(
        session,
        query=query,
        content=content,
        rank_position=1,
        result_page=1,
        discovery_method="search",
    )
    updated_relation = upsert_discovery_relation(
        session,
        query=query,
        content=content,
        rank_position=9,
        result_page=3,
        discovery_method="repeat-search",
    )

    assert updated_relation.id == first_relation.id
    assert session.scalars(select(DiscoveryRelation)).all() == [first_relation]
    assert updated_relation.rank_position == 9
    assert updated_relation.result_page == 3
    assert updated_relation.discovery_method == "repeat-search"


def test_reply_comment_links_to_previously_ingested_parent(session: Session) -> None:
    adapter = MockPlatformAdapter()
    content = ingest_content(session, adapter.get_content("note-ai-001"))
    parent, reply = adapter.list_comments(content.platform_content_id).items

    parent_model = ingest_comment(session, parent)
    reply_model = ingest_comment(session, reply)

    assert reply_model.parent_comment_id == parent_model.id


def test_comment_ingest_requires_existing_content(session: Session) -> None:
    adapter = MockPlatformAdapter()
    comment = adapter.list_comments("note-ai-001").items[0]

    with pytest.raises(IngestReferenceError):
        ingest_comment(session, comment)


def test_stable_text_hash_normalizes_basic_text_differences() -> None:
    assert normalize_text_for_hash("  AI\tStudy\nPlan  ") == "ai study plan"
    assert stable_text_hash("  AI\tStudy\nPlan  ") == stable_text_hash("ai study plan")
    assert stable_text_hash(None) == stable_text_hash("")
    assert stable_text_hash("ai study plan") != stable_text_hash("ai school plan")


def _query(session: Session, query_text: str) -> Query:
    query = Query(
        query_text=query_text,
        platform="xhs",
        query_type="seed",
        status="completed",
        source="test",
    )
    session.add(query)
    session.flush()
    return query
