from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from storage.models import CollectionTask, Lead, LeadEvidence, SkillRun, WorkerHeartbeat


REVIEW_STATUSES = ("new", "needs_enrichment", "watch", "information_insufficient")
RUNNING_SKILL_STATUSES = ("queued", "running", "cancelling")
WORKER_STALE_AFTER = timedelta(minutes=5)
DETAIL_LIMIT = 10


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized else None


def _lead_item(session: Session, lead: Lead) -> dict[str, Any]:
    evidence = session.scalar(
        select(LeadEvidence)
        .where(LeadEvidence.lead_id == lead.id)
        .order_by(LeadEvidence.score_contribution.desc(), LeadEvidence.id.asc())
        .limit(1)
    )
    return {
        "id": lead.id,
        "display_name": lead.profile.display_name or f"线索 #{lead.id}",
        "status": lead.status,
        "region_text": lead.region_text or lead.profile.region_text,
        "demand_type": lead.demand_type,
        "intent_stage": lead.intent_stage,
        "intent_score": lead.intent_score,
        "information_completeness": lead.information_completeness,
        "recommended_next_step": lead.recommended_next_step,
        "evidence_text": evidence.evidence_text if evidence else None,
        "updated_at": _iso(lead.updated_at),
    }


def _skill_run_item(run: SkillRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "skill_key": run.skill_key,
        "status": run.status,
        "current_stage": run.current_stage,
        "progress_current": run.progress_current,
        "progress_total": run.progress_total,
        "progress_percent": run.progress_percent,
        "error_message": run.error_message,
        "updated_at": _iso(run.updated_at),
    }


def _task_item(task: CollectionTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "task_type": task.task_type,
        "platform": task.platform,
        "target_id": task.target_id,
        "attempt_count": task.attempt_count,
        "max_attempts": task.max_attempts,
        "last_error": task.last_error,
        "finished_at": _iso(task.finished_at),
        "updated_at": _iso(task.updated_at),
    }


def _worker_item(worker: WorkerHeartbeat, *, now: datetime) -> dict[str, Any]:
    heartbeat = _as_utc(worker.last_heartbeat_at)
    is_stale = heartbeat is None or now - heartbeat > WORKER_STALE_AFTER
    return {
        "worker_id": worker.worker_id,
        "status": worker.status,
        "health": "stale" if is_stale else "healthy",
        "current_task_id": worker.current_task_id,
        "completed_task_count": worker.completed_task_count,
        "failed_task_count": worker.failed_task_count,
        "last_error": worker.last_error,
        "last_heartbeat_at": _iso(worker.last_heartbeat_at),
    }


def _next_action(
    *,
    failed_tasks: int,
    review_queue: int,
    running_skills: int,
) -> dict[str, str]:
    if failed_tasks:
        return {
            "kind": "inspect_failure",
            "title": "先处理失败任务",
            "description": f"当前有 {failed_tasks} 个失败任务需要确认原因和恢复方式。",
            "target": "/tasks",
        }
    if review_queue:
        return {
            "kind": "review_leads",
            "title": "开始审核待判断线索",
            "description": f"当前有 {review_queue} 条线索等待人工判断。",
            "target": "/leads",
        }
    if running_skills:
        return {
            "kind": "monitor_run",
            "title": "关注正在运行的任务",
            "description": f"当前有 {running_skills} 个 Skill Run 正在执行。",
            "target": "/tasks",
        }
    return {
        "kind": "none",
        "title": "当前没有紧急事项",
        "description": "系统队列平稳，可以检查 Campaign 或准备下一批任务。",
        "target": "/campaigns",
    }


def build_operator_workbench(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    generated_at = _as_utc(now) if now else _utc_now()
    assert generated_at is not None

    review_queue = session.scalar(select(func.count(Lead.id)).where(Lead.status.in_(REVIEW_STATUSES))) or 0
    running_skills = (
        session.scalar(select(func.count(SkillRun.id)).where(SkillRun.status.in_(RUNNING_SKILL_STATUSES))) or 0
    )
    failed_tasks = session.scalar(select(func.count(CollectionTask.id)).where(CollectionTask.status == "failed")) or 0

    leads = session.scalars(
        select(Lead)
        .where(Lead.status.in_(REVIEW_STATUSES))
        .order_by(Lead.intent_score.desc(), Lead.updated_at.desc(), Lead.id.desc())
        .limit(DETAIL_LIMIT)
    ).all()
    skill_runs = session.scalars(
        select(SkillRun)
        .where(SkillRun.status.in_(RUNNING_SKILL_STATUSES))
        .order_by(SkillRun.updated_at.desc(), SkillRun.id.desc())
        .limit(DETAIL_LIMIT)
    ).all()
    task_failures = session.scalars(
        select(CollectionTask)
        .where(CollectionTask.status == "failed")
        .order_by(CollectionTask.updated_at.desc(), CollectionTask.id.desc())
        .limit(DETAIL_LIMIT)
    ).all()
    workers = session.scalars(select(WorkerHeartbeat)).all()
    worker_items = [_worker_item(worker, now=generated_at) for worker in workers]
    stale_workers = sum(item["health"] == "stale" for item in worker_items)
    worker_items.sort(
        key=lambda item: (
            item["health"] != "stale",
            item["last_heartbeat_at"] or "",
        )
    )
    worker_items = worker_items[:DETAIL_LIMIT]

    return {
        "generated_at": generated_at.isoformat(),
        "attention": {
            "review_queue": review_queue,
            "running_skills": running_skills,
            "failed_tasks": failed_tasks,
            "stale_workers": stale_workers,
        },
        "lead_queue": [_lead_item(session, lead) for lead in leads],
        "skill_runs": [_skill_run_item(run) for run in skill_runs],
        "task_failures": [_task_item(task) for task in task_failures],
        "workers": worker_items,
        "next_action": _next_action(
            failed_tasks=failed_tasks,
            review_queue=review_queue,
            running_skills=running_skills,
        ),
    }
