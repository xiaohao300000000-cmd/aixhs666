from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
import pytest
from apps import cli


class _Runner:
    def __init__(self, **kwargs) -> None:
        pass


class _Session:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, traceback) -> None:
        pass
    def commit(self) -> None:
        pass


def _runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_load_runtime_dependencies", lambda: None)
    monkeypatch.setattr(cli, "PipelineRunner", _Runner)
    monkeypatch.setattr(cli, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(cli, "load_adapter", lambda name: object())


def test_comment_reply_generate_once_creates_card_without_xhs_send(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _runtime(monkeypatch)
    monkeypatch.setenv("FEISHU_LLM_REVIEW_CHAT_ID", "chat-1")

    class Reply:
        id = 41
        status = "pending_review"
        feishu_message_id = "message-1"

    monkeypatch.setattr("integrations.feishu.comment_replies.create_comment_reply_for_valid_screening", lambda *args, **kwargs: Reply())
    monkeypatch.setattr("services.comment_reply_generation.OpenAICompatibleCommentReplyGenerator", object)
    monkeypatch.setattr(cli, "FeishuIMClient", object)
    assert cli.main(["--json", "comment-reply-generate-once", "--screening-id", "9"]) == 0
    assert json.loads(capsys.readouterr().out) == {"comment_reply": {"created": True, "reply_id": 41, "status": "pending_review", "feishu_message_id": "message-1"}}


def test_comment_reply_sync_followup_recovers_without_sender(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _runtime(monkeypatch)
    calls: list[int] = []
    def push_followup(session_factory, *, reply_id):
        calls.append(reply_id)
        return {"created": 1, "updated": 0, "skipped": 0}
    monkeypatch.setattr("services.feishu_customer_followup.push_customer_followup", push_followup)
    assert cli.main(["--json", "comment-reply-sync-followup", "--reply-id", "42"]) == 0
    assert calls == [42]
    assert json.loads(capsys.readouterr().out) == {"comment_reply_followup": {"created": 1, "skipped": 0, "updated": 0}}


def test_comment_reply_reconcile_stale_uses_guarded_recovery(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _runtime(monkeypatch)
    calls: list[dict[str, object]] = []

    class Result:
        applied = True
        duplicate = False
        reply_id = 43
        status = "result_unknown"
        reconciliation_required = True

    def reconcile(session_factory, **kwargs):
        calls.append(kwargs)
        return Result()

    monkeypatch.setattr("integrations.feishu.comment_replies.reconcile_stale_comment_reply", reconcile)
    assert cli.main(["--json", "comment-reply-reconcile-stale", "--reply-id", "43", "--card-timeout-seconds", "60", "--send-timeout-seconds", "120"]) == 0
    assert calls[0]["reply_id"] == 43
    assert calls[0]["card_timeout"] == timedelta(seconds=60)
    assert calls[0]["send_timeout"] == timedelta(seconds=120)
    assert isinstance(calls[0]["now"], datetime)
    assert json.loads(capsys.readouterr().out)["comment_reply_reconciliation"]["status"] == "result_unknown"


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("--card-timeout-seconds", "0"),
        ("--card-timeout-seconds", "-1"),
        ("--send-timeout-seconds", "0"),
        ("--send-timeout-seconds", "-1"),
    ],
)
def test_comment_reply_reconcile_stale_rejects_nonpositive_timeouts_without_calling_service(
    monkeypatch: pytest.MonkeyPatch,
    argument: str,
    value: str,
) -> None:
    _runtime(monkeypatch)
    monkeypatch.setattr(
        "integrations.feishu.comment_replies.reconcile_stale_comment_reply",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("invalid timeout must not call reconciliation")),
    )
    arguments = [
        "comment-reply-reconcile-stale",
        "--reply-id",
        "43",
        "--card-timeout-seconds",
        "60",
        "--send-timeout-seconds",
        "120",
    ]
    arguments[arguments.index(argument) + 1] = value
    with pytest.raises(SystemExit) as exc_info:
        cli.main(arguments)
    assert exc_info.value.code != 0


def test_comment_reply_adopt_card_requires_audited_identity(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _runtime(monkeypatch)
    calls: list[dict[str, object]] = []

    class Result:
        applied = True
        duplicate = False
        reply_id = 44
        status = "pending_review"
        reconciliation_required = False

    monkeypatch.setattr("integrations.feishu.comment_replies.adopt_reconciled_comment_reply_card", lambda session_factory, **kwargs: calls.append(kwargs) or Result())
    assert cli.main([
        "--json", "comment-reply-adopt-card", "--reply-id", "44", "--message-id", "msg-1",
        "--chat-id", "chat-1", "--operator", "ops@example.com", "--reason", "verified in Feishu",
    ]) == 0
    assert calls == [{"reply_id": 44, "message_id": "msg-1", "chat_id": "chat-1", "operator": "ops@example.com", "reason": "verified in Feishu"}]
    assert json.loads(capsys.readouterr().out)["comment_reply_card_adoption"]["applied"] is True


def test_comment_reply_adopt_card_rejects_missing_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _runtime(monkeypatch)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["comment-reply-adopt-card", "--reply-id", "44", "--message-id", "msg-1", "--chat-id", "chat-1", "--operator", "ops"])
    assert exc_info.value.code == 2
