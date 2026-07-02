from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

from collectors import CollectedComment, CollectedContent
from integrations.feishu import build_phrase_review_payloads
from intelligence.comment_budget import build_comment_identity, evaluate_comment_budget
from intelligence.content_insights import ContentInsightInput, generate_content_insights
from intelligence.dashboard import (
    DailyDashboardMetric,
    DashboardInput,
    FieldCompletenessMetric,
    PhraseReviewMetric,
    QueryOutputMetric,
    build_dashboard_summary,
)
from intelligence.demand_chain import DemandTextRecord, build_demand_event_chains
from intelligence.event_calendar import EducationEvent, EventType, QueryInput, generate_event_priority_suggestions
from intelligence.phrase_discovery import discover_phrase_candidates
from intelligence.platform_evaluation import evaluate_platforms
from intelligence.scoring import QuerySourceStats, ScoringTargetType, score_query_source
from intelligence.signal_alerts import build_signal_alerts
from intelligence.source_pool import HighValueSourcePool
from intelligence.text_processing import process_texts
from apps.worker.source_pool import generate_high_value_sources
from apps.worker.phrase_review import prepare_feishu_phrase_review_payloads
from apps.worker.signal_alerts import prepare_feishu_signal_alert_payloads


NOW = datetime(2026, 7, 2, 10, 30, tzinfo=timezone.utc)


def main() -> None:
    content = CollectedContent(
        platform="xhs",
        platform_content_id="xhs-note-pet-fz-001",
        platform_author_id="author-fz-teacher",
        content_type="note",
        title="福州 PET 二刷压线后怎么选机构",
        body_text="五年级 PET 压线没过，暑假想冲刺二刷，家长最关心价格、试听和老师稳定性。",
        published_at=NOW - timedelta(hours=4),
        url="https://example.invalid/xhs-note-pet-fz-001",
        region_text="福州",
        like_count=188,
        comment_count=4,
        collect_count=73,
    )
    comments = (
        _comment("c1", "福州五年级 PET 二刷压线，求推荐机构，价格多少？", "parent-fz-1", "福州", 3),
        _comment("c2", "有没有试听课？孩子跟不上，暑假冲刺来得及吗？", "parent-fz-1", "福州", 2),
        _comment("c3", "厦门分班考来不及，英语跟不上怎么办？", "parent-xm-1", "厦门", 1),
        _comment("c4", "英孚英语不满意想退费，有没有避坑建议？", "parent-xm-2", "厦门", 4),
    )
    query_text = "福州 PET 二刷"

    processed = process_texts([(comment.platform_comment_id, comment.body_text) for comment in comments])
    budget_state = evaluate_comment_budget(tuple(build_comment_identity(comment) for comment in comments)).state
    pool = HighValueSourcePool(now=NOW)
    high_value_sources = generate_high_value_sources(pool=pool, content=content, comments=comments)
    source_score = score_query_source(
        QuerySourceStats(
            target_type=ScoringTargetType.SOURCE,
            target_id=content.platform_content_id,
            label=content.title or content.platform_content_id,
            observed_content_count=1,
            new_content_count=1,
            duplicate_content_count=0,
            observed_user_count=3,
            new_user_count=3,
            observed_expression_count=4,
            new_expression_count=3,
            task_count=2,
            failed_task_count=0,
            coverage_gap_value=0.8,
            context_completion_value=0.9,
            collection_cost=0.2,
        )
    )
    event = EducationEvent(
        name="福州 PET 暑假冲刺报名",
        event_type=EventType.REGISTRATION,
        region="福州",
        starts_at=NOW - timedelta(days=1),
        ends_at=NOW + timedelta(days=10),
        warmup_window=timedelta(days=14),
        cooldown_window=timedelta(days=3),
        query_terms=("PET", "二刷", "压线", "暑假", "报名"),
    )
    event_suggestions = generate_event_priority_suggestions(
        events=(event,),
        queries=(QueryInput(query_id="q-pet-fz", query_text=query_text, region="福州"),),
        now=NOW,
    )
    chains = build_demand_event_chains(
        [
            DemandTextRecord(
                public_profile_id=comment.platform_author_id or "unknown",
                platform=comment.platform,
                text=comment.body_text or "",
                occurred_at=comment.published_at or NOW,
                source_entity_type="comment",
                source_entity_id=comment.platform_comment_id,
                source_content_id=comment.platform_content_id,
                source_comment_id=comment.platform_comment_id,
            )
            for comment in comments
        ]
    )
    alerts = build_signal_alerts(
        chains=chains,
        event_suggestions=event_suggestions,
        source_scores=(source_score,),
        now=NOW,
    )
    alert_payloads = prepare_feishu_signal_alert_payloads(alerts[:3])
    phrases = discover_phrase_candidates(
        [content.body_text or "", *(comment.body_text or "" for comment in comments)],
        existing_phrases={"PET", "福州"},
        min_source_text_count=1,
        max_candidates=6,
    )
    phrase_payloads = prepare_feishu_phrase_review_payloads(phrases[:3])
    dashboard = build_dashboard_summary(
        DashboardInput(
            generated_at=NOW,
            daily_metrics=(
                DailyDashboardMetric(
                    metric_date=date(2026, 7, 2),
                    new_content_count=1,
                    new_comment_count=len(comments),
                    new_profile_count=3,
                    observed_content_count=1,
                    duplicate_content_count=0,
                ),
            ),
            query_outputs=(
                QueryOutputMetric(
                    query_id="q-pet-fz",
                    query_text=query_text,
                    new_content_count=1,
                    discovery_count=1,
                    task_count=2,
                    failed_task_count=0,
                ),
            ),
            source_scores=(source_score,),
            phrase_reviews=(PhraseReviewMetric(date(2026, 7, 2), pending_count=len(phrases[:3])),),
            field_completeness=(
                FieldCompletenessMetric("contents", "body_text", 1, 1),
                FieldCompletenessMetric("comments", "body_text", len(comments), len(comments)),
                FieldCompletenessMetric("comments", "region_text", len([c for c in comments if c.region_text]), len(comments)),
            ),
        )
    )
    insights = generate_content_insights(
        [
            ContentInsightInput(
                text=comment.body_text or "",
                occurred_at=comment.published_at or NOW,
                region=comment.region_text,
                source_score=0.8,
                candidate_phrases=tuple(candidate.phrase for candidate in phrases[:3]),
            )
            for comment in comments
        ],
        dashboard_summary=dashboard,
        phrase_candidates=phrases,
    )
    platform_report = evaluate_platforms()
    access_plan = platform_report.access_plan

    checks = {
        "processed_texts": len(processed) == 4 and any(item.fields.regions for item in processed),
        "dynamic_budget": budget_state.total_comment_count == 4,
        "source_pool": len(high_value_sources) >= 3,
        "source_score": source_score.task_value_score > 0.5,
        "event_priority": bool(event_suggestions) and event_suggestions[0].boost > 0,
        "demand_chains": len(chains) == 3,
        "signal_alerts": bool(alerts) and alert_payloads[0].message_type == "interactive",
        "phrase_review": bool(phrases) and phrase_payloads[0].message_type == "interactive",
        "dashboard": dashboard.totals.new_comment_count == 4 and dashboard.overall_field_completeness_rate > 0.8,
        "content_insights": bool(insights.content_topics) and bool(insights.local_demand_differences),
        "platform_evaluation": platform_report.recommended_platform and bool(access_plan.acceptance_metrics),
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise SystemExit(f"closed-loop checks failed: {failed}")

    report = {
        "status": "passed",
        "generated_at": NOW.isoformat(),
        "checks": checks,
        "summary": {
            "processed_text_count": len(processed),
            "high_value_source_count": len(high_value_sources),
            "top_alert": alerts[0].evidence_summary,
            "top_alert_score": alerts[0].ranking_score,
            "phrase_candidates": [candidate.phrase for candidate in phrases[:5]],
            "dashboard_duplicate_rate": dashboard.duplicate_rate,
            "content_topics": [item.title for item in insights.content_topics[:3]],
            "local_regions": [item.region for item in insights.local_demand_differences],
            "recommended_second_platform": platform_report.recommended_platform,
            "second_platform_plan_steps": access_plan.minimum_validation_steps,
        },
    }
    output_path = Path("orchestration/e2e/closed_loop_result.json")
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _comment(
    platform_comment_id: str,
    body_text: str,
    platform_author_id: str,
    region_text: str,
    like_count: int,
) -> CollectedComment:
    return CollectedComment(
        platform="xhs",
        platform_comment_id=platform_comment_id,
        platform_content_id="xhs-note-pet-fz-001",
        platform_author_id=platform_author_id,
        parent_platform_comment_id=None,
        body_text=body_text,
        published_at=NOW - timedelta(hours=2),
        like_count=like_count,
        reply_count=0,
        region_text=region_text,
    )


if __name__ == "__main__":
    main()
