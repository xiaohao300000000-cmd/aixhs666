from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
import pytest
import storage.models  # noqa: F401
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from integrations.feishu import (
    FeishuAPIError,
    FeishuClient,
    FeishuSettings,
    apply_phrase_review_callback,
    apply_signal_alert_callback,
    build_phrase_review_payload,
    build_webhook_body,
    send_interactive_card,
    verify_callback_token,
    verify_webhook_signature,
)
from storage.database import Base
from storage.models import CollectionEvent, Query


def test_feishu_client_dry_run_does_not_require_webhook_url() -> None:
    client = FeishuClient(settings=_settings(enabled=False, webhook_url=None))

    result = client.send_webhook({"msg_type": "interactive", "card": {"header": {}}})

    assert result.sent is False
    assert result.dry_run is True
    assert result.response_json is not None
    assert result.response_json["payload"]["msg_type"] == "interactive"


def test_send_interactive_card_posts_webhook_body() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"StatusCode": 0, "msg": "ok"})

    payload = build_phrase_review_payload({"candidate_id": "cand-1", "phrase": "二刷"})
    client = FeishuClient(
        settings=_settings(enabled=True, webhook_url="https://open.feishu.invalid/hook/secret-token"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = send_interactive_card(client, payload)

    assert result.sent is True
    assert result.status_code == 200
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body == build_webhook_body(payload)
    assert body["msg_type"] == "interactive"


def test_feishu_client_retries_server_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, json={"msg": "temporary"})
        return httpx.Response(200, json={"msg": "ok"})

    client = FeishuClient(
        settings=_settings(enabled=True, webhook_url="https://open.feishu.invalid/hook/secret-token", max_retries=1),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.send_webhook({"msg_type": "interactive"})

    assert result.sent is True
    assert attempts == 2


def test_feishu_client_masks_secret_on_non_retryable_error() -> None:
    client = FeishuClient(
        settings=_settings(enabled=True, webhook_url="https://open.feishu.invalid/hook/very-secret-token"),
        http_client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(400, json={"msg": "bad"}))),
    )

    with pytest.raises(FeishuAPIError) as exc_info:
        client.send_webhook({"msg_type": "interactive"})

    message = str(exc_info.value)
    assert "very-secret-token" not in message
    assert "bad" in message


def test_callback_token_and_signature_verification() -> None:
    assert verify_callback_token({"token": "expected"}, "expected") is True
    assert verify_callback_token({"token": "wrong"}, "expected") is False

    body = b'{"event": "callback"}'
    timestamp = "1782970000"
    nonce = "nonce"
    encrypt_key = "secret"
    expected = base64.b64encode(
        hmac.new(encrypt_key.encode("utf-8"), f"{timestamp}{nonce}".encode("utf-8") + body, hashlib.sha256).digest()
    ).decode("utf-8")

    assert (
        verify_webhook_signature(
            timestamp=timestamp,
            nonce=nonce,
            body=body,
            signature=expected,
            encrypt_key=encrypt_key,
        )
        is True
    )
    assert (
        verify_webhook_signature(
            timestamp=timestamp,
            nonce=nonce,
            body=body,
            signature="wrong",
            encrypt_key=encrypt_key,
        )
        is False
    )


def test_phrase_review_callback_records_approve_reject_and_convert_idempotently() -> None:
    with _session() as session:
        approve = apply_phrase_review_callback(session, _phrase_payload("evt-approve", "cand-1", "approve"), verification_token="token")
        reject = apply_phrase_review_callback(session, _phrase_payload("evt-reject", "cand-2", "reject"), verification_token="token")
        convert = apply_phrase_review_callback(
            session,
            _phrase_payload("evt-convert", "cand-3", "convert_to_query", query_text="福州 PET 二刷"),
            verification_token="token",
        )
        duplicate = apply_phrase_review_callback(
            session,
            _phrase_payload("evt-convert", "cand-3", "convert_to_query", query_text="福州 PET 二刷"),
            verification_token="token",
        )

        assert approve.applied is True
        assert reject.applied is True
        assert convert.applied is True
        assert duplicate.duplicate is True
        assert duplicate.event_id == convert.event_id
        assert duplicate.query_id == convert.query_id

        events = session.scalars(select(CollectionEvent).order_by(CollectionEvent.id)).all()
        assert [event.event_data["review_status"] for event in events] == [
            "approved",
            "rejected",
            "converted_to_query",
        ]
        queries = session.scalars(select(Query)).all()
        assert len(queries) == 1
        assert queries[0].query_text == "福州 PET 二刷"
        assert queries[0].source == "feishu_phrase_review"


def test_signal_alert_callback_is_idempotent() -> None:
    with _session() as session:
        first = apply_signal_alert_callback(session, _alert_payload("evt-alert", "alert-1", "keep"), verification_token="token")
        duplicate = apply_signal_alert_callback(session, _alert_payload("evt-alert", "alert-1", "keep"), verification_token="token")

        assert first.applied is True
        assert duplicate.duplicate is True
        assert duplicate.event_id == first.event_id
        assert len(session.scalars(select(CollectionEvent)).all()) == 1


def test_callback_rejects_invalid_verification_token() -> None:
    with _session() as session:
        with pytest.raises(ValueError, match="invalid Feishu verification token"):
            apply_phrase_review_callback(session, _phrase_payload("evt-1", "cand-1", "approve"), verification_token="expected")


def _settings(
    *,
    enabled: bool,
    webhook_url: str | None,
    max_retries: int = 0,
) -> FeishuSettings:
    return FeishuSettings(
        enabled=enabled,
        webhook_url=webhook_url,
        app_id=None,
        app_secret=None,
        verification_token=None,
        encrypt_key=None,
        timeout_seconds=0.1,
        max_retries=max_retries,
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _phrase_payload(event_id: str, candidate_id: str, action: str, *, query_text: str | None = None) -> dict:
    value = {"candidate_id": candidate_id, "action": action, "phrase": "二刷"}
    if query_text:
        value["query_text"] = query_text
    return {
        "token": "token",
        "header": {"event_id": event_id},
        "event": {
            "operator": {"open_id": "reviewer-1"},
            "action": {"value": value},
        },
    }


def _alert_payload(event_id: str, alert_id: str, action: str) -> dict:
    return {
        "token": "token",
        "header": {"event_id": event_id},
        "event": {
            "operator": {"open_id": "reviewer-1"},
            "action": {"value": {"alert_id": alert_id, "action": action}},
        },
    }
