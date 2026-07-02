from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Protocol

from integrations.feishu.client import FeishuClient, FeishuSendResult
from integrations.feishu.phrase_review import FeishuPhraseReviewPayload
from integrations.feishu.signal_alerts import FeishuSignalAlertPayload


class InteractivePayload(Protocol):
    message_type: str
    card: dict[str, Any]


def build_webhook_body(payload: InteractivePayload) -> dict[str, Any]:
    return {"msg_type": payload.message_type, "card": payload.card}


def send_interactive_card(
    client: FeishuClient,
    payload: FeishuPhraseReviewPayload | FeishuSignalAlertPayload,
    *,
    dry_run: bool | None = None,
) -> FeishuSendResult:
    return client.send_webhook(build_webhook_body(payload), dry_run=dry_run)


def verify_callback_token(payload: dict[str, Any], verification_token: str | None) -> bool:
    if not verification_token:
        return True
    token = payload.get("token")
    if token is None and isinstance(payload.get("header"), dict):
        token = payload["header"].get("token")
    return hmac.compare_digest(str(token or ""), verification_token)


def verify_webhook_signature(
    *,
    timestamp: str,
    nonce: str,
    body: bytes,
    signature: str,
    encrypt_key: str | None,
) -> bool:
    if not encrypt_key:
        return True
    message = f"{timestamp}{nonce}".encode("utf-8") + body
    digest = hmac.new(encrypt_key.encode("utf-8"), message, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)
