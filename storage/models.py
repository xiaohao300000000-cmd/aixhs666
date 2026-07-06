from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
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
    leads: Mapped[list[Lead]] = relationship(back_populates="profile")


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
    __table_args__ = (
        UniqueConstraint("query_id", "content_id", name="uq_discovery_relations_query_id_content_id"),
        Index("ix_discovery_relations_query_id_discovered_at", "query_id", "discovered_at"),
    )

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


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="idle", server_default="idle")
    current_task_id: Mapped[int | None] = mapped_column(ForeignKey("collection_tasks.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


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


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        Index("ix_pipeline_runs_status_started_at", "status", "started_at"),
        UniqueConstraint("idempotency_key", name="uq_pipeline_runs_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    requested_by: Mapped[str | None] = mapped_column(String(100))
    request_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    progress_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))


class AnalysisProcessingState(Base):
    __tablename__ = "analysis_processing_states"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "analysis_version",
            name="uq_analysis_processing_states_entity_version",
        ),
        Index("ix_analysis_processing_states_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(100), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_fingerprint: Mapped[str | None] = mapped_column(String(128))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_pipeline_run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"))


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("platform", "public_profile_id", name="uq_leads_platform_public_profile_id"),
        Index("ix_leads_status_updated_at", "status", "updated_at"),
        Index("ix_leads_intent_score", "intent_score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    public_profile_id: Mapped[int] = mapped_column(ForeignKey("public_profiles.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="new", server_default="new")
    region_text: Mapped[str | None] = mapped_column(String(255))
    demand_type: Mapped[str | None] = mapped_column(String(100))
    product: Mapped[str | None] = mapped_column(String(100))
    intent_stage: Mapped[str | None] = mapped_column(String(100))
    intent_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    information_completeness: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    known_info_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    missing_info_json: Mapped[list[str] | None] = mapped_column(JSON)
    recommended_next_step: Mapped[str | None] = mapped_column(Text)
    owner_name: Mapped[str | None] = mapped_column(String(255))
    operator_note: Mapped[str | None] = mapped_column(Text)
    last_feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    profile: Mapped[PublicProfile] = relationship(back_populates="leads")
    evidence_items: Mapped[list[LeadEvidence]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    enrichment_tasks: Mapped[list[EnrichmentTask]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class LeadEvidence(Base):
    __tablename__ = "lead_evidence"
    __table_args__ = (
        UniqueConstraint(
            "lead_id",
            "source_entity_type",
            "source_entity_id",
            name="uq_lead_evidence_lead_source",
        ),
        Index("ix_lead_evidence_lead_id", "lead_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    content_id: Mapped[int | None] = mapped_column(ForeignKey("contents.id", ondelete="SET NULL"))
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="SET NULL"))
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    demand_type: Mapped[str | None] = mapped_column(String(100))
    intent_stage: Mapped[str | None] = mapped_column(String(100))
    score_contribution: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    lead: Mapped[Lead] = relationship(back_populates="evidence_items")


class LeadScreeningResult(TimestampMixin, Base):
    __tablename__ = "lead_screening_results"
    __table_args__ = (
        UniqueConstraint("source_entity_type", "source_entity_id", name="uq_lead_screening_source"),
        Index("ix_lead_screening_review_status", "review_status"),
        Index("ix_lead_screening_workflow_status", "workflow_status"),
        Index("ix_lead_screening_profile_id", "public_profile_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    content_id: Mapped[int | None] = mapped_column(ForeignKey("contents.id", ondelete="SET NULL"))
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="SET NULL"))
    public_profile_id: Mapped[int | None] = mapped_column(ForeignKey("public_profiles.id", ondelete="SET NULL"))
    model_name: Mapped[str | None] = mapped_column(String(255))
    valuable: Mapped[bool | None] = mapped_column(Boolean)
    demand_type: Mapped[str | None] = mapped_column(String(100))
    intent_strength: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[int | None] = mapped_column(Integer)
    judgment_evidence_json: Mapped[list[str] | None] = mapped_column(JSON)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    llm_raw_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="needs_review", server_default="needs_review")
    status_reason: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    workflow_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending_llm", server_default="pending_llm")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    feishu_message_id: Mapped[str | None] = mapped_column(String(255))
    feishu_chat_id: Mapped[str | None] = mapped_column(String(255))
    feishu_card_status: Mapped[str | None] = mapped_column(String(50))
    human_review_status: Mapped[str | None] = mapped_column(String(50))
    human_reviewer_id: Mapped[str | None] = mapped_column(String(255))
    human_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnrichmentTask(TimestampMixin, Base):
    __tablename__ = "enrichment_tasks"
    __table_args__ = (
        UniqueConstraint("lead_id", "task_type", name="uq_enrichment_tasks_lead_task_type"),
        Index("ix_enrichment_tasks_status_updated_at", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    reason: Mapped[str | None] = mapped_column(Text)

    lead: Mapped[Lead] = relationship(back_populates="enrichment_tasks")


class FeishuBitableRecord(TimestampMixin, Base):
    __tablename__ = "feishu_bitable_records"
    __table_args__ = (
        UniqueConstraint(
            "local_entity_type",
            "local_entity_id",
            "app_token",
            "table_id",
            name="uq_feishu_bitable_local_record",
        ),
        Index("ix_feishu_bitable_record_id", "record_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    local_entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    local_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    app_token: Mapped[str] = mapped_column(String(255), nullable=False)
    table_id: Mapped[str] = mapped_column(String(255), nullable=False)
    record_id: Mapped[str | None] = mapped_column(String(255))
    sync_direction: Mapped[str] = mapped_column(String(50), nullable=False, default="push", server_default="push")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_remote_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)
    remote_fields_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
