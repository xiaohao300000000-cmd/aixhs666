from sqlalchemy import UniqueConstraint

import storage.models  # noqa: F401
from storage.database import Base


CORE_TABLES = {
    "queries",
    "contents",
    "comments",
    "public_profiles",
    "discovery_relations",
    "collection_tasks",
    "snapshots",
    "collection_events",
}


EXPECTED_COLUMNS = {
    "queries": {
        "id",
        "query_text",
        "platform",
        "query_type",
        "status",
        "priority",
        "source",
        "semantic_cluster_id",
        "run_count",
        "last_run_at",
        "next_run_at",
        "created_at",
        "updated_at",
    },
    "contents": {
        "id",
        "platform",
        "platform_content_id",
        "content_type",
        "author_profile_id",
        "title",
        "body_text",
        "published_at",
        "url",
        "region_text",
        "like_count",
        "comment_count",
        "collect_count",
        "first_seen_at",
        "last_seen_at",
        "created_at",
        "updated_at",
    },
    "comments": {
        "id",
        "platform",
        "platform_comment_id",
        "content_id",
        "parent_comment_id",
        "author_profile_id",
        "body_text",
        "published_at",
        "like_count",
        "reply_count",
        "first_seen_at",
        "last_seen_at",
        "created_at",
        "updated_at",
    },
    "public_profiles": {
        "id",
        "platform",
        "platform_user_id",
        "display_name",
        "profile_url",
        "bio",
        "region_text",
        "public_contact_text",
        "first_seen_at",
        "last_seen_at",
        "created_at",
        "updated_at",
    },
    "discovery_relations": {
        "id",
        "query_id",
        "content_id",
        "rank_position",
        "result_page",
        "discovery_method",
        "discovered_at",
    },
    "collection_tasks": {
        "id",
        "task_type",
        "platform",
        "target_id",
        "query_id",
        "priority",
        "status",
        "attempt_count",
        "max_attempts",
        "scheduled_at",
        "started_at",
        "finished_at",
        "last_error",
        "worker_id",
        "cursor_json",
        "payload_json",
        "created_at",
        "updated_at",
    },
    "snapshots": {
        "id",
        "entity_type",
        "entity_id",
        "snapshot_type",
        "object_storage_path",
        "content_hash",
        "captured_at",
    },
    "collection_events": {
        "id",
        "event_type",
        "entity_type",
        "entity_id",
        "event_data",
        "occurred_at",
    },
}


def table(name: str):
    return Base.metadata.tables[name]


def unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table(table_name).constraints
        if isinstance(constraint, UniqueConstraint)
    }


def index_column_sets(table_name: str) -> dict[str, tuple[str, ...]]:
    return {index.name: tuple(column.name for column in index.columns) for index in table(table_name).indexes}


def foreign_key_target(table_name: str, column_name: str) -> str:
    foreign_keys = table(table_name).c[column_name].foreign_keys
    assert len(foreign_keys) == 1
    return next(iter(foreign_keys)).target_fullname


def test_core_tables_are_registered() -> None:
    assert CORE_TABLES <= set(Base.metadata.tables)


def test_core_tables_have_expected_columns() -> None:
    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        assert expected_columns <= set(table(table_name).c.keys())


def test_unique_constraints_match_identity_rules() -> None:
    assert ("platform", "platform_content_id") in unique_column_sets("contents")
    assert ("platform", "platform_comment_id") in unique_column_sets("comments")
    assert ("platform", "platform_user_id") in unique_column_sets("public_profiles")
    assert ("query_id", "content_id") in unique_column_sets("discovery_relations")


def test_required_indexes_are_declared() -> None:
    assert index_column_sets("queries")["ix_queries_status_next_run_at"] == ("status", "next_run_at")
    assert index_column_sets("comments")["ix_comments_content_id_published_at"] == ("content_id", "published_at")
    assert index_column_sets("discovery_relations")["ix_discovery_relations_query_id_discovered_at"] == (
        "query_id",
        "discovered_at",
    )
    assert index_column_sets("collection_tasks")["ix_collection_tasks_status_scheduled_at_priority"] == (
        "status",
        "scheduled_at",
        "priority",
    )


def test_foreign_keys_link_core_entities() -> None:
    assert foreign_key_target("contents", "author_profile_id") == "public_profiles.id"
    assert foreign_key_target("comments", "content_id") == "contents.id"
    assert foreign_key_target("comments", "parent_comment_id") == "comments.id"
    assert foreign_key_target("comments", "author_profile_id") == "public_profiles.id"
    assert foreign_key_target("discovery_relations", "query_id") == "queries.id"
    assert foreign_key_target("discovery_relations", "content_id") == "contents.id"
    assert foreign_key_target("collection_tasks", "query_id") == "queries.id"
