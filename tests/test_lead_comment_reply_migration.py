from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest


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
