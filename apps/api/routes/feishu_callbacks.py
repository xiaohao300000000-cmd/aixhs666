from __future__ import annotations

import logging
import os
import time
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from integrations.feishu.comment_replies import enqueue_comment_reply_callback, is_comment_reply_callback
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
from integrations.feishu.webhook import decode_callback_payload, verify_callback_token, verify_webhook_signature
from services.outreach_generation import OpenAICompatibleOutreachGenerator
from services.customer_progression import promote_screening_customer
from services.feishu_customer_followup import push_customer_followup
from services.feishu_task_center import TaskCenterCallbackError, apply_task_center_callback, is_task_center_callback
from storage.database import SessionLocal
from storage.models import LeadScreeningResult


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
    started_at = time.monotonic()
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
        payload = decode_callback_payload(body, encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY"))
    except ValueError as exc:
        logger.warning("Feishu callback rejected while decoding payload: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    event_id, action_name = _callback_identity(payload)
    logger.info("Feishu callback received event_id=%s action=%s", event_id, action_name)

    if payload.get("type") == "url_verification":
        if not verify_callback_token(payload, os.getenv("FEISHU_VERIFICATION_TOKEN")):
            logger.warning("Feishu LLM review callback rejected: invalid verification token")
            raise HTTPException(status_code=401, detail="invalid Feishu verification token")
        return {"challenge": payload.get("challenge")}

    if is_task_center_callback(payload):
        verification_token = (os.getenv("FEISHU_VERIFICATION_TOKEN") or "").strip()
        with SessionLocal() as session:
            try:
                result = apply_task_center_callback(session, payload, verification_token=verification_token or None, client=None)
                session.commit()
            except (TaskCenterCallbackError, ValueError) as exc:
                session.rollback()
                logger.warning("Feishu task center callback rejected event_id=%s action=%s: %s", event_id, action_name, exc)
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception:
                session.rollback()
                logger.exception("Feishu task center callback failed event_id=%s action=%s", event_id, action_name)
                raise
        response = _card_callback_response(card=result.get("card"), content="任务已受理")
        _log_callback_accepted(started_at, event_id=event_id, action_name=action_name, callback_type="task_center")
        return response

    if is_comment_reply_callback(payload):
        verification_token = (os.getenv("FEISHU_VERIFICATION_TOKEN") or "").strip()
        if not verification_token:
            logger.error("Feishu comment reply callback rejected: FEISHU_VERIFICATION_TOKEN is not configured")
            raise HTTPException(status_code=503, detail="FEISHU_VERIFICATION_TOKEN is required for comment reply callbacks")
        try:
            result = enqueue_comment_reply_callback(
                SessionLocal,
                payload,
                verification_token=verification_token,
            )
        except ValueError as exc:
            logger.warning("Feishu comment reply callback rejected: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        background_tasks.add_task(_sync_comment_reply_followup, result.reply_id, result.status)
        _log_callback_accepted(started_at, event_id=event_id, action_name=action_name, callback_type="comment_reply")
        return _card_callback_response(content="操作已受理", card=getattr(result, "card", None))

    if is_outreach_callback(payload):
        background_tasks.add_task(_apply_outreach_callback, payload)
        _log_callback_accepted(started_at, event_id=event_id, action_name=action_name, callback_type="outreach")
        return _card_callback_response(content="操作已受理")

    with SessionLocal() as session:
        try:
            result = apply_llm_review_callback(
                session,
                payload,
                client=None,
                verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN"),
            )
            if result.applied and result.human_review_status == "valid":
                screening = session.get(LeadScreeningResult, result.screening_result_id)
                event_id, _ = _callback_identity(payload)
                promote_screening_customer(
                    session,
                    result.screening_result_id,
                    reviewer_id=screening.human_reviewer_id if screening is not None else None,
                    reason=screening.qualification_human_reason if screening is not None else None,
                    idempotency_key=f"feishu-review:{event_id}",
                )
        except LLMReviewCallbackError as exc:
            logger.warning("Feishu LLM review callback rejected: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session.commit()
    background_tasks.add_task(_update_llm_review_card, payload)
    if result.applied and result.human_review_status == "valid":
        background_tasks.add_task(_create_outreach_after_valid_review, result.screening_result_id, payload)
    _log_callback_accepted(started_at, event_id=event_id, action_name=action_name, callback_type="llm_review")
    return _card_callback_response(content="操作成功")


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


def _card_callback_response(*, content: str, card: dict[str, Any] | None = None) -> dict[str, Any]:
    response: dict[str, Any] = {"toast": {"type": "success", "content": content}}
    if card is not None:
        response["card"] = {"type": "raw", "data": card}
    return response


def _callback_identity(payload: dict[str, Any]) -> tuple[str, str]:
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    value = action.get("value") if isinstance(action.get("value"), dict) else {}
    event_id = str(header.get("event_id") or payload.get("event_id") or event.get("event_id") or "unknown")
    action_name = str(action.get("name") or value.get("action") or value.get("name") or "unknown")
    return event_id, action_name


def _log_callback_accepted(started_at: float, *, event_id: str, action_name: str, callback_type: str) -> None:
    elapsed_ms = round((time.monotonic() - started_at) * 1000, 1)
    logger.info(
        "Feishu callback accepted type=%s event_id=%s action=%s elapsed_ms=%s",
        callback_type,
        event_id,
        action_name,
        elapsed_ms,
    )


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
    with SessionLocal() as session:
        try:
            apply_outreach_callback(
                session,
                payload,
                card_client=FeishuIMClient(),
                verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN"),
            )
            session.commit()
        except OutreachCallbackError:
            session.rollback()
            logger.exception("Feishu outreach callback rejected")
        except Exception:
            session.rollback()
            logger.exception("Feishu outreach callback processing failed")


def _sync_comment_reply_followup(reply_id: int, status: str) -> None:
    try:
        push_customer_followup(SessionLocal, reply_id=reply_id)
    except Exception:
        logger.exception("Feishu customer followup sync failed for persisted comment reply status %s", status)


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
