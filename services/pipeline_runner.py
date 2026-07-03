from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import Enum
import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.comment_collection import run_comment_task
from apps.worker.detail_collection import run_detail_task
from apps.worker.resume import start_partial_task
from apps.worker.search_collection import run_search_task
from collectors import PlatformAdapter
from intelligence.clustering import cluster_texts
from intelligence.content_insights import ContentInsightInput, generate_content_insights
from intelligence.demand_chain import DemandEventType, DemandTextRecord, build_demand_event_chains
from intelligence.phrase_discovery import discover_phrase_candidates
from intelligence.scoring import QuerySourceStats, ScoringTargetType, rank_query_sources
from intelligence.text_processing import process_text
from scheduler import TaskStatus, create_task
from services.lead_generation import generate_leads_for_profiles
from storage.models import AnalysisProcessingState, CollectionTask, Comment, Content, DiscoveryRelation, PipelineRun, PublicProfile
from storage.models import Query as StoredQuery


ANALYSIS_VERSION = "pipeline_rules_v1"
MAX_HISTORY_CONTEXT_PER_QUERY = 50
TERMINAL_PIPELINE_STATUSES = {"completed", "failed", "cancelled", "partial"}
DEFAULT_PROGRESS = {
    "collection": "pending",
    "processing": "pending",
    "demand_events": "pending",
    "clustering": "pending",
    "query_scoring": "pending",
    "insight": "pending",
}


class PipelineRunError(RuntimeError):
    pass


@dataclass(slots=True)
class PipelineScope:
    query_ids: set[int] = field(default_factory=set)
    content_ids: set[int] = field(default_factory=set)
    new_content_ids: set[int] = field(default_factory=set)
    updated_content_ids: set[int] = field(default_factory=set)
    comment_ids: set[int] = field(default_factory=set)
    new_comment_ids: set[int] = field(default_factory=set)
    updated_comment_ids: set[int] = field(default_factory=set)
    profile_ids: set[int] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class AnalysisTextRecord:
    source_id: str
    text: str
    platform: str
    profile_id: int | None
    occurred_at: datetime | None
    entity_type: str
    entity_id: int
    content_id: int | None
    comment_id: int | None


class PipelineRunner:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        adapter_factory: Callable[[], PlatformAdapter],
        snapshot_root: str | Path = ".runtime/storage-snapshots",
        analysis_version: str = ANALYSIS_VERSION,
    ) -> None:
        self.session_factory = session_factory
        self.adapter_factory = adapter_factory
        self.snapshot_root = Path(snapshot_root)
        self.analysis_version = analysis_version

    def run_cycle(
        self,
        *,
        query_ids: list[int] | None = None,
        all_enabled: bool = False,
        collection_limit: int = 20,
        skip_analysis: bool = False,
        dry_run: bool = False,
        requested_by: str = "pipeline",
        idempotency_key: str | None = None,
        fail_stage: str | None = None,
        run_id: int | None = None,
    ) -> dict[str, Any]:
        request_data = {
            "query_ids": query_ids or [],
            "all_enabled": all_enabled,
            "collection_limit": collection_limit,
            "skip_analysis": skip_analysis,
            "dry_run": dry_run,
            "fail_stage": fail_stage,
        }
        with self.session_factory() as session:
            run = self._get_or_create_run(
                session,
                run_id=run_id,
                requested_by=requested_by,
                request_data=request_data,
                idempotency_key=idempotency_key,
            )
            if run.status == "completed" and idempotency_key:
                return self._run_payload(run)
            queries = self._select_queries(session, query_ids=query_ids, all_enabled=all_enabled)
            if not queries:
                raise PipelineRunError("No queries selected. Provide --query-id or --all-enabled.")
            if dry_run:
                result = _empty_result(run.id, status="completed")
                result["queries"]["requested"] = len(queries)
                result["queries"]["completed"] = 0
                result["warnings"].append("dry-run: no collection or analysis was executed")
                self._finish_run(session, run, status="completed", result=result)
                session.commit()
                return self._run_payload(run)
            self._start_run(session, run)
            session.commit()
            run_id = run.id

        adapter = self.adapter_factory()
        try:
            with self.session_factory() as session:
                run = self._require_run(session, run_id)
                result = _empty_result(run.id, status="running")
                queries = self._select_queries(session, query_ids=query_ids, all_enabled=all_enabled)
                self._set_progress(session, run, "collection", "running")
                self._fail_if_requested("collection", fail_stage)
                collection_stats, scope = self._run_collection(
                    session,
                    adapter=adapter,
                    queries=queries,
                    collection_limit=collection_limit,
                    result=result,
                )
                queries_completed = collection_stats.pop("queries_completed", 0)
                queries_failed = collection_stats.pop("queries_failed", 0)
                result["collection"].update(collection_stats)
                result["queries"]["requested"] = len(queries)
                result["queries"]["completed"] = queries_completed
                result["queries"]["failed"] = queries_failed
                self._set_progress(session, run, "collection", "completed")

                if skip_analysis:
                    for stage in ("processing", "demand_events", "clustering", "query_scoring", "insight"):
                        self._set_progress(session, run, stage, "skipped")
                    result["warnings"].append("analysis skipped by request")
                else:
                    self._run_analysis(session, run=run, result=result, scope=scope, fail_stage=fail_stage)

                status = "completed" if not result["errors"] else "partial"
                result["status"] = status
                self._finish_run(session, run, status=status, result=result)
                session.commit()
                return self._run_payload(run)
        except Exception as exc:
            with self.session_factory() as session:
                run = self._require_run(session, run_id)
                result = dict(run.result_data or _empty_result(run.id, status="failed"))
                result["status"] = "failed"
                result.setdefault("errors", []).append(str(exc))
                self._finish_run(session, run, status="failed", result=result, error_message=str(exc))
                session.commit()
                return self._run_payload(run)
        finally:
            close = getattr(adapter, "close", None)
            if callable(close):
                close()

    def get_run(self, run_id: int) -> dict[str, Any]:
        with self.session_factory() as session:
            return self._run_payload(self._require_run(session, run_id))

    def retry_run(self, run_id: int, *, requested_by: str = "pipeline-retry") -> dict[str, Any]:
        with self.session_factory() as session:
            run = self._require_run(session, run_id)
            request_data = dict(run.request_data or {})
        return self.run_cycle(
            query_ids=list(request_data.get("query_ids") or []),
            all_enabled=bool(request_data.get("all_enabled")),
            collection_limit=int(request_data.get("collection_limit") or 20),
            skip_analysis=bool(request_data.get("skip_analysis")),
            dry_run=bool(request_data.get("dry_run")),
            requested_by=requested_by,
            fail_stage=None,
            run_id=run_id,
        )

    def cancel_run(self, run_id: int) -> dict[str, Any]:
        with self.session_factory() as session:
            run = self._require_run(session, run_id)
            if run.status in TERMINAL_PIPELINE_STATUSES:
                raise PipelineRunError(f"Cannot cancel pipeline run from status {run.status}")
            run.status = "cancelled"
            run.finished_at = _utc_now()
            run.error_message = "cancelled by request"
            session.commit()
            return self._run_payload(run)

    def status(self) -> dict[str, Any]:
        with self.session_factory() as session:
            latest = session.scalar(select(PipelineRun).order_by(PipelineRun.id.desc()).limit(1))
            return {
                "generated_at": _utc_now().isoformat(),
                "counts": {
                    "queries_active": session.scalar(select(func.count(StoredQuery.id)).where(StoredQuery.status == "active")) or 0,
                    "contents": session.scalar(select(func.count(Content.id))) or 0,
                    "comments": session.scalar(select(func.count(Comment.id))) or 0,
                    "profiles": session.scalar(select(func.count(PublicProfile.id))) or 0,
                    "pipeline_runs": session.scalar(select(func.count(PipelineRun.id))) or 0,
                },
                "latest_run": None if latest is None else self._run_payload(latest),
            }

    def latest_insights(self) -> dict[str, Any]:
        with self.session_factory() as session:
            run = session.scalar(
                select(PipelineRun)
                .where(PipelineRun.result_data.is_not(None))
                .order_by(PipelineRun.finished_at.desc().nullslast(), PipelineRun.id.desc())
                .limit(1)
            )
            if run is None:
                return {"latest_run": None, "insight": None}
            result = run.result_data or {}
            return {"latest_run": self._run_payload(run), "insight": result.get("insight")}

    def _run_collection(
        self,
        session: Session,
        *,
        adapter: PlatformAdapter,
        queries: list[StoredQuery],
        collection_limit: int,
        result: dict[str, Any],
    ) -> tuple[dict[str, int], PipelineScope]:
        before_content_ids = set(session.scalars(select(Content.id)).all())
        before_comment_ids = set(session.scalars(select(Comment.id)).all())
        before_profile_ids = set(session.scalars(select(PublicProfile.id)).all())
        found_platform_ids: set[str] = set()
        failed = 0
        completed = 0
        scope = PipelineScope(query_ids={query.id for query in queries if query.id is not None})

        for query in queries:
            try:
                task = create_task(
                    session,
                    task_type="search",
                    platform=query.platform,
                    target_id=query.query_text,
                    query_id=query.id,
                    priority=query.priority,
                    payload_json={"limit": collection_limit, "source": "pipeline"},
                    max_attempts=1,
                )
                self._run_task_to_end(session, task, adapter=adapter, task_type="search", limit=collection_limit)
                query.run_count = (query.run_count or 0) + 1
                query.last_run_at = _utc_now()
                completed += 1
            except Exception as exc:
                failed += 1
                result["errors"].append(f"query {query.id} collection failed: {exc}")
                continue

            content_rows = session.scalars(
                select(Content)
                .join(DiscoveryRelation, DiscoveryRelation.content_id == Content.id)
                .where(DiscoveryRelation.query_id == query.id)
                .order_by(DiscoveryRelation.discovered_at.desc())
                .limit(collection_limit)
            ).all()
            for content in content_rows:
                if content.id is not None:
                    scope.content_ids.add(content.id)
                if content.author_profile_id is not None:
                    scope.profile_ids.add(content.author_profile_id)
                found_platform_ids.add(content.platform_content_id)
                self._collect_detail_and_comments(session, content=content, adapter=adapter, limit=collection_limit, result=result)

        after_content_ids = set(session.scalars(select(Content.id)).all())
        after_comment_ids = set(session.scalars(select(Comment.id)).all())
        after_profile_ids = set(session.scalars(select(PublicProfile.id)).all())
        scope.content_ids.update(after_content_ids - before_content_ids)
        scope.comment_ids.update(after_comment_ids - before_comment_ids)
        scope.profile_ids.update(after_profile_ids - before_profile_ids)
        self._add_related_comments_and_profiles(session, scope)
        self._classify_analysis_scope(session, scope, before_content_ids=before_content_ids, before_comment_ids=before_comment_ids)
        new_contents = len(after_content_ids - before_content_ids)
        return (
            {
                "contents_found": len(found_platform_ids),
                "new_contents": new_contents,
                "updated_contents": len(scope.updated_content_ids),
                "existing_contents": max(len(found_platform_ids) - new_contents, 0),
                "new_comments": len(after_comment_ids - before_comment_ids),
                "updated_comments": len(scope.updated_comment_ids),
                "new_profiles": len(after_profile_ids - before_profile_ids),
                "duplicates": max(len(found_platform_ids) - new_contents, 0),
                "queries_completed": completed,
                "queries_failed": failed,
            },
            scope,
        )

    def _add_related_comments_and_profiles(self, session: Session, scope: PipelineScope) -> None:
        if scope.content_ids:
            comments = session.scalars(select(Comment).where(Comment.content_id.in_(scope.content_ids))).all()
            for comment in comments:
                if comment.id is not None:
                    scope.comment_ids.add(comment.id)
                if comment.author_profile_id is not None:
                    scope.profile_ids.add(comment.author_profile_id)
        if scope.comment_ids:
            comments = session.scalars(select(Comment).where(Comment.id.in_(scope.comment_ids))).all()
            for comment in comments:
                scope.content_ids.add(comment.content_id)
                if comment.author_profile_id is not None:
                    scope.profile_ids.add(comment.author_profile_id)

    def _classify_analysis_scope(
        self,
        session: Session,
        scope: PipelineScope,
        *,
        before_content_ids: set[int],
        before_comment_ids: set[int],
    ) -> None:
        for content in session.scalars(select(Content).where(Content.id.in_(scope.content_ids))).all() if scope.content_ids else []:
            if content.id in before_content_ids:
                if self._needs_analysis(session, entity_type="content", entity=content):
                    scope.updated_content_ids.add(content.id)
            else:
                scope.new_content_ids.add(content.id)
        for comment in session.scalars(select(Comment).where(Comment.id.in_(scope.comment_ids))).all() if scope.comment_ids else []:
            if comment.id in before_comment_ids:
                if self._needs_analysis(session, entity_type="comment", entity=comment):
                    scope.updated_comment_ids.add(comment.id)
            else:
                scope.new_comment_ids.add(comment.id)

    def _needs_analysis(self, session: Session, *, entity_type: str, entity: Content | Comment) -> bool:
        state = session.scalar(
            select(AnalysisProcessingState).where(
                AnalysisProcessingState.entity_type == entity_type,
                AnalysisProcessingState.entity_id == entity.id,
                AnalysisProcessingState.analysis_version == self.analysis_version,
            )
        )
        if state is None:
            return True
        return state.source_fingerprint != _entity_fingerprint(entity_type, entity)

    def _collect_detail_and_comments(
        self,
        session: Session,
        *,
        content: Content,
        adapter: PlatformAdapter,
        limit: int,
        result: dict[str, Any],
    ) -> None:
        try:
            detail_task = create_task(
                session,
                task_type="content_detail",
                platform=content.platform,
                target_id=content.platform_content_id,
                payload_json={"source": "pipeline"},
                max_attempts=1,
            )
            self._run_task_to_end(session, detail_task, adapter=adapter, task_type="detail", limit=limit)
        except Exception as exc:
            result["warnings"].append(f"detail collection skipped for {content.platform_content_id}: {exc}")
        try:
            comment_task = create_task(
                session,
                task_type="comments",
                platform=content.platform,
                target_id=content.platform_content_id,
                payload_json={"limit": limit, "source": "pipeline"},
                max_attempts=1,
            )
            self._run_task_to_end(session, comment_task, adapter=adapter, task_type="comments", limit=limit)
        except Exception as exc:
            result["warnings"].append(f"comment collection skipped for {content.platform_content_id}: {exc}")

    def _run_task_to_end(
        self,
        session: Session,
        task: CollectionTask,
        *,
        adapter: PlatformAdapter,
        task_type: str,
        limit: int,
    ) -> None:
        while True:
            task.status = TaskStatus.RUNNING.value
            task.worker_id = "pipeline-runner"
            task.started_at = _utc_now()
            task.finished_at = None
            session.flush()
            if task_type == "search":
                task = run_search_task(session, task=task, adapter=adapter, snapshot_root=self.snapshot_root, default_limit=limit)
            elif task_type == "detail":
                task = run_detail_task(session, task=task, adapter=adapter, snapshot_root=self.snapshot_root)
            elif task_type == "comments":
                task = run_comment_task(session, task=task, adapter=adapter, snapshot_root=self.snapshot_root, default_limit=limit)
            else:
                raise PipelineRunError(f"unsupported pipeline task type {task_type}")
            if task.status == TaskStatus.PARTIAL.value and task_type in {"search", "comments"}:
                task = start_partial_task(
                    session,
                    task_id=task.id,
                    worker_id="pipeline-runner",
                    allowed_task_types={task.task_type},
                )
                continue
            if task.status != TaskStatus.COMPLETED.value:
                raise PipelineRunError(f"{task.task_type} task {task.id} ended as {task.status}")
            return

    def _run_analysis(
        self,
        session: Session,
        *,
        run: PipelineRun,
        result: dict[str, Any],
        scope: PipelineScope,
        fail_stage: str | None,
    ) -> None:
        current_texts = self._text_records(
            session,
            content_ids=scope.new_content_ids | scope.updated_content_ids,
            comment_ids=scope.new_comment_ids | scope.updated_comment_ids,
        )
        historical_texts = (
            self._historical_context_records(
                session,
                scope=scope,
                exclude_source_ids={record.source_id for record in current_texts},
            )
            if current_texts
            else []
        )
        result["analysis_scope"] = {
            "current_records": len(current_texts),
            "historical_context_records": len(historical_texts),
            "total_records_used": len(current_texts) + len(historical_texts),
            "max_history_context_per_query": MAX_HISTORY_CONTEXT_PER_QUERY,
        }
        result["database_totals"] = self._database_totals(session)

        self._set_progress(session, run, "processing", "running")
        self._fail_if_requested("processing", fail_stage)
        processed = [process_text(record.text, source_id=record.source_id) for record in current_texts]
        low_info = sum(1 for item in processed if item.is_low_information)
        result["processing"].update(
            {
                "records_in_scope": len(current_texts),
                "processed_records": len(processed),
                "new_contents_processed": len(scope.new_content_ids),
                "updated_contents_processed": len(scope.updated_content_ids),
                "new_comments_processed": len(scope.new_comment_ids),
                "updated_comments_processed": len(scope.updated_comment_ids),
                "low_information_records": low_info,
            }
        )
        self._set_progress(session, run, "processing", "completed")

        if not current_texts:
            result["warnings"].append("No new or updated text records were available for analysis.")
            result["analysis_metadata"] = _analysis_metadata(self.analysis_version)
            result["insight"] = _empty_insight()
            result["evidence"] = []
            for stage in ("demand_events", "clustering", "query_scoring", "insight"):
                self._set_progress(session, run, stage, "completed")
            return

        self._set_progress(session, run, "demand_events", "running")
        self._fail_if_requested("demand_events", fail_stage)
        demand_records = [
            DemandTextRecord(
                public_profile_id=str(record.profile_id),
                platform=record.platform,
                text=record.text,
                occurred_at=record.occurred_at or _utc_now(),
                source_entity_type=record.entity_type,
                source_entity_id=str(record.entity_id),
                source_content_id=str(record.content_id) if record.content_id is not None else None,
                source_comment_id=str(record.comment_id) if record.comment_id is not None else None,
            )
            for record in current_texts
            if record.profile_id is not None
        ]
        chains = build_demand_event_chains(demand_records) if demand_records else []
        result["processing"]["demand_events_created"] = sum(
            1 for chain in chains for event in chain.events if event.event_type != DemandEventType.UNKNOWN
        )
        lead_result = generate_leads_for_profiles(session, set(scope.profile_ids))
        result["leads"] = lead_result.to_dict()
        self._set_progress(session, run, "demand_events", "completed")

        context_processed = [process_text(record.text, source_id=record.source_id) for record in historical_texts]
        normalized_texts = [
            item.normalized_text
            for item in (*processed, *context_processed)
            if item.normalized_text and not item.is_low_information
        ]
        self._set_progress(session, run, "clustering", "running")
        self._fail_if_requested("clustering", fail_stage)
        clusters = cluster_texts(normalized_texts) if normalized_texts else []
        existing_phrases = set(session.scalars(select(StoredQuery.query_text)).all())
        candidates = discover_phrase_candidates(normalized_texts, existing_phrases=existing_phrases, min_source_text_count=1)
        result["intelligence"]["clusters_created_or_updated"] = len(clusters)
        result["intelligence"]["candidate_queries_created"] = len(candidates)
        self._set_progress(session, run, "clustering", "completed")

        self._set_progress(session, run, "query_scoring", "running")
        self._fail_if_requested("query_scoring", fail_stage)
        scores = self._score_queries(session)
        result["intelligence"]["query_scores_updated"] = len(scores)
        self._set_progress(session, run, "query_scoring", "completed")

        self._set_progress(session, run, "insight", "running")
        self._fail_if_requested("insight", fail_stage)
        insight_inputs = [
            ContentInsightInput(text=item.normalized_text, occurred_at=_utc_now())
            for item in (*processed, *context_processed)
            if item.normalized_text and not item.is_low_information
        ]
        insight = generate_content_insights(insight_inputs, phrase_candidates=candidates)
        result["insight"] = {
            "demand_chains": [_to_jsonable(chain) for chain in chains[:20]],
            "clusters": [_to_jsonable(cluster) for cluster in clusters[:20]],
            "candidate_queries": [_to_jsonable(candidate) for candidate in candidates[:20]],
            "query_scores": [_to_jsonable(score) for score in scores[:20]],
            "content_insights": _to_jsonable(insight),
        }
        result["evidence"] = self._evidence_payload(current_texts, processed)
        result["analysis_metadata"] = _analysis_metadata(self.analysis_version)
        result["recommended_actions"] = _recommended_actions(candidates, scores)
        self._mark_analysis_processed(session, run_id=run.id, records=current_texts)
        self._set_progress(session, run, "insight", "completed")

    def _evidence_payload(self, texts: list[AnalysisTextRecord], processed: list[Any]) -> list[dict[str, Any]]:
        payload = []
        processed_by_source = {item.source_id: item for item in processed}
        for record in texts[:100]:
            processed_item = processed_by_source.get(record.source_id)
            payload.append(
                {
                    "source_id": record.source_id,
                    "platform": record.platform,
                    "source_entity_type": record.entity_type,
                    "source_entity_id": str(record.entity_id),
                    "source_content_id": str(record.content_id) if record.content_id is not None else None,
                    "source_comment_id": str(record.comment_id) if record.comment_id is not None else None,
                    "public_profile_id": str(record.profile_id) if record.profile_id is not None else None,
                    "occurred_at": _iso(record.occurred_at),
                    "evidence_text": record.text,
                    "normalized_text": processed_item.normalized_text if processed_item is not None else None,
                    "is_low_information": processed_item.is_low_information if processed_item is not None else None,
                    "low_info_reasons": [
                        reason.value if isinstance(reason, Enum) else str(reason)
                        for reason in (processed_item.low_info_reasons if processed_item is not None else ())
                    ],
                }
            )
        return payload

    def _text_records(
        self,
        session: Session,
        *,
        content_ids: set[int],
        comment_ids: set[int],
    ) -> list[AnalysisTextRecord]:
        records: list[AnalysisTextRecord] = []
        if content_ids:
            records.extend(
                _content_record(content)
                for content in session.scalars(select(Content).where(Content.id.in_(content_ids)).order_by(Content.id.asc())).all()
            )
        if comment_ids:
            records.extend(
                _comment_record(comment)
                for comment in session.scalars(select(Comment).where(Comment.id.in_(comment_ids)).order_by(Comment.id.asc())).all()
            )
        return [record for record in records if record.text]

    def _historical_context_records(
        self,
        session: Session,
        *,
        scope: PipelineScope,
        exclude_source_ids: set[str],
    ) -> list[AnalysisTextRecord]:
        records: list[AnalysisTextRecord] = []
        seen = set(exclude_source_ids)
        for query_id in sorted(scope.query_ids):
            query_records: list[AnalysisTextRecord] = []
            content_ids = list(
                session.scalars(
                    select(DiscoveryRelation.content_id)
                    .where(DiscoveryRelation.query_id == query_id)
                    .order_by(DiscoveryRelation.discovered_at.desc())
                    .limit(MAX_HISTORY_CONTEXT_PER_QUERY)
                )
            )
            if not content_ids:
                continue
            contents = session.scalars(select(Content).where(Content.id.in_(content_ids)).order_by(Content.id.desc())).all()
            comments = session.scalars(select(Comment).where(Comment.content_id.in_(content_ids)).order_by(Comment.id.desc())).all()
            for record in [*(_content_record(content) for content in contents), *(_comment_record(comment) for comment in comments)]:
                if record.source_id in seen or not record.text:
                    continue
                query_records.append(record)
                seen.add(record.source_id)
                if len(query_records) >= MAX_HISTORY_CONTEXT_PER_QUERY:
                    break
            records.extend(query_records)
        return records

    def _mark_analysis_processed(self, session: Session, *, run_id: int, records: list[AnalysisTextRecord]) -> None:
        processed_at = _utc_now()
        for record in records:
            entity = session.get(Content if record.entity_type == "content" else Comment, record.entity_id)
            if entity is None:
                continue
            state = session.scalar(
                select(AnalysisProcessingState).where(
                    AnalysisProcessingState.entity_type == record.entity_type,
                    AnalysisProcessingState.entity_id == record.entity_id,
                    AnalysisProcessingState.analysis_version == self.analysis_version,
                )
            )
            if state is None:
                state = AnalysisProcessingState(
                    entity_type=record.entity_type,
                    entity_id=record.entity_id,
                    analysis_version=self.analysis_version,
                    processed_at=processed_at,
                )
                session.add(state)
            state.source_updated_at = entity.updated_at
            state.source_fingerprint = _entity_fingerprint(record.entity_type, entity)
            state.processed_at = processed_at
            state.last_pipeline_run_id = run_id
        session.flush()

    def _database_totals(self, session: Session) -> dict[str, int]:
        return {
            "contents": session.scalar(select(func.count(Content.id))) or 0,
            "comments": session.scalar(select(func.count(Comment.id))) or 0,
            "profiles": session.scalar(select(func.count(PublicProfile.id))) or 0,
        }

    def _score_queries(self, session: Session) -> list[Any]:
        stats = []
        for query in session.scalars(select(StoredQuery).order_by(StoredQuery.id.asc())).all():
            content_ids = set(
                session.scalars(select(DiscoveryRelation.content_id).where(DiscoveryRelation.query_id == query.id)).all()
            )
            task_count = session.scalar(select(func.count(CollectionTask.id)).where(CollectionTask.query_id == query.id)) or 0
            failed_count = session.scalar(
                select(func.count(CollectionTask.id)).where(
                    CollectionTask.query_id == query.id,
                    CollectionTask.status == TaskStatus.FAILED.value,
                )
            ) or 0
            user_ids = set()
            expressions = set()
            for content in session.scalars(select(Content).where(Content.id.in_(content_ids))).all() if content_ids else []:
                if content.author_profile_id:
                    user_ids.add(content.author_profile_id)
                if content.body_text:
                    expressions.add(process_text(content.body_text).normalized_text.casefold())
            stats.append(
                QuerySourceStats(
                    target_type=ScoringTargetType.QUERY,
                    target_id=str(query.id),
                    label=query.query_text,
                    observed_content_count=len(content_ids),
                    new_content_count=len(content_ids),
                    duplicate_content_count=0,
                    observed_user_count=len(user_ids),
                    new_user_count=len(user_ids),
                    observed_expression_count=len(expressions),
                    new_expression_count=len(expressions),
                    task_count=task_count,
                    failed_task_count=failed_count,
                    context_completion_value=1.0 if content_ids else 0.0,
                )
            )
        return rank_query_sources(stats)

    def _select_queries(self, session: Session, *, query_ids: list[int] | None, all_enabled: bool) -> list[StoredQuery]:
        statement = select(StoredQuery)
        if query_ids:
            statement = statement.where(StoredQuery.id.in_(query_ids)).order_by(StoredQuery.priority.desc(), StoredQuery.id.asc())
        elif all_enabled:
            statement = statement.where(StoredQuery.status == "active").order_by(StoredQuery.priority.desc(), StoredQuery.id.asc())
        else:
            statement = statement.where(StoredQuery.status == "active").order_by(StoredQuery.priority.desc(), StoredQuery.id.asc()).limit(1)
        return list(session.scalars(statement).all())

    def _get_or_create_run(
        self,
        session: Session,
        *,
        run_id: int | None,
        requested_by: str,
        request_data: dict[str, Any],
        idempotency_key: str | None,
    ) -> PipelineRun:
        if run_id is not None:
            run = self._require_run(session, run_id)
            run.request_data = request_data
            run.progress_data = dict(DEFAULT_PROGRESS)
            run.result_data = None
            run.error_message = None
            return run
        if idempotency_key:
            existing = session.scalar(select(PipelineRun).where(PipelineRun.idempotency_key == idempotency_key))
            if existing is not None:
                return existing
        run = PipelineRun(
            status="pending",
            requested_by=requested_by,
            request_data=request_data,
            progress_data=dict(DEFAULT_PROGRESS),
            result_data=None,
            idempotency_key=idempotency_key,
        )
        session.add(run)
        session.flush()
        return run

    def _start_run(self, session: Session, run: PipelineRun) -> None:
        run.status = "running"
        run.started_at = _utc_now()
        run.finished_at = None
        run.progress_data = dict(DEFAULT_PROGRESS)
        run.error_message = None
        session.flush()

    def _finish_run(
        self,
        session: Session,
        run: PipelineRun,
        *,
        status: str,
        result: dict[str, Any],
        error_message: str | None = None,
    ) -> None:
        result["run_id"] = run.id
        result["status"] = status
        result["started_at"] = _iso(run.started_at)
        result["finished_at"] = _utc_now().isoformat()
        run.status = status
        run.result_data = result
        run.finished_at = _utc_now()
        run.error_message = error_message
        session.flush()

    def _set_progress(self, session: Session, run: PipelineRun, stage: str, status: str) -> None:
        progress = dict(run.progress_data or DEFAULT_PROGRESS)
        progress[stage] = status
        run.progress_data = progress
        session.flush()
        session.commit()

    def _require_run(self, session: Session, run_id: int) -> PipelineRun:
        run = session.get(PipelineRun, run_id)
        if run is None:
            raise PipelineRunError(f"Pipeline run {run_id} was not found")
        return run

    def _run_payload(self, run: PipelineRun) -> dict[str, Any]:
        return {
            "run_id": run.id,
            "status": run.status,
            "requested_by": run.requested_by,
            "request_data": run.request_data or {},
            "progress_data": run.progress_data or {},
            "result_data": run.result_data,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "error_message": run.error_message,
            "idempotency_key": run.idempotency_key,
        }

    def _fail_if_requested(self, stage: str, fail_stage: str | None) -> None:
        if fail_stage == stage:
            raise PipelineRunError(f"simulated failure at stage: {stage}")


def _empty_result(run_id: int, *, status: str) -> dict[str, Any]:
    now = _utc_now().isoformat()
    return {
        "run_id": run_id,
        "status": status,
        "started_at": now,
        "finished_at": None,
        "queries": {"requested": 0, "completed": 0, "failed": 0},
        "collection": {
            "contents_found": 0,
            "new_contents": 0,
            "existing_contents": 0,
            "new_comments": 0,
            "new_profiles": 0,
            "duplicates": 0,
        },
        "processing": {
            "records_in_scope": 0,
            "processed_records": 0,
            "new_contents_processed": 0,
            "updated_contents_processed": 0,
            "new_comments_processed": 0,
            "updated_comments_processed": 0,
            "low_information_records": 0,
            "demand_events_created": 0,
        },
        "intelligence": {
            "clusters_created_or_updated": 0,
            "candidate_queries_created": 0,
            "query_scores_updated": 0,
        },
        "leads": {
            "leads_created": 0,
            "leads_updated": 0,
            "evidence_created": 0,
            "enrichment_tasks_created": 0,
            "qualified_leads": 0,
            "needs_enrichment_leads": 0,
        },
        "warnings": [],
        "errors": [],
        "recommended_actions": [],
        "insight": None,
        "evidence": [],
        "analysis_metadata": None,
        "analysis_scope": {
            "current_records": 0,
            "historical_context_records": 0,
            "total_records_used": 0,
            "max_history_context_per_query": MAX_HISTORY_CONTEXT_PER_QUERY,
        },
        "database_totals": {
            "contents": 0,
            "comments": 0,
            "profiles": 0,
        },
    }


def _recommended_actions(candidates: list[Any], scores: list[Any]) -> list[str]:
    actions = []
    if candidates:
        actions.append(f"review {len(candidates)} candidate queries")
    if scores:
        top = scores[0]
        actions.append(f"prioritize query {top.target_id}: {top.label}")
    return actions


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, Counter):
        return dict(value)
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _content_record(content: Content) -> AnalysisTextRecord:
    return AnalysisTextRecord(
        source_id=f"content:{content.id}",
        text=" ".join(part for part in (content.title, content.body_text) if part),
        platform=content.platform,
        profile_id=content.author_profile_id,
        occurred_at=content.published_at or content.first_seen_at,
        entity_type="content",
        entity_id=content.id,
        content_id=content.id,
        comment_id=None,
    )


def _comment_record(comment: Comment) -> AnalysisTextRecord:
    return AnalysisTextRecord(
        source_id=f"comment:{comment.id}",
        text=comment.body_text or "",
        platform=comment.platform,
        profile_id=comment.author_profile_id,
        occurred_at=comment.published_at or comment.first_seen_at,
        entity_type="comment",
        entity_id=comment.id,
        content_id=comment.content_id,
        comment_id=comment.id,
    )


def _entity_fingerprint(entity_type: str, entity: Content | Comment) -> str:
    if entity_type == "content":
        value = "\n".join(
            (
                entity.title or "",
                entity.body_text or "",
            )
        )
    else:
        value = "\n".join(
            (
                entity.body_text or "",
                str(entity.parent_comment_id or ""),
            )
        )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _analysis_metadata(analysis_version: str) -> dict[str, Any]:
    return {
        "analysis_version": analysis_version,
        "rule_version": analysis_version,
        "text_processing_version": "text_processing_v1",
        "demand_chain_version": "demand_chain_v1",
        "clustering_version": "semantic_clustering_v1",
        "phrase_discovery_version": "phrase_discovery_v1",
        "query_scoring_version": "query_source_scoring_v1",
        "content_insight_version": "content_insights_v1",
        "ai_provider": "none",
        "prompt_version": None,
        "generated_at": _utc_now().isoformat(),
    }


def _empty_insight() -> dict[str, Any]:
    return {
        "demand_chains": [],
        "clusters": [],
        "candidate_queries": [],
        "query_scores": [],
        "content_insights": {
            "frequent_questions": [],
            "emerging_anxieties": [],
            "content_topics": [],
            "lead_magnet_topics": [],
            "live_stream_topics": [],
            "local_demand_differences": [],
        },
    }
