from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from storage.settings import get_settings


def test_contact_reply_two_step_migration_adds_revisions_and_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision_path = Path(__file__).parents[1] / "alembic/versions/0021_contact_reply_two_step.py"
    spec = importlib.util.spec_from_file_location("revision_0021", revision_path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    for operation in (
        "add_column",
        "create_table",
        "create_index",
        "execute",
        "drop_index",
        "drop_table",
        "drop_column",
    ):
        monkeypatch.setattr(
            revision.op,
            operation,
            lambda *args, _operation=operation, **kwargs: calls.append((_operation, args, kwargs)),
        )

    revision.upgrade()

    added = {args[1].name: args[1] for operation, args, _ in calls if operation == "add_column"}
    assert added["draft_revision"].server_default.arg == "1"
    assert added["approved_revision"].nullable is True
    assert added["queued_at"].nullable is True
    backfills = [str(args[0]) for operation, args, _ in calls if operation == "execute"]
    assert any("approved_revision" in sql and "approved_text IS NOT NULL" in sql for sql in backfills)
    create_table = next(args for operation, args, _ in calls if operation == "create_table")
    assert create_table[0] == "contact_command_operations"
    assert any(
        item.name == "uq_contact_command_operations_scope_entity_key"
        for item in create_table[1:]
    )


def test_lead_comment_reply_migration_preserves_audit_records(monkeypatch: pytest.MonkeyPatch) -> None:
    revision_path = Path(__file__).parents[1] / "alembic/versions/0015_lead_comment_replies.py"
    spec = importlib.util.spec_from_file_location("revision_0015", revision_path)
    assert spec is not None
    assert spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    for operation in ("add_column", "create_table", "create_index", "drop_index", "drop_table", "drop_column"):
        monkeypatch.setattr(
            revision.op,
            operation,
            lambda *args, _operation=operation, **kwargs: calls.append((_operation, args, kwargs)),
        )

    revision.upgrade()

    create_table = next(args for operation, args, _ in calls if operation == "create_table")
    assert create_table[0] == "lead_comment_replies"
    columns = {item.name: item for item in create_table[1:] if hasattr(item, "nullable") and item.name}
    assert columns["screening_result_id"].nullable is True
    assert columns["target_comment_id"].nullable is True
    assert columns["target_platform_comment_id"].nullable is False
    assert columns["target_content_id"].nullable is True
    assert columns["target_platform_content_id"].nullable is False
    assert columns["draft_text"].nullable is False

    foreign_keys = [item for item in create_table[1:] if item.__class__.__name__ == "ForeignKeyConstraint"]
    foreign_key_actions = {
        tuple(constraint.column_keys): constraint.ondelete for constraint in foreign_keys
    }
    assert foreign_key_actions[("screening_result_id",)] == "SET NULL"
    assert foreign_key_actions[("target_comment_id",)] == "SET NULL"
    assert foreign_key_actions[("target_content_id",)] == "SET NULL"
    assert any(item.name == "uq_lead_comment_replies_screening_result_id" for item in create_table[1:])
    assert any(item.name == "uq_lead_comment_replies_target_platform_comment_id" for item in create_table[1:])
    assert (
        "create_index",
        ("ix_lead_comment_replies_target_status", "lead_comment_replies", ["target_comment_id", "status"]),
        {},
    ) in calls

    calls.clear()
    revision.downgrade()

    assert ("drop_index", ("ix_lead_comment_replies_target_status",), {"table_name": "lead_comment_replies"}) in calls
    assert ("drop_table", ("lead_comment_replies",), {}) in calls
    assert ("drop_column", ("leads", "next_followup_at"), {}) in calls
    assert ("drop_column", ("leads", "followup_status"), {}) in calls


@pytest.mark.postgres
def test_contact_reply_migration_real_postgres_upgrade_downgrade_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("POSTGRES_MIGRATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("POSTGRES_MIGRATION_TEST_DATABASE_URL is required for migration round-trip")
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    engine = create_engine(database_url)
    try:
        command.upgrade(config, "0020_review_queue_idempotency")
        with engine.begin() as connection:
            reply_id = connection.scalar(
                text(
                    "INSERT INTO lead_comment_replies "
                    "(target_platform_comment_id, target_platform_content_id, draft_text, approved_text, status) "
                    "VALUES ('legacy-comment-v1905', 'legacy-content-v1905', '旧草稿文本', '旧审批文本', 'approved_to_send') "
                    "RETURNING id"
                )
            )

        command.upgrade(config, "0021_contact_reply_two_step")
        with engine.connect() as connection:
            upgraded = connection.execute(
                text(
                    "SELECT draft_text, approved_text, status, draft_revision, approved_revision "
                    "FROM lead_comment_replies WHERE id = :reply_id"
                ),
                {"reply_id": reply_id},
            ).one()
            column_types = dict(
                connection.execute(
                    text(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'lead_comment_replies' "
                        "AND column_name IN ('draft_revision', 'approved_revision', 'queued_at')"
                    )
                ).all()
            )
            constraint_count = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conname = 'uq_contact_command_operations_scope_entity_key'"
                )
            )
        assert upgraded == ("旧草稿文本", "旧审批文本", "approved_to_send", 1, 1)
        assert column_types == {
            "approved_revision": "integer",
            "draft_revision": "integer",
            "queued_at": "timestamp with time zone",
        }
        assert constraint_count == 1

        with engine.begin() as connection:
            insert_operation = text(
                "INSERT INTO contact_command_operations "
                "(operation_scope, entity_id, idempotency_key_hash, request_json, result_json) "
                "VALUES ('send_approved_contact', :reply_id, :key_hash, '{}'::json, '{}'::json)"
            )
            connection.execute(insert_operation, {"reply_id": reply_id, "key_hash": "a" * 64})
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(insert_operation, {"reply_id": reply_id, "key_hash": "a" * 64})

        command.downgrade(config, "0020_review_queue_idempotency")
        with engine.connect() as connection:
            downgraded = connection.execute(
                text("SELECT draft_text, approved_text, status FROM lead_comment_replies WHERE id = :reply_id"),
                {"reply_id": reply_id},
            ).one()
            removed_columns = connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'lead_comment_replies' "
                    "AND column_name IN ('draft_revision', 'approved_revision', 'queued_at')"
                )
            )
        assert downgraded == ("旧草稿文本", "旧审批文本", "approved_to_send")
        assert removed_columns == 0

        command.upgrade(config, "0021_contact_reply_two_step")
        with engine.connect() as connection:
            round_trip = connection.execute(
                text(
                    "SELECT draft_text, approved_text, status, draft_revision, approved_revision "
                    "FROM lead_comment_replies WHERE id = :reply_id"
                ),
                {"reply_id": reply_id},
            ).one()
        assert round_trip == ("旧草稿文本", "旧审批文本", "approved_to_send", 1, 1)
    finally:
        engine.dispose()
        get_settings.cache_clear()
