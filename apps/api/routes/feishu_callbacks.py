from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from collectors.xiaohongshu.dm import XiaohongshuDirectMessageSender
from integrations.feishu.im import FeishuIMClient
from integrations.feishu.llm_review import (
    LLMReviewCallbackError,
    apply_llm_review_callback,
    update_llm_review_card_from_callback,
)
from integrations.feishu.outreach import (
    OutreachCallbackError,
    apply_outreach_callback,
    create_outreach_for_valid_screening,
    is_outreach_callback,
)
from integrations.feishu.webhook import verify_callback_token, verify_webhook_signature
from services.outreach_generation import OpenAICompatibleOutreachGenerator
from storage.database import SessionLocal


router = APIRouter(prefix="/feishu/callback", tags=["feishu-callbacks"])
logger = logging.getLogger(__name__)


@router.post("/llm-review")
async def llm_review_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_lark_request_timestamp: Annotated[str | None, Header()] = None,
    x_lark_request_nonce: Annotated[str | None, Header()] = None,
    x_lark_signature: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    body = await request.body()
    if not _verify_signature(
        body=body,
        timestamp=x_lark_request_timestamp,
        nonce=x_lark_request_nonce,
        signature=x_lark_signature,
    ):
        logger.warning("Feishu LLM review callback rejected: invalid signature")
        raise HTTPException(status_code=401, detail="invalid Feishu signature")
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("Feishu LLM review callback rejected: invalid JSON payload")
        raise HTTPException(status_code=400, detail="invalid JSON payload") from exc
    if not isinstance(payload, dict):
        logger.warning("Feishu LLM review callback rejected: invalid payload type")
        raise HTTPException(status_code=400, detail="invalid payload")

    if payload.get("type") == "url_verification":
        if not verify_callback_token(payload, os.getenv("FEISHU_VERIFICATION_TOKEN")):
            logger.warning("Feishu LLM review callback rejected: invalid verification token")
            raise HTTPException(status_code=401, detail="invalid Feishu verification token")
        return {"challenge": payload.get("challenge")}

    if is_outreach_callback(payload):
        background_tasks.add_task(_apply_outreach_callback, payload)
        return {"code": 0, "msg": "accepted", "type": "outreach"}

    with SessionLocal() as session:
        try:
            result = apply_llm_review_callback(
                session,
                payload,
                client=None,
                verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN"),
            )
        except LLMReviewCallbackError as exc:
            logger.warning("Feishu LLM review callback rejected: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session.commit()
    background_tasks.add_task(_update_llm_review_card, payload)
    if result.applied and result.human_review_status == "valid":
        background_tasks.add_task(_create_outreach_after_valid_review, result.screening_result_id, payload)
    return {
        "code": 0,
        "msg": "success",
        "applied": result.applied,
        "duplicate": result.duplicate,
        "screening_result_id": result.screening_result_id,
        "human_review_status": result.human_review_status,
    }


def _update_llm_review_card(payload: dict[str, Any]) -> None:
    with SessionLocal() as session:
        try:
            update_llm_review_card_from_callback(
                session,
                payload,
                client=FeishuIMClient(),
                verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN"),
            )
        except Exception:
            logger.exception("Feishu LLM review card update failed after callback was applied")


def _create_outreach_after_valid_review(screening_result_id: int, payload: dict[str, Any]) -> None:
    chat_id = _chat_id_from_payload(payload) or os.getenv("FEISHU_LLM_REVIEW_CHAT_ID")
    if not chat_id:
        logger.warning("Cannot create outreach approval card: chat_id is missing")
        return
    with SessionLocal() as session:
        try:
            create_outreach_for_valid_screening(
                session,
                screening_id=screening_result_id,
                generator=OpenAICompatibleOutreachGenerator(),
                card_client=FeishuIMClient(),
                chat_id=chat_id,
            )
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Feishu outreach approval card creation failed")


def _apply_outreach_callback(payload: dict[str, Any]) -> None:
    sender = XiaohongshuDirectMessageSender()
    try:
        with SessionLocal() as session:
            try:
                apply_outreach_callback(
                    session,
                    payload,
                    card_client=FeishuIMClient(),
                    xhs_sender=sender,
                    verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN"),
                )
                session.commit()
            except OutreachCallbackError:
                session.rollback()
                logger.exception("Feishu outreach callback rejected")
            except Exception:
                session.rollback()
                logger.exception("Feishu outreach callback processing failed")
    finally:
        sender.close()


def _chat_id_from_payload(payload: dict[str, Any]) -> str | None:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    context = event.get("context") if isinstance(event.get("context"), dict) else {}
    value = context.get("open_chat_id") or event.get("chat_id")
    return str(value) if value else None


def _verify_signature(
    *,
    body: bytes,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
) -> bool:
    encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY")
    if not encrypt_key:
        return True
    if not timestamp or not nonce or not signature:
        return False
    return verify_webhook_signature(
        timestamp=timestamp,
        nonce=nonce,
        body=body,
        signature=signature,
        encrypt_key=encrypt_key,
    )
