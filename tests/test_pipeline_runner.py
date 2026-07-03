from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import storage.models  # noqa: F401
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import create_app
from apps.cli import main as cli_main
from collectors import (
    CollectedComment,
    CollectedContent,
    CollectedProfile,
    CollectedSearchResult,
    CommentPage,
    MockPlatformAdapter,
    PageCursor,
    SearchPage,
)
from services.pipeline_runner import ANALYSIS_VERSION, PipelineRunner, _entity_fingerprint
from storage.database import Base, get_session
from storage.models import AnalysisProcessingState, Comment, Content, DiscoveryRelation, PipelineRun, PublicProfile, Query


@pytest.fixture()
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield SessionLocal
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_pipeline_runner_mock_full_cycle(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    runner = _runner(factory, tmp_path, adapter=MutableAdapter())

    payload = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")

    result = payload["result_data"]
    assert payload["status"] == "completed"
    assert result["queries"] == {"requested": 1, "completed": 1, "failed": 0}
    assert result["collection"]["contents_found"] == 1
    assert result["collection"]["new_contents"] == 1
    assert result["collection"]["new_comments"] == 2
    assert result["collection"]["new_profiles"] == 3
    assert result["processing"]["records_in_scope"] == 3
    assert result["processing"]["processed_records"] == 3
    assert result["processing"]["new_contents_processed"] == 1
    assert result["processing"]["new_comments_processed"] == 2
    assert result["processing"]["demand_events_created"] >= 1
    assert result["leads"]["leads_created"] >= 1
    assert result["leads"]["evidence_created"] >= 1
    assert result["intelligence"]["clusters_created_or_updated"] >= 1
    assert result["intelligence"]["candidate_queries_created"] >= 1
    assert result["intelligence"]["query_scores_updated"] == 1
    assert result["insight"]["content_insights"] is not None
    assert result["evidence"]
    assert result["evidence"][0]["source_entity_type"] in {"content", "comment"}
    assert result["analysis_metadata"]["rule_version"] == "pipeline_rules_v1"
    with factory() as session:
        run = session.get(PipelineRun, payload["run_id"])
        assert run is not None
        assert run.status == "completed"
        assert session.query(Content).count() == 1
        assert session.query(Comment).count() == 2
        assert session.query(PublicProfile).count() == 3


def test_pipeline_runner_is_idempotent_for_repeated_query(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    runner = _runner(factory, tmp_path)

    first = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")
    second = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")

    assert first["result_data"]["collection"]["new_contents"] == 1
    assert second["result_data"]["collection"]["new_contents"] == 0
    assert second["result_data"]["collection"]["existing_contents"] == 1
    assert second["result_data"]["collection"]["new_comments"] == 0
    with factory() as session:
        assert session.query(PipelineRun).count() == 2
        assert session.query(Content).count() == 1
        assert session.query(Comment).count() == 2
        relation_count = session.scalar(select(func.count()).select_from(Content).join(Content.discovery_relations))
        assert relation_count == 1


def test_pipeline_second_run_with_no_new_data_skips_analysis(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    adapter = MutableAdapter()
    runner = _runner(factory, tmp_path, adapter=adapter)

    first = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")
    second = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")

    assert first["result_data"]["processing"]["records_in_scope"] == 3
    assert second["result_data"]["processing"]["records_in_scope"] == 0
    assert second["result_data"]["processing"]["processed_records"] == 0
    assert second["result_data"]["analysis_scope"]["current_records"] == 0
    assert second["result_data"]["analysis_scope"]["historical_context_records"] == 0
    assert second["result_data"]["intelligence"]["candidate_queries_created"] == 0
    assert "No new or updated text records were available for analysis." in second["result_data"]["warnings"]
    with factory() as session:
        assert session.query(Content).count() == 1
        assert session.query(Comment).count() == 2


def test_pipeline_only_processes_new_comment(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    adapter = MutableAdapter()
    runner = _runner(factory, tmp_path, adapter=adapter)

    runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")
    adapter.comments["note-1"] = (*adapter.comments["note-1"], adapter.comment("comment-3", "价格多少，可以试听吗"))
    second = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")

    assert second["result_data"]["processing"]["records_in_scope"] == 1
    assert second["result_data"]["processing"]["new_comments_processed"] == 1
    assert second["result_data"]["processing"]["updated_contents_processed"] == 0
    assert second["result_data"]["analysis_scope"]["historical_context_records"] <= 50


def test_pipeline_reprocesses_updated_content_only(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    adapter = MutableAdapter()
    runner = _runner(factory, tmp_path, adapter=adapter)

    runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")
    adapter.contents["note-1"] = adapter.content("福州 PET 二刷更新", "正文更新：孩子压线，想找冲刺班。")
    second = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")

    assert second["result_data"]["processing"]["records_in_scope"] == 1
    assert second["result_data"]["processing"]["updated_contents_processed"] == 1
    assert second["result_data"]["processing"]["new_comments_processed"] == 0
    assert second["result_data"]["processing"]["updated_comments_processed"] == 0


def test_pipeline_analysis_version_change_reprocesses_scope(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    adapter = MutableAdapter()
    runner_v1 = _runner(factory, tmp_path, adapter=adapter)
    runner_v2 = _runner(factory, tmp_path, adapter=adapter, analysis_version="pipeline_rules_v2")

    runner_v1.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")
    second = runner_v2.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")

    assert second["result_data"]["processing"]["records_in_scope"] == 3
    assert second["result_data"]["analysis_metadata"]["analysis_version"] == "pipeline_rules_v2"
    with factory() as session:
        versions = set(session.scalars(select(AnalysisProcessingState.analysis_version)).all())
        assert versions == {ANALYSIS_VERSION, "pipeline_rules_v2"}


def test_pipeline_failure_does_not_mark_analysis_processed(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    adapter = MutableAdapter()
    runner = _runner(factory, tmp_path, adapter=adapter)

    failed = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test", fail_stage="clustering")
    assert failed["status"] == "failed"
    with factory() as session:
        assert session.query(AnalysisProcessingState).count() == 0
    retried = runner.retry_run(failed["run_id"], requested_by="test-retry")

    assert retried["result_data"]["processing"]["records_in_scope"] == 3
    assert retried["status"] == "completed"
    with factory() as session:
        assert session.query(AnalysisProcessingState).count() == 3


def test_pipeline_analysis_scope_is_bounded_with_large_history(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    adapter = MutableAdapter()
    _seed_historical_records(factory, query_id, content_count=1000, comments_per_content=3)
    runner = _runner(factory, tmp_path, adapter=adapter)

    payload = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")
    result = payload["result_data"]

    assert result["processing"]["records_in_scope"] == 3
    assert result["analysis_scope"]["historical_context_records"] <= 50
    assert result["analysis_scope"]["total_records_used"] <= 53
    assert result["database_totals"]["contents"] == 1001
    assert result["database_totals"]["comments"] == 3002


def test_pipeline_runner_records_failure_and_retry_continues(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    runner = _runner(factory, tmp_path)

    failed = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test", fail_stage="clustering")
    retried = runner.retry_run(failed["run_id"], requested_by="test-retry")

    assert failed["status"] == "failed"
    assert failed["progress_data"]["collection"] == "completed"
    assert failed["progress_data"]["clustering"] == "running"
    assert "simulated failure at stage: clustering" in failed["error_message"]
    assert retried["run_id"] == failed["run_id"]
    assert retried["status"] == "completed"
    assert retried["result_data"]["collection"]["new_contents"] == 0
    with factory() as session:
        assert session.query(Content).count() == 1
        assert session.query(Comment).count() == 2


def test_pipeline_api_and_cli_use_same_runner_shape(
    factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    query_id = _seed_query(factory, "admissions")
    monkeypatch.setenv("WORKER_ADAPTER", "mock")
    monkeypatch.setenv("OPS_TOKEN", "secret")

    def override_get_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        response = client.post(
            "/ops/api/pipeline/runs",
            headers={"X-Ops-Token": "secret"},
            json={"query_ids": [query_id], "collection_limit": 20, "requested_by": "api"},
        )
        status = client.get("/ops/api/runtime/status")
        latest = client.get("/ops/api/insights/latest")
        dashboard = client.get("/ops/api/dashboard/public")
        page = client.get("/ops")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    api_payload = response.json()
    assert api_payload["result_data"]["queries"]["requested"] == 1
    assert status.status_code == 200
    assert latest.status_code == 200
    assert dashboard.status_code == 200
    assert dashboard.json()["evidence"]
    assert dashboard.json()["analysis_metadata"]["rule_version"] == "pipeline_rules_v1"
    assert page.status_code == 200
    assert "今日机会总览" in page.text

    import apps.cli as cli

    monkeypatch.setattr(cli, "SessionLocal", factory)
    assert cli_main(["--json", "run-status", str(api_payload["run_id"])]) == 0
    cli_payload = capsys.readouterr().out
    assert f'"run_id": {api_payload["run_id"]}' in cli_payload


def _runner(
    factory: sessionmaker[Session],
    tmp_path: Path,
    *,
    adapter: object | None = None,
    analysis_version: str = ANALYSIS_VERSION,
) -> PipelineRunner:
    selected_adapter = adapter or MockPlatformAdapter()
    return PipelineRunner(
        session_factory=factory,
        adapter_factory=lambda: selected_adapter,
        snapshot_root=tmp_path,
        analysis_version=analysis_version,
    )


def _seed_query(factory: sessionmaker[Session], query_text: str) -> int:
    with factory() as session:
        query = Query(
            query_text=query_text,
            platform="xhs",
            query_type="seed",
            status="active",
            priority=10,
            source="test",
        )
        session.add(query)
        session.commit()
        return query.id


class MutableAdapter:
    platform = "xhs"

    def __init__(self) -> None:
        self.contents = {
            "note-1": self.content("福州 PET 二刷", "孩子 PET 压线，想找冲刺机构，价格多少？"),
        }
        self.comments = {
            "note-1": (
                self.comment("comment-1", "福州哪家机构比较靠谱？"),
                self.comment("comment-2", "可以约试听或者体验课吗"),
            )
        }
        self.profiles = {
            "author-1": CollectedProfile("xhs", "author-1", "作者", None, None, "福州", None),
            "parent-1": CollectedProfile("xhs", "parent-1", "家长1", None, None, "福州", None),
            "parent-2": CollectedProfile("xhs", "parent-2", "家长2", None, None, "福州", None),
            "parent-3": CollectedProfile("xhs", "parent-3", "家长3", None, None, "福州", None),
        }

    def content(self, title: str, body_text: str) -> CollectedContent:
        return CollectedContent(
            platform="xhs",
            platform_content_id="note-1",
            platform_author_id="author-1",
            content_type="note",
            title=title,
            body_text=body_text,
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            url="https://mock.xhs.local/note-1",
            region_text="福州",
            like_count=10,
            comment_count=len(self.comments.get("note-1", ())) if hasattr(self, "comments") else 2,
            collect_count=3,
        )

    def comment(self, comment_id: str, body_text: str) -> CollectedComment:
        author_id = {
            "comment-1": "parent-1",
            "comment-2": "parent-2",
            "comment-3": "parent-3",
        }.get(comment_id, "parent-1")
        return CollectedComment(
            platform="xhs",
            platform_comment_id=comment_id,
            platform_content_id="note-1",
            platform_author_id=author_id,
            parent_platform_comment_id=None,
            body_text=body_text,
            published_at=datetime(2026, 1, 2, tzinfo=UTC),
            like_count=1,
            reply_count=0,
            region_text="福州",
        )

    def search(self, query_text: str, *, cursor: str | None = None, limit: int = 20) -> SearchPage:
        content = self.contents["note-1"]
        item = CollectedSearchResult(
            platform=content.platform,
            platform_content_id=content.platform_content_id,
            platform_author_id=content.platform_author_id,
            content_type=content.content_type,
            title=content.title,
            body_text=content.body_text,
            published_at=content.published_at,
            url=content.url,
            region_text=content.region_text,
            like_count=content.like_count,
            comment_count=len(self.comments["note-1"]),
            collect_count=content.collect_count,
            rank_position=1,
            result_page=1,
        )
        return SearchPage(query_text=query_text, items=(item,), cursor=PageCursor())

    def get_content(self, platform_content_id: str) -> CollectedContent:
        return self.contents[platform_content_id]

    def list_comments(self, platform_content_id: str, *, cursor: str | None = None, limit: int = 20) -> CommentPage:
        return CommentPage(platform_content_id=platform_content_id, items=self.comments[platform_content_id][:limit], cursor=PageCursor())

    def get_profile(self, platform_user_id: str) -> CollectedProfile:
        return self.profiles[platform_user_id]


def _seed_historical_records(
    factory: sessionmaker[Session],
    query_id: int,
    *,
    content_count: int,
    comments_per_content: int,
) -> None:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="history-author", first_seen_at=datetime(2025, 1, 1, tzinfo=UTC))
        session.add(profile)
        session.flush()
        processed_at = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(content_count):
            content = Content(
                platform="xhs",
                platform_content_id=f"history-note-{index}",
                content_type="note",
                author_profile_id=profile.id,
                title=f"历史内容 {index}",
                body_text=f"历史 PET 二刷 需求 {index}",
                first_seen_at=processed_at,
                last_seen_at=processed_at,
            )
            session.add(content)
            session.flush()
            session.add(DiscoveryRelation(query_id=query_id, content_id=content.id, discovered_at=processed_at))
            session.add(
                AnalysisProcessingState(
                    entity_type="content",
                    entity_id=content.id,
                    analysis_version=ANALYSIS_VERSION,
                    source_updated_at=content.updated_at,
                    source_fingerprint=_entity_fingerprint("content", content),
                    processed_at=processed_at,
                )
            )
            for comment_index in range(comments_per_content):
                comment = Comment(
                    platform="xhs",
                    platform_comment_id=f"history-comment-{index}-{comment_index}",
                    content_id=content.id,
                    author_profile_id=profile.id,
                    body_text=f"历史评论 {index}-{comment_index} 价格 试听",
                    first_seen_at=processed_at,
                    last_seen_at=processed_at,
                )
                session.add(comment)
                session.flush()
                session.add(
                    AnalysisProcessingState(
                        entity_type="comment",
                        entity_id=comment.id,
                        analysis_version=ANALYSIS_VERSION,
                        source_updated_at=comment.updated_at,
                        source_fingerprint=_entity_fingerprint("comment", comment),
                        processed_at=processed_at,
                    )
                )
        session.commit()
