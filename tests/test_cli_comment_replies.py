from __future__ import annotations

import json
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
