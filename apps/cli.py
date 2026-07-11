from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import sys
from typing import Any

from runtime_env import load_dotenv


ControlPanelRecord: Any = None
FeishuBitableClient: Any = None
FeishuIMClient: Any = None
LarkCliControlPanelClient: Any = None
PipelineRunError: Any = None
PipelineRunner: Any = None
SessionLocal: Any = None
generate_leads_from_history: Any = None
load_adapter: Any = None
pull_workbench_feedback: Any = None
rank_leads_for_workbench: Any = None
rebuild_auto_leads_from_history: Any = None
run_agent_cycle: Any = None
run_control_panel_once: Any = None
select: Any = None
sync_workbench_rows: Any = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aixhs", description="Agent-neutral AIXHS runtime CLI.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show runtime status.")

    run_cycle = subparsers.add_parser("run-cycle", help="Run one collection and analysis cycle.")
    run_cycle.add_argument("--query-id", action="append", type=int, dest="query_ids", help="Query id to run.")
    run_cycle.add_argument("--all-enabled", action="store_true", help="Run all active queries.")
    run_cycle.add_argument("--collection-limit", type=int, default=20, help="Per-query collection limit.")
    run_cycle.add_argument("--skip-analysis", action="store_true", help="Skip analysis stages.")
    run_cycle.add_argument("--dry-run", action="store_true", help="Create a run record without collecting.")
    run_cycle.add_argument("--idempotency-key", default=None, help="Optional idempotency key.")

    run_status = subparsers.add_parser("run-status", help="Show a pipeline run.")
    run_status.add_argument("run_id", type=int)

    retry_run = subparsers.add_parser("retry-run", help="Retry a pipeline run.")
    retry_run.add_argument("run_id", type=int)

    insights = subparsers.add_parser("insights", help="Show insights.")
    insights.add_argument("--latest", action="store_true", help="Show latest insight output.")

    leads_backfill = subparsers.add_parser("leads-backfill", help="Generate leads from historical contents and comments.")
    leads_backfill.add_argument("--rebuild", action="store_true", help="Delete auto-status leads and regenerate from history.")
    llm_screen = subparsers.add_parser("leads-llm-screen", help="Screen historical contents and comments with an LLM.")
    llm_screen.add_argument(
        "--source",
        choices=("content", "comment", "all"),
        default="all",
        help="Source type to screen.",
    )
    llm_screen.add_argument("--source-id", action="append", type=int, dest="source_ids", help="Specific local source id to screen.")
    llm_screen.add_argument("--limit", type=int, default=None, help="Maximum number of records to screen.")
    llm_screen.add_argument("--reprocess", action="store_true", help="Re-run records that already have screening results.")
    subparsers.add_parser("agent-run", help="Run agent-selected collection and sync-ready prioritization.")
    subparsers.add_parser("feishu-sync", help="Sync prioritized leads to Feishu Bitable.")
    ai_review_sync = subparsers.add_parser("feishu-ai-review-sync", help="Sync DeepSeek screening results to Feishu AI review tables.")
    ai_review_sync.add_argument("--limit", type=int, default=None, help="Maximum screening results to sync.")
    subparsers.add_parser("feishu-pull-feedback", help="Pull Feishu Bitable status changes back into PostgreSQL.")
    llm_reviews = subparsers.add_parser("feishu-send-llm-reviews", help="Send pending LLM screening reviews as Feishu cards.")
    llm_reviews.add_argument("--chat-id", default=None, help="Feishu chat id that receives review cards.")
    llm_reviews.add_argument("--limit", type=int, default=10, help="Maximum cards to send.")
    lead_flow = subparsers.add_parser("lead-flow-once", help="Run one lead screening workflow step.")
    lead_flow.add_argument("--chat-id", default=None, help="Feishu chat id that receives review cards.")
    lead_flow.add_argument("--limit", type=int, default=1, help="Maximum records to move in this step.")
    lead_flow.add_argument(
        "--source",
        choices=("content", "comment", "all"),
        default="all",
        help="Source type to screen when the next step is LLM.",
    )
    lead_flow.add_argument("--source-id", action="append", type=int, dest="source_ids", help="Specific local source id to screen.")
    outreach = subparsers.add_parser("outreach-generate-once", help="Generate one Feishu outreach approval card for a valid screening.")
    outreach.add_argument("--screening-id", type=int, required=True, help="Lead screening result id already marked valid.")
    outreach.add_argument("--chat-id", default=None, help="Feishu chat id that receives the outreach approval card.")
    comment_reply = subparsers.add_parser("comment-reply-generate-once", help="Generate one Feishu comment reply approval card without sending to XHS.")
    comment_reply.add_argument("--screening-id", type=int, required=True, help="Valid comment screening result id.")
    comment_reply.add_argument("--chat-id", default=None, help="Feishu chat id that receives the comment reply approval card.")
    comment_followup = subparsers.add_parser("comment-reply-sync-followup", help="Retry customer followup sync for a persisted comment reply result.")
    comment_followup.add_argument("--reply-id", type=int, required=True, help="Persisted comment reply id to sync.")
    comment_reconcile = subparsers.add_parser("comment-reply-reconcile-stale", help="Mark stale card/send claims for operator reconciliation without retrying XHS.")
    comment_reconcile.add_argument("--reply-id", type=int, required=True, help="Comment reply id to reconcile.")
    comment_reconcile.add_argument("--card-timeout-seconds", type=_positive_integer, required=True, help="Minimum stale age for an unresolved card claim.")
    comment_reconcile.add_argument("--send-timeout-seconds", type=_positive_integer, required=True, help="Minimum stale age for an unresolved XHS send claim.")
    comment_adopt = subparsers.add_parser("comment-reply-adopt-card", help="Adopt a verified Feishu card after reconciliation without sending XHS.")
    comment_adopt.add_argument("--reply-id", type=int, required=True, help="Comment reply id to update.")
    comment_adopt.add_argument("--message-id", required=True, help="Verified Feishu message id.")
    comment_adopt.add_argument("--chat-id", required=True, help="Verified Feishu chat id.")
    comment_adopt.add_argument("--operator", required=True, help="Operator identity recorded in the audit trail.")
    comment_adopt.add_argument("--reason", required=True, help="Operator reason recorded in the audit trail.")
    control_panel = subparsers.add_parser("run-control-panel-once", help="Run one human-started Feishu control panel command.")
    control_panel.add_argument("--base-token", default=None, help="Feishu Base token for the control panel.")
    control_panel.add_argument("--table-id", default=None, help="Feishu table ID for the control panel.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    _load_runtime_dependencies()
    parser = build_parser()
    args = parser.parse_args(argv)
    runner = PipelineRunner(session_factory=SessionLocal, adapter_factory=lambda: load_adapter("xhs"))
    try:
        if args.command == "status":
            payload = runner.status()
        elif args.command == "run-cycle":
            payload = runner.run_cycle(
                query_ids=args.query_ids,
                all_enabled=args.all_enabled,
                collection_limit=args.collection_limit,
                skip_analysis=args.skip_analysis,
                dry_run=args.dry_run,
                requested_by="cli",
                idempotency_key=args.idempotency_key,
            )
        elif args.command == "run-status":
            payload = runner.get_run(args.run_id)
        elif args.command == "retry-run":
            payload = runner.retry_run(args.run_id, requested_by="cli-retry")
        elif args.command == "insights":
            payload = runner.latest_insights()
        elif args.command == "leads-backfill":
            with SessionLocal() as session:
                result = rebuild_auto_leads_from_history(session) if args.rebuild else generate_leads_from_history(session)
                session.commit()
                payload = {"leads": result.to_dict()}
        elif args.command == "leads-llm-screen":
            from services.llm_lead_screening import OpenAICompatibleLeadScreeningClient, run_llm_lead_screening

            source_types = {"content", "comment"} if args.source == "all" else {args.source}
            source_ids = set(args.source_ids) if args.source_ids else None
            with SessionLocal() as session:
                result = run_llm_lead_screening(
                    session,
                    client=OpenAICompatibleLeadScreeningClient(),
                    source_entity_types=source_types,
                    source_entity_ids=source_ids,
                    limit=args.limit,
                    reprocess=args.reprocess,
                )
                session.commit()
                payload = {"llm_lead_screening": result.to_dict()}
        elif args.command == "agent-run":
            payload = run_agent_cycle(SessionLocal, runner)
        elif args.command == "feishu-sync":
            with SessionLocal() as session:
                rows = rank_leads_for_workbench(session)
                client = FeishuBitableClient()
                result = sync_workbench_rows(session, client, rows)
                session.commit()
                payload = {"feishu_sync": result.__dict__}
        elif args.command == "feishu-ai-review-sync":
            from services.feishu_ai_review_sync import sync_feishu_ai_review_rows

            with SessionLocal() as session:
                result = sync_feishu_ai_review_rows(session, limit=args.limit)
                session.commit()
                payload = {"feishu_ai_review_sync": result.to_dict()}
        elif args.command == "feishu-pull-feedback":
            with SessionLocal() as session:
                client = FeishuBitableClient()
                payload = {"feishu_feedback": pull_workbench_feedback(session, client)}
                session.commit()
        elif args.command == "feishu-send-llm-reviews":
            import os

            from integrations.feishu.llm_review import send_pending_llm_review_cards

            chat_id = args.chat_id or os.getenv("FEISHU_LLM_REVIEW_CHAT_ID")
            if not chat_id:
                parser.error("feishu-send-llm-reviews requires --chat-id or FEISHU_LLM_REVIEW_CHAT_ID")
            with SessionLocal() as session:
                result = send_pending_llm_review_cards(
                    session,
                    client=FeishuIMClient(),
                    chat_id=chat_id,
                    limit=args.limit,
                )
                session.commit()
                payload = {"feishu_llm_reviews": result}
        elif args.command == "lead-flow-once":
            import os

            from integrations.feishu.llm_review import send_pending_llm_review_cards
            from services.lead_screening_flow import PENDING_FEISHU, advance_llm_done_to_pending_feishu, lead_screening_flow_stats
            from services.llm_lead_screening import OpenAICompatibleLeadScreeningClient, run_llm_lead_screening
            from storage.models import LeadScreeningResult

            source_types = {"content", "comment"} if args.source == "all" else {args.source}
            source_ids = set(args.source_ids) if args.source_ids else None
            with SessionLocal() as session:
                advanced = advance_llm_done_to_pending_feishu(session, limit=args.limit)
                if advanced["advanced"] > 0:
                    session.commit()
                    payload = {"lead_flow": {"step": "advance_to_pending_feishu", **advanced, **lead_screening_flow_stats(session)}}
                elif _has_pending_feishu(session, LeadScreeningResult, PENDING_FEISHU):
                    chat_id = args.chat_id or os.getenv("FEISHU_LLM_REVIEW_CHAT_ID")
                    if not chat_id:
                        parser.error("lead-flow-once requires --chat-id or FEISHU_LLM_REVIEW_CHAT_ID when sending Feishu cards")
                    result = send_pending_llm_review_cards(
                        session,
                        client=FeishuIMClient(),
                        chat_id=chat_id,
                        limit=args.limit,
                    )
                    session.commit()
                    payload = {"lead_flow": {"step": "feishu_send", **result, **lead_screening_flow_stats(session)}}
                else:
                    result = run_llm_lead_screening(
                        session,
                        client=OpenAICompatibleLeadScreeningClient(),
                        source_entity_types=source_types,
                        source_entity_ids=source_ids,
                        limit=args.limit,
                    )
                    session.commit()
                    payload = {"lead_flow": {"step": "llm", **result.to_dict(), **lead_screening_flow_stats(session)}}
        elif args.command == "outreach-generate-once":
            import os

            from integrations.feishu.outreach import create_outreach_for_valid_screening
            from services.outreach_generation import OpenAICompatibleOutreachGenerator

            chat_id = args.chat_id or os.getenv("FEISHU_LLM_REVIEW_CHAT_ID")
            if not chat_id:
                parser.error("outreach-generate-once requires --chat-id or FEISHU_LLM_REVIEW_CHAT_ID")
            with SessionLocal() as session:
                outreach = create_outreach_for_valid_screening(
                    session,
                    screening_id=args.screening_id,
                    generator=OpenAICompatibleOutreachGenerator(),
                    card_client=FeishuIMClient(),
                    chat_id=chat_id,
                )
                session.commit()
                payload = {
                    "outreach": {
                        "created": outreach is not None,
                        "outreach_id": outreach.id if outreach is not None else None,
                        "status": outreach.status if outreach is not None else None,
                        "feishu_message_id": outreach.feishu_message_id if outreach is not None else None,
                    }
                }
        elif args.command == "comment-reply-generate-once":
            import os

            from integrations.feishu.comment_replies import create_comment_reply_for_valid_screening
            from services.comment_reply_generation import OpenAICompatibleCommentReplyGenerator

            chat_id = args.chat_id or os.getenv("FEISHU_LLM_REVIEW_CHAT_ID")
            if not chat_id:
                parser.error("comment-reply-generate-once requires --chat-id or FEISHU_LLM_REVIEW_CHAT_ID")
            with SessionLocal() as session:
                reply = create_comment_reply_for_valid_screening(
                    session,
                    screening_id=args.screening_id,
                    generator=OpenAICompatibleCommentReplyGenerator(),
                    card_client=FeishuIMClient(),
                    chat_id=chat_id,
                )
                session.commit()
                payload = {
                    "comment_reply": {
                        "created": reply is not None,
                        "reply_id": reply.id if reply is not None else None,
                        "status": reply.status if reply is not None else None,
                        "feishu_message_id": reply.feishu_message_id if reply is not None else None,
                    }
                }
        elif args.command == "comment-reply-sync-followup":
            from services.feishu_customer_followup import push_customer_followup

            payload = {"comment_reply_followup": push_customer_followup(SessionLocal, reply_id=args.reply_id)}
        elif args.command == "comment-reply-reconcile-stale":
            from integrations.feishu.comment_replies import reconcile_stale_comment_reply

            result = reconcile_stale_comment_reply(
                SessionLocal,
                reply_id=args.reply_id,
                now=datetime.now(UTC),
                card_timeout=timedelta(seconds=args.card_timeout_seconds),
                send_timeout=timedelta(seconds=args.send_timeout_seconds),
            )
            payload = {"comment_reply_reconciliation": _comment_reply_result_payload(result)}
        elif args.command == "comment-reply-adopt-card":
            from integrations.feishu.comment_replies import adopt_reconciled_comment_reply_card

            result = adopt_reconciled_comment_reply_card(
                SessionLocal,
                reply_id=args.reply_id,
                message_id=args.message_id,
                chat_id=args.chat_id,
                operator=args.operator,
                reason=args.reason,
            )
            payload = {"comment_reply_card_adoption": _comment_reply_result_payload(result)}
        elif args.command == "run-control-panel-once":
            payload = {
                "control_panel": run_control_panel_once(
                    LarkCliControlPanelClient(base_token=args.base_token, table_id=args.table_id),
                    actions=_build_control_panel_actions(runner),
                )
            }
        else:
            parser.error(f"unknown command: {args.command}")
    except PipelineRunError as exc:
        _emit({"error": str(exc)}, as_json=args.json, stream=sys.stderr)
        return 2

    _emit(payload, as_json=args.json)
    return 0


def _load_runtime_dependencies() -> None:
    global ControlPanelRecord
    global FeishuBitableClient
    global FeishuIMClient
    global LarkCliControlPanelClient
    global PipelineRunError
    global PipelineRunner
    global SessionLocal
    global generate_leads_from_history
    global load_adapter
    global pull_workbench_feedback
    global rank_leads_for_workbench
    global rebuild_auto_leads_from_history
    global run_agent_cycle
    global run_control_panel_once
    global select
    global sync_workbench_rows

    from sqlalchemy import select as sqlalchemy_select

    from apps.worker.main import load_adapter as worker_load_adapter
    from integrations.feishu.bitable import FeishuBitableClient as BitableClient
    from integrations.feishu.im import FeishuIMClient as IMClient
    from services.agent_runtime import rank_leads_for_workbench as rank_rows
    from services.agent_runtime import run_agent_cycle as run_cycle
    from services.feishu_control_panel import ControlPanelRecord as PanelRecord
    from services.feishu_control_panel import LarkCliControlPanelClient as PanelClient
    from services.feishu_control_panel import run_control_panel_once as run_control_once
    from services.feishu_workbench import pull_workbench_feedback as pull_feedback
    from services.feishu_workbench import sync_workbench_rows as sync_rows
    from services.lead_generation import generate_leads_from_history as generate_leads
    from services.lead_generation import rebuild_auto_leads_from_history as rebuild_leads
    from services.pipeline_runner import PipelineRunError as RunError
    from services.pipeline_runner import PipelineRunner as Runner
    from storage.database import SessionLocal as session_factory

    _set_runtime_dependency("ControlPanelRecord", PanelRecord)
    _set_runtime_dependency("FeishuBitableClient", BitableClient)
    _set_runtime_dependency("FeishuIMClient", IMClient)
    _set_runtime_dependency("LarkCliControlPanelClient", PanelClient)
    _set_runtime_dependency("PipelineRunError", RunError)
    _set_runtime_dependency("PipelineRunner", Runner)
    _set_runtime_dependency("SessionLocal", session_factory)
    _set_runtime_dependency("generate_leads_from_history", generate_leads)
    _set_runtime_dependency("load_adapter", worker_load_adapter)
    _set_runtime_dependency("pull_workbench_feedback", pull_feedback)
    _set_runtime_dependency("rank_leads_for_workbench", rank_rows)
    _set_runtime_dependency("rebuild_auto_leads_from_history", rebuild_leads)
    _set_runtime_dependency("run_agent_cycle", run_cycle)
    _set_runtime_dependency("run_control_panel_once", run_control_once)
    _set_runtime_dependency("select", sqlalchemy_select)
    _set_runtime_dependency("sync_workbench_rows", sync_rows)


def _set_runtime_dependency(name: str, value: Any) -> None:
    if globals().get(name) is None:
        globals()[name] = value


def _emit(payload: dict[str, Any], *, as_json: bool, stream: Any | None = None) -> None:
    stream = stream or sys.stdout
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stream)
        return
    if "result_data" in payload and payload["result_data"]:
        result = payload["result_data"]
        print(f"run {payload['run_id']} {payload['status']}", file=stream)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), file=stream)
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=stream)


def _comment_reply_result_payload(result: Any) -> dict[str, Any]:
    return {
        "applied": result.applied,
        "duplicate": result.duplicate,
        "reply_id": result.reply_id,
        "status": result.status,
        "reconciliation_required": result.reconciliation_required,
    }


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer greater than zero") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _has_pending_feishu(session: Any, model: Any, status: str) -> bool:
    return session.scalar(select(model.id).where(model.workflow_status == status).limit(1)) is not None


def _build_control_panel_actions(runner: PipelineRunner) -> dict[str, Any]:
    def find_new_customers(record: ControlPanelRecord) -> dict[str, Any]:
        search_text = _single_text(record.fields.get("要找什么"))
        limit = _positive_int(record.fields.get("最多看多少条"), default=20)
        if search_text:
            with SessionLocal() as session:
                from storage.models import Query

                query = Query(
                    query_text=search_text,
                    platform="xhs",
                    query_type="search",
                    status="active",
                    priority=0,
                    source="feishu_control_panel",
                )
                session.add(query)
                session.commit()
                query_id = query.id
            run = runner.run_cycle(query_ids=[query_id], collection_limit=limit, requested_by="feishu-control-panel")
        else:
            run = runner.run_cycle(all_enabled=True, collection_limit=limit, requested_by="feishu-control-panel")
        return {"message": _run_summary("已经找完新客户", run)}

    def rebuild_customers(_record: ControlPanelRecord) -> dict[str, Any]:
        with SessionLocal() as session:
            result = rebuild_auto_leads_from_history(session)
            session.commit()
        return {"message": f"已经重新整理客户：新增 {result.created} 个，更新 {result.updated} 个，跳过 {result.skipped} 个"}

    def refresh_customer_table(_record: ControlPanelRecord) -> dict[str, Any]:
        with SessionLocal() as session:
            rows = rank_leads_for_workbench(session)
            result = sync_workbench_rows(session, FeishuBitableClient(), rows)
            session.commit()
        return {"message": f"客户表已刷新：新增 {result.created} 个，更新 {result.updated} 个，失败 {result.failed} 个"}

    def import_confirmations(_record: ControlPanelRecord) -> dict[str, Any]:
        with SessionLocal() as session:
            result = pull_workbench_feedback(session, FeishuBitableClient())
            session.commit()
        return {"message": f"确认结果已同步：更新 {result['updated']} 个，跳过 {result['skipped']} 个"}

    def check_status(_record: ControlPanelRecord) -> dict[str, Any]:
        status = runner.status()
        counts = status["counts"]
        return {
            "message": (
                f"系统正常。现在有 {counts.get('contents', 0)} 篇内容、{counts.get('comments', 0)} 条评论、"
                f"{counts.get('profiles', 0)} 个用户。"
            )
        }

    return {
        "找新客户": find_new_customers,
        "重新整理客户": rebuild_customers,
        "刷新客户表": refresh_customer_table,
        "同步确认结果": import_confirmations,
        "查看系统状态": check_status,
    }


def _run_summary(prefix: str, run: dict[str, Any]) -> str:
    result = run.get("result_data") or {}
    collection = result.get("collection") or {}
    contents_count = int(collection.get("new_contents", 0) or 0) + int(collection.get("updated_contents", 0) or 0)
    comments_count = int(collection.get("new_comments", 0) or 0) + int(collection.get("updated_comments", 0) or 0)
    return (
        f"{prefix}：找到内容 {contents_count} 条，"
        f"找到评论 {comments_count} 条。"
    )


def _single_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value)


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(float(_single_text(value)))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


if __name__ == "__main__":
    raise SystemExit(main())
