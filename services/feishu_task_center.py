from __future__ import annotations

import os
from typing import Any

from sqlalchemy.orm import Session

from integrations.feishu.im import FeishuIMClient
from integrations.feishu.webhook import verify_callback_token
from services.feishu_ai_review_sync import DEFAULT_CUSTOMER_TABLE_ID, DEFAULT_EVIDENCE_TABLE_ID
from services.skill_registry import list_campaign_options
from services.skill_runtime import copy_skill_run, create_skill_run, preview_skill_run, queue_skill_run, request_skill_run_cancel, retry_skill_run, skill_run_result_view, update_skill_run_parameters
from storage.models import SkillRun, SkillRunEvent


class TaskCenterCallbackError(ValueError):
    pass


def _card(title: str, elements: list[dict[str, Any]], template: str = "blue") -> dict[str, Any]:
    return {"schema": "2.0", "config": {"update_multi": True, "width_mode": "default"}, "header": {"template": template, "title": {"tag": "plain_text", "content": title}}, "body": {"direction": "vertical", "padding": "12px", "elements": elements}}


def _button(text: str, name: str, *, primary: bool = False, form_submit: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {"tag": "button", "name": name, "text": {"tag": "plain_text", "content": text}, "type": "primary_filled" if primary else "default", "behaviors": [{"type": "callback", "value": {"action": name}}]}
    if form_submit:
        item["form_action_type"] = "submit"
    return item


def build_task_catalog_card() -> dict[str, Any]:
    return _card("飞书任务中心", [{"tag": "markdown", "content": "选择任务并按步骤填写参数、预览、运行和查看结果。\n\n**历史线索智能筛选**\n仅处理 PostgreSQL 中已有历史数据，不访问小红书，不发送评论或私信。"}, _button("创建任务", "skill_create_screen_historical_leads", primary=True)])


def build_task_form_card(run: SkillRun) -> dict[str, Any]:
    campaigns = list_campaign_options()
    elements = [{"tag": "markdown", "content": f"**任务 #{run.id}** · 历史线索智能筛选"}, {"tag": "form", "name": f"skill_form_{run.id}", "elements": [
        {"tag": "select_static", "name": "data_range", "placeholder": {"tag": "plain_text", "content": "数据范围"}, "required": True, "initial_option": "all", "options": [{"text": {"tag": "plain_text", "content": "全部历史数据"}, "value": "all"}, {"text": {"tag": "plain_text", "content": "最近30天"}, "value": "last_30_days"}, {"text": {"tag": "plain_text", "content": "最近90天"}, "value": "last_90_days"}]},
        {"tag": "select_static", "name": "source_types", "placeholder": {"tag": "plain_text", "content": "数据类型"}, "required": True, "initial_option": "content_and_comment", "options": [{"text": {"tag": "plain_text", "content": "帖子和评论"}, "value": "content_and_comment"}, {"text": {"tag": "plain_text", "content": "仅帖子"}, "value": "content_only"}, {"text": {"tag": "plain_text", "content": "仅评论"}, "value": "comment_only"}]},
        {"tag": "input", "name": "limit", "label": {"tag": "plain_text", "content": "处理数量（1-500）"}, "default_value": "50", "required": True},
        {"tag": "select_static", "name": "campaign_id", "placeholder": {"tag": "plain_text", "content": "Campaign"}, "required": True, "initial_option": campaigns[0].campaign_id, "options": [{"text": {"tag": "plain_text", "content": item.name}, "value": item.campaign_id} for item in campaigns]},
        _button("预览任务", f"skill_preview_{run.id}", primary=True, form_submit=True),
    ]}]
    return _card("历史线索智能筛选 - 填写参数", elements)


def build_skill_run_card(run: SkillRun) -> dict[str, Any]:
    view = skill_run_result_view(run)
    if run.status == "previewed":
        preview = view["preview"]
        return _card("任务预览", [{"tag": "markdown", "content": f"**任务 #{run.id}**\n候选数据：**{preview.get('candidate_count', 0)}** 条\n处理上限：{preview.get('limit')}\nCampaign：{preview.get('campaign_id')}\n\n确认后由独立 Worker 执行。"}, _button("确认运行", f"skill_confirm_{run.id}", primary=True), _button("复制任务", f"skill_copy_{run.id}")])
    if run.status == "failed":
        return _card("任务失败", [{"tag": "markdown", "content": f"**任务 #{run.id}**\n阶段：{run.current_stage or '-'}\n错误：{run.error_message or '未知错误'}\n\n请明确点击重试。"}, _button("重试", f"skill_retry_{run.id}", primary=True), _button("复制任务", f"skill_copy_{run.id}")], "red")
    if run.status == "succeeded":
        return _card(
            "任务完成",
            [
                {"tag": "markdown", "content": _business_report_text(run)},
                _button("查看结果", f"skill_result_{run.id}", primary=True),
                _button("复制任务", f"skill_copy_{run.id}"),
            ],
            "green",
        )
    cancellable = run.status in {"queued", "running", "cancel_requested"} and run.current_stage not in {"sync_feishu", "summarize"}
    elements = [{"tag": "markdown", "content": f"**任务 #{run.id}**\n状态：{run.status}\n当前阶段：{run.current_stage or '等待 Worker'}\n进度：{run.progress_current}/{run.progress_total}（{run.progress_percent}%）"}]
    if cancellable: elements.append(_button("取消任务", f"skill_cancel_{run.id}"))
    return _card("任务运行中" if run.status != "cancelled" else "任务已取消", elements, "orange" if run.status != "cancelled" else "grey")


def build_skill_result_card(run: SkillRun) -> dict[str, Any]:
    view = skill_run_result_view(run)
    result = view["result"]
    sync = result.get("feishu_sync", {})
    dry_run = int(sync.get("dry_run", 0) or 0)
    failed = int(sync.get("failed", 0) or 0)
    created = int(sync.get("created", 0) or 0)
    updated = int(sync.get("updated", 0) or 0)
    if dry_run:
        sync_text = f"⚠️ **未写入多维表格**：当前为 dry-run，预演 {dry_run} 条写入。"
    elif failed:
        sync_text = f"⚠️ **多维表格同步部分失败**：新增 {created} / 更新 {updated} / 失败 {failed}。"
    else:
        sync_text = f"✅ **已写入多维表格**：新增 {created} / 更新 {updated} / 失败 0。"
    parameters = view["parameters"]
    business_text = _business_report_text(run, include_destination=True)
    content = (
        f"**任务 #{run.id} · 历史线索智能筛选**\n"
        f"Campaign：{parameters.get('campaign_id', '-')}\n"
        f"处理上限：{parameters.get('limit', '-')}\n\n"
        f"{business_text}\n\n"
        f"{sync_text}{_result_links()}"
    )
    return _card("任务结果详情", [{"tag": "markdown", "content": content}, _button("复制任务", f"skill_copy_{run.id}", primary=True)], "green")


def _result_links() -> str:
    app_token = (os.getenv("FEISHU_BITABLE_APP_TOKEN") or "").strip()
    if not app_token:
        return ""
    customer_table = (os.getenv("FEISHU_AI_REVIEW_CUSTOMER_TABLE_ID") or DEFAULT_CUSTOMER_TABLE_ID).strip()
    evidence_table = (os.getenv("FEISHU_AI_REVIEW_EVIDENCE_TABLE_ID") or DEFAULT_EVIDENCE_TABLE_ID).strip()
    base_url = f"https://my.feishu.cn/base/{app_token}"
    return f"\n\n[打开 AI 筛选客户线索]({base_url}?table={customer_table}) · [打开证据明细]({base_url}?table={evidence_table})"


def _business_report_text(run: SkillRun, *, include_destination: bool = False) -> str:
    report = run.business_report_json or {}
    if not report:
        result = run.result_summary_json or {}
        return (
            f"**任务 #{run.id}**\n"
            f"处理数量：**{result.get('processed_count', 0)}**\n"
            f"有效需求：**{result.get('valid_demands', 0)}**\n"
            f"高意向客户：**{result.get('high_intent_customers', 0)}**\n"
            f"待确认数量：**{result.get('needs_confirmation', 0)}**"
        )
    counts = report.get("counts", {})
    queue = report.get("queue", {})
    next_action = report.get("next_action", {})
    lines = [
        f"**任务 #{run.id}**",
        str(report.get("conclusion") or "本次运行已完成。"),
        "",
        f"高优先级：{counts.get('priority_review', 0)}",
        f"普通候选：{counts.get('standard_review', 0)}",
        f"不确定候选：{counts.get('uncertain_review', 0)}",
        f"明确自动排除：{counts.get('automatic_exclusion', 0)}",
        f"今日审核队列：{queue.get('prepared', 0)}（质量控制 {queue.get('quality_control', 0)}）",
    ]
    if int(queue.get("emergency", 0) or 0):
        lines.append(f"紧急新增：{queue.get('emergency', 0)}")
    if include_destination:
        base = (report.get("destinations", {}) or {}).get("base", {}) or {}
        lines.append(f"数据去向：{base.get('detail') or base.get('status') or '保存在 PostgreSQL'}")
    lines.append(f"下一步：{next_action.get('label') or '审核本次候选'}")
    return "\n".join(lines)


def send_task_center_card(*, chat_id: str, client: FeishuIMClient | None = None) -> dict[str, str]:
    return (client or FeishuIMClient()).send_interactive_card(chat_id=chat_id, card=build_task_catalog_card())


def is_task_center_callback(payload: dict[str, Any]) -> bool:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    return _action_name(action).startswith("skill_")


def _action_name(action: dict[str, Any]) -> str:
    value = action.get("value") if isinstance(action.get("value"), dict) else {}
    return str(action.get("name") or value.get("action") or value.get("name") or "")


def apply_task_center_callback(session: Session, payload: dict[str, Any], *, verification_token: str | None, client: FeishuIMClient | None = None) -> dict[str, Any]:
    if not verify_callback_token(payload, verification_token): raise TaskCenterCallbackError("invalid Feishu verification token")
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    context = event.get("context") if isinstance(event.get("context"), dict) else {}
    name = _action_name(action)
    event_id = str((payload.get("header") or {}).get("event_id") or payload.get("event_id") or event.get("event_id") or event.get("token") or name)
    operator = event.get("operator") if isinstance(event.get("operator"), dict) else {}
    requested_by = operator.get("open_id")
    chat_id = context.get("open_chat_id")
    message_id = context.get("open_message_id")
    if name == "skill_create_screen_historical_leads":
        run = create_skill_run(session, requested_by=requested_by, idempotency_key=f"task-center:create:{event_id}", feishu_chat_id=chat_id, feishu_message_id=message_id)
        card = build_task_form_card(run)
    else:
        try: run_id = int(name.rsplit("_", 1)[1])
        except ValueError as exc: raise TaskCenterCallbackError("invalid task action") from exc
        run = session.get(SkillRun, run_id)
        if run is None: raise TaskCenterCallbackError("skill run not found")
        if run.feishu_message_id and message_id and run.feishu_message_id != message_id: raise TaskCenterCallbackError("message mismatch")
        if run.feishu_chat_id and chat_id and run.feishu_chat_id != chat_id: raise TaskCenterCallbackError("chat mismatch")
        key = f"task-center:{event_id}"
        duplicate = session.query(SkillRunEvent).filter(SkillRunEvent.event_key == key).first()
        if duplicate is not None:
            duplicate_run = session.get(SkillRun, duplicate.skill_run_id)
            if duplicate_run is not None:
                card = build_skill_run_card(duplicate_run)
                return {"accepted": True, "duplicate": True, "run_id": duplicate_run.id, "status": duplicate_run.status, "card": card, "update_token": event.get("token")}
        if name.startswith("skill_preview_"):
            form = action.get("form_value") if isinstance(action.get("form_value"), dict) else {}
            update_skill_run_parameters(session, run.id, {"data_range": form.get("data_range", "all"), "source_types": form.get("source_types", "content_and_comment"), "limit": int(form.get("limit", 50)), "campaign_id": form.get("campaign_id")})
            preview_skill_run(session, run.id, event_key=key)
        elif name.startswith("skill_confirm_"): queue_skill_run(session, run.id, event_key=key)
        elif name.startswith("skill_cancel_"): request_skill_run_cancel(session, run.id, event_key=key)
        elif name.startswith("skill_retry_"): retry_skill_run(session, run.id, event_key=key)
        elif name.startswith("skill_copy_"):
            run = copy_skill_run(session, run.id, requested_by=requested_by, event_key=key); run.feishu_chat_id = chat_id; run.feishu_message_id = message_id; card = build_task_form_card(run); session.flush(); return {"accepted": True, "run_id": run.id, "card": card, "update_token": event.get("token")}
        elif name.startswith("skill_result_"):
            card = build_skill_result_card(run)
            session.flush()
            if client is not None and event.get("token"): client.update_interactive_card(token=str(event["token"]), card=card)
            return {"accepted": True, "run_id": run.id, "status": run.status, "card": card, "update_token": event.get("token")}
        else:
            raise TaskCenterCallbackError("unsupported task action")
        card = build_skill_run_card(run)
    session.flush()
    if client is not None and event.get("token"): client.update_interactive_card(token=str(event["token"]), card=card)
    return {"accepted": True, "run_id": run.id, "status": run.status, "card": card, "update_token": event.get("token")}


def update_skill_run_message(session: Session, run_id: int, *, client: FeishuIMClient | None = None) -> None:
    run = session.get(SkillRun, run_id)
    if run is None or not run.feishu_message_id: return
    (client or FeishuIMClient()).patch_interactive_message(message_id=run.feishu_message_id, card=build_skill_run_card(run))
