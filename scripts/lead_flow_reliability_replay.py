from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import storage.models  # noqa: F401
from integrations.feishu.llm_review import FeishuSendUncertainError, send_pending_llm_review_cards
from services.lead_screening_flow import (
    LLM_DONE,
    PENDING_FEISHU,
    SEND_UNCERTAIN,
    SENT,
    advance_llm_done_to_pending_feishu,
    diagnose_lead_screening_workflow,
)
from services.llm_lead_screening import LeadScreeningContext, LLMLeadScreeningDecision, run_llm_lead_screening
from storage.database import Base
from storage.models import Comment, Content, LeadScreeningResult, PublicProfile


@dataclass(slots=True)
class CountingLLMClient:
    lock: Lock
    calls: dict[int, int]
    successes: dict[int, int]
    failures: set[int]

    def screen(self, context: LeadScreeningContext) -> LLMLeadScreeningDecision:
        with self.lock:
            self.calls[context.source_entity_id] = self.calls.get(context.source_entity_id, 0) + 1
        if context.source_entity_id in self.failures:
            self.failures.remove(context.source_entity_id)
            raise RuntimeError("injected LLM failure")
        with self.lock:
            self.successes[context.source_entity_id] = self.successes.get(context.source_entity_id, 0) + 1
        needs_review = context.source_entity_id % 3 != 0
        valuable = context.source_entity_id % 5 != 0
        return LLMLeadScreeningDecision(
            valuable=valuable,
            demand_type="course" if valuable else "none",
            intent_strength="high" if valuable else "low",
            judgment_evidence=("replay fake evidence",),
            confidence=0.88 if valuable else 0.9,
            reason="replay fake decision",
            review_required=needs_review,
            raw_json={"source_entity_id": context.source_entity_id},
            model_name="replay-fake-llm",
        )


@dataclass(slots=True)
class CountingFeishuClient:
    lock: Lock
    calls: dict[int, int]
    successes: dict[int, int]
    uncertain_results: dict[int, int]
    ordinary_failures: set[int]
    uncertain_failures: set[int]

    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        screening_id = _screening_id_from_card(card)
        with self.lock:
            self.calls[screening_id] = self.calls.get(screening_id, 0) + 1
        if screening_id in self.uncertain_failures:
            with self.lock:
                self.uncertain_results[screening_id] = self.uncertain_results.get(screening_id, 0) + 1
            raise FeishuSendUncertainError("injected Feishu uncertain result")
        if screening_id in self.ordinary_failures:
            self.ordinary_failures.remove(screening_id)
            raise RuntimeError("injected Feishu ordinary failure")
        with self.lock:
            self.successes[screening_id] = self.successes.get(screening_id, 0) + 1
        return {"message_id": f"om_replay_{screening_id}", "chat_id": chat_id}

    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}


def main() -> int:
    args = _parser().parse_args()
    rng = random.Random(args.seed)
    engine = create_engine(args.database_url, pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        raise SystemExit("lead flow reliability replay requires PostgreSQL")
    if args.reset_test_database:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    seeded = _seed_records(session_factory, count=args.records, rng=rng)
    llm_calls: dict[int, int] = {}
    llm_client = CountingLLMClient(lock=Lock(), calls=llm_calls, successes={}, failures=seeded["llm_failure_source_ids"])
    _run_llm_workers(session_factory, workers=args.llm_workers, limit=args.limit, client=llm_client)
    _advance_ready_records(session_factory, limit=args.records)

    feishu_calls: dict[int, int] = {}
    with session_factory() as session:
        pending_ids = session.scalars(
            select(LeadScreeningResult.id).where(LeadScreeningResult.workflow_status == PENDING_FEISHU).order_by(LeadScreeningResult.id.asc())
        ).all()
    ordinary_failures = set(rng.sample(pending_ids, min(len(pending_ids), max(1, int(len(pending_ids) * args.failure_rate)))))
    remaining = [item for item in pending_ids if item not in ordinary_failures]
    uncertain_failures = set(rng.sample(remaining, min(len(remaining), max(1, int(len(remaining) * args.uncertain_rate)))))
    feishu_client = CountingFeishuClient(
        lock=Lock(),
        calls=feishu_calls,
        successes={},
        uncertain_results={},
        ordinary_failures=ordinary_failures,
        uncertain_failures=uncertain_failures,
    )
    _run_feishu_workers(session_factory, workers=args.feishu_workers, limit=args.limit, client=feishu_client)

    safe_args = {**vars(args), "database_url": make_url(args.database_url).render_as_string(hide_password=True)}
    result = _summarize(
        session_factory,
        seeded=seeded,
        llm_calls=llm_calls,
        llm_successes=llm_client.successes,
        feishu_calls=feishu_calls,
        feishu_successes=feishu_client.successes,
        args=safe_args,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    engine.dispose()
    return 0 if result["duplicate_llm_calls"] == 0 and result["duplicate_feishu_calls"] == 0 else 1


def _run_llm_workers(session_factory: sessionmaker[Session], *, workers: int, limit: int, client: CountingLLMClient) -> None:
    def worker() -> None:
        while True:
            with session_factory() as session:
                result = run_llm_lead_screening(session, client=client, source_entity_types={"comment"}, limit=limit)
                session.commit()
            if result.screened + result.failed == 0:
                return

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(lambda _: worker(), range(workers)))


def _advance_ready_records(session_factory: sessionmaker[Session], *, limit: int) -> None:
    while True:
        with session_factory() as session:
            result = advance_llm_done_to_pending_feishu(session, limit=limit)
            session.commit()
        if result["advanced"] == 0:
            return


def _run_feishu_workers(session_factory: sessionmaker[Session], *, workers: int, limit: int, client: CountingFeishuClient) -> None:
    def worker() -> None:
        while True:
            with session_factory() as session:
                result = send_pending_llm_review_cards(session, client=client, chat_id="oc_replay", limit=limit)
                session.commit()
            if result["sent"] + result["failed"] == 0:
                return

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(lambda _: worker(), range(workers)))


def _seed_records(session_factory: sessionmaker[Session], *, count: int, rng: random.Random) -> dict[str, Any]:
    now = datetime.now(UTC)
    llm_failure_offsets = set(rng.sample(range(count), max(1, int(count * 0.05))))
    with session_factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id=f"replay-user-{now.timestamp()}", display_name="Replay 家长")
        session.add(profile)
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id=f"replay-note-{now.timestamp()}",
            content_type="note",
            author_profile_id=profile.id,
            title="Replay PET",
            body_text="Replay body",
        )
        session.add(content)
        session.flush()
        source_ids: list[int] = []
        llm_failure_source_ids: set[int] = set()
        for index in range(count):
            comment = Comment(
                platform="xhs",
                platform_comment_id=f"replay-comment-{now.timestamp()}-{index}",
                content_id=content.id,
                author_profile_id=profile.id,
                body_text=f"Replay comment {index} PET 试听 价格",
            )
            session.add(comment)
            session.flush()
            source_ids.append(comment.id)
            if index in llm_failure_offsets:
                llm_failure_source_ids.add(comment.id)
            if index % 25 == 0:
                session.add(
                    LeadScreeningResult(
                        platform="xhs",
                        source_entity_type="comment",
                        source_entity_id=comment.id,
                        comment_id=comment.id,
                        public_profile_id=profile.id,
                        workflow_status="reviewed",
                        review_status="needs_review",
                        human_review_status="valid",
                    )
                )
            elif index % 25 == 1:
                session.add(
                    LeadScreeningResult(
                        platform="xhs",
                        source_entity_type="comment",
                        source_entity_id=comment.id,
                        comment_id=comment.id,
                        public_profile_id=profile.id,
                        workflow_status=SENT,
                        review_status="needs_review",
                        feishu_message_id=f"om_existing_{index}",
                    )
                )
            elif index % 25 == 2:
                session.add(
                    LeadScreeningResult(
                        platform="xhs",
                        source_entity_type="comment",
                        source_entity_id=comment.id,
                        comment_id=comment.id,
                        public_profile_id=profile.id,
                        workflow_status=PENDING_FEISHU,
                        review_status="needs_review",
                    )
                )
            elif index % 25 == 3:
                session.add(
                    LeadScreeningResult(
                        platform="xhs",
                        source_entity_type="comment",
                        source_entity_id=comment.id,
                        comment_id=comment.id,
                        public_profile_id=profile.id,
                        workflow_status="sending",
                        review_status="needs_review",
                        attempt_count=2,
                        last_error="stale replay seed",
                        updated_at=now - timedelta(hours=2),
                    )
                )
        session.commit()
    return {"source_ids": source_ids, "llm_failure_source_ids": llm_failure_source_ids}


def _summarize(
    session_factory: sessionmaker[Session],
    *,
    seeded: dict[str, Any],
    llm_calls: dict[int, int],
    llm_successes: dict[int, int],
    feishu_calls: dict[int, int],
    feishu_successes: dict[int, int],
    args: dict[str, Any],
) -> dict[str, Any]:
    with session_factory() as session:
        status_counts = dict(session.execute(select(LeadScreeningResult.workflow_status, func.count()).group_by(LeadScreeningResult.workflow_status)).all())
        diagnostics = diagnose_lead_screening_workflow(session)
        total_screenings = session.scalar(select(func.count(LeadScreeningResult.id))) or 0
    duplicate_llm = {str(key): value for key, value in llm_successes.items() if value > 1}
    duplicate_feishu = {str(key): value for key, value in feishu_successes.items() if value > 1}
    return {
        "args": args,
        "seeded_records": len(seeded["source_ids"]),
        "total_screenings": total_screenings,
        "llm_calls": sum(llm_calls.values()),
        "feishu_calls": sum(feishu_calls.values()),
        "status_counts": status_counts,
        "success_count": status_counts.get(SENT, 0),
        "failure_count": status_counts.get(PENDING_FEISHU, 0) + status_counts.get("pending_llm", 0),
        "uncertain_count": status_counts.get(SEND_UNCERTAIN, 0),
        "duplicate_llm_calls": len(duplicate_llm),
        "duplicate_feishu_calls": len(duplicate_feishu),
        "duplicate_llm_samples": duplicate_llm,
        "duplicate_feishu_samples": duplicate_feishu,
        "stale_issue_count": diagnostics["issue_counts"]["stale_sending"],
        "diagnostics": diagnostics,
    }


def _screening_id_from_card(card: dict[str, Any]) -> int:
    for element in card.get("body", {}).get("elements", []):
        if not isinstance(element, dict) or element.get("tag") != "button":
            continue
        behaviors = element.get("behaviors") or []
        if behaviors and isinstance(behaviors[0], dict):
            value = behaviors[0].get("value") or {}
            if "screening_result_id" in value:
                return int(value["screening_result_id"])
    raise RuntimeError("screening_result_id missing from replay card")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay LLM to Feishu workflow reliability with fake transports.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--records", type=int, default=120)
    parser.add_argument("--llm-workers", type=int, default=2)
    parser.add_argument("--feishu-workers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--failure-rate", type=float, default=0.08)
    parser.add_argument("--uncertain-rate", type=float, default=0.05)
    parser.add_argument("--reset-test-database", action="store_true")
    parser.add_argument("--output", default=".runtime/lead-flow-reliability-result.json")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
