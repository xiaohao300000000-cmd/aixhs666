from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeAlias

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from collectors import CollectedComment, CollectedContent, CollectedProfile, CollectedSearchResult
from storage.models import Comment, Content, DiscoveryRelation, PublicProfile, Query


CollectedContentLike: TypeAlias = CollectedContent | CollectedSearchResult


class IngestReferenceError(ValueError):
    """Raised when a collected object points at a missing required entity."""


def ingest_profile(
    session: Session,
    profile: CollectedProfile,
    *,
    now: datetime | None = None,
) -> PublicProfile:
    seen_at = _seen_at(now)
    stored = _find_profile(session, profile.platform, profile.platform_user_id)

    if stored is None:
        stored = PublicProfile(
            platform=profile.platform,
            platform_user_id=profile.platform_user_id,
            first_seen_at=seen_at,
        )
        session.add(stored)

    _apply_profile_fields(stored, profile, seen_at=seen_at)
    session.flush()
    return stored


def ingest_content(
    session: Session,
    content: CollectedContentLike,
    *,
    now: datetime | None = None,
) -> Content:
    seen_at = _seen_at(now)
    stored = _find_content(session, content.platform, content.platform_content_id)
    author_profile = _get_or_create_profile_identity(
        session,
        content.platform,
        content.platform_author_id,
        seen_at=seen_at,
    )

    if stored is None:
        stored = Content(
            platform=content.platform,
            platform_content_id=content.platform_content_id,
            first_seen_at=seen_at,
        )
        session.add(stored)

    _apply_content_fields(stored, content, author_profile=author_profile, seen_at=seen_at)
    session.flush()
    return stored


def ingest_comment(
    session: Session,
    comment: CollectedComment,
    *,
    now: datetime | None = None,
) -> Comment:
    seen_at = _seen_at(now)
    content = _find_content(session, comment.platform, comment.platform_content_id)
    if content is None:
        raise IngestReferenceError(
            f"content {comment.platform}:{comment.platform_content_id} must be ingested before its comments"
        )

    parent_comment = None
    if comment.parent_platform_comment_id is not None:
        parent_comment = _find_comment(session, comment.platform, comment.parent_platform_comment_id)
        if parent_comment is None:
            raise IngestReferenceError(
                "parent comment "
                f"{comment.platform}:{comment.parent_platform_comment_id} must be ingested before its replies"
            )

    author_profile = _get_or_create_profile_identity(
        session,
        comment.platform,
        comment.platform_author_id,
        seen_at=seen_at,
    )
    stored = _find_comment(session, comment.platform, comment.platform_comment_id)

    if stored is None:
        stored = Comment(
            platform=comment.platform,
            platform_comment_id=comment.platform_comment_id,
            first_seen_at=seen_at,
        )
        session.add(stored)

    _apply_comment_fields(
        stored,
        comment,
        content=content,
        parent_comment=parent_comment,
        author_profile=author_profile,
        seen_at=seen_at,
    )
    session.flush()
    return stored


def ingest_search_result(
    session: Session,
    query: Query | int,
    result: CollectedSearchResult,
    *,
    discovery_method: str = "search",
    now: datetime | None = None,
) -> tuple[Content, DiscoveryRelation]:
    seen_at = _seen_at(now)
    content = ingest_content(session, result, now=seen_at)
    relation = upsert_discovery_relation(
        session,
        query=query,
        content=content,
        rank_position=result.rank_position,
        result_page=result.result_page,
        discovery_method=discovery_method,
        discovered_at=seen_at,
    )
    return content, relation


def ingest_search_results(
    session: Session,
    query: Query | int,
    results: tuple[CollectedSearchResult, ...],
    *,
    discovery_method: str = "search",
    now: datetime | None = None,
) -> list[tuple[Content, DiscoveryRelation]]:
    seen_at = _seen_at(now)
    return [
        ingest_search_result(
            session,
            query,
            result,
            discovery_method=discovery_method,
            now=seen_at,
        )
        for result in results
    ]


def upsert_discovery_relation(
    session: Session,
    *,
    query: Query | int,
    content: Content,
    rank_position: int | None = None,
    result_page: int | None = None,
    discovery_method: str | None = None,
    discovered_at: datetime | None = None,
) -> DiscoveryRelation:
    seen_at = _seen_at(discovered_at)
    query_id = _query_id(session, query)
    if content.id is None:
        session.add(content)
        session.flush()

    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        return _native_upsert_discovery_relation(
            session,
            query_id=query_id,
            content_id=content.id,
            rank_position=rank_position,
            result_page=result_page,
            discovery_method=discovery_method,
            discovered_at=seen_at,
        )

    relation = session.scalar(
        select(DiscoveryRelation).where(
            DiscoveryRelation.query_id == query_id,
            DiscoveryRelation.content_id == content.id,
        )
    )

    if relation is None:
        relation = DiscoveryRelation(
            query_id=query_id,
            content_id=content.id,
            discovered_at=seen_at,
        )
        session.add(relation)

    relation.rank_position = rank_position
    relation.result_page = result_page
    relation.discovery_method = discovery_method
    relation.discovered_at = seen_at
    session.flush()
    return relation


def _native_upsert_discovery_relation(
    session: Session,
    *,
    query_id: int,
    content_id: int,
    rank_position: int | None,
    result_page: int | None,
    discovery_method: str | None,
    discovered_at: datetime,
) -> DiscoveryRelation:
    bind = session.get_bind()
    insert_statement = _insert_discovery_relation(bind.dialect.name)
    statement = (
        insert_statement(DiscoveryRelation)
        .values(
            query_id=query_id,
            content_id=content_id,
            rank_position=rank_position,
            result_page=result_page,
            discovery_method=discovery_method,
            discovered_at=discovered_at,
        )
        .on_conflict_do_update(
            index_elements=["query_id", "content_id"],
            set_={
                "rank_position": rank_position,
                "result_page": result_page,
                "discovery_method": discovery_method,
                "discovered_at": discovered_at,
            },
        )
        .returning(DiscoveryRelation.id)
    )
    try:
        relation_id = session.execute(statement).scalar_one()
    except IntegrityError:
        session.rollback()
        raise
    relation = session.get(DiscoveryRelation, relation_id)
    if relation is None:
        raise IngestReferenceError(f"discovery relation {relation_id} was not found after upsert")
    session.refresh(relation)
    return relation


def _insert_discovery_relation(dialect_name: str):
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        return insert
    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert

        return insert
    raise IngestReferenceError(f"unsupported upsert dialect: {dialect_name}")


def _seen_at(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _query_id(session: Session, query: Query | int) -> int:
    if isinstance(query, int):
        return query

    session.add(query)
    session.flush()
    if query.id is None:
        raise IngestReferenceError("query must have an id before writing discovery relations")
    return query.id


def _find_profile(session: Session, platform: str, platform_user_id: str) -> PublicProfile | None:
    return session.scalar(
        select(PublicProfile).where(
            PublicProfile.platform == platform,
            PublicProfile.platform_user_id == platform_user_id,
        )
    )


def _find_content(session: Session, platform: str, platform_content_id: str) -> Content | None:
    return session.scalar(
        select(Content).where(
            Content.platform == platform,
            Content.platform_content_id == platform_content_id,
        )
    )


def _find_comment(session: Session, platform: str, platform_comment_id: str) -> Comment | None:
    return session.scalar(
        select(Comment).where(
            Comment.platform == platform,
            Comment.platform_comment_id == platform_comment_id,
        )
    )


def _get_or_create_profile_identity(
    session: Session,
    platform: str,
    platform_user_id: str | None,
    *,
    seen_at: datetime,
) -> PublicProfile | None:
    if platform_user_id is None:
        return None

    profile = _find_profile(session, platform, platform_user_id)
    if profile is None:
        profile = PublicProfile(
            platform=platform,
            platform_user_id=platform_user_id,
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )
        session.add(profile)
    else:
        profile.last_seen_at = seen_at
        profile.updated_at = seen_at

    session.flush()
    return profile


def _apply_profile_fields(profile: PublicProfile, collected: CollectedProfile, *, seen_at: datetime) -> None:
    profile.display_name = collected.display_name
    profile.profile_url = collected.profile_url
    profile.bio = collected.bio
    profile.region_text = collected.region_text
    profile.public_contact_text = collected.public_contact_text
    profile.last_seen_at = seen_at
    profile.updated_at = seen_at


def _apply_content_fields(
    content: Content,
    collected: CollectedContentLike,
    *,
    author_profile: PublicProfile | None,
    seen_at: datetime,
) -> None:
    content.content_type = collected.content_type
    content.author_profile_id = None if author_profile is None else author_profile.id
    content.title = collected.title
    content.body_text = collected.body_text
    content.published_at = collected.published_at
    content.url = collected.url
    content.region_text = collected.region_text
    content.like_count = collected.like_count
    content.comment_count = collected.comment_count
    content.collect_count = collected.collect_count
    content.last_seen_at = seen_at
    content.updated_at = seen_at


def _apply_comment_fields(
    stored: Comment,
    collected: CollectedComment,
    *,
    content: Content,
    parent_comment: Comment | None,
    author_profile: PublicProfile | None,
    seen_at: datetime,
) -> None:
    stored.content_id = content.id
    stored.parent_comment_id = None if parent_comment is None else parent_comment.id
    stored.author_profile_id = None if author_profile is None else author_profile.id
    stored.body_text = collected.body_text
    stored.published_at = collected.published_at
    stored.region_text = collected.region_text
    stored.like_count = collected.like_count
    stored.reply_count = collected.reply_count
    stored.last_seen_at = seen_at
    stored.updated_at = seen_at
