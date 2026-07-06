from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from apps.worker.main import load_adapter
from integrations.feishu.bitable import FeishuBitableClient
from services.agent_runtime import rank_leads_for_workbench, run_agent_cycle
from services.feishu_control_panel import ControlPanelRecord, LarkCliControlPanelClient, run_control_panel_once
from services.feishu_workbench import pull_workbench_feedback, sync_workbench_rows
from services.lead_generation import generate_leads_from_history, rebuild_auto_leads_from_history
from services.pipeline_runner import PipelineRunError, PipelineRunner
from storage.database import SessionLocal


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
    subparsers.add_parser("agent-run", help="Run agent-selected collection and sync-ready prioritization.")
    subparsers.add_parser("feishu-sync", help="Sync prioritized leads to Feishu Bitable.")
    subparsers.add_parser("feishu-pull-feedback", help="Pull Feishu Bitable status changes back into PostgreSQL.")
    control_panel = subparsers.add_parser("run-control-panel-once", help="Run one human-started Feishu control panel command.")
    control_panel.add_argument("--base-token", default=None, help="Feishu Base token for the control panel.")
    control_panel.add_argument("--table-id", default=None, help="Feishu table ID for the control panel.")
    return parser


def main(argv: list[str] | None = None) -> int:
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
        elif args.command == "agent-run":
            payload = run_agent_cycle(SessionLocal, runner)
        elif args.command == "feishu-sync":
            with SessionLocal() as session:
                rows = rank_leads_for_workbench(session)
                client = FeishuBitableClient()
                result = sync_workbench_rows(session, client, rows)
                session.commit()
                payload = {"feishu_sync": result.__dict__}
        elif args.command == "feishu-pull-feedback":
            with SessionLocal() as session:
                client = FeishuBitableClient()
                payload = {"feishu_feedback": pull_workbench_feedback(session, client)}
                session.commit()
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
