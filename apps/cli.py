from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from apps.worker.main import load_adapter
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


if __name__ == "__main__":
    raise SystemExit(main())
