from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Protocol

from Crypto.Cipher import AES

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
    message = f"{timestamp}{nonce}{encrypt_key}".encode("utf-8") + body
    expected = hashlib.sha256(message).hexdigest()
    return hmac.compare_digest(expected, signature)


def decode_callback_payload(body: bytes, *, encrypt_key: str | None) -> dict[str, Any]:
    try:
        envelope = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON payload") from exc
    if not isinstance(envelope, dict):
        raise ValueError("invalid payload")
    encrypted = envelope.get("encrypt")
    if not encrypted:
        return envelope
    if not encrypt_key:
        raise ValueError("FEISHU_ENCRYPT_KEY is required for encrypted callbacks")
    try:
        ciphertext = base64.b64decode(str(encrypted), validate=True)
        if len(ciphertext) <= AES.block_size or len(ciphertext) % AES.block_size != 0:
            raise ValueError("invalid encrypted callback payload")
        iv = ciphertext[: AES.block_size]
        key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
        plaintext = AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext[AES.block_size :])
        padding = plaintext[-1]
        if padding < 1 or padding > AES.block_size or plaintext[-padding:] != bytes([padding]) * padding:
            raise ValueError("invalid encrypted callback padding")
        payload = json.loads(plaintext[:-padding].decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid encrypted callback payload") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid encrypted callback payload")
    return payload
