import storage.models  # noqa: F401
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from collectors import MockPlatformAdapter, PlatformAdapter
from storage.database import Base
from storage.models import Comment, Content, PublicProfile, Query


def test_mock_adapter_exposes_platform_boundary() -> None:
    adapter: PlatformAdapter = MockPlatformAdapter()

    assert adapter.platform == "xhs"
    assert callable(adapter.search)
    assert callable(adapter.get_content)
    assert callable(adapter.list_comments)
    assert callable(adapter.get_profile)


def test_search_returns_deterministic_content_results() -> None:
    adapter = MockPlatformAdapter()

    first_page = adapter.search("ai-study", limit=1)
    second_page = adapter.search("ai-study", cursor=first_page.cursor.next_cursor, limit=1)
    full_page = adapter.search("ai-study", limit=20)

    assert first_page == adapter.search("ai-study", limit=1)
    assert [item.platform_content_id for item in full_page.items] == ["note-ai-001", "note-ai-002"]
    assert first_page.items[0].platform == "xhs"
    assert first_page.items[0].platform_author_id == "user-author-001"
    assert first_page.items[0].rank_position == 1
    assert first_page.cursor.has_more is True
    assert first_page.cursor.next_cursor == "1"
    assert second_page.items[0].platform_content_id == "note-ai-002"
    assert second_page.cursor.has_more is False


def test_content_detail_can_be_read() -> None:
    adapter = MockPlatformAdapter()

    detail = adapter.get_content("note-ai-001")

    assert detail.platform == "xhs"
    assert detail.platform_content_id == "note-ai-001"
    assert detail.platform_author_id == "user-author-001"
    assert detail.title == "AI study planning checklist"
    assert detail.body_text is not None
    assert detail.like_count == 128
    assert detail.url == "https://mock.xhs.local/notes/note-ai-001"
    assert detail.region_text == "Shanghai"


def test_comments_include_top_level_and_reply() -> None:
    adapter = MockPlatformAdapter()

    comments = adapter.list_comments("note-ai-001")

    assert [comment.platform_comment_id for comment in comments.items] == ["comment-ai-001", "comment-ai-002"]
    parent, reply = comments.items
    assert parent.parent_platform_comment_id is None
    assert parent.reply_count == 1
    assert reply.parent_platform_comment_id == parent.platform_comment_id
    assert reply.platform_content_id == "note-ai-001"


def test_public_profile_can_be_read() -> None:
    adapter = MockPlatformAdapter()

    profile = adapter.get_profile("user-author-001")

    assert profile.platform == "xhs"
    assert profile.platform_user_id == "user-author-001"
    assert profile.display_name == "AI Admissions Lab"
    assert profile.profile_url == "https://mock.xhs.local/users/user-author-001"
    assert profile.region_text == "Shanghai"


def test_mock_data_maps_to_core_orm_models() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    adapter = MockPlatformAdapter()
    content = adapter.get_content("note-ai-001")
    comments = adapter.list_comments(content.platform_content_id).items

    try:
        with Session(engine) as session:
            query = Query(
                query_text="ai-study",
                platform=adapter.platform,
                query_type="seed",
                status="completed",
                source="mock",
            )
            session.add(query)

            profiles = [
                _to_profile_model(adapter.get_profile("user-author-001")),
                _to_profile_model(adapter.get_profile("user-parent-001")),
                _to_profile_model(adapter.get_profile("user-student-001")),
            ]
            session.add_all(profiles)
            session.flush()
            profile_by_user_id = {profile.platform_user_id: profile for profile in profiles}

            content_model = Content(
                platform=content.platform,
                platform_content_id=content.platform_content_id,
                content_type=content.content_type,
                author_profile_id=profile_by_user_id["user-author-001"].id,
                title=content.title,
                body_text=content.body_text,
                published_at=content.published_at,
                url=content.url,
                region_text=content.region_text,
                like_count=content.like_count,
                comment_count=content.comment_count,
                collect_count=content.collect_count,
            )
            session.add(content_model)
            session.flush()

            parent_comment, reply_comment = comments
            parent_model = _to_comment_model(
                parent_comment,
                content_id=content_model.id,
                author_profile_id=profile_by_user_id["user-parent-001"].id,
            )
            session.add(parent_model)
            session.flush()

            reply_model = _to_comment_model(
                reply_comment,
                content_id=content_model.id,
                author_profile_id=profile_by_user_id["user-student-001"].id,
                parent_comment_id=parent_model.id,
            )
            session.add(reply_model)
            session.commit()

            stored_query = session.scalar(select(Query).where(Query.query_text == "ai-study"))
            stored_content = session.scalar(select(Content).where(Content.platform_content_id == "note-ai-001"))
            stored_reply = session.scalar(select(Comment).where(Comment.platform_comment_id == "comment-ai-002"))
            stored_profiles = session.scalars(select(PublicProfile)).all()

            assert stored_query is not None
            assert stored_content is not None
            assert stored_reply is not None
            assert stored_query.platform == "xhs"
            assert stored_content.author_profile_id == profile_by_user_id["user-author-001"].id
            assert stored_reply.parent_comment_id == parent_model.id
            assert len(stored_profiles) == 3
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _to_profile_model(profile) -> PublicProfile:
    return PublicProfile(
        platform=profile.platform,
        platform_user_id=profile.platform_user_id,
        display_name=profile.display_name,
        profile_url=profile.profile_url,
        bio=profile.bio,
        region_text=profile.region_text,
        public_contact_text=profile.public_contact_text,
    )


def _to_comment_model(
    comment,
    *,
    content_id: int,
    author_profile_id: int | None,
    parent_comment_id: int | None = None,
) -> Comment:
    return Comment(
        platform=comment.platform,
        platform_comment_id=comment.platform_comment_id,
        content_id=content_id,
        parent_comment_id=parent_comment_id,
        author_profile_id=author_profile_id,
        body_text=comment.body_text,
        published_at=comment.published_at,
        like_count=comment.like_count,
        reply_count=comment.reply_count,
    )
