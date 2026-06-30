from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Query(TimestampMixin, Base):
    __tablename__ = "queries"
    __table_args__ = (Index("ix_queries_status_next_run_at", "status", "next_run_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    query_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source: Mapped[str | None] = mapped_column(String(100))
    semantic_cluster_id: Mapped[int | None] = mapped_column(Integer)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    discovery_relations: Mapped[list[DiscoveryRelation]] = relationship(back_populates="query")
    collection_tasks: Mapped[list[CollectionTask]] = relationship(back_populates="query")


class PublicProfile(TimestampMixin, Base):
    __tablename__ = "public_profiles"
    __table_args__ = (UniqueConstraint("platform", "platform_user_id", name="uq_public_profiles_platform_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    profile_url: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    region_text: Mapped[str | None] = mapped_column(String(255))
    public_contact_text: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    contents: Mapped[list[Content]] = relationship(back_populates="author_profile")
    comments: Mapped[list[Comment]] = relationship(back_populates="author_profile")


class Content(TimestampMixin, Base):
    __tablename__ = "contents"
    __table_args__ = (UniqueConstraint("platform", "platform_content_id", name="uq_contents_platform_content_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_content_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    author_profile_id: Mapped[int | None] = mapped_column(ForeignKey("public_profiles.id", ondelete="SET NULL"))
    title: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    url: Mapped[str | None] = mapped_column(Text)
    region_text: Mapped[str | None] = mapped_column(String(255))
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    collect_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    author_profile: Mapped[PublicProfile | None] = relationship(back_populates="contents")
    comments: Mapped[list[Comment]] = relationship(back_populates="content")
    discovery_relations: Mapped[list[DiscoveryRelation]] = relationship(back_populates="content")


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint("platform", "platform_comment_id", name="uq_comments_platform_comment_id"),
        Index("ix_comments_content_id_published_at", "content_id", "published_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_comment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content_id: Mapped[int] = mapped_column(ForeignKey("contents.id", ondelete="CASCADE"), nullable=False)
    parent_comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"))
    author_profile_id: Mapped[int | None] = mapped_column(ForeignKey("public_profiles.id", ondelete="SET NULL"))
    body_text: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    content: Mapped[Content] = relationship(back_populates="comments")
    parent_comment: Mapped[Comment | None] = relationship(
        back_populates="replies",
        remote_side="Comment.id",
    )
    replies: Mapped[list[Comment]] = relationship(back_populates="parent_comment")
    author_profile: Mapped[PublicProfile | None] = relationship(back_populates="comments")


class DiscoveryRelation(Base):
    __tablename__ = "discovery_relations"
    __table_args__ = (Index("ix_discovery_relations_query_id_discovered_at", "query_id", "discovered_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id", ondelete="CASCADE"), nullable=False)
    content_id: Mapped[int] = mapped_column(ForeignKey("contents.id", ondelete="CASCADE"), nullable=False)
    rank_position: Mapped[int | None] = mapped_column(Integer)
    result_page: Mapped[int | None] = mapped_column(Integer)
    discovery_method: Mapped[str | None] = mapped_column(String(100))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    query: Mapped[Query] = relationship(back_populates="discovery_relations")
    content: Mapped[Content] = relationship(back_populates="discovery_relations")


class CollectionTask(TimestampMixin, Base):
    __tablename__ = "collection_tasks"
    __table_args__ = (Index("ix_collection_tasks_status_scheduled_at_priority", "status", "scheduled_at", "priority"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(255))
    query_id: Mapped[int | None] = mapped_column(ForeignKey("queries.id", ondelete="SET NULL"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(255))
    cursor_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    query: Mapped[Query | None] = relationship(back_populates="collection_tasks")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CollectionEvent(Base):
    __tablename__ = "collection_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
